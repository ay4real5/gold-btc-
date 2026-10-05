from datetime import date
from decimal import Decimal

from goldbot.journal import TradeJournal


def test_rebuilds_daily_pnl_from_csv(tmp_path):
    journal = TradeJournal(str(tmp_path / "trades.csv"))
    base = {"instrument": "XAU_USD", "side": "buy", "units": "1", "entry": "2500", "sl": "2490", "tp": "2520", "exit": "2520", "reason": "test"}
    journal.append({**base, "time": "2026-09-30T10:00:00Z", "pnl": "20"})
    journal.append({**base, "time": "2026-09-30T11:00:00Z", "pnl": "-5"})
    journal.append({**base, "time": "2026-09-29T11:00:00Z", "pnl": "100"})
    assert journal.pnl_for_day(date(2026, 9, 30)) == Decimal("15")
