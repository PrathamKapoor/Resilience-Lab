import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { getJson } from './client';
import {
  deriveDashboardMetrics,
  deriveRecommendation,
  getExperimentStatus,
  listExperiments,
  loadExperimentDashboard,
} from './dashboard-data';

function buildDashboardBundle(extraEnv = {}, viteArgs = []) {
  const dashboardRoot = process.cwd();
  execFileSync(
    process.execPath,
    [join(dashboardRoot, 'node_modules', 'vite', 'bin', 'vite.js'), 'build', ...viteArgs],
    {
      cwd: dashboardRoot,
      env: { ...process.env, NODE_ENV: 'production', ...extraEnv },
      stdio: 'pipe',
    },
  );
  const assets = readdirSync(join(dashboardRoot, 'dist', 'assets'));
  return assets.map((asset) => readFileSync(join(dashboardRoot, 'dist', 'assets', asset), 'utf8')).join('');
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

test('aggregates named metrics without inventing missing data', () => {
  expect(deriveDashboardMetrics([{ availability: 0.99, p99_latency_ms: 200 }]))
    .toMatchObject({ availabilityPercent: 99, p99LatencyMs: 200 });
});

test('preserves missing metric values as null', () => {
  expect(deriveDashboardMetrics([{ availability: 0.99 }])).toMatchObject({
    p99LatencyMs: null,
    errorRatePercent: null,
  });
});

test('states when recommendation evidence is insufficient', () => {
  expect(deriveRecommendation({ metrics: {} }, 'Recommendation: see comparison analysis.'))
    .toMatchObject({ recommendation: null, insufficientEvidence: true });
});

test('loads only documented experiment dashboard endpoints with same-origin credentials', async () => {
  const payloads = new Map([
    ['/api/v1/experiments/demo', { experiment: { id: 'demo' } }],
    ['/api/v1/experiments/demo/metrics', { metrics_per_run: [{ availability: 1 }] }],
    ['/api/v1/experiments/demo/timeline', { timeline: [[{ elapsed: 0 }]] }],
    ['/api/v1/experiments/demo/events', { events: [{ event_type: 'fault' }] }],
    ['/api/v1/experiments/demo/analysis', { analysis: { metrics: {} } }],
  ]);
  const fetchMock = vi.fn((path, options) => Promise.resolve({
    ok: true,
    text: () => Promise.resolve(path.endsWith('/report') ? 'Recommendation: see comparison analysis.' : JSON.stringify(payloads.get(path))),
  }));
  vi.stubGlobal('fetch', fetchMock);

  const dashboard = await loadExperimentDashboard('demo');

  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    '/api/v1/experiments/demo',
    '/api/v1/experiments/demo/metrics',
    '/api/v1/experiments/demo/timeline',
    '/api/v1/experiments/demo/events',
    '/api/v1/experiments/demo/analysis',
    '/api/v1/experiments/demo/report',
  ]);
  expect(fetchMock.mock.calls.every(([, options]) => options.credentials === 'same-origin')).toBe(true);
  expect(dashboard).toMatchObject({
    experiment: { id: 'demo' },
    metrics: { availabilityPercent: 100 },
    timeline: [[{ elapsed: 0 }]],
    events: [{ event_type: 'fault' }],
    recommendation: { recommendation: null, insufficientEvidence: true },
  });
});

test('returns experiment summaries from the documented list endpoint', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    text: () => Promise.resolve(JSON.stringify({ experiments: [{ id: 'demo' }] })),
  })));

  await expect(listExperiments()).resolves.toEqual([{ id: 'demo' }]);
});

test('loads status from the documented experiment status endpoint', async () => {
  const status = {
    id: 'demo',
    status: 'RUNNING',
    error: null,
    cancellation_reason: null,
    runs: [{ run_id: 'demo-0', status: 'RUNNING' }],
  };
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    text: () => Promise.resolve(JSON.stringify(status)),
  })));

  await expect(getExperimentStatus('demo')).resolves.toEqual(status);
});

test('sends a configured local API key only in development', async () => {
  vi.stubEnv('VITE_RESILIENCELAB_API_KEY', 'local-development-key');
  const fetchMock = vi.fn(() => Promise.resolve({ ok: true, text: () => Promise.resolve('{}') }));
  vi.stubGlobal('fetch', fetchMock);

  await getJson('/api/v1/experiments');

  expect(fetchMock).toHaveBeenCalledWith('/api/v1/experiments', {
    credentials: 'same-origin',
    headers: { 'X-API-Key': 'local-development-key' },
  });
});

test('keeps the configured local API key out of the production bundle', () => {
  const bundle = buildDashboardBundle({ VITE_RESILIENCELAB_API_KEY: 'local-development-key' });

  expect(bundle).not.toContain('local-development-key');
});

test('keeps the local API key out of custom-mode production bundles', () => {
  const bundle = buildDashboardBundle(
    { VITE_RESILIENCELAB_API_KEY: 'staging-development-key' },
    ['--mode', 'staging'],
  );

  expect(bundle).not.toContain('staging-development-key');
});

test('exposes a readable non-2xx API error', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: false,
    status: 403,
    statusText: 'Forbidden',
    text: () => Promise.resolve(JSON.stringify({ detail: 'dashboard access denied' })),
  })));

  await expect(getJson('/api/v1/experiments')).rejects.toMatchObject({
    name: 'ApiError',
    status: 403,
    detail: 'dashboard access denied',
    message: 'Request failed (403): dashboard access denied',
  });
});

test('continues without events when the optional endpoint is unavailable', async () => {
  const payloads = new Map([
    ['/api/v1/experiments/demo', { experiment: { id: 'demo' } }],
    ['/api/v1/experiments/demo/metrics', { metrics_per_run: [] }],
    ['/api/v1/experiments/demo/timeline', { timeline: [] }],
    ['/api/v1/experiments/demo/analysis', { analysis: {} }],
  ]);
  vi.stubGlobal('fetch', vi.fn((path) => Promise.resolve(path.endsWith('/events')
    ? { ok: false, status: 404, statusText: 'Not Found', text: () => Promise.resolve('Not Found') }
    : { ok: true, text: () => Promise.resolve(path.endsWith('/report') ? '' : JSON.stringify(payloads.get(path))) })));

  await expect(loadExperimentDashboard('demo')).resolves.toMatchObject({
    experiment: { id: 'demo' },
    events: null,
  });
});
