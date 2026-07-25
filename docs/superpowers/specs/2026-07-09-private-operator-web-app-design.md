# Private Operator Web App Design

## Purpose

This design defines the first real website product for the Synthetic Indices system: a private operator web app that gives the user a polished browser-based control surface for `R_75` and `R_100` calls while keeping the existing Python engine as the source of truth.

Version 1 is intentionally local-bridge-first:

- the browser becomes the main operator interface
- the current Python trading system remains the decision engine
- a backend bridge translates browser actions into structured engine calls
- the frontend API contract is designed so the backend can later move to fully hosted infrastructure with minimal frontend rewrite

## External Context

The implementation target repo provided by the user is:

- `https://github.com/MitemsHub/mitemshub-indices`

Current observed state:

- the repository is empty

This is acceptable for version 1 because it allows the app structure to be created cleanly around the product requirements instead of inheriting unrelated code.

The user also provided:

- `https://github.com/MitemsHub/mitems-studio-os`

This repo should be treated as the website quality and design operations reference. Its structure indicates an opinionated studio system covering:

- constitution and product discovery
- design philosophy, typography, spacing, layout, motion, and component systems
- React, Next.js, TypeScript, Tailwind, API design, architecture, testing, deployment, and QA guidance

For this project, `mitems-studio-os` is not the engine repo. It is the design and engineering standard the app should align to.

## Scope

This design covers:

1. The product shape of the private operator web app.
2. The version 1 architecture using a local backend bridge in front of the existing Python engine.
3. The UI structure for fresh `R_75` and `R_100` call requests.
4. The account-mode toggle behavior for `Own Account` versus `Prop Firm`.
5. The API contract between frontend and bridge.
6. The relationship between the trading engine repo and the website repo.
7. The future migration path from local bridge to hosted backend.
8. The quality bar and design standards inherited from `mitems-studio-os`.

## Non-Goals

- Direct broker execution from the website in version 1.
- Public marketing site or public dashboard in version 1.
- Multi-user SaaS, subscriptions, or customer account management.
- Full MT5-hosted execution infrastructure in version 1.
- Rewriting the existing Python engine before the web product exists.
- Building an AI chat gimmick instead of a disciplined operator interface.

## Current Problem

The system now has meaningful operator value, but the interface is still CLI-first:

- `live-watch` gives the live call stream
- `live-watch-review` gives post-hoc review and transport visibility
- MT5 readiness and rollout tooling already exist

This is powerful, but not yet the right long-term product surface for a human operator who wants:

- a stable browser-based interface
- symbol buttons for `R_75` and `R_100`
- structured manual trade instructions
- recent call context and system health in one place
- a clean future path to hosted infrastructure

## Design Goals

- Build a serious private operator product now, not a throwaway dashboard.
- Keep the current Python engine as the decision source of truth.
- Introduce a backend bridge so the browser never depends on raw CLI text.
- Make the frontend stable across future infrastructure upgrades.
- Design for future scale without forcing full hosting complexity immediately.
- Use `mitems-studio-os` as the style and engineering quality baseline.
- Avoid generic SaaS visual language and avoid overbuilt widget clutter.
- Allow the operator to switch between own-account behavior and prop-firm-safe behavior without changing the underlying market engine.

## Approaches Considered

### Option 1: Fully Hosted Backend Immediately

Build the website and also host the backend from day one.

Pros:

- clean deployment story
- public internet-ready architecture from the start
- fewer future infra transitions

Cons:

- adds hosting and ops complexity too early
- creates pressure to solve infrastructure before the product surface is proven
- complicates the path if future MT5-capable workloads require different hosting choices

### Option 2: Local Backend Bridge First

Build the website now, but place a lightweight backend bridge between the browser and the existing local Python engine.

Pros:

- fastest path to a real operator product
- keeps the frontend architecture clean
- lets the engine remain the source of truth
- creates a stable API contract for later hosting
- reduces rewrite risk

Cons:

- version 1 is not fully cloud-hosted
- deployment is less turnkey than a static site

### Option 3: Static Dashboard First

Build only a visual frontend using saved data or mock results.

Pros:

- fastest visual progress
- easiest hosting story

Cons:

- does not satisfy the actual need for fresh-call runs
- creates a fake product
- likely requires major rework later

## Selected Approach

Use Option 2: local backend bridge first.

This gives the user the correct product boundary immediately:

- the frontend is a real application
- the backend bridge is the browser-facing runtime
- the existing Python engine remains the decision system

Later, the backend bridge can be reimplemented or relocated behind hosted infrastructure without forcing the frontend to be redesigned.

## Product Type

The website is a:

- private operator app

It is not:

- a public landing page
- a public analytics dashboard
- a copy-trading platform
- a broker-execution website in version 1

## Version 1 Architecture

### Three Layers

Version 1 should be built as three clear layers:

