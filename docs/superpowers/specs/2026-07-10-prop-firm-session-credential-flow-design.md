# Prop Firm Session Credential Flow Design

## Purpose

This design defines how `Prop Firm` mode should work inside the private operator web app so the operator can use a separate MT5 account when needed without changing the `Volatility 75` and `Volatility 100` workflow.

The change is not about new trading logic. It is about making account selection realistic:

- `Own Account` uses the normal MT5 connection
- `Prop Firm` can use a dedicated prop MT5 account
- if no separate prop details are entered, `Prop Firm` falls back to the same MT5 account used by `Own Account`

## Why This Exists

The current prop flow is too rigid because it assumes one static prop-account connection from environment variables.

That is not how the operator workflow behaves in practice:

- prop firms can issue separate login details
- those details may change from one account to another
- the operator may still want to run the same `R_75` and `R_100` process without rewriting local runtime config

The app should treat `Prop Firm` as a separate account context, not as a permanently hardcoded environment mode.

## User Requirement

When the operator clicks `Prop Firm`, the app should ask for MT5 login details for the prop account.

If the operator does not enter separate prop details, the app should still allow `Prop Firm` mode and fall back to the own-account MT5 connection already available in runtime configuration.

The symbols remain unchanged:

- `R_75`
- `R_100`

## Scope

This design covers:

1. The `Own Account` / `Prop Firm` interaction in the operator command bar.
2. Session-only handling of prop MT5 credentials in the browser.
3. Backend request handling for dynamic prop account telemetry.
4. Fallback from prop credentials to own-account MT5 runtime credentials.
5. Prop profile fetching used by the compliance surface.
6. Prop-mode call execution for `R_75` and `R_100`.
7. Operator-facing error handling for invalid MT5 credentials.
8. Test coverage for the new interaction and fallback behavior.

## Non-Goals

- Changing the trading symbols.
- Replacing the existing local Python engine bridge.
- Persisting prop credentials across browser restarts.
- Building multi-user auth, secrets vaulting, or cloud credential storage.
- Replacing the current prop-firm drawdown model.
- Changing the existing operator-page visual system beyond what is needed for the new prompt.

## Chosen Direction

The selected direction is:

- session-only prop credentials
- explicit prompt on `Prop Firm` selection
- blank-input fallback to own-account MT5 credentials

This means:

- prop credentials are kept only in browser memory for the current session
- refreshing the page clears them
- the backend uses request-supplied prop credentials when present
- otherwise the backend uses the own-account MT5 runtime credentials already configured locally

This direction is chosen because it balances realism, safety, and workflow speed:

- realistic because prop accounts can differ from the own account
- safer because passwords are not written to local browser storage
- faster because the operator can still continue in prop mode without entering new credentials every time

## UX Flow

### Entry Point

The existing `Prop Firm` button in `external/mitemshub-indices/src/components/operator/command-bar.tsx` remains the entry point.

Clicking it should no longer switch modes immediately.

Instead, it opens a lightweight modal or prompt sheet that lets the operator choose how the prop mode should connect.

### Prompt Contents

The prompt should use plain operator-facing wording, not technical backend language.

It should contain:

- `Server`
- `Login`
- `Password`
- optional `Starting balance`
- short explanation that leaving the connection fields blank will use the same MT5 account as `Own Account`

The prompt should also make the drawdown baseline understandable:

- `Starting balance` is the prop-program baseline used for daily and overall drawdown calculations
- default value is `100000`

### Confirm Behavior

When the operator confirms:

1. If `server`, `login`, and `password` are provided, the app stores those values in session memory and switches to `prop_firm`.
2. If those fields are blank, the app switches to `prop_firm` and marks the prop connection as `fallback_to_own_account`.
3. If the operator cancels, the app stays in the current mode and nothing changes.

### Session Behavior

The session-only prop connection remains available while the browser session is open.

