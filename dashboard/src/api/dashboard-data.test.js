import { afterEach, expect, test, vi } from 'vitest';
import {
  deriveDashboardMetrics,
  deriveRecommendation,
  listExperiments,
  loadExperimentDashboard,
} from './dashboard-data';

afterEach(() => {
  vi.unstubAllGlobals();
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
