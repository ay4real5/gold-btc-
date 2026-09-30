# Conversation history (Claude Code → Devin handoff)

A condensed record of the conversation between Ayori and Claude that led to this
repository. It is ordered by time. Secrets are left out on purpose.

## 1. Pocket Option or forex?

Ayori had two options:

- **Pocket Option**: a free "page scanning" signal bot, but only if Ayori
  registers under the referrer's affiliate link.
- **Forex (XAU/USD and BTC)**: someone offered to sell a compiled `.ex5` MT5
  bot.

Claude's assessment:

- **Pocket Option**
  - The referrer is an affiliate and is typically paid a share of the client's
    **losses**.
  - Binary options pay about 80–92% on a win and cost 100% on a loss, so you
    need a win rate of roughly 53–56% just to break even.
  - The broker is offshore and unregulated.
  - Our earlier testing found the S/R signal inverted. A fade version looked
    better but is unproven.
  - Recommendation: skip.
- **EX5 bot**
  - Compiled code, so nobody can see what it does.
  - Most bots for sale are martingale/grid systems or overfit to past data.
  - Required before paying: a verified live track record (Myfxbook/FXBlue
    investor access, 6+ months), max drawdown, no martingale, a demo trial.
  - Never enable "Allow DLL imports".
- **Verdict**: forex is the better market, but not through this seller.

## 2. "I've watched it trade on TikTok Live for 4 months, and he says $50 is enough"

Claude explained that a live stream is not proof:

- The seller chooses when to go live and can end a stream when trades go badly.
- The account could be a demo.
- He could be running several accounts and showing the winning one.
- "$50 minimum" is a sales hook. The real cost is the bot price, and gold/BTC
  can wipe out a $50 account in one move.

Suggested test: ask for the MT5 account number, broker server and **investor
(read-only) password** of the streamed account, plus a demo trial.

## 3. The seller's reply ("SNIPERFX", @Snixpvrfx)

- **What he said**
  - "We don't have trial versions."
  - Pointed to a free Telegram channel of bots
    (`t.me/freeindicatorsrobotsmt4mt5`).
  - Claimed "UltraV1.2B is tested and approved", with an unlimited licence that
    connects "more than 8 accounts".
- **What the channel showed**: it reposts YoForex-branded EAs (e.g. "EA Alpha
  Compass FX.ex4"). YoForex shares copied or cracked EAs.
- **Pinned message**: "Get 400% deposit bonus if you register today", which is
  offshore broker affiliate bait.

**Verdict:** don't buy. He refused both checks, reposts other people's bots and
earns from referrals. Don't run the free `.ex4`/`.ex5` files on a real account,
and don't register with a broker through his link.

## 4. OANDA

- **Why it's acceptable**
  - Established since 1996.
  - Regulated in the US (CFTC/NFA), UK (FCA), Australia (ASIC), Canada,
    Singapore and elsewhere.
  - No giant bonuses.
  - Supports MT4/MT5 and has an official REST API (v20).
- **Caveats**
  - Check which OANDA **entity** the account is opened with. Non-core countries
    are often placed with an offshore OANDA entity that has lighter protection.
  - Only use oanda.com directly.
  - A good broker does not make a strategy profitable.
- **Agreed plan**
  1. Demo account.
  2. API token.
  3. A Python bot with visible code on the v20 API.
  4. Weeks of demo testing before any real money.

## 5. Token check

Ayori shared an OANDA API token. Claude ran read-only checks:

- `GET https://api-fxpractice.oanda.com/v3/accounts` returned account
  `101-004-40412150-001`, a **practice/demo** account.
- The same token on `api-fxtrade.oanda.com` (live) returned *"Insufficient
  authorization"*, so it cannot trade real money.

The token was pasted in chat, so regenerate it in the OANDA dashboard at some
point. It must **never** be committed. This repo is public.

## 6. Handoff

Ayori created this repository and asked for the conversation to be saved here to
continue in Devin. No bot code has been written yet. See `AGENTS.md` for the task.

## Background (earlier projects, for context)

- Ayori runs a separate Deriv demo bot (`derivmasterpiece`, Python), and its
  martingale ladder once lost $896 in 88 seconds. Lesson: no martingale, flat
  risk only.
- Ayori's goal is daily profit with the bot running continuously. The honest
  math is that no bot guarantees daily profit. Demo-test first and judge on
  weeks of logged results.
