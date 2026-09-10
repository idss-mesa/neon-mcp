# Citing NEON data

NEON data are released under the Creative Commons CC BY 4.0 license and
must be cited. NEON's data policy:
<https://www.neonscience.org/data-samples/data-policies-citation>.

* **Released data** belong to an annual release (`RELEASE-2026`, ...) that has a
  DOI per data product. Cite the product *and* the release DOI. Released data
  do not change.
* **Provisional data** (`PROVISIONAL` in availability) have no DOI and may
  change. Say so, give the access date, and archive the exact files you used
  (your own DOI) for reproducibility.
* **Prototype datasets** have their own DOIs and version numbers.
* Acknowledge NSF: "The National Ecological Observatory Network is a program
  sponsored by the U.S. National Science Foundation and operated under
  cooperative agreement by Battelle."

Signed file URLs expire after about seven days: never cite them.

`neon_get_citation` renders these templates (placeholders use `$name`):

```citation-released
NEON (National Ecological Observatory Network). $productName ($productCode), $release. $doiUrl. Dataset accessed from https://data.neonscience.org on $accessedOn.
```

```citation-provisional
NEON (National Ecological Observatory Network). $productName ($productCode), provisional data. Dataset accessed from https://data.neonscience.org on $accessedOn. Data archived at [your DOI].
```

```citation-prototype
NEON (National Ecological Observatory Network). $projectTitle, version $version. $doiUrl. Prototype dataset accessed from https://data.neonscience.org/prototype-datasets/$uuid on $accessedOn.
```

```bibtex
@misc{$key,
  author = {{NEON (National Ecological Observatory Network)}},
  title = {$title},
  year = {$year},
  publisher = {National Ecological Observatory Network (NEON)},
  doi = {$doi},
  url = {$url},
  note = {Dataset accessed from https://data.neonscience.org on $accessedOn}
}
```

For authoritative DataCite metadata use NEON's DOI landing page or
`neonUtilities::getCitation` in R.
