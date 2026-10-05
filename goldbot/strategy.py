from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Signal:
    side: str
    entry: float
    stop: float
    take_profit: float
    reason: str


def _indicators(candles: pd.DataFrame, ema_period: int = 50, atr_period: int = 14) -> pd.DataFrame:
    frame = candles.copy()
    frame["ema"] = frame["close"].ewm(span=ema_period, adjust=False).mean()
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [(frame["high"] - frame["low"]), (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.rolling(atr_period).mean()
    return frame


def _signal(side: str, entry: float, atr: float, reason: str) -> Signal:
    stop = entry - 1.5 * atr if side == "buy" else entry + 1.5 * atr
    risk = abs(entry - stop)
    target = entry + 2 * risk if side == "buy" else entry - 2 * risk
    return Signal(side, entry, stop, target, reason)


def breakout_signal(candles: pd.DataFrame, ema_period: int = 50, lookback: int = 20, atr_period: int = 14) -> Signal | None:
    if len(candles) < max(ema_period, lookback + 1, atr_period + 1):
        return None
    frame = _indicators(candles, ema_period, atr_period)
    latest = frame.iloc[-1]
    prior = frame.iloc[-lookback - 1:-1]
    atr = float(latest["atr"])
    entry = float(latest["close"])
    if pd.isna(atr) or atr <= 0:
        return None
    if entry > float(latest["ema"]) and entry > float(prior["high"].max()):
        return _signal("buy", entry, atr, "EMA trend + 20-candle breakout")
    if entry < float(latest["ema"]) and entry < float(prior["low"].min()):
        return _signal("sell", entry, atr, "EMA trend + 20-candle breakout")
    return None


def pullback_signal(candles: pd.DataFrame, ema_period: int = 50, atr_period: int = 14) -> Signal | None:
    if len(candles) < max(ema_period, atr_period + 1) + 1:
        return None
    frame = _indicators(candles, ema_period, atr_period)
    latest, previous = frame.iloc[-1], frame.iloc[-2]
    atr = float(latest["atr"])
    entry, ema = float(latest["close"]), float(latest["ema"])
    if pd.isna(atr) or atr <= 0:
        return None
    if entry > ema and float(previous["low"]) <= float(previous["ema"]) and entry > float(previous["high"]):
        return _signal("buy", entry, atr, "EMA trend pullback confirmation")
    if entry < ema and float(previous["high"]) >= float(previous["ema"]) and entry < float(previous["low"]):
        return _signal("sell", entry, atr, "EMA trend pullback confirmation")
    return None


def session_breakout_signal(candles: pd.DataFrame, atr_period: int = 14) -> Signal | None:
    if len(candles) < atr_period + 2 or "time" not in candles:
        return None
    frame = _indicators(candles, atr_period=atr_period)
    times = pd.to_datetime(frame["time"], utc=True)
    latest_time = times.iloc[-1]
    if not 7 <= latest_time.hour < 12:
        return None
    session = frame[(times.dt.date == latest_time.date()) & (times.dt.hour < 7)]
    if len(session) < 4:
        return None
    latest = frame.iloc[-1]
    atr, entry = float(latest["atr"]), float(latest["close"])
    if pd.isna(atr) or atr <= 0:
        return None
    if entry > float(session["high"].max()):
        return _signal("buy", entry, atr, "London breakout above Asian range")
    if entry < float(session["low"].min()):
        return _signal("sell", entry, atr, "London breakout below Asian range")
    return None


def _ema_cross(candles: pd.DataFrame, fast_span: int, slow_span: int, label: str) -> Signal | None:
    if len(candles) < 40:
        return None
    frame = _indicators(candles.tail(250))
    fast = frame["close"].ewm(span=fast_span, adjust=False).mean()
    slow = frame["close"].ewm(span=slow_span, adjust=False).mean()
    entry, atr = float(frame["close"].iloc[-1]), float(frame["atr"].iloc[-1])
    if not pd.notna(atr) or atr <= 0:
        return None
    up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
    if up:
        return Signal("buy", entry, entry - atr, entry + 1.2 * atr, label)
    if down:
        return Signal("sell", entry, entry + atr, entry - 1.2 * atr, label)
    return None


def scalp_signal(candles: pd.DataFrame) -> Signal | None:
    return _ema_cross(candles, 5, 12, "M5 EMA5/12 cross")


def scalp38_signal(candles: pd.DataFrame) -> Signal | None:
    return _ema_cross(candles, 3, 8, "M5 EMA3/8 cross")


def m1_fast_signal(candles: pd.DataFrame) -> Signal | None:
    """M1 trend continuation: close beyond the prior candle on the EMA20 side; 2 ATR stop, 1.2R target."""
    if len(candles) < 40:
        return None
    frame = _indicators(candles.tail(250))
    trend = frame["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    latest, previous = frame.iloc[-1], frame.iloc[-2]
    entry, atr = float(latest["close"]), float(latest["atr"])
    if not pd.notna(atr) or atr <= 0:
        return None
    risk = 2 * atr
    if entry > trend and entry > float(previous["high"]):
        return Signal("buy", entry, entry - risk, entry + 1.2 * risk, "M1 EMA20 continuation")
    if entry < trend and entry < float(previous["low"]):
        return Signal("sell", entry, entry + risk, entry - 1.2 * risk, "M1 EMA20 continuation")
    return None


def session_long_signal(candles: pd.DataFrame, entry_hour: int = 13, stop_atr: float = 6.0,
                        skip_friday: bool = False) -> Signal | None:
    """Long-only session hold on H1 candles.

    entry_hour is New York wall-clock time, so the session stays put across daylight-saving changes.
    Fires when the last completed candle is the hour before entry_hour, so the fill lands at entry_hour. The runner's holding limit closes it at the session end. Target is a placeholder:
    session runs use the ladder, which replaces it with a distant ceiling.
    """
    if len(candles) < 30 or "time" not in candles:
        return None
    frame = _indicators(candles.tail(100))
    latest = frame.iloc[-1]
    stamp = pd.Timestamp(latest["time"]).tz_convert("America/New_York")
    if stamp.hour != (entry_hour - 1) % 24:
        return None
    if skip_friday and (stamp + pd.Timedelta(hours=1)).weekday() == 4:
        return None
    entry, atr = float(latest["close"]), float(latest["atr"])
    if not pd.notna(atr) or atr <= 0:
        return None
    risk = stop_atr * atr
    return Signal("buy", entry, entry - risk, entry + 1.2 * risk, f"session long from {entry_hour:02d}:00 New York")


STRATEGIES = {
    "breakout": breakout_signal,
    "pullback": pullback_signal,
    "session_breakout": session_breakout_signal,
    "scalp": scalp_signal,
    "scalp38": scalp38_signal,
    "m1_fast": m1_fast_signal,
    "session_long": session_long_signal,
}

# Strategies that use the short-hold model: 15-minute time exit, cooldown, bid/ask scalp check.
TIMED_STRATEGIES = {"scalp": "M5", "scalp38": "M5", "m1_fast": "M1", "session_long": "H1"}
