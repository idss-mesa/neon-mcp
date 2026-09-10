# NEON product codes, files and releases

## Codes

`DP1.10003.001` = data product level (`DP1`..`DP4`), a five-digit product
number, and a three-digit revision. `productCodeLong` is
`NEON.DOM.SITE.DP1.10003.001` (the pattern file names follow);
`productCodePresentation` drops the revision (`NEON.DP1.10003`). neon-mcp
accepts `DP1.10003` (revision `.001` assumed) and `NEON.`-prefixed forms.

Levels: 1 = quality-controlled measurements; 2 = temporally interpolated;
3 = spatially interpolated or mosaicked (e.g. AOP tiles); 4 = derived products.

## Packages

`basic` holds the core data tables; `expanded` adds quality metrics and
extra tables (`productHasExpanded`).

## File names

```
NEON.D16.ABBY.DP1.00001.001.000.010.030.2DWSD_30min.2023-01.basic.20250128T000000Z.csv
     |   |    |             |   |   |   |           |       |     generation timestamp
     |   |    product code  HOR VER TMI table        month   package
     domain site
```

* **HOR** — horizontal index (e.g. `000` tower, `001`..`005` soil plots).
* **VER** — vertical index (e.g. `010` first tower level, `060` sixth).
* **TMI** — temporal index in minutes (`001`, `002`, `030`, `100` = daily, ...).
* Observational (OS) files omit HOR/VER/TMI: `NEON.D01.HARV.DP1.10003.001.brd_countdata.2023-06.basic.20250128T000000Z.csv`.

`neon_list_files` classifies each file as a `kind`: `data`, `variables`
(column definitions), `readme`, `sensor_positions`, `eml` (metadata),
`science_review_flags`, `categorical_codes`, `validation`, `package` (a zip)
or `other`, and parses `table`, `hor`, `ver`, `tmi` for filtering.

## Releases and PROVISIONAL

Each January NEON publishes an immutable release (`RELEASE-2021` ...
`RELEASE-2026`) with DOIs. Newer data are `PROVISIONAL`: available, not
yet released, and subject to change. `PROVISIONAL` is not a release tag —
filter it with `provisional` / `include_provisional`.

## Signed URLs

File URLs are Google Cloud Storage signed URLs valid for about 7 days
(`urlExpiresAt`). They need no token; list again to refresh them.
