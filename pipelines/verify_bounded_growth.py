#!/usr/bin/env python3
"""Fail CI if a monthly update exceeds its declared repository-growth scope."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

DATA_PATH = re.compile(
    r"^(?:generation/dataset=(fuelinst|fuelhh)|(?P<prices>prices))/year=(\d{4})/month=(\d{1,2})/([^/]+)$"
)
ALLOWED_REPORTS = {
    "reports/latest_parquet_audit.json",
    "reports/fetch_latest_month_latest.json",
    "reports/bounded_growth_gate_latest.json",
}


def git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, text=True, capture_output=True)
    return result.stdout


def working_tree_changes(base: str) -> list[tuple[str, str]]:
    changes: dict[str, str] = {}
    for line in git_output("diff", "--name-status", "--no-renames", base, "--").splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        changes[path.replace("\\", "/")] = status[0]
    for path in git_output("ls-files", "--others", "--exclude-standard").splitlines():
        if path.strip():
            changes[path.replace("\\", "/")] = "A"
    return sorted((status, path) for path, status in changes.items())


def evaluate_changes(
    audit: dict[str, Any],
    changes: list[tuple[str, str]],
    root: Path,
    *,
    max_new_parquet_files: int,
    max_new_parquet_bytes: int,
) -> dict[str, Any]:
    errors: list[str] = []
    mode = audit.get("mode")
    apply = audit.get("apply") is True
    allowed: dict[str, str] = {}
    for item in audit.get("plan", []):
        if item.get("action") in {"ADD_MISSING", "REPAIR_EXISTING"}:
            allowed[str(item.get("partition", "")).replace("\\", "/").rstrip("/")] = item["action"]

    changed_parquet: list[dict[str, Any]] = []
    seen_partitions: set[str] = set()
    for status, path in changes:
        if path in ALLOWED_REPORTS:
            if status == "D":
                errors.append(f"audit report deleted: {path}")
            continue
        match = DATA_PATH.match(path)
        if match is None:
            errors.append(f"monthly updater changed an out-of-scope path: {status} {path}")
            continue
        if not path.endswith(".parquet"):
            errors.append(f"non-Parquet data artifact: {status} {path}")
            continue
        partition = path.rsplit("/", 1)[0]
        action = allowed.get(partition)
        if action is None:
            errors.append(f"data changed outside the audited plan: {status} {path}")
            continue
        seen_partitions.add(partition)
        if mode == "FILL_MISSING" and (action != "ADD_MISSING" or status != "A"):
            errors.append(f"normal run must only add a missing partition: {status} {path}")
        if mode == "EXPLICIT_REPAIR" and action != "REPAIR_EXISTING":
            errors.append(f"repair run has a non-repair plan action: {status} {path}")
        size = 0
        physical = root / Path(path)
        if status != "D" and physical.exists():
            size = physical.stat().st_size
        changed_parquet.append({"status": status, "path": path, "bytes": size, "action": action})

    if apply and mode == "FILL_MISSING":
        missing = sorted(set(allowed) - seen_partitions)
        if missing:
            errors.append("planned dataset-months produced no Parquet change: " + ", ".join(missing))

    additions = [item for item in changed_parquet if item["status"] != "D"]
    total_bytes = sum(int(item["bytes"]) for item in additions)
    if len(additions) > max_new_parquet_files:
        errors.append(f"{len(additions)} written Parquet files exceed limit {max_new_parquet_files}")
    if total_bytes > max_new_parquet_bytes:
        errors.append(f"{total_bytes} written Parquet bytes exceed limit {max_new_parquet_bytes}")
    if mode not in {"FILL_MISSING", "EXPLICIT_REPAIR"}:
        errors.append(f"unknown audit mode: {mode!r}")

    return {
        "schemaVersion": "data-gb-electricity.bounded-growth-gate.v1",
        "status": "PASS" if not errors else "FAIL",
        "mode": mode,
        "limits": {
            "maxNewParquetFiles": max_new_parquet_files,
            "maxNewParquetBytes": max_new_parquet_bytes,
            "actualWrittenParquetFiles": len(additions),
            "actualChangedParquetFiles": len(changed_parquet),
            "actualWrittenParquetBytes": total_bytes,
        },
        "changedParquet": changed_parquet,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the monthly updater changed only its bounded plan")
    parser.add_argument("--audit", default="reports/fetch_latest_month_latest.json")
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--max-new-parquet-files", type=int, default=9)
    parser.add_argument("--max-new-parquet-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--report", default="reports/bounded_growth_gate_latest.json")
    args = parser.parse_args()

    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    result = evaluate_changes(
        audit,
        working_tree_changes(args.base),
        Path("."),
        max_new_parquet_files=args.max_new_parquet_files,
        max_new_parquet_bytes=args.max_new_parquet_bytes,
    )
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
