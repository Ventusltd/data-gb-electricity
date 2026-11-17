#!/usr/bin/env python3
"""Offline, typed daily system-sell products for bounded browser consumption."""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipelines'))
from gb_calendar import london_midnight_utc
from build_price_decade_rollup import price_input_glob, require_price_grain

SCHEMA = 'data-gb-electricity.system-sell-daily.v1'
UNIT = 'GBP/MWh'
BASIS = 'ELEXON_SYSTEM_SELL_PRICE'
QUANTUM = Decimal('0.000001')


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def six(value):
    if value is None:
        return None
    return float(value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN))


def source_manifest(repo):
    return [{'path': str(p.relative_to(repo)).replace('\\', '/'), 'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size}
            for p in sorted((repo / 'prices').glob('year=*/month=*/data_*.parquet'))]


def daily_rows(repo):
    import duckdb
    with duckdb.connect() as db:
        db.execute("SET TimeZone='UTC'")
        grain = require_price_grain(db, price_input_glob(str(repo)))
        db.read_parquet(price_input_glob(str(repo)), hive_partitioning=False).create_view('prices')
        types = {row[0]: row[1] for row in db.execute('DESCRIBE prices').fetchall()}
        expected = {'settlementDate': 'DATE', 'settlementPeriod': 'BIGINT',
                    'periodStartUTC': 'TIMESTAMP WITH TIME ZONE', 'systemSellPriceGBPperMWh': 'DOUBLE'}
        if any(types.get(k) != v for k, v in expected.items()):
            raise ValueError('Unexpected original source types')
        date_values = [row[0] for row in db.execute('SELECT DISTINCT settlementDate::VARCHAR FROM prices ORDER BY 1').fetchall()]
        if any(value is None for value in date_values):
            raise ValueError('Missing source-declared settlement date')
        dates = [dt.date.fromisoformat(value) for value in date_values]
        start, end = dates[0], dates[-1]
        if start.year < 1996 or (end-start).days > 366*100:
            raise ValueError('Calendar is outside the declared bounded GB rules')
        calendar = []
        day = start
        while day <= end:
            first, next_first = london_midnight_utc(day), london_midnight_utc(day + dt.timedelta(days=1))
            calendar.append((day.isoformat(), int(first.timestamp()), int((next_first-first).total_seconds()/1800)))
            day += dt.timedelta(days=1)
        db.execute('CREATE TABLE gb_days(day VARCHAR PRIMARY KEY,start_epoch BIGINT,expected INTEGER)')
        db.execute('''INSERT INTO gb_days SELECT r.day,r.start_epoch,r.expected
            FROM UNNEST(?::STRUCT(day VARCHAR,start_epoch BIGINT,expected INTEGER)[]) input(r)''',
            [[{'day':day,'start_epoch':epoch,'expected':count} for day,epoch,count in calendar]])
        bad = db.execute('''SELECT count(*) FROM prices p LEFT JOIN gb_days c ON p.settlementDate::VARCHAR=c.day
            WHERE c.day IS NULL OR p.settlementPeriod IS NULL OR p.settlementPeriod<1 OR p.settlementPeriod>c.expected''').fetchone()[0]
        duplicate_declared = db.execute('SELECT count(*) FROM (SELECT settlementDate,settlementPeriod FROM prices GROUP BY 1,2 HAVING count(*)>1)').fetchone()[0]
        if bad or duplicate_declared:
            raise ValueError('Invalid or duplicate source-declared GB date/period identity')
        groups = {row[0]: row[1:] for row in db.execute('''SELECT settlementDate::VARCHAR,
            count(*), count(systemSellPriceGBPperMWh), list(systemSellPriceGBPperMWh ORDER BY settlementPeriod),
            count(*) FILTER(WHERE epoch(periodStartUTC)<>c.start_epoch+(settlementPeriod-1)*1800)
            FROM prices p JOIN gb_days c ON p.settlementDate::VARCHAR=c.day GROUP BY 1 ORDER BY 1''').fetchall()}
        rows = []
        with localcontext() as context:
            context.prec = 90
            for day, _, expected_periods in calendar:
                observed, priced, values, mismatches = groups.get(day, (0, 0, [], 0))
                values = [Decimal.from_float(v) for v in values if v is not None]
                mean = sum(values, Decimal(0)) / len(values) if values else None
                status = 'NO_OBSERVATIONS' if not observed else 'COMPLETE_SOURCE_DAY' if priced == observed == expected_periods else 'PARTIAL_SOURCE_DAY'
                rows.append({'date': day, 'expected_periods': expected_periods, 'observed_periods': observed,
                             'priced_periods': priced, 'coverage_status': status,
                             'utc_alignment_mismatches': mismatches,
                             'price_coverage_pct': round(100*priced/expected_periods, 6),
                             'mean_available_gbp_per_mwh': six(mean),
                             'minimum_observed_gbp_per_mwh': six(min(values)) if values else None,
                             'maximum_observed_gbp_per_mwh': six(max(values)) if values else None})
        window = db.execute('SELECT min(periodStartUTC)::VARCHAR,max(periodStartUTC)::VARCHAR FROM prices').fetchone()
    return rows, grain, window


def compile_products(repo, folder):
    import duckdb
    before = source_manifest(repo)
    rows, grain, window = daily_rows(repo)
    years = sorted({int(r['date'][:4]) for r in rows})
    source = {'schema': SCHEMA + '.sources', 'source_grain': 'periodStartUTC', 'price_basis': BASIS,
              'source_field': 'systemSellPriceGBPperMWh', 'repository': 'Ventusltd/data-gb-electricity',
              'endpoint': 'https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices',
              'files': before, 'input_grain': grain, 'first_stored_period_utc': window[0], 'last_stored_period_utc': window[1],
              'utc_alignment_mismatches': sum(r['utc_alignment_mismatches'] for r in rows),
              'calendar_quality': 'Source-declared settlement dates/periods retained. Legacy stored UTC fields can disagree; counters report this without correcting frozen source history.'}
    sources = encode(source)
    (folder / 'sources.json').write_bytes(sources)
    parts = []
    for year in years:
        selected = [r for r in rows if r['date'].startswith(str(year) + '-')]
        payload = {'schema': SCHEMA, 'year': year, 'unit': UNIT, 'price_basis': BASIS,
                   'time_basis': 'Source-declared GB settlement date in Europe/London; stored UTC alignment reported separately',
                   'mean_basis': 'Available reported settlement-period prices; no interpolation',
                   'rounding': 'Six decimal places, half-even, from exact stored IEEE-754 source values',
                   'rows': selected}
        raw = encode(payload)
        name = str(year) + '.json'
        (folder / name).write_bytes(raw)
        parts.append({'year': year, 'path': name, 'sha256': digest(raw), 'bytes': len(raw),
                      'calendar_days': len(selected), 'observed_days': sum(r['observed_periods']>0 for r in selected),
                      'complete_days': sum(r['coverage_status']=='COMPLETE_SOURCE_DAY' for r in selected),
                      'partial_days': sum(r['coverage_status']=='PARTIAL_SOURCE_DAY' for r in selected),
                      'missing_days': sum(r['coverage_status']=='NO_OBSERVATIONS' for r in selected)})
    parquet = folder / 'daily.parquet'
    with duckdb.connect() as db:
        db.execute('CREATE TABLE daily(date VARCHAR PRIMARY KEY,expected_periods INTEGER,observed_periods INTEGER,priced_periods INTEGER,coverage_status VARCHAR,utc_alignment_mismatches INTEGER,price_coverage_pct DOUBLE,mean_available_gbp_per_mwh DOUBLE,minimum_observed_gbp_per_mwh DOUBLE,maximum_observed_gbp_per_mwh DOUBLE)')
        fields = list(rows[0])
        actual_rows = [tuple(r[k] for k in fields) for r in rows]
        db.execute('''INSERT INTO daily SELECT r.date,r.expected_periods,r.observed_periods,r.priced_periods,
            r.coverage_status,r.utc_alignment_mismatches,r.price_coverage_pct,r.mean_available_gbp_per_mwh,
            r.minimum_observed_gbp_per_mwh,r.maximum_observed_gbp_per_mwh FROM UNNEST(?::STRUCT(
            date VARCHAR,expected_periods INTEGER,observed_periods INTEGER,priced_periods INTEGER,
            coverage_status VARCHAR,utc_alignment_mismatches INTEGER,price_coverage_pct DOUBLE,
            mean_available_gbp_per_mwh DOUBLE,minimum_observed_gbp_per_mwh DOUBLE,maximum_observed_gbp_per_mwh DOUBLE)[]) input(r)''', [rows])
        db.sql('SELECT * FROM daily ORDER BY date').write_parquet(str(parquet), compression='zstd')
        reread = db.execute('SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY date', [str(parquet)]).fetchall()
        if reread != actual_rows:
            raise ValueError('Daily full-row Parquet readback mismatch')
        if db.execute('SELECT DISTINCT compression FROM parquet_metadata(?)', [str(parquet)]).fetchall() != [('ZSTD',)]:
            raise ValueError('Unexpected Parquet compression')
    if source_manifest(repo) != before:
        raise ValueError('Source files changed during build')
    index = {'schema': SCHEMA + '.index', 'unit': UNIT, 'price_basis': BASIS,
             'time_basis': 'Source-declared GB settlement date in Europe/London; stored UTC alignment reported separately',
             'source_grain': 'Source-declared settlementDate plus settlementPeriod; original stored periodStartUTC remains the upstream key',
             'first_date': rows[0]['date'], 'last_date': rows[-1]['date'], 'rows': len(rows),
             'source_periods': grain['rows'], 'observed_periods': sum(r['observed_periods'] for r in rows),
             'priced_periods': sum(r['priced_periods'] for r in rows), 'parts': parts,
             'utc_alignment_mismatches': source['utc_alignment_mismatches'], 'calendar_quality': source['calendar_quality'],
             'sources': {'path':'sources.json','bytes':len(sources),'sha256':digest(sources)},
             'parquet': {'path':'daily.parquet','bytes':parquet.stat().st_size,'sha256':digest(parquet.read_bytes()),'rows':len(rows),'compression':'ZSTD','full_row_readback':'PASS'},
             'engine': 'duckdb-' + duckdb.__version__, 'producer_sha256': digest(Path(__file__).read_bytes()),
             'scope': 'Historical system-sell prices; no market-index merge, realtime quote or forecast'}
    if index['source_periods'] != index['observed_periods']:
        raise ValueError('Daily aggregation lost source rows')
    (folder / 'index.json').write_bytes(encode(index))
    return index


def run(repo, output, verify=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='price-daily-stage-', dir=output.parent) as temporary:
        stage = Path(temporary)
        index = compile_products(repo, stage)
        produced = {p.name for p in stage.iterdir()}
        if verify:
            actual = {p.name for p in output.iterdir() if p.is_file()}
            if actual != produced or any((output/p).read_bytes() != (stage/p).read_bytes() for p in produced):
                raise ValueError('Daily committed products differ from actual source rebuild')
        else:
            if output.exists() and any(p.is_file() and p.name not in produced for p in output.iterdir()):
                raise ValueError('Unexpected existing output; no silent history deletion')
            output.mkdir(exist_ok=True)
            for name in sorted(produced - {'index.json'}) + ['index.json']:
                target = output / name
                if not target.exists() or target.read_bytes() != (stage/name).read_bytes():
                    (stage/name).replace(target)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    index = run(args.repo, args.output or args.repo/'derived/price-daily-browser', args.verify)
    print(json.dumps({'status':'PASS','source_periods':index['source_periods'],'calendar_days':index['rows'],
                      'last_date':index['last_date'],'years':len(index['parts']),
                      'largest_year_bytes':max(p['bytes'] for p in index['parts']), 'parquet_bytes':index['parquet']['bytes']}))


if __name__ == '__main__':
    main()
