# Daily historical system-sell prices

`price_daily_browser.py` derives small, lazy-loadable annual JSON products and
one full-row ZSTD Parquet file from every physical `prices/**/data_*.parquet`
part in this data-owner repository. It fetches no new data and changes no raw
source history. The existing rollup workflow maintains both products.

The input is **Elexon system-sell price**, in GBP/MWh. It is not market-index
price, a consumer tariff, a project revenue forecast or a realtime quote. The
products do not mix price bases. Consumers must display the actual last date
from `index.json` and preserve gaps, partial coverage and the quality counters.

## Calendar and inherited clock quality

Daily groups use the source-declared `settlementDate` plus `settlementPeriod`,
matching the existing yearly rollup's date basis. Expected counts are derived
from consecutive Europe/London midnights: 46, 48 or 50 periods. Dates with no
rows are explicit `NO_OBSERVATIONS` rows with null prices. A day is
`COMPLETE_SOURCE_DAY` only when every expected, unique period has a price;
otherwise it is `PARTIAL_SOURCE_DAY`. The existing rollup's 24-period inclusion
floor never certifies completeness here.

Legacy stored `periodStartUTC` values can disagree with the declared GB date
and period. This product reports `utc_alignment_mismatches` per day and in the
index/source manifest, while preserving both identities in upstream history.
For example, older summer rows can store midnight UTC for period 1 rather than
the preceding 23:00 UTC; the 2016 autumn clock collision also leaves 31 October
without periods 1 and 2. It does not repair timestamps, reconstruct lost rows,
impute prices or certify intraday alignment. `COMPLETE_SOURCE_DAY` describes
declared-period coverage and does not override the separate clock counter.

The current 2016-01-01 through 2026-10-31 snapshot has 189,270 observed prices,
3,957 calendar dates, 3,919 complete source days, 25 partial source days and
13 missing dates. There are 106,668 inherited UTC alignment disagreements.
These are snapshot facts, not future coverage targets.

## Product contract and verification

`index.json` names each annual JSON file and its exact byte count/SHA-256. It
also pins `sources.json` and `daily.parquet`, records the producer SHA-256 and
DuckDB version, and states the price/time bases. `sources.json` pins all input
file bytes and SHA-256 values, their original stored-UTC range and grain checks.
Annual files contain the date, expected/observed/priced periods, coverage
status, clock mismatch count, available-price mean, minimum and maximum.

Means use every available source price, retaining negative values and null
gaps. Decimal arithmetic starts from the exact stored IEEE-754 values and
rounds to six decimal places using half-even. There is no interpolation or
smoothing. Every output Parquet row is compared with the complete JSON-row
values after a ZSTD readback. Original stored UTC keys and declared date/period
pairs must each be unique; impossible declared periods reject the build.

```sh
python -B -m unittest discover -s tests -v
python -B derived/price_daily_browser.py
python -B derived/price_daily_browser.py --verify
```

DuckDB 1.3.2 is pinned in the existing owner workflow for reproducible output.
Verification rebuilds into a temporary directory and compares every product
byte and the complete output inventory. Source hashes are checked before and
after compilation. Validation finishes before replacement, and `index.json`
is written last. No browser chart or homepage pointer is changed by this data
producer; chart integration remains with the chart and release owners.
