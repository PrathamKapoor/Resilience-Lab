import GradientWaves from './GradientWaves';

const STATE_COPY = {
  loading: {
    title: 'Loading experiment evidence',
    body: 'Reading the selected experiment, metrics, timeline, and analysis.',
  },
  empty: {
    title: 'No experiments yet',
    body: 'Completed experiment evidence will appear here when it is available.',
  },
  error: {
    title: 'Dashboard data unavailable',
    body: 'The experiment API did not return a usable dashboard response.',
  },
  permission: {
    title: 'Permission required',
    body: 'Your current credentials cannot read this experiment.',
  },
  integrity: {
    title: 'Integrity check failed',
    body: 'This experiment cannot be presented because its recorded evidence did not pass integrity checks.',
  },
};

const KPI_DEFINITIONS = [
  ['Availability', 'availabilityPercent', '%', 2],
  ['p99 latency', 'p99LatencyMs', ' ms', 1],
  ['Error rate', 'errorRatePercent', '%', 2],
  ['Throughput', 'throughputPerSecond', ' req/s', 1],
  ['Recovery time', 'recoveryTimeSeconds', ' s', 2],
];

function formatNumber(value, suffix, digits) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Not recorded';
  return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${suffix}`;
}

function formatElapsed(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} s`
    : 'Time not recorded';
}

function findPolicy(analysis, report) {
  const analysisPolicy = typeof analysis === 'string'
    ? analysis.match(/^Policy:\s*(.+)$/im)?.[1]?.trim()
    : null;
  const reportPolicy = typeof report === 'string'
    ? report.match(/^(?:Policy:\s*|- \*\*Policy\*\*:\s*)(.+)$/im)?.[1]?.trim()
    : null;
  return analysisPolicy || reportPolicy || null;
}

function formatDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function writeExperimentToUrl(experimentId) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('experiment', experimentId);
  window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`);
}

function TopBar({ experiments, selectedId, selectedStatus, onSelect }) {
  const handleSelection = (event) => {
    writeExperimentToUrl(event.target.value);
    onSelect?.(event.target.value);
  };

  return (
    <header className="top-bar">
      <a className="wordmark" href="/dashboard/" aria-label="ResilienceLab dashboard home">
        Resilience<span>Lab</span>
      </a>
      <p className="top-bar-context">Experiment evidence</p>
      {experiments.length > 0 ? (
        <div className="experiment-control">
          <label htmlFor="experiment-selector">Experiment</label>
          <select
            id="experiment-selector"
            value={selectedId || experiments[0].id}
            onChange={handleSelection}
          >
            {experiments.map((experiment) => (
              <option key={experiment.id} value={experiment.id}>
                {experiment.name || experiment.id}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {selectedStatus ? (
        <p className="status-chip" data-state={selectedStatus.toLowerCase()}>
          <span className="status-dot" aria-hidden="true" />
          Status: {selectedStatus}
        </p>
      ) : null}
    </header>
  );
}

function StatePanel({ state, detail }) {
  const copy = STATE_COPY[state] || STATE_COPY.error;
  return (
    <section
      className={`state-panel state-panel--${state}`}
      aria-labelledby={`${state}-state-title`}
      role={state === 'loading' ? 'status' : 'alert'}
      aria-live={state === 'loading' ? 'polite' : undefined}
    >
      <p className="eyebrow">Dashboard state · {state}</p>
      <h1 id={`${state}-state-title`}>{copy.title}</h1>
      <p>{detail || copy.body}</p>
    </section>
  );
}

function KpiGrid({ metrics = {} }) {
  return (
    <section className="kpi-section" aria-labelledby="kpi-title">
      <div className="section-heading">
        <p className="eyebrow">Observed means</p>
        <h2 id="kpi-title">Run-level signals</h2>
      </div>
      <dl className="kpi-grid">
        {KPI_DEFINITIONS.map(([label, key, suffix, digits]) => (
          <div className="kpi-card" key={key}>
            <dt>{label}</dt>
            <dd>{formatNumber(metrics[key], suffix, digits)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TimelineCard({ timeline, events }) {
  const runs = Array.isArray(timeline) ? timeline.filter(Array.isArray) : [];
  const markers = (Array.isArray(events) ? events : []).filter((event) => (
    /Fault|Recover|Circuit/.test(event?.event_type || '')
  ));
  const bucketCount = runs.reduce((total, run) => total + run.length, 0);

  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <div className="section-heading section-heading--row">
        <div>
          <p className="eyebrow">Causal record</p>
          <h2 id="timeline-title">Fault &amp; recovery timeline</h2>
        </div>
        <p className="section-meta">{runs.length} runs · {bucketCount} buckets</p>
      </div>
      {markers.length > 0 ? (
        <ol className="timeline-list">
          {markers.map((event, index) => (
            <li key={`${event.sequence ?? index}-${event.event_type}`}>
              <span className="timeline-marker" aria-hidden="true" />
              <div>
                <strong>{event.event_type}</strong>
                <p>
                  {formatElapsed(event.elapsed)}
                  {event.target_service ? ` · ${event.target_service}` : ''}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-copy">No causal fault or recovery markers were recorded.</p>
      )}
    </section>
  );
}

function PolicyCard({ analysis, report, recommendation }) {
  const policy = findPolicy(analysis, report);
  const recommendationText = recommendation?.recommendation || recommendation?.evidence;
  return (
    <section className="panel policy-panel" aria-labelledby="policy-title">
      <p className="eyebrow">Decision evidence</p>
      <h2 id="policy-title">Policy rationale</h2>
      <dl className="policy-facts">
        <div>
          <dt>Recorded policy</dt>
          <dd>{policy || 'Not recorded'}</dd>
        </div>
        <div>
          <dt>Recommendation</dt>
          <dd>{recommendationText || 'No recommendation was returned by the experiment analysis.'}</dd>
        </div>
      </dl>
    </section>
  );
}

function SignalsCard({ events }) {
  const signals = Array.isArray(events) ? events.slice(-5).reverse() : [];
  return (
    <section className="panel signals-panel" aria-labelledby="signals-title">
      <p className="eyebrow">Most recent first</p>
      <h2 id="signals-title">Latest signals</h2>
      {signals.length > 0 ? (
        <ul className="signal-list">
          {signals.map((event, index) => (
            <li key={`${event.sequence ?? index}-${event.event_type}`}>
              <div>
                <strong>{event.event_type}</strong>
                {event.target_service ? <span>{event.target_service}</span> : null}
              </div>
              <time>{formatElapsed(event.elapsed)}</time>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-copy">No structured events were returned for this experiment.</p>
      )}
    </section>
  );
}

function CompletedDashboard({ data }) {
  const experiment = data.experiment || {};
  const updatedAt = formatDate(experiment.updated_at);
  const reportHref = experiment.id
    ? `/api/v1/experiments/${encodeURIComponent(experiment.id)}/report`
    : null;

  return (
    <>
      <section className="hero" aria-labelledby="experiment-title">
        <div className="hero-waves">
          <GradientWaves
            horizonColor="#E7DDFF"
            waveColor="#FF9B87"
            crestColor="#FFF7F0"
            detail="low"
            speed={0.18}
            amplitude={1.8}
            mouseInteraction={false}
          />
        </div>
        <div className="hero-content">
          <p className="eyebrow">Selected experiment · {experiment.id || 'ID not recorded'}</p>
          <h1 id="experiment-title">{experiment.name || experiment.id || 'Unnamed experiment'}</h1>
          <p className="hero-summary">
            {experiment.description || 'No experiment description was returned by the API.'}
          </p>
          <dl className="hero-meta">
            <div><dt>State</dt><dd>{experiment.status || 'Not recorded'}</dd></div>
            <div><dt>Updated</dt><dd>{updatedAt || 'Not recorded'}</dd></div>
            <div><dt>Config hash</dt><dd>{experiment.config_hash || 'Not recorded'}</dd></div>
          </dl>
        </div>
      </section>

      <KpiGrid metrics={data.metrics} />

      <div className="editorial-grid">
        <TimelineCard timeline={data.timeline} events={data.events} />
        <PolicyCard analysis={data.analysis} report={data.report} recommendation={data.recommendation} />
        <SignalsCard events={data.events} />
      </div>

      <footer className="report-footer">
        <div>
          <p className="eyebrow">Source document</p>
          <h2>Read the complete experiment record</h2>
        </div>
        {reportHref ? (
          <a className="report-link" href={reportHref} target="_blank" rel="noreferrer">
            Open full report
            <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="none">
              <path d="M4 12 12 4M6 4h6v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        ) : (
          <p>Report link unavailable.</p>
        )}
      </footer>
    </>
  );
}

export default function Dashboard({
  experiments = [],
  selectedId,
  data,
  state = 'loading',
  error,
  onSelect,
}) {
  const selectedSummary = experiments.find((experiment) => experiment.id === selectedId)
    || experiments[0];

  return (
    <div className="dashboard-app">
      <a className="skip-link" href="#dashboard-content">Skip to dashboard content</a>
      <TopBar
        experiments={experiments}
        selectedId={selectedId}
        selectedStatus={data?.experiment?.status || selectedSummary?.status}
        onSelect={onSelect}
      />
      <main className="dashboard-shell" id="dashboard-content">
        {state === 'completed' && data
          ? <CompletedDashboard data={data} />
          : <StatePanel state={state} detail={error} />}
      </main>
    </div>
  );
}
