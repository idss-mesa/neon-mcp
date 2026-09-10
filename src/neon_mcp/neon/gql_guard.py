"""Guard rails for the ``neon_graphql`` escape hatch.

Only read-only queries against an allow-list of NEON root fields, at most one
introspection root (NEON rejects more as ``BadFaithIntrospection``), bounded
length and selection depth. Oversized responses are pruned by shortening the
largest list until they fit, reporting the elided paths.
"""

from __future__ import annotations

import json
import re
from typing import Any

from neon_mcp.errors import ToolError

ALLOWED_ROOTS: frozenset[str] = frozenset(
    {
        "products",
        "product",
        "demoProduct",
        "filterProducts",
        "sites",
        "site",
        "filterSites",
        "location",
        "locationHierarchy",
        "findLocations",
        "prototypeDatasets",
        "prototypeDataset",
        "__schema",
        "__type",
        "__typename",
    }
)

_STRING_RE = re.compile(r'"""(?:.|\n)*?"""|"(?:\\.|[^"\\])*"')
_COMMENT_RE = re.compile(r"#[^\n]*")
_NAME_RE = re.compile(r"[_A-Za-z][_0-9A-Za-z]*")


def _strip(query: str) -> str:
    return _COMMENT_RE.sub(" ", _STRING_RE.sub('""', query))


def _invalid(message: str, **details: Any) -> ToolError:
    return ToolError(
        "invalid_argument",
        message,
        details=details or None,
        hint="Read neon://reference/graphql-schema for the allowed shape.",
    )


def _skip_parens(text: str, i: int) -> int:
    depth = 0
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise _invalid("Unbalanced parentheses in the GraphQL query.")


def _root_fields(body: str) -> list[str]:
    """Top-level field names of a selection set body (aliases resolved)."""
    fields: list[str] = []
    i, depth = 0, 0
    while i < len(body):
        ch = body[i]
        if ch == "{":
            depth += 1
            i += 1
        elif ch == "}":
            depth -= 1
            i += 1
        elif ch == "(":
            i = _skip_parens(body, i)
        elif depth == 0 and (m := _NAME_RE.match(body, i)):
            name = m.group(0)
            j = m.end()
            while j < len(body) and body[j].isspace():
                j += 1
            if j < len(body) and body[j] == ":":  # alias: real field follows
                j += 1
                while j < len(body) and body[j].isspace():
                    j += 1
                m2 = _NAME_RE.match(body, j)
                if m2:
                    name = m2.group(0)
                    j = m2.end()
            if name == "on" or name.startswith("..."):
                i = j
                continue
            fields.append(name)
            i = j
        elif body.startswith("...", i):
            if depth == 0:
                raise _invalid(
                    "Fragment spreads are not allowed at the root of a neon_graphql query."
                )
            i += 3
        else:
            i += 1
    return fields


def check_query(
    query: str, *, max_chars: int, max_depth: int, allowed_roots: frozenset[str] = ALLOWED_ROOTS
) -> None:
    """Raise ``invalid_argument`` unless ``query`` is a safe read-only NEON query."""
    if len(query) > max_chars:
        raise _invalid(f"The query is longer than {max_chars} characters.", maxChars=max_chars)
    text = _strip(query).strip()
    if not text:
        raise _invalid("The query is empty.")
    if text.count("{") != text.count("}"):
        raise _invalid("Unbalanced braces in the GraphQL query.")

    depth = peak = 0
    for ch in text:
        if ch == "{":
            depth += 1
            peak = max(peak, depth)
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise _invalid("Unbalanced braces in the GraphQL query.")
    if peak > max_depth:
        raise _invalid(
            f"Selection depth {peak} exceeds the limit of {max_depth}.", maxDepth=max_depth
        )

    operations = 0
    roots: list[str] = []
    i = 0
    while i < len(text):
        if text[i].isspace() or text[i] == ",":
            i += 1
            continue
        if text[i] == "{":
            start = i
        else:
            m = _NAME_RE.match(text, i)
            if not m:
                raise _invalid("Could not parse the GraphQL document.")
            keyword = m.group(0)
            if keyword in ("mutation", "subscription"):
                raise _invalid("Only read-only queries are allowed (no mutation or subscription).")
            if keyword not in ("query", "fragment"):
                raise _invalid(f"Unexpected token {keyword!r} in the GraphQL document.")
            start = text.find("{", m.end())
            if start < 0:
                raise _invalid("Could not parse the GraphQL document.")
            j = m.end()
            while j < start:  # skip variable definitions with parentheses
                if text[j] == "(":
                    j = _skip_parens(text, j)
                else:
                    j += 1
            if keyword == "fragment":
                i = _block_end(text, start)
                continue
        end = _block_end(text, start)
        operations += 1
        roots.extend(_root_fields(text[start + 1 : end - 1]))
        i = end
    if operations == 0:
        raise _invalid("The document contains no query operation.")
    bad = sorted({r for r in roots if r not in allowed_roots})
    if bad:
        raise _invalid(
            f"Root field(s) {', '.join(bad)} are not allowed.",
            allowedRoots=sorted(allowed_roots),
        )
    introspection = sum(1 for r in roots if r in ("__schema", "__type"))
    if introspection > 1:
        raise _invalid("NEON allows a single __type or __schema per query.")


def _block_end(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise _invalid("Unbalanced braces in the GraphQL query.")


def _size(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _largest_list(obj: Any, path: str) -> tuple[list[Any] | None, str, int]:
    best: tuple[list[Any] | None, str, int] = (None, "", 0)
    if isinstance(obj, list):
        if len(obj) > 1:
            best = (obj, path, _size(obj))
        for idx, item in enumerate(obj):
            cand = _largest_list(item, f"{path}[{idx}]")
            if cand[2] > best[2]:
                best = cand
    elif isinstance(obj, dict):
        for key, value in obj.items():
            cand = _largest_list(value, f"{path}.{key}" if path else key)
            if cand[2] > best[2]:
                best = cand
    return best


def prune_to_budget(data: Any, max_bytes: int) -> tuple[Any, list[str]]:
    """Shorten the largest lists until ``data`` fits; return elided paths."""
    paths: dict[str, int] = {}
    guard = 0
    while _size(data) > max_bytes and guard < 10_000:
        guard += 1
        target, path, size = _largest_list(data, "data")
        if target is None or len(target) <= 1:
            break
        excess = _size(data) - max_bytes
        per_item = max(size // max(len(target), 1), 1)
        drop = min(max(excess // per_item + 1, 1), len(target) - 1)
        keep = len(target) - drop
        del target[keep:]
        paths[path] = keep
    return data, [f"{p}[{n}:]" for p, n in paths.items()]
