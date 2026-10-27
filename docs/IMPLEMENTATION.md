# Implementation plan

This is the working plan. Requirements say what the product must do. Decisions say what was chosen and rejected. This file says what is already true in the repository and what happens next.

Update this file in the same change as any review that changes behavior. Also update [REQUIREMENTS.md](REQUIREMENTS.md) and [architecture/DECISIONS.md](architecture/DECISIONS.md). The review screen at `mockup/quantivo-mobile.html` follows those documents. It is not a second source of truth.

**As of 23 October 2026.**

## Where things stand

| Item | State |
| --- | --- |
| Requirements, architecture, and decisions ADR-001 through ADR-023 | Written |
| Implementation phases | Phase 1 through Phase 5, numbered the same as M1 through M5 |
| API under `backend/` | Phase 1 schema is migrated. The automated tests pass |
| Expo app | `mobile/`. Development sign-in, Mani's sample list, and signal detail |
| Review screen | `mockup/quantivo-mobile.html`. Phone and desktop, sample data, nothing persisted |
| Current phase | Phase 1 is in the repo. Channel feed settings and the Equity parser are in the repo. Phases 2 through 5 are otherwise not started |

## Checklist

Done means the behavior is in the API or the app and covered by the Phase 1 tests. Next means it is specified and not started.

### Phase 1 — Foundation

- [x] Local Postgres, migration, and seed of Mani's scanner, the Equity channel, and sample calls
- [x] Development sign-in. The one-time code is returned only in development and test
- [x] Sample feed, signal list, and signal detail. The sample does not call Telegram
- [x] Each call stores segment, source channel, and the horizon words as published
- [x] Quantity from maximum loss. Capital and risk-reward do not change the share count. The ticket starts from that quantity on every scanner. While the call is executable, another whole-lot quantity can be confirmed. A call that is not executable shows that quantity and does not take another. The field shows the rupee risk and the rupee reward for that quantity. A connected Zerodha session keeps the quantity only when the available margin covers it
- [x] Zerodha sign-in, then one saved intent for a call. No broker order is written. The call shows that Zerodha session
- [x] A trader signs in on Zerodha from Account. The Kite app key and secret are saved once on Admin. The access token stays in the server secret directory until 6:00 AM IST. This build does not send an order
- [x] Automated tests for that path
- [x] Start, stop, and restart scripts. A busy port is left alone
- [ ] Confirm on the phone: open one call, tap Buy, and save the intent. The screens and the API tests are in place

### Phase 2 — Scanner experience

- [ ] Editable risk profile at first login and on Account, saved in `risk_profiles`
- [x] Home row: All, then each source channel. All is the registered calls together. No horizon tab row
- [x] Actionable and All are one short bar. The Actionable side shows how many calls are on that list. The closed-call count sits in the All side. A call that has touched the first target or the stop leaves Actionable, including a last price already through either level. The row shows the trigger, the stop, and the targets. The final target is Last. T1 is shown when another target follows it. T2 is shown only when a price sits between the first and the last. A call with one target shows that price as Last.
- [x] A hamburger at the top left opens Home, Scanners, Orders, Account, and Admin for an operator. Orders lists that trader's saved intents. A call shows a back arrow there
- [x] An operator manages scanners on Admin, one card each. Add a scanner asks for the provider name, the scanner name, and the description. The card edits those same fields, deletes the scanner, and adds, renames, and deletes its channels. Manage on the Scanners card opens Admin. Channels are added under that scanner. Home opens the scanner that was chosen
- [x] Home switches held scanners in one tap. The channel row is the open scanner's channels
- [x] Each call's mark is generated from the name match, the expiry clock, the horizon clocks, the entry window, and Fyers one-minute bars for an NSE cash call. Same-day Intraday and BTST go stale at 30 minutes. Short term and long term go stale at 30 days until an admin changes those clocks. Intraday to 7 days expires 7 days after the post. The chip shows Entry, Caution, Not valid, a trail, Final, or Stop with the minute that produced it. Caution, a trail, Not valid, Final, and Stop are not an entry. A stored status word is not shown. Without the Fyers app the clock mark stays and no time is invented
- [x] An NSE cash call shows LTP during the cash session and Last LTP outside it, including when the price is not in yet. The price is green when it is above the previous close and red when it is below, with that percent beside it. A price without the change stays in the body ink. The open list reads the server's Fyers data socket price with the stored calls. A symbol with no recent tick uses one quote call, reused for up to a minute. A socket price is kept only when a quote for that symbol is already in this process and the tick is within 25 percent of that quote. Any other tick is ignored. A chart icon on the list and on the call opens the session candles at 1 minute and 5 minutes. The back arrow returns to the screen that opened the chart. The horizontal axis shows the bar time in IST. The price scale is on the right and the chart opens on the latest candle. Dragging the chart moves through the session. Dragging the price scale changes the candle height. Dragging the time scale, or the wheel, fits more candles in the view. The crosshair shows that bar's time and price. The list asks Fyers only for actionable calls. The price is not the trigger and it does not change quantity.
- [x] Registration per channel. An unregistered channel says so and shows no calls
- [ ] Horizon text on each call. "Intraday" and "Intraday to 7 days" stay different strings
- [ ] Provider prices labeled apart from the Quantivo quantity

