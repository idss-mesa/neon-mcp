# neon-mcp agent workflow

A five-call path from a question to cited data. Every result is compact JSON
with `page`, `notes`, `nextSteps` and `resolved`; follow `page.nextOffset`
before concluding a list is complete.

1. **Find the product** — `neon_search_products(query="breeding bird point counts")`.
   Free text is ANDed over names, keywords, themes and descriptions; a bare
   code (`DP1.10003.001`) short-circuits. Filters: `theme`, `science_team`
   (TIS, TOS, AIS, AOS, AOP), `site`, `domain_code`, `status` (default ACTIVE).
2. **Check availability (no token)** — `neon_get_availability(product="DP1.10003.001", domain_code="D01")`.
   Rows are month ranges `"2016-06/2025-06"`; `byRelease` separates released
   tags from `PROVISIONAL` months. Add `site` for one site, `start_month` /
   `end_month` to window it, `provisional="exclude"` to drop provisional data.
3. **List files (token)** — `neon_list_files(product="DP1.10003.001", site_codes=["HARV"], start_month="2023-06", kind="data")`.
   Returns NEON file names, sizes, MD5s and signed URLs that expire after
   about 7 days (`urlExpiresAt`). `detail="summary"` sizes a wide pull first.
4. **Download (stdio only)** — `neon_download_files(...)` with the same
   selectors writes under the configured download directory, verifies MD5s,
   and refuses a plan above 50 files / 2 GiB before moving a byte. Over HTTP
   hand the signed URLs to the user instead.
5. **Cite** — `neon_get_citation(product="DP1.10003.001")` gives NEON-format
   text and BibTeX with the release DOI (`provisional=true` for provisional data).

## Inputs

* `product` and `site` fields accept codes (`DP1.10003.001`, `DP1.10003`,
  `HARV`, `harv`) or names (`"breeding landbird"`, `"Harvard Forest"`).
  A confident match is used and echoed in `resolved`; otherwise the call
  fails with `ambiguous_input` listing up to eight candidates — retry with one
  of their codes. Fields named `*_code` are strict codes.
* Months are `YYYY-MM`. `PROVISIONAL` is never a `release` value.

## Errors (`structuredContent.error.code`)

| Code | Meaning | What to do |
|---|---|---|
| `auth_required` | The endpoint needs a NEON API token | Read `neon://guide/api-token` |
| `forbidden` | NEON rejected the token | Create a new token |
| `not_found` | Unknown code (NEON answers 400 "not found") | Use `didYouMean` / `validReleases` |
| `ambiguous_input` | A name matched several codes | Retry with a candidate code |
| `invalid_argument` | Bad or unknown argument | Read the message; it names the field |
| `rate_limited` | NEON's rate limit is exhausted | Wait `retryAfterSeconds` |
| `query_too_large` / `download_limit_exceeded` | Request too wide | Narrow sites or months, or use `detail="summary"` |
| `upstream_error` / `upstream_unavailable` | NEON failed or is unreachable | Retry later; `neon_ping(check_api=true)` |
