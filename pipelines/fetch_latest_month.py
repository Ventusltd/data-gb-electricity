#!/usr/bin/env python3
"""Bounded monthly Elexon updater for data-gb-electricity.

Normal scheduled runs inspect a short window of closed calendar months and add
only missing dataset-month partitions. Existing Parquet is frozen. Replacing a
historical partition requires an explicit date range *and* --repair-existing.

All API rows are fetched and checked before the first write. Dataset-month,
row, byte, file, request and retry-attempt budgets give CI hard limits rather
than hopeful prose.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

from fetch_elexon_api_to_parquet_hardened import (
    fetch_fuelhh,
    fetch_fuelinst,
    fetch_prices,
    parse_dt,
    write_records,
    utc_now_text,
)
from gb_calendar import london_today
from monthly_growth_policy import (
    DATASETS,
    build_plan,
    enforce_plan_bound,
    existing_partition_files,
    writable_plan,
    write_key,
)

DEFAULT_MAX_DATASET_MONTHS = 9
DEFAULT_MAX_NEW_ROWS = 2_000_000
DEFAULT_MAX_NEW_PARQUET_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_API_REQUESTS = 200
DEFAULT_MAX_API_ATTEMPTS = 600


def previous_complete_month(today: dt.date | None = None) -> tuple[int, int]:
    today = today or london_today()
    first_this_month = dt.date(today.year, today.month, 1)
    last_prev_month = first_this_month - dt.timedelta(days=1)
    return last_prev_month.year, last_prev_month.month


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + offset
    return idx // 12, idx % 12 + 1


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = dt.date(year, 12, 31) if month == 12 else dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return start, end


def months_from_range(start: dt.date, end: dt.date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = shift_month(year, month, 1)
    return months


def parquet_audit() -> dict[str, Any]:
    files = list(Path("generation").glob("**/*.parquet")) + list(Path("prices").glob("**/*.parquet"))
    total_bytes = sum(path.stat().st_size for path in files if path.exists())
    return {
        "parquetFileCount": len(files),
        "parquetTotalMB": round(total_bytes / 1048576, 3),
        "generationFuelinstMB": round(sum(path.stat().st_size for path in Path("generation/dataset=fuelinst").glob("**/*.parquet")) / 1048576, 3),
        "generationFuelhhMB": round(sum(path.stat().st_size for path in Path("generation/dataset=fuelhh").glob("**/*.parquet")) / 1048576, 3),
        "pricesMB": round(sum(path.stat().st_size for path in Path("prices").glob("**/*.parquet")) / 1048576, 3),
    }


def fail_if_empty(dataset: str, rows: list[dict[str, Any]], year: int, month: int) -> None:
    if not rows:
        raise RuntimeError(
            f"{dataset} returned zero rows for {year}-{month:02d}; "
            "refusing to write an empty partition"
        )


def fail_if_outside_month(dataset: str, rows: list[dict[str, Any]], year: int, month: int) -> None:
    field = "time" if dataset == "fuelhh" else "periodStartUTC"
    outside = 0
    invalid = 0
    for row in rows:
        stamp = parse_dt(row.get(field))
        if stamp is None:
            invalid += 1
        elif (stamp.year, stamp.month) != (year, month):
            outside += 1
    if invalid or outside:
        raise RuntimeError(
            f"{dataset} {year}-{month:02d}: {invalid} invalid timestamps and "
            f"{outside} rows outside the authorised month"
        )


def rows_in_utc_partition_month(
    dataset: str,
    rows: list[dict[str, Any]],
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    field = "time" if dataset == "fuelhh" else "periodStartUTC"
    return [
        row
        for row in rows
        if (stamp := parse_dt(row.get(field))) is not None and (stamp.year, stamp.month) == (year, month)
    ]


def api_bounds(dataset: str, year: int, month: int) -> tuple[dt.date, dt.date]:
    """Return source-query dates that fully cover one UTC partition month.

    FUELHH and price endpoints are addressed by GB settlement date. During BST,
    a UTC month boundary can sit inside the neighbouring settlement date, so a
    one-day buffer on each side is fetched and then discarded before writing.
    """
    start, end = month_bounds(year, month)
    if dataset in {"fuelhh", "prices"}:
        return start - dt.timedelta(days=1), end + dt.timedelta(days=1)
    return start, end


def estimated_api_requests(dataset: str, year: int, month: int, fuelinst_window: int, fuelhh_window: int) -> int:
    start, end = api_bounds(dataset, year, month)
    days = (end - start).days + 1
    if dataset == "fuelinst":
        return math.ceil(days / fuelinst_window)
    if dataset == "fuelhh":
        return math.ceil(days / fuelhh_window)
    return days


def audit_payload(
    args: argparse.Namespace,
    target_months: list[tuple[int, int]],
    plan: list[dict[str, Any]],
    per_month_counts: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    before: dict[str, Any],
) -> dict[str, Any]:
    written_bytes = sum(
        int(part.get("bytes", 0))
        for result in results
        for part in result.get("partitions", [])
    )
    return {
        "schemaVersion": "fetch_latest_month.bounded.v2",
        "updatedUTC": utc_now_text(),
        "apply": args.apply,
        "mode": "EXPLICIT_REPAIR" if args.repair_existing else "FILL_MISSING",
        "targetMonths": [f"{year}-{month:02d}" for year, month in target_months],
        "datasets": args.datasets,
        "plan": plan,
        "perMonth": per_month_counts,
        "limits": {
            "maxDatasetMonthsWritten": args.max_dataset_months,
            "maxNewRows": args.max_new_rows,
            "maxNewParquetBytes": args.max_new_parquet_bytes,
            "maxApiRequests": args.max_api_requests,
            "maxApiAttempts": args.max_api_attempts,
            "actualDatasetMonthsWritten": len(writable_plan(plan)),
            "actualRowsFetched": sum(
                int(value.get("rowsFetched", 0))
                for month in per_month_counts.values()
                for value in month.values()
                if isinstance(value, dict)
            ),
            "actualParquetBytesWritten": written_bytes,
            "estimatedApiRequests": sum(
                int(value.get("estimatedApiRequests", 0))
                for month in per_month_counts.values()
                for value in month.values()
                if isinstance(value, dict)
            ),
            "estimatedMaximumApiAttempts": sum(
                int(value.get("estimatedApiRequests", 0))
                for month in per_month_counts.values()
                for value in month.values()
                if isinstance(value, dict)
            ) * args.retries,
        },
        "historyPolicy": {
            "normal": "existing dataset-month partitions are frozen and skipped",
            "repair": "requires explicit start/end dates plus --repair-existing",
            "writeOrder": "fetch all; validate all; write pending Parquet; validate readback; atomically replace data_0",
        },
        "idempotencyKeys": {
            "fuelinst": ["periodStartUTC", "fuelType"],
            "fuelhh": ["time", "technology"],
            "prices": ["periodStartUTC"],
        },
        "results": results,
        "parquetAuditBefore": before,
        "parquetAuditAfter": parquet_audit(),
        "timeBasis": "Parquet partitions are UTC year/month; GB settlement-date endpoints receive a one-day boundary buffer which is filtered before write",
        "priceRevisionPolicy": "frozen once written; a later correction is an explicit, audited repair",
    }


def write_audit(payload: dict[str, Any]) -> None:
    reports = Path("reports")
    reports.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    (reports / "latest_parquet_audit.json").write_text(text, encoding="utf-8")
    (reports / "fetch_latest_month_latest.json").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill missing closed Elexon month partitions within hard growth limits")
    parser.add_argument("--start-date", help="Explicit first repair/inspection date; expanded to a calendar month.")
    parser.add_argument("--end-date", help="Explicit last repair/inspection date; expanded to a calendar month.")
    parser.add_argument(
        "--refetch-months",
        type=int,
        default=3,
        help="Recent closed months to inspect for gaps. Existing partitions are not re-fetched. Default 3.",
    )
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS), choices=list(DATASETS))
    parser.add_argument("--repair-existing", action="store_true", help="Replace existing partitions. Requires explicit start and end dates.")
    parser.add_argument("--max-dataset-months", type=int, default=DEFAULT_MAX_DATASET_MONTHS)
    parser.add_argument("--max-new-rows", type=int, default=DEFAULT_MAX_NEW_ROWS)
    parser.add_argument("--max-new-parquet-bytes", type=int, default=DEFAULT_MAX_NEW_PARQUET_BYTES)
    parser.add_argument("--max-api-requests", type=int, default=DEFAULT_MAX_API_REQUESTS)
    parser.add_argument("--max-api-attempts", type=int, default=DEFAULT_MAX_API_ATTEMPTS)
    parser.add_argument("--fuelinst-window-days", type=int, default=1)
    parser.add_argument("--fuelhh-window-days", type=int, default=7)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--request-delay-seconds", type=float, default=1.5)
    parser.add_argument("--plan-only", action="store_true", help="Print the bounded plan without network calls or filesystem writes.")
    parser.add_argument("--apply", action="store_true", help="Write verified Parquet. Omit to fetch and validate without writing.")
    args = parser.parse_args()

    explicit_range = bool(args.start_date or args.end_date)
    if explicit_range:
        if not (args.start_date and args.end_date):
            raise SystemExit("start-date and end-date must be supplied together")
        start = dt.date.fromisoformat(args.start_date)
        end = dt.date.fromisoformat(args.end_date)
        if start > end:
            raise SystemExit("start-date must not be after end-date")
        target_months = months_from_range(start, end)
    else:
        if args.refetch_months < 1:
            raise SystemExit("refetch-months must be >= 1")
        previous_year, previous_month = previous_complete_month()
        target_months = [
            shift_month(previous_year, previous_month, -offset)
            for offset in range(args.refetch_months - 1, -1, -1)
        ]

    latest_closed = previous_complete_month()
    if any(month > latest_closed for month in target_months):
        raise SystemExit("only complete calendar months may be fetched")
    if args.repair_existing and not explicit_range:
        raise SystemExit("--repair-existing requires explicit --start-date and --end-date")
    if args.max_new_rows < 1 or args.max_new_parquet_bytes < 1 or args.max_api_requests < 1 or args.max_api_attempts < 1:
        raise SystemExit("row, byte and API-request limits must be positive")
    if args.fuelinst_window_days < 1 or args.fuelhh_window_days < 1:
        raise SystemExit("API window sizes must be positive")
    if args.retries < 1 or args.request_delay_seconds < 0:
        raise SystemExit("retries must be positive and request delay must not be negative")
    if len(set(args.datasets)) != len(args.datasets):
        raise SystemExit("datasets must not contain duplicates")

    before = parquet_audit()
    plan = build_plan(Path("."), args.datasets, target_months, repair_existing=args.repair_existing)
    enforce_plan_bound(plan, args.max_dataset_months)
    writable = writable_plan(plan)
    request_estimate = sum(
        estimated_api_requests(
            item["dataset"],
            *(int(value) for value in item["month"].split("-")),
            args.fuelinst_window_days,
            args.fuelhh_window_days,
        )
        for item in writable
    )
    if request_estimate > args.max_api_requests:
        raise RuntimeError(
            f"bounded-collection stop: {request_estimate} estimated API requests exceed "
            f"limit {args.max_api_requests}"
        )
    maximum_attempts = request_estimate * args.retries
    if maximum_attempts > args.max_api_attempts:
        raise RuntimeError(
            f"bounded-collection stop: {maximum_attempts} maximum API attempts exceed "
            f"limit {args.max_api_attempts}"
        )
    print(json.dumps({
        "mode": "EXPLICIT_REPAIR" if args.repair_existing else "FILL_MISSING",
        "estimatedApiRequests": request_estimate,
        "maxApiRequests": args.max_api_requests,
        "estimatedMaximumApiAttempts": maximum_attempts,
        "maxApiAttempts": args.max_api_attempts,
        "plan": plan,
    }, indent=2))
    if args.plan_only:
        return 0

    actions = {write_key(item["dataset"], item["month"]): item for item in writable}
    fetched: dict[tuple[str, str], list[dict[str, Any]]] = {}
    per_month: dict[str, dict[str, Any]] = {f"{year}-{month:02d}": {} for year, month in target_months}

    # Network first, filesystem later: a late API failure cannot leave a half-run.
    for year, month in target_months:
        month_text = f"{year}-{month:02d}"
        for dataset in args.datasets:
            action = actions.get(write_key(dataset, month_text))
            if action is None:
                per_month[month_text][dataset] = {"action": "SKIP_FROZEN", "rowsFetched": 0, "estimatedApiRequests": 0}
                continue
            start, end = api_bounds(dataset, year, month)
            request_count = estimated_api_requests(dataset, year, month, args.fuelinst_window_days, args.fuelhh_window_days)
            if dataset == "fuelinst":
                raw_rows = fetch_fuelinst(start, end, args.fuelinst_window_days, args.retries, args.request_delay_seconds)
            elif dataset == "fuelhh":
                raw_rows = fetch_fuelhh(start, end, args.fuelhh_window_days, args.retries, args.request_delay_seconds)
            else:
                raw_rows = fetch_prices(start, end, args.retries, args.request_delay_seconds)
            rows = rows_in_utc_partition_month(dataset, raw_rows, year, month)
            fail_if_empty(dataset, rows, year, month)
            fail_if_outside_month(dataset, rows, year, month)
            fetched[(dataset, month_text)] = rows
            per_month[month_text][dataset] = {
                "action": action["action"],
                "estimatedApiRequests": request_count,
                "rowsFetched": len(raw_rows),
                "rowsKeptInUtcPartition": len(rows),
                "boundaryRowsDiscarded": len(raw_rows) - len(rows),
            }

    total_rows = sum(
        int(value.get("rowsFetched", 0))
        for month in per_month.values()
        for value in month.values()
        if isinstance(value, dict)
    )
    if total_rows > args.max_new_rows:
        raise RuntimeError(f"bounded-growth stop: {total_rows} fetched rows exceed limit {args.max_new_rows}")

    # Recheck the plan immediately before writing so a concurrent run cannot
    # turn ADD_MISSING into an accidental historical overwrite.
    for item in writable:
        year, month = (int(value) for value in item["month"].split("-"))
        now = existing_partition_files(Path("."), item["dataset"], year, month)
        if item["action"] == "ADD_MISSING" and now:
            raise RuntimeError(f"{item['dataset']} {item['month']} appeared after planning; refusing overwrite")
        if item["action"] == "REPAIR_EXISTING" and not now:
            raise RuntimeError(f"{item['dataset']} {item['month']} disappeared after planning; refusing changed repair scope")

    results: list[dict[str, Any]] = []
    for item in writable:
        rows = fetched[write_key(item["dataset"], item["month"])]
        result = write_records(
            item["dataset"],
            rows,
            args.apply,
            replace_existing=item["action"] == "REPAIR_EXISTING",
            refuse_existing=item["action"] == "ADD_MISSING",
        )
        results.append(result)

    payload = audit_payload(args, target_months, plan, per_month, results, before)
    if payload["limits"]["actualParquetBytesWritten"] > args.max_new_parquet_bytes:
        raise RuntimeError(
            f"bounded-growth stop: {payload['limits']['actualParquetBytesWritten']} written bytes exceed "
            f"limit {args.max_new_parquet_bytes}"
        )
    write_audit(payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
