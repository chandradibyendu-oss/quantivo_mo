# Architecture decisions

Decisions below are accepted unless a status says otherwise. They constrain the rest of the build. A later change needs a new decision, not a quiet exception in a feature branch.

## ADR-001 — Modular monolith

**Status:** Accepted

**Context.** The product needs several domains: identity, scanners, entitlements, risk, orders, and brokers. It does not yet have the traffic, the team size, or the release independence that would justify separate services.

**Decision.** One API process owns the domain modules and one PostgreSQL database. Modules are packages with explicit calls. A worker may be added later as another process on the same database. It is not a new bounded context with its own store.

**Consequences.** Cross-module changes are transactions, which is what order validation needs. The process must stay disciplined so scanner and broker code do not spread into the core. Operational scale is a later problem.

**Rejected.** Microservices per module. Separate databases per module. A shared "utils" layer that every feature imports for business rules.

## ADR-002 — Technology stack

**Status:** Accepted

**Context.** The repository was empty. The product needs a mobile client, a typed API, and a relational store. The machine already has Python 3.13, Node 22, and Docker. Port 5432 is already in use.

**Decision.**

| Concern | Choice |
| --- | --- |
| Mobile | React Native with Expo and TypeScript. Pin the current stable Expo SDK when the app is scaffolded |
| API | Python, FastAPI, Pydantic. Support 3.11 and newer. Develop on 3.13 |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Admin portal | Next.js and TypeScript, in M4 |
| Local database | Docker Compose, host port 5433 |
| Tests | Pytest for the API. Component tests for the app when it exists |

**Consequences.** The API and the app are separate deployables in one repository. The admin portal is not started just to occupy a directory.

**Rejected.** A mobile-only repository, SQLite as the system of record, and introducing a queue or Redis before there is a job to run.

## ADR-003 — Synchronous database sessions

**Status:** Accepted for the monolith

**Context.** The foundation's work is request-scoped transactional logic: OTP checks, entitlement checks, and a quantity comparison. Adapter I/O will matter later.

**Decision.** SQLAlchemy 2 sessions are synchronous. FastAPI runs those endpoints in its thread pool. Async is reserved for a later adapter that is actually network-bound.

**Consequences.** Transactions are easy to see and to test. A slow broker call in a future milestone must not sit inside an open write transaction.

**Rejected.** Async sessions everywhere in M1. A raw SQL layer beside the ORM.

## ADR-004 — Development OTP is a different provider, and production cannot select it

**Status:** Accepted

**Context.** SMS is not available, and a fixed code such as `000000` would be dangerous if it ever shipped. The mobile flow still has to be usable on a developer machine.

**Decision.** `AUTH_PROVIDER=dev_mock` is the only provider in this build. It stores an HMAC of the code. It returns the code only when the environment is development or test. If the environment is production, settings fail to load. There is no production OTP provider yet, so production cannot start. That is intentional.

Challenges expire, older unused challenges are consumed when a new one is issued, requests are rate limited, and the raw code is excluded from logs and audit events.

**Consequences.** Deploying this build to production fails closed until a real delivery provider is added and the guard is updated on purpose.

**Rejected.** A magic OTP that works in every environment. Logging the code. Putting the code in the audit payload.

## ADR-005 — Live trading cannot be enabled

**Status:** Accepted

**Context.** A boolean named `LIVE_TRADING_ENABLED` is a common foot-gun. The simulated adapter could be mistaken for a paper broker that fills orders.

**Decision.** Any configuration with live trading enabled is invalid. The simulated adapter raises on place, modify, and cancel. The order endpoint audits a refusal and writes no order row. M3 may add simulated fills behind the same adapter without flipping this flag. A real broker requires a new decision, a tested adapter, and an explicit configuration change.

**Consequences.** There is no hidden paper-trading success path. Tests can assert that the flag cannot be turned on.

**Rejected.** A development switch that submits orders to a real sandbox using credentials in `.env`. Treating HTTP 200 from a broker as a fill.

## ADR-006 — Payment, subscription, and entitlement are different facts

**Status:** Accepted

**Context.** A user may pay Quantivo, pay a scanner directly, or be activated by an operator. Those events do not happen at the same time, and any one of them can be revoked alone.

**Decision.** `payment_transactions`, `scanner_subscriptions`, and `subscription_entitlements` are separate tables. Signal reads require an active entitlement joined to an active subscription. If the two disagree, access is denied. M1 activation writes the subscription and the entitlement and writes no payment. Catalogue ratings and subscriber counts are not stored.

**Consequences.** Reports and support can tell "they paid" from "they can see signals" from "the provider still considers them subscribed". The schema has a payment table before a payment provider exists, so the later integration does not overload the entitlement row.

**Rejected.** A single `is_subscribed` flag. Creating a successful payment row for development activation. Inventing subscriber counts.

## ADR-007 — Brokers and scanners stay behind ports, and secrets stay out of the schema

**Status:** Accepted

**Context.** The first real broker and the first real scanner are unknown. Their authentication lifetimes and order types will differ. Storing a token "temporarily" in the connection table is how secrets leak into backups and audits.

**Decision.** Domain code depends on a scanner port and a broker port. The Mani's sample adapter and the simulated broker are the M1 implementations. `broker_connections` stores status, an external account reference, and the last successful authentication time. It has no password, OTP, token, or API-secret column. A future adapter that must persist a credential uses a secret store and a reference, which will be its own decision.