1. `Frontend app`
   - browser-based private operator interface
   - built in the website repo
   - responsible only for UX, rendering, and API consumption

2. `Backend bridge`
   - receives frontend requests
   - runs a fresh call request for `R_75` or `R_100`
   - reads review/history/system data
   - normalizes outputs into web-friendly JSON

3. `Existing Python engine`
   - continues to own market data collection, analysis, journaling, and review logic
   - remains the source of truth until later backend evolution

### Boundary Rules

The frontend must not:

- call raw Python scripts directly
- parse CLI terminal text
- own trading logic

The backend bridge must:

- isolate the frontend from CLI/raw internals
- translate symbol button actions into structured engine calls
- expose a stable API

The existing engine must:

- remain unchanged in responsibility
- remain authoritative for call generation and review outputs

## Repository Strategy

### Website Repo

Use:

- `https://github.com/MitemsHub/mitemshub-indices`

as the website/product repo.

Because it is currently empty, it should become:

- the frontend home
- the bridge-layer home for version 1
- the deployment repo for the operator app

### Engine Repo

The current Synthetic Indices project remains:

- the engine repo
- the domain logic source of truth
- the system that the bridge wraps in version 1

### Design Operating Manual

Use:

- `https://github.com/MitemsHub/mitems-studio-os`

as the design and engineering standard, especially for:

- design philosophy
- component discipline
- layout hierarchy
- React / Next.js / TypeScript / Tailwind conventions
- API design, testing, QA, and deployment standards

## Frontend Structure

The app should feel like a private trading desk product, not a generic SaaS admin screen.

## Account Mode Model

Version 1 must include an `Account Mode` control with two states:

- `Own Account`
- `Prop Firm`

The toggle is not cosmetic. It changes how the returned call is framed for execution guidance.

### Own Account Mode

In `Own Account` mode:

- the app presents the market call as returned by the engine
- the manual trade panel is shown as-is
- no prop-rule compliance overlay is applied

### Prop Firm Mode

In `Prop Firm` mode:

- the app still requests the same underlying market call
- the backend bridge applies a second rule-aware compliance layer before the trade is presented as acceptable
- the UI must show whether the trade is:
  - allowed as-is
  - allowed only with tighter risk
  - blocked for prop-rule safety

### Version 1 Prop Baseline

For version 1, the prop-firm mode should target:

- Blueberry Funded `2-Step funded`

This should be modeled as a concrete risk-policy profile, not as a vague "prop firm" concept.

### Required Prop Inputs

Prop-mode evaluation requires current account-state inputs. The app must support a lightweight prop account profile containing:

- starting balance
- current balance
- current equity
- today's realized loss
- today's floating loss exposure
- high-impact news lockout state

If these inputs are missing, the app may still show the market call, but the prop compliance status must be explicitly marked as insufficient account-state data.

### Primary Workspace

The main screen should include:

- top command bar
- primary call panel
- trade instruction panel
- review and system panel
- recent history section

### Top Command Bar

Must include:

- `R_75` trigger
- `R_100` trigger
- account mode toggle: `Own Account` / `Prop Firm`
- fresh run action state
- last refresh time
- backend health badge
- current mode badge such as `read-only` or `manual execution`

### Primary Call Panel

Must prioritize:

- `buy_candidate`, `sell_candidate`, or `stand_aside`
- confidence
- regime
- direction bias
- why
- wait-for guidance
- generated time

This is the visual and informational center of the product.

### Trade Instruction Panel

Must present:

- entry area
- stop area
- target area
- reward/risk
- a clean manual trade framing

If the call is not actionable, this panel must degrade gracefully into a disciplined stand-aside instruction state instead of showing empty trading fields.

When `Prop Firm` mode is active, this panel must also show the compliance-adjusted trade framing rather than pretending the raw market call alone is sufficient.

### Prop Compliance Panel

When `Prop Firm` mode is active, the main workspace must show a dedicated prop compliance panel or integrated compliance section with:

- prop profile name
- compliance status
- remaining daily loss buffer
- remaining overall drawdown buffer
- max allowed risk for this trade idea
- whether resizing is required
- reason for block or adjustment when not allowed as-is

### Review And System Panel

Must show:

- recent alert count
- suppressed context count
- transport event count
- latest transport event
- latest transport reason
- freshness or backend status summary

### Call History

Must include:

- recent `R_75` and `R_100` decisions
- time
- call type
- confidence
- actionable state

## Symbol Button Behavior

When the user clicks `R_75` or `R_100`, version 1 should:

1. set the active symbol
2. trigger a fresh call run through the backend bridge
3. show a high-quality loading state
4. request evaluation under the currently selected account mode
5. update the primary call panel with the returned payload
6. update prop compliance output when prop mode is active
7. update relevant review/history/system surfaces

The symbol button is not merely navigation. It is an operator command.

