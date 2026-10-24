# My Cloud PC

A responsive React/Vite desktop simulation intended for mouse and touch input. It includes a desktop, Start menu, draggable/resizable windows on larger screens, minimize/maximize/close controls, a local Notepad using Dexie/IndexedDB, a mock File Explorer, wallpaper settings, and a PWA manifest.

## Requirements

- Node.js 18+
- npm

## Run locally

```bash
npm install
npm run dev
```

Open the Vite URL printed in the terminal. To create a production bundle:

```bash
npm run build
npm run preview
```

## Deploy

The app lives in the `cloud-pc/` subdirectory of the parent repository. In a Vercel project, set **Root Directory** to `cloud-pc`, **Build Command** to `npm run build`, and **Output Directory** to `dist`. The generated app can also be hosted as static files on a suitable host.

## Storage and limitations

- Notepad text and File Explorer entry metadata are stored in IndexedDB in the current browser/device.
- File Explorer records selected file names/types/sizes only. It does not upload files or persist their bytes.
- This project simulates a desktop interface; it does not provide a remote Windows/Linux machine, remote compute, server-side storage, or cross-device synchronization.
- The PWA manifest includes an SVG icon. Installability and offline behavior depend on the host/browser; offline caching/service-worker support is not included in this starter.
- On narrow mobile layouts, windows use a full-screen layout to remain touch-friendly.

## Main files

- `src/App.jsx` — desktop shell and apps
- `src/components/Window.jsx` — pointer-event window manager
- `src/db.js` — Dexie/IndexedDB helpers
- `src/index.css` — responsive theme
