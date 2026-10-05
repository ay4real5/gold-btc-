from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest
import requests

from goldbot.config import Config
from goldbot.runner import PracticeRunner
from goldbot.strategy import Signal, STRATEGIES


class FakeClient:
    def __init__(self):
        self.orders = []
        self.closes = []
        self.balance = "100000"
        self.now = datetime(2026, 9, 30, 10, 5, tzinfo=timezone.utc)
        self.live = []
        self.closed = []
        self.pending = 0
        self.quote = {"tradeable": True, "time": self.now.isoformat(),
                      "closeoutAsk": "100", "closeoutBid": "99.95",
                      "loss_conversion": "1", "position_conversion": "1"}
        self.response = None

    def instruments(self):
        return [{"name": "XAU_USD", "tradeUnitsPrecision": 1, "displayPrecision": 3,
                 "minimumTradeSize": "0.1", "maximumOrderUnits": "100000", "marginRate": "0.05"}]

    def closed_trades(self):
        return self.closed

    def account_summary(self):
        return {"balance": self.balance, "marginAvailable": self.balance,
                "pendingOrderCount": self.pending, "openTradeCount": len(self.live),
                "unrealizedPL": "0"}

    def candles(self, *args):
        return pd.DataFrame([{"time": (self.now - timedelta(minutes=5)).isoformat(),
                              "open": 100, "high": 101, "low": 99, "close": 100}])

    def open_trades(self):
        return self.live

    def pricing(self, instrument):
        return {**self.quote,
                "asks": [{"price": self.quote["closeoutAsk"], "liquidity": 100000}],
                "bids": [{"price": self.quote["closeoutBid"], "liquidity": 100000}]}

    def market_order(self, *args):
        self.orders.append(args)
        if self.response is not None:
            return self.response
        trade_id = str(len(self.orders))
        self.live.append({"id": trade_id, "instrument": "XAU_USD", "state": "OPEN",
                          "openTime": self.now.isoformat(), "initialUnits": args[1], "price": "100",
                          "clientExtensions": {"id": args[4], "tag": args[6]},
                          "stopLossOrder": {"price": args[2], "state": "PENDING"},
                          "takeProfitOrder": {"price": args[3], "state": "PENDING"}})
        return {"orderFillTransaction": {"tradeOpened": {"tradeID": trade_id}}}

    def trade(self, trade_id):
        return next(t for t in self.live + self.closed if t["id"] == trade_id)

    def close_trade(self, trade_id):
        self.closes.append(trade_id)
        trade = self.trade(trade_id)
        self.live.remove(trade)
        self.closed.append({**trade, "state": "CLOSED", "closeTime": self.now.isoformat(),
                            "realizedPL": "0", "averageClosePrice": "100"})
        return {"orderFillTransaction": {"tradesClosed": [{"tradeID": trade_id}]}}


def make_config(tmp_path):
    return Config(token="token", account_id="account", strategy_name="scalp",
                  journal_path=str(tmp_path / "trades.csv"), state_path=str(tmp_path / "state.json"))


def make_runner(tmp_path, monkeypatch, execute=True):
    client = FakeClient()
    monkeypatch.setitem(STRATEGIES, "scalp", lambda candles: Signal("buy", 100, 99, 101.2, "test"))
    runner = PracticeRunner(make_config(tmp_path), client, execute=execute, clock=lambda: client.now)
    return runner, client


