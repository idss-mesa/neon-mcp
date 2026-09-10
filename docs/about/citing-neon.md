---
title: "Citing NEON data"
description: "NEON data are CC-BY 4.0: how to cite a data product and release by DOI, why provisional data cannot be cited by DOI, and how to acknowledge NEON and NSF."
type: Policy
tags:
  - about
  - citation
  - DOI
  - data-policy
  - CC-BY
generated:
  by: "claude/fable-5.1"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-guidelines
    resource: "https://www.neonscience.org/data-samples/guidelines-policies"
    title: "NEON — Data and Samples: Guidelines and Policies"
    author: "team:neon"
  - id: neon-citation
    resource: "https://www.neonscience.org/data-samples/data-policies-citation"
    title: "NEON — Data Policies and Citation Guidelines"
    author: "team:neon"
  - id: neon-api-releases
    resource: "https://data.neonscience.org/data-api/endpoints/releases/"
    title: "NEON Data API — Releases endpoint"
    author: "team:neon"
  - id: neon-mcp-license
    resource: "https://github.com/idss-mesa/neon-mcp/blob/main/LICENSE"
    title: "neon-mcp LICENSE file (MIT)"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# Citing NEON data

neon-mcp is only a conduit. The data it returns belong to the National
Ecological Observatory Network (NEON), and NEON's data policy — not this
project's license — governs how you may use and must credit them. This page
summarises that policy and shows how to build a correct citation from what
the API (and therefore neon-mcp) gives you.

## License: CC-BY 4.0

NEON releases its data and data products under the
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/){target=_blank}
license[^neon-guidelines]. You may use, share and adapt them for any purpose,
including commercially, provided you give appropriate credit. NEON asks that
you cite each data product you use, at the release you used, and acknowledge
NEON and the U.S. National Science Foundation in publications[^neon-citation].
Read the policy pages themselves before publishing; they are the authority
and may change:

* [Guidelines and policies](https://www.neonscience.org/data-samples/guidelines-policies){target=_blank}
* [Data policies and citation guidelines](https://www.neonscience.org/data-samples/data-policies-citation){target=_blank}

## Releases and DOIs

NEON publishes an annual **release** — a frozen, versioned snapshot of a data
product's files (RELEASE-2021 through RELEASE-2026 exist as of September
2026). Every data product within a release has its own DOI, which is what you
cite. Anything newer than the latest release is **provisional**: subject to
reprocessing and without a DOI (see below).

The Data API exposes the DOI wherever a product meets a release[^neon-api-releases]:

* `GET /products/{productCode}` returns `releases[]`, each with `release`
  (the tag), `generationDate`, `url` and `productDoi.url`.
* `GET /releases/{releaseTag}` returns `dataProducts[]`, each with
  `productCode`, `productName` and `productDoi`.

For example, the product *2D wind speed and direction* (`DP1.00001.001`) in
`RELEASE-2021` carries `productDoi.url` =
[https://doi.org/10.48443/s9ya-zc81](https://doi.org/10.48443/s9ya-zc81){target=_blank}.
neon-mcp's product and release tools surface these fields, so an agent can
assemble a citation without a second lookup.

## How to cite a data product

NEON's recommended pattern[^neon-citation] names the product, its code, the
release, the DOI and the access date:

> NEON (National Ecological Observatory Network). *Product name*
> (DPx.xxxxx.xxx), RELEASE-YYYY. https://doi.org/xx.xxxxx/xxxx-xxxx.
> Dataset accessed from https://data.neonscience.org/data-products/DPx.xxxxx.xxx/RELEASE-YYYY
> on Month DD, YYYY.

Filled in for the example above:

> NEON (National Ecological Observatory Network). 2D wind speed and direction
> (DP1.00001.001), RELEASE-2021. https://doi.org/10.48443/s9ya-zc81. Dataset
> accessed from https://data.neonscience.org/data-products/DP1.00001.001/RELEASE-2021
> on September 10, 2026.

Cite every product you used, each at the release you actually downloaded.
If you retrieved data through neon-mcp you may mention the tool in your
methods, but the citation of record is always the NEON data product DOI.

## Provisional data

Availability listings from the API carry a `PROVISIONAL` pseudo-release tag
alongside real release tags[^neon-api-releases]. Provisional data:

* have **no DOI** and cannot be cited by one;
* may be revised, reprocessed or removed before they enter a release;
* are excluded from data queries by default and must be requested explicitly.

When neon-mcp shows a site-month only under `PROVISIONAL`, that data are not
yet in any release. For reproducible work prefer a release; if you must use
provisional data, say so and cite them by access date:

> NEON (National Ecological Observatory Network). *Product name*
> (DPx.xxxxx.xxx), provisional data. Dataset accessed from
> https://data.neonscience.org on Month DD, YYYY.

## Acknowledging NEON and NSF

NEON requests an acknowledgement in publications that use its data or
samples[^neon-citation]; its suggested wording is:

> The National Ecological Observatory Network is a program sponsored by the
> U.S. National Science Foundation and operated under cooperative agreement
> by Battelle. This material is based in part upon work supported by the
> National Science Foundation through the NEON Program.

NEON also asks to be told about publications that use its data so it can
track the observatory's impact; the citation-guidelines page explains how.

## About neon-mcp itself

The neon-mcp server software is MIT-licensed by The Regents of the University
of New Mexico[^neon-mcp-license] and is not affiliated with or endorsed by
NEON, Battelle or NSF. See [License](license.md) for the software and
documentation licenses.

[^neon-guidelines]: NEON — Data and Samples: Guidelines and Policies. <https://www.neonscience.org/data-samples/guidelines-policies>
[^neon-citation]: NEON — Data Policies and Citation Guidelines. <https://www.neonscience.org/data-samples/data-policies-citation>
[^neon-api-releases]: NEON Data API — Releases endpoint. <https://data.neonscience.org/data-api/endpoints/releases/>
[^neon-mcp-license]: neon-mcp `LICENSE` file. <https://github.com/idss-mesa/neon-mcp/blob/main/LICENSE>
