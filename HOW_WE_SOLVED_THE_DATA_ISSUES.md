# How We Solved the Data Issues

A plain-language log of the data decisions behind `data-gb-electricity`, so any
future session (human or AI) understands *why* it is shaped this way — not just
what is here. Newest entry at the top.

---

## 2026-06-29 — The 1.2 GB problem, diagnosed and solved

### What was wrong
The retiring `globalgrid2050` monolith carried a **1.2 GB** `data/generation/`
directory. The cause was not complexity — it was **verbosity**. Elexon
generation data was stored as raw CSV in "long format": one row per timestamp
per fuel, every row repeating the full ISO timestamp (twice), the source string,
and a fetch timestamp. One month of 5-minute FUELINST data = ~157,000 rows =
16 MB. Seventy-two months ≈ 1.15 GB. It was the **same dataset recorded
verbosely**, never aggregated or compressed.

### Why it was confusing
The brain looks for 1.2 GB of *variety* and there is none — there is 1.2 GB of
*the same thing*. GitHub's reported size (~77 MB) hid it, because Git's packfile
already dedupes the repetition. The bulk only bites on clone time, not on the
Pages limit.

### What we did
Converted all three GB-electricity sources from CSV to **partitioned Parquet
(zstd)**:

- FUELINST 5-min generation (72 files)
- FUELHH half-hourly generation (125 files)
- Elexon system prices (12 files)

**Result: 1,218 MB CSV → 33.6 MB Parquet (~36× smaller), 319 partition files,
row counts identical to source.** Verified with an integrity canary
(2023-09 FUELINST = 156,960 rows in source and in Parquet).

### Why Parquet, not CSV/JSON
CSV stores row-by-row, repeating every string on every row. Parquet stores
**column-by-column**, so a column that is mostly repetition (19 fuel names over
and over) collapses to almost nothing. Zero data lost; every 5-minute reading
preserved. This keeps the granularity needed for grid/BESS/power-electronics
analysis while removing the bloat.

### Why a separate repo (not app + data together)
Code is small, cloned often, changes on bugfixes. Data is large, cloned rarely,
changes on a schedule. Different clocks → different homes. Keeping data out of
the app repo is what lets the app stay instantly clonable while the data grows
to gigabytes. The app fetches data by URL / queries it; it never clones it.

### Why the raw CSV is NOT committed here
The raw monolith CSV is the **cold-storage source of truth**. This repo commits
the *distilled* Parquet (34 MB), not the 1.2 GB raw. Raw is regenerable; see
`pipelines/port_csv_to_parquet.py`.

### One bug worth remembering
The first conversion attempt used `substr()` to pull year/month from the
timestamp column. It failed: DuckDB's `read_csv_auto` parses those columns as
TIMESTAMP type, so `substr` throws a binder error. Fix: use `year()` / `month()`
date functions. The committed script already does this.

### Known gap (intentional, not an oversight)
**Live updater not yet built.** The old monolith automation that fetched fresh
Elexon data was switched off during federation. The job that appends new monthly
Parquet still has to be built, and it belongs in THIS data repo, not the app.
Tracked in README under "TODO: live updater".

---

## Template for future entries

```
## YYYY-MM-DD — <short title>
### What was wrong / what changed
### What we did
### Why (the decision and its tradeoff)
### Verification (numbers, canary, what was checked)
### Known gaps left open
```
