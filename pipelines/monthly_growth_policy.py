#!/usr/bin/env python3
"""Pure planning rules for bounded, history-preserving monthly updates.

This module deliberately imports neither PyArrow nor the network fetcher. CI and
unit tests can therefore prove which dataset-months an update is allowed to
touch before an API request or Parquet write begins.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

DATASETS = ("fuelinst", "fuelhh", "prices")


def partition_directory(root: Path, dataset: str, year: int, month: int) -> Path:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset: {dataset}")
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month: {month}")
    if dataset == "prices":
        return root / "prices" / f"year={year}" / f"month={month}"
    return root / "generation" / f"dataset={dataset}" / f"year={year}" / f"month={month}"


def existing_partition_files(root: Path, dataset: str, year: int, month: int) -> list[Path]:
    return sorted(partition_directory(root, dataset, year, month).glob("*.parquet"))


def build_plan(
    root: Path,
    datasets: Iterable[str],
    months: Iterable[tuple[int, int]],
    *,
    repair_existing: bool,
) -> list[dict[str, Any]]:
    """Return one auditable decision for every requested dataset-month.

    The normal law is append-only at partition granularity: a partition with at
    least one Parquet file is frozen and skipped. Replacing it is possible only
    when the caller has explicitly selected repair mode.
    """
    plan: list[dict[str, Any]] = []
    for year, month in months:
        month_text = f"{year}-{month:02d}"
        for dataset in datasets:
            files = existing_partition_files(root, dataset, year, month)
            if files and repair_existing:
                action = "REPAIR_EXISTING"
                reason = "explicit repair flag; replace one complete dataset-month"
            elif files:
                action = "SKIP_FROZEN"
                reason = "Parquet already exists; preserve historical bytes"
            else:
                action = "ADD_MISSING"
                reason = "no Parquet exists for this requested dataset-month"
            plan.append({
                "dataset": dataset,
                "month": month_text,
                "action": action,
                "reason": reason,
                "partition": partition_directory(root, dataset, year, month).as_posix(),
                "existingFiles": [path.as_posix() for path in files],
                "existingBytes": sum(path.stat().st_size for path in files),
            })
    return plan


def writable_plan(plan: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in plan if item["action"] in {"ADD_MISSING", "REPAIR_EXISTING"}]


def enforce_plan_bound(plan: Iterable[dict[str, Any]], max_dataset_months: int) -> None:
    if max_dataset_months < 1:
        raise ValueError("max-dataset-months must be >= 1")
    writable = writable_plan(plan)
    if len(writable) > max_dataset_months:
        names = ", ".join(f"{item['dataset']}:{item['month']}" for item in writable)
        raise RuntimeError(
            f"bounded-growth stop: {len(writable)} dataset-months exceed "
            f"the limit {max_dataset_months}: {names}"
        )


def write_key(dataset: str, month_text: str) -> tuple[str, str]:
    return dataset, month_text
