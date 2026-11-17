"""Synthetic daily source-grain/DST/coverage checks, plus actual-source replay."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'derived'))
import price_daily_browser as producer


class DailyBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.output = self.repo / 'derived/product'
        self.db = duckdb.connect()
        self.db.execute('CREATE TABLE fixture(settlementDate DATE,settlementPeriod BIGINT,periodStartUTC TIMESTAMPTZ,systemSellPriceGBPperMWh DOUBLE,marketIndexPrice DOUBLE)')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add_day(self, date, periods, first_utc, missing=(), null_price=(), split=False):
        first = dt.datetime.fromisoformat(first_utc.replace('Z', '+00:00'))
        for part in range(2 if split else 1):
            self.db.execute('DELETE FROM fixture')
            rows = [(date, i, (first+dt.timedelta(minutes=(i-1)*30)).isoformat(), None if i in null_price else float(i), 999.0)
                    for i in range(1, periods+1) if i not in missing and (not split or (i-1)%2 == part)]
            self.db.executemany('INSERT INTO fixture VALUES (CAST(? AS DATE),?,CAST(? AS TIMESTAMPTZ),?,?)', rows)
            target = self.repo / f'prices/year={date[:4]}/month={int(date[5:7])}/data_{date}_{part}.parquet'
            target.parent.mkdir(parents=True, exist_ok=True)
            self.db.sql('SELECT * FROM fixture ORDER BY periodStartUTC').write_parquet(str(target), compression='zstd')

    def result(self):
        index = producer.run(self.repo, self.output)
        data = json.loads((self.output / str(index['parts'][0]['year'])).with_suffix('.json').read_bytes())
        return index, data['rows']

    def test_spring46_and_autumn50_are_complete_source_days(self):
        for date, n, first in [('2026-03-29',46,'2026-03-29T00:00:00Z'),('2026-10-25',50,'2026-10-24T23:00:00Z')]:
            with self.subTest(date=date):
                self.add_day(date,n,first)
        index, rows = self.result()
        selected = {r['date']:r for r in rows}
        self.assertEqual((selected['2026-03-29']['expected_periods'], selected['2026-10-25']['expected_periods']), (46,50))
        self.assertEqual(selected['2026-03-29']['coverage_status'], 'COMPLETE_SOURCE_DAY')
        self.assertEqual(selected['2026-10-25']['utc_alignment_mismatches'], 0)
        self.assertEqual(index['observed_periods'],96)

    def test_every_physical_part_is_combined_without_market_index_prices(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z',split=True)
        index, rows = self.result()
        self.assertEqual(index['source_periods'],48)
        self.assertEqual(rows[0]['mean_available_gbp_per_mwh'],24.5)
        self.assertEqual(rows[0]['maximum_observed_gbp_per_mwh'],48.0)

    def test_absent_dates_are_explicit_gaps_with_null_prices(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z')
        self.add_day('2026-01-03',48,'2026-01-03T00:00:00Z')
        _, rows = self.result()
        self.assertEqual(rows[1]['date'],'2026-01-02')
        self.assertEqual(rows[1]['coverage_status'],'NO_OBSERVATIONS')
        self.assertIsNone(rows[1]['mean_available_gbp_per_mwh'])

    def test_missing_and_null_periods_are_partial_not_zero_or_imputed(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z',missing=(1,2),null_price=(3,))
        _, rows = self.result()
        self.assertEqual((rows[0]['observed_periods'],rows[0]['priced_periods']),(46,45))
        self.assertEqual(rows[0]['coverage_status'],'PARTIAL_SOURCE_DAY')
        self.assertEqual(rows[0]['minimum_observed_gbp_per_mwh'],4.0)

    def test_legacy_utc_clock_disagreement_is_retained_and_counted(self):
        self.add_day('2026-07-01',48,'2026-07-01T00:00:00Z')
        index, rows = self.result()
        self.assertEqual(rows[0]['utc_alignment_mismatches'],48)
        self.assertEqual(index['utc_alignment_mismatches'],48)
        self.assertEqual(rows[0]['mean_available_gbp_per_mwh'],24.5)
        self.assertIn('Source-declared', index['time_basis'])

    def test_legacy_october_clock_collision_loss_stays_partial_on_oct31(self):
        self.add_day('2016-10-30',50,'2016-10-30T00:00:00Z')
        self.add_day('2016-10-31',48,'2016-10-31T00:00:00Z',missing=(1,2))
        _, rows=self.result()
        self.assertEqual((rows[0]['expected_periods'],rows[0]['utc_alignment_mismatches']),(50,50))
        self.assertEqual((rows[1]['observed_periods'],rows[1]['expected_periods']),(46,48))
        self.assertEqual(rows[1]['coverage_status'],'PARTIAL_SOURCE_DAY')
        self.assertEqual(rows[1]['price_coverage_pct'],95.833333)

    def test_unremoved_legacy_clock_key_collision_is_rejected(self):
        self.add_day('2016-10-30',50,'2016-10-30T00:00:00Z')
        self.add_day('2016-10-31',48,'2016-10-31T00:00:00Z')
        with self.assertRaisesRegex(ValueError,'Price grain failed'):
            producer.run(self.repo,self.output)
        self.assertFalse(self.output.exists())

    def test_twenty_four_period_floor_never_certifies_a_complete_day(self):
        self.add_day('2026-01-01',24,'2026-01-01T00:00:00Z')
        index, rows=self.result()
        self.assertEqual(rows[0]['coverage_status'],'PARTIAL_SOURCE_DAY')
        self.assertEqual(rows[0]['price_coverage_pct'],50.0)
        self.assertEqual(index['parts'][0]['complete_days'],0)

    def test_no_sell_observations_keep_null_mean_and_zero_price_coverage(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z',null_price=tuple(range(1,49)))
        _, rows=self.result()
        self.assertIsNone(rows[0]['mean_available_gbp_per_mwh'])
        self.assertEqual(rows[0]['price_coverage_pct'],0.0)
        self.assertEqual(rows[0]['coverage_status'],'PARTIAL_SOURCE_DAY')

    def test_duplicate_declared_periods_fail_before_replacing_output(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z')
        self.result()
        saved = (self.output/'index.json').read_bytes()
        self.db.execute('DELETE FROM fixture')
        self.db.execute("INSERT INTO fixture VALUES ('2026-01-01',1,'2026-01-02T00:00:00Z',1,999)")
        self.db.sql('SELECT * FROM fixture').write_parquet(str(self.repo/'prices/year=2026/month=1/data_extra.parquet'))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            producer.run(self.repo,self.output)
        self.assertEqual((self.output/'index.json').read_bytes(),saved)

    def test_impossible_spring_period47_is_not_allowed(self):
        self.add_day('2026-03-29',47,'2026-03-29T00:00:00Z')
        with self.assertRaisesRegex(ValueError,'identity'):
            producer.run(self.repo,self.output)
        self.assertFalse(self.output.exists())

    def test_corrupted_product_is_not_accepted_by_shape_only(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z')
        self.result()
        part=self.output/'2026.json';data=json.loads(part.read_bytes());data['rows'][0]['mean_available_gbp_per_mwh']=999
        part.write_bytes(producer.encode(data))
        with self.assertRaisesRegex(ValueError,'actual source rebuild'):
            producer.run(self.repo,self.output,verify=True)

    def test_negative_prices_remain_negative_and_full_parquet_readback_passes(self):
        self.add_day('2026-01-01',48,'2026-01-01T00:00:00Z')
        p=next((self.repo/'prices').glob('**/*.parquet'))
        self.db.read_parquet(str(p)).create_view('original')
        self.db.sql('SELECT settlementDate,settlementPeriod,periodStartUTC, -systemSellPriceGBPperMWh AS systemSellPriceGBPperMWh,marketIndexPrice FROM original').write_parquet(str(p.with_name('replacement.parquet')))
        p.unlink();p.with_name('replacement.parquet').rename(p)
        index, rows=self.result()
        self.assertEqual(rows[0]['mean_available_gbp_per_mwh'],-24.5)
        self.assertEqual(index['parquet']['full_row_readback'],'PASS')
        self.assertEqual(producer.run(self.repo,self.output,verify=True)['rows'],1)


if __name__ == '__main__':
    unittest.main()