## API Contract

The frontend should be designed against a stable API contract, even in version 1.

### Required Endpoints

- `POST /api/calls/run`
  - input: `symbol`, `account_mode`, optional prop profile payload
  - action: run a fresh call request
- `GET /api/calls/latest?symbol=...`
  - action: return latest known result
- `GET /api/history?symbol=...`
  - action: return recent symbol call history
- `GET /api/system/status`
  - action: return backend and review health
- `GET /api/prop-profiles/current`
  - action: return the currently selected prop profile and account-state inputs when prop mode is active

### Fresh Call Response

The backend bridge should return structured JSON fields such as:

- `symbol`
- `call`
- `alert_type`
- `trade_status`
- `confidence`
- `regime`
- `direction_bias`
- `why`
- `wait_for`
- `decision_summary`
- `entry_area`
- `stop_area`
- `target_area`
- `entry`
- `stop_loss`
- `take_profit`
- `reward_risk`
- `generated_at`
- `account_mode`
- `prop_compliance`
- `prop_adjusted_risk`
- `prop_block_reason`
- `prop_remaining_daily_buffer`
- `prop_remaining_overall_buffer`

### Review/System Response

The backend bridge should expose structured review and system fields such as:

- `latest_call`
- `alert_count`
- `suppressed_context_count`
- `transport_event_count`
- `latest_transport_event`
- `latest_transport_reason`
- `backend_status`
- `journal_status`

### Prop Compliance Semantics

When `account_mode=prop_firm`, the backend bridge must evaluate the market call against the Blueberry 2-Step funded policy layer and return a compliance result such as:

- `allowed`
- `allowed_with_adjustment`
- `blocked`
- `insufficient_account_state`

The market call and the compliance result must remain separate concepts:

- market engine decides trade direction and setup quality
- prop policy layer decides whether the trade is acceptable under the selected account mode

## Design Standards

The app must align with the spirit of `mitems-studio-os`, especially:

- systems over page-by-page improvisation
- hierarchy over decoration
- typography as a primary hierarchy tool
- whitespace as a feature
- motion as guidance, not spectacle
- performance as part of design
- accessibility as a baseline requirement

### Visual Direction

The app should be:

- dark and focused
- editorial and premium
- restrained in color use
- deliberate in spacing
- serious in tone

It must not look like:

- generic AI SaaS
- neon crypto casino UI
- crowded admin panel
- dashboard wallpaper made of cards

## Security And Privacy

Version 1 is private by default.

Requirements:

- authentication is required before access
- engine secrets remain server-side
- frontend never receives raw secrets or broker credentials
- bridge logs must avoid leaking sensitive runtime details into the browser

Version 1 does not need public-user account complexity, but it must not be casually exposed.

Prop account-state inputs are sensitive operational data and should be treated as protected user state, not public UI content.

## Error Handling

The app should fail clearly, not theatrically.

Cases that need explicit UX:

- backend bridge unavailable
- fresh call request fails
- review/status data unavailable
- no actionable setup exists
- engine output is stale

The UI should communicate these states plainly and preserve operator trust.

## Future Migration Path

The architecture should support:

### Phase 1

- private operator app
- local backend bridge
- current Python engine

### Phase 2

- same frontend contract
- hosted backend bridge or API
- stronger persistence, auth, and audit trail

### Phase 3

- possible execution-capable infrastructure
- stricter permission and trade control workflows
- MT5-capable deployment path if live execution is later enabled

The frontend should remain substantially stable across these phases.

## Version 1 In Scope

- private operator app
- fresh-call actions for `R_75` and `R_100`
- account-mode toggle for `Own Account` and `Prop Firm`
- Blueberry 2-Step funded prop compliance layer
- primary call panel
- trade instruction panel
- prop compliance visibility
- review/system visibility
- recent history
- local bridge API
- design system alignment with `mitems-studio-os`

## Explicitly Deferred

- direct broker execution from the website
- MT5 order placement from browser actions
- public marketing surface
- public subscriptions or customer accounts
- multi-tenant SaaS behavior
- chat-first assistant interface
- mobile app
- advanced analytics suite beyond operator needs

## File And Project Planning Direction

The later implementation plan should assume:

- website repo uses a modern React / Next.js / TypeScript frontend
- bridge layer is implemented cleanly and separately from UI concerns
- engine-facing integration code is isolated and replaceable
- frontend components derive from a disciplined design token and layout system rather than ad hoc styling

## Success Criteria

This design is successful when:

- the user can open a private website and request a fresh `R_75` or `R_100` call
- the website presents structured manual trade guidance clearly
- review and transport/system health are visible inside the app
- the current Python engine remains the source of truth
- the frontend does not depend on CLI text
- the website repo is ready to grow into the real product home
- the frontend can later move to a hosted backend with minimal product-surface rewrite
