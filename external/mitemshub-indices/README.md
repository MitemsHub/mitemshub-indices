# MitemsHub Indices

## Local bridge setup

1. Copy `.env.example` to `.env.local`.
2. Point `SYNTHETIC_ENGINE_ROOT` at the existing Synthetic Indices engine repo.
3. Install dependencies with `npm install`.
4. Start the app with `npm run dev`.

The bridge currently uses deterministic fallback data until the engine integration expands beyond the boundary configuration added in Task 5.

If `npm` is not on your `PATH` in this Windows workspace, use the bundled Node.js toolchain already working here:

```powershell
$env:Path = 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' install
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run dev
```

## One-click local startup

After the first-time setup is complete, you can start the app with:

- `launch-mitemshub-indices.bat`

This launcher:

- checks that `.env.local` exists
- installs dependencies only if needed
- builds the app
- starts the local server on `http://localhost:3006`
- opens the browser automatically

To stop the locally launched app, run:

- `stop-mitemshub-indices.ps1`
