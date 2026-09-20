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

Submit and run the existing configuration through the existing API client.
Wait until the terminal's `resiliencelab server status exp_demo` response says
`completed`:

```bash
resiliencelab server submit configs/example.yaml
resiliencelab server run exp_demo
resiliencelab server status exp_demo
```

Keep the API and Vite terminals running. Open
`http://127.0.0.1:5173/dashboard/?experiment=exp_demo`, refresh after the
terminal reports `completed`, and keep that terminal visible. This local mode
keeps results only in FastAPI memory. Its dashboard experiment header may still
say `created` and show no config hash after completion, so neither field is
evidence for the timed walkthrough. Open the full report to show its recorded
`Config SHA256`. This local demonstration intentionally uses local FastAPI
mode; the shipped Compose server mode requires API-key authentication and has
no browser credential UI.

Do not begin the clock if the dashboard says “No experiments yet,” “Dashboard
data unavailable,” or the completion terminal does not say `completed`.

## Timed walkthrough

| Time | Screen action | What to say, constrained to recorded evidence |
| --- | --- | --- |
| 0:00–0:20 | Show the selected experiment and the completion terminal. | “ResilienceLab is a controlled in-process simulation. The terminal reports this local in-memory `exp_demo` run completed; the dashboard header can still say `created`, so I will not use it as lifecycle evidence.” |
| 0:20–0:45 | Point to **Fault & recovery timeline** and **Latest signals**. | “The configuration targets `payment_service` with burst `http_503` faults. Here we inspect the recorded `FaultInjected` and, when present, `FaultRecovered` events rather than claiming a fault that was not observed.” |
| 0:45–1:15 | Read the five KPI cards. | “These are arithmetic means over the completed run measurements: availability, p99 latency, error rate, throughput, and recovery time. Any card saying ‘Not recorded’ is deliberately not estimated. The dashboard has no defined resilience-score or error-budget value to show.” |
| 1:15–1:40 | Return to the causal markers. | “Recovery is evidenced by recorded recovery or circuit-transition events and, where measured, recovery time. If no matching marker is present, the honest conclusion is that this run did not record that signal.” |
| 1:40–2:05 | Open **Policy rationale**. | “This reports the policy recorded with this experiment. A recommendation is displayed only if analysis or the report contains an explicit, non-placeholder recommendation. Otherwise the card says evidence is insufficient; this is not an adaptive policy ranking.” |
| 2:05–2:35 | Open the full report and point to `Config SHA256`. | “This report records the configuration hash for the completed local result. The report and event stream provide the detail behind the cards; the empty local header hash is not a substitute.” |
| 2:35–3:00 | Show the completion terminal and name the persistent repeat procedure. | “Repeat these API commands while this local process stays up. Local results disappear on restart. For persistent configuration, raw records, analysis, timelines, report, and manifest, use the CLI or server experiment workflow. Wall-clock metrics can still vary, so this is evidence for a controlled experiment, not a promise of identical production behaviour.” |

## Safe fallback

If the API is still running, wait for its status to become `completed`; do not
present partial metrics as final results. If a metric, recovery marker, report,
or explicit recommendation is absent, say it was not recorded or evidence is
insufficient. The reproducibility and integrity limits are documented in
[`reproducibility.md`](reproducibility.md) and the event meaning in
[`events.md`](events.md).
