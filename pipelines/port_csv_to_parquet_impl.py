#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

EXPECTED = {
    "fuelinst": 72,
    "fuelhh": 125,
    "prices": 11,
    "parquet_files_min": 300,
    "canary_rows": 156_960,
}

COMBINED_SOURCE_MARKERS = (
    "_half_hourly.csv",
    "_all_years.csv",
    "_combined.csv",
)


def mb(path: Path) -> float:
    if path.is_file():
        return round(path.stat().st_size / 1048576, 3)
    if not path.exists():
        return 0.0
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1048576, 3)


def exclude_combined_sources(files: list[str]) -> list[str]:
    clean: list[str] = []
    for file in files:
        name = Path(file).name.lower()
        if any(name.endswith(marker) for marker in COMBINED_SOURCE_MARKERS):
            continue
        clean.append(file)
    return sorted(clean)


def sources(root: Path) -> dict[str, list[str]]:
    return {
        "fuelinst": exclude_combined_sources(sorted(glob.glob(str(root / "data/generation/archive/*/*.csv")))),
        "fuelhh": exclude_combined_sources(sorted(glob.glob(str(root / "data/generation/fuelhh_halfhourly/*/*.csv")))),
        "prices": exclude_combined_sources(sorted(glob.glob(str(root / "data/electricity/elexon_system_prices_*.csv")))),
    }


def check_counts(src: dict[str, list[str]]) -> None:
    print(f"found clean source files: {len(src['fuelinst'])} FUELINST, {len(src['fuelhh'])} FUELHH, {len(src['prices'])} price files")
    for key in ("fuelinst", "fuelhh", "prices"):
        if len(src[key]) < EXPECTED[key]:
            raise SystemExit(f"count below clean baseline for {key}: {len(src[key])} < {EXPECTED[key]}")


def convert(src_root: Path, out_root: Path) -> None:
    src = sources(src_root)
    check_counts(src)
    for rel in ("generation", "prices"):
        target = out_root / rel
        if target.exists():
            shutil.rmtree(target)

    (out_root / "generation").mkdir(parents=True, exist_ok=True)
    (out_root / "prices").mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    out = str(out_root)
    fi, fh, pr = src["fuelinst"], src["fuelhh"], src["prices"]

    con.execute(f"""COPY (
      WITH raw AS (
        SELECT *, row_number() OVER (PARTITION BY periodStartUTC, fuelType ORDER BY filename) AS _rn
        FROM read_csv_auto({fi!r}, union_by_name=true, filename=true)
      )
      SELECT * EXCLUDE (filename, _rn), 'fuelinst' AS dataset, year(periodStartUTC) AS year, month(periodStartUTC) AS month
      FROM raw
      WHERE _rn = 1
    )
      TO '{out}/generation/dataset=fuelinst' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (year,month), OVERWRITE_OR_IGNORE);""")

    con.execute(f"""COPY (
      WITH raw AS (
        SELECT *, row_number() OVER (PARTITION BY "time", technology ORDER BY filename) AS _rn
        FROM read_csv_auto({fh!r}, union_by_name=true, filename=true)
      )
      SELECT * EXCLUDE (filename, _rn), 'fuelhh' AS dataset, year("time") AS year, month("time") AS month
      FROM raw
      WHERE _rn = 1
    )
      TO '{out}/generation/dataset=fuelhh' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (year,month), OVERWRITE_OR_IGNORE);""")

    con.execute(f"""COPY (
      WITH raw AS (
        SELECT *, row_number() OVER (PARTITION BY periodStartUTC ORDER BY filename) AS _rn
        FROM read_csv_auto({pr!r}, union_by_name=true, filename=true)
      )
      SELECT * EXCLUDE (filename, _rn), year(periodStartUTC) AS year, month(periodStartUTC) AS month
      FROM raw
      WHERE _rn = 1
    )
      TO '{out}/prices' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (year,month), OVERWRITE_OR_IGNORE);""")


def duplicate_key_groups(con: duckdb.DuckDBPyConnection, query: str) -> int:
    return int(con.execute(query).fetchone()[0])


def verify(out_root: Path) -> dict[str, object]:
    con = duckdb.connect()
    parquet_files = list(out_root.glob("generation/**/*.parquet")) + list(out_root.glob("prices/**/*.parquet"))
    total_mb = round(sum(p.stat().st_size for p in parquet_files) / 1048576, 3)
    canary = con.execute(
        f"SELECT count(*) FROM read_parquet('{out_root}/generation/dataset=fuelinst/year=2023/month=9/*.parquet')"
    ).fetchone()[0]
    duplicates = {
        "fuelinst": duplicate_key_groups(con, f"""
            SELECT count(*) FROM (
              SELECT periodStartUTC, fuelType, count(*) AS c
              FROM read_parquet('{out_root}/generation/dataset=fuelinst/year=*/month=*/*.parquet')
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """),
        "fuelhh": duplicate_key_groups(con, f"""
            SELECT count(*) FROM (
              SELECT "time", technology, count(*) AS c
              FROM read_parquet('{out_root}/generation/dataset=fuelhh/year=*/month=*/*.parquet')
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """),
        "prices": duplicate_key_groups(con, f"""
            SELECT count(*) FROM (
              SELECT periodStartUTC, count(*) AS c
              FROM read_parquet('{out_root}/prices/year=*/month=*/*.parquet')
              GROUP BY 1
              HAVING count(*) > 1
            )
        """),
    }
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "parquet_files": len(parquet_files),
        "parquet_files_minimum_baseline": EXPECTED["parquet_files_min"],
        "total_mb": total_mb,
        "fuelinst_mb": mb(out_root / "generation/dataset=fuelinst"),
        "fuelhh_mb": mb(out_root / "generation/dataset=fuelhh"),
        "prices_mb": mb(out_root / "prices"),
        "fuelinst_2023_09_rows": canary,
        "duplicate_key_groups": duplicates,
    }
    print(json.dumps(report, indent=2))
    if len(parquet_files) < EXPECTED["parquet_files_min"]:
        raise SystemExit("parquet file count below baseline")
    if total_mb < 25.0:
        raise SystemExit("parquet size below expected minimum baseline")
    if canary != EXPECTED["canary_rows"]:
        raise SystemExit("canary row count mismatch")
    if any(count != 0 for count in duplicates.values()):
        raise SystemExit(f"duplicate key groups found: {duplicates}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", default="../globalgrid2050")
    ap.add_argument("--output-root", default=".")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="reports/latest_parquet_audit.json")
    args = ap.parse_args()

    src_root = Path(args.source_root).resolve()
    out_root = Path(args.output_root).resolve()
    src = sources(src_root)
    check_counts(src)
    print("clean source MB:", {k: round(sum(Path(f).stat().st_size for f in v) / 1048576, 3) for k, v in src.items()})

    report = {"generated_utc": datetime.now(timezone.utc).isoformat(), "mode": "apply" if args.apply else "audit"}
    if args.apply:
        convert(src_root, out_root)
        report.update(verify(out_root))
    else:
        print("audit only - no parquet written")

    report_path = out_root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
