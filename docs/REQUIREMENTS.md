# Quantivo product requirements

**Status:** Baseline for implementation  
**Product:** Quantivo, a mobile-first trading assistant  
**Market assumption:** India first. Indian mobile numbers, INR, NSE and BSE, and the MIS / CNC product vocabulary. The domain model does not hard-code a single scanner, broker, or subscription commercial model.

Quantivo aggregates signals from scanner providers, connects a user to a supported broker, calculates a suggested quantity from the user's risk settings, and monitors orders and positions. Scanner providers keep their own names inside the product. Quantivo is the platform brand.

These requirements describe the product. They do not claim that the current code satisfies them. Each group names the phase that owns it. Phase numbers and milestone numbers are the same: Phase 1 is M1. Phase 1 is the current implementation pass.

## 1. Users and responsibilities

| Actor | Responsibility |
| --- | --- |
| Retail trader | Owns the phone number, risk preferences, broker connection, and the explicit confirmation of any order |
| Scanner provider | Owns signal content, its commercial offer, and the meaning of its own subscription |
| Broker | Authoritative source of orders, fills, positions, and funds once a real integration exists |
| Quantivo | Normalizes signals, decides entitlements, calculates quantity, orchestrates confirmed intents, and keeps an audit trail |
| Quantivo operator | Manages users, providers, entitlements, and support investigations through a role-restricted admin portal |
| Payment provider | Takes money. A successful payment is not itself an entitlement |

Quantivo does not become the scanner, the broker, or the payment institution. Market recommendations, scanner data, execution technology, and broker services stay conceptually separate.

## 2. Assumptions

1. The first users already understand that a signal is not an order. Nothing is sent to a broker without an explicit confirmation, and in the current build nothing is sent at all.
2. A user may subscribe to a scanner directly with that provider, or later through Quantivo. Both paths must be able to grant the same kind of entitlement.
3. Not every broker supports the same order types, product codes, or session lifetime. Adapters expose capabilities. The core does not assume they match.
4. MIS and CNC are the first product vocabulary. The platform must not convert one into the other unless the user asks and the broker supports that conversion.
5. Development has no SMS provider and no broker credentials. A development-only authentication provider and a simulated broker are allowed. They must be incapable of booting as production trading.
6. Ratings, subscriber counts, returns, and win rates are omitted until they come from a verified source. The product must not fabricate them.
7. Before any real-money order path is enabled, the applicable SEBI, exchange, broker API, algo-trading, market-data licensing, privacy, and contract obligations have to be identified against the rules then in force. Free signals, a confirmation tap, or a static server IP are not treated as removing those obligations.
8. Local PostgreSQL on this machine cannot use host port 5432, because that port is already taken. Development uses host port 5433.

## 3. Implementation phases

Phase and milestone numbers match. The working order is in [IMPLEMENTATION.md](IMPLEMENTATION.md).

| Phase | Outcome | Requirement groups |
| --- | --- | --- |
| Phase 1 — Foundation (M1) | A developer can run the API locally, sign in with development authentication, see Mani's sample signals, inspect a signal, and see that order placement is refused | Identity foundation, catalogue and mock feed, risk display, simulated broker skeleton, operability |
| Phase 2 — Scanner experience (M2) | Catalogue, activation, one normalized feed, channel registration, and the mobile home and detail screens are the daily path. Horizon is shown on each call, not as a second tab row | Catalogue, entitlements, signal presentation |
| Phase 3 — Simulated trading (M3) | Risk is revalidated on the server, an intent is stored, and a simulated broker fills and protects the position | Risk enforcement, order lifecycle, reconciliation skeleton |
| Phase 4 — Administration (M4) | Operators manage users, providers, entitlements, and reports without seeing broker secrets | Admin portal, reporting, audit review |
| Phase 5 — Production readiness (M5) | The real Mani's Telegram worker and one real broker, after API and regulatory review, behind an explicit live-trading gate | Real adapters, deployment, pilot |

Phase 2's mobile screens are pulled forward only as far as Phase 1 needs them to demonstrate the signal path. The signal table in that slice still stores segment, source channel, and the published horizon text, with Mani's using one channel, so Phase 2 does not have to reshape the row. Channel registration is Phase 2. The horizon is printed on each call. There is no horizon tab row. Phases 3 through 5 are specified so the foundation does not block them. They are not part of the current implementation pass.

