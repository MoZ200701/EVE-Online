"""Pure point-in-time feature primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import mean, stdev


@dataclass(frozen=True)
class HistoryBar:
    """One daily market-history bar."""

    date: str
    average: float
    highest: float
    lowest: float
    order_count: int
    volume: int


@dataclass(frozen=True)
class FeatureRow:
    """One point-in-time feature row."""

    date: str
    simple_return: float | None
    realized_vol: float | None
    momentum: float | None
    price_zscore: float | None
    volume_ratio: float | None
    hl_range: float | None
    day_of_week: int
    day_of_month: int


def compute_features(
    bars: Sequence[HistoryBar],
    *,
    short_window: int = 7,
    long_window: int = 14,
) -> list[FeatureRow]:
    """Return trailing features for chronological bars without sorting."""
    _require_windows(short_window, long_window)

    simple_returns = [_simple_return(bars, index) for index in range(len(bars))]
    rows: list[FeatureRow] = []
    for index, bar in enumerate(bars):
        parsed_date = date.fromisoformat(bar.date)
        rows.append(
            FeatureRow(
                date=bar.date,
                simple_return=simple_returns[index],
                realized_vol=_realized_vol(simple_returns, index, short_window),
                momentum=_momentum(bars, index, short_window),
                price_zscore=_price_zscore(bars, index, long_window),
                volume_ratio=_volume_ratio(bars, index, short_window),
                hl_range=_hl_range(bar),
                day_of_week=parsed_date.weekday(),
                day_of_month=parsed_date.day,
            )
        )

    return rows


def _require_windows(short_window: int, long_window: int) -> None:
    if short_window < 1:
        raise ValueError("short_window must be at least 1")
    if long_window < 1:
        raise ValueError("long_window must be at least 1")


def _simple_return(bars: Sequence[HistoryBar], index: int) -> float | None:
    if index == 0:
        return None

    current = bars[index].average
    previous = bars[index - 1].average
    if current <= 0:
        return None
    if previous <= 0:
        return None

    return current / previous - 1


def _realized_vol(
    simple_returns: Sequence[float | None],
    index: int,
    short_window: int,
) -> float | None:
    start = index - short_window + 1
    if start < 1:
        return None

    values = simple_returns[start : index + 1]
    if len(values) < 2 or any(value is None for value in values):
        return None

    return stdev(value for value in values if value is not None)


def _momentum(
    bars: Sequence[HistoryBar],
    index: int,
    short_window: int,
) -> float | None:
    previous_index = index - short_window
    if previous_index < 0:
        return None

    current = bars[index].average
    previous = bars[previous_index].average
    if current <= 0:
        return None
    if previous <= 0:
        return None

    return current / previous - 1


def _price_zscore(
    bars: Sequence[HistoryBar],
    index: int,
    long_window: int,
) -> float | None:
    start = index - long_window + 1
    if start < 0:
        return None

    values = [bar.average for bar in bars[start : index + 1]]
    sample_stdev = stdev(values) if len(values) > 1 else 0.0
    if sample_stdev == 0:
        return None

    return (bars[index].average - mean(values)) / sample_stdev


def _volume_ratio(
    bars: Sequence[HistoryBar],
    index: int,
    short_window: int,
) -> float | None:
    start = index - short_window + 1
    if start < 0:
        return None

    values = [bar.volume for bar in bars[start : index + 1]]
    average_volume = mean(values)
    if average_volume == 0:
        return None

    return bars[index].volume / average_volume


def _hl_range(bar: HistoryBar) -> float | None:
    """Return daily high-low range, not an order-book bid/ask spread."""
    if bar.average <= 0:
        return None

    return (bar.highest - bar.lowest) / bar.average
