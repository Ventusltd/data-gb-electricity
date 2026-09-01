# data-gb-electricity

AI READ FIRST: This repository follows the GlobalGrid2050 Data Discipline Manual in `Ventusltd/globalgrid2050-hompage/docs/DATA_DISCIPLINE_MANUAL.md`. Read that manual before patching, porting, backfilling, scheduling, publishing or wiring this repository to UI. Green is not proof. File count is not proof. Size is not proof. The proof is the declared data law tested on the declared key.

GB electricity data repository for the GlobalGrid2050 federation.

This repository holds Great Britain electricity time-series in compact, partitioned Parquet form. It is the data layer for the federated successors of the old `globalgrid2050` monolith.

## Scope

This is GB electricity, not full UK electricity.

Elexon settles the Great Britain electricity market. Northern Ireland sits in the separate all-island Single Electricity Market. The distinction matters because interconnector and border-flow datasets can treat Moyle and related flows differently from domestic GB generation and demand.

## Data source register

The detailed source register is `DATA_SOURCES.md`.

It records the Elexon endpoints, trust status, grain, idempotency keys, cleaning rules and Parquet output paths.

## Two source pathways

This repository has two different source pathways and they must not be confused.

Historical backfill source:

The one-time historical backfill clones the retiring `Ventusltd/globalgrid2050` source tree inside the GitHub runner and converts its CSV history into clean Parquet.

The historical backfill does not fetch all history directly from the live Elexon API.

The backfill excludes overlapping combined CSV files, deduplicates by declared key, verifies the output, and commits only the Parquet data and audit report.

Monthly updater source:

The monthly updater fetches new or repaired months from Elexon API endpoints.

It does not repeatedly re-fetch full history.

It is the forward-maintenance path after the historical base has landed.

## Source datasets

FUELINST provisional generation.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST

Status: candidate or provisional.

Idempotency key: periodStartUTC plus fuelType.

FUELHH settled half-hourly generation.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH

Status: confirmed or settled.

Idempotency key: time plus technology.

Elexon system prices.

Endpoint for monthly updater: https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/YYYY-MM-DD

Status: price data.

Idempotency key: periodStartUTC.

## Parquet layout

Generation FUELINST path pattern: generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet

Generation FUELHH path pattern: generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet

Prices path pattern: prices/year=YYYY/month=M/data_0.parquet

DuckDB may also create data_1.parquet or later numbered files inside a partition. That is not automatically a bug. Multiple physical files are acceptable if total rows equal distinct declared keys.

Packaging rule:

Format: Parquet.

Compression: zstd.

Raw CSV committed here: no.

Monolith clone committed here: no.

## One-time historical backfill

The historical backfill workflow is `.github/workflows/backfill_history.yml`.

It is manually triggered from GitHub Actions.

It clones the retiring source repo inside the runner and runs `pipelines/port_csv_to_parquet.py`.

That wrapper calls `pipelines/port_csv_to_parquet_impl.py`, where the current implementation lives.

The workflow commits only generation, prices and reports.

The backfill must pass real data-law checks before it should be trusted.

Hard invariants:

FUELINST 2023 month 9 canary must remain exactly 156,960 rows.

FUELINST duplicate key groups must be zero on periodStartUTC plus fuelType.

FUELHH duplicate key groups must be zero on time plus technology.

Prices duplicate key groups must be zero on periodStartUTC.

Moving quantities:

Parquet file count is not a fixed target.

Total megabytes is not a fixed target.

Row counts for living months are not fixed permanent targets.

These values can grow as source data grows. They should be recorded and monitored, not treated as exact equality checks.

The first clean historical backfill is recorded in `CHANGELOG.md`. That clean run verified 456 Parquet files, zero duplicate key groups, and the FUELINST canary at 156,960 rows. The number 456 is evidence of that run, not a permanent law.

## Automated monthly updater

The active monthly process is `pipelines/fetch_latest_month.py` plus `.github/workflows/monthly_update.yml`.

The workflow is scheduled to run once per month and inspect the latest three closed UTC partition months for missing dataset partitions.