## 4. Functional requirements

### 4.1 Identity and access — M1, with recovery depth in later milestones

| ID | Requirement |
| --- | --- |
| REQ-ID-01 | A person registers and signs in with an Indian mobile number and a one-time code. |
| REQ-ID-02 | The development OTP provider is selected only when the environment is development or test. Production startup fails if that provider is configured. The one-time code is never a fixed production bypass. |
| REQ-ID-03 | A successful check issues a short-lived access token and a rotating refresh token. The refresh token is stored only as a hash. Logout and expiry both end the session. |
| REQ-ID-04 | Every new user receives the `user` role. Access to later admin functions requires a separate role. A suspended or closed account cannot open a new session. |
| REQ-ID-05 | The user can read and update a display name and a risk profile. Notification preferences, MPIN, and biometric unlock are specified and are not part of M1. |
| REQ-ID-06 | OTP requests are rate limited. A challenge expires, locks after repeated failures, and is not written to logs or audit payloads. |
| REQ-ID-07 | Account recovery for a lost phone number is an operator-assisted process in a later milestone. Until then, possession of the verified number is the recovery method. |

### 4.2 Broker connections — skeleton in M1, execution in M3, first real broker in M5

| ID | Requirement |
| --- | --- |
| REQ-BR-01 | The core depends on a broker adapter for authentication, instruments, place, modify, cancel, order status, trades, positions, and funds. Unsupported operations fail explicitly. |
| REQ-BR-02 | M1 ships a simulated adapter. It can record a connection and a last-successful-authentication time. It cannot place, modify, cancel, or fill an order. |
| REQ-BR-03 | The user can see connection status: disconnected, connected, expired, or unavailable. Expiry and outage copy must be specific. M1 uses disconnected and connected. |
| REQ-BR-04 | Broker passwords, OTPs, access tokens, and API secrets are never stored in plaintext, in logs, or in audit payloads. The simulated connection stores no secrets at all. |
| REQ-BR-05 | Live order placement stays disabled until the adapter has been tested, the broker permissions are confirmed, and a future build explicitly allows it. The current process refuses to start if live trading is turned on. |
| REQ-BR-06 | When a real broker exists, that broker is authoritative for orders, fills, and positions. Quantivo records intent and history and must not overwrite broker facts. |
| REQ-BR-07 | A trader signs in on Zerodha from Account. An operator saves the Kite Connect api key and api secret once on Admin configuration. The access token stays in the server secret directory, not in a table, and is not returned to the phone. The session lasts until 6:00 AM IST and is not refreshed. After that the account says the session ended and asks for another sign-in. The call shows that Zerodha session. This build records the session and does not send an order. |

### 4.3 Scanner catalogue, subscription, and entitlement — M1 mock, M4 operations

