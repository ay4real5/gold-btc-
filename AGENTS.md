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
3. **Flat, fixed risk per trade** (e.g. 1% of balance, sized from the SL
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
