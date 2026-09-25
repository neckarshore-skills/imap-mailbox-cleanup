"""Ordering key of `manage search` without a server: naive, aware and missing dates."""

import datetime
from types import SimpleNamespace

from mailbox_cleanup.manage.search import _newest_first, _sent_at

UTC = datetime.UTC
PLUS2 = datetime.timezone(datetime.timedelta(hours=2))


def _msg(uid, date_str, date):
    return SimpleNamespace(uid=uid, date_str=date_str, date=date)


def test_mixed_naive_aware_and_missing_dates_sort_without_error():
    msgs = [
        _msg(
            "9", "Mon, 21 Sep 2026 09:00:00 +0200", datetime.datetime(2026, 9, 21, 9, tzinfo=PLUS2)
        ),
        _msg("10", "Tue, 22 Sep 2026 10:00:00", datetime.datetime(2026, 9, 22, 10)),  # naive
        _msg("11", "", datetime.datetime(1900, 1, 1)),  # no Date header
        _msg("12", "garbage", datetime.datetime(1900, 1, 1)),  # unparseable
    ]
    order = [m.uid for m in _newest_first(msgs)]
    assert order[:2] == ["10", "9"]
    assert set(order[2:]) == {"11", "12"}  # undated mail last


def test_equal_dates_break_ties_by_numeric_uid():
    d = datetime.datetime(2026, 9, 21, 9, tzinfo=UTC)
    msgs = [_msg("9", "x", d), _msg("10", "x", d), _msg("2", "x", d)]
    assert [m.uid for m in _newest_first(msgs)] == ["10", "9", "2"]


def test_missing_date_is_none_not_1900():
    assert _sent_at(_msg("1", "", datetime.datetime(1900, 1, 1))) is None
