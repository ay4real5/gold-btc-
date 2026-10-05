from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Callable

import pandas as pd

from .strategy import Signal, breakout_signal, scalp_signal


@dataclass(frozen=True)
class BacktestResult:
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    expectancy_r: float
    profit_factor: float | None
    max_drawdown_r: float
    max_consecutive_losses: int


def run_backtest(
    candles: pd.DataFrame,
    strategy: Callable[[pd.DataFrame], Signal | None] = breakout_signal,
    warmup: int = 60,
    default_spread: float = 0.3,
) -> BacktestResult:
    results: list[float] = []
    active: Signal | None = None
    entry_cost_r = 0.0
    for index in range(warmup, len(candles)):
        candle = candles.iloc[index]
        if active:
            stop_hit = candle["low"] <= active.stop if active.side == "buy" else candle["high"] >= active.stop
            target_hit = candle["high"] >= active.take_profit if active.side == "buy" else candle["low"] <= active.take_profit
            if stop_hit or target_hit:
                reward = abs(active.take_profit - active.entry) / abs(active.entry - active.stop)
                results.append((-1.0 if stop_hit else reward) - entry_cost_r)
                active = None
        if active is None:
            active = strategy(candles.iloc[:index + 1])
            if active:
                spread = float(candle.get("spread", default_spread))
                entry_cost_r = spread / abs(active.entry - active.stop)

    return summarize(results)


def summarize(results: list[float]) -> BacktestResult:
    wins = sum(result > 0 for result in results)
    losses = sum(result <= 0 for result in results)
    net_r = sum(results)
    gross_profit = sum(result for result in results if result > 0)
    gross_loss = abs(sum(result for result in results if result <= 0))
    equity = peak = max_drawdown = 0.0
    consecutive = max_consecutive = 0
    for result in results:
        equity += result
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        consecutive = consecutive + 1 if result <= 0 else 0
        max_consecutive = max(max_consecutive, consecutive)
    trades = len(results)
    return BacktestResult(
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=round(wins / trades * 100, 2) if trades else 0.0,
        net_r=round(net_r, 3),
        expectancy_r=round(net_r / trades, 3) if trades else 0.0,
        profit_factor=round(gross_profit / gross_loss, 3) if gross_loss else None,
        max_drawdown_r=round(max_drawdown, 3),
        max_consecutive_losses=max_consecutive,
    )


