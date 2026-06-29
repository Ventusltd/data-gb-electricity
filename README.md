# data-gb-electricity

GB electricity data repository for the GlobalGrid2050 federation.

This repository is intended to hold Great Britain electricity time-series in partitioned Parquet form. It is the data layer for the federated successors of the old `globalgrid2050` monolith.

## Scope

This is **GB electricity**, not full UK electricity.

Elexon settles the Great Britain electricity market. Northern Ireland sits in the separate all-island Single Electricity Market. The distinction matters because interconnector and border-flow datasets can treat Moyle and related flows differently from domestic GB generation and demand.

## Source datasets

The current source-of-truth raw CSV lives in the retiring monolith:

```text
https://github.com/Ventusltd/globalgrid2050
```

The three source sets used for the first Parquet port are:

```text
FUELINST provisional 5-minute generation
source path: globalgrid2050/data/generation/archive/*/*.csv
schema: source, periodStartUTC, fuelType, generationMW, publishTimeUTC, fetchedAtUTC
status: candidate

FUELHH settled half-hourly generation
source path: globalgrid2050/data/generation/fuelhh_halfhourly/*/*.csv
schema: time, technology, generationMW, source
status: confirmed

Elexon system prices
source path: globalgrid2050/data/electricity/elexon_system_prices_*.csv
schema: source, settlementDate, settlementPeriod, periodStartUTC, systemBuyPriceGBPperMWh, systemSellPriceGBPperMWh, netImbalanceVolumeMWh, fetchedAtUTC
status: price data
```

## Tripwire counts

The first conversion must match these source counts:

```text
FUELINST = 72 CSV files
FUELHH   = 125 CSV files
PRICES   = 12 CSV files
```

The expected Parquet output from the tested recipe is approximately:

```text
source CSV:      ~1,218 MB
Parquet output:  ~33.6 MB
partition files: 319
canary rows:     156,960 rows in generation/dataset=fuelinst/year=2023/month=9
```

If these numbers differ materially, stop and inspect the source data or paths before committing.

## Parquet layout

Target layout:

```text
generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet
generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet
prices/year=YYYY/month=M/data_0.parquet
```

## Pipeline

Conversion script:

```text
pipelines/port_csv_to_parquet.py
```

Audit only:

```bash
python3 pipelines/port_csv_to_parquet.py --source-root ../globalgrid2050
```

Build and verify:

```bash
python3 pipelines/port_csv_to_parquet.py --source-root ../globalgrid2050 --apply
```

The script is deliberately strict. It checks source counts, writes partitioned Parquet, checks the total Parquet file count, checks output size range, and verifies the 2023-09 FUELINST canary row count.

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

## Regeneration path

```text
old monolith raw CSV -> pipelines/port_csv_to_parquet.py -> partitioned Parquet
```

The old monolith raw CSV is treated as cold-storage source of truth during the transition and is deliberately not committed here.

Do not commit raw CSV to this repo.

## Workflow templates

Workflow templates have been added under:

```text
workflow_templates/01-audit-source-counts.yml
workflow_templates/02-build-parquet.yml
```

The intended active workflow locations are:

```text
.github/workflows/01-audit-source-counts.yml
.github/workflows/02-build-parquet.yml
```

The audit workflow checks source file counts and writes an audit artifact.

The build workflow requires manual confirmation with:

```text
BUILD_PARQUET
```

It then builds verified Parquet and commits only generated Parquet outputs plus the audit report.

## Governance

Rules:

- audit before build;
- no raw CSV committed here;
- no app code here;
- no monolith copy here;
- no broad rewrite;
- one data concern per repo;
- verify tripwire numbers before committing output.

## TODO

TODO: live updater.

The old monolith automation that fetched new Elexon data does not belong in future app repos. A fresh live updater should be built later inside this data repo, appending or regenerating monthly Parquet partitions with the same audit-first discipline.
