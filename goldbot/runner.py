from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import tempfile
import time

import pandas as pd

from .config import Config
from .journal import TradeJournal
from .oanda import OandaClient
from .risk import daily_loss_reached, position_units
from .strategy import STRATEGIES, TIMED_STRATEGIES


# In ladder mode the broker take-profit is a distant ceiling; the bot ratchets the stop instead.
LADDER_CEILING_STEPS = 10
# The first ladder stop sits slightly past entry so spread and slippage do not turn break-even into a loss.
BREAK_EVEN_BUFFER_R = Decimal("0.05")

def number(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite trading value")
    return result


class PracticeRunner:
    def __init__(self, config: Config, client: OandaClient, execute: bool = False, clock=None):
        config.validate()
        self.config, self.client, self.execute = config, client, execute
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.state_path = Path(config.state_path)
        journal_path = Path(config.journal_path)
        if not execute:
            self.state_path = self.state_path.with_name(self.state_path.stem + "-dry.json")
            journal_path = journal_path.with_name(journal_path.stem + "-dry.csv")
        self.journal = TradeJournal(str(journal_path))
        self.state = self._load_state()
        self.account_key = sha256(config.account_id.encode()).hexdigest()[:16]
        if self.state.get("account_key", self.account_key) != self.account_key:
            raise ValueError("State belongs to a different account")
        self.state["account_key"] = self.account_key
        instruments = {item["name"]: item for item in client.instruments()}
        if config.instrument not in instruments:
            raise RuntimeError(f"{config.instrument} is not tradable on this account")
        self.instrument = instruments[config.instrument]

    @contextmanager
    def execution_lock(self):
        suffix = "execute" if self.execute else "dry"
        path = Path(tempfile.gettempdir()) / f"goldbot-{self.account_key}-{self.config.instrument}-{self.config.strategy_name}-{suffix}.lock"
        with path.open("a+b") as handle:
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("Another runner already holds this account lock") from error
            try:
                self.state = self._load_state()
                if self.state.get("account_key", self.account_key) != self.account_key:
                    raise ValueError("State belongs to a different account")
                self.state["account_key"] = self.account_key
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Invalid runner state")
        return state

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.state_path)

    def _owned(self, trade) -> bool:
        return (trade["instrument"] == self.config.instrument
                and trade.get("clientExtensions", {}).get("tag") == "goldbot-" + self.config.strategy_name)

    def _record(self, trade, closed: bool) -> None:
        if trade["id"] in self.journal.trade_ids(closed=closed):
            return
        units = number(trade["initialUnits"])
        pnl = (number(trade["realizedPL"]) + number(trade.get("financing", "0"))
               - number(trade.get("commission", "0")) - number(trade.get("guaranteedExecutionFees", "0"))) if closed else ""
        self.journal.append({
            "trade_id": trade["id"], "time": trade["closeTime"] if closed else trade["openTime"],
            "instrument": trade["instrument"], "side": "buy" if units > 0 else "sell", "units": abs(units),
            "entry": trade["price"], "sl": (trade.get("stopLossOrder") or {}).get("price", ""),
            "tp": (trade.get("takeProfitOrder") or {}).get("price", ""),
            "exit": trade.get("averageClosePrice", "") if closed else "", "pnl": pnl,
            "reason": self.state.get("exit_reasons", {}).get(trade["id"],
                       "OANDA closed trade reconciliation" if closed else "Protected demo entry"),
        })

    def sync_closed_trades(self) -> int:
        known = self.journal.trade_ids()
        added = 0
        for trade in self.client.closed_trades():
            if self._owned(trade):
                closed_at = pd.Timestamp(trade["closeTime"]).isoformat()
                if closed_at > self.state.get("last_exit", ""):
                    self.state["last_exit"] = closed_at
                if trade.get("clientExtensions", {}).get("id") == self.state.get("pending_order"):
                    self.state.pop("pending_order", None)
            if trade["id"] not in known and self._owned(trade):
                self._record(trade, closed=True)
                known.add(trade["id"])
                added += 1
        self._save_state()
        return added

    def _close(self, trade, reason: str) -> dict:
        if not self.execute:
            return {"action": "dry_run_" + reason, "trade_id": trade["id"]}
        self.state.setdefault("exit_reasons", {})[trade["id"]] = reason
        self._save_state()
        response = self.client.close_trade(trade["id"])
        if not response.get("orderFillTransaction"):
            return {"action": "close_not_filled", "trade_id": trade["id"]}
        refreshed = self.client.trade(trade["id"])
        if refreshed["state"] != "CLOSED":
            raise RuntimeError("Full close not confirmed; new entries blocked by open trade")
        self._record(refreshed, closed=True)
        self.state["last_exit"] = pd.Timestamp(refreshed["closeTime"]).isoformat()
        self._save_state()
        return {"action": reason, "trade_id": trade["id"]}

    @staticmethod
    def _protected(trade) -> bool:
        return all((trade.get(key) or {}).get("state") == "PENDING"
                   for key in ("stopLossOrder", "takeProfitOrder"))

    def cycle(self) -> dict[str, object]:
        now = self.clock()
        logging.info("heartbeat execute=%s strategy=%s", self.execute, self.config.strategy_name)
        account_trades = self.client.open_trades()
        open_trades = [trade for trade in account_trades if trade["instrument"] == self.config.instrument]
        # SL/TP orders attached to any open trade count as pending orders; only standalone orders should block entries.
        attached = sum(1 for trade in account_trades
                       for key in ("stopLossOrder", "takeProfitOrder", "trailingStopLossOrder") if trade.get(key))
        for trade in open_trades:
            if not self._owned(trade):
                continue
            self._record(trade, closed=False)
            if not self._protected(trade):
                self.state["halted"] = "missing_protection"
                self._save_state()
                return self._close(trade, "missing_protection")
            tag = trade["clientExtensions"]["tag"]
            age = (now - pd.Timestamp(trade["openTime"]).to_pydatetime()).total_seconds()
            if self.config.ladder:
                result = self._ladder(trade, now)
                if result:
                    return result
            step = self.state.get("ladder", {}).get(trade["id"], {}).get("step", 0)
            limit = self.config.runner_max_hold_seconds if step else self.config.max_hold_seconds
            if tag.removeprefix("goldbot-") in TIMED_STRATEGIES and age >= limit:
                return self._close(trade, "time_exit")
            if trade["clientExtensions"].get("id") == self.state.get("pending_order"):
                self.state.pop("pending_order", None)
                self._save_state()
        reconciled = self.sync_closed_trades()
        account = self.client.account_summary()
        balance = number(account["balance"])
        pnl = self.journal.pnl_for_day(now.date())
        if self.state.get("day") != now.date().isoformat():
            self.state.update(day=now.date().isoformat(), opening_balance=str(balance - pnl), daily_halted=False)
        opening = number(self.state["opening_balance"])
        if balance <= 0 or opening <= 0:
            raise ValueError("Account balance must be positive")
        cap = number(self.config.daily_loss_fraction)
        if daily_loss_reached(pnl + number(account["unrealizedPL"]), opening, cap):
            self.state["daily_halted"] = True
        self._save_state()
        status = {"time": now.isoformat(), "execute": self.execute, "strategy": self.config.strategy_name,
                  "daily_pnl": str(pnl), "reconciled": reconciled}
        if self.state.get("daily_halted"):
            owned = next((trade for trade in open_trades if self._owned(trade)), None)
            if owned:
                return {**status, **self._close(owned, "daily_loss_exit")}
            return {**status, "action": "daily_loss_cap"}
        if self.state.get("halted"):
            return {**status, "action": "safety_halt", "reason": self.state["halted"]}
        if self.state.get("pending_order"):
            return {**status, "action": "unresolved_order"}
        if open_trades:
            return {**status, "action": "open_trade_exists"}
        if int(account["pendingOrderCount"]) > attached:
            return {**status, "action": "pending_orders"}
        if self.state.get("last_exit"):
            since_exit = (now - pd.Timestamp(self.state["last_exit"]).to_pydatetime()).total_seconds()
            if since_exit < self.config.cooldown_seconds:
                return {**status, "action": "cooldown"}
        candles = self.client.candles(self.config.instrument, self.config.granularity, 250)
        if candles.empty:
            return {**status, "action": "no_candles"}
        candle_time = str(candles.iloc[-1]["time"])
        age = (now - pd.Timestamp(candle_time).to_pydatetime()).total_seconds()
        if age < self.config.candle_seconds or age > 2 * self.config.candle_seconds + 90:
            logging.warning("Stale or invalid completed-candle timestamp: age=%s", round(age))
            return {**status, "action": "stale_candles", "candle_age_seconds": round(age)}
        if age > self.config.candle_seconds + 90:
            return {**status, "action": "waiting_next_candle"}
        key = self.config.strategy_name + ":" + candle_time
        if self.state.get("last_signal_key") == key:
            return {**status, "action": "already_evaluated"}
        self.state["last_signal_key"] = key
        self._save_state()
        signal = STRATEGIES[self.config.strategy_name](candles, **self.config.strategy_kwargs)
        if signal is None:
            return {**status, "action": "no_signal"}
        return {**status, **self._enter(signal, candle_time, account, pnl, opening)}

    def _enter(self, signal, candle_time, account, pnl, opening) -> dict:
        price = self.client.pricing(self.config.instrument)
        if not price.get("tradeable", price.get("status") == "tradeable"):
            return {"action": "market_closed"}
        age = (self.clock() - pd.Timestamp(price["time"]).to_pydatetime()).total_seconds()
        if not 0 <= age <= 30:
            return {"action": "stale_price"}
        asks, bids = price.get("asks", []), price.get("bids", [])
        if not asks or not bids:
            return {"action": "no_liquidity"}
        ask, bid = number(asks[0]["price"]), number(bids[0]["price"])
        precision = int(self.instrument["displayPrecision"])
        stop = number(f"{signal.stop:.{precision}f}")
        take_profit = signal.take_profit
        if self.config.ladder:
            reach = abs(signal.entry - signal.stop) * self.config.ladder_step_r * LADDER_CEILING_STEPS
            take_profit = signal.entry + reach if signal.side == "buy" else signal.entry - reach
        target = number(f"{take_profit:.{precision}f}")
        entry = ask if signal.side == "buy" else bid
        distance = abs(number(signal.entry) - stop)
        if distance <= 0 or bid <= 0 or ask < bid:
            raise ValueError("Invalid risk or quote")
        if ask - bid > distance * number(self.config.max_spread_r):
            return {"action": "spread_too_wide"}
        if abs(entry - number(signal.entry)) > distance * Decimal("0.25"):
            return {"action": "price_moved"}
        bound = entry + distance * number(self.config.slippage_r) * (1 if signal.side == "buy" else -1)
        bound = number(f"{bound:.{precision}f}")
        if not (stop < entry <= bound < target if signal.side == "buy" else target < bound <= entry < stop):
            return {"action": "invalid_protection_prices"}
        balance = number(account["balance"])
        budget = balance * number(self.config.risk_fraction)
        if budget > opening * number(self.config.daily_loss_fraction) + min(pnl, Decimal("0")):
            return {"action": "daily_risk_budget"}
        conversion = number(price["loss_conversion"])
        units = position_units(balance, number(self.config.risk_fraction), bound, stop,
                               conversion, int(self.instrument["tradeUnitsPrecision"]))
        maximum = number(self.instrument["maximumOrderUnits"])
        if maximum > 0:
            units = min(units, maximum).quantize(Decimal(1).scaleb(-int(self.instrument["tradeUnitsPrecision"])), rounding=ROUND_DOWN)
        if units < number(self.instrument["minimumTradeSize"]):
            return {"action": "below_minimum_size"}
        margin_rate = max(number(self.instrument["marginRate"]), number(account.get("marginRate", "0")))
        position_conversion = number(price["position_conversion"])
        if margin_rate <= 0 or position_conversion <= 0:
            raise ValueError("Invalid margin conversion")
        if units * max(ask, bound) * position_conversion * margin_rate > number(account["marginAvailable"]) * Decimal("0.8"):
            return {"action": "insufficient_margin"}
        levels = asks if signal.side == "buy" else bids
        liquidity = sum((number(level["liquidity"]) for level in levels
                         if (number(level["price"]) <= bound if signal.side == "buy" else number(level["price"]) >= bound)), Decimal("0"))
        if units > liquidity:
            return {"action": "insufficient_liquidity"}
        signed = units if signal.side == "buy" else -units
        if not self.execute:
            return {"action": "dry_run_signal", "side": signal.side, "units": str(signed),
                    "sl": str(stop), "tp": str(target), "planned_risk": str(units * abs(bound - stop) * conversion)}
        if any(trade["instrument"] == self.config.instrument for trade in self.client.open_trades()):
            return {"action": "open_trade_exists"}
        client_id = "goldbot-" + sha256((self.account_key + self.config.instrument + self.config.strategy_name + candle_time).encode()).hexdigest()[:24]
        self.state["pending_order"] = client_id
        self._save_state()
        response = self.client.market_order(self.config.instrument, str(signed), f"{stop:.{precision}f}",
                                             f"{target:.{precision}f}", client_id, f"{bound:.{precision}f}",
                                             "goldbot-" + self.config.strategy_name)
        if "orderCancelTransaction" in response or "orderRejectTransaction" in response:
            self.state.pop("pending_order", None)
            self._save_state()
            return {"action": "order_cancelled"}
        trade_id = response.get("orderFillTransaction", {}).get("tradeOpened", {}).get("tradeID")
        if not trade_id:
            return {"action": "unresolved_order"}
        trade = self.client.trade(trade_id)
        if trade["state"] == "OPEN":
            self._record(trade, closed=False)
            if not self._protected(trade):
                self.state["halted"] = "missing_protection"
                self._save_state()
                return self._close(trade, "missing_protection")
        else:
            self._record(trade, closed=True)
        self.state.pop("pending_order", None)
        self._save_state()
        return {"action": "order_filled", "trade_id": trade_id, "units": str(signed)}

    def _ladder(self, trade, now) -> dict | None:
        """Step the stop up as price reaches each multiple of ladder_step_r: break-even first, then the previous step."""
        ladders = self.state.setdefault("ladder", {})
        info = ladders.get(trade["id"])
        if info is None:
            entry = number(trade["price"])
            info = {"entry": str(entry), "risk": str(abs(entry - number(trade["stopLossOrder"]["price"]))), "step": 0}
            ladders[trade["id"]] = info
            self._save_state()
        entry, risk = number(info["entry"]), number(info["risk"])
        direction = 1 if number(trade["initialUnits"]) > 0 else -1
        side = "bid" if direction == 1 else "ask"
        current = number(self.client.pricing(self.config.instrument)[side + "s"][0]["price"])
        best = current
        opened = pd.Timestamp(trade["openTime"]).floor("min")
        minutes = int((now - opened.to_pydatetime()).total_seconds() // 60) + 2
        candles = self.client.candles(self.config.instrument, "M1", min(max(minutes, 2), 500))
        if not candles.empty:
            recent = candles[pd.to_datetime(candles["time"], utc=True) >= opened]
            column = f"{side}_high" if direction == 1 else f"{side}_low"
            if column not in recent:
                column = "high" if direction == 1 else "low"
            if not recent.empty:
                extreme = number(recent[column].max() if direction == 1 else recent[column].min())
                best = max(best, extreme) if direction == 1 else min(best, extreme)
        step_size = risk * number(self.config.ladder_step_r)
        if step_size <= 0:
            return None
        reached = int((best - entry) * direction / step_size)
        if reached <= info["step"]:
            return None
        offset = risk * BREAK_EVEN_BUFFER_R if reached == 1 else step_size * (reached - 1)
        precision = int(self.instrument["displayPrecision"])
        stop = number(f"{entry + direction * offset:.{precision}f}")
        if (current - stop) * direction <= 0:
            return self._close(trade, "ladder_stop")
        if not self.execute:
            return {"action": "dry_run_ladder_step", "trade_id": trade["id"], "step": reached, "sl": str(stop)}
        self.client.set_trade_orders(trade["id"], f"{stop:.{precision}f}", trade["takeProfitOrder"]["price"])
        info["step"] = reached
        self._save_state()
        return {"action": "ladder_step", "trade_id": trade["id"], "step": reached, "sl": str(stop)}

    def run(self) -> None:
        logging.info("Starting practice runner execute=%s strategy=%s", self.execute, self.config.strategy_name)
        while True:
            try:
                logging.info("cycle %s", json.dumps(self.cycle()))
            except Exception as error:
                logging.error("Runner cycle failed (%s: %s); no new order retry", type(error).__name__, error)
            time.sleep(self.config.poll_seconds)
