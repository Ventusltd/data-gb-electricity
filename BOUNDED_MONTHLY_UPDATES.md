# Bounded monthly updates

The forward updater is append-only at dataset-month partition grain during a
normal run. “Append-only” does not mean appending rows to one growing file. It
means adding one compressed Parquet file for a missing closed month and leaving
every existing historical partition byte-for-byte unchanged.

## Normal scheduled run

The workflow inspects the latest three complete UTC partition months after the
corresponding GB calendar month has closed.
For each of `fuelinst`, `fuelhh` and `prices` it makes one of two decisions:

- `SKIP_FROZEN`: at least one Parquet file already exists; make no API request
  and do not touch its bytes.
- `ADD_MISSING`: no Parquet exists; fetch that complete dataset-month, validate
  it and create `data_0.parquet`.

The current history therefore catches up bounded gaps without repeatedly
rewriting the latest three months. Once caught up, the ordinary monthly growth
is at most three files: one new closed month for each dataset.

## Explicit repair

Source corrections sometimes require a historical replacement. That is not
disguised as a normal update. It requires all three of:

1. an explicit start date;
2. an explicit end date;
3. `--repair-existing`.

The same dataset-month, row, file, byte and API-request ceilings apply. A verified pending
Parquet file is written and read back before `data_0.parquet` is replaced.
Additional stale shards in that one authorised partition are removed only after
the replacement has passed schema and key-uniqueness checks.

## Hard limits

The unattended workflow permits at most:

- 9 written dataset-months;
- 2,000,000 fetched rows;
- 9 written Parquet files;
- 134,217,728 written Parquet bytes.
- 200 estimated upstream API requests.
- 600 maximum HTTP attempts including retries.

These are stop conditions, not monitoring thresholds. Exceeding one makes the
job fail before a commit. Raising a limit is a reviewed source change.

## Two independent gates

`fetch_latest_month.py` enforces the plan before and during collection. It
fetches and validates every response before its first write, rejects rows
outside the authorised month, and rechecks partition existence just before the
write to close a concurrent-run race.

`verify_bounded_growth.py` then reads the audit plan and Git's actual working
tree diff. A normal run fails if it modifies or deletes tracked history, writes
an unplanned month, commits raw/CSV data, or exceeds its file/byte limits.

The audit reports remain small moving pointers in `reports/`. Historical data
remains in Parquet rather than accumulating one JSON report per run.

## Local proof without network

```text
python -m unittest discover -s tests -v
python pipelines/fetch_latest_month.py --plan-only --refetch-months 3
```

The plan command performs no API calls and no writes. On the 2026-09-01
baseline it freezes existing June FUELINST/prices and identifies exactly seven
missing dataset-months across June, July and August.
