"""Server instructions returned by ``server/discover`` (kept under 1 200 characters)."""

from __future__ import annotations

SERVER_INSTRUCTIONS = (
    "neon-mcp exposes the NEON (National Ecological Observatory Network) Data API. Typical flow: "
    "neon_search_products (fuzzy keywords) -> neon_get_availability (which sites/months have data, "
    "released vs PROVISIONAL) -> neon_list_files (needs a NEON API token; signed URLs valid ~7 days; "
    "detail='summary' sizes a pull first) -> neon_download_files (stdio only, writes under the "
    "configured download directory) -> neon_get_citation. Product and site fields accept codes "
    "(HARV, DP1.10003.001) or names ('Harvard Forest', 'breeding landbird'); confident matches are "
    "echoed in `resolved`, ambiguous ones return ambiguous_input with candidates. PROVISIONAL is not "
    "a release tag: use the provisional / include_provisional switches. Every result is compact and "
    "paginated (page.nextOffset), carries notes, and ends with nextSteps. Call neon_ping to learn "
    "whether a token is configured; without one, all discovery, availability, taxonomy, release, "
    "location and prototype tools still work. Read neon://guide/agent-workflow for worked examples "
    "and neon://reference/vocabularies for valid filter values."
)
