"""Derive the price record rollup: a browser-sized product over this repo's own Parquet.

WHY IT LIVES HERE
-----------------
The governing rule in UI_CHARTS_MIGRATION_SCOPE.md is "data before charts": the
UI repository must consume data products that already sit clean, and must not
own source data or create a second source of truth. Blocker 2 of that scope
asks for exactly this -- "create any missing derived browser/rollup products
needed by the charts".

So the rollup is defined here, beside the Parquet it aggregates, and consumers
read it. It is about six kilobytes against roughly a hundred megabytes of
settlement periods, which is the difference between a chart that opens on a
phone and one that does not.

Known consumers:
  - Ventusltd/gb-electricity-ui   the chart layer
  - Ventusltd/gridatlas           a panel beside the map of generation projects

WHAT IT IS NOT
--------------
No resampling, smoothing, modelling or forecasting. Every figure is an
arithmetic aggregate of settlement periods that are already in this repository.
A day needs at least 24 of its 48 periods to count as a day at all. The number
of included dates, calendar dates and coverage percentage behind every year are
carried together, so a partial year reads as partial rather than being quietly
presented like a full calendar year. A day meeting the 24-period floor is called
included, never complete: 24 out of 48 is an inclusion rule, not proof that the
day is complete.

PRICES ONLY, DELIBERATELY
-------------------------
Solar is not here. PVLive has not been decided into this repository -- item 4 of
the migration scope leaves it open between here, a separate solar repo, or a
deferred no-data state. Inventing a solar product here to make a panel look
fuller would be the exact failure the discipline manual exists to prevent, so
the rollup states that solar is absent and why.

    python derived/build_price_decade_rollup.py
"""

import calendar
import io
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Half of the 48 settlement periods. Below that a "daily mean" is a mean of
# whatever happened to be collected, which is a different quantity.
MIN_PERIODS_PER_DAY = 24

FIELD = "systemSellPriceGBPperMWh"


def mean(values):
    return sum(values) / len(values) if values else None


