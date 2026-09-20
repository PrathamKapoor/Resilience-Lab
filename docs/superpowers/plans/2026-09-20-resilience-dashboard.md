# Resilience Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Folk-inspired, API-backed ResilienceLab dashboard at `/dashboard` with a safe GradientWaves hero.

**Architecture:** A Vite + React JavaScript application in `dashboard/` calls existing same-origin `/api/v1` APIs. FastAPI serves its production build without shadowing API routes; Docker builds assets in a Node stage and copies only compiled output to the non-root Python runtime.

**Tech Stack:** React 18, Vite, Vitest, OGL, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-resilience-dashboard-design.md`

## Global Constraints

- Use only real `/api/v1` data; never embed an API key in the bundle.
- Mount dashboard paths after API routes and preserve `/api/v1/*` behavior.
- Use GradientWaves decoratively with `detail="low"`, `speed={0.18}`, pointer events disabled, a reduced-motion fallback, and WebGL cleanup.
- Meet keyboard, contrast, responsive, and color-independent status requirements at 375px, 768px, 1024px, and 1440px.
- Keep `dashboard/node_modules`, Vite caches, and `dashboard/dist` ignored.

---

### Task 1: Scaffold the dashboard frontend

**Files:**
- Create: `dashboard/package.json`, `dashboard/vite.config.js`, `dashboard/index.html`, `dashboard/src/main.jsx`, `dashboard/src/styles.css`, `dashboard/src/App.test.jsx`
- Modify: `.gitignore`

**Interfaces:** Produces `npm run dev`, `npm run build`, `npm run test`, and `dashboard/dist/index.html`; Vite proxies `/api` to `http://127.0.0.1:8000` in development.

- [ ] **Step 1: Write the failing build-contract test**

```jsx
import { expect, test } from 'vitest';
test('uses the dashboard base path', () => {
  expect(import.meta.env.BASE_URL).toBe('/dashboard/');
});
```

- [ ] **Step 2: Verify failure**

Run: `npm --prefix dashboard test -- --run`

Expected: FAIL because no dashboard package exists.

- [ ] **Step 3: Implement the Vite project**

Add React, React DOM, OGL, Vite, Vitest, and React Testing Library. Configure Vite with `base: '/dashboard/'`, the React plugin, test environment `jsdom`, and the API proxy. Add warm off-white global CSS tokens.

- [ ] **Step 4: Verify build**

Run: `npm --prefix dashboard test -- --run; npm --prefix dashboard run build`

Expected: PASS and `dashboard/dist/index.html` exists.

- [ ] **Step 5: Commit**

```bash
git add .gitignore dashboard
git commit -m "feat: scaffold dashboard frontend"
```

### Task 2: API data layer and metric derivation

**Files:**
- Create: `dashboard/src/api/client.js`, `dashboard/src/api/dashboard-data.js`, `dashboard/src/api/dashboard-data.test.js`

**Interfaces:** Produces `listExperiments()`, `loadExperimentDashboard(id)`, `deriveDashboardMetrics(metrics)`, and `deriveRecommendation(analysis, report)`.

- [ ] **Step 1: Write failing metric derivation test**

```jsx
import { expect, test } from 'vitest';
import { deriveDashboardMetrics } from './dashboard-data';
test('aggregates named metrics without inventing missing data', () => {
  expect(deriveDashboardMetrics([{ availability: 0.99, p99_latency_ms: 200 }]))
    .toMatchObject({ availabilityPercent: 99, p99LatencyMs: 200 });
});
```

- [ ] **Step 2: Verify failure**

Run: `npm --prefix dashboard test -- --run src/api/dashboard-data.test.js`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement API boundaries**

Fetch with `credentials: 'same-origin'`; expose readable non-2xx errors; load the documented experiment, metrics, timeline, events, analysis, and report endpoints. Return `null` for absent values and state explicitly when analysis has insufficient recommendation evidence.

- [ ] **Step 4: Verify tests**

Run: `npm --prefix dashboard test -- --run`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/api
git commit -m "feat: add dashboard API data layer"
```

### Task 3: Dashboard UI and GradientWaves

**Files:**
- Create: `dashboard/src/components/GradientWaves.jsx`, `dashboard/src/components/GradientWaves.css`, `dashboard/src/components/Dashboard.jsx`, `dashboard/src/components/Dashboard.test.jsx`
- Modify: `dashboard/src/main.jsx`, `dashboard/src/styles.css`

**Interfaces:** `Dashboard` consumes selected experiment data and renders named loading, empty, error, permission, integrity, and completed states.

- [ ] **Step 1: Write failing UI state test**

```jsx
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import Dashboard from './Dashboard';
test('explains an empty experiment state', () => {
  render(<Dashboard experiments={[]} state="empty" />);
  expect(screen.getByText(/no experiments yet/i)).toBeTruthy();
});
```

- [ ] **Step 2: Verify failure**

Run: `npm --prefix dashboard test -- --run src/components/Dashboard.test.jsx`

Expected: FAIL because `Dashboard` does not exist.

- [ ] **Step 3: Implement the view**

Create a top bar, URL-backed experiment selector, hero, KPI cards, textual fault/recovery timeline markers, policy rationale, latest signals, and report link. Use semantic HTML and a responsive editorial grid. Copy the supplied component, guard it against reduced motion and unavailable WebGL, use `#E7DDFF`, `#FF9B87`, `#FFF7F0`, make its canvas `aria-hidden`, and keep it behind hero content.

- [ ] **Step 4: Verify tests and build**

Run: `npm --prefix dashboard test -- --run; npm --prefix dashboard run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src
git commit -m "feat: add resilience experiment dashboard"
```

### Task 4: FastAPI dashboard routes

**Files:**
- Modify: `resiliencelab/api/app.py`
- Create: `tests/test_dashboard_routes.py`

**Interfaces:** `GET /dashboard` and nested dashboard client paths serve the Vite entry when built. All `/api/v1/*` routes remain API-owned.

- [ ] **Step 1: Write failing route tests**

```python
def test_dashboard_does_not_shadow_api(client):
    assert client.get('/api/v1/health').status_code == 200

def test_dashboard_is_explicit_when_build_is_missing(client):
    assert client.get('/dashboard').status_code in {200, 503}
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_dashboard_routes.py -q --basetemp .pytest-tmp/dashboard-routes`

Expected: FAIL because `/dashboard` is unregistered.

- [ ] **Step 3: Implement safe static serving**

After `app.include_router(v1)`, resolve `dashboard/dist`, serve the index at `/dashboard` and nested client paths, and return a 503 with `npm --prefix dashboard run build` if absent. Do not mount a catch-all static route at `/`.

- [ ] **Step 4: Verify focused tests**

Run: `python -m pytest tests/test_dashboard_routes.py tests/test_api_contract.py -q --basetemp .pytest-tmp/dashboard-routes`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add resiliencelab/api/app.py tests/test_dashboard_routes.py
git commit -m "feat: serve dashboard from API"
```

### Task 5: Package and present the dashboard

**Files:**
- Modify: `deployment/docker/Dockerfile`, `deployment/docker-compose.yml`, `README.md`
- Create: `docs/demo-script.md`, `docs/architecture-dashboard.md`

**Interfaces:** Produces a dashboard-aware container build and a repeatable three-minute judge demo.

- [ ] **Step 1: Verify Docker lacks dashboard build support**

Run: `rg 'node:|dashboard/dist' deployment/docker/Dockerfile`

Expected: no match before implementation.

- [ ] **Step 2: Implement packaging and documentation**

Use a pinned Node builder to run `npm ci` and `npm run build`, then copy only `dashboard/dist` into the existing non-root Python image. Document local development, production build, `/dashboard`, metric provenance, architecture, and the demo sequence: context, fault injection, impact, recovery, recommendation, reproducibility.

- [ ] **Step 3: Verify build and documentation**

Run: `npm --prefix dashboard ci; npm --prefix dashboard run build; rg -n '/dashboard|three-minute|fault' README.md docs/demo-script.md docs/architecture-dashboard.md`

Expected: build succeeds and all demo stages are documented.

- [ ] **Step 4: Commit**

```bash
git add deployment/docker deployment/docker-compose.yml README.md docs
git commit -m "docs: add dashboard demo and deployment guide"
```

### Task 6: Release verification

**Files:** Modify only files required to correct verification failures.

- [ ] **Step 1: Run frontend verification**

Run: `npm --prefix dashboard test -- --run; npm --prefix dashboard run build`

Expected: PASS.

- [ ] **Step 2: Run backend verification**

Run: `python -m pytest -q --basetemp .pytest-tmp/dashboard-full; python -m ruff check resiliencelab tests; python -m ruff format --check resiliencelab tests`

Expected: PASS with the existing skipped-test count unchanged or explained.

- [ ] **Step 3: Smoke test responsive accessibility**

Open `/dashboard` at 375px, 768px, 1024px, and 1440px. Verify no horizontal scroll, visible focus, textual statuses, readable error/empty states, and a static hero with reduced motion.

- [ ] **Step 4: Commit and push verified changes**

```bash
git add -A
git commit -m "test: verify resilience dashboard release"
git push origin HEAD:main
```
