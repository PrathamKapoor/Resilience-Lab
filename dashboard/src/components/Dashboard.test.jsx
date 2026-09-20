import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import Dashboard from './Dashboard';
import GradientWaves from './GradientWaves';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('explains an empty experiment state', () => {
  render(<Dashboard experiments={[]} state="empty" />);
  expect(screen.getByText(/no experiments yet/i)).toBeTruthy();
});

test.each([
  ['loading', 'Loading experiment evidence'],
  ['error', 'Dashboard data unavailable'],
  ['permission', 'Permission required'],
  ['integrity', 'Integrity check failed'],
])('names the %s state in text', (state, message) => {
  render(<Dashboard experiments={[]} state={state} />);
  expect(screen.getByText(message)).toBeTruthy();
});

test('renders completed experiment evidence without inventing missing values', () => {
  render(
    <Dashboard
      experiments={[
        { id: 'exp-1', name: 'Checkout resilience', status: 'completed' },
        { id: 'exp-2', name: 'Search resilience', status: 'running' },
      ]}
      selectedId="exp-1"
      state="completed"
      data={{
        experiment: {
          id: 'exp-1',
          name: 'Checkout resilience',
          description: 'Dependency latency fault under peak load.',
          status: 'completed',
          config_hash: '9ad31f',
          updated_at: '2026-09-20T08:30:00Z',
        },
        metrics: {
          availabilityPercent: 99.25,
          p99LatencyMs: 212,
          errorRatePercent: 0.75,
          throughputPerSecond: 48.4,
          recoveryTimeSeconds: null,
        },
        timeline: [[{ t: 0.5, availability: 1 }, { t: 1.5, availability: 0.91 }]],
        events: [
          { sequence: 3, event_type: 'FaultInjected', elapsed: 2.25, target_service: 'payments', metadata: {} },
          { sequence: 7, event_type: 'FaultRecovered', elapsed: 5.5, target_service: 'payments', metadata: {} },
        ],
        analysis: 'RESULT SUMMARY\n\nPolicy: bounded-retry',
        report: '# Experiment Report\n\n- **Policy**: bounded-retry',
        recommendation: {
          recommendation: null,
          insufficientEvidence: true,
          evidence: 'Insufficient recommendation evidence is available from this experiment.',
        },
      }}
    />,
  );

  expect(screen.getByRole('heading', { name: 'Checkout resilience' })).toBeTruthy();
  expect(screen.getByText('99.25%')).toBeTruthy();
  expect(screen.getByText('212 ms')).toBeTruthy();
  expect(screen.getByText('Not recorded')).toBeTruthy();
  const timeline = screen.getByRole('region', { name: /fault & recovery timeline/i });
  expect(within(timeline).getByText('FaultInjected')).toBeTruthy();
  expect(within(timeline).getByText('FaultRecovered')).toBeTruthy();
  expect(screen.getByText('bounded-retry')).toBeTruthy();
  expect(screen.getByText(/Insufficient recommendation evidence/)).toBeTruthy();
  expect(screen.getByRole('link', { name: /open full report/i })).toHaveProperty(
    'href',
    'http://localhost:3000/api/v1/experiments/exp-1/report',
  );
});

test('selects an experiment through a labelled native control', () => {
  const onSelect = vi.fn();
  window.history.replaceState({}, '', '/dashboard/');
  render(
    <Dashboard
      experiments={[
        { id: 'exp-1', name: 'Experiment one', status: 'completed' },
        { id: 'exp-2', name: 'Experiment two', status: 'running' },
      ]}
      selectedId="exp-1"
      state="loading"
      onSelect={onSelect}
    />,
  );

  fireEvent.change(screen.getByRole('combobox', { name: 'Experiment' }), {
    target: { value: 'exp-2' },
  });
  expect(onSelect).toHaveBeenCalledWith('exp-2');
  expect(window.location.search).toBe('?experiment=exp-2');
});

test('uses a static decorative fallback when reduced motion is requested', () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));

  const { container } = render(<GradientWaves detail="low" speed={0.18} />);
  const decoration = container.querySelector('[aria-hidden="true"]');

  expect(decoration?.getAttribute('data-motion')).toBe('static');
  expect(decoration?.querySelector('canvas')).toBeNull();
});
