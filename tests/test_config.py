import pytest

from goldbot.config import Config


def test_refuses_live_environment():
    config = Config(token="token", account_id="account", environment="live")
    with pytest.raises(ValueError, match="practice"):
        config.validate()


def test_accepts_practice_environment():
    Config(token="token", account_id="account", environment="practice").validate()


def test_enforces_max_risk_fraction():
    Config(token="token", account_id="account", risk_fraction=0.05).validate()
    with pytest.raises(ValueError, match="RISK_FRACTION"):
        Config(token="token", account_id="account", risk_fraction=0.051).validate()


def test_default_risk_fraction_is_two_percent():
    config = Config(token="token", account_id="account")
    assert config.risk_fraction == 0.02


@pytest.mark.parametrize("name,granularity,seconds", [("scalp", "M5", 300), ("scalp38", "M5", 300),
                                                      ("m1_fast", "M1", 60), ("session_breakout", "M15", 900)])
def test_strategy_granularity(name, granularity, seconds):
    config = Config(token="token", account_id="account", strategy_name=name)
    config.validate()
    assert (config.granularity, config.candle_seconds) == (granularity, seconds)


def test_accepts_other_instruments_but_rejects_malformed():
    Config(token="token", account_id="account", instrument="EUR_USD").validate()
    Config(token="token", account_id="account", instrument="NAS100_USD").validate()
    with pytest.raises(ValueError, match="Instrument"):
        Config(token="token", account_id="account", instrument="btcusd").validate()
