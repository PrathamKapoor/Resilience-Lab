import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

function Dashboard() {
  return <main className="dashboard-shell">Resilience Dashboard</main>;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Dashboard />
  </StrictMode>,
);
