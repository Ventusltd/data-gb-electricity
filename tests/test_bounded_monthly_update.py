from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))

from fetch_elexon_api_to_parquet_hardened import SCHEMAS, period_start_from_date_period, partition_file, write_records
import fetch_latest_month as monthly
from fetch_latest_month import api_bounds, estimated_api_requests, fail_if_outside_month, months_from_range, rows_in_utc_partition_month, shift_month
from gb_calendar import london_date_at, london_midnight_utc
from monthly_growth_policy import build_plan, enforce_plan_bound, writable_plan
from verify_bounded_growth import evaluate_changes


class PlanningTests(unittest.TestCase):
    def test_existing_partition_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "prices/year=2026/month=7/data_0.parquet"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"existing")
            plan = build_plan(root, ["prices"], [(2026, 7), (2026, 8)], repair_existing=False)
            self.assertEqual([item["action"] for item in plan], ["SKIP_FROZEN", "ADD_MISSING"])
            self.assertEqual(len(writable_plan(plan)), 1)

    def test_repair_is_explicit_in_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "prices/year=2026/month=7/data_0.parquet"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"existing")
            plan = build_plan(root, ["prices"], [(2026, 7)], repair_existing=True)
            self.assertEqual(plan[0]["action"], "REPAIR_EXISTING")

    def test_dataset_month_budget_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_plan(Path(tmp), ["fuelinst", "fuelhh", "prices"], [(2026, 7), (2026, 8)], repair_existing=False)
            with self.assertRaisesRegex(RuntimeError, "6 dataset-months exceed"):
                enforce_plan_bound(plan, 5)

    def test_month_range_is_calendar_bounded(self) -> None:
        self.assertEqual(months_from_range(dt.date(2025, 12, 20), dt.date(2026, 2, 1)), [(2025, 12), (2026, 1), (2026, 2)])
        self.assertEqual(shift_month(2026, 1, -1), (2025, 12))

    def test_rows_outside_authorised_month_fail(self) -> None:
        rows = [{"periodStartUTC": "2026-07-31T23:30:00Z"}, {"periodStartUTC": "2026-08-01T00:00:00Z"}]
        with self.assertRaisesRegex(RuntimeError, "1 rows outside"):
            fail_if_outside_month("prices", rows, 2026, 7)

    def test_gb_settlement_days_have_46_and_50_periods(self) -> None:
        spring = dt.date(2026, 3, 29)
        autumn = dt.date(2026, 10, 25)
        self.assertEqual((london_midnight_utc(spring + dt.timedelta(days=1)) - london_midnight_utc(spring)).total_seconds(), 23 * 3600)
        self.assertEqual((london_midnight_utc(autumn + dt.timedelta(days=1)) - london_midnight_utc(autumn)).total_seconds(), 25 * 3600)
        self.assertIsNotNone(period_start_from_date_period(spring.isoformat(), 46))
        self.assertIsNone(period_start_from_date_period(spring.isoformat(), 47))
        self.assertIsNotNone(period_start_from_date_period(autumn.isoformat(), 50))
        self.assertIsNone(period_start_from_date_period(autumn.isoformat(), 51))

    def test_london_date_crosses_midnight_during_bst(self) -> None:
        instant = dt.datetime(2026, 8, 31, 23, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(london_date_at(instant), dt.date(2026, 9, 1))

    def test_settlement_endpoints_get_boundary_buffer_then_filter_to_utc_month(self) -> None:
        self.assertEqual(api_bounds("prices", 2026, 7), (dt.date(2026, 6, 30), dt.date(2026, 8, 1)))
        rows = [
            {"periodStartUTC": "2026-06-30T23:30:00Z"},
            {"periodStartUTC": "2026-07-01T00:00:00Z"},
            {"periodStartUTC": "2026-07-31T23:30:00Z"},
            {"periodStartUTC": "2026-08-01T00:00:00Z"},
        ]
        kept = rows_in_utc_partition_month("prices", rows, 2026, 7)
        self.assertEqual([row["periodStartUTC"] for row in kept], ["2026-07-01T00:00:00Z", "2026-07-31T23:30:00Z"])

    def test_api_request_estimate_is_bounded_before_network(self) -> None:
        self.assertEqual(estimated_api_requests("fuelinst", 2026, 7, 1, 7), 31)
        self.assertEqual(estimated_api_requests("fuelhh", 2026, 7, 1, 7), 5)
        self.assertEqual(estimated_api_requests("prices", 2026, 7, 1, 7), 33)


class ParquetWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        import os
        os.chdir(self.root)

    def tearDown(self) -> None:
        import os
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    @staticmethod
    def price_row(stamp: str, value: float) -> dict[str, object]:
        return {
            "source": "fixture",
            "settlementDate": dt.date.fromisoformat(stamp[:10]),
            "settlementPeriod": 1,
            "periodStartUTC": dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")),
            "systemBuyPriceGBPperMWh": value,
            "systemSellPriceGBPperMWh": value,
            "netImbalanceVolumeMWh": 0.0,
            "fetchedAtUTC": dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc),
        }

    def test_new_partition_uses_verified_pending_write(self) -> None:
        result = write_records("prices", [self.price_row("2026-07-01T00:00:00Z", 20.0)], True, refuse_existing=True)
        path = partition_file("prices", 2026, 7)
        self.assertTrue(path.exists())
        self.assertFalse(path.with_name("data_0.parquet.pending").exists())
        self.assertEqual(result["partitions"][0]["readbackValidation"]["duplicateKeyGroups"], 0)

    def test_new_partition_refuses_race(self) -> None:
        path = partition_file("prices", 2026, 7)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"race")
        with self.assertRaisesRegex(RuntimeError, "appeared after planning"):
            write_records("prices", [self.price_row("2026-07-01T00:00:00Z", 20.0)], True, refuse_existing=True)

    def test_explicit_repair_removes_stale_shards_only_after_readback(self) -> None:
        write_records("prices", [self.price_row("2026-07-01T00:00:00Z", 20.0)], True, refuse_existing=True)
        path = partition_file("prices", 2026, 7)
        stale = path.with_name("data_1.parquet")
        stale.write_bytes(path.read_bytes())
        result = write_records("prices", [self.price_row("2026-07-01T00:00:00Z", 30.0)], True, replace_existing=True)
        self.assertFalse(stale.exists())
        self.assertEqual(result["partitions"][0]["writeMode"], "replace-explicit-repair")


