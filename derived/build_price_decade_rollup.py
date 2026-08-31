"""Derive the price decade rollup: a browser-sized product over this repo's own Parquet.

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
A day needs at least 24 of its 48 periods to count as a day at all, and the
number of days behind every year is carried with it, so a partial year reads as
partial rather than being quietly averaged in.

PRICES ONLY, DELIBERATELY
-------------------------
Solar is not here. PVLive has not been decided into this repository -- item 4 of
the migration scope leaves it open between here, a separate solar repo, or a
deferred no-data state. Inventing a solar product here to make a panel look
fuller would be the exact failure the discipline manual exists to prevent, so
the rollup states that solar is absent and why.

    python derived/build_price_decade_rollup.py
"""

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
    lowest = None
    highest = None
    for day, day_mean, day_low, day_high, _periods in rows:
        year = str(day)[:4]
        by_year[year].append(float(day_mean))
        # Counted separately from the daily mean. A mean hides a negative half
        # hour completely, and negative half hours are the export limitation
        # and curtailment question for anyone building generation.
        if day_low is not None and float(day_low) < 0:
            negative[year] += 1
        if day_low is not None and (lowest is None or float(day_low) < lowest["value"]):
            lowest = {"value": round(float(day_low), 2), "date": str(day)}
        if day_high is not None and (highest is None or float(day_high) > highest["value"]):
            highest = {"value": round(float(day_high), 2), "date": str(day)}

    by_year_out = [{
        "year": year,
        "days": len(values),
        "mean_gbp_per_mwh": round(mean(values), 2),
        "min_daily_mean": round(min(values), 2),
        "max_daily_mean": round(max(values), 2),
        "days_with_a_negative_settlement_period": negative.get(year, 0),
    } for year, values in sorted(by_year.items())]

    all_days = [v for values in by_year.values() for v in values]

    product = {
        "schema": "data-gb-electricity.price-decade-rollup.v1",
        "what_this_is": (
            "Yearly aggregates of the GB system sell price, derived from the "
            "Parquet in this repository so that a browser can carry the decade "
            "without carrying the settlement periods. Arithmetic aggregates "
            "only: no resampling, smoothing, modelling or forecasting."),
        "not_a_forecast": (
            "Historic system conditions. Not a projection, not a price "
            "expectation, and not a statement about the economics of any "
            "project or asset."),
        "grain": {
            "source_grain": "half-hourly settlement period",
            "product_grain": "calendar year, over daily means",
            "minimum_periods_per_day": MIN_PERIODS_PER_DAY,
            "note": ("a day below the minimum is excluded rather than averaged, "
                     "so the day counts below are complete days"),
        },
        "derived_from": {
            "repository": "Ventusltd/data-gb-electricity",
            "path": "prices/year=*/month=*/data_0.parquet",
            "field": FIELD,
            "upstream": "Elexon",
            "settlement_periods": periods,
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
            "decade_mean": round(mean(all_days), 2),
            "lowest_settlement_period": lowest,
            "highest_settlement_period": highest,
            "days_with_a_negative_settlement_period": sum(negative.values()),
            "by_year": by_year_out,
        },
    }

    out_dir = os.path.join(HERE)
    out = os.path.join(out_dir, "price-decade-rollup.json")
    io.open(out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(product, ensure_ascii=False, indent=2) + "\n")

    print("wrote derived/price-decade-rollup.json (%.1f kB)"
          % (os.path.getsize(out) / 1024.0))
    print("  %s-%s, %d settlement periods, %d complete days"
          % (product["price"]["span"][0], product["price"]["span"][1],
             periods, len(all_days)))
    print("  mean %.2f GBP/MWh, %d days with a negative period"
          % (product["price"]["decade_mean"],
             product["price"]["days_with_a_negative_settlement_period"]))
    print("  lowest %s" % lowest)
    print("  highest %s" % highest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
