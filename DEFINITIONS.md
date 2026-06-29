# Definitions and Skills Register

This file is a manually maintained training glossary for `data-gb-electricity`.

It explains the data engineering terms, tools and disciplines used in this repo in plain language.

Add new entries alphabetically. Each entry should explain what the thing is, why we used it, and what failure discipline applies to it.

---

## API

An API is a structured way for software to request data from another system.

In this repo, APIs are used to fetch electricity data from Elexon instead of manually downloading files. This matters because an API-based process can be repeated, audited and automated.

The discipline is that every API source must be named, its endpoint must be recorded, and the cleaning rule must be clear.

## Audit Report

An audit report is a machine-readable record of what a pipeline produced during a run.

In this repo, audit reports record facts such as generated time, file counts, data size, target months and canary row counts.

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

## CSV

CSV means comma-separated values. It is a simple text format where rows and columns are stored as readable text.

CSV is useful for exchange and transparency, but it is inefficient for large repeated time-series data. It repeats timestamps, strings and source labels many times.

In the old repo, raw CSV helped preserve the source data, but it made the working tree too large. In this repo, CSV is treated as transition source material, not the preferred storage format.

## Data Repository

A data repository is a repo whose primary job is to store and update datasets, not user interface code.

This repo exists because data and application code move at different speeds. The data can grow monthly while the app remains light.

The discipline is that the data repo should contain compact data, source registers, pipelines and audit evidence, not unrelated app code.

## DuckDB

DuckDB is an embedded analytical database engine.

It lets a script run SQL directly over files such as CSV and Parquet without needing a separate database server.

We used DuckDB because it can read many source CSV files, combine them, derive year and month fields from timestamps, and write partitioned Parquet quickly inside a GitHub Actions runner.

The key lesson from the backfill was that DuckDB can write partitioned output, but the top-level output folders must exist first on a clean runner. That is why the script now creates the generation and prices folders before writing.

## Elexon

Elexon is the GB electricity market data source used by this repo.

The repo uses Elexon data for generation and system price datasets.

The discipline is that Elexon source names, endpoints and cleaning keys must be documented so the data chain can be defended later.

## FUELHH

FUELHH is an Elexon half-hourly generation dataset.

In this repo it is used as the settled or confirmed half-hourly generation source.

It is important because FUELHH is better suited for confirmed historical reporting than fast provisional data.

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

## Snapshot Check

A snapshot check tests a value from one point in time.

The original 319 Parquet file count was a snapshot check.

It became a bug because the source data grew to 341 files. Snapshot checks should not be used as exact permanent laws for living datasets.

## Source of Truth

A source of truth is the authoritative place from which a dataset or fact is derived.

For this repo, Elexon is the external source of truth for GB electricity market data.

The old monolith is a transition source for the historical backfill, but the future source of truth should be the documented API pathway.

## System Prices

System prices are Elexon imbalance price data for GB electricity settlement periods.

In this repo they are stored separately from generation data because prices and generation have different meanings and cleaning keys.

The key used for prices is periodStartUTC.

## Workflow Dispatch

Workflow dispatch means manually starting a GitHub Actions workflow.

In this repo, the historical backfill is triggered by workflow dispatch because it is a controlled one-time operation.

Manual dispatch lets the operator choose when to run a high-impact workflow.

## zstd Compression

zstd is a compression method used inside the Parquet files.

It gives strong compression while remaining fast to read.

It was used because the dataset has many repeated values and should remain compact without becoming hard to query.
