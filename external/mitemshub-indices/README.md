# MitemsHub Indices

This operator app lives inside the main Synthetic Indices Bot monorepo.

## Local bridge setup

1. From the monorepo root, keep the engine code in place.
2. In this app folder, copy `.env.example` to `.env.local`.
3. Point `SYNTHETIC_ENGINE_ROOT` at the monorepo root:
   `C:\Users\USER\Desktop\Projects\Synthetic Indices Bot`
4. Install dependencies with `npm install`.
5. Start the app with `npm run dev`.

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

## Repository Ownership

This app is part of the same project as the Python engine.

- run Git commands from the monorepo root
- do not recreate a nested `.git` directory here
- keep app secrets in `.env.local`, which remains ignored by the root repo
