# Quantivo architecture

This directory is the architecture baseline for the rest of the build. Implementation continues only against these documents.

| Document | What it answers |
| --- | --- |
| [Product requirements](../REQUIREMENTS.md) | Who the product serves, what it must do, and how that work is split across milestones |
| [Architecture overview](OVERVIEW.md) | Shape of the system and the runtime view |
| [System context](SYSTEM_CONTEXT.md) | Quantivo, its users, and the external parties it must not absorb |
| [Component model](COMPONENTS.md) | Module boundaries inside the API and the clients |
| [Data flow](DATA_FLOW.md) | How identity, signals, entitlements, and orders move through the system |
| [Business processes](BUSINESS_PROCESSES.md) | Sign-in, scanner activation, and trade review as the user experiences them |
| [Domain model](DOMAIN_MODEL.md) | Entities, relationships, and the constraints that protect them |
| [Data architecture](DATA_ARCHITECTURE.md) | Logical model, physical tables, column definitions, and where each row comes from |
| [Decisions](DECISIONS.md) | Critical decisions, why they were taken, and what was rejected |
| [Deployment](DEPLOYMENT.md) | Development, the Lightsail pilot, and the later India-scale network |
| [Implementation plan](../IMPLEMENTATION.md) | Phase 1 through Phase 5, what is done, and what is next |

## How to read the diagrams

Solid arrows are part of the foundation being built now. Dashed arrows are specified and intentionally not built yet. External parties stay outside Quantivo even when a later milestone integrates with them.

## Current repository state

The workspace started empty. A partial Python API skeleton exists under `backend/`. It is not the completed foundation:

- The Phase 1 migration is generated and the API tests pass.
- The Expo application under `mobile/` signs in, lists Mani's sample calls, and opens one signal.
- Feed settings for each source channel are in the API, and an admin sees them on Admin configuration after signing in. The Equity parser and a Telegram worker command are in the repo. The worker does not poll until this machine has its own Telegram login. The HTTP reader, the broader admin portal, the payment provider, the real broker, and push notifications are not implemented.

A review screen lives at `mockup/quantivo-mobile.html`. It is a way to check layout and copy. It is not a running client, and numbers typed there are not saved.

Treat the documents as the source of intent. Treat the code as an incomplete draft that must be brought in line with them. When a review changes behavior, update the requirements, the decisions, and the implementation plan in the same pass as the mockup.
