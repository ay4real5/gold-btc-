from decimal import Decimal

from goldbot.risk import daily_loss_reached, position_units


def test_position_size_uses_fixed_balance_risk():
    units = position_units(
        balance=Decimal("10000"),
        risk_fraction=Decimal("0.02"),
        entry=Decimal("2500"),
        stop=Decimal("2490"),
        quote_to_home=Decimal("0.75"),
    )
    assert units == Decimal("26.6")


def test_daily_loss_cap():
    assert daily_loss_reached(Decimal("-300"), Decimal("10000"), Decimal("0.03"))
    assert not daily_loss_reached(Decimal("-299.99"), Decimal("10000"), Decimal("0.03"))


def test_daily_loss_applies_to_account_balance():
    opening = Decimal("10000")
    pnl = Decimal("-500")
    assert daily_loss_reached(pnl, opening, Decimal("0.03"))
    assert not daily_loss_reached(pnl, opening, Decimal("0.06"))
