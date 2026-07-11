# Prop Telemetry Status Label Design

## Purpose

This design defines a small but critical safety improvement for the operator app:

- the prop compliance surface must tell the operator whether the displayed prop-account numbers are confirmed live, coming from own-account fallback, or unavailable for live verification

The goal is not to change the trading workflow. The goal is to stop the UI from looking equally trustworthy in all prop telemetry states.

## Why This Exists

The current prop flow can show a valid-looking compliance panel without clearly telling the operator whether:

- the prop profile was read successfully from the intended account
- the prop profile is using the own-account MT5 fallback
- live prop telemetry could not be confirmed

That ambiguity is dangerous because the operator can mistake fallback-safe or unavailable states for confirmed live account telemetry.

## User Requirement

Use backend-truth status plus a small UI label.

That means:

- the backend determines the telemetry state
- the frontend displays a compact, plain-language status line
- the wording must be clear and operator-facing, not technical

## Scope

This design covers:

1. Adding backend-truth prop telemetry status to the prop profile response.
2. Distinguishing dedicated live success, own-account fallback success, and unavailable live verification.
3. Showing a compact plain-language label above the prop compliance surface.
4. Updating tests for route behavior and operator rendering.

## Non-Goals

- Changing the existing prop connection modal flow.
- Changing the prop drawdown calculation model.
- Adding a large warning banner or a new panel.
- Reworking the visual layout of the operator page.
- Adding deployment or GitHub workflow logic into the UI.

## Chosen Direction

The selected direction is:

- backend-truth status
- compact inline label
- plain operator wording

This is preferred because it is both honest and lightweight:

- honest because the backend knows whether live telemetry actually succeeded
- lightweight because the operator page only needs a short status line, not a new warning system

## Backend Design

### Response Shape

The prop profile payload should be extended with a small telemetry status object.

The shape should be similar to:

```ts
type PropTelemetryStatus =
  | "live_confirmed"
  | "own_account_fallback"
  | "live_unavailable";

type PropTelemetryState = {
  status: PropTelemetryStatus;
  message: string;
};
```

The prop profile response should then include:

```ts
type PropProfileResponse = PropAccountState & {
  telemetry: PropTelemetryState;
};
```

### Truth Rules

The backend should set the status using these rules:

1. `live_confirmed`
   - dedicated prop credentials were used and the live MT5 profile read succeeded
   - or own-account fallback credentials were used and the live MT5 profile read succeeded through that fallback path
   - the message should still distinguish which connection source was used

2. `own_account_fallback`
   - the request intentionally used blank prop credentials
   - the backend used the own-account MT5 runtime credentials
   - the live MT5 profile read succeeded through that fallback path

3. `live_unavailable`
   - live prop telemetry could not be verified
   - either dedicated credentials failed, fallback credentials were missing, or the MT5 read failed unexpectedly

### Message Rules

The backend should return plain operator wording, not internal transport jargon.

Preferred messages:

- `Live prop check confirmed`
- `Using own-account fallback`
- `Live prop check unavailable`

If useful, a short reason can still be attached internally or as a secondary field, but the main message should remain short and clear.

### Failure Honesty

When live telemetry cannot be confirmed:

- the backend may still return the safe fallback profile numbers so the UI remains stable
- but it must label the result as `live_unavailable`
- the UI must never present that result as confirmed live telemetry

## Frontend Design

### Rendering Rule

The operator app should render a compact status line above the prop compliance panel when `accountMode === "prop_firm"`.

This line should come directly from the backend telemetry object.

The UI should not invent or infer the status from partial client-side heuristics.

### Wording

The status line should display the backend message exactly or very close to it, for example:

- `Live prop check confirmed`
- `Using own-account fallback`
- `Live prop check unavailable`

The style should be compact and readable:

- small utility-style text
- visible enough to notice
- not large enough to dominate the page

### Placement

The label should appear immediately above the existing prop compliance panel.

That keeps the meaning attached to the panel it qualifies.

## Data Flow

1. The frontend requests the prop profile.
2. The backend resolves credentials and attempts the live MT5 read.
3. The backend returns:
   - prop numbers
   - telemetry status
   - telemetry message
4. The frontend stores the full response in workspace state.
5. The prop-mode surface renders the compact status line above the compliance panel.

## Error Handling

### Dedicated Prop Failure

If dedicated prop credentials were entered but the MT5 login fails:

- return `live_unavailable`
- keep the message plain, such as `Live prop check unavailable`
- do not label the panel as confirmed live

### Missing Fallback Credentials

If the operator chose fallback behavior but no own-account MT5 credentials are available:

- return `live_unavailable`
- keep the existing safe UI behavior
- ensure the label makes the lack of live verification explicit

### Unexpected MT5 Read Failure

If the MT5 read fails for any other reason:

- return `live_unavailable`
- preserve the stable page shape
- do not silently imply live confirmation

## Testing

Add or update tests to cover:

1. route returns `telemetry.status = "live_confirmed"` when dedicated live read succeeds
2. route returns `telemetry.status = "own_account_fallback"` when blank prop credentials succeed through own-account fallback
3. route returns `telemetry.status = "live_unavailable"` when live verification fails
4. operator shell renders the backend message above the prop panel
5. the frontend does not replace backend-truth status with a local guess

## Acceptance Criteria

This change is complete when all of the following are true:

- the prop profile response includes backend-truth telemetry status
- the backend explicitly distinguishes live confirmation, own-account fallback, and unavailable live verification
- the operator page shows a compact plain-language status line above the prop compliance panel
- unavailable live telemetry is clearly labeled and not presented as confirmed
- automated tests cover the new backend and frontend behavior
