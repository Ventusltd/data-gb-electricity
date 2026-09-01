#!/usr/bin/env python3
"""Dependency-free Great Britain civil-date helpers for electricity data.

Python on Windows does not ship the IANA timezone database. The updater only
needs two stable GB rules: the local calendar date now, and UTC instants for
local midnight. Since 1996, British Summer Time runs from 01:00 UTC on the last
Sunday in March to 01:00 UTC on the last Sunday in October. The repository's
data starts in 2015, so this rule covers its entire declared span.
"""
from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc


def last_sunday(year: int, month: int) -> dt.date:
    if month == 12:
        first_next = dt.date(year + 1, 1, 1)
    else:
        first_next = dt.date(year, month + 1, 1)
    last = first_next - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() + 1) % 7)


def bst_utc_bounds(year: int) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(last_sunday(year, 3), dt.time(1), tzinfo=UTC)
    end = dt.datetime.combine(last_sunday(year, 10), dt.time(1), tzinfo=UTC)
    return start, end


def london_date_at(instant_utc: dt.datetime) -> dt.date:
    if instant_utc.tzinfo is None:
        raise ValueError("instant_utc must be timezone-aware")
    instant_utc = instant_utc.astimezone(UTC)
    start, end = bst_utc_bounds(instant_utc.year)
    offset = dt.timedelta(hours=1) if start <= instant_utc < end else dt.timedelta(0)
    return (instant_utc + offset).date()


def london_today() -> dt.date:
    return london_date_at(dt.datetime.now(UTC))


def london_midnight_utc(day: dt.date) -> dt.datetime:
    """Return the UTC instant at which a GB civil date starts.

    On the March transition day midnight is still GMT. On the October
    transition day midnight is still BST. This makes consecutive dates 23, 24
    or 25 hours apart exactly where Elexon settlement days require it.
    """
    start_day = last_sunday(day.year, 3)
    end_day = last_sunday(day.year, 10)
    bst_at_midnight = start_day < day <= end_day
    local_as_utc = dt.datetime.combine(day, dt.time(0), tzinfo=UTC)
    return local_as_utc - (dt.timedelta(hours=1) if bst_at_midnight else dt.timedelta(0))
