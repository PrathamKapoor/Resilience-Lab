import { StrictMode, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { listExperiments, loadExperimentDashboard } from './api/dashboard-data';
import Dashboard from './components/Dashboard';
import './styles.css';

function stateForError(error) {
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

function DashboardApp() {
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
    setState('loading');
    setError(null);
    setData(null);
    loadExperimentDashboard(selectedId)
      .then((dashboardData) => {
        if (!active) return;
        setData(dashboardData);
        setState('completed');
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.message);
        setState(stateForError(requestError));
      });
    return () => {
      active = false;
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

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <DashboardApp />
  </StrictMode>,
);