def run_scalp_backtest(candles: pd.DataFrame, slippage: float = 0.05,
                       strategy: Callable = scalp_signal, warmup: int = 60,
                       risk_fraction: float = 0.02, daily_loss_fraction: float = 0.03,
                       bar_minutes: int = 5, name: str = "scalp") -> dict:
    if not isfinite(slippage) or slippage < 0:
        raise ValueError("Slippage must be finite and nonnegative")
    if not 0 < risk_fraction <= 0.02 or not 0 < daily_loss_fraction <= 0.10:
        raise ValueError("Invalid simulated risk limits")
    required = [f"{side}_{field}" for side in ("bid", "ask") for field in ("open", "high", "low", "close")]
    if len(candles) <= warmup + 1 or not {"time", *required}.issubset(candles.columns):
        raise ValueError("Insufficient bid/ask history")
    frame = candles.reset_index(drop=True)
    times = pd.to_datetime(frame["time"], utc=True)
    if not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Candles must be ordered and unique")
    if not all(isfinite(float(v)) and float(v) > 0 for v in frame[required].to_numpy().ravel()):
        raise ValueError("Invalid bid/ask data")
    bar = timedelta(minutes=bar_minutes)
    if (times.diff().dropna().dt.total_seconds() < bar.total_seconds()).any():
        raise ValueError(f"Expected M{bar_minutes} candles")
    times = [stamp.to_pydatetime() for stamp in times]
    results, exits = [], []
    active = None
    cooldown_until = times[0]
    equity = day_opening = 100.0
    current_day = None
    daily_halted = False
    rejected = 0

    def finish(exit_price, exit_time, reason):
        nonlocal active, equity, cooldown_until, daily_halted
        result = active["direction"] * (exit_price - active["entry"]) / active["risk"]
        equity += active["budget"] * result
        results.append(result)
        exits.append({"time": exit_time.isoformat(), "r": result, "reason": reason})
        cooldown_until = exit_time + timedelta(minutes=5)
        daily_halted |= equity - day_opening <= -day_opening * daily_loss_fraction
        active = None

    for index in range(warmup, len(frame)):
        candle = frame.iloc[index]
        now = times[index]
        if current_day != now.date():
            current_day, day_opening, daily_halted = now.date(), equity, False
        if active:
            side = "bid" if active["direction"] == 1 else "ask"
            opening = float(candle[f"{side}_open"])
            if now >= active["deadline"]:
                finish(opening - active["direction"] * slippage, now, "time_exit")
        if active is None and now >= cooldown_until and not daily_halted:
            budget = equity * risk_fraction
            remaining = day_opening * daily_loss_fraction + min(equity - day_opening, 0)
            if budget <= remaining and times[index] - times[index - 1] == bar:
                signal = strategy(frame.iloc[max(0, index - 250):index])
                if signal:
                    direction = 1 if signal.side == "buy" else -1
                    stop, target = round(signal.stop, 3), round(signal.take_profit, 3)
                    distance = abs(signal.entry - stop)
                    ask, bid = float(candle["ask_open"]), float(candle["bid_open"])
                    quote = ask if direction == 1 else bid
                    entry = quote + direction * slippage
                    valid = stop < entry < target if direction == 1 else target < entry < stop
                    if (distance > 0 and 0 <= ask - bid <= 0.10 * distance
                            and abs(quote - signal.entry) <= 0.25 * distance
                            and slippage <= 0.05 * distance and valid):
                        active = {"entry": entry, "risk": abs(entry - stop), "stop": stop, "target": target,
                                  "direction": direction, "deadline": now + timedelta(minutes=15), "budget": budget}
                    else:
                        rejected += 1
        if active:
            direction = active["direction"]
            side = "bid" if direction == 1 else "ask"
            low, high = float(candle[f"{side}_low"]), float(candle[f"{side}_high"])
            opening = float(candle[f"{side}_open"])
            stop_hit = low <= active["stop"] if direction == 1 else high >= active["stop"]
            target_hit = high >= active["target"] if direction == 1 else low <= active["target"]
            if stop_hit:
                exit_price = min(opening, active["stop"]) if direction == 1 else max(opening, active["stop"])
                finish(exit_price - direction * slippage, now + bar, "stop")
            elif target_hit:
                finish(active["target"], now + bar, "target")
    if active:
        side = "bid" if active["direction"] == 1 else "ask"
        finish(float(frame.iloc[-1][f"{side}_close"]) - active["direction"] * slippage,
               times[-1] + bar, "end_of_sample")
    months = {}
    for exit in exits:
        month = exit["time"][:7]
        months.setdefault(month, []).append(exit["r"])
    return {
        "strategy": name, "granularity": f"M{bar_minutes}", "candles": len(frame),
        "start": times[0].isoformat(), "end": times[-1].isoformat(),
        "model": "next-open bid/ask fills; adverse slippage; stop-first intrabar ties; gap losses; 15m time exit; 5m cooldown; daily risk budget",
        "limitations": "OHLC approximation, no intrabar sequence, commission, financing, margin or GBP conversion model; not an execution guarantee",
        "slippage_usd_per_unit": slippage, "rejected_signals": rejected,
        "results": asdict(summarize(results)),
        "monthly": {month: asdict(summarize(values)) for month, values in months.items()},
        "exit_reasons": {reason: sum(item["reason"] == reason for item in exits)
                         for reason in ("stop", "target", "time_exit", "end_of_sample")},
    }
