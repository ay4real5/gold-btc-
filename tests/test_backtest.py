import pandas as pd

import pytest

from goldbot.backtest import run_backtest, run_scalp_backtest
from goldbot.strategy import Signal


def test_backtest_charges_spread_and_reports_metrics():
    candles = pd.DataFrame(
        [{"open": 100, "high": 100.5, "low": 99.5, "close": 100, "spread": 0.1} for _ in range(62)]
    )
    candles.loc[61, "high"] = 103

    def strategy(frame):
        return Signal("buy", 100, 99, 102, "test") if len(frame) == 61 else None

    result = run_backtest(candles, strategy)
    assert result.trades == 1
    assert result.net_r == 1.9
    assert result.win_rate == 100
    assert result.profit_factor is None


def test_backtest_resolves_same_bar_stop_and_target_as_loss():
    candles = pd.DataFrame(
        [{"open": 100, "high": 100.5, "low": 99.5, "close": 100, "spread": 0} for _ in range(62)]
    )
    candles.loc[61, ["high", "low"]] = [103, 98]

    def strategy(frame):
        return Signal("buy", 100, 99, 102, "test") if len(frame) == 61 else None

    result = run_backtest(candles, strategy)
    assert result.net_r == -1


def scalp_candles():
    data = {"time": pd.date_range("2026-09-30T10:00Z", periods=8, freq="5min")}
    for side in ("bid", "ask"):
        for field, value in (("open", 100.0), ("close", 100.0), ("high", 100.4), ("low", 99.6)):
            data[f"{side}_{field}"] = [value] * 8
    return pd.DataFrame(data)


def entry_once(frame):
    return Signal("buy", 100, 99, 101.2, "test") if len(frame) == 2 else None


def test_scalp_backtest_uses_actual_target_not_two_r():
    candles = scalp_candles()
    candles.loc[2, "bid_high"] = 101.3
    result = run_scalp_backtest(candles, slippage=0, strategy=entry_once, warmup=2)
    assert result["results"]["net_r"] == 1.2
    assert result["exit_reasons"]["target"] == 1


def test_scalp_backtest_gap_stop_can_exceed_one_r():
    candles = scalp_candles()
    candles.loc[3, ["bid_open", "bid_low"]] = [98, 97.5]
    result = run_scalp_backtest(candles, slippage=0, strategy=entry_once, warmup=2)
    assert result["results"]["net_r"] == -2


def test_scalp_backtest_time_exit_uses_boundary_open_not_future_high():
    candles = scalp_candles()
    candles.loc[5, "bid_open"] = 100.1
    candles.loc[5, "bid_high"] = 110
    result = run_scalp_backtest(candles, slippage=0, strategy=entry_once, warmup=2)
    assert result["results"]["net_r"] == 0.1
    assert result["exit_reasons"]["time_exit"] == 1


def test_scalp_backtest_marks_open_trade_at_end_and_charges_costs():
    candles = scalp_candles().iloc[:4].copy()
    candles["ask_open"] = 100.02
    result = run_scalp_backtest(candles, slippage=0.01, strategy=entry_once, warmup=2)
    assert result["results"]["net_r"] < 0
    assert result["exit_reasons"]["end_of_sample"] == 1


def test_scalp_backtest_stops_first_on_ambiguous_bar():
    candles = scalp_candles()
    candles.loc[2, ["bid_low", "bid_high"]] = [98.9, 101.3]
    result = run_scalp_backtest(candles, slippage=0, strategy=entry_once, warmup=2)
    assert result["results"]["net_r"] == -1


def test_scalp_backtest_rejects_missing_bid_ask_data():
    with pytest.raises(ValueError, match="bid/ask"):
        run_scalp_backtest(pd.DataFrame({"close": [100] * 100}))
