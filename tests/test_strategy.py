import pandas as pd

from goldbot.strategy import breakout_signal, scalp_signal


def test_long_breakout_has_stop_and_two_r_target():
    closes = [100 + index * 0.1 for index in range(60)] + [110]
    candles = pd.DataFrame(
        {"open": closes, "high": [value + 0.2 for value in closes], "low": [value - 0.2 for value in closes], "close": closes}
    )
    signal = breakout_signal(candles)
    assert signal is not None
    assert signal.side == "buy"
    assert signal.stop < signal.entry < signal.take_profit
    assert round((signal.take_profit - signal.entry) / (signal.entry - signal.stop), 8) == 2


def test_no_signal_without_enough_history():
    candles = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]})
    assert breakout_signal(candles) is None


def test_scalp_requires_fresh_cross_and_has_short_target():
    closes = [100] * 40 + [101]
    frame = pd.DataFrame({"open": closes, "close": closes,
                          "high": [v + 0.2 for v in closes], "low": [v - 0.2 for v in closes]})
    signal = scalp_signal(frame)
    assert signal is not None
    assert signal.side == "buy"
    risk = signal.entry - signal.stop
    assert round((signal.take_profit - signal.entry) / risk, 6) == 1.2
    following = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
    assert scalp_signal(following) is None
    mirrored = frame.copy()
    mirrored["close"] = 210 - frame["close"]
    mirrored["open"] = 210 - frame["open"]
    mirrored["high"] = 210 - frame["low"]
    mirrored["low"] = 210 - frame["high"]
    assert scalp_signal(mirrored).side == "sell"


def test_scalp_no_signal_for_flat_or_short_history():
    frame = pd.DataFrame({"open": [100] * 60, "close": [100] * 60,
                          "high": [100] * 60, "low": [100] * 60})
    assert scalp_signal(frame) is None
    assert scalp_signal(frame.iloc[:10]) is None
    trending = pd.DataFrame({"open": [100 + i * 0.1 for i in range(50)], "close": [100 + i * 0.1 for i in range(50)],
                              "high": [100 + i * 0.1 + 0.2 for i in range(50)], "low": [100 + i * 0.1 - 0.2 for i in range(50)]})
    assert scalp_signal(trending) is None


def _frame(closes):
    return pd.DataFrame({"open": closes, "close": closes,
                         "high": [v + 0.2 for v in closes], "low": [v - 0.2 for v in closes]})


def test_scalp38_crosses_on_fresh_move():
    from goldbot.strategy import scalp38_signal
    signal = scalp38_signal(_frame([100] * 40 + [101]))
    assert signal.side == "buy"
    assert round((signal.take_profit - signal.entry) / (signal.entry - signal.stop), 6) == 1.2


def test_m1_fast_needs_trend_side_and_prior_candle_break():
    from goldbot.strategy import m1_fast_signal
    rising = [100 + i * 0.05 for i in range(60)] + [104]
    signal = m1_fast_signal(_frame(rising))
    assert signal.side == "buy"
    assert round((signal.take_profit - signal.entry) / (signal.entry - signal.stop), 6) == 1.2
    falling = [200 - v for v in rising]
    assert m1_fast_signal(_frame(falling)).side == "sell"
    assert m1_fast_signal(_frame([100] * 60)) is None
