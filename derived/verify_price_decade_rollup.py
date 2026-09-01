"""Fail-closed semantic proof for the browser-sized GB price product."""

import calendar
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PATH = os.path.join(HERE, "price-decade-rollup.json")


def close(left, right, tolerance=0.011):
    return abs(float(left) - float(right)) <= tolerance


def main():
    with open(PATH, encoding="utf-8") as stream:
        product = json.load(stream)

    assert product["schema"] == "data-gb-electricity.price-decade-rollup.v2"
    assert product["not_a_forecast"]
    assert product["solar"]["present"] is False
    assert "complete days" not in product["grain"]["note"].lower()

    rows = product["price"]["by_year"]
    assert len(rows) >= 10
    assert [row["year"] for row in rows] == sorted(row["year"] for row in rows)

    included = 0
    negative = 0
    partial = 0
    for row in rows:
        expected = 366 if calendar.isleap(int(row["year"])) else 365
        assert row["days"] == row["days_included"]
        assert row["calendar_days"] == expected
        assert close(row["calendar_date_coverage_pct"],
                     100.0 * row["days_included"] / expected)
        want_status = ("FULL_DATE_COVERAGE"
                       if row["days_included"] == expected
                       else "PARTIAL_DATE_COVERAGE")
        assert row["calendar_date_coverage"] == want_status
        partial += want_status == "PARTIAL_DATE_COVERAGE"
        assert close(row["negative_period_day_share_pct"],
                     100.0 * row["days_with_a_negative_settlement_period"]
                     / row["days_included"])
        included += row["days_included"]
        negative += row["days_with_a_negative_settlement_period"]

    assert partial > 0, "disease fixture: real product must expose partial years"
    assert included == product["derived_from"]["included_days"]
    assert included == product["derived_from"]["complete_days"]
    assert negative == product["price"]["days_with_a_negative_settlement_period"]
    assert close(product["price"]["negative_period_day_share_pct"],
                 100.0 * negative / included)
    assert (product["price"]["available_record_daily_mean"]
            == product["price"]["decade_mean"])

    for name in ("lowest_settlement_period", "highest_settlement_period"):
        price_extreme = product["price"][name]
        assert set(price_extreme) == {
            "value", "date", "settlement_period", "period_start_utc"}
        assert 1 <= price_extreme["settlement_period"] <= 50
        assert price_extreme["period_start_utc"]

    assert (product["derived_from"]["settlement_periods_on_included_dates"]
            <= product["derived_from"]["settlement_periods"])

    # Re-read the owner Parquet. Shape-only tests would bless a self-consistent
    # lie if both the product and its builder drifted together.
    import duckdb
    parquet_glob = os.path.join(REPO, "prices", "year=*", "month=*",
                                "data_0.parquet").replace("\\", "/")
    connection = duckdb.connect()
    source_periods = connection.execute(
        "SELECT count(*) FROM read_parquet(?) "
        "WHERE systemSellPriceGBPperMWh IS NOT NULL", [parquet_glob]).fetchone()[0]
    assert source_periods == product["derived_from"]["settlement_periods"]
    source_days = connection.execute("""
        SELECT count(*), sum(periods)
        FROM (
          SELECT settlementDate, count(*) AS periods
          FROM read_parquet(?)
          WHERE systemSellPriceGBPperMWh IS NOT NULL
          GROUP BY 1
          HAVING count(*) >= ?
        )
    """, [parquet_glob, product["grain"]["minimum_periods_per_day"]]).fetchone()
    assert source_days[0] == product["derived_from"]["included_days"]
    assert source_days[1] == product["derived_from"]["settlement_periods_on_included_dates"]

    for name, direction in (("lowest_settlement_period", "ASC"),
                            ("highest_settlement_period", "DESC")):
        row = connection.execute("""
            WITH included_days AS (
              SELECT settlementDate
              FROM read_parquet(?)
              WHERE systemSellPriceGBPperMWh IS NOT NULL
              GROUP BY 1 HAVING count(*) >= ?
            )
            SELECT p.systemSellPriceGBPperMWh, p.settlementDate,
                   p.settlementPeriod,
                   strftime(p.periodStartUTC AT TIME ZONE 'UTC',
                            '%Y-%m-%dT%H:%M:%SZ')
            FROM read_parquet(?) p
            INNER JOIN included_days d USING (settlementDate)
            WHERE p.systemSellPriceGBPperMWh IS NOT NULL
            ORDER BY p.systemSellPriceGBPperMWh {direction}, p.periodStartUTC ASC
            LIMIT 1
        """.format(direction=direction), [parquet_glob,
                           product["grain"]["minimum_periods_per_day"],
                           parquet_glob]).fetchone()
        observed = product["price"][name]
        assert close(observed["value"], row[0])
        assert observed["date"] == str(row[1])
        assert observed["settlement_period"] == row[2]
        assert observed["period_start_utc"] == row[3]
    print("PASS: price rollup v2 states inclusion, coverage, shares and exact extremes")


if __name__ == "__main__":
    main()
