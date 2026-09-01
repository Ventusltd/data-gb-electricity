# Monthly updater proof plan

Purpose: prove that unattended updates fill bounded gaps while preserving
historic Parquet bytes.

## Local gates

Run on Windows and Linux:

```text
python -m unittest discover -s tests -v
python pipelines/fetch_latest_month.py --plan-only --refetch-months 3
```

The tests include diseased fixtures. They must show that a historical
modification, unplanned partition, raw CSV and excess byte growth all make the
repository-diff gate fail. The GB calendar fixtures must prove 46 settlement
periods on the spring clock-change day and 50 on the autumn day without an
external timezone package.

`--plan-only` must make no network call and no write. Inspect every
dataset-month decision before enabling a live fetch.

## First controlled GitHub Actions run

Use `.github/workflows/monthly_update.yml` through `workflow_dispatch`.

Choose an already present, complete month and leave `repair_existing` false.
Expected result: all selected datasets say `SKIP_FROZEN`, no API request is
made for them, no Parquet changes, and no data commit is created.

Then choose one closed month with a genuinely missing dataset partition.
Expected result: that dataset-month says `ADD_MISSING`; every existing selected
partition says `SKIP_FROZEN`; exactly one `data_0.parquet` is added for each
missing dataset-month.

## Required evidence

The workflow must be green, but green alone is insufficient. Retain both:

- `reports/fetch_latest_month_latest.json`, which records the selection plan,
  row counts, limits, schema/key checks and before/after package size;
- `reports/bounded_growth_gate_latest.json`, which records the actual Git diff
  and proves it matches the plan.

For every written partition verify the declared data law:

- FUELINST: rows equal distinct `periodStartUTC` plus `fuelType`;
- FUELHH: rows equal distinct `time` plus `technology`;
- prices: rows equal distinct `periodStartUTC`.

Verify tracked historical Parquet outside the plan is byte-identical to the
parent commit. Verify no raw CSV, API response dump or timestamped audit archive
was added.

## Explicit repair proof

Only after normal mode passes, run one known complete month with explicit
`start_date`, `end_date` and `repair_existing=true`.

The audit must say `EXPLICIT_REPAIR`. Only selected dataset-month directories
may change. Replacement `data_0.parquet` must pass pending-file readback before
the old file is replaced. Any stale `data_N.parquet` shard may be removed only
inside that authorised partition and only after readback succeeds.

## Failure handling

Do not raise a growth limit to make a surprising run green. Preserve the audit
artifact, identify whether the source expanded legitimately or the query scope
escaped, and change one layer at a time. A limit change is a reviewed code
change, never a workflow input.

## Status

Local policy, DST, atomic-write and diseased growth-gate fixtures pass. The
first controlled GitHub `workflow_dispatch` remains required before the
schedule should be considered production-proven.