| ID | Requirement |
| --- | --- |
| REQ-SC-01 | The catalogue shows provider name, a monogram until a real logo exists, description, category, scanner name, price, and billing frequency when the provider has them. |
| REQ-SC-02 | Verified ratings and active subscriber counts are null until they come from a trustworthy source. |
| REQ-SC-03 | Activation goes through one entitlement model. The allowed methods are provider API, signed webhook, provider-managed verification, and admin-assisted activation. Phase 1 implements admin-assisted activation for Mani's sample only, and only outside production. |
| REQ-SC-04 | Payment status, provider subscription status, and application entitlement are separate records. Development activation grants an entitlement and does not create a payment. |
| REQ-SC-05 | A user without an active entitlement cannot read that scanner's signals. Activating twice does not create a second active subscription. |
| REQ-SC-06 | Every grant and later revocation is audited. |
| REQ-SC-07 | A scanner may have more than one source channel. The known shape is one Telegram channel per market, such as Equity, F&O, and commodity. Each channel is its own access grant under that scanner. A scanner with one channel has one grant. |
| REQ-SC-08 | The home list shows a signal only when the user is registered for that signal's channel. All shows the union of registered channels and names the channels left out. Opening an unregistered channel says the user is not registered and does not show that channel's calls. |
| REQ-SC-09 | Each source channel has one feed configuration. The kind is `none`, `telegram`, or `http_api`, and the saved options depend on that kind. Telegram stores a channel id and a parser name. An HTTP feed stores a URL and the name of an environment variable for a secret. The secret, the Telegram `api_id`, `api_hash`, and session file are not stored. The worker reads a PDL Sweep body from that URL. Today's rows and the history list become calls. A row without a horizon is Intraday. A horizon on the row is stored as sent. |
| REQ-SC-10 | An operator adds a source channel under a chosen scanner with a channel name and a segment, and can rename that name on the channel card. The field is Channel name. Save channel stores it. The Telegram chat stays a separate field. A new channel starts with no feed and no registrations. Traders who already had the one existing channel on that scanner keep that channel. Stopping a feed and deleting a channel each ask first and name the channel. Delete removes that channel and its stored calls. A channel with an order record is not deleted. |
| REQ-SC-11 | An operator manages the catalogue on Admin. One card is one scanner. The card edits the provider name, the scanner name, and the description shown on the catalogue, and can delete the scanner. The same provider name keeps scanners together, and renaming a provider renames it for every scanner from that publisher. Naming an existing provider moves the scanner under that provider. Add a scanner asks for the provider name, the scanner name, and the description traders see under the name. A new scanner starts with no channels, no price, and no rating. Its channels are added, renamed, and deleted on that same card. A channel with an order record keeps the channel and the scanner. Channels are not visible on another scanner. On Scanners, an operator sees Manage, which opens Admin. |
| REQ-SC-12 | When a trader holds more than one scanner, those names are the Home title. The row scrolls sideways. The selected name is larger and underlined. One tap opens that scanner and its channels. A scanner that is not activated stays on the Scanners screen. One held scanner shows its name as the title, with no switch row. Channel names stay as text tabs under the title. |

### 4.4 Signals — M1

