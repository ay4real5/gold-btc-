import csv
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


FIELDS = ["trade_id", "time", "instrument", "side", "units", "entry", "sl", "tp", "exit", "pnl", "reason"]


class TradeJournal:
    def __init__(self, path: str):
        self.path = Path(path)

    def append(self, row: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists() and self.path.stat().st_size > 0
        if exists:
            with self.path.open(newline="", encoding="utf-8") as handle:
                if next(csv.reader(handle)) != FIELDS:
                    raise ValueError("Journal schema mismatch; migrate before executing")
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in FIELDS})
            handle.flush()
            os.fsync(handle.fileno())

    def trade_ids(self, closed: bool = True) -> set[str]:
        if not self.path.exists():
            return set()
        with self.path.open(newline="", encoding="utf-8") as handle:
            return {row["trade_id"] for row in csv.DictReader(handle)
                    if row.get("trade_id") and bool(row.get("pnl")) == closed}

    def pnl_for_day(self, day=None) -> Decimal:
        day = day or datetime.now(timezone.utc).date()
        if not self.path.exists():
            return Decimal("0")
        total = Decimal("0")
        with self.path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["pnl"] and datetime.fromisoformat(row["time"].replace("Z", "+00:00")).astimezone(timezone.utc).date() == day:
                    total += Decimal(row["pnl"])
        return total
