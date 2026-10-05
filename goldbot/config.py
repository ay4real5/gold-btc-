from dataclasses import dataclass, field
import os
import re

from dotenv import load_dotenv

from .strategy import TIMED_STRATEGIES

GRANULARITY_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


@dataclass(frozen=True)
class Config:
    token: str
    account_id: str
    environment: str = "practice"
    instrument: str = "XAU_USD"
    risk_fraction: float = 0.02
    daily_loss_fraction: float = 0.03
    journal_path: str = "data/trades.csv"
    state_path: str = "data/state.json"
    poll_seconds: int = 30
    stale_seconds: int = 1800
    strategy_name: str = "session_breakout"
    max_hold_seconds: int = 900
    cooldown_seconds: int = 300
    max_spread_r: float = 0.10
    slippage_r: float = 0.05
    ladder: bool = False
    ladder_step_r: float = 1.2
    runner_max_hold_seconds: int = 14400
    strategy_kwargs: dict = field(default_factory=dict)

    @property
    def granularity(self) -> str:
        return TIMED_STRATEGIES.get(self.strategy_name, "M15")

    @property
    def candle_seconds(self) -> int:
        return GRANULARITY_SECONDS[self.granularity]

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        config = cls(
            token=os.getenv("OANDA_API_TOKEN", ""),
            account_id=os.getenv("OANDA_ACCOUNT_ID", ""),
            environment=os.getenv("OANDA_ENV", ""),
            risk_fraction=float(os.getenv("RISK_FRACTION", "0.02")),
            daily_loss_fraction=float(os.getenv("DAILY_LOSS_FRACTION", "0.03")),
            journal_path=os.getenv("JOURNAL_PATH", "data/trades.csv"),
            state_path=os.getenv("STATE_PATH", "data/state.json"),
            poll_seconds=int(os.getenv("POLL_SECONDS", "30")),
            stale_seconds=int(os.getenv("STALE_SECONDS", "1800")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.environment != "practice":
            raise ValueError("Refusing to run: OANDA_ENV must be practice")
        if not self.token or not self.account_id:
            raise ValueError("OANDA_API_TOKEN and OANDA_ACCOUNT_ID are required")
        if not 0 < self.risk_fraction <= 0.05:
            raise ValueError("RISK_FRACTION must be between 0 and 0.05")
        if not 0 < self.daily_loss_fraction <= 0.10:
            raise ValueError("DAILY_LOSS_FRACTION must be between 0 and 0.10")
        if not 10 <= self.poll_seconds <= 60 or self.stale_seconds < 300:
            raise ValueError("Polling must be 10-60s and stale detection at least 300s")
        if self.strategy_name not in {"session_breakout", *TIMED_STRATEGIES}:
            raise ValueError("Unsupported execution strategy")
        if not re.fullmatch(r"[A-Z0-9]+_[A-Z]{3}", self.instrument):
            raise ValueError("Instrument must look like XAU_USD")
        if self.max_hold_seconds < 300 or self.cooldown_seconds < 300:
            raise ValueError("Holding limit and cooldown must be at least five minutes")
        if not 0.3 <= self.ladder_step_r <= 5 or self.runner_max_hold_seconds < self.max_hold_seconds:
            raise ValueError("Invalid ladder step or runner holding limit")
        if not 0 < self.max_spread_r <= 0.25 or not 0 < self.slippage_r <= 0.10:
            raise ValueError("Invalid spread or slippage risk limit")
