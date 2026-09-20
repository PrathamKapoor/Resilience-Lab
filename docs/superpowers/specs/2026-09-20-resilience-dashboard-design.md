# ResilienceLab Dashboard Design

## Purpose

Deliver a judge-ready dashboard at `/dashboard` that turns a completed or running
ResilienceLab experiment into a clear operational story: fault injected, system
degradation, recovery, and the policy that best controls the failure.

The visual direction is inspired by Folk's editorial minimalism, not a copy of
Folk's product. It uses a warm off-white workspace, oversized dark typography,
rounded surfaces, generous visual rhythm, coral fault accents, and a restrained
animated wave backdrop.

## Chosen Architecture

Create a self-contained Vite + React JavaScript application in `dashboard/`.
Its production build is served by the existing FastAPI app at `/dashboard`.
The dashboard reads the existing authenticated `/api/v1` experiment endpoints;
it does not add a dashboard database, alter experiment lifecycle semantics, or
invent any metrics.

During development, Vite runs independently and proxies `/api` to FastAPI.
For production and demos, `npm run build` emits `dashboard/dist`, which FastAPI
serves. The FastAPI route must return a useful unavailable message when the
frontend has not yet been built, while every existing API route remains
unchanged.

## Alternatives Considered

1. **React/Vite frontend served by FastAPI — selected.** It supports the user
   requested React Bits component directly, keeps dashboard code isolated, and
   remains a one-service demo after a production build.
2. **Vanilla HTML/JavaScript mounted in FastAPI.** Smaller build surface, but
   cannot honestly integrate the supplied React `GradientWaves` component.
3. **Separate hosted SPA.** More deployment flexibility, but it would add
   hosting, CORS, auth, and judge-demo failure modes without helping the MVP.

## Information Architecture

The default page is a selected experiment view.

- A compact top bar contains the ResilienceLab wordmark, navigation labels,
  experiment selector, and a clear run-status chip.
- The hero names the experiment and tells the single high-level outcome. A
  `GradientWaves` layer is visual texture only; all meaning remains available
  as ordinary text and charts.
- KPI cards show resilience score, availability, p99 latency, and error-budget
  consumption. Each value is sourced from the selected experiment's metrics or
  marked unavailable.
- The recovery section combines the timeline with explicit fault and recovery
  markers. It answers whether the system returned to a stable state.
- A recommendation card explains the best available policy using the existing
  analysis/report data. If an evidence-backed recommendation cannot be
  derived, the card states that explicitly rather than fabricating one.
- A latest-signals list shows relevant experiment events, with a link to the
  existing report for full detail.

The desktop layout is a dense three-column editorial grid. It becomes a
single-column, horizontally safe layout below 768px. The primary judge-demo
flow is: choose experiment -> identify injected fault -> read impact -> see
recovery -> compare the policy recommendation.

## Data and State

`DashboardApp` loads experiment summaries from `GET /api/v1/experiments` and
persists the selected experiment id in the URL query string. It then loads:

- `GET /api/v1/experiments/{id}` for identity and status;
- `GET /api/v1/experiments/{id}/metrics` for per-run metrics;
- `GET /api/v1/experiments/{id}/timeline` for recovery chart points;
- `GET /api/v1/experiments/{id}/events` for latest signals; and
- `GET /api/v1/experiments/{id}/analysis` and `/report` for an evidence-backed
  recommendation and narrative.

Requests use same-origin credentials and the configured API-key header when
provided through a development-only local configuration. No API key is embedded
in a production frontend bundle. Loading, empty, permission-denied, integrity
conflict, and unavailable-data states are distinct and readable. A running
experiment polls its status at a bounded interval and stops polling in a
terminal state or when the tab is hidden.

## Visual System

- Background: warm off-white `#F7F4EF`; surfaces: `#FFFDFA`; ink: `#1D1B1A`.
- Accent: coral `#FF6A4D` for faults, lilac for comparative context, green only
  for successful recovery, and never color alone for status.
- Typography: a system-safe sans-serif fallback first; production web fonts
  must not block first paint. Large headings use tight tracking; body copy is
  at least 16px with readable contrast.
- Components use 18–20px corners, thin neutral borders, almost no shadow,
  visible keyboard focus, labelled controls, and actual SVG icons rather than
  emoji.
- Motion is limited to short transitions. `prefers-reduced-motion` disables
  nonessential animation.

## GradientWaves Integration

Install `ogl` and place the supplied JavaScript/CSS component under
`dashboard/src/components/GradientWaves.jsx` and `.css`. Use it only as an
absolutely positioned, pointer-inert hero background behind readable content.
Use ResilienceLab colors: horizon `#E7DDFF`, wave `#FF9B87`, crest `#FFF7F0`.
Set `detail="low"`, `speed={0.18}`, and modest amplitude to protect demo
hardware. Respect reduced motion by rendering a static CSS gradient instead;
the component must clean up its WebGL context and animation frame on unmount.

The waves never carry data, never cover controls, and are disabled for users
who request reduced motion or whose browser lacks WebGL 2. The hero reserves
its height up front to prevent layout shift.

## FastAPI Integration and Packaging

FastAPI mounts the built dashboard only after `/api/v1` routes are registered,
so API routes cannot be shadowed. `/dashboard` and nested client routes serve
the built SPA index. Build assets are cacheable by hashed filename; the HTML
entry point is not long-cached. Docker and Kubernetes build the dashboard in a
Node build stage and copy only the compiled static files into the existing
non-root Python runtime image.

The repository documents local development and the production build command.
`node_modules`, Vite caches, and generated dashboard distribution files remain
ignored unless the deployment model explicitly requires committed assets.

## Testing and Acceptance Criteria

- Python API tests assert that `/dashboard` returns the application when a
  build is present and never intercepts `/api/v1/*`.
- Frontend tests cover metric transformation, recommendation derivation,
  loading/error/empty states, and reduced-motion Wave fallback.
- A production build completes with `npm run build` and contains no embedded
  secret or API key.
- The page is usable at 375px, 768px, 1024px, and 1440px; it has no horizontal
  scroll, keyboard focus is visible, controls have accessible labels, and
  text/status relationships are not color-only.
- The final walkthrough demonstrates a real experiment using existing API
  responses from local mode or server mode, including at least one completed
  run and its actual fault/recovery signals.
