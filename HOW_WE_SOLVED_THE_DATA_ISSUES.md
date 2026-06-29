# How We Solved the Data Issues

A plain-language log of the data decisions behind `data-gb-electricity`, so any future session understands why it is shaped this way. Newest entry at the top.

---

## 2026-06-29 — Backfill failure logic hardened

### What happened

The historical backfill was failing after several runs, but the failures were not proof that the data model was wrong.

They were proof that the workflow was still carrying assumptions from a static package rather than a living reproducible data pipeline.

The final diagnosis is now clear.

The conversion step successfully generated valid Parquet output on the GitHub runner. The current runner output observed in the failed run was 341 Parquet files, about 33.871 MB, with the settled FUELINST 2023 month 9 canary still holding at 156,960 rows.

The data was therefore not corrupt. The script failed because it still required exactly 319 Parquet files, which was only the count from an earlier snapshot.

The source repo had grown since that earlier measurement. More source months created more year and month partitions. That is expected behaviour for a living dataset.

### Failure sequence

First, DuckDB failed because the clean runner did not already have the top-level generation and prices folders. That was fixed by creating those folders before writing Parquet.

Second, the build succeeded but the commit step was too fragile. It could fail on a missing optional report path, and it also ran an unnecessary pull rebase before every push. That was fixed by adding output folders only if they exist, adding reports as a folder when present, pushing directly first, and rebasing only if the first push is rejected.

Third, the build succeeded again but the verification logic treated a growing output count as a fixed law. The script expected exactly 319 Parquet files. The live runner produced 341. That was fixed by changing the Parquet count from an exact equality to a minimum baseline.

### The rule learned

A good test asserts an invariant, not a snapshot.

A settled historical canary is an invariant. FUELINST 2023 month 9 must remain 156,960 rows. If that changes, something is genuinely wrong.

A total Parquet file count is not an invariant. It is a moving snapshot. It should be recorded and monitored, but it should not fail the pipeline merely because the source data grew.

Source file counts and Parquet partition counts are now treated as minimum baselines rather than exact permanent numbers.

The canary remains a hard equality.

### Current patch state

The mkdir fix is in `pipelines/port_csv_to_parquet.py`.

The hardened commit and push logic is in `.github/workflows/backfill_history.yml`.

The same commit step hardening is also in `.github/workflows/monthly_update.yml`.

The Parquet file count check is now a floor rather than an exact equality in `pipelines/port_csv_to_parquet.py`.

The canary row check remains strict.

### Known gap

One final fresh workflow dispatch is still required to prove the full path end to end: build, verify, commit and push.

Confidence is high because the remaining failure was a false snapshot assert, not bad data.

---

## 2026-06-29 — Backfill plus automated monthly updater

### What changed

The repo now has two data workflows.

`.github/workflows/backfill_history.yml` is the one-time historical backfill.

`.github/workflows/monthly_update.yml` is the automatic monthly updater.

The monthly workflow runs on a schedule and fetches only the previous complete calendar month by default. Manual dispatch remains available for testing and repair ranges.

### What we added

`pipelines/fetch_latest_month.py`

`.github/workflows/monthly_update.yml`

`.github/workflows/backfill_history.yml`

### Why this is allowed

This is a deliberate exception to the usual manual-apply doctrine. It is justified because the operation is narrow, data-only, idempotent, and fail-loud. It writes compact Parquet partitions, not raw CSV or app code. Published facts are still verified by the human through the UI and independent checks.

### Guarantees

FUELINST key: periodStartUTC plus fuelType.

FUELHH key: time plus technology.

PRICES key: periodStartUTC.

Failure behaviour: API errors, empty returns, schema problems or true canary corruption exit non-zero.

Touched month partitions are fetched for the full month, deduplicated and rewritten fresh. This prevents duplicate compounding over time.

### Known gap

The first successful end-to-end backfill run still needs to be triggered and checked in GitHub Actions after the latest hardening patch.

---

## 2026-06-29 — The 1.2 GB problem, diagnosed and solved

### What was wrong

The retiring `globalgrid2050` source tree carried a 1.2 GB `data/generation/` directory. The cause was not complexity. It was verbosity. Elexon generation data was stored as raw CSV in long format: one row per timestamp per fuel, repeatedly storing timestamp strings, source text and fetch timestamps.

### Why it was confusing

The issue was not variety. It was the same structured data repeated in a storage-heavy format. Git compression hid some of this in reported repo size, but clone and working-tree size still suffered.

### What we did

Converted all three GB-electricity sources from CSV to partitioned Parquet with zstd compression.

The original verified package contained 72 FUELINST files, 125 FUELHH files and 12 Elexon system price files.

The original verified package produced about 33.6 MB of Parquet across 319 partition files, with the FUELINST 2023 month 9 canary at 156,960 rows.

The live runner later observed 341 Parquet files because the source repo had grown. This is expected and healthy. The 319 figure is now treated as a minimum baseline, not a permanent equality.

### Why Parquet

CSV stores row by row and repeats strings. Parquet stores column by column, compresses repeated values well, preserves row-level granularity, and remains queryable.

### Why a separate repo

Code and data have different clocks. The app should stay small. The data repo can grow deliberately, while app repos fetch compact data from it.

### Why the raw CSV is not committed here

The old raw CSV is treated as cold-storage source of truth during transition. This repo stores distilled Parquet and reproducible scripts, not raw CSV bulk.

### Bug remembered

The first conversion attempt used `substr()` on timestamp columns. DuckDB parsed them as TIMESTAMP, so the fix was to use `year()` and `month()` date functions.

---

## Template for future entries

## YYYY-MM-DD — short title

### What changed

### What we added

### Why

### Verification

### Known gap
