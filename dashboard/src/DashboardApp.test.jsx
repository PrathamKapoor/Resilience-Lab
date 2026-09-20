import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import {
  getExperimentStatus,
  listExperiments,
  loadExperimentDashboard,
} from './api/dashboard-data';
import DashboardApp, { POLL_INTERVAL_MS, stateForError } from './DashboardApp';

vi.mock('./api/dashboard-data', () => ({
  getExperimentStatus: vi.fn(),
  listExperiments: vi.fn(),
  loadExperimentDashboard: vi.fn(),
}));

const EXPERIMENTS = [
  { id: 'exp-1', name: 'Experiment one', status: 'COMPLETED' },
  { id: 'exp-2', name: 'Experiment two', status: 'COMPLETED' },
];

function completedDashboard(id) {
  const experiment = EXPERIMENTS.find((item) => item.id === id);
  return {
    experiment: {
      ...experiment,
      description: `Description for ${experiment.name}.`,
      config_hash: `hash-${id}`,
      updated_at: '2026-09-20T08:30:00Z',
    },
    metrics: {},
    timeline: [],
    events: [],
    analysis: 'Policy: bounded-retry',
    report: `# ${experiment.name}`,
    recommendation: {
      recommendation: null,
      insufficientEvidence: true,
      evidence: 'Insufficient recommendation evidence is available from this experiment.',
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function setDocumentVisibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
  Object.defineProperty(document, 'hidden', { configurable: true, value: state === 'hidden' });
  act(() => document.dispatchEvent(new Event('visibilitychange')));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  window.history.replaceState({}, '', '/dashboard/');
  delete document.visibilityState;
  delete document.hidden;
});

test('restores the selected experiment from the initial URL', async () => {
  window.history.replaceState({}, '', '/dashboard/?experiment=exp-2');
  listExperiments.mockResolvedValue(EXPERIMENTS);
  loadExperimentDashboard.mockImplementation((id) => Promise.resolve(completedDashboard(id)));

  render(<DashboardApp />);

  expect(await screen.findByRole('heading', { name: 'Experiment two' })).toBeTruthy();
  expect(screen.getByRole('combobox', { name: 'Experiment' }).value).toBe('exp-2');
  expect(window.location.search).toBe('?experiment=exp-2');
});

test('loads a direct URL experiment even when it is absent from the listed page', async () => {
  window.history.replaceState({}, '', '/dashboard/?experiment=exp-2');
  listExperiments.mockResolvedValue([EXPERIMENTS[0]]);
  getExperimentStatus.mockResolvedValue({ id: 'exp-2', status: 'COMPLETED' });
  loadExperimentDashboard.mockResolvedValue(completedDashboard('exp-2'));

  render(<DashboardApp />);

  expect(await screen.findByRole('heading', { name: 'Experiment two' })).toBeTruthy();
  expect(loadExperimentDashboard).toHaveBeenCalledWith('exp-2');
  expect(window.location.search).toBe('?experiment=exp-2');
});

test('follows browser back and forward selection changes', async () => {
  listExperiments.mockResolvedValue(EXPERIMENTS);
  loadExperimentDashboard.mockImplementation((id) => Promise.resolve(completedDashboard(id)));
  render(<DashboardApp />);
  expect(await screen.findByRole('heading', { name: 'Experiment one' })).toBeTruthy();

  window.history.pushState({}, '', '/dashboard/?experiment=exp-2');
  act(() => window.dispatchEvent(new PopStateEvent('popstate')));

  expect(await screen.findByRole('heading', { name: 'Experiment two' })).toBeTruthy();
  expect(screen.getByRole('combobox', { name: 'Experiment' }).value).toBe('exp-2');
});

test.each([
  [{ status: 401 }, 'permission'],
  [{ status: 403 }, 'permission'],
  [{ status: 409 }, 'integrity'],
  [{ message: 'Artifact checksum mismatch' }, 'integrity'],
  [{ status: 500 }, 'error'],
])('maps API failures to an explicit dashboard state', (error, expectedState) => {
  expect(stateForError(error)).toBe(expectedState);
});

test('pauses bounded status polling while hidden and stops at completion', async () => {
  vi.useFakeTimers();
  setDocumentVisibility('visible');
  listExperiments.mockResolvedValue([
    { id: 'exp-1', name: 'Experiment one', status: 'RUNNING' },
  ]);
  getExperimentStatus
    .mockResolvedValueOnce({ id: 'exp-1', status: 'RUNNING' })
    .mockResolvedValueOnce({ id: 'exp-1', status: 'COMPLETED' });
  loadExperimentDashboard.mockResolvedValue(completedDashboard('exp-1'));

  render(<DashboardApp />);
  await flushPromises();
  expect(getExperimentStatus).toHaveBeenCalledTimes(1);
  expect(loadExperimentDashboard).not.toHaveBeenCalled();

  setDocumentVisibility('hidden');
  await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2));
  expect(getExperimentStatus).toHaveBeenCalledTimes(1);

  setDocumentVisibility('visible');
  await flushPromises();
  expect(getExperimentStatus).toHaveBeenCalledTimes(2);
  expect(loadExperimentDashboard).toHaveBeenCalledWith('exp-1');
  expect(screen.getByRole('heading', { name: 'Experiment one' })).toBeTruthy();

  await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2));
  expect(getExperimentStatus).toHaveBeenCalledTimes(2);
});

test('ignores an old status response after the selection changes', async () => {
  setDocumentVisibility('visible');
  const oldStatus = deferred();
  listExperiments.mockResolvedValue([
    { id: 'exp-1', name: 'Experiment one', status: 'RUNNING' },
    EXPERIMENTS[1],
  ]);
  getExperimentStatus.mockReturnValue(oldStatus.promise);
  loadExperimentDashboard.mockImplementation((id) => Promise.resolve(completedDashboard(id)));

  render(<DashboardApp />);
  await flushPromises();
  expect(getExperimentStatus).toHaveBeenCalledWith('exp-1');

  fireEvent.change(screen.getByRole('combobox', { name: 'Experiment' }), {
    target: { value: 'exp-2' },
  });
  expect(await screen.findByRole('heading', { name: 'Experiment two' })).toBeTruthy();

  oldStatus.resolve({ id: 'exp-1', status: 'COMPLETED' });
  await flushPromises();
  expect(screen.getByRole('heading', { name: 'Experiment two' })).toBeTruthy();
  expect(loadExperimentDashboard).not.toHaveBeenCalledWith('exp-1');
});

test('does not continue polling after unmount', async () => {
  vi.useFakeTimers();
  setDocumentVisibility('visible');
  const status = deferred();
  listExperiments.mockResolvedValue([
    { id: 'exp-1', name: 'Experiment one', status: 'RUNNING' },
  ]);
  getExperimentStatus.mockReturnValue(status.promise);

  const { unmount } = render(<DashboardApp />);
  await flushPromises();
  expect(getExperimentStatus).toHaveBeenCalledTimes(1);
  unmount();

  status.resolve({ id: 'exp-1', status: 'RUNNING' });
  await flushPromises();
  await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2));
  expect(getExperimentStatus).toHaveBeenCalledTimes(1);
  expect(loadExperimentDashboard).not.toHaveBeenCalled();
});
