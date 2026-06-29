# GB Electricity Data Sources

Status: active source register

Repository: `Ventusltd/data-gb-electricity`

This file records the upstream sources used by this repository. It is deliberately separate from the app layer so the data repo can explain where its data came from, how it is fetched, how it is cleaned and how it is packaged.

## Scope

This repository is for Great Britain electricity data.

It is not a full United Kingdom electricity dataset because Northern Ireland is part of the separate all-island SEM market. This distinction matters for market settlement and interconnector treatment.

## Source pathways

There are two source pathways.

Historical backfill pathway:

The historical base was produced from CSV files in the retiring `Ventusltd/globalgrid2050` source tree, cloned inside a GitHub Actions runner.

That pathway is implemented by `.github/workflows/backfill_history.yml` and `pipelines/port_csv_to_parquet.py`, which delegates to `pipelines/port_csv_to_parquet_impl.py`.

The backfill excludes overlapping combined source files, deduplicates by declared key, writes Parquet and verifies duplicate key groups are zero before the output should be trusted.

Forward monthly pathway:

New or repaired months are fetched from Elexon API endpoints.

That pathway is implemented by `.github/workflows/monthly_update.yml`, `pipelines/fetch_latest_month.py` and helper logic in `pipelines/fetch_elexon_api_to_parquet.py`.

The monthly updater should be treated as unproven until a controlled workflow_dispatch run is completed, audited and recorded in `CHANGELOG.md`.

## Source 1 — FUELINST generation

Name: Elexon BMRS FUELINST.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST

Trust status: candidate or provisional.

Grain: 5-minute generation snapshot by fuel type.

Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option.

Query pattern: publishDateTimeFrom, publishDateTimeTo, format=json.

Idempotency key: periodStartUTC plus fuelType.

Output path: generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet, with possible additional data_N files from DuckDB physical splitting.

Purpose:

FUELINST provides the recent, provisional generation signal. It is useful for tracker freshness and grid-behaviour analysis, but it must not be treated as settled historic truth.

Cleaning rule:

Rows are normalised to source, periodStartUTC, fuelType, generationMW, publishTimeUTC, fetchedAtUTC and dataset.

Re-runs overwrite matching periodStartUTC plus fuelType rows rather than appending duplicates.

## Source 2 — FUELHH generation

Name: Elexon BMRS FUELHH.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH

Trust status: confirmed or settled.

Grain: half-hourly generation by fuel type, normalised into technology buckets.

Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option.

Query pattern: settlementDateFrom, settlementDateTo, format=json.

Idempotency key: time plus technology.

Output path: generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet, with possible additional data_N files from DuckDB physical splitting.

Purpose:

FUELHH is the confirmed historic generation source. It is the correct basis for settled history, monthly totals and higher-trust generation analysis.

Cleaning rule:

Rows are deduplicated by timestamp and source fuel, grouped into technology buckets, then written as time, technology, generationMW, source and dataset.

Technology bucket mapping:

Solar: SOLAR, PV.

Wind: WIND.

Hydro: NPSHYD, HYDRO.

Gas: CCGT, OCGT.

Coal: COAL.

Biomass: BIOMASS.

Nuclear: NUCLEAR.

Pumped Storage: PS.

Imports and Exports: INT.

Other: fallback bucket.

Re-runs overwrite matching time plus technology rows rather than appending duplicates.

## Source 3 — Elexon system prices

Name: Elexon BMRS system or imbalance prices.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/YYYY-MM-DD

Trust status: price data.

Grain: half-hourly settlement period.

Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option.

Query pattern: one date per request, format=json.

Idempotency key: periodStartUTC.

Output path: prices/year=YYYY/month=M/data_0.parquet, with possible additional data_N files from DuckDB physical splitting.

Purpose:

System prices provide the half-hourly price signal used by GB electricity tracking and future price-aware applications.

Cleaning rule:

Rows are normalised to source, settlementDate, settlementPeriod, periodStartUTC, systemBuyPriceGBPperMWh, systemSellPriceGBPperMWh, netImbalanceVolumeMWh and fetchedAtUTC.

Re-runs overwrite matching periodStartUTC rows rather than appending duplicates.

## Historical CSV transition notes

The historical backfill uses the retiring source tree as cold-storage transition input.

The original source tree contains per-year or per-month CSV files and some combined all-years files.

Combined overlapping files must not be read alongside per-period files.

The clean backfill excludes combined overlapping files and deduplicates by declared key before writing.

The original package measurements around 33.6 MB and 319 files are historical context only. They are not permanent correctness targets.

The clean live backfill recorded in `CHANGELOG.md` produced a larger current dataset and passed the real data-law checks: duplicate key groups equal zero and the FUELINST 2023 month 9 canary remains 156,960.

## Packaging rule

The data package is Parquet, not raw CSV.

Compression: zstd.

Partition scheme: dataset/year/month for generation; year/month for prices.

Raw CSV committed here: no.

Monolith clone committed here: no.

Reason:

The old monolith reached approximately 1.2 GB of verbose CSV. Parquet preserves row-level granularity in a much smaller and more queryable form.

## Fetch implementation

Historical backfill:

Workflow: `.github/workflows/backfill_history.yml`.

Wrapper script: `pipelines/port_csv_to_parquet.py`.

Implementation script: `pipelines/port_csv_to_parquet_impl.py`.

Monthly updater:

Workflow: `.github/workflows/monthly_update.yml`.

Monthly script: `pipelines/fetch_latest_month.py`.

API helper script: `pipelines/fetch_elexon_api_to_parquet.py`.

The monthly workflow runs once per month and can also be triggered manually for a controlled repair range.

## Reports

Backfill and monthly runs write or update:

reports/latest_parquet_audit.json

reports/fetch_latest_month_latest.json

reports/package_verification_summary.json

The audit reports should log date range, datasets, endpoint names or source files, idempotency keys, rows fetched or converted, duplicate-key outcomes and partitions touched.

## Data law

The source register records sources, but source names are not enough.

The trusted Parquet output must satisfy the declared grain.

For FUELINST, total rows must equal distinct periodStartUTC plus fuelType.

For FUELHH, total rows must equal distinct time plus technology.

For prices, total rows must equal distinct periodStartUTC.

A green workflow is not proof unless the real data law is checked.
