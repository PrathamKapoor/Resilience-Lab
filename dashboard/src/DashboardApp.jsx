import { useCallback, useEffect, useState } from 'react';
import {
  getExperimentStatus,
  listExperiments,
  loadExperimentDashboard,
} from './api/dashboard-data';
import Dashboard from './components/Dashboard';

export const POLL_INTERVAL_MS = 5_000;

const COMPLETED_STATUS = 'completed';
const FAILED_STATUSES = new Set(['failed', 'cancelled', 'canceled']);

function normalizeStatus(status) {
  return typeof status === 'string' ? status.toLowerCase() : '';
}

export function stateForError(error) {
  if (error?.status === 401 || error?.status === 403) return 'permission';
  const detail = `${error?.detail || ''} ${error?.message || ''}`;
  if (error?.status === 409 || /integrity|corrupt|checksum|hash mismatch/i.test(detail)) {
    return 'integrity';
  }
  return 'error';
}

function selectedExperimentFromUrl(experiments) {
  const requestedId = new URL(window.location.href).searchParams.get('experiment');
  return experiments.some((experiment) => experiment.id === requestedId)
    ? requestedId
    : experiments[0]?.id || null;
}

function replaceSelectedExperiment(experimentId) {
  if (!experimentId) return;
  const url = new URL(window.location.href);
  if (url.searchParams.get('experiment') === experimentId) return;
  url.searchParams.set('experiment', experimentId);
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
}

export default function DashboardApp() {
  const [experiments, setExperiments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    listExperiments()
      .then((items) => {
        if (!active) return;
        setExperiments(items);
        if (items.length === 0) {
          setState('empty');
          return;
        }
        const nextId = selectedExperimentFromUrl(items);
        replaceSelectedExperiment(nextId);
        setSelectedId(nextId);
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.message);
        setState(stateForError(requestError));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return undefined;
    let active = true;
    let finished = false;
    let requestInFlight = false;
    let pollTimer;

    setState('loading');
    setError(null);
    setData(null);

    const fail = (requestError) => {
      if (!active) return;
      finished = true;
      setError(requestError?.message || requestError?.error || requestError?.cancellation_reason || null);
      setState(stateForError(requestError));
    };

    const loadCompletedDashboard = async () => {
      finished = true;
      try {
        const dashboardData = await loadExperimentDashboard(selectedId);
        if (!active) return;
        setData(dashboardData);
        setState('completed');
      } catch (requestError) {
        fail(requestError);
      }
    };

    const schedulePoll = () => {
      if (!active || finished || document.hidden) return;
      clearTimeout(pollTimer);
      pollTimer = window.setTimeout(pollStatus, POLL_INTERVAL_MS);
    };

    const pollStatus = async () => {
      if (!active || finished || requestInFlight || document.hidden) return;
      requestInFlight = true;
      try {
        const statusResponse = await getExperimentStatus(selectedId);
        if (!active) return;
        const nextStatus = normalizeStatus(statusResponse?.status);
        if (statusResponse?.status) {
          setExperiments((items) => items.map((experiment) => (
            experiment.id === selectedId
              ? { ...experiment, status: statusResponse.status }
              : experiment
          )));
        }

        if (nextStatus === COMPLETED_STATUS) {
          await loadCompletedDashboard();
        } else if (FAILED_STATUSES.has(nextStatus)) {
          fail(statusResponse);
        } else {
          schedulePoll();
        }
      } catch (requestError) {
        fail(requestError);
      } finally {
        requestInFlight = false;
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        clearTimeout(pollTimer);
      } else if (!finished && !requestInFlight) {
        pollStatus();
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    const selectedStatus = normalizeStatus(
      experiments.find((experiment) => experiment.id === selectedId)?.status,
    );
    if (selectedStatus === COMPLETED_STATUS) {
      loadCompletedDashboard();
    } else if (FAILED_STATUSES.has(selectedStatus)) {
      fail({});
    } else {
      pollStatus();
    }

    return () => {
      active = false;
      clearTimeout(pollTimer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [selectedId]);

  useEffect(() => {
    const onPopState = () => {
      const requestedId = selectedExperimentFromUrl(experiments);
      if (requestedId && requestedId !== selectedId) setSelectedId(requestedId);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [experiments, selectedId]);

  const selectExperiment = useCallback((experimentId) => {
    setSelectedId(experimentId);
  }, []);

  return (
    <Dashboard
      experiments={experiments}
      selectedId={selectedId}
      data={data}
      state={state}
      error={error}
      onSelect={selectExperiment}
    />
  );
}
