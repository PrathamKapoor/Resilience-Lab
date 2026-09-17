# Quickstart

## Install

```bash
python -m pip install -e ".[dev]"
```

## Validate a configuration

```bash
resiliencelab validate configs/example.yaml
```

## Run an experiment

```bash
resiliencelab run configs/example.yaml --store ./results
```

This writes an integrity-verified artifact bundle under `./results/<experiment-id>/`
(configuration, environment, raw records, analysis, timeline, report, content-integrity manifest).

## Read the report

```bash
resiliencelab report exp_demo --store ./results
```

## Compare policies

```bash
resiliencelab compare exp_a exp_b --store ./results
```

## Reproduce a result

```bash
resiliencelab reproduce exp_demo --store ./results
```

## Run a benchmark

```bash
resiliencelab benchmark RL-BENCH-003 --repetitions 1
```

## Run a factorial matrix

```bash
resiliencelab matrix configs/example.yaml --store ./results
```

## Start the API

```bash
uvicorn resiliencelab.api.app:app --host 0.0.0.0 --port 8000
```

OpenAPI docs are served at `/docs`.