The app should provide a clear way to reopen or edit the prop connection details after the first setup, such as:

- clicking `Prop Firm` again while already in prop mode
- or an `Edit prop connection` secondary action near the prop panel

Either pattern is acceptable, but the first implementation should prefer reusing the existing `Prop Firm` toggle surface to keep scope smaller.

## Frontend Design

### State Model

`external/mitemshub-indices/src/hooks/use-operator-workspace.ts` should own the session-only prop connection state.

Introduce a dedicated state shape similar to:

```ts
type PropConnectionInput = {
  mode: "fallback_to_own_account" | "dedicated_prop_account";
  server: string | null;
  login: string | null;
  password: string | null;
  terminalPath: string | null;
  startingBalance: number;
};
```

This state lives only in memory inside the client hook.

### Mode Switching

The command bar should stop calling `setAccountMode("prop_firm")` directly.

Instead, the button should trigger a handler exposed by the workspace hook, for example:

- `onRequestPropMode()`

That handler opens the prompt and only switches mode after the operator confirms the chosen connection behavior.

### Prop Profile Refresh

The workspace currently loads the prop profile on startup from `/api/prop-profiles/current`.

That is not sufficient once prop mode depends on session-entered credentials.

The workspace should:

- continue loading default support surfaces on startup
- fetch a prop profile again whenever prop mode is activated or prop connection details change
- pass the session-selected prop connection input when requesting the live prop profile

### Symbol Execution

The `R_75` and `R_100` buttons remain unchanged from the operator's point of view.

When a symbol is run in `prop_firm` mode, the request body should include:

- `account_mode`
- the resolved prop account state used for compliance
- the session prop connection input when present

The operator workflow stays the same:

- choose account mode
- press `R_75` or `R_100`
- receive the live trade plan

## Backend Design

### Core Rule

`external/mitemshub-indices/src/lib/engine-bridge.ts` must stop assuming that live prop credentials come only from environment variables.

The bridge should support two credential sources for prop telemetry:

1. request-supplied prop credentials from the active browser session
2. fallback own-account credentials from runtime environment

### Credential Resolution

Introduce a server-side resolution step for prop-mode requests:

1. If request-supplied `server`, `login`, and `password` are present, use them.
2. Otherwise, use the own-account MT5 runtime values from:
   - `SYNTHETIC_MT5_SERVER`
   - `SYNTHETIC_MT5_LOGIN`
   - `SYNTHETIC_MT5_PASSWORD`
   - `SYNTHETIC_MT5_TERMINAL_PATH`
3. Use the request `startingBalance` if provided and valid.
4. Otherwise default the prop starting balance to `100000`.

This keeps the drawdown logic correct while allowing connection flexibility.

### Prop Profile Request Contract

The prop profile route should become request-driven for the live case.

The simplest implementation is to support `POST` with a body shaped like:

```ts
type PropProfileRequest = {
  connection?: {
    server?: string | null;
    login?: string | null;
    password?: string | null;
    terminalPath?: string | null;
  } | null;
  startingBalance?: number | null;
};
```

Resolution behavior:

- if the request includes complete connection credentials, use them
- if it omits or blanks them, resolve through the own-account fallback
- if both dedicated and fallback credentials are unavailable, return a meaningful error state instead of pretending a live prop profile exists

### Call Route Contract

`/api/calls/run` should accept optional prop connection input in prop mode.

The request shape can be extended with:

```ts
type RunCallRequest = {
  symbol: "R_75" | "R_100";
  account_mode: "own_account" | "prop_firm";
  prop_account_state: PropAccountState | null;
  prop_connection?: {
    server?: string | null;
    login?: string | null;
    password?: string | null;
    terminalPath?: string | null;
    startingBalance?: number | null;
  } | null;
};
```

The backend does not need to use the credentials to generate the market snapshot itself.

The credentials matter for:

- reading the correct account telemetry
- calculating the correct prop compliance state
- ensuring the call shown in prop mode matches the active account context

