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
