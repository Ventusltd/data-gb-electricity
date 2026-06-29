# How We Solved the Data Issues

A plain-language log of the data decisions behind `data-gb-electricity`, so any future session understands why it is shaped this way. Newest entry at the top.

---

## 2026-06-29 — Backfill plus automated monthly updater

### What changed

The repo now has two data workflows:

```text
.github/workflows/backfill_history.yml
.github/workflows/monthly_update.yml
```

The first is a one-time historical backfill. The second is an automatic monthly updater.

### What we added

```text
pipelines/fetch_latest_month.py
.github/workflows/monthly_update.yml
.github/workflows/backfill_history.yml
```

The monthly workflow runs on a schedule and fetches only the previous complete calendar month by default. Manual dispatch remains available for testing and repair ranges.

### Why this is allowed

This is a deliberate exception to the usual manual-apply doctrine. It is justified because the operation is narrow, data-only, idempotent, and fail-loud. It writes compact Parquet partitions, not raw CSV or app code. Published facts are still verified by the human through the UI and independent checks.

### Guarantees

```text
FUELINST key: periodStartUTC + fuelType
FUELHH key: time + technology
PRICES key: periodStartUTC
Failure behaviour: API errors, empty returns or schema problems exit non-zero.
```

Touched month partitions are fetched for the full month, deduplicated and rewritten fresh. This prevents duplicate compounding over time.

### Known gap

The first successful workflow run still needs to be triggered and checked in GitHub Actions.

---

## 2026-06-29 — The 1.2 GB problem, diagnosed and solved

### What was wrong

The retiring `globalgrid2050` source tree carried a **1.2 GB** `data/generation/` directory. The cause was not complexity. It was verbosity. Elexon generation data was stored as raw CSV in long format: one row per timestamp per fuel, repeatedly storing timestamp strings, source text and fetch timestamps.

### Why it was confusing

The issue was not variety. It was the same structured data repeated in a storage-heavy format. Git compression hid some of this in reported repo size, but clone and working-tree size still suffered.

### What we did

Converted all three GB-electricity sources from CSV to partitioned Parquet with zstd compression:

```text
FUELINST: 72 files
FUELHH: 125 files
Elexon system prices: 12 files
```

Verified result:

```text
source CSV: approximately 1,218 MB
Parquet output: approximately 33.6 MB
partition files: 319
FUELINST 2023 month 9 canary: 156,960 rows
```

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

```text
## YYYY-MM-DD — short title
### What changed
### What we added
### Why
### Verification
### Known gap
```