def test_execute_attaches_protection_and_fixed_size(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    assert runner.cycle()["action"] == "order_filled"
    order = client.orders[0]
    assert order[0] == "XAU_USD"
    assert order[2:4] == ("99.000", "101.200")
    assert Decimal(order[1]) * (Decimal(order[5]) - Decimal(order[2])) <= Decimal("2000")
    assert order[6] == "goldbot-scalp"
    assert runner.journal.trade_ids(closed=False) == {"1"}


def test_daily_loss_cap_survives_restart(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.balance = "97000"
    runner.journal.append({"trade_id": "1", "time": client.now.isoformat(), "pnl": "-3000"})
    assert runner.cycle()["action"] == "daily_loss_cap"
    restarted = PracticeRunner(runner.config, client, True, clock=lambda: client.now)
    assert restarted.cycle()["action"] == "daily_loss_cap"
    assert not client.orders


def test_closed_trade_reconciliation_is_idempotent_and_includes_costs(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.closed = [{"id": "7", "instrument": "XAU_USD", "initialUnits": "1",
                      "closeTime": client.now.isoformat(), "price": "100", "averageClosePrice": "102",
                      "realizedPL": "2", "financing": "-0.1", "commission": "0.2",
                      "stopLossOrder": {"price": "99"}, "takeProfitOrder": {"price": "102"}}]
    assert runner.sync_closed_trades() == 1
    assert runner.sync_closed_trades() == 0
    assert runner.journal.pnl_for_day(client.now.date()) == Decimal("1.7")


@pytest.mark.parametrize("condition,action", [("wide", "spread_too_wide"), ("stale", "stale_price"),
                                               ("closed", "market_closed"), ("pending", "pending_orders"),
                                               ("margin", "insufficient_margin"), ("budget", "daily_risk_budget")])
def test_entry_guards(tmp_path, monkeypatch, condition, action):
    runner, client = make_runner(tmp_path, monkeypatch)
    if condition == "wide":
        client.quote["closeoutBid"] = "99"
    elif condition == "stale":
        client.quote["time"] = (client.now - timedelta(minutes=1)).isoformat()
    elif condition == "closed":
        client.quote["tradeable"] = False
    elif condition == "pending":
        client.pending = 1
    elif condition == "margin":
        client.instruments = lambda: []
        runner.instrument["marginRate"] = "100"
    elif condition == "budget":
        client.balance = "97500"
        runner.journal.append({"time": client.now.isoformat(), "pnl": "-2500"})
    assert runner.cycle()["action"] == action
    assert not client.orders


def test_order_cancellation_is_not_reported_as_fill(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.response = {"orderCancelTransaction": {"reason": "INSUFFICIENT_MARGIN"}}
    assert runner.cycle()["action"] == "order_cancelled"
    assert runner.cycle()["action"] == "already_evaluated"
    assert not runner.journal.trade_ids(closed=False)


def test_ambiguous_submission_blocks_later_entries_and_restart(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    def timeout(*args):
        client.orders.append(args)
        raise requests.Timeout()
    client.market_order = timeout
    with pytest.raises(requests.Timeout):
        runner.cycle()
    client.now += timedelta(minutes=5)
    restarted = PracticeRunner(runner.config, client, True, clock=lambda: client.now)
    assert restarted.cycle()["action"] == "unresolved_order"
    assert len(client.orders) == 1


def test_time_exit_runs_even_on_same_candle_and_closes_all(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    runner.cycle()
    client.live[0]["openTime"] = (client.now - timedelta(minutes=16)).isoformat()
    assert runner.cycle()["action"] == "time_exit"
    assert client.closes == ["1"]
    assert not client.live


def test_full_exit_then_cooldown_then_fresh_entry(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    runner.cycle()
    client.close_trade("1")
    assert runner.cycle()["action"] == "cooldown"
    client.now += timedelta(minutes=5)
    client.quote["time"] = client.now.isoformat()
    assert runner.cycle()["action"] == "order_filled"
    assert len(client.orders) == 2
    assert len(client.live) == 1


def test_dry_run_does_not_place_or_close_or_consume_execution_state(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch, execute=False)
    assert runner.cycle()["action"] == "dry_run_signal"
    executing = PracticeRunner(runner.config, client, True, clock=lambda: client.now)
    assert executing.cycle()["action"] == "order_filled"
    assert len(client.orders) == 1


def test_foreign_trade_blocks_entries_and_is_never_closed(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.live = [{"id": "manual", "instrument": "XAU_USD",
                    "openTime": (client.now - timedelta(hours=1)).isoformat()}]
    assert runner.cycle()["action"] == "open_trade_exists"
    assert not client.closes and not client.orders


def test_same_candle_does_not_reenter_after_restart(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.response = {"orderCancelTransaction": {"reason": "TEST"}}
    runner.cycle()
    restarted = PracticeRunner(runner.config, client, True, clock=lambda: client.now)
    assert restarted.cycle()["action"] == "already_evaluated"
    assert len(client.orders) == 1


def test_account_lock_prevents_two_runners(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    other = PracticeRunner(runner.config, client, True, clock=lambda: client.now)
    with runner.execution_lock():
        with pytest.raises(RuntimeError, match="account lock"):
            with other.execution_lock():
                pytest.fail("Second runner must not acquire lock")
    with other.execution_lock():
        pass


def test_missing_protection_closes_owned_trade_and_halts(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    runner.cycle()
    client.live[0].pop("stopLossOrder")
    assert runner.cycle()["action"] == "missing_protection"
    assert client.closes == ["1"]
    assert runner.cycle()["action"] == "safety_halt"


def test_dry_run_never_closes_existing_trade(tmp_path, monkeypatch):
    executing, client = make_runner(tmp_path, monkeypatch)
    executing.cycle()
    client.live[0]["openTime"] = (client.now - timedelta(hours=1)).isoformat()
    observing = PracticeRunner(executing.config, client, False, clock=lambda: client.now)
    assert observing.cycle()["action"] == "dry_run_time_exit"
    assert client.closes == []


def test_unexpected_order_response_is_not_filled(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    client.response = {}
    assert runner.cycle()["action"] == "unresolved_order"
    assert runner.cycle()["action"] == "unresolved_order"
    assert len(client.orders) == 1


def test_old_candles_cannot_trigger_new_entry(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    old = client.candles()
    old["time"] = (client.now - timedelta(hours=1)).isoformat()
    client.candles = lambda *args: old
    assert runner.cycle()["action"] == "stale_candles"
    assert not client.orders


def test_sell_order_has_negative_units_and_lower_price_bound(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    monkeypatch.setitem(STRATEGIES, "scalp", lambda frame: Signal("sell", 100, 101, 98.8, "test"))
    assert runner.cycle()["action"] == "order_filled"
    order = client.orders[0]
    assert Decimal(order[1]) < 0
    assert Decimal(order[5]) < Decimal(client.quote["closeoutBid"])
    assert abs(Decimal(order[1])) * (Decimal(order[2]) - Decimal(order[5])) <= 2000


def test_entry_uses_order_book_not_closeout_prices(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    quote = client.pricing("XAU_USD")
    quote.update(closeoutAsk="110", closeoutBid="90")
    client.pricing = lambda instrument: quote
    assert runner.cycle()["action"] == "order_filled"


def test_insufficient_depth_within_bound_blocks_order(tmp_path, monkeypatch):
    runner, client = make_runner(tmp_path, monkeypatch)
    quote = client.pricing("XAU_USD")
    quote["asks"][0]["liquidity"] = 1
    client.pricing = lambda instrument: quote
    assert runner.cycle()["action"] == "insufficient_liquidity"
    assert not client.orders


def test_live_environment_refused_before_any_requests(tmp_path):
    from dataclasses import replace
    with pytest.raises(ValueError, match="practice"):
        PracticeRunner(replace(make_config(tmp_path), environment="live"), None, True)


def test_m1_fast_trades_are_owned_and_time_exited(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setitem(STRATEGIES, "m1_fast", lambda candles: Signal("buy", 100, 99, 101.2, "test"))
    client.candles = lambda *args: pd.DataFrame([{"time": (client.now - timedelta(minutes=1)).isoformat(),
                                                  "open": 100, "high": 101, "low": 99, "close": 100}])
    config = Config(token="token", account_id="account", strategy_name="m1_fast",
                    journal_path=str(tmp_path / "trades.csv"), state_path=str(tmp_path / "state.json"))
    runner = PracticeRunner(config, client, execute=True, clock=lambda: client.now)
    assert runner.cycle()["action"] == "order_filled"
    assert client.orders[0][6] == "goldbot-m1_fast"
    client.live[0]["openTime"] = (client.now - timedelta(minutes=16)).isoformat()
    assert runner.cycle()["action"] == "time_exit"


def make_ladder_runner(tmp_path, monkeypatch):
    client = FakeClient()
    client.modified = []

    def set_trade_orders(trade_id, stop, take_profit):
        client.modified.append((trade_id, stop, take_profit))
        client.trade(trade_id)["stopLossOrder"]["price"] = stop

    client.set_trade_orders = set_trade_orders
    monkeypatch.setitem(STRATEGIES, "scalp", lambda candles: Signal("buy", 100, 99, 101.2, "test"))
    config = replace(make_config(tmp_path), ladder=True)
    runner = PracticeRunner(config, client, execute=True, clock=lambda: client.now)
    assert runner.cycle()["action"] == "order_filled"
    client.candles = lambda *args: pd.DataFrame()
    return runner, client


def test_ladder_entry_uses_distant_broker_target(tmp_path, monkeypatch):
    runner, client = make_ladder_runner(tmp_path, monkeypatch)
    assert client.orders[0][2:4] == ("99.000", "112.000")


def test_ladder_moves_stop_to_break_even_then_previous_step(tmp_path, monkeypatch):
    runner, client = make_ladder_runner(tmp_path, monkeypatch)
    client.quote.update(closeoutBid="101.3", closeoutAsk="101.35")
    result = runner.cycle()
    assert (result["action"], result["step"]) == ("ladder_step", 1)
    assert client.modified[-1] == ("1", "100.050", "112.000")
    client.quote.update(closeoutBid="102.5", closeoutAsk="102.55")
    assert runner.cycle()["step"] == 2
    assert client.modified[-1][1] == "101.200"
    client.live[0]["openTime"] = (client.now - timedelta(minutes=30)).isoformat()
    assert runner.cycle()["action"] == "open_trade_exists"
    assert not client.closes


def test_ladder_closes_when_price_already_fell_back_through_new_stop(tmp_path, monkeypatch):
    runner, client = make_ladder_runner(tmp_path, monkeypatch)
    client.candles = lambda *args: pd.DataFrame([{"time": client.now.isoformat(), "bid_high": 101.3, "high": 101.3}])
    assert runner.cycle()["action"] == "ladder_stop"
    assert client.closes == ["1"]
