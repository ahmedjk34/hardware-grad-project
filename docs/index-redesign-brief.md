# Handoff prompt — redesign the operator console index page

Paste everything below the line into a fresh agent session that has this
repository checked out.

---

## Task

Fully restyle and expand the index page of the React operator console in
`web/`, following the specification in `docs/DESIGN.md`. This is a graduation
project's flagship screen — the visual quality bar is "a machine tool's control
panel", not "a starter template".

## Read first, in this order

1. `docs/DESIGN.md` — the design system. Tokens, layout, component specs and
   the explicit "do not do" list. This is authoritative; follow it rather than
   inventing a look.
2. `docs/CONSOLE.md` — §2 "The product" and §3 "The eight facts that shape
   the design". The eight facts explain *why* the safety states are shaped
   the way they are.
3. `web/src/` — all of it. It is small: `App.tsx`, `store.ts`, `ws.ts`,
   `api.ts`, `types.ts`, `style.css`, and eight components.
4. `python/web/state.py`, `routes_command.py`, `app.py` — the exact state
   payload and endpoints available. Do not guess the API shape; it is all here.

## What the app is

A gantry rig places blocks on a surface. An overhead camera watches. The
operator taps a cell in the live camera image, confirms, and the Arduino runs an
uninterruptible ~40 second pick-and-place. A FastAPI service on a Raspberry Pi
owns the one camera and the one serial port and enforces every safety rule; the
browser is untrusted and only mirrors server state.

## Hard constraints

- **Behaviour must not change.** The guarded request sequence, the two-tap build
  confirmation, the reconnecting WebSocket, and the homography maths in
  `GridOverlay` / `lib/workspace.ts` are load-bearing and tested. Run
  `cd web && npm test` before and after; `step7`, `step9`, `step10` and
  `lib/workspace.test.tsx` must all still pass. If a test's DOM query breaks
  because of a legitimate markup change, update the query — never the guard it
  is checking.
- **Never add a "cancel build" or "retry" control.** The firmware is deaf during
  a build and a locked session has no software recovery. This is a safety rule,
  not a preference.
- **No CDN assets.** The Pi serves this over LAN with no guaranteed internet.
  System font stack, or a self-hosted font in `web/public/`. Everything must
  work offline; the PWA shell must keep working.
- Keep the stack: Vite + React + TypeScript, plain CSS custom properties. Do not
  introduce a UI component library or a CSS framework.

## Deliverables

### A. A real stylesheet

Replace `web/src/style.css` with a token-driven system implementing
`docs/DESIGN.md` §3 — colour, type scale, 4px spacing scale, radii, motion
tokens, focus rings, and a `prefers-reduced-motion` branch. No raw hex values
outside the token block.

### B. Restructured index layout

Implement `docs/DESIGN.md` §5: status rail, camera stage as the hero, right
control rail on desktop, and a sticky bottom action sheet on phones so BUILD is
always in the thumb zone. The camera column needs `min-width: 0` or the video
will push the rail off screen.

### C. Restyled existing components

`StatusBar`, `CameraView`, `GridOverlay`, `ControlPanel`, `BuildButton`,
`BuildBanner`, `LockedBanner`, `ResultToast`, `Calibrate` — all to the §6 specs.
Particular attention to:

- the **double-stroke halo** on every SVG overlay stroke (§6.2) so the overlay
  survives arbitrary video behind it;
- the **command readout** as a large mono instrument well that does not reflow
  when the selection changes (§6.3);
- the **armed BUILD state** with a visibly draining 3-second countdown (§6.4);
- disabled-reason text rendered visibly, not only in a `title` attribute —
  phones have no hover.

The components are currently written as one enormous line each. Break them into
readable multi-line TSX as you go.

### D. New features — all of these use endpoints that already exist

The current UI ignores capability the backend already ships. Add:

1. **Rig log panel.** `/api/events` already broadcasts `{type:"log", line}` and
   `ws.ts` drops it. Extend the store with a bounded log buffer (cap ~200 lines)
   and render a terminal-styled, auto-scrolling, collapsible panel with
   prefix-based colouring per §6.7.
2. **Overlay view toggles.** `POST /api/view` accepts
   `{grid, detect, paper, overlay}`; `state.views` reports them. Render as chips
   on the camera stage. These stay enabled during a build — they are
   display-only, and the server allows them while RUNNING.
3. **Grid mode switch.** `POST /api/mode` with `vertical` / `horizontal`.
   Requires an explicit confirm step warning that the rig homes X/Y and the
   selection is cleared.
4. **Camera freshness meter.** Use `state.camera` and `state.camera_age_ms` for
   a LIVE / STALE / WAITING chip with the age in ms, plus the stage treatments
   in §6.1.
5. **Direct level entry.** `POST /api/level` accepts `{value}` as well as
   `{delta}`. Guard against negatives.
6. **Keyboard shortcuts** per §7, with a `?` overlay listing them.
7. **Calibration as a stepped wizard** rather than a row of bare buttons: show
   which of the four corners is being collected, with a progress indicator, and
   surface the sheet-calibration path as a distinct choice.

Wire each of these through `api.ts` in the existing style. Add a Vitest case per
new behaviour.

### E. Polish

- Replace `web/index.html`'s bare title with a proper document title, theme
  colour, and description; give the PWA manifest a real icon set.
- Make sure `WAITING`, `STALE`, `DISCONNECTED`, `RUNNING` and `LOCKED` each look
  visibly, unmistakably different — screenshot-check all five.

## Verification

- `cd web && npm test` passes.
- `cd web && npm run build` succeeds.
- Drive every state without hardware:
  `cd python && ../.venv/bin/python -m web --mock` then `cd web && npm run dev`.
  The mock board can produce placed, rejected and aborted outcomes — exercise
  all three plus the locked banner.
- Check the layout at 390px, 768px and 1440px wide.

## Report back

A short summary of: what you restyled, what you added, which endpoints you newly
consumed, which tests you added, and anything in `docs/DESIGN.md` you
deliberately deviated from and why.
