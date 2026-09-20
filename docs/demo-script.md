# 180-second SIH judge demo: fault to evidence

## Before the judges arrive

Use the existing, deterministic burst-outage configuration
[`configs/example.yaml`](../configs/example.yaml). It injects `http_503`
faults against `payment_service` in burst mode, with exponential backoff,
full jitter, and a circuit breaker. Its five sequential 60-second repetitions
mean it must be completed before the timed demonstration.

Start FastAPI in local mode and Vite in separate terminals:

```bash
uvicorn resiliencelab.api.app:app --host 127.0.0.1 --port 8000
```

```bash
npm --prefix dashboard ci
npm --prefix dashboard run dev
```

Submit and run the existing configuration through the existing API client,
then wait for `completed`:

```bash
resiliencelab server submit configs/example.yaml
resiliencelab server run exp_demo
resiliencelab server status exp_demo
```

Keep the API and Vite terminals running. Open
`http://127.0.0.1:5173/dashboard/?experiment=exp_demo`, refresh after the
status is `completed`, and keep the terminal that reported completion visible
as a fallback. This local demonstration intentionally uses local FastAPI mode;
the shipped Compose server mode requires API-key authentication and has no
browser credential UI.

Do not begin the clock if the dashboard says “No experiments yet,” “Dashboard
data unavailable,” or the experiment status is not completed.

## Timed walkthrough

| Time | Screen action | What to say, constrained to recorded evidence |
| --- | --- | --- |
| 0:00–0:20 | Show the experiment header and status. | “ResilienceLab is a controlled in-process simulation. This is `exp_demo`, a completed experiment with a recorded configuration hash, not production telemetry.” |
| 0:20–0:45 | Point to **Fault & recovery timeline** and **Latest signals**. | “The configuration targets `payment_service` with burst `http_503` faults. Here we inspect the recorded `FaultInjected` and, when present, `FaultRecovered` events rather than claiming a fault that was not observed.” |
| 0:45–1:15 | Read the five KPI cards. | “These are arithmetic means over the completed run measurements: availability, p99 latency, error rate, throughput, and recovery time. Any card saying ‘Not recorded’ is deliberately not estimated. The dashboard has no defined resilience-score or error-budget value to show.” |
| 1:15–1:40 | Return to the causal markers. | “Recovery is evidenced by recorded recovery or circuit-transition events and, where measured, recovery time. If no matching marker is present, the honest conclusion is that this run did not record that signal.” |
| 1:40–2:05 | Open **Policy rationale**. | “This reports the policy recorded with this experiment. A recommendation is displayed only if analysis or the report contains an explicit, non-placeholder recommendation. Otherwise the card says evidence is insufficient; this is not an adaptive policy ranking.” |
| 2:05–2:35 | Point to config hash and the full report link. | “The configuration hash ties this view to its stored experiment. The report and event stream provide the detail behind the cards.” |
| 2:35–3:00 | Show the completion terminal and name the repeat procedure. | “Repeat the same submission and run commands with the same configuration. Seeds, configuration, raw records, analysis, timeline, and report are retained by the experiment workflow; wall-clock metrics can still vary. That is why this is evidence for a controlled experiment, not a promise of identical production behaviour.” |

## Safe fallback

If the API is still running, wait for its status to become `completed`; do not
present partial metrics as final results. If a metric, recovery marker, report,
or explicit recommendation is absent, say it was not recorded or evidence is
insufficient. The reproducibility and integrity limits are documented in
[`reproducibility.md`](reproducibility.md) and the event meaning in
[`events.md`](events.md).
