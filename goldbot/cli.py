import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from logging.handlers import RotatingFileHandler

from .backtest import run_backtest, run_scalp_backtest
from .config import Config
from .oanda import OandaClient
from .runner import PracticeRunner
from .strategy import STRATEGIES, breakout_signal


def main() -> None:
    parser = argparse.ArgumentParser(description="Practice-only OANDA gold bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show practice account and instrument status")
    backtest = subparsers.add_parser("backtest", help="Backtest one strategy on recent candles")
    backtest.add_argument("--granularity", default="M15", choices=["M5", "M15", "M30", "H1"])
    backtest.add_argument("--count", type=int, default=500)
    backtest.add_argument("--strategy", default="breakout", choices=STRATEGIES)
    compare = subparsers.add_parser("compare", help="Compare all strategies over a historical period")
    compare.add_argument("--granularity", default="M15", choices=["M5", "M15", "M30", "H1"])
    compare.add_argument("--days", type=int, default=90)
    signal = subparsers.add_parser("signal", help="Evaluate the latest completed candles without trading")
    signal.add_argument("--granularity", default="M15", choices=["M5", "M15", "M30", "H1"])
    run = subparsers.add_parser("run", help="Run practice forward testing")
    run.add_argument("--execute", action="store_true", help="Allow practice orders")
    run.add_argument("--once", action="store_true", help="Run one cycle and exit")
    run.add_argument("--strategy", default="session_breakout", choices=["session_breakout", "scalp"])
    scalp_check = subparsers.add_parser("scalp-check", help="Read-only M5 bid/ask historical check")
    scalp_check.add_argument("--days", type=int, default=30)
    scalp_check.add_argument("--slippage", type=float, default=0.05, help="USD per gold unit per market fill")
    args = parser.parse_args()

    if args.command == "backtest" and args.strategy == "scalp":
        parser.error("Use scalp-check for the M5 strategy and its timed-exit cost model")
    config = Config.from_env()
    client = OandaClient(config.token, config.account_id)
    if args.command == "run":
        config = replace(config, strategy_name=args.strategy)
        runner = PracticeRunner(config, client, execute=args.execute)
        with runner.execution_lock():
            runner.state_path.parent.mkdir(parents=True, exist_ok=True)
            log_path = runner.state_path.with_suffix(".log")
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                                handlers=[logging.StreamHandler(), RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)])
            if args.once:
                print(json.dumps(runner.cycle(), indent=2))
            else:
                runner.run()
        return
    names = {item["name"] for item in client.instruments()}
    if config.instrument not in names:
        raise RuntimeError(f"{config.instrument} is not tradable on this account")

    if args.command == "status":
        account = client.account_summary()
        output = {
            "environment": config.environment,
            "instrument": config.instrument,
            "currency": account["currency"],
            "balance": account["balance"],
            "openTradeCount": account["openTradeCount"],
            "pendingOrderCount": account["pendingOrderCount"],
        }
    elif args.command == "scalp-check":
        if not 7 <= args.days <= 365:
            parser.error("--days must be between 7 and 365")
        end = datetime.now(timezone.utc)
        candles = client.candles_between(config.instrument, end - timedelta(days=args.days), end, "M5")
        output = run_scalp_backtest(candles, slippage=args.slippage,
                                    risk_fraction=float(os.getenv("RISK_FRACTION", "0.02")), daily_loss_fraction=config.daily_loss_fraction)
    elif args.command == "compare":
        if not 7 <= args.days <= 730:
            raise ValueError("--days must be between 7 and 730")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        candles = client.candles_between(config.instrument, start, end, args.granularity)
        output = {
            "instrument": config.instrument,
            "granularity": args.granularity,
            "days": args.days,
            "completed_candles": len(candles),
            "cost_model": "historical close spread charged once per trade; stop wins ties",
            "results": {name: asdict(run_backtest(candles, strategy)) for name, strategy in STRATEGIES.items() if name != "scalp"},
        }
    else:
        candles = client.candles(config.instrument, args.granularity, args.count if args.command == "backtest" else 250)
        if args.command == "backtest":
            output = asdict(run_backtest(candles, STRATEGIES[args.strategy]))
        else:
            latest = breakout_signal(candles)
            output = {"completed_candles": len(candles), "signal": asdict(latest) if latest else None}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
