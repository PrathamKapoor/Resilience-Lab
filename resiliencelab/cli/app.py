"""ResilienceLab command-line interface."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from resiliencelab.analysis.events import causal_trace, filter_events
from resiliencelab.core.config import ConfigValidationError, load_yaml
from resiliencelab.core.schema import ExperimentSpec
from resiliencelab.events import event_from_dict
from resiliencelab.experiments.artifacts import write_artifacts
from resiliencelab.experiments.benchmarks import normalize_benchmark_name, resolve_benchmark_path
from resiliencelab.experiments.report import automatic_analysis
from resiliencelab.experiments.result import ExperimentResult
from resiliencelab.experiments.runner import ExperimentRunner

app = typer.Typer(help="ResilienceLab — reproducible resilience experimentation platform.")
console = Console()
DEFAULT_STORE = Path("results")


def _err(message: str) -> NoReturn:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _store_for(store: str | Path | None) -> Path:
    return Path(store) if store else DEFAULT_STORE


@app.command()
def init(
    directory: Annotated[str, typer.Argument()] = ".",
) -> None:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / "configs").mkdir(exist_ok=True)
    (target / "results").mkdir(exist_ok=True)
    example = """experiment:
  id: exp_demo
  name: retry-jitter-under-burst-failure
  version: 1
workload:
  type: closed_loop
  clients: 50
  arrival_rate: 200
  duration: 60s
  warmup: 10s
failure:
  - target: payment_service
    type: http_503
    mode: burst
    probability: 0.30
    duration: 20s
policy:
  retry:
    enabled: true
    max_attempts: 3
  backoff:
    type: exponential
    base: 100ms
    maximum: 5s
    jitter: full
  circuit_breaker:
    enabled: true
    threshold: 10
    recovery_window: 15s
  timeout:
    total: 1s
  concurrency:
    enabled: true
    limit: 50
repetitions:
  count: 5
  seed_strategy: deterministic
