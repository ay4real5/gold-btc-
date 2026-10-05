from datetime import datetime, timezone

from goldbot.oanda import OandaClient


def candle(time):
    prices = {"o": "100", "h": "101", "l": "99", "c": "100"}
    return {"time": time, "complete": True, "mid": prices, "bid": prices, "ask": {**prices, "c": "100.2"}, "volume": 1}


def test_candles_between_paginates_until_end(monkeypatch):
    client = OandaClient("token", "account")
    batches = [
        {"candles": [candle("2026-01-01T00:15:00Z")]},
        {"candles": [candle("2026-01-01T00:30:00Z")]},
    ]
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: batches.pop(0))
    frame = client.candles_between(
        "XAU_USD",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
    )
    assert len(frame) == 2
    assert not batches


def test_market_order_and_full_close_payloads(monkeypatch):
    client = OandaClient("token", "account")
    calls = []
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    client.market_order("XAU_USD", "1", "99", "101.2", "entry-1", "100.05", "goldbot-scalp")
    order = calls[0][1]["json"]["order"]
    assert order["stopLossOnFill"]["price"] == "99"
    assert order["takeProfitOnFill"]["price"] == "101.2"
    assert order["priceBound"] == "100.05"
    assert order["positionFill"] == "OPEN_ONLY"
    assert order["tradeClientExtensions"]["tag"] == "goldbot-scalp"
    client.close_trade("1")
    assert calls[1] == (("PUT", "/accounts/account/trades/1/close"), {"json": {"units": "ALL"}})


def test_closed_trades_pages_beyond_first_page(monkeypatch):
    client = OandaClient("token", "account")
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs["params"])
        return {"trades": [{"id": "4"}, {"id": "3"}] if len(calls) == 1 else [{"id": "2"}]}
    monkeypatch.setattr(client, "_request", request)
    assert len(client.closed_trades(count=2)) == 3
    assert calls[1]["beforeID"] == "2"


def test_pricing_requests_current_home_conversions(monkeypatch):
    client = OandaClient("token", "account")
    def request(*args, **kwargs):
        assert kwargs["params"]["includeHomeConversions"] == "true"
        return {"prices": [{"tradeable": True}],
                "homeConversions": [{"currency": "USD", "accountLoss": "0.76", "positionValue": "0.75"}]}
    monkeypatch.setattr(client, "_request", request)
    quote = client.pricing("XAU_USD")
    assert quote["loss_conversion"] == "0.76"


def test_retries_reads_but_never_order_writes():
    client = OandaClient("token", "account")
    retry = client.session.get_adapter("https://api-fxpractice.oanda.com").max_retries
    assert retry.total == 3
    assert retry.is_retry("GET", 504)
    assert not retry.is_retry("POST", 504)
    assert not retry.is_retry("PUT", 504)
