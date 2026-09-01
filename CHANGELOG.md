# Changelog

Plain-language project change log for `data-gb-electricity`. Newest entries first.

---

## 2026-09-01 — Monthly growth made bounded and history-preserving

The scheduled updater no longer deletes and rewrites three recent months on
every run. It inspects them and fetches only missing dataset-month partitions.
Existing Parquet is frozen unless an operator supplies an explicit date range
and separately enables repair mode.

Hard limits now cover dataset-months, fetched rows, Parquet files, Parquet
bytes and estimated API requests. All responses are collected and validated
before the first write. GB settlement-date endpoints receive a boundary buffer,
then only rows in the authorised UTC partition month are retained.

A second gate compares the audit plan with Git's actual diff. It fails on a
normal historical modification, an unplanned partition, raw data, or excessive
growth before CI may commit anything. Twenty-one local fixtures include diseased
cases for each of those failures, atomic Parquet readback, concurrent partition
appearance, and the 46/50-period GB clock-change days.

All 456 checked-in Parquet files are also schema canaries. The audit caught and
corrected the unproven helper's price-schema drift before a new month was
written: the established package uses `date32` settlement dates and `int64`
settlement periods.

The direct helper's write switch is disabled so it cannot bypass these limits.
The one-time full backfill now requires an explicit confirmation phrase.

The first controlled workflow dispatch remains required before the unattended
schedule is considered production-proven.

---

## 2026-06-29 — First clean historical backfill verified

The corrected historical backfill has run and landed clean data on main.

The repository now contains 456 Parquet files. That larger file count is expected because the current source data is larger than the original test package and because DuckDB can split a single partition into more than one physical file.

The important result is not the file count. The important result is the row-level key audit.

Prices were checked across 126 partitions. Total rows equal distinct periodStartUTC values in every partition. Duplicate key groups are zero.

FUELHH was checked across 126 partitions. Total rows equal distinct time plus technology keys in every partition. Duplicate key groups are zero.

FUELINST was checked across 67 partitions. Total rows equal distinct periodStartUTC plus fuelType keys in every partition. Duplicate key groups are zero.

The FUELINST 2023 month 9 canary still holds exactly at 156,960 rows.

The earlier doubled price data on main has been replaced.

The remaining data_1.parquet files are now benign DuckDB physical splits, not duplicate-row evidence. The test is not whether every partition has only one physical file. The test is whether every partition has one row per declared key.

This is the first clean state suitable for a serious citable snapshot.

---

## 2026-06-29 — Duplicate source overlap fixed

A row-level audit found that the first landed price data was doubled.

The cause was overlapping source files. The script read both per-year system price files and a combined all-years system price file.

The fix excluded combined overlapping source files and added key-level deduplication before writing.

The strict keys are now:

FUELINST: periodStartUTC plus fuelType.

FUELHH: time plus technology.

Prices: periodStartUTC.

The backfill now fails if duplicate key groups remain.

The monthly updater was also hardened so touched month partition directories are removed before rewrite, preventing stale extra files from surviving a clean monthly update.

---

## 2026-06-29 — Snapshot checks replaced with living-data checks

The original backfill script treated 319 Parquet files as a permanent exact number.

That was wrong because the dataset is living and the source repo grew.

The Parquet file count is now treated as a minimum baseline rather than an exact equality.

The total Parquet size check was also changed away from a fixed upper ceiling. Total size is a living quantity and should not fail merely because the source data grew.

The canary remains strict because settled history should not change.

The duplicate-key check is strict because duplicate keys are a real data-quality defect.

---

## 2026-06-29 — Backfill workflow hardened

The early workflow failures were caused by clean-runner assumptions and fragile commit logic.

The script now creates the top-level generation and prices folders before DuckDB writes partitioned output.

The workflow commit step now adds output folders only if they exist and pushes directly first, rebasing only if the first push is rejected.

The workflow is designed to fail loudly on real data or build errors, not on optional report-path fragility.

---

## 2026-06-29 — Historical data moved from raw CSV concept to compact Parquet concept

The retiring source tree carried about 1.2 GB of raw or near-raw CSV generation data.

The data repo uses compact partitioned Parquet with zstd compression instead.

The purpose is to preserve row-level analytical detail while keeping the repository small enough to clone, audit and build on.

This supports the Global Grid OS mission: cloneable, verifiable and regenerable data, not a static opaque upload.