**Consequences.** Tests can inspect the schema and fail if a secret-like column appears. The connection screen can be honest about a simulated session.

**Rejected.** A broker-specific order table as the core model. Copying a broker's login form into Quantivo.

## ADR-008 — One signal model, with staleness derived on read

**Status:** Accepted

**Context.** Scanners will send different payloads. Stored status goes stale if a job does not run. Duplicate webhooks are normal.

**Decision.** Ingestion maps every adapter into one normalized signal. Identity for deduplication is `(scanner_id, external_ref)`. A content hash ignores timestamps. The same hash is a no-op. A new hash revises the row and keeps `published_at`. Withdrawn, expired, and stale are derived when the signal is read. Only derived `active` is executable. Stale follows the horizon words. Same-day Intraday and BTST start at 30 minutes. Short term and long term start at 30 days. An admin saves those three clocks. Intraday to 7 days is not one of them. That horizon expires 7 days after the post.

**Consequences.** Restarting the API does not require a sweep before the list is correct. Revising a signal does not make it look newly published.

**Rejected.** One table per scanner. Persisting `stale` as a provider status. Updating `published_at` on every sync.

## ADR-009 — Quantity uses rupee risk, not capital allocation

**Status:** Accepted

**Context.** Traders often name a sum they will deploy and a smaller sum they will lose. Using the deployed sum as the risk numerator overstates size.

**Decision.** `quantity = floor(max risk INR / abs(trigger - stop))`, then round down to lot size and apply the optional quantity and exposure caps. The stop must sit on the losing side of the trigger. Maximum risk cannot exceed capital allocation. Capital allocation is stored and displayed and is not an input to the division. The server repeats the calculation at submit time. M1 does not pretend to have checked broker funds.

**Consequences.** The detail screen can show the formula in words. A client that sends its own quantity fails the check when the numbers differ.