def percentage(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else None


def extreme(con, glob, direction):
    """Return the exact price period at one extreme, on an included date."""
    if direction not in ("ASC", "DESC"):
        raise ValueError("invalid price direction")
    row = con.execute("""
        WITH included_days AS (
          SELECT settlementDate
          FROM read_parquet(?)
          WHERE {field} IS NOT NULL
          GROUP BY 1
          HAVING count(*) >= {minimum}
        )
        SELECT p.{field}, p.settlementDate, p.settlementPeriod,
               strftime(p.periodStartUTC AT TIME ZONE 'UTC',
                        '%Y-%m-%dT%H:%M:%SZ')
        FROM read_parquet(?) p
        INNER JOIN included_days d USING (settlementDate)
        WHERE p.{field} IS NOT NULL
        ORDER BY p.{field} {direction}, p.periodStartUTC ASC
        LIMIT 1
    """.format(field=FIELD, minimum=MIN_PERIODS_PER_DAY, direction=direction),
        [glob, glob]).fetchone()
    if row is None:
        return None
    value, day, period, start_utc = row
    return {
        "value": round(float(value), 2),
        "date": str(day),
        "settlement_period": int(period),
        "period_start_utc": start_utc,
    }


def main():
    import duckdb

    glob = os.path.join(REPO, "prices", "year=*", "month=*",
                        "data_0.parquet").replace("\\", "/")
    con = duckdb.connect()

    periods = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE %s IS NOT NULL" % FIELD,
        [glob]).fetchone()[0]

    rows = con.execute("""
        SELECT settlementDate AS day,
               avg({field}) AS day_mean,
               min({field}) AS day_low,
               max({field}) AS day_high,
               count(*) AS periods
        FROM read_parquet(?)
        WHERE {field} IS NOT NULL
        GROUP BY 1
        HAVING count(*) >= {min}
        ORDER BY 1
    """.format(field=FIELD, min=MIN_PERIODS_PER_DAY), [glob]).fetchall()

    if not rows:
        raise SystemExit("no price rows matched %s" % glob)

    by_year = defaultdict(list)
    negative = defaultdict(int)
    included_periods = 0
    for day, day_mean, day_low, _day_high, day_periods in rows:
        year = str(day)[:4]
        by_year[year].append(float(day_mean))
        included_periods += int(day_periods)
        # Counted separately from the daily mean because a daily mean can hide
        # a negative within-day observation. No project effect is inferred.
        if day_low is not None and float(day_low) < 0:
            negative[year] += 1

    lowest = extreme(con, glob, "ASC")
    highest = extreme(con, glob, "DESC")

    by_year_out = []
    for year, values in sorted(by_year.items()):
        included_days = len(values)
        calendar_days = 366 if calendar.isleap(int(year)) else 365
        negative_days = negative.get(year, 0)
        by_year_out.append({
            "year": year,
            # Compatibility alias for consumers published against v1. New
            # consumers must use days_included and show its coverage.
            "days": included_days,
            "days_included": included_days,
            "calendar_days": calendar_days,
            "calendar_date_coverage_pct": percentage(included_days, calendar_days),
            "calendar_date_coverage": (
                "FULL_DATE_COVERAGE" if included_days == calendar_days
                else "PARTIAL_DATE_COVERAGE"),
            "mean_gbp_per_mwh": round(mean(values), 2),
            "min_daily_mean": round(min(values), 2),
            "max_daily_mean": round(max(values), 2),
            "days_with_a_negative_settlement_period": negative_days,
            "negative_period_day_share_pct": percentage(negative_days, included_days),
        })

    all_days = [v for values in by_year.values() for v in values]

    product = {
        "schema": "data-gb-electricity.price-decade-rollup.v2",
        "what_this_is": (
            "Yearly aggregates of the available GB system sell-price record, "
            "derived from the Parquet in this repository so that a browser can "
            "carry the history without carrying the settlement periods. Arithmetic aggregates "
            "only: no resampling, smoothing, modelling or forecasting."),
        "not_a_forecast": (
            "Historic system conditions. Not a projection, not a price "
            "expectation, and not a statement about the economics of any "
            "project or asset."),
        "grain": {
            "source_grain": "half-hourly settlement period",
            "product_grain": "calendar year, over daily means",
            "minimum_periods_per_day": MIN_PERIODS_PER_DAY,
            "note": ("a date with fewer than the minimum available periods is "
                     "excluded rather than averaged. A retained date is included, "
                     "not necessarily complete; calendar-date coverage is carried "
                     "for every year"),
        },
        "derived_from": {
            "repository": "Ventusltd/data-gb-electricity",
            "path": "prices/year=*/month=*/data_0.parquet",
            "field": FIELD,
            "upstream": "Elexon",
            "settlement_periods": periods,
            "settlement_periods_on_included_dates": included_periods,
            "included_days": len(all_days),
            # Compatibility alias for already-published readers. Its name is
            # deprecated: a 24-period floor does not prove a complete day.
            "complete_days": len(all_days),
        },
        "solar": {
            "present": False,
            "why": ("PVLive has not been decided into this repository. Item 4 of "
                    "UI_CHARTS_MIGRATION_SCOPE.md leaves it open between here, a "
                    "separate solar data repository, and a deferred no-data "
                    "state. Inventing a solar series here to make a panel look "
                    "fuller is the failure the data discipline exists to "
                    "prevent."),
        },
        "price": {
            "unit": "GBP per MWh",
            "span": [by_year_out[0]["year"], by_year_out[-1]["year"]],
            "available_record_daily_mean": round(mean(all_days), 2),
            # Compatibility alias for already-published readers. The available
            # record spans 11 calendar labels and has gaps.
            "decade_mean": round(mean(all_days), 2),
            "lowest_settlement_period": lowest,
            "highest_settlement_period": highest,
            "days_with_a_negative_settlement_period": sum(negative.values()),
            "negative_period_day_share_pct": percentage(
                sum(negative.values()), len(all_days)),
            "by_year": by_year_out,
        },
    }

    out_dir = os.path.join(HERE)
    out = os.path.join(out_dir, "price-decade-rollup.json")
    io.open(out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(product, ensure_ascii=False, indent=2) + "\n")

    print("wrote derived/price-decade-rollup.json (%.1f kB)"
          % (os.path.getsize(out) / 1024.0))
    print("  %s-%s, %d settlement periods, %d included days"
          % (product["price"]["span"][0], product["price"]["span"][1],
             periods, len(all_days)))
    print("  mean %.2f GBP/MWh, %d days with a negative period"
          % (product["price"]["available_record_daily_mean"],
             product["price"]["days_with_a_negative_settlement_period"]))
    print("  lowest %s" % lowest)
    print("  highest %s" % highest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
