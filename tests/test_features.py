import pytest

from evemarket.analytics.features import FeatureRow, HistoryBar, compute_features


def test_compute_features_hand_worked_values() -> None:
    rows = compute_features(_bars(), short_window=2, long_window=3)

    row = rows[2]

    assert row.date == "2026-01-07"
    assert row.simple_return == pytest.approx(0.2)
    assert row.realized_vol == pytest.approx(0.07071067811865475)
    assert row.momentum == pytest.approx(0.32)
    assert row.price_zscore == pytest.approx((132.0 - 114.0) / 16.3707055437449)
    assert row.volume_ratio == pytest.approx(1.2)
    assert row.hl_range == pytest.approx(26.0 / 132.0)


def test_compute_features_has_no_future_leakage() -> None:
    bars = _bars()
    rows = compute_features(bars, short_window=2, long_window=3)

    for index in range(len(bars)):
        prefix_rows = compute_features(
            bars[: index + 1],
            short_window=2,
            long_window=3,
        )
        assert rows[index] == prefix_rows[-1]


def test_compute_features_warmup_nones_and_always_defined_fields() -> None:
    rows = compute_features(_bars(), short_window=2, long_window=3)

    assert rows[0] == FeatureRow(
        date="2026-01-05",
        simple_return=None,
        realized_vol=None,
        momentum=None,
        price_zscore=None,
        volume_ratio=None,
        hl_range=0.2,
        day_of_week=0,
        day_of_month=5,
    )
    assert rows[1].simple_return == pytest.approx(0.1)
    assert rows[1].realized_vol is None
    assert rows[1].momentum is None
    assert rows[1].price_zscore is None
    assert rows[1].volume_ratio == pytest.approx(200.0 / 150.0)
    assert rows[1].hl_range == pytest.approx(22.0 / 110.0)


def test_compute_features_calendar_fields() -> None:
    rows = compute_features(_bars(), short_window=2, long_window=3)

    assert rows[0].day_of_week == 0
    assert rows[0].day_of_month == 5


def test_compute_features_degenerate_guards() -> None:
    flat_rows = compute_features(
        [
            HistoryBar("2026-01-01", 100.0, 105.0, 95.0, 10, 100),
            HistoryBar("2026-01-02", 100.0, 105.0, 95.0, 10, 100),
            HistoryBar("2026-01-03", 100.0, 105.0, 95.0, 10, 100),
        ],
        short_window=2,
        long_window=3,
    )
    assert flat_rows[2].price_zscore is None

    zero_volume_rows = compute_features(
        [
            HistoryBar("2026-01-01", 100.0, 105.0, 95.0, 10, 0),
            HistoryBar("2026-01-02", 110.0, 115.0, 105.0, 10, 0),
        ],
        short_window=2,
        long_window=2,
    )
    assert zero_volume_rows[1].volume_ratio is None

    zero_average_rows = compute_features(
        [
            HistoryBar("2026-01-01", 100.0, 105.0, 95.0, 10, 100),
            HistoryBar("2026-01-02", 0.0, 1.0, 0.0, 10, 100),
            HistoryBar("2026-01-03", 120.0, 125.0, 115.0, 10, 100),
        ],
        short_window=2,
        long_window=2,
    )
    assert zero_average_rows[1].simple_return is None
    assert zero_average_rows[1].momentum is None
    assert zero_average_rows[1].hl_range is None
    assert zero_average_rows[2].simple_return is None


def test_compute_features_empty_input_returns_empty_list() -> None:
    assert compute_features([]) == []


@pytest.mark.parametrize(
    ("short_window", "long_window", "match"),
    [
        (0, 7, "short_window must be at least 1"),
        (7, 0, "long_window must be at least 1"),
    ],
)
def test_compute_features_rejects_invalid_windows(
    short_window: int,
    long_window: int,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        compute_features(_bars(), short_window=short_window, long_window=long_window)


def _bars() -> list[HistoryBar]:
    return [
        HistoryBar("2026-01-05", 100.0, 110.0, 90.0, 10, 100),
        HistoryBar("2026-01-06", 110.0, 121.0, 99.0, 11, 200),
        HistoryBar("2026-01-07", 132.0, 145.0, 119.0, 12, 300),
        HistoryBar("2026-01-08", 165.0, 180.0, 150.0, 13, 400),
    ]
