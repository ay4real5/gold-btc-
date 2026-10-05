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


def scalp_signal(candles: pd.DataFrame) -> Signal | None:
    if len(candles) < 40:
        return None
    frame = _indicators(candles.tail(250))
    fast = frame["close"].ewm(span=5, adjust=False).mean()
    slow = frame["close"].ewm(span=12, adjust=False).mean()
    latest, previous = frame.iloc[-1], frame.iloc[-2]
    entry, atr = float(latest["close"]), float(latest["atr"])
    if not pd.notna(atr) or atr <= 0:
        return None
    up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
    if up:
        return Signal("buy", entry, entry - atr, entry + 1.2 * atr, "M5 EMA5/12 cross")
    if down:
        return Signal("sell", entry, entry + atr, entry - 1.2 * atr, "M5 EMA5/12 cross")
    return None


STRATEGIES = {
    "breakout": breakout_signal,
    "pullback": pullback_signal,
    "session_breakout": session_breakout_signal,
    "scalp": scalp_signal,
}
