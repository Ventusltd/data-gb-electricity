#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

FUELINST_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST"
FUELHH_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH"
SYSTEM_PRICE_URL = "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices"
USER_AGENT = "GlobalGrid2050 data-gb-electricity monthly parquet updater"
UTC = dt.timezone.utc
LONDON = ZoneInfo("Europe/London")

GROUPS = {
    "Solar": ["SOLAR", "PV"],
    "Wind": ["WIND"],
    "Hydro": ["NPSHYD", "HYDRO"],
    "Gas": ["CCGT", "OCGT"],
    "Coal": ["COAL"],
    "Biomass": ["BIOMASS"],
    "Nuclear": ["NUCLEAR"],
    "Pumped Storage": ["PS"],
    "Imports & Exports": ["INT"],
}

SCHEMAS = {
    "fuelinst": pa.schema([
        ("source", pa.string()),
        ("periodStartUTC", pa.timestamp("us", tz="UTC")),
        ("fuelType", pa.string()),
        ("generationMW", pa.float64()),
        ("publishTimeUTC", pa.timestamp("us", tz="UTC")),
        ("fetchedAtUTC", pa.timestamp("us", tz="UTC")),
        ("dataset", pa.string()),
    ]),
    "fuelhh": pa.schema([
        ("time", pa.timestamp("us", tz="UTC")),
        ("technology", pa.string()),
        ("generationMW", pa.float64()),
        ("source", pa.string()),
        ("dataset", pa.string()),
    ]),
    "prices": pa.schema([
        ("source", pa.string()),
        ("settlementDate", pa.string()),
        ("settlementPeriod", pa.int32()),
        ("periodStartUTC", pa.timestamp("us", tz="UTC")),
        ("systemBuyPriceGBPperMWh", pa.float64()),
        ("systemSellPriceGBPperMWh", pa.float64()),
        ("netImbalanceVolumeMWh", pa.float64()),
        ("fetchedAtUTC", pa.timestamp("us", tz="UTC")),
    ]),
}


def utc_now_dt() -> dt.datetime:
    return dt.datetime.now(UTC)


def utc_now_text() -> str:
    return utc_now_dt().isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        d = value
    elif isinstance(value, dt.date):
        d = dt.datetime.combine(value, dt.time(0, 0), tzinfo=UTC)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            d = dt.datetime.fromisoformat(text)
        except Exception:
            try:
                d = dt.datetime.fromisoformat(text[:10])
            except Exception:
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def dt_key(value: Any) -> str:
    d = parse_dt(value)
    return "" if d is None else d.isoformat().replace("+00:00", "Z")