"""
    (target / "configs" / "example.yaml").write_text(example, encoding="utf-8")
    console.print(f"[green]Initialized[/green] ResilienceLab workspace at {target.resolve()}")


@app.command()
def validate(
    path: Annotated[str, typer.Argument(help="Path to experiment YAML")],
) -> None:
    try:
        spec = load_yaml(path)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
    console.print(f"[green]Valid[/green] experiment `{spec.id}` ({spec.name})")
    console.print(f"  workload: {spec.workload.type.value}, {spec.workload.clients} clients")
    console.print(f"  failures: {[f'{f.type.value}/{f.mode.value}' for f in spec.failure]}")
    console.print(f"  repetitions: {spec.repetitions.count}")


@app.command()
def run(
    path: Annotated[str, typer.Argument(help="Path to experiment YAML")],
    store: Annotated[str | None, typer.Option(help="Results directory")] = None,
    repetitions: Annotated[int | None, typer.Option(help="Override repetition count")] = None,
) -> None:
    try:
        spec = load_yaml(path)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
    if repetitions is not None:
        spec.repetitions.count = repetitions
    result = _run_spec(spec)
    _store_result(result, _store_for(store))
    console.print(f"[green]Completed[/green] `{spec.id}` with policy `{result.policy_name}`")
    _print_runs(result)


def _run_spec(spec: ExperimentSpec) -> ExperimentResult:
    runner = ExperimentRunner()
    return asyncio.run(runner.run_async(spec))


def _store_result(result: ExperimentResult, store: Path) -> None:
    base = store / result.experiment_id
    write_artifacts(result, base)
    console.print(f"Artifacts written to {base.resolve()}")


def _print_runs(result: ExperimentResult) -> None:
    table = Table(title=f"Repetitions for {result.experiment_id}")
    for column in ("seed", "availability", "throughput", "p95", "p99", "amplification", "recovery"):
        table.add_column(column, justify="right")
    for run in result.runs:
        m = run.primary_metrics()
        table.add_row(
            str(run.seed),
            f"{m['availability']:.4f}",
            f"{m['throughput']:.1f}",
            f"{m['latency_p95']:.4f}",
            f"{m['latency_p99']:.4f}",
            f"{m['amplification']:.2f}",
            f"{m['recovery_time']:.1f}",
        )
    console.print(table)


@app.command()
def report(
    experiment_id: Annotated[str, typer.Argument()],
    store: Annotated[str | None, typer.Option()] = None,
) -> None:
    base = _store_for(store) / experiment_id
    report_path = base / "report" / "report.md"
    if not report_path.exists():
        _err(f"no report found for `{experiment_id}` (searched {base})")
    console.print(report_path.read_text(encoding="utf-8"))


def _load_events(base: Path) -> list[Any]:
    events: list[Any] = []
    raw_dir = base / "raw"
    if not raw_dir.exists():
        return events
    for path in sorted(raw_dir.glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(event_from_dict(json.loads(line)))
    return events


@app.command()
def events(
    experiment_id: Annotated[str, typer.Argument()],
    store: Annotated[str | None, typer.Option()] = None,
    event_type: Annotated[str | None, typer.Option("--type")] = None,
    service: Annotated[str | None, typer.Option("--service")] = None,
    request: Annotated[int | None, typer.Option("--request")] = None,
    trace: Annotated[bool, typer.Option("--trace")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 100,
) -> None:
    base = _store_for(store) / experiment_id
    all_events = _load_events(base)
    if not all_events:
        _err(f"no events found for `{experiment_id}` (searched {base})")
    filtered = filter_events(
        all_events,
        event_type=event_type,
        service=service,
        request_id=request,
    )
    if trace:
        console.print(causal_trace(filtered, limit=limit))
        return
    for event in filtered[:limit]:
        console.print(
            f"[dim]{event.elapsed:8.3f}[/dim] {event.event_type} "
            f"req={event.request_id} {event.target_service or ''}".rstrip()
        )
    console.print(f"[dim]{len(filtered)} event(s)[/dim]")


@app.command()
def compare(
    experiment_ids: Annotated[list[str], typer.Argument(help="Two or more experiment IDs")],
    store: Annotated[str | None, typer.Option()] = None,
    paired: Annotated[bool, typer.Option("--paired", help="Match replicates by index")] = False,
) -> None:
    if len(experiment_ids) < 2:
        _err("compare requires at least two experiment IDs")
    experiments: list[dict[str, Any]] = []
    for experiment_id in experiment_ids:
        summary_path = _store_for(store) / experiment_id / "experiment.json"
        if not summary_path.exists():
            _err(f"no results for `{experiment_id}`")
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        experiments.append(data)
    from resiliencelab.analysis.comparison import build_comparison, build_paired_comparison

    comparison = build_comparison(experiments)
    table = Table(title="Condition means (n = repetitions)")
    table.add_column("metric", justify="right")
    for experiment in comparison["experiments"]:
        table.add_column(experiment["name"], justify="right")
    metrics = [
        "availability",
        "throughput",
        "latency_p95",
        "latency_p99",
        "amplification",
        "recovery_time",
    ]
    rows = comparison["experiments"]
    for metric in metrics:
        table.add_row(
            metric,
            *[f"{row[metric]['mean']:.4f} (n={int(row[metric].get('n', 0))})" for row in rows],
        )
    console.print(table)

    if paired and len(experiments) >= 2:
        paired_result = build_paired_comparison(experiments[0], experiments[1], metrics)
        console.print(
            f"\nPaired difference ({paired_result['reference']} - {paired_result['versus']}, "
            f"matched replicates n={paired_result['n_matched']}):"
        )
        for metric in metrics:
            stats = paired_result["metrics"][metric]
            console.print(
                f"  {metric}: Δ={stats['mean_difference']:.4f} "
                f"95% CI [{stats['ci_low']:.4f}, {stats['ci_high']:.4f}], "
                f"d={stats['cohens_d_paired']:.3f}"
            )

    if "effects" in comparison:
        console.print("\nEffect sizes (Cohen's d) versus baseline:")
        for effect in comparison["effects"]:
            console.print(f"  {effect['versus']}:")
            for metric in metrics:
                key = f"{metric}_cohens_d"
                if key in effect:
                    console.print(
                        f"    {metric}: {effect[key]:.3f} (n={effect.get(f'{metric}_n', 0)})"
                    )


@app.command()
def reproduce(
    experiment_id: Annotated[str, typer.Argument()],
    store: Annotated[str | None, typer.Option()] = None,
    output: Annotated[str | None, typer.Option(help="Store reproduction under new id")] = None,
) -> None:
    base = _store_for(store) / experiment_id
    config_path = base / "configuration.yaml"
    if not config_path.exists():
        _err(f"no configuration found for `{experiment_id}`")
    spec = load_yaml(config_path)
    result = _run_spec(spec)
    out_base = _store_for(store) / (output or f"{experiment_id}-repro")
    write_artifacts(result, out_base)
    console.print(f"Reproduction stored at {out_base.resolve()}")
    console.print(f"\n{automatic_analysis(result)}")


@app.command()
def benchmark(
    name: Annotated[str, typer.Argument(help="Benchmark name (e.g. RL-BENCH-003)")],
    repetitions: Annotated[int | None, typer.Option()] = None,
    store: Annotated[str | None, typer.Option()] = None,
    benchmarks_dir: Annotated[str | None, typer.Option()] = None,
) -> None:
    resolved = resolve_benchmark_path(normalize_benchmark_name(name), benchmarks_dir)
    if resolved is None:
        _err(f"unknown benchmark `{name}`")
    spec = load_yaml(resolved)
    if repetitions is not None:
        spec.repetitions.count = repetitions
    result = _run_spec(spec)
    _store_result(result, _store_for(store))
    console.print(f"[green]Benchmark {name} complete[/green] — policy `{result.policy_name}`")
    _print_runs(result)


@app.command("matrix")
def matrix(
    path: Annotated[str, typer.Argument(help="Base experiment YAML")],
    factors: Annotated[str | None, typer.Option(help="JSON file of factor values")] = None,
    store: Annotated[str | None, typer.Option()] = None,
    metric: Annotated[str, typer.Option(help="Metric for main effects")] = "availability",
) -> None:
    spec = load_yaml(path)
    factor_map = _load_factors(factors) if factors else None
    from resiliencelab.analysis.design import build_design, interaction_effect, main_effect
    from resiliencelab.experiments.factorial import CORE_FACTORS

    effective_factors = factor_map or CORE_FACTORS
    conditions = build_design(spec, effective_factors)
    console.print(f"Generated {len(conditions)} experiment conditions")
    entries: list[dict[str, Any]] = []
    observations: dict[str, dict[str, list[float]]] = {}
    for condition in conditions:
        console.print(f"  running {condition.condition_id} ...")
        result = _run_spec(condition.spec)
        _store_result(result, _store_for(store))
        entry = result.as_comparison_entry()
        entry["condition_id"] = condition.condition_id
        entries.append(entry)
        for row in entry["metrics_per_run"]:
            for metric_name, value in row.items():
                observations.setdefault(metric_name, {}).setdefault(
                    condition.condition_id, []
                ).append(float(value))

    from resiliencelab.analysis.comparison import build_comparison

    comparison = build_comparison(entries)
    comparison_path = _store_for(store) / "matrix_comparison.json"
    comparison_path.write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")

    design_doc = {
        "analysis_version": comparison.get("analysis_version"),
        "base_experiment": spec.id,
        "factors": effective_factors,
        "conditions": [
            {
                "condition_id": c.condition_id,
                "index": c.index,
                "factors": c.factors,
                "label": c.label(),
                "spec_id": c.spec.id,
            }
            for c in conditions
        ],
    }
    design_path = _store_for(store) / "matrix_design.json"
    design_path.write_text(json.dumps(design_doc, indent=2, default=str), encoding="utf-8")

    effects: dict[str, Any] = {}
    condition_observations = observations.get(metric, {})
    effects["metric"] = metric
    effects["main_effects"] = [
        main_effect(conditions, condition_observations, factor) for factor in effective_factors
    ]
    binary_pairs = []
    factor_names = list(effective_factors)
    for i, fa in enumerate(factor_names):
        for fb in factor_names[i + 1 :]:
            a_levels = {c.factors.get(fa) for c in conditions}
            b_levels = {c.factors.get(fb) for c in conditions}
            if len(a_levels) == 2 and len(b_levels) == 2:
                binary_pairs.append((fa, fb))
    for fa, fb in binary_pairs:
        key = f"interaction_{fa}_x_{fb}"
        try:
            effects[key] = interaction_effect(conditions, condition_observations, fa, fb)
        except ValueError:
            continue
    effects_path = _store_for(store) / "matrix_effects.json"
    effects_path.write_text(json.dumps(effects, indent=2, default=str), encoding="utf-8")
    console.print(f"Comparison written to {comparison_path.resolve()}")
    console.print(f"Design written to {design_path.resolve()}")
    console.print(f"Effects written to {effects_path.resolve()}")


def _load_factors(path: str) -> dict[str, Any]:
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _err("factors file must contain a mapping of path -> list of values")
    return dict(raw)


server_app = typer.Typer(help="Server-backed commands (requires PostgreSQL + Redis).")
app.add_typer(server_app, name="server")


def _server_client() -> Any:
    import httpx

    base_url = os.environ.get("RESILIENCELAB_API_URL", "http://127.0.0.1:8000")
    return httpx.Client(base_url=base_url, timeout=120.0)


@server_app.command("submit")
def server_submit(
    path: Annotated[str, typer.Argument(help="Path to experiment YAML")],
    api_url: Annotated[str | None, typer.Option(help="API server URL")] = None,
) -> None:
    spec = load_yaml(path)
    import yaml

    config_data = {"experiment": {"id": spec.id, "name": spec.name, "version": spec.version}}
    config_data.update(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    client = _server_client()
    response = client.post("/api/v1/experiments", json={"config": config_data})
    if response.status_code != 201:
        _err(f"server error: {response.text}")
    data = response.json()
    console.print(
        f"[green]Queued[/green] experiment `{data['id']}` as {data.get('status', 'queued')}"
    )


@server_app.command("status")
def server_status(
    experiment_id: Annotated[str, typer.Argument()],
) -> None:
    client = _server_client()
    response = client.get(f"/api/v1/experiments/{experiment_id}/status")
    if response.status_code == 404:
        _err(f"experiment `{experiment_id}` not found")
    data = response.json()
    table = Table(title=f"Experiment {data['id']}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Status", data["status"])
    if data.get("error"):
        table.add_row("Error", data["error"])
    for run in data.get("runs", []):
        table.add_row(f"  {run['run_id']}", run["status"])
    console.print(table)


@server_app.command("list")
def server_list(
    status: Annotated[str | None, typer.Option(help="Filter by status")] = None,
) -> None:
    client = _server_client()
    params: dict[str, Any] = {}
    if status:
        params["status"] = status
    response = client.get("/api/v1/experiments", params=params)
    data = response.json()
    table = Table(title="Experiments")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Created")
    for exp in data.get("experiments", []):
        table.add_row(exp["id"], exp.get("name", ""), exp["status"], exp.get("created_at", "")[:19])
    console.print(table)


@server_app.command("run")
def server_run(
    experiment_id: Annotated[str, typer.Argument()],
) -> None:
    client = _server_client()
    response = client.post(f"/api/v1/experiments/{experiment_id}/run")
    if response.status_code == 404:
        _err(f"experiment `{experiment_id}` not found")
    if response.status_code == 409:
        _err(response.json().get("detail", "conflict"))
    data = response.json()
    console.print(f"[green]Queued[/green] experiment `{data['id']}` for execution")


@server_app.command("cancel")
def server_cancel(
    experiment_id: Annotated[str, typer.Argument()],
) -> None:
    client = _server_client()
    response = client.post(f"/api/v1/experiments/{experiment_id}/cancel")
    if response.status_code == 404:
        _err(f"experiment `{experiment_id}` not found")
    data = response.json()
    console.print(f"[yellow]Cancelled[/yellow] experiment `{data['id']}`")


@server_app.command("health")
def server_health() -> None:
    client = _server_client()
    response = client.get("/api/v1/health")
    data = response.json()
    table = Table(title="Server Health")
    table.add_column("Component")
    table.add_column("Status")
    table.add_row("Overall", data["status"])
    table.add_row("Mode", "server" if data.get("server_mode") else "local")
    for name, status in data.get("checks", {}).items():
        color = "green" if status == "ok" else "red"
        table.add_row(name, f"[{color}]{status}[/{color}]")
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
