# One-Click Local Launcher Design

## Purpose

This design defines a one-click local launcher for the `mitemshub-indices` app so the operator can start the full local website quickly without repeating the manual startup steps every day.

The launcher is not a new runtime. It is only an automation layer over the already working local workflow.

## Why This Exists

The current local process works, but daily use is too manual:

- open PowerShell
- move into the app directory
- ensure the correct Node runtime is available
- ensure dependencies exist
- start the app
- open the browser

That is unnecessary friction for an operator-facing local tool.

## User Requirement

The operator wants a one-click local launcher as long as it does not reduce accuracy, remove any existing logic, or weaken performance.

The correct interpretation is:

- startup should become much easier
- the app must still use the same local engine bridge
- the app must still use the same `.env.local`
- `R_75` and `R_100` must still produce the same calls they would produce under manual startup

## Scope

This design covers:

1. A one-click production-style launcher for daily local use.
2. A small companion stop script to shut down the local app cleanly.
3. Automatic browser opening after startup.
4. Safe runtime checks for `.env.local`, dependencies, and build output.
5. Small documentation updates for local usage.

## Non-Goals

- Changing the engine logic.
- Changing MT5 login behavior.
- Changing prop-account calculations.
- Replacing the existing Next.js runtime.
- Auto-starting at Windows login.
- Adding Telegram integration.
- Rewriting the app into a desktop executable.

## Chosen Direction

The selected direction is:

- production-style local launcher
- helper stop script
- browser auto-open

This is preferred because it is the best daily-use experience:

- cleaner than dev mode for normal operation
- closer to how the app is already verified in production-style local runs
- safer than auto-start because it only runs when the operator wants it

## Files

The launcher set should include:

- `launch-mitemshub-indices.ps1`
- `launch-mitemshub-indices.bat`
- `stop-mitemshub-indices.ps1`

Optional documentation update:

- `README.md`

## Startup Design

### Launcher Entry Point

The operator should be able to start the app by double-clicking `launch-mitemshub-indices.bat`.

That batch file should exist only as a Windows-friendly entry point and should call the main PowerShell launcher.

The main logic belongs in `launch-mitemshub-indices.ps1`.

### Runtime Behavior

The launcher should:

1. Determine the app directory from the script location.
2. Confirm that `.env.local` exists.
3. Ensure the Node runtime is available.
4. Use the bundled Node path already known to work in this workspace if the normal environment path is not enough.
5. Install dependencies only when `node_modules` is missing.
6. Run `npm run build`.
7. Start `npm run start -- --port 3006` in a separate PowerShell process.
8. Wait briefly for startup.
9. Open `http://localhost:3006` in the default browser.

### Port Choice

The default launcher port should be `3006`.

That matches the current verified local preview flow and avoids conflicting with common development defaults like `3000`.

## Accuracy And Performance

The launcher must not change any computation path.

It should still use:

- the same app files
- the same `.env.local`
- the same local engine bridge
- the same MT5 credentials already configured locally

That means the launcher does not determine call quality. It only automates startup.

If the manual startup gives accurate calls, the launcher should give the same calls because it starts the same application in the same local environment.

## Safety Rules

### Config Safety

The launcher must not:

- overwrite `.env.local`
- inject new credentials
- rewrite engine paths
- modify project code

If `.env.local` is missing, the launcher should stop and show a direct message telling the operator to create it first from `.env.example`.

### Process Safety

The launcher should not kill unrelated processes.

The stop script should only stop the app process it is responsible for, using a tracked process ID file or a similarly precise method.

### Dependency Safety

The launcher should only run `npm install` when dependencies are clearly missing.

It should not reinstall dependencies on every launch, because that adds needless delay and can introduce instability.

## Stop Script Design

The stop script should:

1. Read the stored app process ID if available.
2. Stop that specific process if it is still running.
3. Remove the process ID marker after shutdown.
4. Report clearly if no launcher-started process is currently active.

This gives the operator a simple and predictable way to shut down the local app.

## Error Handling

### Missing `.env.local`

Show a message such as:

- `Missing .env.local. Copy .env.example to .env.local and fill in your local settings first.`

### Missing Node Runtime

If both the system runtime and bundled Node path fail, show a direct message such as:

- `Node runtime not found. Install Node or restore the bundled Node toolchain path.`

### Failed Build

If `npm run build` fails:

- do not start the server
- show the build error
- stop cleanly

### Startup Failure

If the server process fails to start:

- do not open the browser blindly
- show a message indicating startup failed

## Testing

Add or update tests only where they add real value.

For this change, the meaningful verification is:

1. launcher scripts are created in the app repo
2. the launcher starts the app on `http://localhost:3006`
3. the browser opens successfully
4. the stop script shuts down the launched app cleanly
5. the app still returns the same verified local behavior after launcher startup

Script-heavy validation may rely partly on direct execution checks rather than unit tests.

## Acceptance Criteria

This design is complete when all of the following are true:

- the operator can start the app by double-clicking one launcher entry file
- the launcher starts the same local app logic already used in manual startup
- the launcher does not rewrite `.env.local` or credentials
- the launcher opens the local app in the browser
- the stop script shuts down only the launcher-started app process
- the documented local workflow is reduced from multiple manual commands to one-click startup
