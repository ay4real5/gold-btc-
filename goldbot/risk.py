from decimal import Decimal, ROUND_DOWN


def position_units(
    balance: Decimal,
    risk_fraction: Decimal,
    entry: Decimal,
    stop: Decimal,
    quote_to_home: Decimal,
    precision: int = 1,
) -> Decimal:
    distance = abs(entry - stop)
    if distance <= 0 or quote_to_home <= 0:
        raise ValueError("Stop distance and conversion factor must be positive")
    raw_units = balance * risk_fraction / (distance * quote_to_home)
    quantum = Decimal(1).scaleb(-precision)
    units = raw_units.quantize(quantum, rounding=ROUND_DOWN)
    if units <= 0:
        raise ValueError("Calculated position size is below the minimum")
    return units


def daily_loss_reached(realized_pnl: Decimal, opening_balance: Decimal, cap_fraction: Decimal) -> bool:
    return realized_pnl <= -(opening_balance * cap_fraction)
