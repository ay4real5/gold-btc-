# AGENTS.md

Read `CONVERSATION.md` first for the history and the reasons behind this project.

## Goal

Build a Python trading bot for **XAU/USD** (and **BTC/USD** if the account offers
it) on the **OANDA v20 REST API**. It runs on a **demo (practice) account only**
until weeks of logged results justify real money. Ayori decides that step
explicitly, not the agent.

## Environment

- Practice API base: `https://api-fxpractice.oanda.com/v3`
- Practice stream: `https://stream-fxpractice.oanda.com/v3`
- Account ID: `101-004-40412150-001` (practice)
- Credentials come from environment variables. In Devin, set them as secrets.
  Locally, put them in a `.env` file, which is gitignored.
  - `OANDA_API_TOKEN`
  - `OANDA_ACCOUNT_ID`
  - `OANDA_ENV=practice`
- The repo is **public**. Never commit tokens, `.env`, or account credentials.

## Hard requirements

1. **Demo only.** Refuse to start if `OANDA_ENV` is not `practice`, unless
   Ayori explicitly adds a live mode later.
2. **Stop-loss and take-profit on every order**, attached at order creation.
3. **Flat, fixed risk per trade** (currently 2% of balance, sized from the SL
   distance). **No martingale, grid or loss-recovery staking.**
4. **Daily loss cap.** Stop trading for the day after a set loss. Rebuild the
   day's PnL from the journal on restart, so the cap survives restarts.
5. **Trade journal** (CSV): time, instrument, side, units, entry, SL, TP, exit,
   PnL, reason. It is used to judge the strategy after weeks of demo.
6. **Liveness.** The previous Deriv bot failed by hanging while still alive.
   Log a heartbeat, and alert or restart when no candles or ticks have arrived
   recently.
7. **Check instruments first.** Call `GET /accounts/{id}/instruments` and
   confirm `XAU_USD` / `BTC_USD` are available before relying on them.

## Suggested first steps

1. Scaffold the project: `requirements.txt` (`requests`, `python-dotenv`,
   `pandas`), `.env.example`, a config module, and an OANDA client wrapper.
2. List the account summary and instruments, then report which are tradable.
3. Implement one simple, testable strategy (e.g. a trend filter plus a
   breakout/pullback entry on M15/H1) with a backtest on OANDA historical
   candles before running it on demo.
4. Run it on the practice account and review the journal weekly.

## Out of scope

- Buying or running third-party EX4/EX5 bots (see `CONVERSATION.md` §3).
- Pocket Option / binary options.

## Local verification and runner modes

- Run tests from the repository root: `python -m pytest -q`.
- Read-only account check: `python -m goldbot status`.
- M5 scalp history check: `python -m goldbot scalp-check --days 90`.
  Uses bid/ask candles, next-open entries, assumed adverse slippage, timed exits,
  and a daily risk budget. It is still an OHLC approximation, not proof of execution or profitability.
- No-order runner check: `python -m goldbot run --strategy scalp --once`.
- Continuous observation: `python -m goldbot run --strategy scalp`.
  Practice order execution requires the additional explicit `--execute` flag.
- Execution defaults to the existing session breakout; select `--strategy scalp`
  for M5 EMA9/20 fresh crosses with EMA50 trend, 1 ATR stops and 1.2 ATR targets.
  Scalp trades have a 15-minute full-close deadline and a five-minute post-exit cooldown.
  Time exits require the local process, network and market to be available; broker SL/TP remain attached.
- The CLI takes a per-account process lock. Dry-run state/journal/logs are separate
  from execution state. Runtime logs rotate beside the state file.
- An ambiguous order submission persists a pending intent and blocks new entries
  until reconciled. Do not delete state to bypass a pending intent or safety halt.
- Keep this as a dedicated bot practice account. Manual transactions, transfers,
  partial closes, and other agents can invalidate balance/journal-based daily accounting.
- The first July-September 2026 M5 scalp check was negative. It is an experimental
  candidate, not a validated replacement for the session strategy. Historical
  session results also use the older, simpler backtest model.

## High-frequency demo data collection (2026-10-05)

Ayori wants at least 30 trades/day of demo data. Each timed strategy runs on its own practice
sub-account with its own data folder and 0.1% risk, so the 3% daily cap allows about 30 losses:

- `python -m goldbot run --strategy m1_fast --data-dir data/m1_fast --risk 0.001 --execute`
  (main account): M1 EMA20 continuation, 2 ATR stop, 1.2R target. About 33-36 trades/day.
- `python -m goldbot run --strategy scalp38 --account-id <sub-account> --data-dir data/scalp38 --risk 0.001 --execute`:
  M5 EMA3/8 cross, about 9 trades/day. This needs a second practice sub-account that Ayori creates in the OANDA hub.
- History checks: `python -m goldbot scalp-check --strategy {scalp,scalp38,m1_fast} --days 14`
  (set `RISK_FRACTION=0.001`). Over 2026-09-21 to 2026-10-05: scalp38 had 90 trades and +2.0R
  (+0.02R/trade, PF 1.07); m1_fast had 362 trades and -60.5R (-0.17R/trade, PF 0.66), because spread is large
  compared with M1 stops. The 2% default risk with the 3% daily cap throttles any strategy to about 2 trades/day.
- OANDA GET requests retry 429/5xx/connection errors. Orders and closes are never retried.
- Auto-restart: Windows scheduled task `GoldBotRunner` (installed by Ayori's request via `tools/install_task.ps1`) runs scalp38 + ladder at logon and re-checks every 5 minutes. Stop it with `Stop-ScheduledTask GoldBotRunner` and remove it with `Unregister-ScheduledTask GoldBotRunner`.

## Ladder exit (2026-10-05)

`--ladder` on `run` or `scalp-check` replaces the fixed 1.2R target with a stepped stop.
- At +1.2R the stop moves to break-even plus 0.05R. At each further 1.2R step it moves to the previous step.
- The broker take-profit becomes a distant 12R ceiling. The broker stop-loss stays attached the whole time.
- After step 1 the 15-minute time exit becomes a 4-hour limit.
- The bot detects steps from the current quote and M1 highs/lows since entry. If price has already fallen back through
  the new stop, it closes the trade (`ladder_stop`).
- Stop updates use `PUT /trades/{id}/orders` and are not retried.
- Over 28 days of scalp38 history: fixed target +3.3R (PF 1.05, max DD 9.6R), ladder +3.6R (PF 1.06, max DD 13.0R).
  No proven difference yet. The plan is an A/B test: the main account runs scalp38 with the fixed target, and a second
  practice sub-account runs `--strategy scalp38 --ladder --account-id <id> --data-dir data/scalp38_ladder --risk 0.001 --execute`.
