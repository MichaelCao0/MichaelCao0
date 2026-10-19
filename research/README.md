# Publication metadata and citations

`publications.json` contains the curated titles, venues, verified code/project links,
and stable Google Scholar publication IDs. Venue evidence is recorded in
`venue_sources`. Edit this catalog when adding a paper or updating its acceptance;
the updater does not infer a venue from arXiv or automatically attach repositories
with matching names.

`scholar.json` is the last successfully parsed public Google Scholar profile:
per-paper citations, citing-paper links, total citations, h-index, i10-index, and
the successful retrieval date. Counts use Scholar's merged-record totals.

The daily `Refresh profile` workflow runs `.github/scripts/update_research.py`
and rewrites only the Research marker block in the profile README. No API key or
additional account is required. If Scholar blocks the request or returns an
incomplete profile, the workflow emits a warning and retains the previous counts
and retrieval date. It never substitutes another citation provider or reports a
failed retrieval as zero citations.

```bash
python3 -m unittest discover -s tests -v
python3 .github/scripts/update_research.py
python3 .github/scripts/update_research.py --cached
```

The test fixture includes only public profile name, summary statistics, and
publication rows from the 2026-10-19 response. It excludes forms and session fields.
