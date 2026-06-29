#!/usr/bin/env python3
"""Monthly Elexon API fetcher for data-gb-electricity.

Default behaviour:
  * fetch the most recent complete calendar month plus a trailing lookback;
  * fetch only requested month(s), not full history;
  * fail loudly on API/schema/empty-data/duplicate-key problems;
  * remove and rewrite each touched month partition fresh as zstd Parquet;
  * write a lightweight audit report for the GitHub Actions run.

This script delegates endpoint parsing and Parquet writing helpers to the
hardened Elexon helper so the updater uses the same key and schema discipline as
the verified historical backfill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fetch_elexon_api_to_parquet_hardened import (
    fetch_fuelhh,
    fetch_fuelinst,
    fetch_prices,
    partition_file,
    write_records,
    utc_now_text,
)

DATASETS = ("fuelinst", "fuelhh", "prices")
LONDON = ZoneInfo("Europe/London")


def previous_complete_month(today: dt.date | None = None) -> tuple[int, int]:
    today = today or dt.datetime.now(LONDON).date()
    first_this_month = dt.date(today.year, today.month, 1)
    last_prev_month = first_this_month - dt.timedelta(days=1)
    return last_prev_month.year, last_prev_month.month


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + offset
    return idx // 12, idx % 12 + 1


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = dt.date(year, 12, 31) if month == 12 else dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    yesterday = dt.datetime.now(LONDON).date() - dt.timedelta(days=1)
    return start, min(end, yesterday)


def months_from_range(start: dt.date, end: dt.date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = shift_month(y, m, 1)
    return months


def parquet_audit() -> dict[str, Any]:
    files = list(Path("generation").glob("**/*.parquet")) + list(Path("prices").glob("**/*.parquet"))
    total_bytes = sum(p.stat().st_size for p in files if p.exists())
    return {
        "parquetFileCount": len(files),
        "parquetTotalMB": round(total_bytes / 1048576, 3),
        "generationFuelinstMB": round(sum(p.stat().st_size for p in Path("generation/dataset=fuelinst").glob("**/*.parquet")) / 1048576, 3),
        "generationFuelhhMB": round(sum(p.stat().st_size for p in Path("generation/dataset=fuelhh").glob("**/*.parquet")) / 1048576, 3),
        "pricesMB": round(sum(p.stat().st_size for p in Path("prices").glob("**/*.parquet")) / 1048576, 3),
    }


def remove_existing_partitions(dataset: str, months: list[tuple[int, int]], apply: bool) -> list[str]:
    removed: list[str] = []
    if not apply:
        return removed
    for year, month in months:
        path = partition_file(dataset, year, month)
        partition_dir = path.parent
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
            removed.append(str(partition_dir))
    return removed


def fail_if_empty(dataset: str, rows: list[dict[str, Any]], year: int, month: int) -> None:
    if not rows:
        raise RuntimeError(f"{dataset} returned zero rows for {year}-{month:02d}; refusing to write empty or partial partition")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest complete Elexon month and write compact Parquet")
    parser.add_argument("--start-date", help="Optional repair/backfill start date; expanded to full calendar month(s).")
    parser.add_argument("--end-date", help="Optional repair/backfill end date; expanded to full calendar month(s).")
    parser.add_argument("--refetch-months", type=int, default=3, help="Number of recent complete months to fetch when start/end are omitted. Default 3.")
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS), choices=list(DATASETS))
    parser.add_argument("--fuelinst-window-days", type=int, default=1)
    parser.add_argument("--fuelhh-window-days", type=int, default=7)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--request-delay-seconds", type=float, default=1.5)
    parser.add_argument("--apply", action="store_true", help="Write Parquet. Omit for dry run.")
    args = parser.parse_args()

    if args.start_date or args.end_date:
        if not (args.start_date and args.end_date):
            raise SystemExit("start-date and end-date must be supplied together for repair/backfill ranges")
        start = dt.date.fromisoformat(args.start_date)
        end = dt.date.fromisoformat(args.end_date)
        target_months = months_from_range(start, end)
    else:
        if args.refetch_months < 1:
            raise SystemExit("refetch-months must be >= 1")
        py, pm = previous_complete_month()
        target_months = [shift_month(py, pm, -i) for i in range(args.refetch_months - 1, -1, -1)]

    print(f"target months: {', '.join(f'{y}-{m:02d}' for y, m in target_months)}")
    print(f"datasets: {', '.join(args.datasets)}")
    print(f"apply: {args.apply}")

    fetched: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in args.datasets}
    per_month_counts: dict[str, dict[str, int]] = {}

    for year, month in target_months:
        start, end = month_bounds(year, month)
        ym = f"{year}-{month:02d}"
        per_month_counts[ym] = {}
        if end < start:
            raise RuntimeError(f"target month {ym} is not complete enough to fetch after clamping")

        if "fuelinst" in args.datasets:
            rows = fetch_fuelinst(start, end, args.fuelinst_window_days, args.retries, args.request_delay_seconds)
            fail_if_empty("fuelinst", rows, year, month)
            fetched["fuelinst"].extend(rows)
            per_month_counts[ym]["fuelinst"] = len(rows)

        if "fuelhh" in args.datasets:
            rows = fetch_fuelhh(start, end, args.fuelhh_window_days, args.retries, args.request_delay_seconds)
            fail_if_empty("fuelhh", rows, year, month)
            fetched["fuelhh"].extend(rows)
            per_month_counts[ym]["fuelhh"] = len(rows)

        if "prices" in args.datasets:
            rows = fetch_prices(start, end, args.retries, args.request_delay_seconds)
            fail_if_empty("prices", rows, year, month)
            fetched["prices"].extend(rows)
            per_month_counts[ym]["prices"] = len(rows)

    removed: dict[str, list[str]] = {}
    results: list[dict[str, Any]] = []
    for dataset in args.datasets:
        removed[dataset] = remove_existing_partitions(dataset, target_months, args.apply)
        results.append(write_records(dataset, fetched[dataset], args.apply))

    audit = parquet_audit()
    payload = {
        "schemaVersion": "fetch_latest_month.hardened.v1",
        "updatedUTC": utc_now_text(),
        "apply": args.apply,
        "targetMonths": [f"{y}-{m:02d}" for y, m in target_months],
        "datasets": args.datasets,
        "perMonthRowCounts": per_month_counts,
        "idempotency": {
            "fuelinst": ["periodStartUTC", "fuelType"],
            "fuelhh": ["time", "technology"],
            "prices": ["periodStartUTC"],
            "method": "full touched month partition directories are removed, re-fetched, deduped, schema-checked, readback-checked and rewritten fresh",
        },
        "removedPartitionsBeforeRewrite": removed,
        "results": results,
        "parquetAudit": audit,
        "timeBasis": "target months are derived in Europe/London civil time; timestamps are stored in UTC",
        "priceRevisionPolicy": "latest-visible-as-of-run-date with a trailing refetch window",
    }

    reports = Path("reports")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "latest_parquet_audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (reports / "fetch_latest_month_latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("monthly fetch audit:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
