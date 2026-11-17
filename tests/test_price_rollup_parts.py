"""Synthetic split-part regression; no upstream fetch or historical rewrite."""
import datetime
import importlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'derived'))
builder = importlib.import_module('build_price_decade_rollup')
verifier = importlib.import_module('verify_price_decade_rollup')


class SplitPricePartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temp.name)
        self.derived = self.repo / 'derived'
        self.derived.mkdir()
        self.db = duckdb.connect(':memory:')
        self.db.execute('CREATE TABLE fixture(settlementDate DATE,settlementPeriod BIGINT,periodStartUTC TIMESTAMPTZ,systemSellPriceGBPperMWh DOUBLE)')
        for year in range(2016, 2026):
            for part in (0, 1):
                rows = []
                for period in range(part * 12, (part + 1) * 12):
                    stamp = datetime.datetime(year, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(minutes=period * 30)
                    rows.append((stamp.date().isoformat(), period + 1, stamp.isoformat(), float(period - 10)))
                self.db.execute('DELETE FROM fixture')
                self.db.executemany('INSERT INTO fixture VALUES (CAST(? AS DATE),?,CAST(? AS TIMESTAMPTZ),?)', rows)
                target = self.repo / 'prices' / f'year={year}' / 'month=1' / f'data_{part}.parquet'
                target.parent.mkdir(parents=True, exist_ok=True)
                self.db.sql('SELECT * FROM fixture ORDER BY periodStartUTC').write_parquet(str(target), compression='zstd')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_builder(self):
        with patch.object(builder, 'REPO', str(self.repo)), patch.object(builder, 'HERE', str(self.derived)):
            builder.main()
        return json.loads((self.derived / 'price-decade-rollup.json').read_text(encoding='utf-8'))

    def test_all_physical_parts_combine_before_daily_inclusion_and_verify(self):
        product = self.run_builder()
        self.assertEqual(product['derived_from']['settlement_periods'], 240)
        self.assertEqual(product['derived_from']['included_days'], 10)
        self.assertTrue(all(row['days_included'] == 1 for row in product['price']['by_year']))
        self.assertEqual(product['derived_from']['input_grain']['distinct_periods'], 240)
        with patch.object(verifier, 'REPO', str(self.repo)), patch.object(verifier, 'PATH', str(self.derived / 'price-decade-rollup.json')):
            verifier.main()

    def test_a_duplicate_in_an_extra_part_fails_before_output_replacement(self):
        target = self.derived / 'price-decade-rollup.json'
        target.write_text('accepted previous bytes', encoding='utf-8')
        source = self.repo / 'prices/year=2016/month=1/data_0.parquet'
        duplicate = source.with_name('data_2.parquet')
        duplicate.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Price grain failed'):
            self.run_builder()
        self.assertEqual(target.read_text(encoding='utf-8'), 'accepted previous bytes')

    def test_null_period_in_extra_part_is_not_hidden_by_daily_aggregation(self):
        self.db.execute('DELETE FROM fixture')
        self.db.execute("INSERT INTO fixture VALUES ('2016-01-01',49,NULL,12)")
        target = self.repo / 'prices/year=2016/month=1/data_2.parquet'
        self.db.sql('SELECT * FROM fixture').write_parquet(str(target), compression='zstd')
        with self.assertRaisesRegex(ValueError, 'Price grain failed'):
            self.run_builder()

    def test_nonfinite_price_does_not_become_an_aggregate(self):
        self.db.execute('DELETE FROM fixture')
        self.db.execute("INSERT INTO fixture VALUES ('2016-01-02',1,'2016-01-02T00:00:00Z','NaN'::DOUBLE)")
        target = self.repo / 'prices/year=2016/month=1/data_2.parquet'
        self.db.sql('SELECT * FROM fixture').write_parquet(str(target), compression='zstd')
        with self.assertRaisesRegex(ValueError, 'Price grain failed'):
            self.run_builder()


if __name__ == '__main__':
    unittest.main()
