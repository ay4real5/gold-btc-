from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class OandaClient:
    BASE_URL = "https://api-fxpractice.oanda.com/v3"

    def __init__(self, token: str, account_id: str, timeout: int = 20):
        self.account_id = account_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        # Retry transient failures on reads only; orders and closes must never be resubmitted blindly.
        retry = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self.session.request(method, self.BASE_URL + path, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.json()

    def account_summary(self) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{self.account_id}/summary")["account"]

    def instruments(self) -> list[dict[str, Any]]:
        return self._request("GET", f"/accounts/{self.account_id}/instruments")["instruments"]

    @staticmethod
    def _candle_rows(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "time": candle["time"],
                "open": float(candle["mid"]["o"]),
                "high": float(candle["mid"]["h"]),
                "low": float(candle["mid"]["l"]),
                "close": float(candle["mid"]["c"]),
                "spread": float(candle["ask"]["c"]) - float(candle["bid"]["c"]),
                "volume": candle["volume"],
                **{f"{side}_{field}": float(candle[side][key])
                   for side in ("bid", "ask")
                   for field, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))},
            }
            for candle in candles if candle["complete"]
        ]

    def candles(self, instrument: str, granularity: str = "M15", count: int = 500) -> pd.DataFrame:
        data = self._request(
            "GET",
            f"/instruments/{instrument}/candles",
            params={"price": "MBA", "granularity": granularity, "count": count},
        )
        return pd.DataFrame(self._candle_rows(data["candles"]))

    def candles_between(self, instrument: str, start: datetime, end: datetime, granularity: str = "M15") -> pd.DataFrame:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("start and end must be timezone-aware and increasing")
        rows: list[dict[str, Any]] = []
        cursor = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_utc = end.astimezone(timezone.utc)
        while True:
            data = self._request(
                "GET",
                f"/instruments/{instrument}/candles",
                params={"price": "MBA", "granularity": granularity, "from": cursor, "count": 5000, "includeFirst": "false"},
            )
            batch = self._candle_rows(data["candles"])
            if not batch:
                break
            rows.extend(batch)
            last_time = pd.Timestamp(batch[-1]["time"]).to_pydatetime()
            if last_time >= end_utc:
                break
            cursor = batch[-1]["time"]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        times = pd.to_datetime(frame["time"], utc=True)
        return frame[times <= end_utc].drop_duplicates("time").reset_index(drop=True)

    def pricing(self, instrument: str) -> dict[str, Any]:
        data = self._request("GET", f"/accounts/{self.account_id}/pricing",
                             params={"instruments": instrument, "includeHomeConversions": "true"})
        if not data["prices"]:
            raise RuntimeError("No pricing returned")
        price = dict(data["prices"][0])
        conversion = next((item for item in data.get("homeConversions", [])
                           if item["currency"] == instrument.split("_")[1]), None)
        if conversion:
            price["loss_conversion"] = conversion["accountLoss"]
            price["position_conversion"] = conversion["positionValue"]
        return price

    def open_trades(self) -> list[dict[str, Any]]:
        return self._request("GET", f"/accounts/{self.account_id}/openTrades")["trades"]

    def closed_trades(self, count: int = 500) -> list[dict[str, Any]]:
        trades = []
        params = {"state": "CLOSED", "count": count}
        while True:
            batch = self._request("GET", f"/accounts/{self.account_id}/trades", params=params)["trades"]
            trades.extend(batch)
            if len(batch) < count:
                return trades
            before = min(int(trade["id"]) for trade in batch) - 1
            if "beforeID" in params and before >= int(params["beforeID"]):
                raise RuntimeError("Trade pagination did not advance")
            params = {**params, "beforeID": str(before)}

    def trade(self, trade_id: str) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{self.account_id}/trades/{trade_id}")["trade"]

    def close_trade(self, trade_id: str) -> dict[str, Any]:
        return self._request("PUT", f"/accounts/{self.account_id}/trades/{trade_id}/close", json={"units": "ALL"})

    def market_order(self, instrument: str, units: str, stop: str, take_profit: str,
                     client_id: str, price_bound: str, tag: str) -> dict[str, Any]:
        order = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": units,
                "timeInForce": "FOK",
                "positionFill": "OPEN_ONLY",
                "priceBound": price_bound,
                "clientExtensions": {"id": client_id, "tag": tag},
                "tradeClientExtensions": {"id": client_id, "tag": tag},
                "stopLossOnFill": {"price": stop, "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": take_profit, "timeInForce": "GTC"},
            }
        }
        return self._request("POST", f"/accounts/{self.account_id}/orders", json=order)
