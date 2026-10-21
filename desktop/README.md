# Desktop wrapper (Tauri)

The desktop app is a thin native window around the same React PWA, so the UI is identical
everywhere.

Packaging is done in a dedicated step **after** the six feature modules are built, so the
bundle can include the finished Python backend as a sidecar.

Planned approach:

1. `npm create tauri-app` (Tauri v2) inside this `desktop/` folder.
2. Point `frontendDist` at `../../frontend/dist` and `devUrl` at `http://localhost:5173`.
3. Bundle the FastAPI backend as a PyInstaller executable and register it as a Tauri
   sidecar, so the installed app starts the API automatically.
4. Run `npm run tauri build` to produce `.msi`/`.exe` on Windows (and `.dmg`/`.AppImage`
   on other platforms).

Until then, use the web app (`scripts\dev.ps1`) — it already installs on desktop browsers
as a PWA too.