| ID | Requirement |
| --- | --- |
| REQ-SG-01 | One normalized signal model accepts every scanner. Provider-specific payloads do not leak into order and risk code. |
| REQ-SG-02 | A signal carries symbol, exchange, side, timeframe, product hint, trigger, stop-loss, one or more targets, lot size, publication time, expiry, provider status, and an external reference. |
| REQ-SG-03 | Repeat delivery of the same provider content is idempotent. A changed payload revises the row and keeps the original publication time. |
| REQ-SG-04 | The feed distinguishes provider status from derived status. Withdrawn and expired signals stay non-executable. A same-day Intraday or BTST call older than its clock is stale and is not executable. Short term and long term each have their own clock. The starting values are 30 minutes, 30 days, and 30 days. An admin can change them. Intraday to 7 days expires 7 days after the post. A PDL Sweep call whose horizon is Intraday or BTST stays on Actionable through that IST trade date, including after 15:30. The next IST date puts it on All. The desk does not send a status word. A target-hit time shows Final at that time, and that row stays on Actionable while the trade date is still today. With no target-hit time the pill is Open while the trade date is today, and Expired once that date has passed. The desk does not send a stop-hit time. These rows are quoted on All as well as on Actionable. When the row sends stars, the list shows that 1 to 5 mark from the desk's 7-day target touch rate. A row without stars shows none. That call does not use the 30-minute clock or the one-minute bar marks. |
| REQ-SG-12 | The mark on a call is generated. A status word stored on the row is not shown. No NSE comes from the name match. Expired comes from `expires_at`. Stale comes from the horizon clock: 30 minutes for same-day Intraday or BTST, and the saved day clocks for short term and long term. Waiting means the entry window is still open. Window over means that window has ended and the one-minute bars are not in yet. For an NSE cash call, Entry, Caution, Not valid, T1 trail, T2 trail, Final, and Stop are generated from Fyers one-minute bars. Finished one-minute bars are saved. A day already saved is not read again. The minute still forming stays in memory and is filled from the data socket. A socket price is kept only when a quote for that symbol is already in this process and the tick is within 25 percent of that quote. A missing day, including the rest of today after a restart, is read once, slowly enough to stay inside the Fyers data allowance. A finished mark is not read again. The row shows a short coloured pill, such as `Entry 10:05` or `Window over`. The sentence that explains the pill is on the call. The minute on the pill is the minute that produced the mark. Entry is the minute the candle closed through the trigger. A stop or a target uses the minute of the bar that touched it. A bar that touches the stop and a target does not choose. Not valid, Final, and Stop are not executable. Quantity does not change. Without the Fyers app, the clock mark stays and no time is invented. |
| REQ-SG-13 | An NSE cash call shows a last traded price from a configured Fyers app. During the cash session, 09:15 to 15:30 IST on a weekday, the label is LTP. Outside that session the label is Last LTP. The label is on the stock list and on the call, with an em dash when the price is not in yet. The price is green when it is above the previous close and red when it is below, with that percent beside it. A price without the change stays in the body ink. An admin saves the Fyers app id, app secret, and PIN once on Admin configuration, registers the callback URL on that Fyers app, and signs in on Fyers. Quantivo does not ask for the Fyers password. The server keeps the Fyers client id, PIN, and TOTP key in the environment and signs in after 6:30 AM IST. The admin saves that key once. A browser sign-in remains when the key is not saved. The list asks only for actionable calls. A fresh price from the server's one Fyers data socket is shown on the open list, which checks again every 5 seconds. A symbol with no tick for 30 seconds uses the quote call, in batches of 50, and that price is reused for up to a minute. A socket price is kept only when a quote for that symbol is already in this process and the tick is within 25 percent of that quote. Any other tick is ignored and is not folded into the minute. All does not ask for a quote on a closed call. One open call can still show its own price. LTP is not the trigger, it does not change quantity, and it does not mark Entry. F&O and commodity stay without a price until a quote adapter covers them. A chart icon on the list and on the call opens that session's candles at 1 minute and 5 minutes. The back arrow returns to the screen that opened the chart. The horizontal axis shows the bar time in IST. The price scale is on the right and the chart opens on the latest candle. Dragging the chart moves through the session. Dragging the price scale changes the candle height. Dragging the time scale, or the wheel, fits more candles in the view. The crosshair shows that bar's time and price. The candles are the same Fyers one-minute bars used for the price marks, folded into five-minute bars on the chart. They are not stored on the signal. Prepare order on the chart uses the same refusal as the call. |
| REQ-SG-05 | The API and UI label provider-supplied prices separately from Quantivo-calculated quantity. |
| REQ-SG-06 | The M1 feed is Mani's. Until this app's own Telegram worker is connected, an in-process sample uses that name and does not call Telegram. The worker reads feed settings from this database. It does not read another project's database, API, or Telegram login. |
| REQ-SG-11 | An Equity Telegram post is stored when it has a buy level, a stop, and at least one target, and it was sent on a weekday between 09:15 and 15:30 IST. When that post already names the buy and is missing the stop or a target, the worker reads the immediate next message if it is the following message id and was sent within 10 minutes. The call is stored under the first message. A next message that is its own call, names another stock, or carries a different horizon stays separate. The horizon words are stored as published. The worker resolves the posted name against a cached NSE cash list and stores the one matching symbol. A name that matches none or more than one symbol is stored as written and is not executable. A stop or a target on the wrong side of the buy is moved by a power of ten when the current price, or the buy if no price is in yet, shows a missing zero or a slipped decimal. A level already on the right side is kept. The buy is kept. |
| REQ-SG-07 | The home experience shows the Quantivo name, the selected scanner, feed mode, and a compact signal list. One short bar chooses Actionable or All. The Actionable side shows how many calls are on that list. The closed-call count sits in the All side. Actionable hides a stale, expired, or unmatched call, and a call that has touched the first target or the stop. That includes Not valid, Caution, a trail, Final, and Stop. A last price already through a target or the stop leaves Actionable, and the pill says Final, a trail, or Stop, with no minute, until the bars name that minute. The call is not an entry until a fresh call. All includes those calls. The row shows the trigger, the stop, and the targets. The final target is Last. T1 is shown when another target follows it. T2 is shown only when a price sits between the first and the last. A call with one target shows that price as Last. While that list is open it reads the stored calls again every 5 seconds. The last traded price on that read comes from the server's Fyers data socket. A symbol with no recent tick reuses a quote for up to a minute. On a weekday from 09:15 to 15:30 IST the Telegram worker checks the channel about every 5 seconds. Outside that window it checks about once a minute. A new call can appear on the open list without leaving the screen. Detail shows the proposed trade, the quantity breakdown, broker status, and any warning. |
| REQ-SG-08 | A signal carries a market segment: equity, F&O, or commodity. The home feed opens on All segments. The trader can filter to one segment. The filter changes the view only. It does not grant or remove access. |
| REQ-SG-09 | Risk-reward for a target is the distance from the trigger to that target, divided by the distance from the trigger to the stop. For a sell, both distances run the other way. The figure is shown so the trader can judge the call. It is not an input to quantity. A fill at a price other than the trigger changes the real risk-reward, because both distances are then measured from the fill. |
| REQ-SG-10 | A signal stores the horizon words as published, and the channel they came from. Horizon aliases are defined per channel and do not apply to another channel. "Intraday" on one channel is not the same filter as "Intraday to 7 days" on another, unless that pair is explicitly mapped. Unlisted wording stays visible under its original words. The home screen prints the horizon on each call. It does not add a horizon tab row. |

