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

The three active datasets are:

```text
FUELINST provisional 5-minute generation
endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST
schema: source, periodStartUTC, fuelType, generationMW, publishTimeUTC, fetchedAtUTC, dataset
status: candidate / provisional
idempotency key: periodStartUTC + fuelType

FUELHH settled half-hourly generation
endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH
schema: time, technology, generationMW, source, dataset
status: confirmed / settled
idempotency key: time + technology

Elexon system prices
endpoint: https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/YYYY-MM-DD
schema: source, settlementDate, settlementPeriod, periodStartUTC, systemBuyPriceGBPperMWh, systemSellPriceGBPperMWh, netImbalanceVolumeMWh, fetchedAtUTC
status: price data
idempotency key: settlementDate + settlementPeriod
```

## Parquet layout

Target layout:

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

## Automated monthly updater

The active monthly process is:

```text
pipelines/fetch_elexon_api_to_parquet.py
.github/workflows/elexon_api_to_parquet_monthly.yml
```

The workflow runs automatically once per month and fetches only the previous closed calendar month by default.

It does **not** repeatedly re-fetch the full history.

Default monthly behaviour:

```text
Run date: 7th day of each month at 03:17 UTC
Date range fetched: previous calendar month
Datasets: fuelinst fuelhh prices
Output: merged Parquet partitions and reports
Commit: generation/, prices/, reports/
```

Manual `workflow_dispatch` remains available only for controlled repair or explicit backfill ranges.

Example repair run:

```text
start_date: 2026-06-01
end_date: 2026-06-30
datasets: fuelinst fuelhh prices
commit_outputs: true
```

## Cleaning and merge discipline

Every run merges into month partitions by stable keys so re-runs overwrite rather than duplicate:

```text
FUELINST: periodStartUTC + fuelType
FUELHH: time + technology
PRICES: settlementDate + settlementPeriod
```

The updater reads any existing partition, merges the newly fetched rows, sorts by key, then writes the same month partition back as zstd Parquet.

This is how the repo avoids becoming another 1 GB CSV store.

## Historical port record

The first historical conversion was proven with these tripwires:

```text
source CSV:      ~1,218 MB
Parquet output:  ~33.6 MB
partition files: 319
canary rows:     156,960 rows in generation/dataset=fuelinst/year=2023/month=9
```

The historical conversion script remains available as the reproducibility record:

```text
pipelines/port_csv_to_parquet.py
```

It converts the retiring monolith raw CSV into the same partitioned Parquet layout. The old monolith raw CSV is treated as cold-storage source of truth during transition and is deliberately not committed here.

## DuckDB query examples

Maximum provisional FUELINST generation by fuel:

```sql
SELECT fuelType, max(generationMW)
FROM read_parquet('generation/dataset=fuelinst/**/*.parquet')
GROUP BY fuelType
ORDER BY max(generationMW) DESC;
```

Settled FUELHH monthly MWh by technology can be derived from half-hourly MW values using the correct grain rule:

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

## Reports

The monthly updater writes:

```text
reports/elexon_api_to_parquet_latest.json
reports/elexon_api_to_parquet_latest.md
reports/elexon_api_to_parquet_YYYYMMDDTHHMMSSZ.json
```

The package verification record is:

```text
reports/package_verification_summary.json
```

The plain-language decision log is:

```text
HOW_WE_SOLVED_THE_DATA_ISSUES.md
```

## Governance

Rules:

- source endpoints must be logged in `DATA_SOURCES.md`;
- fetch through the data repo, not the app repo;
- write Parquet directly, not raw CSV;
- no raw CSV committed here;
- no app code here;
- no monolith clone here;
- no broad rewrite;
- one data concern per repo;
- monthly automation fetches only the previous month unless an explicit repair range is provided.
