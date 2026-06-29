# Definitions and Skills Register

This file is a manually maintained training glossary for `data-gb-electricity`.

It explains the data engineering terms, tools and disciplines used in this repo in plain language.

Add new entries alphabetically. Each entry should explain what the thing is, why we used it, and what failure discipline applies to it.

---

## Accepted Value Set

An accepted value set is the list of values a column is allowed to contain.

For this repo, examples include known dataset names, known fuel types or known technology group names.

The discipline is that categorical fields should not silently accept new spellings or unexpected labels without being noticed. New legitimate values can be added, but they should be added deliberately.

## Anomaly Band

An anomaly band is a reasonable range around a moving quantity.

It is used when exact equality is wrong because the data naturally changes over time.

For this repo, row counts, file counts and monthly data volumes should usually be checked with floors or bands, not exact equality, unless the quantity is a true invariant.

## API

An API is a structured way for software to request data from another system.

In this repo, APIs are used to fetch electricity data from Elexon instead of manually downloading files. This matters because an API-based process can be repeated, audited and automated.

The discipline is that every API source must be named, its endpoint must be recorded, and the cleaning rule must be clear.

## Audit Report

An audit report is a machine-readable record of what a pipeline produced during a run.

In this repo, audit reports record facts such as generated time, file counts, data size, target months, duplicate-key checks and canary row counts.

The audit report is not the data itself. It is the evidence trail showing what the pipeline did.

## Backfill

A backfill is a one-time process that loads historical data into a new structure.

In this repo, the historical backfill converts the retiring monolith's GB electricity CSV data into compact Parquet partitions.

The backfill is different from the monthly updater. The backfill creates the historical base. The monthly updater keeps the base current.

## Baseline Check

A baseline check is a minimum safety threshold.

It asks whether the output is at least as complete as a known good earlier run.

Baseline checks are used for quantities that can grow over time, such as source file counts or Parquet partition counts. They should not use exact equality when the dataset is expected to grow.

## Canary Check

A canary check is a small strict test that proves a much larger process has not silently corrupted the data.

In this repo, the FUELINST 2023 month 9 canary must remain 156,960 rows. That month is settled history, so the row count should not change.

The canary is a true invariant. If it fails, the pipeline should fail.

## Compound Key

A compound key is a unique identifier made from more than one column.

This matters when no single column uniquely identifies a row.

In this repo, FUELINST uses periodStartUTC plus fuelType. FUELHH uses time plus technology. Prices use periodStartUTC.

The discipline is that every published dataset must have a declared grain and a declared key.

## CSV

CSV means comma-separated values. It is a simple text format where rows and columns are stored as readable text.

CSV is useful for exchange and transparency, but it is inefficient for large repeated time-series data. It repeats timestamps, strings and source labels many times.

In the old repo, raw CSV helped preserve the source data, but it made the working tree too large. In this repo, CSV is treated as transition source material, not the preferred storage format.

## Data Contract

A data contract is a stated agreement about what a dataset must look like and mean.

It includes column names, data types, keys, accepted values, uniqueness rules and freshness expectations.

In this repo, the data contract should be enforced at the Parquet boundary. If the published Parquet breaks the contract, the workflow should fail before committing.

## Data Diff

A data diff compares two versions of a dataset and shows what changed at row or value level.

It is stronger than checking only file counts or total size.

For this repo, data diff logic can prove that a monthly update only added or deliberately rewrote the intended partitions, instead of silently changing old history.

## Data Quality Dimensions

Data quality dimensions are the main categories used to judge whether data is fit for use.

The most relevant dimensions here are accuracy, completeness, consistency, uniqueness, validity and timeliness.

The duplicate-row bug was a uniqueness failure. A missing month would be a completeness failure. A stale updater would be a timeliness failure.

## Data Repository

A data repository is a repo whose primary job is to store and update datasets, not user interface code.

This repo exists because data and application code move at different speeds. The data can grow monthly while the app remains light.

The discipline is that the data repo should contain compact data, source registers, pipelines and audit evidence, not unrelated app code.

## Distinct Count Check

A distinct count check compares total rows with the number of unique keys.

The principle is simple: if a dataset has one row per key, then total rows must equal distinct keys.

This is the check that prevents duplicate timestamps or duplicate compound keys from silently entering the Parquet data.

## DuckDB

DuckDB is an embedded analytical database engine.

It lets a script run SQL directly over files such as CSV and Parquet without needing a separate database server.

We used DuckDB because it can read many source CSV files, combine them, derive year and month fields from timestamps, deduplicate by key, and write partitioned Parquet quickly inside a GitHub Actions runner.