Default monthly behaviour:

Run date: 2nd day of each month at 06:17 UTC.

Date range inspected: the latest three complete UTC partition months after the corresponding GB calendar month has closed.

Default write rule: fetch only missing dataset-months. Existing Parquet is frozen and causes no API request.

Datasets: fuelinst, fuelhh and prices.

Output: at most one new `data_0.parquet` per missing dataset-month, plus moving audit reports.

Commit: generation, prices and reports.

Manual workflow_dispatch remains available for controlled testing. Replacing existing history requires explicit start and end dates plus the separate `repair_existing` switch.

Hard unattended limits are 9 dataset-months, 2,000,000 fetched rows, 9
Parquet files, 134,217,728 written Parquet bytes, 200 estimated logical API
requests and 600 maximum HTTP attempts including retries.
A second gate compares the audit plan with Git's real diff and rejects
historical modification, an unplanned partition, raw data, or excess growth
before commit. See `BOUNDED_MONTHLY_UPDATES.md`.

Important status note:

The monthly updater is implemented and documented, but it should be treated as unproven until a controlled workflow_dispatch run has been completed, audited and recorded in `CHANGELOG.md`.

Do not rely on the unattended monthly schedule until that first end-to-end updater proof exists.

Suggested first manual test:

Use one complete month already covered by the dataset.

Run all three datasets.

Confirm an existing partition is reported `SKIP_FROZEN` and remains byte-identical.

Confirm a missing partition is reported `ADD_MISSING` and creates exactly one Parquet file.

Confirm duplicate key groups remain zero.

Confirm the audit records the plan, skip decisions, row counts, hard limits and before/after Parquet audit.

## Cleaning and merge discipline

Normal runs never remove or rewrite an existing calendar-month partition. They
fetch a full missing dataset-month, deduplicate by stable key, validate schema
and key uniqueness, write a pending Parquet file, read it back, and only then
install `data_0.parquet`.

Historical replacement is a distinct explicit-repair mode. It is date-bounded,
uses the same limits and records the replacement in the audit.

FUELINST key: periodStartUTC plus fuelType.

FUELHH key: time plus technology.

Prices key: periodStartUTC.

This is how the repo avoids duplicate compounding and avoids becoming another raw CSV store.

## Reports

The main audit reports are:

reports/latest_parquet_audit.json

reports/fetch_latest_month_latest.json

reports/bounded_growth_gate_latest.json

reports/package_verification_summary.json

The decision and training documents are:

HOW_WE_SOLVED_THE_DATA_ISSUES.md

CHANGELOG.md

DEFINITIONS.md

GLOBAL_GRID_OS_MISSION.md

## Query examples

Maximum provisional FUELINST generation by fuel:

SELECT fuelType, max(generationMW)
FROM read_parquet('generation/dataset=fuelinst/**/*.parquet')
GROUP BY fuelType
ORDER BY max(generationMW) DESC;

Settled FUELHH monthly MWh by technology:

SELECT
  year,
  month,
  technology,
  sum(generationMW * 0.5) AS mwh
FROM read_parquet('generation/dataset=fuelhh/**/*.parquet')
GROUP BY year, month, technology
ORDER BY year, month, technology;

Price uniqueness check:

SELECT count(*) AS rows, count(DISTINCT periodStartUTC) AS distinct_periods
FROM read_parquet('prices/**/*.parquet');

Rows must equal distinct_periods for prices.

## Governance

Rules:

Source endpoints must be logged in `DATA_SOURCES.md`.

Fetch through the data repo, not the app repo.

Write Parquet directly, not raw CSV.

No raw CSV committed here.

No app code here.

No source repo clone committed here.

Monthly automation inspects only recent complete months and fetches missing
dataset-months. Existing history is not queried or changed unless an explicit
bounded repair range is provided.

Failed API calls, empty results, duplicate keys, schema problems or canary corruption must make the workflow go red.

A green workflow is not proof by itself.

A matching file count is not proof by itself.

A matching total size is not proof by itself.

The proof must test the real data law.