**Rejected.** Quantity equals capital divided by price. Floating-point money. Trusting the quantity posted by the phone. Changing the quantity because the reward is larger or smaller. Risk-reward is defined in [ADR-020](#adr-020--risk-reward-is-shown-and-does-not-size-the-trade).

## ADR-010 — The broker is authoritative for facts, Quantivo for intent

**Status:** Accepted, with the broker side unimplemented

**Context.** Internal state and broker state will diverge after timeouts, missed webhooks, and restarts. Showing Quantivo's hope as if it were a fill would be worse than showing uncertainty.

**Decision.** `order_intents` record what the user asked for. `broker_orders`, `trade_executions`, and `position_snapshots` record what the broker reported. Snapshots are append-only facts. Reconciliation compares them. Until a broker can report anything, those tables exist and the order flow writes nothing to them. Unknown broker state fails closed.

**Consequences.** M3 has a place to put fills without migrating the meaning of the intent table. The UI must not show a stop as active until a broker order says so.

**Rejected.** One status column that means both "user confirmed" and "broker filled". Estimating a position from the intent when the broker cannot be reached.

## ADR-011 — Persist intent before submission, once submission exists

**Status:** Accepted for M3. Not implemented in M1

**Context.** The phone will retry. Webhooks will be delivered twice. A broker timeout does not mean the order is absent.

**Decision.** When submission is built, the intent and its idempotency key are committed before the adapter is called. A replay returns the existing intent. M1 keeps the key on the refusal audit and does not insert an intent, because there is no submission to make idempotent. A successful adapter response, later, still does not mean filled.

**Consequences.** M1 tests assert an empty order table after a refusal. M3 tests must assert exactly one intent for a repeated key.

**Rejected.** Creating an intent in M1 and marking it filled. Generating the idempotency key only on the client and trusting it without a unique constraint.

## ADR-012 — No job queue until a job needs durability

**Status:** Accepted

**Context.** Ingestion in the foundation is a synchronous, idempotent function. Notifications, webhook intake, and reconciliation are not built.

**Decision.** Do not add Celery, RQ, Redis, or a cloud queue in the foundation. When those jobs arrive, they must be durable, retry-safe, observable, and protected against duplicate processing. The worker shares the monolith's database and modules.

**Consequences.** The local stack stays Postgres plus the API. The reconciliation design is not an excuse to add infrastructure early.

**Rejected.** A queue with no consumers. In-memory background tasks for anything that must survive a restart.

## ADR-013 — India first, without a single-provider core

**Status:** Accepted

**Context.** The first workflow is Indian cash equities: `+91` numbers, INR, NSE and BSE, MIS and CNC. Other markets and brokers are expected later.

**Decision.** Validation and vocabulary start with that market. Provider codes, broker codes, exchanges, and products are data and adapter capabilities, not branches named after one vendor in the core. Product conversion is never implicit.

**Consequences.** A second broker adds an adapter and capability flags. It does not rename the order module. Phone validation will need a new decision before non-Indian numbers are accepted.

**Rejected.** Hard-coding one scanner's JSON as the signal schema. Assuming every broker supports bracket orders.

## ADR-014 — Decimal money

**Status:** Accepted

**Context.** Equity prices and rupee risk are exact at paise. Binary floating point is the wrong tool, and an integer paise convention is easy to mix with rupees.

**Decision.** Python uses `Decimal`. PostgreSQL uses `numeric`. API money fields are decimal strings. Quantity is an integer. Display rounding for the foundation is two decimal places.

**Consequences.** Tests can assert `27` shares and `486.00` INR of risk without float noise.

**Rejected.** `float` prices. Sending numbers as JSON floats.

## ADR-015 — Fail closed

**Status:** Accepted

**Context.** The dangerous failures in this product are silent ones: an old signal traded, an unknown broker state shown as flat, a protective order shown as working.

**Decision.** Non-active signals are not executable. Risk that cannot produce a legal quantity yields no order. A missing entitlement hides the signal. A missing broker connection stops the request before the trading gate. Unconfirmed protection, once protection exists, is shown as unprotected. Client errors use a stable code and a short message.

**Consequences.** The UI has to show warnings rather than disabling the warning to make the happy path cleaner. Operators will see refusals in the audit log. That is the point.

**Rejected.** Best-effort submission. Defaulting unknown order state to filled or to cancelled.

## ADR-016 — Admin is another client, and it cannot see secrets

**Status:** Accepted, deferred to M4

**Context.** Operators need support tools. Those tools are a common way for a trading platform to over-expose broker sessions.

**Decision.** The admin portal is a separate Next.js client of the same API. Admin permissions are seeded and unused until that milestone. Admin queries read users, providers, entitlements, and audit events. They do not have a path to broker secrets, because the schema does not keep them. Signal statistics and user execution statistics stay separate queries.

**Consequences.** M1 does not build a half-finished admin UI. The role table is real so the later portal does not invent a second account system.

**Rejected.** A staff flag on the user row. Reusing the trader's mobile screens for administration.

## ADR-017 — Fictional market data only

**Status:** Amended by ADR-023. Sample rows and the ban on invented ratings still stand. The provider is no longer a fictional firm named Apex.

**Context.** No scanner or market-data contract is in place. Scraping a private terminal would be both legally and operationally unacceptable.

**Decision.** Sample symbols are used so the screens are readable before the Telegram worker is connected. Copy in the catalogue says the signals are not market recommendations. No live quote, return, or win rate is shown.

**Consequences.** The feed status says `mock`. A later real provider is a new adapter plus a licence check, not a replacement of the signal table.

**Rejected.** Calling a public quote API and presenting it as a scanner signal. Hard-coded performance numbers in the catalogue.

## ADR-018 — Fixed broker egress, first on Lightsail

**Status:** Accepted. Read-only market quotes are amended by ADR-030.

**Context.** The first real broker is expected to allow order traffic only from a pre-registered source address. The pilot does not need multi-zone autoscaling. A later deployment must serve users across India, hundreds of scanners, and more than one broker without giving every application replica its own whitelist entry.

**Decision.** Development has no broker egress. The first production deployment is Amazon Lightsail in Mumbai: a load balancer for TLS, one instance with a static IP, and a private managed PostgreSQL database. Broker, SMS, and scanner calls leave through that static IP. The scale deployment keeps the monolith and moves the stable address to one Elastic IP per broker, used only by that broker's gateway tasks. API replicas scale behind a load balancer in `ap-south-1` and do not call brokers directly. Details and diagrams are in [DEPLOYMENT.md](DEPLOYMENT.md).

**Consequences.** The pilot has a single availability zone and a single egress address. A broker that requires an exclusive second IP, or user volume that exceeds a vertical resize, is the point to leave Lightsail. The phone never uses the whitelisted address.

**Rejected.** Running the pilot on a home or office connection. Putting a public IP on every future API task. One microservice per broker in order to get a static IP.

## ADR-019 — Mani Telegram channel is the first scanner adapter

**Status:** Accepted

**Context.** The Quantivo AI app already has a Mani tab. A Telethon user session polls one provider channel, a deterministic parser extracts buy-above, stop, and targets, and the UI reads stored calls. The HTTP handler does not call Telegram. The same shape is what the scanner port requires. The session file is a long-lived credential, and Telethon cannot share one session across many API processes.

**Decision.** The first production feed is this adapter, deployed as one worker on the Lightsail instance. Channel id plus message id is the signal `external_ref`. The parser, the NSE name match, and the 09:15–15:30 IST accept window stay inside the adapter. A call that already names the buy and is missing the stop or a target may take those fields from the immediate next message, the following message id sent within 10 minutes. That call is stored under the first message. The next message is left alone when it is a separate call, names another stock, or carries a different horizon. The API serves the normalized signals to entitled users. Suggested order quantity uses the platform risk formula. Capital divided by buy-above is not an order quantity. Unmatched names are not executable. The session file, `api_id`, and `api_hash` stay on the worker. Deployment detail is in [DEPLOYMENT.md](DEPLOYMENT.md).

**Consequences.** The pilot depends on one platform Telegram login remaining a member of the channel and authorized. Losing that session stops new calls until an operator signs in again. Scaling the API does not scale Telegram readers. Live prices are not part of this adapter. A last traded price is a separate Fyers read, in ADR-030. On a weekday from 09:15 to 15:30 IST the worker checks the channel about every 5 seconds. Outside that window it checks about once a minute. Home reads the stored calls again every 5 seconds while the list is open, and leaves the rows on screen during that read. The same read includes LTP from one Fyers data socket when a Fyers app is configured. A symbol with no recent tick reuses a quote for up to a minute.

**Rejected.** Polling Telegram from the mobile app or from every API replica. Treating the channel text as the core signal schema. Using the capital-divided-by-price count as the quantity that can be submitted.

## ADR-020 — Risk-reward is shown and does not size the trade

**Status:** Accepted

**Context.** A call has a trigger, a stop, and one or more targets. The distance to the target tells the trader whether the call is attractive. The distance to the stop tells Quantivo how many shares or lots keep the loss inside the profile.

**Decision.** Risk is the absolute distance from the trigger to the stop. Reward for a target is the absolute distance from the trigger to that target. Risk-reward is reward divided by risk. The detail screen may show it. Quantity stays the ADR-009 calculation. A better reward does not increase the quantity. A worse reward does not reduce it. The trader skips the call instead. If the broker fills at a price other than the trigger, the realized risk-reward is measured from that fill, not from the original trigger.

**Consequences.** Targets remain provider data. They are required for a call to be understandable, and they are not read by the quantity function.

**Rejected.** Sizing up high risk-reward calls. Hiding calls below a fixed risk-reward cutoff. Using the live price as the entry when the signal still has its own trigger and no fill exists.

## ADR-021 — One feed, segment filters, and horizon channels

**Status:** Superseded in part by ADR-022. Segment filters and lot-size quantity still stand. Horizon is no longer a channel, and registration is no longer per horizon.

**Context.** A scanner provider can publish equity, F&O, and commodity, and can run a separate Telegram channel for each time horizon. The trader who already uses that provider wants those calls together. A channel they have not paid for or otherwise registered for must not leak into the list. The earlier desk layout, with a tab per strategy name, is not this product.

**Decision.** Home is one scanner. Market segment is a property of the signal: equity, F&O, or commodity. The feed opens on All. Equity, F&O, and Commodity are filters on that list. The last segment filter is remembered on the device. Segment is not an entitlement.

Horizon is a channel under the scanner. The review labels are Intraday to 7 days, Short term, Swing, and Long term. Intraday to 7 days, Short term, and Long term are the horizons the existing call parser already names. Swing is the fourth label used in the review. A provider's real channel list may replace any label. Each channel has its own registration under the scanner entitlement. All shows only registered channels and names the ones left out. Choosing an unregistered channel shows that the user is not registered and shows no calls from it. Registering for a channel uses the same entitlement methods as scanner activation. It does not create a payment by itself.

F&O and commodity quantity uses the contract lot. If one lot would lose more than the maximum rupee risk, the quantity is none and the screen says why.

**Consequences.** Scanner activation alone is not enough when that scanner has more than one channel. A one-channel scanner, including the current Mani's sample until channels are added, still has a single grant and behaves as the original entitlement rule. The signal row needs a segment and a horizon so the filters are not guessed from the symbol. The M1 runnable slice may ship with one horizon populated. The home screen still has to be able to grow into this layout without a second feed model.

**Rejected.** A separate app or a separate scanner sign-up for each segment. Permanent tabs that hide a new call in another segment with no All view. Showing unregistered channel text and blocking only the order button. One risk profile per segment in the first version. Reusing the other product's strategy desks as the navigation.

## ADR-022 — A channel owns its horizon words

**Status:** Accepted. Replaces the horizon-as-channel part of ADR-021.

**Context.** Mani's Equity tab reads one Telegram channel. Posts in that channel carry their own horizon line, such as "Intraday to 7 days" or "Short term". The provider also has other Telegram channels for F&O and commodity. Those channels do not reuse the Equity wording. One of them may say only "Intraday". The Equity parser today maps any line containing "intraday" to a single code, and the Equity screen then fuzzy-matches labels onto three global names. That is safe only while one channel exists. A second channel would make "Intraday" and "Intraday to 7 days" look like the same horizon.

**Decision.** Registration is per source channel. For this provider the channels are the Equity channel, the F&O channel, and the commodity channel. A channel the user is not registered for shows that fact and no calls. Horizon is not a registration.

Each call stores the horizon words as written. Alias rules live on that channel's adapter and apply only there. The Equity adapter may treat "Intraday to 7 days" and its known typos as one chip on the Equity channel. It must not claim that the F&O channel's "Intraday" is the same chip. Wording that the channel's alias list does not name stays as its own chip, using the original words. Calls are not dropped because the horizon is unfamiliar.

The home screen does not add a horizon tab row. Each call shows the horizon words under the symbol, next to its channel. "Intraday to 7 days" on Equity and "Intraday" on F&O stay different because they are stored as different text, not because the screen offers two chips to merge.

A later cross-channel family, such as "show every intraday-style call", is an explicit map written when the channel is added. It is not a fuzzy match across channels, and it is not required for the first feed.

**Consequences.** The Equity parser's global "intraday means intraday to 7 days" rule stays inside the Equity adapter if that channel really means that. It does not become a platform enum. The signal stores the raw horizon and the channel. Segment still follows the channel: the Equity channel is equity. ADR-021's segment filter and the one-lot quantity rule are unchanged.

**Rejected.** One global horizon list for every channel. Fuzzy-matching "Intraday" to "Intraday to 7 days" across channels. Registering the user for a horizon instead of for a channel. Hiding a call whose horizon text is new.

## ADR-023 — Mani's is the first scanner

**Status:** Accepted. Amends ADR-017.

**Context.** The review used a fictional provider named Apex so the screens could be read before a real feed existed. The first scanner to integrate is Mani's, the Telegram channel already read by the other Quantivo app. Keeping both names would make the catalogue and the pilot look like two providers.

**Decision.** The catalogue provider is Mani's. The scanner the trader opens is Mani's Channel. There is no Apex provider. Development still needs a feed that does not call Telegram, so the in-process sample uses the Mani's name and is labeled as sample data. The Telegram worker, when connected, writes into that same scanner. It does not introduce a second provider.

**Consequences.** Seed data, the review screen, and the M1 adapter use Mani's. Sample rows remain sample data until the worker is connected. Ratings and returns stay omitted.

**Rejected.** Leaving Apex in the catalogue beside Mani's. Calling Mani's a fictional firm.

## ADR-024 — A channel feed is configured, and the reader stays an adapter

**Status:** Accepted.

**Context.** Mani's Equity posts can be read from Telegram. Another scanner may publish through a direct HTTP API, or through a source that does not exist yet. The operator has to choose the source per channel. The other Quantivo app already parses the Equity channel, but its tables, its quantity formula, and its Telegram login belong to that app.

**Decision.** Each source channel has one feed row. The kind is `none`, `telegram`, or `http_api`. The options stored for that kind are not the same:

- `none` has no options. The development sample remains the feed.
- `telegram` stores the channel id, the parser name, and a poll limit. The only parser now is `equity_calls`, and it is allowed only on an equity channel. The operator enters the channel name. The API resolves it to the id of a chat the worker login has already joined. `api_id`, `api_hash`, and the session file stay in the worker environment.
- `http_api` stores the URL, `GET`, a poll interval, and the name of an environment variable that holds a secret. The secret value is not stored. A PDL Sweep body is read by ADR-033. Any other body is saved and skipped.

An operator with `admin.feeds.write` changes the row through the API. The change is audited without the secret and without the URL's userinfo. A trader cannot call that API. The same phone sign-in is used; `python -m app.grant_admin` attaches the admin role after the person has signed in once. That admin then sees Admin configuration in the signed-in app. The screen sets each channel and shows whether the one worker Telegram login is present. It does not collect that login. The broader Next.js admin portal is still a later client of this API.

The Equity parser writes the existing signal shape. Horizon words stay as published. The worker resolves a posted name against a cached copy of the public NSE cash list: an exact ticker, then the company-name words, then one clear spelling. A channel spelling such as `Aegies Logistics` maps to its ticker. A former ticker that NSE has renamed, such as `LTIM`, is stored as the current listing `LTM` when that listing is in the cash list. The stored symbol is that NSE ticker. A name that matches none or more than one symbol is stored as written and is not executable. The list is cached on this worker. It is not read from the other Quantivo project. Posts outside weekdays 09:15–15:30 IST are ignored. The worker polls only channels whose feed kind is `telegram` and whose status is active, and only when this worker's own login is present.

**Consequences.** Choosing Telegram hides the sample calls. The worker walks that channel's history once, then keeps reading new posts. Until this machine has its own login, the list says the login is missing and does not fall back to the sample. An HTTP feed that is not a PDL Sweep body is saved and is not turned into calls. F&O and commodity still need their own parsers before a Telegram id can be saved on those channels.

**Rejected.** Copying the other app's tables, session file, or `api_hash` into this project. Connecting to that project's database or API as the feed. One set of options for every source kind. Storing an API secret in `source_feeds`.

## ADR-025 — Admin adds a channel; the trader switches the ones they registered

**Status:** Accepted.

**Context.** The catalogue started with one Equity channel. The operator needs to add F&O or commodity, or a second equity chat, without a code change. The trader then needs to move between the channels they registered for, and to see those calls in one list.

**Decision.** Admin configuration can add a source channel. The operator enters the channel name and the segment (`equity`, `fno`, or `commodity`). The server stores a unique code and a feed of kind `none`. The channel name can be renamed later on that channel's card. The Telegram chat stays a separate field and is resolved to the id of a joined chat. `equity_calls` remains available only on an equity segment.

A new channel starts with no registrations. While a scanner has one channel and the trader has no registration row, the scanner entitlement still shows that channel. Adding a second channel writes a registration for the channel that already existed, for each trader who already has the scanner entitlement, so those calls stay visible. The new channel stays hidden until that trader registers. Registration does not create a payment.

The home row is All, then each source channel by its display name. All is the calls from registered channels, and it names the channels left out. Opening an unregistered channel says the trader is not registered and shows no calls. A segment chip is not the channel: two equity channels would be two names.

**Consequences.** The phone Admin screen is where a channel is added, renamed, stopped, or deleted. Stopping a feed asks first: new posts are not stored, and the channel and its calls stay. Deleting asks first and names how many stored calls will go with the channel. A channel that has an order record is not deleted. The trader registers from the channel they opened. Leaving a channel hides its calls from All.

**Rejected.** Auto-registering every new channel. Using Equity / F&O / Commodity as the only switch once two channels share a segment. Treating the Telegram chat title as the stored channel name.

## ADR-027 — An operator adds a scanner, then its channels

**Status:** Accepted.

**Context.** The catalogue row is a provider and a scanner, and a scanner owns source channels. The seed creates one of each: Mani's, and Mani's Channel, with the Equity channel under it. Admin could add another channel, and that channel was always stored on Mani's Channel. A second provider had nowhere to go.

**Decision.** Admin configuration is one card per scanner. The card adds nothing by itself: Add a scanner asks for a provider name, a scanner name, and the description traders see under the name. The same provider name adds another scanner under that provider. The card then edits the provider name, the scanner name, and the description shown on the catalogue, and can delete the scanner. Renaming a provider renames it for every scanner from that publisher. Naming an existing provider moves this scanner under that provider. The scanner code stays, unless that move would duplicate a code. Price, rating, and subscriber count stay empty. The scanner starts with no channels. Its channels are added, renamed, and deleted on the same card. When more than one scanner is active, a channel is not stored unless that scanner is chosen. Deleting a scanner deletes its channels. A channel with an order record keeps the channel and the scanner. On Scanners, an operator sees Manage, which opens this catalogue. Home opens the scanner the trader last opened. The menu returns to that scanner. One scanner's channels are not listed on another scanner. The worker still uses one Telegram login for every Telegram channel.

**Consequences.** Mani's Channel remains the seeded scanner. A later provider is a catalogue row, not a code change. `equity_calls` remains available only on an equity channel, whichever scanner that channel belongs to.

**Rejected.** A second seeded provider. Putting every new channel on Mani's Channel. Inventing a price or a rating for a scanner the operator just added.

## ADR-028 — Home switches a held scanner in one tap

**Status:** Accepted.

**Context.** A trader can hold more than one scanner, and each scanner has its own channels. Reaching another scanner meant opening the navigation list, then Scanners, then Open feed.

**Decision.** Home shows the scanners the trader has activated as the title, and only when there are two or more. The row scrolls sideways. The selected name is larger and underlined. One tap opens that scanner, resets the channel to All, and shows that scanner's channels underneath. Channel names use text tabs under the title. The last opened scanner is the one Home returns to. A scanner that is not activated is not in the row. One held scanner keeps its name as the title.

**Consequences.** The channel tabs always belong to the scanner that is open. With one held scanner the scanner row is absent.

**Rejected.** Putting every catalogue scanner in the row. A second trip through the Scanners screen for a scanner the trader already holds. Rounded rectangles for the scanner and channel switch.

## ADR-029 — The call mark is the price path, with the minute on the chip

**Status:** Accepted.

**Context.** A trader watches a live call and needs the minute to enter and the minute to exit. Entry is a one-minute candle that closed through the trigger inside the window. A stop or a target is a touch. The last traded price is not that path.

**Decision.** The mark is generated from [FLOWCHARTS.md](../FLOWCHARTS.md). A status word stored on the signal is not an input, including a word brought in with older data. No NSE, Expired, and Stale come from the match and the clocks. Waiting and Window over remain until the one-minute bars for that NSE cash call have been read. Those bars come from the configured Fyers app, for actionable NSE cash calls, and they are not stored on the signal. Finished minutes are saved apart from the signal, and a day already saved is not read again. Entry, Caution, Not valid, T1 trail, T2 trail, Final, and Stop replace the clock mark once the bars cover the path. The row chip is a short pill: a 6px dot and a 13px label, such as `Entry 10:05` or `T1 trail 10:31`. The explanation sentence is on the call, under the pill. Waiting and Final are green. Entry is a deeper green. A lighter green is a trail. Stone is Window over, Checking, and Not valid. Amber is Caution and Stale. Red is Stop. Expired is a warm neutral. Plain is No NSE. The exact words and colours are in [FLOWCHARTS.md](../FLOWCHARTS.md). Not valid, Caution, a trail, Final, and Stop leave Actionable and are not executable. A last price already through a target or the stop leaves Actionable and the pill says Final, a trail, or Stop, with no minute, until the bars name that minute, and it is not executable. A bar that touches the stop and a target does not choose. A stop touch before a close through the trigger does not become Entry. Quantity does not change.

**Consequences.** A fresh call says Waiting before the first bars are in. After the window, before the bars are in, it says Window over. It does not say Not valid, and it does not say Entry, until the bars have been read. A missing Fyers app leaves the clock mark and does not invent a time. The list keeps reading stored calls every 5 seconds. History for a symbol is filled in the background, a few days at a time, so that read stays short.

**Rejected.** Showing a migrated Withdrawn or Expired word. Copying another app's quote session to invent Entry and Not valid. Treating the last traded price as the entry. Hiding a call because the window has ended. Guessing an exit when one bar hits the stop and a target.

## ADR-026 — The phone menu is the way between screens

**Status:** Accepted.

**Context.** The call list had grown into the only screen. Admin and sign out sat under the calls. A second provider would have had nowhere to appear except by replacing Mani's in that title.

**Decision.** A signed-in phone shows a hamburger at the top left, with no caption. The control opens Home, Scanners, Orders, Account, and Admin when the signed-in person is an operator. Orders lists the saved intents for that trader. Those names appear only in the opened list. On Home, when more than one scanner is held, those names replace the title and scroll sideways. On a call, the same place shows a back arrow to the list and the title is the symbol. Scanners lists the catalogue, one card per provider, with that scanner's channels. Home is the call list for the active scanner. A call is one compact row: symbol and side, quantity, horizon and channel, trigger, stop, and the targets. The final target is Last. T2 is shown only when a price sits between the first target and the last. The type stays large and the ink stays dark. The review phone uses the same control. The desktop review keeps the side list.

**Consequences.** Admin is not a link at the bottom of the calls. A new provider appears on Scanners when it is in the catalogue. The call list does not spend a card on each row. Home chooses Actionable or All with one short bar. The Actionable side shows how many calls are on that list. The closed-call count sits in the All side. Actionable hides a stale, expired, or unmatched call, and a call that has touched the first target or the stop. A last price already through either level leaves too. All includes those calls. A call can say Window over and stay in Actionable when its horizon is still open.

**Rejected.** A vertical overflow icon for navigation. A caption on the hamburger. A list of unlabeled icons. A bottom bar and a menu both showing the same four places. Hard-coding Mani's as the only scanner on the navigation screen.

## ADR-030 — Last traded price is a labeled Fyers quote

**Status:** Accepted.

**Context.** A trader wants the last traded price next to a call. The other desk reads quotes from its own broker session. This app already resolves NSE cash names from the public Fyers symbol file, so the quote symbol is the same `NSE:SYMBOL-SERIES` form. ADR-017 still forbids presenting a quote as the scanner's call. ADR-018 keeps order traffic off this machine. ADR-029 refuses to treat the last price as an entry.

**Decision.** The API reads last traded price from Fyers when `FYERS_APP_ID` and `FYERS_ACCESS_TOKEN` are both set. One Data Socket in this process carries the full symbol update, including the move against the previous close, for the actionable NSE cash names. Home still reads the list every 5 seconds and shows that cached price. A symbol with no tick for 30 seconds falls back to the quote call, batched 50 at a time and reused for 60 seconds. A socket price is kept only when a quote for that symbol is already in this process and the tick is within 25 percent of that quote. Any other tick is ignored and is not folded into the minute. During the cash session the phone labels it LTP. After the close, and on a weekend, the label is Last LTP. The label is on every NSE cash row and on the call, with an em dash when no price has been read. The price is green when it is above the previous close and red when it is below, with that percent beside it. A price without the change stays in the body ink. All does not send a closed call to Fyers. Opening one call can still read that symbol. A chart icon on the row and on the call opens the session candles. The back arrow returns to the screen that opened the chart. The default is 5 minutes, and 1 minute is the same bars. Five-minute candles are five of those one-minute bars, aligned to 09:15. The horizontal axis shows the bar time in IST. The price scale is on the right and the chart opens on the latest candle. Dragging the chart moves through the session. Dragging the price scale changes the candle height. Dragging the time scale, or the wheel, fits more candles in the view. The crosshair shows that bar's time and price. A weekend chart uses the previous weekday. Finished one-minute bars are saved in their own table. They are not a column on the signal, and a saved last price is not used to draw them. A day already saved is not read again. The minute still forming stays in memory and is filled from the data socket. A missing day is read once. A finished mark is not read again. Quotes and History share one process budget: 5 a second, 50 a minute, and 5,000 a day, with room left in the minute for a quote. A rate limit pauses both and keeps bars already stored. Prepare order on the chart is the same refusal as on the call. An admin saves the Fyers app id, app secret, and PIN once on Admin configuration, registers the callback URL on that Fyers app, and signs in on the Fyers page. Quantivo does not ask for the Fyers password. The API stores the app secret, the PIN, the access token, and the refresh token in the server environment file and the running process. It does not put them in a table, return them after saving, or write them into the audit payload. The access token still ends at 6:30 AM IST. ADR-033 signs in again with a TOTP key saved once. The socket reconnects with that token. A browser sign-in remains when that key is absent. A trader cannot call that API. F&O and commodity are not quoted and have no chart. Zerodha is a later adapter behind the same quote read. The price does not change quantity, the guide chip, or whether the call can be sent.

**Consequences.** This is the one development call to a broker host, and it is read-only. Orders stay refused. A Fyers access token expires at 6:30 AM IST. Fyers disabled the refresh-token call, so the server signs in with a TOTP key and PIN saved once on Admin. A failed sign-in waits 15 minutes before trying again. Until the app is saved, Home says the last traded price needs a Fyers app. The review screen's LTP figures are samples for the layout. The budget counts only this process. Another program on the same Fyers account shares the real allowance. The account is on Fyers Prime, so this process allows 10 calls a second, 500 a minute, and 500,000 a day. History may use 450 of each minute. A restart reads a missing day, or the unfinished part of today, once under the same budget. A day already saved is not read again.

**Rejected.** Copying another project's quote session. Treating LTP as the trigger or as Entry. Hiding a call because the quote failed. Putting the access token in Postgres. Returning the access token to the phone after it is saved. Asking the admin for the Fyers password. Pasting a new access token every morning. Calling Zerodha before a Kite app exists. Quoting from the phone.

## ADR-033 — Fyers quotes sign in each morning with a saved TOTP key

**Status:** Accepted.

**Context.** Fyers ends an access token at 6:30 AM IST. The refresh-token API now returns code -16 because SEBI requires a daily two-factor login. An admin cannot open the Fyers page every morning.

**Decision.** Admin saves the Fyers client id and the external TOTP key once, beside the PIN. After 6:30 AM the server creates the TOTP code, completes the Fyers login, and stores the new access token in the environment file. The key is not written to a table, a log, or an audit payload. A browser sign-in remains when that key is absent. A refused login is not retried for 15 minutes.

**Rejected.** Calling the disabled refresh-token API every morning. Asking an admin to sign in by hand after every 6:30 AM. Putting the TOTP key in Postgres.

## ADR-031 — A Zerodha session is the trader's Kite login, and it ends at 6:00 AM IST

**Status:** Accepted.

**Context.** Trading uses the trader's own Zerodha account. Fyers quotes stay a single server app. Kite Connect gives each login an access token and an empty refresh token. Zerodha's own description is that the token lasts until the next 6:00 AM IST flush, and a person has to sign in by hand at least once a day. A logout on Kite ends it sooner. The request token on the redirect lasts a few minutes.

**Decision.** An operator saves one Kite Connect api key and api secret on Admin configuration. Those values stay in the server environment file. A trader signs in on Zerodha from Account. The redirect exchanges the request token on the server. The access token is written under `.quantivo/secrets/zerodha/` for that user and is not returned to the phone, stored in a table, or written into the audit payload. `broker_connections` records `zerodha`, the Zerodha client id, and the sign-in time. The session is connected until the next 06:00 IST after that sign-in. A sign-in at 06:00 lasts until the next morning. After 06:00 the account says the session ended. This build does not send an order.

**Consequences.** Quotes still come from Fyers. A connected Zerodha session does not place, modify, or cancel an order. The phone shows the 6:00 AM limit on Account. Changing or removing the Kite app clears the stored sessions.

**Rejected.** Asking the trader for the Kite api secret. Putting the access token in Postgres. Refreshing the session without a sign-in. Treating the session as a rolling 24 hours from login. Sending an order while live trading is off.

## ADR-032 — A confirmation stores one intent and does not call Zerodha

**Status:** Accepted.

**Context.** The trader should be able to accept a call in two taps, with the call's prices already filled in, and change those prices when they want to. The order still cannot leave this machine. Zerodha rejects an order that does not come from a registered static IP, and live trading stays off until that path is reviewed.

**Decision.** Buy and Sell open a ticket filled from the call. The product starts as MIS, and the trader may change it to CNC. The trader may also edit the trigger, stop, and targets. The server recalculates quantity from the trigger and the stop and rejects a different quantity. Confirm writes one `proposed` intent for that trader and call, including the prices they confirmed. The same confirmation key returns that row. An unsent intent is updated when they confirm different prices. No broker order is written, and the stop and targets are not shown as active. An operator can delete a proposed intent that has no broker order. The delete asks first and is audited. The call stays. An intent that was sent is not deleted.

**Consequences.** The phone says the order was saved and that Zerodha was not sent it. Orders lists those saved intents for the signed-in trader, newest first, with the status. Admin lists every unsent proposed intent and can remove one. The same delete is on Orders when the signed-in person is an operator. A fill, an active stop, and a real Kite order wait for the reviewed broker path.

**Rejected.** Sending the order to Zerodha from the developer machine. Marking the stop active before a broker confirms it. Letting the phone choose a quantity other than the server's figure. Creating a second intent when the same confirmation is tapped twice.

## ADR-033 — PDL Sweep is read from the other app's live URL

**Status:** Accepted.

**Context.** Quantivo_AI already answers `GET /api/watchlist/pdl-sweep/live` with today's rows and a history list. Each today row has a symbol, LONG or SHORT, an entry, a stop, and one target. It does not send a horizon word. This app's Intraday clock for Mani's channel is 30 minutes. That clock must not apply to this desk.

**Decision.** The worker GETs an active `http_api` feed on its poll interval. Both `today` and `history` are stored. The horizon is `Intraday` unless the row includes `horizon`. LONG is BUY and SHORT is SELL. Entry, stop, and target are the trigger, the stop, and one target. The identity is the symbol, the trade date, and the signal time. An Intraday or BTST row from this feed stays on Actionable through its IST trade date, including after 15:30. The next IST date puts it on All. The desk does not send a status word. A target-hit time is Final at that time, and that row stays on Actionable while the trade date is still today. With no target-hit time the pill is Open while the trade date is today, and Expired once that date has passed. The desk does not send a stop-hit time, so Stop is not taken from this payload. These rows are quoted on All as well as on Actionable. When the row sends stars, the list shows that 1 to 5 mark. The hint is the hit rate and the 7-day count from the same row. A row without stars shows none. The one-minute bar marks are not used for this feed. It does not use the 30-minute Intraday clock. A horizon the payload sends later, such as Short term, uses that horizon's existing clock. The secret, when the feed names an environment variable, is sent as a bearer token and is not stored. Quantity stays `floor(maximum rupee risk / abs(trigger - stop))`.

**Consequences.** On one laptop the URL is `http://127.0.0.1:8000/api/watchlist/pdl-sweep/live`. In the cloud the same channel keeps that path and changes the host. Mani's Intraday calls still go stale at their own clock.

**Rejected.** Copying the other app's database. Treating this Intraday as Mani's 30-minute Intraday. Storing the history list as Actionable calls. Copying the desk's last price onto the call. Inventing a star rating the payload did not send.
