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
