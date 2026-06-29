# Monthly Updater Test Plan

Purpose: prove the monthly updater end to end before trusting the unattended schedule.

The historical backfill is now clean. The remaining open risk is the monthly updater, because it is the workflow intended to keep the dataset alive over time.

A README claim is not proof. A successful workflow run plus data-law verification is proof.

## Test target

Use `.github/workflows/monthly_update.yml` through manual workflow_dispatch.

Use `pipelines/fetch_latest_month.py` and `pipelines/fetch_elexon_api_to_parquet.py`.

Run one controlled complete month first.

Suggested test month: choose a month already present in the clean backfill and known to be complete.

Datasets: fuelinst fuelhh prices.

## Workflow inputs

start_date: first day of the chosen complete month.

end_date: last day of the chosen complete month.

refetch_months: 1.

datasets: fuelinst fuelhh prices.

## Expected behaviour

The workflow should fetch all three datasets for the target month.

The workflow should remove the touched month partition directories before rewriting.

The workflow should write fresh Parquet files for the touched month.

The workflow should write reports/latest_parquet_audit.json.

The workflow should write reports/fetch_latest_month_latest.json.

The workflow should commit generation, prices and reports only if the run succeeds.

## Required verification after run

Verify FUELINST duplicate key groups are zero for the touched month.

Verify FUELHH duplicate key groups are zero for the touched month.

Verify prices duplicate key groups are zero for the touched month.

Verify the audit report records the target month.

Verify the audit report records removedPartitionsBeforeRewrite.

Verify the audit report records idempotency keys.

Verify the commit changed only the expected month partitions and reports.

## Proof standard

A green workflow is not enough.

The test passes only if the workflow is green and the touched Parquet data passes the declared key uniqueness laws.

For FUELINST: total rows must equal distinct periodStartUTC plus fuelType.

For FUELHH: total rows must equal distinct time plus technology.

For prices: total rows must equal distinct periodStartUTC.

## Failure handling

If the workflow fails, do not patch broadly.

Capture the exact failed step and exact log line.

Patch only that layer.

Rerun the same controlled month.

Record the result in CHANGELOG.md.

## Status

Pending.

The monthly updater should be treated as implemented but not yet proven until this plan has been run and recorded.