def pick(row: dict[str, Any], names: Iterable[str]) -> Any:
    folded = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        value = folded.get(name.lower())
        if value not in (None, ""):
            return value
    return ""


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def request_json(url: str, retries: int, delay: float) -> list[Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            rows = data if isinstance(data, list) else data.get("data", [])
            return rows if isinstance(rows, list) else []
        except Exception as exc:
            last_error = exc
            sleep_for = min(60.0, delay * (2 ** (attempt - 1)))
            print(f"retry {attempt}/{retries}: {exc}; sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)
    raise RuntimeError(f"request failed after {retries} retries: {last_error}")


def windows(start: dt.date, end: dt.date, span_days: int) -> Iterable[tuple[dt.date, dt.date]]:
    cur = start
    while cur <= end:
        win_end = min(end, cur + dt.timedelta(days=span_days - 1))
        yield cur, win_end
        cur = win_end + dt.timedelta(days=1)


def days_between(start: dt.date, end: dt.date) -> Iterable[dt.date]:
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def default_previous_month() -> tuple[dt.date, dt.date]:
    today = dt.datetime.now(LONDON).date()
    first_this_month = dt.date(today.year, today.month, 1)
    last_prev_month = first_this_month - dt.timedelta(days=1)
    first_prev_month = dt.date(last_prev_month.year, last_prev_month.month, 1)
    return first_prev_month, last_prev_month


def group_for(fuel: str) -> str:
    f = str(fuel or "").upper()
    for label, prefixes in GROUPS.items():
        if any(f.startswith(prefix) for prefix in prefixes):
            return label
    return "Other"


def period_start_from_date_period(date_text: str, period: int | None) -> dt.datetime | None:
    if period is None:
        return None
    try:
        settlement_date = dt.date.fromisoformat(str(date_text)[:10])
    except Exception:
        return None
    local_start = dt.datetime.combine(settlement_date, dt.time(0, 0), tzinfo=LONDON)
    local_next = local_start + dt.timedelta(days=1)
    utc_start = local_start.astimezone(UTC)
    utc_next = local_next.astimezone(UTC)
    periods = int((utc_next - utc_start).total_seconds() // 1800)
    if period < 1 or period > periods:
        return None
    return utc_start + dt.timedelta(minutes=(period - 1) * 30)


def partition_file(dataset: str, year: int, month: int) -> Path:
    if dataset == "prices":
        return Path("prices") / f"year={year}" / f"month={month}" / "data_0.parquet"
    return Path("generation") / f"dataset={dataset}" / f"year={year}" / f"month={month}" / "data_0.parquet"


def key_for(dataset: str, row: dict[str, Any]) -> tuple[str, str]:
    if dataset == "fuelinst":
        return (dt_key(row.get("periodStartUTC")), str(row.get("fuelType", "")))
    if dataset == "fuelhh":
        return (dt_key(row.get("time")), str(row.get("technology", "")))
    if dataset == "prices":
        return (dt_key(row.get("periodStartUTC")), "system_price")
    raise ValueError(dataset)


def read_parquet_file(path: Path) -> pa.Table:
    """Read one physical Parquet file without Hive-partition column inference.

    The generation tree uses a directory named dataset=fuelinst and the files also
    contain a normal column named dataset. pyarrow.parquet.read_table may infer the
    directory value as a dictionary partition column and then conflict with the
    in-file string column. ParquetFile reads the file footer directly and avoids
    merging directory partition columns into the table schema.
    """
    return pq.ParquetFile(path).read()


def read_existing(dataset: str, path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    table = read_parquet_file(path)
    fields = [field.name for field in SCHEMAS[dataset]]
    return [{field: row.get(field) for field in fields} for row in table.to_pylist()]


def validate_rows(dataset: str, rows: list[dict[str, Any]], context: str) -> dict[str, int]:
    seen: set[tuple[str, str]] = set()
    duplicate_groups: set[tuple[str, str]] = set()
    null_key_rows = 0
    for row in rows:
        key = key_for(dataset, row)
        if not key[0] or not key[1]:
            null_key_rows += 1
            continue
        if key in seen:
            duplicate_groups.add(key)
        seen.add(key)
    if null_key_rows:
        raise RuntimeError(f"{dataset} {context}: {null_key_rows} rows have null or empty key fields")
    if duplicate_groups:
        raise RuntimeError(f"{dataset} {context}: {len(duplicate_groups)} duplicate key groups found")
    return {"rows": len(rows), "distinctKeys": len(seen), "nullKeyRows": null_key_rows, "duplicateKeyGroups": len(duplicate_groups)}


def validate_table_schema(dataset: str, table: pa.Table, context: str) -> None:
    expected = SCHEMAS[dataset]
    if not table.schema.equals(expected, check_metadata=False):
        raise RuntimeError(f"{dataset} {context}: schema drift. expected={expected} got={table.schema}")


def write_records(dataset: str, records: list[dict[str, Any]], apply: bool) -> dict[str, Any]:
    by_month: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        ts = row.get("periodStartUTC") if dataset in {"fuelinst", "prices"} else row.get("time")
        d = parse_dt(ts)
        if d is not None:
            by_month[(d.year, d.month)].append(row)

    report: dict[str, Any] = {"dataset": dataset, "apply": apply, "rowsFetched": len(records), "monthsTouched": 0, "partitions": []}
    for (year, month), new_rows in sorted(by_month.items()):
        path = partition_file(dataset, year, month)
        existing_rows = read_existing(dataset, path)
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        dropped_null_key_rows = 0
        for row in existing_rows + new_rows:
            key = key_for(dataset, row)
            if key[0] and key[1]:
                merged[key] = row
            else:
                dropped_null_key_rows += 1
        final_rows = [merged[key] for key in sorted(merged)]
        validation = validate_rows(dataset, final_rows, f"{year}-{month:02d} pre-write")
        duplicates_dropped = len(existing_rows) + len(new_rows) - len(final_rows) - dropped_null_key_rows
        item: dict[str, Any] = {
            "path": str(path),
            "existingRows": len(existing_rows),
            "newRows": len(new_rows),
            "finalRows": len(final_rows),
            "duplicatesDropped": duplicates_dropped,
            "droppedNullKeyRows": dropped_null_key_rows,
            "validation": validation,
        }
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(final_rows, schema=SCHEMAS[dataset])
            validate_table_schema(dataset, table, f"{year}-{month:02d} pre-write")
            pq.write_table(table, path, compression="zstd")
            written = read_parquet_file(path)
            validate_table_schema(dataset, written, f"{year}-{month:02d} readback")
            readback_rows = [{field.name: row.get(field.name) for field in SCHEMAS[dataset]} for row in written.to_pylist()]
            item["readbackValidation"] = validate_rows(dataset, readback_rows, f"{year}-{month:02d} readback")
            item["bytes"] = path.stat().st_size
        report["monthsTouched"] += 1
        report["partitions"].append(item)
    return report


def fetch_fuelinst(start: dt.date, end: dt.date, window_days: int, retries: int, delay: float) -> list[dict[str, Any]]:
    fetched_at = utc_now_dt()
    out: list[dict[str, Any]] = []
    for w_start, w_end in windows(start, end, window_days):
        start_dt = dt.datetime.combine(w_start, dt.time(0, 0), tzinfo=UTC)
        end_dt = dt.datetime.combine(w_end, dt.time(23, 59), tzinfo=UTC)
        query = urllib.parse.urlencode({"publishDateTimeFrom": start_dt.strftime("%Y-%m-%dT%H:%MZ"), "publishDateTimeTo": end_dt.strftime("%Y-%m-%dT%H:%MZ"), "format": "json"})
        rows = request_json(f"{FUELINST_URL}?{query}", retries, delay)
        print(f"FUELINST {w_start} to {w_end}: {len(rows)} raw rows")
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            fuel = pick(raw, ["fuelType", "fuelTypeName", "fuel", "psrType"])
            generation = as_float(pick(raw, ["generation", "generationMW", "currentUsage", "quantity"]))
            period_start = parse_dt(pick(raw, ["startTime", "publishDateTime", "periodStartUTC", "settlementDate"] ))
            publish_time = parse_dt(pick(raw, ["publishDateTime", "publishTime", "createdTime"] ))
            if fuel and generation is not None and period_start is not None:
                out.append({"source": "Elexon BMRS FUELINST", "periodStartUTC": period_start, "fuelType": str(fuel).strip().upper(), "generationMW": generation, "publishTimeUTC": publish_time, "fetchedAtUTC": fetched_at, "dataset": "fuelinst"})
        time.sleep(delay)
    return out


def fetch_fuelhh(start: dt.date, end: dt.date, window_days: int, retries: int, delay: float) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], tuple[dt.datetime, str, float]] = {}
    for w_start, w_end in windows(start, end, window_days):
        query = urllib.parse.urlencode({"settlementDateFrom": w_start.isoformat(), "settlementDateTo": w_end.isoformat(), "format": "json"})
        rows = request_json(f"{FUELHH_URL}?{query}", retries, delay)
        print(f"FUELHH {w_start} to {w_end}: {len(rows)} raw rows")
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            fuel = pick(raw, ["fuelType", "fuelTypeName", "fuel", "psrType"])
            generation = as_float(pick(raw, ["generation", "generationMW", "quantity"] ))
            timestamp = parse_dt(pick(raw, ["startTime", "settlementPeriodStartTime", "periodStartUTC", "publishDateTime", "settlementDate"] ))
            if fuel and generation is not None and timestamp is not None:
                deduped[(dt_key(timestamp), str(fuel).upper())] = (timestamp, str(fuel).upper(), generation)
        time.sleep(delay)
    by_tech: dict[tuple[str, str], float] = defaultdict(float)
    stamp_by_key: dict[str, dt.datetime] = {}
    for timestamp, fuel, generation in deduped.values():
        key = dt_key(timestamp)
        stamp_by_key[key] = timestamp
        by_tech[(key, group_for(fuel))] += generation
    return [{"time": stamp_by_key[stamp], "technology": tech, "generationMW": mw, "source": "Elexon BMRS FUELHH", "dataset": "fuelhh"} for (stamp, tech), mw in sorted(by_tech.items())]


def fetch_prices(start: dt.date, end: dt.date, retries: int, delay: float) -> list[dict[str, Any]]:
    fetched_at = utc_now_dt()
    out: list[dict[str, Any]] = []
    for day in days_between(start, end):
        date_text = day.isoformat()
        rows = request_json(f"{SYSTEM_PRICE_URL}/{date_text}?format=json", retries, delay)
        print(f"PRICES {date_text}: {len(rows)} raw rows")
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            sp = as_int(pick(raw, ["settlementPeriod", "period"] ))
            if sp is None:
                continue
            source_period_start = parse_dt(pick(raw, ["periodStartUTC", "startTime", "settlementPeriodStartTime", "periodStart"] ))
            period_start = source_period_start or period_start_from_date_period(date_text, sp)
            if period_start is None:
                continue
            out.append({"source": "Elexon BMRS System Prices", "settlementDate": date_text, "settlementPeriod": sp, "periodStartUTC": period_start, "systemBuyPriceGBPperMWh": as_float(pick(raw, ["systemBuyPrice", "sbp"] )), "systemSellPriceGBPperMWh": as_float(pick(raw, ["systemSellPrice", "ssp"] )), "netImbalanceVolumeMWh": as_float(pick(raw, ["netImbalanceVolume", "niv"] )), "fetchedAtUTC": fetched_at})
        time.sleep(delay)
    return out


def write_reports(payload: dict[str, Any]) -> None:
    reports = Path("reports")
    reports.mkdir(parents=True, exist_ok=True)
    stamp = utc_now_dt().strftime("%Y%m%dT%H%M%SZ")
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    (reports / "elexon_api_to_parquet_latest.json").write_text(text, encoding="utf-8")
    (reports / f"elexon_api_to_parquet_{stamp}.json").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Elexon API data and write partitioned Parquet")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--datasets", nargs="+", default=["fuelinst", "fuelhh", "prices"], choices=["fuelinst", "fuelhh", "prices"])
    parser.add_argument("--fuelinst-window-days", type=int, default=1)
    parser.add_argument("--fuelhh-window-days", type=int, default=7)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--request-delay-seconds", type=float, default=1.5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    default_start, default_end = default_previous_month()
    start = dt.date.fromisoformat(args.start_date) if args.start_date else default_start
    end = dt.date.fromisoformat(args.end_date) if args.end_date else default_end
    yesterday = dt.datetime.now(LONDON).date() - dt.timedelta(days=1)
    end = min(end, yesterday)
    if start > end:
        raise SystemExit(f"empty date range after clamping: {start} to {end}")

    results: list[dict[str, Any]] = []
    if "fuelinst" in args.datasets:
        results.append(write_records("fuelinst", fetch_fuelinst(start, end, args.fuelinst_window_days, args.retries, args.request_delay_seconds), args.apply))
    if "fuelhh" in args.datasets:
        results.append(write_records("fuelhh", fetch_fuelhh(start, end, args.fuelhh_window_days, args.retries, args.request_delay_seconds), args.apply))
    if "prices" in args.datasets:
        results.append(write_records("prices", fetch_prices(start, end, args.retries, args.request_delay_seconds), args.apply))

    payload = {"schemaVersion": "elexon_api_to_parquet.hardened.v1", "updatedUTC": utc_now_text(), "apply": args.apply, "startDate": start.isoformat(), "endDate": end.isoformat(), "datasets": args.datasets, "sourceLog": {"fuelinst": FUELINST_URL, "fuelhh": FUELHH_URL, "prices": SYSTEM_PRICE_URL + "/YYYY-MM-DD"}, "idempotencyKeys": {"fuelinst": ["periodStartUTC", "fuelType"], "fuelhh": ["time", "technology"], "prices": ["periodStartUTC"]}, "results": results}
    write_reports(payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