### Phase 3 — Simulated trading

- [x] One stored intent before any broker call. A repeated tap does not create a second intent. The ticket is filled from the call, the product starts as MIS, and prices can be edited. Zerodha is not called. Orders lists those saved intents and their status. An operator can delete a proposed intent that was not sent, from Admin or from Orders, after asking first. The call stays
- [ ] Simulated fill and protection. A stop or target is active only after the broker says so
- [ ] Positions show what the simulated broker reported

### Pulled forward — Mani's Equity feed

- [x] Equity parser writes the existing signal shape. Horizon words stay as published. A buy posted without its stop or target is completed from the immediate next Telegram message when that message follows within 10 minutes and does not start another call. A stop or a target on the wrong side of the buy moves by a power of ten when the current price, or the buy, shows a missing zero or a slipped decimal. The worker resolves a posted name against a cached NSE cash list and stores that symbol. An unresolved or ambiguous name is stored and is not executable
- [x] One feed row per source channel. Kinds are `none`, `telegram`, and `http_api`, each with its own options
- [x] Operator API to read and update those settings. A trader receives 403. The change is audited
- [x] `python -m app.feeds.worker` reads the channel history once, then checks for new posts about every 5 seconds on a weekday from 09:15 to 15:30 IST, and about once a minute outside that window. Home reads those stored calls again every 5 seconds while it is open. The last traded price comes from one Fyers data socket. A symbol with no recent tick reuses a quote for up to a minute. Quotes and one-minute History share the Fyers Prime budget of 10 a second, 500 a minute, and 500,000 a day. Finished one-minute bars are saved, a day already saved is not read again, and the minute still forming is filled from the data socket. A socket price is kept only when a quote for that symbol is already in this process and the tick is within 25 percent of that quote. A finished mark is not read again. Sample calls leave the list when the feed kind is Telegram. The worker starts with this project's services only after this machine has its own login
- [x] HTTP reader for a PDL Sweep body. The worker GETs the saved URL on its poll interval and stores today's rows and the history list. A row from an earlier trade date shows on All. The horizon is Intraday unless the row sends one. That Intraday call stays on Actionable through its IST trade date, then it is on All. A target-hit time shows Final. With no target-hit time the pill is Open on that date and Expired after it. When the row sends stars, the list shows that 1 to 5 mark. Another HTTP body is saved and skipped
- [x] Admin configuration on the signed-in phone, shown when the account has the admin role. It saves each channel's feed and shows the shared worker login as present or missing. It saves a Fyers app id, app secret, PIN, client id, and TOTP key once. The server signs in after 6:30 AM IST. A browser sign-in remains when the TOTP key is not saved. Those secrets are not stored in a table and are not shown again. A Telegram channel name is resolved to the id of a joined chat. Stopping a feed and deleting a channel each ask first. Delete removes the channel and its stored calls, and refuses when an order record points at one of those calls. The broader Next.js portal is still later
- [ ] F&O and commodity parsers. Those channels cannot use `equity_calls`

### Phase 4 — Administration

- [ ] Operator sign-in on the admin portal. Today an operator is a signed-in user with the admin role, granted by `python -m app.grant_admin`
- [ ] Manage users, providers, entitlements, and reports
- [ ] Signal results and the trader's fills reported separately
- [ ] Operators cannot read broker secrets