## Fallback Logic

### Dedicated Prop Account

Use the entered prop MT5 details when all required connection fields are present:

- `server`
- `login`
- `password`

### Own-Account Fallback

If the operator leaves those fields blank, `Prop Firm` mode still runs by reusing the own-account MT5 connection.

This is a valid supported mode, not an error.

The app should still communicate this clearly in the UI, for example:

- `Prop checks are using the same MT5 account as Own Account`

### Invalid Partial Input

If the operator enters some but not all required connection fields, the frontend should block submission and explain what is missing.

The app should not silently downgrade partial manual input into fallback mode.

That prevents accidental use of the wrong account context.

## Error Handling

The app must not fake live success when connection attempts fail.

### Invalid Prop Credentials

If dedicated prop credentials are entered but MT5 login fails, the UI should show a clear message such as:

- `Could not connect to that prop account. Check server, login, or password.`

The mode should not switch into an apparently healthy dedicated prop state.

### Missing Fallback Credentials

If the operator chooses fallback behavior but the own-account runtime credentials are unavailable, the UI should show a clear message such as:

- `Own-account connection is not available, so prop checks cannot run right now.`

### Prop Profile Route Failure

If live prop telemetry fails unexpectedly, the app may keep the page usable, but it must label the state honestly.

Acceptable behavior:

- preserve the last known successful prop profile during the session and show it as stale
- or fall back to the deterministic mock profile only when clearly marked as unavailable for live verification

The implementation must not present mock data as if it were a confirmed live prop reading.

## Security And Storage

Prop credentials are session-only.

That means:

- do not write them to `localStorage`
- do not write them to cookies
- do not write them to `.env.local`
- do not persist them in backend files or journals

The credentials may exist:

- in in-memory React state during the current browser session
- in the request body for the active route call
- transiently in server memory while processing that request

History journaling must continue to exclude secrets.

No MT5 password should ever be appended into the operator call history journal.

## Testing

### Frontend Tests

Add or update tests to cover:

1. clicking `Prop Firm` opens the credential prompt
2. blank submit switches to `prop_firm` and marks fallback-to-own-account behavior
3. full submit stores dedicated prop credentials in session state
4. partial submit is rejected with operator-facing validation
5. switching back to `Own Account` does not break symbol execution

### Hook And Workspace Tests

Add or update tests to cover:

1. prop profile refresh after dedicated prop submission
2. prop profile refresh after fallback submission
3. request payloads include `prop_connection` only in prop mode
4. session-only credentials clear on fresh mount

### Bridge And Route Tests

Add or update tests to cover:

1. request credentials override env-based credentials for prop profile reads
2. blank request credentials fall back to own-account env credentials
3. invalid partial connection is rejected before live MT5 execution
4. `startingBalance` defaults to `100000`
5. missing both dedicated and fallback credentials returns an honest error state

## Implementation Notes

The smallest clean implementation should:

1. add the prop credential prompt and client-side session state
2. extend the prop profile route to accept request-driven connection input
3. extend the workspace hook to refresh prop profile from the active connection choice
4. extend the call route payload so prop-mode requests carry the selected connection context
5. preserve the existing operator visuals unless a small prompt-specific adjustment is necessary

This keeps the change focused on account-context realism without turning the operator app into a broader account-management product.

## Acceptance Criteria

This design is complete when all of the following are true:

- clicking `Prop Firm` no longer blindly assumes one hardcoded prop account
- the operator can enter dedicated prop MT5 credentials for the current session
- leaving the prop fields blank uses the own-account MT5 credentials as fallback
- `R_75` and `R_100` execution flow remains unchanged
- prop drawdown math still uses a baseline starting balance, defaulting to `100000`
- the UI clearly communicates invalid credentials and unavailable fallback conditions
- no prop secrets are persisted to local storage, env files, or history journals
- automated tests cover the new UI, route, and bridge behavior