The key lesson from the backfill was that DuckDB can write partitioned output, but the top-level output folders must exist first on a clean runner. That is why the script now creates the generation and prices folders before writing.

## Elexon

Elexon is the GB electricity market data source used by this repo.

The repo uses Elexon data for generation and system price datasets.

The discipline is that Elexon source names, endpoints and cleaning keys must be documented so the data chain can be defended later.

## Fail-Loud

Fail-loud means the process stops clearly when something important is wrong.

In this repo, duplicate keys, schema drift, empty API returns, missing key fields or canary corruption should stop the workflow.

Fail-loud does not mean every optional path should kill the run. It means real data risks must not be hidden.

## Floor Check

A floor check says a moving quantity must be at least a known minimum.

It is useful for living datasets that grow over time.

The 319 Parquet file count became a floor, not an exact equality, because the dataset can grow.

## FUELHH

FUELHH is an Elexon half-hourly generation dataset.

In this repo it is used as the settled or confirmed half-hourly generation source.

It is important because FUELHH is better suited for confirmed historical reporting than fast provisional data.

The key discipline is one row per time plus technology after cleaning.

## FUELINST

FUELINST is an Elexon near-real-time generation dataset.

In this repo it is used for candidate or provisional generation values, especially where high time resolution is useful.

The important cleaning key is periodStartUTC plus fuelType, because the same timestamp can contain multiple fuel categories.

## GitHub Actions

GitHub Actions is the automation system that runs workflows inside GitHub.

In this repo it runs the historical backfill and monthly updater.

The discipline is that build steps should fail loudly on real errors, while commit steps should not fail just because an optional report path is missing.

## Idempotency

Idempotency means a process can be run more than once without compounding duplicates or creating different results for the same input.

In this repo, touched month partitions are rewritten fresh rather than appended blindly.

That prevents duplicate rows from accumulating over time.

## Idempotent Partition Overwrite

Idempotent partition overwrite means deleting or replacing the whole target partition before writing the new version.

It is safer than appending because re-running the same job converges to the same output instead of doubling rows.

In this repo, the monthly updater removes the whole touched month partition directory before writing the fresh Parquet file.

## Invariant

An invariant is a fact that should not change if the data and process are healthy.

The FUELINST 2023 month 9 row count is an invariant because settled historical data should remain stable.

Invariants can use strict equality checks. Moving quantities should not.

## JSON

JSON is a structured text format used for machine-readable records.

In this repo it is used for audit reports and metadata summaries.

JSON is useful because both humans and scripts can read it.

## Living Dataset

A living dataset is a dataset that is expected to grow or update over time.

The GB electricity dataset is living because new months of data arrive.

The discipline is that living quantities should be monitored or checked against floors, not frozen as exact permanent numbers.

## Monthly Updater

The monthly updater is the scheduled workflow that refreshes the repo with the previous complete month of data.

It is different from the backfill. The backfill loads history. The monthly updater keeps history current.

The updater should fetch only the required month or repair range, rewrite touched partitions fresh, and produce an audit report.

## No Null Key Check

A no null key check ensures every row has the fields needed to identify it.

A row without its timestamp or key field cannot be safely deduplicated or joined.

For this repo, nulls in periodStartUTC, time, fuelType or technology should be treated as hard data-quality failures unless explicitly quarantined.

## OpenLineage

OpenLineage is an emerging standard for recording metadata about data pipeline runs.

This repo does not need a full OpenLineage implementation yet, but its audit JSON is moving in the same direction.

The practical discipline is to record source files, run time, git SHA, row counts, distinct-key counts, schema version and validation results.

## Pandera

Pandera is a Python library for defining and checking data schemas in code.

It can express column types, null rules, accepted values and compound uniqueness checks.

It may be useful later because it is lighter than large data-quality platforms and fits a Python-first repo.

## Parquet

Parquet is a column-based file format for analytical data.

Unlike CSV, which stores data row by row as text, Parquet stores data by column and compresses repeated values efficiently.

We used Parquet because GB electricity time-series data repeats timestamps, fuel types, source labels and numeric structures many times. Parquet reduced the original source CSV bulk from about 1.2 GB to about 34 MB while preserving row-level detail.

Parquet was chosen because it is compact, fast to query, suitable for partitioned datasets, and widely supported by tools such as DuckDB and PyArrow.

## Partitioned Data

Partitioned data is data split into folders based on fields such as dataset, year and month.

In this repo, generation data is partitioned by dataset, year and month. Prices are partitioned by year and month.

Partitioning matters because an app or script can load the month it needs instead of reading the whole historical dataset.