### Phase 5 — Production readiness

- [ ] One worker polls Mani's Telegram channels into the same scanner. The command and the Equity parser are in the repo. Polling waits until this worker has its own Telegram login
- [ ] One real broker behind the live-trading gate
- [ ] Push notifications for new calls, fills, protection, and connection expiry
- [ ] Lightsail pilot. Live trading stays off until that broker path is reviewed

## Review decisions now in the docs

These were checked on the review screen and then written into the requirements and decisions.

| Topic | Rule | Where |
| --- | --- | --- |
| Quantity | Maximum loss divided by the distance from trigger to stop, then lot size and caps. Capital set aside is not the numerator | ADR-009, REQ-RK-02 |
| Risk-reward | Shown from the trigger. Does not change quantity | ADR-020, REQ-SG-09 |
| One lot too large | Quantity is none, and the screen says why. F&O and commodity use the contract lot | ADR-021, REQ-RK-07 |
| Segments | All, then Equity, F&O, or Commodity. A filter, not a subscription | ADR-021, REQ-SG-08 |
| Source channels | Registration is per source channel. All shows registered calls and names the channels left out. An unregistered channel says so and shows no calls. An operator adds and renames a channel from Admin configuration | ADR-022, ADR-025, REQ-SC-07, REQ-SC-08, REQ-SC-10 |
| Horizon words | Stored as published. Aliases apply only inside that channel. "Intraday" is not silently the same as "Intraday to 7 days" | ADR-022, REQ-SG-10 |

## Phases

Phase numbers match the milestone numbers in the requirements. Finish a phase before starting the next one.

### Phase 1 — Foundation

The current phase. A developer can run the API locally and walk the signal path. The acceptance list in the requirements governs this phase.

- Local Postgres, migrations, and a seed of Mani's scanner and its sample signals.
- Development sign-in. The one-time code is returned only in development and test.
- One Mani's sample feed, a signal list, and signal detail. The sample does not call Telegram.
- Each signal stores its segment, source channel, and the horizon words as published. The sample uses one channel. Do not copy the Equity parser's global "intraday" rule into the platform.
- Quantity from maximum loss. Capital and risk-reward do not change the share count.
- A Zerodha sign-in, then one saved intent. No broker order is written. Live trading stays off.
- Automated tests for that path, and the Expo screens needed to sign in, list signals, and open one.

### Phase 2 — Scanner experience

The home screen matches the review screen.

- The risk profile is editable at first login and on Account, and the values are saved.
- One scanner feed titled Mani's Channel. The only category row is All registered, Equity, F&O, and Commodity.
- Registration is per channel. An unregistered channel says so and shows no calls. The filter does not grant access.
- Horizon text stays on each call. There is no horizon tab row. "Intraday" and "Intraday to 7 days" stay different strings.
- Provider prices stay labeled apart from the Quantivo quantity.

### Phase 3 — Simulated trading

- The server rechecks the signal, the product, and the quantity, then stores one intent before any broker call.
- A repeated confirmation does not create a second intent.
- The simulated broker can fill and place protection. A stop or target is active only after that broker says so.
- Positions show what the simulated broker reported. Nothing is sent to a real broker.

### Phase 4 — Administration

- A separate admin sign-in for operators.
- Operators manage users, providers, entitlements, and reports.
- Signal results and the user's own fills are reported separately.
- Operators cannot read broker secrets.

### Phase 5 — Production readiness

- One worker polls Mani's Telegram channels and writes into the same scanner. `python -m app.feeds.worker` is that worker. It reads this database and does not hold a Telegram login until the operator sets one on that process.
- One real broker, after its adapter is tested and the live-trading gate is explicitly opened.
- Push notifications for new calls, fills, protection, and connection expiry.
- The first production host is the Lightsail pilot. Live trading stays off until the broker path and the regulatory checks for that path are done.

## Not in Phase 1

- Saving the review screen's typed risk numbers. The screen keeps them in memory only. Saving the profile is Phase 2.
- A second risk profile per segment.
- Registering the F&O and commodity channels. Channel registration is Phase 2. The Equity feed can be set to Telegram. The worker polls only after this machine has its own login.
- Orders that leave the machine. Simulated fills are Phase 3. A real broker order is Phase 5.