### 4.5 Quantity and risk — calculation in M1, enforcement on submit in M1 and M3

| ID | Requirement |
| --- | --- |
| REQ-RK-01 | The user has a capital allocation per trade, a maximum rupee risk per trade, optional quantity and exposure caps, and an allow-list of products. |
| REQ-RK-02 | Suggested quantity is `floor(maximum rupee risk / per-share risk)`, then rounded down to lot size and reduced by the caps. Capital allocation is not the amount at risk and is not the numerator. |
| REQ-RK-03 | A buy whose stop is not below the trigger, or a sell whose stop is not above the trigger, produces no quantity. |
| REQ-RK-04 | Maximum rupee risk cannot exceed the capital allocated to that trade. |
| REQ-RK-05 | The server recalculates quantity when an order is requested. A client-supplied quantity that differs is rejected. The client is not trusted for price or quantity. |
| REQ-RK-06 | M1 does not check broker funds, because no broker balance is connected. The response says so. Fund checks arrive with the broker adapter that can report them. |
| REQ-RK-07 | F&O and commodity use the contract lot as the lot size. If one lot would lose more than the maximum rupee risk, or a cap cuts the size below one lot, the quantity is none and the reason states that. |

### 4.6 Orders and protection — contract in M1, lifecycle in M3

| ID | Requirement |
| --- | --- |
| REQ-OR-01 | A trade requires an explicit confirmation. The lifecycle vocabulary is: proposed, awaiting confirmation, submitted, accepted, rejected, partially filled, filled, protection pending, protected, exit pending, closed, cancelled, and failed. |
| REQ-OR-02 | From M3, the intent is stored before the broker call. An idempotency key prevents a double submit from a repeated tap, a retry, or a redelivered webhook. |
| REQ-OR-03 | A successful broker acknowledgement is not treated as a fill. |
| REQ-OR-04 | Protective orders are sized to the filled quantity. Partial fills, cancel races, and rejected exits are reconciled. A stop or target is shown as active only after the broker confirms it. Competing exits must not oversell the position. |
| REQ-OR-05 | If protection cannot be confirmed, the position is marked unprotected and the user is notified. |
| REQ-OR-06 | A refused confirmation audits the reason and inserts no intent. A stale, expired, withdrawn, or unmatched call, a product the profile does not allow, a quantity that is not the server's figure, or a missing Zerodha session ends this way. |
| REQ-OR-08 | Buy and Sell on a call open a ticket filled from that call. The product starts as MIS. The trader can change it to CNC, and can edit the trigger, stop, and targets before confirming. Quantity is recalculated from the edited trigger and stop. Confirm stores one proposed intent for that trader and call. A second tap returns that intent. A later edit of an unsent intent updates the same row. Zerodha is not called. The stop and targets are not active. Orders lists that trader's saved intents, newest first, with the status. Another trader's orders are not included. An operator can delete a proposed intent that was not sent to a broker, from Admin or from that account's Orders list. The delete asks first and is audited. The call stays. An intent that was sent stays in the list. |

### 4.7 Positions, notifications, and admin — later milestones

