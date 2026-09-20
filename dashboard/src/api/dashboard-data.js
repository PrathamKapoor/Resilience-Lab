import { getJson, getText } from './client';

const API_ROOT = '/api/v1/experiments';
const PAGE_SIZE = 200;
const MAX_EXPERIMENT_PAGES = 100;

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value);

function average(values) {
  const present = values.filter(isNumber);
  return present.length ? present.reduce((total, value) => total + value, 0) / present.length : null;
}

function p99Milliseconds(metric) {
  if (isNumber(metric.p99_latency_ms)) return metric.p99_latency_ms;
  return isNumber(metric.latency_p99) ? metric.latency_p99 * 1000 : null;
}

export function deriveDashboardMetrics(metrics) {
  const runs = Array.isArray(metrics) ? metrics : [];
  const availability = average(runs.map((metric) => metric?.availability));
  const errorRate = average(runs.map((metric) => metric?.error_rate));

  return {
    availabilityPercent: availability === null ? null : availability * 100,
    p99LatencyMs: average(runs.map(p99Milliseconds)),
    errorRatePercent: errorRate === null ? null : errorRate * 100,
    throughputPerSecond: average(runs.map((metric) => metric?.throughput)),
    recoveryTimeSeconds: average(runs.map((metric) => metric?.recovery_time)),
  };
}

export function deriveRecommendation(analysis, report) {
  const explicitRecommendation = typeof analysis?.recommendation === 'string'
    ? analysis.recommendation.trim()
    : '';
  const reportRecommendation = typeof report === 'string'
    ? report.match(/^Recommendation:\s*(.+)$/im)?.[1]?.trim() || ''
    : '';
  const recommendation = explicitRecommendation || reportRecommendation;
  const normalizedRecommendation = recommendation.toLowerCase().replace(/\s+/g, ' ').trim();
  const isPlaceholder = /^see (?:the )?(?:comparison )?analysis/.test(normalizedRecommendation)
    || /^see comparison and interaction analysis for evidence-based ranking\.?$/.test(normalizedRecommendation);

  if (!recommendation || isPlaceholder) {
    return {
      recommendation: null,
      insufficientEvidence: true,
      evidence: 'Insufficient recommendation evidence is available from this experiment.',
    };
  }

  return { recommendation, insufficientEvidence: false, evidence: null };
}

export async function listExperiments() {
  const experiments = [];
  let offset = 0;

  for (let page = 0; page < MAX_EXPERIMENT_PAGES; page += 1) {
    const data = await getJson(`${API_ROOT}?offset=${offset}&limit=${PAGE_SIZE}`);
    const pageExperiments = Array.isArray(data?.experiments) ? data.experiments : [];
    experiments.push(...pageExperiments);

    if (!data?.pagination?.has_more) return experiments;

    const nextOffset = offset + pageExperiments.length;
    if (nextOffset <= offset) throw new Error('Experiment pagination did not advance.');
    offset = nextOffset;
  }

  throw new Error('Experiment pagination exceeded the safe request limit.');
}

export function getExperimentStatus(id) {
  return getJson(`${API_ROOT}/${encodeURIComponent(id)}/status`);
}

export async function loadExperimentDashboard(id) {
  const experimentId = encodeURIComponent(id);
  const basePath = `${API_ROOT}/${experimentId}`;
  const [detail, metricResponse, timelineResponse, eventResponse, analysisResponse, report] = await Promise.all([
    getJson(basePath),
    getJson(`${basePath}/metrics`),
    getJson(`${basePath}/timeline`),
    getJson(`${basePath}/events`).catch((error) => {
      if (error?.status === 404) return null;
      throw error;
    }),
    getJson(`${basePath}/analysis`),
    getText(`${basePath}/report`),
  ]);
  const analysis = analysisResponse?.analysis ?? null;

  return {
    experiment: detail?.experiment ?? null,
    metrics: deriveDashboardMetrics(metricResponse?.metrics_per_run),
    timeline: timelineResponse?.timeline ?? null,
    events: eventResponse?.events ?? null,
    analysis,
    report: report ?? null,
    recommendation: deriveRecommendation(analysis, report),
  };
}
