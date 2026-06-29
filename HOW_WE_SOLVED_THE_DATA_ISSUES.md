# How We Solved the Data Issues

A plain-language log of the data decisions behind `data-gb-electricity`, so any future session understands why it is shaped this way. Newest entry at the top.

---

## 2026-06-29 — Monthly autonomous API-to-Parquet updater added

### What changed

The data repo now has its own Elexon API fetch and packaging mechanism. It no longer depends on browser uploads, manual CSV handling, or the old monolith for new monthly data.

### What we added

```text
pipelines/fetch_elexon_api_to_parquet.py
.github/workflows/elexon_api_to_parquet_monthly.yml
DATA_SOURCES.md
```

The workflow runs automatically once per month and fetches the previous closed calendar month by default. `workflow_dispatch` remains available for explicit repair ranges.

### Why

The repo must independently log data sources, fetch from Elexon using GitHub runners, clean the records, package the data into compact Parquet, and avoid accumulating raw CSV.

### Packaging rule

```text
generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet
generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet
prices/year=YYYY/month=M/data_0.parquet
```

The updater merges by stable keys so re-runs overwrite rather than duplicate:

```text
FUELINST: periodStartUTC + fuelType
FUELHH: time + technology
PRICES: settlementDate + settlementPeriod
```

### Known gap

The historical Parquet package remains verified. The new monthly updater solves the ongoing data issue going forward and can be used for controlled repair or backfill ranges where needed.

---

## 2026-06-29 — The 1.2 GB problem, diagnosed and solved

### What was wrong

The retiring `globalgrid2050` monolith carried a **1.2 GB** `data/generation/` directory. The cause was not complexity. It was verbosity. Elexon generation data was stored as raw CSV in long format: one row per timestamp per fuel, repeatedly storing timestamp strings, source text and fetch timestamps.

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

The old monolith raw CSV is treated as cold-storage source of truth during transition. This repo stores distilled Parquet and reproducible scripts, not raw CSV bulk.

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
