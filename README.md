# data-gb-electricity

GB electricity data repository for the GlobalGrid2050 federation.

This repository holds Great Britain electricity time-series in compact, partitioned Parquet form. It is the data layer for the federated successors of the old `globalgrid2050` monolith.

## Scope

This is **GB electricity**, not full UK electricity.

Elexon settles the Great Britain electricity market. Northern Ireland sits in the separate all-island Single Electricity Market. The distinction matters because interconnector and border-flow datasets can treat Moyle and related flows differently from domestic GB generation and demand.

## Data source register

The detailed source register is:

```text
DATA_SOURCES.md
```

It records the Elexon endpoints, trust status, grain, idempotency keys, cleaning rules and Parquet output paths.

## Source datasets

```text
FUELINST provisional 5-minute generation
endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST
status: candidate / provisional
idempotency key: periodStartUTC + fuelType

FUELHH settled half-hourly generation
endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH
status: confirmed / settled
idempotency key: time + technology

Elexon system prices
endpoint: https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/YYYY-MM-DD
status: price data
idempotency key: periodStartUTC
```

## Parquet layout

```text
generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet
generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet
prices/year=YYYY/month=M/data_0.parquet
```

Packaging rule:

```text
format: Parquet
compression: zstd
raw CSV committed here: no
monolith clone committed here: no
```

## One-time historical backfill

The historical backfill workflow is:

```text
.github/workflows/backfill_history.yml
```

It is manually triggered from GitHub Actions. It clones the retiring source repo inside the runner, runs:

```text
pipelines/port_csv_to_parquet.py
```

and commits only:

```text
generation/
prices/
reports/latest_parquet_audit.json
```

The backfill must match the known tripwires before it commits:

```text
source CSV:      ~1,218 MB
Parquet output:  ~33.6 MB
partition files: 319
canary rows:     156,960 rows in generation/dataset=fuelinst/year=2023/month=9
```

## Automated monthly updater

The active monthly process is:

```text
pipelines/fetch_latest_month.py
.github/workflows/monthly_update.yml
```

The workflow runs automatically once per month and fetches only the previous closed calendar month by default.

It does **not** repeatedly re-fetch the full history.

Default monthly behaviour:

```text
Run date: 2nd day of each month at 06:00 UTC
Date range fetched: previous complete calendar month
Datasets: fuelinst fuelhh prices
Output: rewritten month Parquet partitions and reports
Commit: generation/, prices/, reports/
```

Manual `workflow_dispatch` remains available for controlled testing, repair or explicit backfill ranges.

Example repair run:

```text
start_date: 2026-06-01
end_date: 2026-06-30
refetch_months: 1
datasets: fuelinst fuelhh prices
```

## Cleaning and merge discipline

Every run fetches the full touched calendar month, removes the existing touched partition, deduplicates the fetched records by stable key, and writes the month partition fresh.

```text
FUELINST: periodStartUTC + fuelType
FUELHH: time + technology
PRICES: periodStartUTC
```

This is how the repo avoids becoming another 1 GB CSV store.

## Reports

The monthly updater writes:

```text
reports/latest_parquet_audit.json
reports/fetch_latest_month_latest.json
```

The package verification record is:

```text
reports/package_verification_summary.json
```

The plain-language decision log is:

```text
HOW_WE_SOLVED_THE_DATA_ISSUES.md
```

## Query examples

Maximum provisional FUELINST generation by fuel:

```sql
SELECT fuelType, max(generationMW)
FROM read_parquet('generation/dataset=fuelinst/**/*.parquet')
GROUP BY fuelType
ORDER BY max(generationMW) DESC;
```

Settled FUELHH monthly MWh by technology:

```sql
SELECT
  year,
  month,
  technology,
  sum(generationMW * 0.5) AS mwh
FROM read_parquet('generation/dataset=fuelhh/**/*.parquet')
GROUP BY year, month, technology
ORDER BY year, month, technology;
```

## Governance

Rules:

- source endpoints must be logged in `DATA_SOURCES.md`;
- fetch through the data repo, not the app repo;
- write Parquet directly, not raw CSV;
- no raw CSV committed here;
- no app code here;
- no source repo clone committed here;
- monthly automation fetches only the previous complete month unless an explicit repair range is provided;
- failed API calls, empty results or schema problems must make the workflow go red.