class CheckedInSchemaTests(unittest.TestCase):
    def test_every_historical_parquet_file_matches_the_writer_schema(self) -> None:
        patterns = {
            "fuelinst": "generation/dataset=fuelinst/**/*.parquet",
            "fuelhh": "generation/dataset=fuelhh/**/*.parquet",
            "prices": "prices/**/*.parquet",
        }
        checked = 0
        for dataset, pattern in patterns.items():
            files = sorted(ROOT.glob(pattern))
            self.assertTrue(files, f"no checked-in {dataset} fixture files")
            for path in files:
                actual = pq.ParquetFile(path).schema_arrow
                self.assertTrue(
                    actual.equals(SCHEMAS[dataset], check_metadata=False),
                    f"{path} schema differs from the monthly writer: {actual}",
                )
                checked += 1
        self.assertGreaterEqual(checked, 456)


class MonthlyIntegrationTests(unittest.TestCase):
    def test_first_run_adds_missing_month_and_second_run_makes_no_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = Path.cwd()
            import os
            os.chdir(tmp)
            try:
                inside = ParquetWriteTests.price_row("2025-07-01T00:00:00Z", 20.0)
                outside = ParquetWriteTests.price_row("2025-06-30T23:30:00Z", 10.0)
                argv = [
                    "fetch_latest_month.py", "--apply", "--datasets", "prices",
                    "--start-date", "2025-07-01", "--end-date", "2025-07-31",
                ]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(monthly, "fetch_prices", return_value=[outside, inside]) as fetch, mock.patch.object(sys, "stdout", io.StringIO()):
                    self.assertEqual(monthly.main(), 0)
                    fetch.assert_called_once()
                self.assertTrue(Path("prices/year=2025/month=7/data_0.parquet").exists())
                first = json.loads(Path("reports/fetch_latest_month_latest.json").read_text(encoding="utf-8"))
                self.assertEqual(first["perMonth"]["2025-07"]["prices"]["boundaryRowsDiscarded"], 1)

                with mock.patch.object(sys, "argv", argv), mock.patch.object(monthly, "fetch_prices") as fetch, mock.patch.object(sys, "stdout", io.StringIO()):
                    self.assertEqual(monthly.main(), 0)
                    fetch.assert_not_called()
                second = json.loads(Path("reports/fetch_latest_month_latest.json").read_text(encoding="utf-8"))
                self.assertEqual(second["plan"][0]["action"], "SKIP_FROZEN")
            finally:
                os.chdir(old_cwd)


class GrowthGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.partition = "prices/year=2026/month=8"
        self.path = self.root / self.partition / "data_0.parquet"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"1234")
        self.audit = {
            "apply": True,
            "mode": "FILL_MISSING",
            "plan": [{"partition": self.partition, "action": "ADD_MISSING"}],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def evaluate(self, changes: list[tuple[str, str]], files: int = 9, size: int = 1024) -> dict[str, object]:
        return evaluate_changes(self.audit, changes, self.root, max_new_parquet_files=files, max_new_parquet_bytes=size)

    def test_clean_addition_passes(self) -> None:
        result = self.evaluate([("A", f"{self.partition}/data_0.parquet")])
        self.assertEqual(result["status"], "PASS")

    def test_historical_modification_fires(self) -> None:
        result = self.evaluate([("M", f"{self.partition}/data_0.parquet")])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("must only add" in error for error in result["errors"]))

    def test_unplanned_partition_fires(self) -> None:
        result = self.evaluate([("A", "prices/year=2026/month=7/data_0.parquet")])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("outside the audited plan" in error for error in result["errors"]))

    def test_raw_artifact_fires(self) -> None:
        result = self.evaluate([("A", f"{self.partition}/raw.csv")])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("non-Parquet" in error for error in result["errors"]))

    def test_byte_budget_fires(self) -> None:
        result = self.evaluate([("A", f"{self.partition}/data_0.parquet")], size=3)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("bytes exceed" in error for error in result["errors"]))

    def test_identical_explicit_repair_is_a_clean_noop(self) -> None:
        repair = {
            "apply": True,
            "mode": "EXPLICIT_REPAIR",
            "plan": [{"partition": self.partition, "action": "REPAIR_EXISTING"}],
        }
        result = evaluate_changes(repair, [], self.root, max_new_parquet_files=9, max_new_parquet_bytes=1024)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["limits"]["actualChangedParquetFiles"], 0)

    def test_cli_reads_gits_actual_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "fixture"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
            (repo / "seed.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True)
            partition = "prices/year=2026/month=8"
            data = repo / partition / "data_0.parquet"
            data.parent.mkdir(parents=True)
            data.write_bytes(b"fixture")
            audit = repo / "reports/fetch_latest_month_latest.json"
            audit.parent.mkdir(parents=True)
            audit.write_text(json.dumps({
                "apply": True,
                "mode": "FILL_MISSING",
                "plan": [{"partition": partition, "action": "ADD_MISSING"}],
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "pipelines/verify_bounded_growth.py"), "--audit", str(audit), "--base", "HEAD", "--report", ""],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
