# GB Electricity Data Sources

Status: active source register  
Repository: `Ventusltd/data-gb-electricity`

This file records the upstream sources used by this repository. It is deliberately separate from the app layer so the data repo can explain where its data came from, how it is fetched, how it is cleaned and how it is packaged.

## Scope

This repository is for **Great Britain electricity** data.

It is not a full United Kingdom electricity dataset because Northern Ireland is part of the separate all-island SEM market. This distinction matters for market settlement and interconnector treatment.

## Source 1 — FUELINST generation

```text
Name: Elexon BMRS FUELINST
Endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST
Trust status: candidate / provisional
Grain: 5-minute generation snapshot by fuel type
Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option
Query pattern: publishDateTimeFrom, publishDateTimeTo, format=json
Idempotency key: periodStartUTC + fuelType
Output path: generation/dataset=fuelinst/year=YYYY/month=M/data_0.parquet
```

Purpose:

FUELINST provides the recent, provisional generation signal. It is useful for tracker freshness and grid-behaviour analysis, but it must not be treated as settled historic truth.

Cleaning rule:

Rows are normalised to:

```text
source
periodStartUTC
fuelType
generationMW
publishTimeUTC
fetchedAtUTC
dataset
```

Re-runs overwrite matching `(periodStartUTC, fuelType)` rows rather than appending duplicates.

## Source 2 — FUELHH generation

```text
Name: Elexon BMRS FUELHH
Endpoint: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH
Trust status: confirmed / settled
Grain: half-hourly generation by fuel type, normalised into technology buckets
Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option
Query pattern: settlementDateFrom, settlementDateTo, format=json
Idempotency key: time + technology
Output path: generation/dataset=fuelhh/year=YYYY/month=M/data_0.parquet
```

Purpose:

FUELHH is the confirmed historic generation source. It is the correct basis for settled history, monthly totals and higher-trust generation analysis.

Cleaning rule:

Rows are deduplicated by timestamp and source fuel, grouped into technology buckets, then written as:

```text
time
technology
generationMW
source
dataset
```

Technology bucket mapping:

```text
Solar: SOLAR, PV
Wind: WIND
Hydro: NPSHYD, HYDRO
Gas: CCGT, OCGT
Coal: COAL
Biomass: BIOMASS
Nuclear: NUCLEAR
Pumped Storage: PS
Imports & Exports: INT
Other: fallback bucket
```

Re-runs overwrite matching `(time, technology)` rows rather than appending duplicates.

## Source 3 — Elexon system prices

```text
Name: Elexon BMRS system / imbalance prices
Endpoint: https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/YYYY-MM-DD
Trust status: price data
Grain: half-hourly settlement period
Fetch cadence in this repo: monthly autonomous refresh, with manual workflow_dispatch option
Query pattern: one date per request, format=json
Idempotency key: settlementDate + settlementPeriod
Output path: prices/year=YYYY/month=M/data_0.parquet
```

Purpose:

System prices provide the half-hourly price signal used by GB electricity tracking and future price-aware applications.

Cleaning rule:

Rows are normalised to:

```text
source
settlementDate
settlementPeriod
periodStartUTC
systemBuyPriceGBPperMWh
systemSellPriceGBPperMWh
netImbalanceVolumeMWh
fetchedAtUTC
```

Re-runs overwrite matching `(settlementDate, settlementPeriod)` rows rather than appending duplicates.

## Packaging rule

The data package is Parquet, not raw CSV.

```text
compression: zstd
partition scheme: dataset=/year=/month= for generation; year=/month= for prices
raw CSV committed here: no
monolith clone committed here: no
```

Reason:

The old monolith reached approximately 1.2 GB of verbose CSV. The tested Parquet package reduced that to approximately 33.6 MB while preserving row-level granularity.

## Fetch implementation

The active fetch and packaging script is:

```text
pipelines/fetch_elexon_api_to_parquet.py
```

The monthly GitHub Action is:

```text
.github/workflows/elexon_api_to_parquet_monthly.yml
```

The workflow runs once per month and can also be triggered manually for a controlled backfill or repair range.

## Reports

Each run writes:

```text
reports/elexon_api_to_parquet_latest.json
reports/elexon_api_to_parquet_latest.md
reports/elexon_api_to_parquet_YYYYMMDDTHHMMSSZ.json
```

These reports log date range, datasets, endpoint names, idempotency keys, rows fetched and partitions touched.
