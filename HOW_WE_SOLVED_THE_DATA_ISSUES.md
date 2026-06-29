# How We Solved the Data Issues

Status: active update log  
Repository: `Ventusltd/data-gb-electricity`  
Last updated: 2026-06-29

## Purpose

This file records how the GlobalGrid2050 GB electricity data issue was solved during the federation of the old `globalgrid2050` monolith into smaller, focused repositories.

The goal is to preserve the reasoning, mistakes, corrections and final data discipline so a future AI or human can continue the work without repeating the same confusion.

## Problem

The old monolith carried large electricity data inside the application repository.

The key data issue was not that the data was useless. The issue was that raw CSV firehose data and app code were living too close together.

The affected public pages were:

```text
https://globalgrid2050.com/uk_energy_tracking_v6/
https://globalgrid2050.com/uk_energy_tracking_v6/generation_history/
```

The data source areas in the old monolith were:

```text
globalgrid2050/data/generation/archive/*/*.csv
globalgrid2050/data/generation/fuelhh_halfhourly/*/*.csv
globalgrid2050/data/electricity/elexon_system_prices_*.csv
```

## Correct data boundary

This new repository is **data only**.

It should hold GB electricity time-series in compact, queryable Parquet form.

It should not hold:

```text
application code
homepage/dashboard code
raw monolith clone
raw CSV firehose
large basemap data
workflow sprawl
```

The app repos can later fetch compact data from here.

## GB not UK

This repo is called `data-gb-electricity`, not `data-uk-electricity`.

Reason:

Elexon settles the Great Britain electricity market. Northern Ireland sits in the separate all-island SEM. Interconnector and border-flow treatment makes this distinction material.

## Dataset classification

```text
FUELINST
grain: 5-minute
status: candidate
reason: provisional firehose

FUELHH
grain: half-hourly
status: confirmed
reason: settled source

PRICES
grain: half-hourly
status: system / imbalance price data
```

A confirmed fact must not be silently derived from candidate FUELINST.

## First solution

Claude converted the source CSV into partitioned Parquet and verified the result.

Verified numbers:

```text
source CSV total: approximately 1,218 MB
Parquet output: approximately 33.6 MB
partition files: 319
compaction: approximately 36x
FUELINST 2023 month 9 canary: 156,960 rows
source/parquet canary match: true
```

The tested partition layout is:

```text
generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet
generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet
prices/year=YYYY/month=M/data_0.parquet
```

## Technique versus artifact

The correct answer is both.

The technique is preserved in:

```text
pipelines/port_csv_to_parquet.py
```

That script is the regeneration path.

The artifact is the verified Parquet tree:

```text
generation/
prices/
reports/latest_parquet_audit.json
```

The first port is a one-shot data migration. It does not need a new GitHub Actions workflow just to run once.

A future live updater is different. That would be recurring infrastructure and should be designed later as a separate, justified pipeline.

## Important correction made during this session

ChatGPT initially suggested using GitHub Actions to run the one-shot conversion because its sandbox could not resolve `github.com`.

That was corrected.

Lesson:

```text
Do not create workflows just to work around a one-time execution environment problem.
```

The monolith already suffered from workflow sprawl. Federation should reduce workflow count, not repeat the same pattern.

## Package received for direct port

A verified package was uploaded:

```text
data-gb-electricity-parquet-port.zip
```

Package SHA256:

```text
90f0df3fdcc266c6918a060876beca34503770f61fc9ba5c2d138b32354ffdff
```

Inspected package contents:

```text
files total: 322
Parquet files: 319
Python scripts: 1
README files: 1
JSON audit reports: 1
raw CSV present: false
workflow files present: false
monolith clone present: false
```

Local verification from the uploaded package:

```text
Parquet total: 33.634 MB
generation/dataset=fuelinst: 26.249 MB
generation/dataset=fuelhh: 4.807 MB
prices: 2.578 MB
canary query: 156,960 rows
```

This confirms the package matches the intended one-shot Parquet port.

## Current implementation state

Text-side repository files are in place:

```text
README.md
.gitignore
pipelines/port_csv_to_parquet.py
```

The verified Parquet artifact tree is ready to commit from the uploaded package:

```text
generation/
prices/
reports/latest_parquet_audit.json
```

If a tool can commit binary files directly, commit the verified artifact tree.

If the current connector cannot reliably commit binary Parquet files, use a normal local Git push or another environment that can push the binary tree without creating a one-shot workflow.

## Do not do this

```text
Do not commit raw CSV.
Do not clone the full monolith into this repo.
Do not build an app here.
Do not add a one-shot GitHub Actions conversion workflow.
Do not add stale dashboard links before the data repo is verified.
```

## Next actions

1. Commit the verified Parquet tree from the package.
2. Re-check that repo contains 319 Parquet files.
3. Keep `pipelines/port_csv_to_parquet.py` as the regeneration path.
4. Add the homepage dashboard catalogue entry only after the data repo is verified.
5. Build the live updater later as a separate scoped task.

## Stop condition

The first data issue is solved when the repo contains:

```text
generation/
prices/
pipelines/port_csv_to_parquet.py
reports/latest_parquet_audit.json
README.md
HOW_WE_SOLVED_THE_DATA_ISSUES.md
```

and the verified tripwires remain:

```text
319 Parquet files
approximately 33.6 MB Parquet output
156,960 canary rows for generation/dataset=fuelinst/year=2023/month=9
```