## Pipeline

A pipeline is a repeatable sequence of steps that turns source data into checked output.

In this repo, the pipeline fetches or reads source data, cleans it, writes Parquet, verifies the output, writes an audit report, and commits the result.

The discipline is that the pipeline must be reproducible. The repo should not depend on a static zip file someone says is correct.

## Provenance and Lineage

Provenance means evidence of where data came from and how it was produced.

Lineage means the chain from source data through transformations to final output.

In this repo, audit reports are the practical lineage trail. They should record resolved input files, source endpoints, output partitions and validation results.

## PyArrow

PyArrow is a Python library for working with Arrow tables and Parquet files.

In this repo it is used by the monthly updater to write Parquet files directly from fetched records.

It is useful because it handles Parquet output reliably and can create parent folders before writing.

## Raw Data

Raw data is source data before it has been cleaned, compressed or reshaped.

The old CSV files are raw or near-raw source material.

This repo does not commit raw CSV bulk. It stores compact Parquet outputs and reproducible scripts instead.

## Reproducibility

Reproducibility means another run of the same process can prove the result again.

This is why the repo favours pipeline backfill over trusting a static zip file.

A reproduced pipeline is stronger evidence than a one-off artefact.

## Schema

A schema is the structure of a dataset: its column names, data types and expected meaning.

Schema discipline matters because a silent column change can break charts, calculations or joins.

Schema problems should fail loudly.

## Schema Drift

Schema drift is an unplanned change in the structure of source data.

Examples include a column being renamed, a timestamp changing type, or a numeric field arriving as text.

Schema drift should fail loudly at the trust boundary instead of silently changing the published Parquet.

## Schema Evolution

Schema evolution is an intentional and documented change to a dataset structure.

It is different from schema drift because it is deliberate, reviewed and explained.

If this repo evolves a schema, the definition, scripts, audit report and downstream consumers should be updated together.

## Schema-on-Write

Schema-on-write means enforcing the schema before or during writing of the trusted output.

This is appropriate for published Parquet because downstream users should not have to guess what the columns mean.

In this repo, the Parquet boundary is where schema discipline should be strongest.

## Small-Files Problem

The small-files problem happens when a dataset is split into too many tiny files.

Too many small files slow down listing, reading and management even if the total data size is modest.

Year and month partitions are acceptable here. Per-day partitions would likely be too granular for this repo.

## Snapshot Check

A snapshot check tests a value from one point in time.

The original 319 Parquet file count was a snapshot check.

It became a bug because the source data grew. Snapshot checks should not be used as exact permanent laws for living datasets.

## Source of Truth

A source of truth is the authoritative place from which a dataset or fact is derived.

For this repo, Elexon is the external source of truth for GB electricity market data.

The old monolith is a transition source for the historical backfill, but the future source of truth should be the documented API pathway.

## Staging Output

Staging output is temporary output written before publication.

It allows the pipeline to build and audit data before replacing the trusted published files.

This supports Write-Audit-Publish because bad staged data can be discarded without touching the published repo state.

## Surrogate Key

A surrogate key is an artificial key created from one or more real fields.

It is useful when a dataset needs a single identifier for a compound grain.

For example, periodStartUTC plus fuelType could be converted into one hashed key for testing or diffing, but the underlying grain must still be documented.

## System Prices

System prices are Elexon imbalance price data for GB electricity settlement periods.

In this repo they are stored separately from generation data because prices and generation have different meanings and cleaning keys.

The key used for prices is periodStartUTC.

## Unix Fail-Loud Discipline

Unix fail-loud discipline means shell scripts should stop when important commands fail.

The usual pattern is set e, u and pipefail so unset variables, failed commands and failed pipeline stages do not pass silently.

In this repo, that discipline should be used for build and audit steps. Intentional non-fatal commands should be marked clearly.

## Workflow Dispatch

Workflow dispatch means manually starting a GitHub Actions workflow.

In this repo, the historical backfill is triggered by workflow dispatch because it is a controlled one-time operation.

Manual dispatch lets the operator choose when to run a high-impact workflow.

## Write-Audit-Publish

Write-Audit-Publish means writing data to a temporary or isolated place, auditing it, and publishing it only if all checks pass.

It prevents bad data from being committed just because the write step completed.

For this repo, the mature pattern is to build Parquet into a staging directory, run schema, canary and uniqueness checks, and only then replace generation and prices in the published tree.

## zstd Compression

zstd is a compression method used inside the Parquet files.

It gives strong compression while remaining fast to read.

It was used because the dataset has many repeated values and should remain compact without becoming hard to query.