| ID | Requirement | Milestone |
| --- | --- | --- |
| REQ-PS-01 | Intraday and delivery views show symbol, quantity, average fill, protection state, broker price and P&L with timestamps, and exit controls | M3 |
| REQ-PS-02 | Reconciliation repairs missed webhooks, expired sessions, API failures, restarts, and internal-versus-broker drift | M3 |
| REQ-NT-01 | Push notifications cover new signals, order updates, fills, protection events, connection expiry, and failed protection. Voice and sounds come after delivery is reliable | M5, after the core notification path |
| REQ-AD-01 | The admin portal is authenticated and role based. It covers users, providers, catalogue, payment review, entitlements, feed health, signal statistics, execution reports, and period reports | M4 |
| REQ-AD-02 | Signal performance and user execution performance are reported separately. Fills, timing, costs, and quantities are not mixed into one fabricated return | M4 |
| REQ-AD-03 | Operators cannot read broker credentials. Sensitive admin actions are authorized and audited | M4 |
| REQ-AD-04 | An operator can set a channel's feed kind and its non-secret options. A trader cannot. The change is audited. An admin signed in on the phone sees Admin configuration: each channel's feed, and whether the shared worker Telegram login is present. For Telegram, the operator enters the channel name. The API resolves that name to the id of a chat the worker login has already joined, and the id is what is saved. That screen does not collect the phone, API id, API hash, or session. The same screen saves a Fyers app id, app secret, and PIN once, then sends the admin to sign in on Fyers. The password is entered on Fyers. The app secret, PIN, access token, and refresh token are written to the server environment. They are not stored in a table, returned after saving, or written into the audit payload. Admin shows the saved app id and client id again. A blank app secret, PIN, or TOTP key on a later save keeps the stored value. The server signs in with the saved TOTP key after 6:30 AM IST. The TOTP key is not returned after saving. The same screen saves the three clocks for how long Intraday and BTST, short term, and long term stay actionable. Those clocks are one database row. The change is audited. The broader admin portal remains a later client | M4, feed API and phone screen now |

## 5. Non-functional requirements

| ID | Requirement |
| --- | --- |
| REQ-NF-01 | Authentication and authorization are enforced on the server. |
| REQ-NF-02 | Request bodies are validated. Authentication endpoints are rate limited. |
| REQ-NF-03 | Secrets live in the environment, not in source. `.env` files with local secrets are not committed. The development database password in Compose is local only. |
| REQ-NF-04 | Schema changes go through migrations. Production backup and restore are documented before M5, not improvised in M1. |
| REQ-NF-05 | Trade and admin actions write an audit event whose payload has been checked for secret-bearing field names. |
| REQ-NF-06 | Logs are structured, requests carry a correlation id, and `/health` and `/ready` exist. Errors returned to clients do not include secrets or stack traces. |
| REQ-NF-07 | Money and prices use decimal values in the API and numeric columns in PostgreSQL. Floating point is not used for prices or risk. |
| REQ-NF-08 | The system fails closed when a generated status is stale or expired, when the name is not one NSE symbol, when broker state is unknown, when risk validation fails, or when protection cannot be confirmed. |
| REQ-NF-09 | Critical paths in M1 have automated tests: authentication, ingestion and deduplication, entitlement, quantity, secret storage, and the order refusal. |
| REQ-NF-10 | The design stays a modular monolith until a measured operational need justifies a split. Scanner and broker specifics stay behind adapters. |
| REQ-NF-11 | The signed-in phone has a hamburger at the top left. It opens Home, Scanners, Orders, Account, and Admin when the person is an operator. The control itself has no caption. On Home, with more than one held scanner, the title is that scrolling scanner row. On a call, that place shows a back arrow and the symbol. Scanners lists every provider in the catalogue. Call rows stay compact, with a large symbol, side, and quantity. |

## 6. Acceptance for the first runnable slice

A developer can:

1. Start PostgreSQL with Docker Compose and apply migrations.
2. Seed Mani's scanner and its sample signals.
3. Request a development OTP, see it only because the environment is development or test, and open a session.
4. Activate the mock scanner without a payment row being created.
5. List actionable signals and open one signal whose provider prices and Quantivo quantity are visibly distinct.
6. Attempt an order without a Zerodha session and receive a refusal. No order intent or broker order row is created.
7. Sign in on Zerodha, confirm the call, and see one saved intent. A second confirm returns that intent. No broker order row is created, and the stop is not active. The call shows the Zerodha session.
8. Run the automated tests for the behavior above.

The slice is not accepted if live trading can be enabled, if production can start on the development OTP provider, or if a stale, expired, or unmatched signal can be submitted.

## 7. Exclusions

The following are named so they are not implied by the foundation:

- Real SMS delivery, payments, scanner APIs, and broker APIs
- Scraping any private scanner or broker system
- Admin screens, push notifications, and a durable job queue
- Simulated fills, stop-loss placement, and position reconciliation
- MPIN, biometrics, and white-label tenancy
- Performance statistics of any kind
