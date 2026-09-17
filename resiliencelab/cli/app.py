"""ResilienceLab command-line interface."""

from __future__ import annotations

import asyncio
import contextlib
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
    confidence: Annotated[
        float, typer.Option("--confidence", help="Confidence level for CIs")
    ] = 0.95,
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

    comparison = build_comparison(experiments, confidence=confidence)
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
        # Validate seed compatibility for paired comparison
        seeds_a = experiments[0].get("seeds", [])
        seeds_b = experiments[1].get("seeds", [])
        if seeds_a and seeds_b and seeds_a != seeds_b:
            console.print(
                "[yellow]Warning: seeds differ between experiments; "
                "paired comparison assumes matched replicates by index.[/yellow]"
            )
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
    experiment_id: Annotated[
        str | None, typer.Argument(help="Experiment ID (omit with --all)")
    ] = None,
    store: Annotated[str | None, typer.Option()] = None,
    output: Annotated[str | None, typer.Option(help="Store reproduction under new id")] = None,
    all_benchmarks: Annotated[
        bool, typer.Option("--all", help="Reproduce all declared paper benchmarks")
    ] = False,
    repetitions: Annotated[
        int | None, typer.Option(help="Override repetition count (with --all)")
    ] = None,
    benchmarks_dir: Annotated[
        str | None, typer.Option(help="Benchmark YAML directory (with --all)")
    ] = None,
) -> None:
    if all_benchmarks:
        from resiliencelab.experiments.reproduce import reproduce_all

        manifest = reproduce_all(
            _store_for(store), benchmarks_dir=benchmarks_dir, repetitions=repetitions
        )
        console.print(
            f"Reproduced {manifest['succeeded']}/{len(manifest['results'])} benchmarks; "
            f"manifest: {(_store_for(store) / 'reproduction_manifest.json').resolve()}"
        )
        for entry in manifest["results"]:
            status = entry.get("status", "?")
            marker = "ok" if status == "ok" else "FAIL"
            detail = entry.get("error") or entry.get("artifact_dir", "")
            console.print(f"  [{marker}] {entry.get('id')}: {status} {detail}".rstrip())
        if manifest["failed"]:
            raise typer.Exit(code=1)
        return
    if experiment_id is None:
        _err("provide EXPERIMENT_ID or use `reproduce --all`")
    base = _store_for(store) / experiment_id
    config_path = base / "configuration.yaml"
    if not config_path.exists():
        _err(f"no configuration found for `{experiment_id}`")
    try:
        spec = load_yaml(config_path)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
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
    try:
        spec = load_yaml(resolved)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
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
    try:
        spec = load_yaml(path)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
    try:
        factor_map = _load_factors(factors) if factors else None
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
    from resiliencelab.analysis.design import build_design, interaction_effect, main_effect
    from resiliencelab.experiments.factorial import CORE_FACTORS
    from resiliencelab.experiments.matrix import (
        condition_dir,
        condition_metadata,
        condition_spec_for,
    )

    effective_factors = factor_map or CORE_FACTORS
    try:
        conditions = build_design(spec, effective_factors)
    except (ValueError, ConfigValidationError) as exc:
        _err(f"invalid matrix design: {exc}")
    except Exception as exc:  # noqa: BLE001
        # Pydantic ValidationError for invalid factor levels surfaces here;
        # report as a design error rather than a raw traceback.
        _err(f"invalid matrix design: {exc}")
    console.print(f"Generated {len(conditions)} experiment conditions")
    store_root = _store_for(store)
    base_dir = store_root / spec.id
    base_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    observations: dict[str, dict[str, list[float]]] = {}
    condition_manifests: dict[str, Any] = {}
    begun = False

    from resiliencelab.analysis.comparison import build_comparison

    def _finalize_matrix() -> int:
        comparison = build_comparison(entries)
        comparison_path = base_dir / "matrix_comparison.json"
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
                    "spec_id": f"{spec.id}_{c.condition_id}",
                    "artifact_dir": f"conditions/{c.condition_id}",
                }
                for c in conditions
            ],
        }
        design_path = base_dir / "matrix_design.json"
        design_path.write_text(json.dumps(design_doc, indent=2, default=str), encoding="utf-8")
        effects: dict[str, Any] = {}
        condition_observations = observations.get(metric, {})
        effects["metric"] = metric
        effects["main_effects"] = [
            main_effect(conditions, condition_observations, factor) for factor in effective_factors
        ]
        factor_names = list(effective_factors)
        from resiliencelab.experiments.matrix import binary_factor_pairs

        binary_pairs = binary_factor_pairs(factor_names, conditions)
        for fa, fb in binary_pairs:
            key = f"interaction_{fa}_x_{fb}"
            try:
                effects[key] = interaction_effect(conditions, condition_observations, fa, fb)
            except ValueError:
                continue
        effects_path = base_dir / "matrix_effects.json"
        effects_path.write_text(json.dumps(effects, indent=2, default=str), encoding="utf-8")
        n_ok = sum(1 for v in condition_manifests.values() if v.get("status") == "ok")
        n_failed = sum(1 for v in condition_manifests.values() if v.get("status") == "failed")
        n_cancelled = sum(1 for v in condition_manifests.values() if v.get("status") == "cancelled")
        matrix_manifest = {
            "base_experiment": spec.id,
            "factors": effective_factors,
            "condition_count": len(conditions),
            "succeeded": n_ok,
            "failed": n_failed,
            "cancelled": n_cancelled,
            "conditions": condition_manifests,
            "files": {
                "matrix_design.json": "matrix_design.json",
                "matrix_comparison.json": "matrix_comparison.json",
                "matrix_effects.json": "matrix_effects.json",
            },
        }
        matrix_manifest_path = base_dir / "matrix_manifest.json"
        matrix_manifest_path.write_text(
            json.dumps(matrix_manifest, indent=2, default=str), encoding="utf-8"
        )
        console.print(f"Comparison written to {comparison_path.resolve()}")
        console.print(f"Design written to {design_path.resolve()}")
        console.print(f"Effects written to {effects_path.resolve()}")
        console.print(f"Matrix manifest written to {matrix_manifest_path.resolve()}")
        return n_failed

    try:
        for condition in conditions:
            begun = True
            try:
                condition_spec = condition_spec_for(spec, condition)
            except Exception as exc:  # noqa: BLE001
                condition_manifests[condition.condition_id] = {
                    "status": "failed",
                    "condition_id": condition.condition_id,
                    "spec_id": None,
                    "artifact_dir": f"conditions/{condition.condition_id}",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                console.print(f"  failed {condition.condition_id}: {exc}")
                continue
            console.print(f"  running {condition.condition_id} ...")
            try:
                result = _run_spec(condition_spec)
            except Exception as exc:  # noqa: BLE001
                condition_manifests[condition.condition_id] = {
                    "status": "failed",
                    "condition_id": condition.condition_id,
                    "spec_id": condition_spec.id,
                    "artifact_dir": f"conditions/{condition.condition_id}",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                console.print(f"  failed {condition.condition_id}: {exc}")
                continue
            dest = condition_dir(store_root, spec.id, condition.condition_id)
            try:
                metadata = condition_metadata(spec, condition, condition_spec.id)
                manifest = write_artifacts(result, dest, condition=metadata)
            except Exception as exc:  # noqa: BLE001
                condition_manifests[condition.condition_id] = {
                    "status": "failed",
                    "condition_id": condition.condition_id,
                    "spec_id": condition_spec.id,
                    "artifact_dir": f"conditions/{condition.condition_id}",
                    "error_type": type(exc).__name__,
                    "error": f"artifact write failed: {exc}",
                }
                console.print(f"  failed {condition.condition_id}: {exc}")
                continue
            status = "cancelled" if result.cancelled else "ok"
            record_entry: dict[str, Any] = {
                "status": status,
                "condition_id": condition.condition_id,
                "spec_id": condition_spec.id,
                "artifact_dir": f"conditions/{condition.condition_id}",
                "manifest": manifest,
            }
            if result.cancelled:
                record_entry["cancellation_reason"] = result.cancellation_reason
            condition_manifests[condition.condition_id] = record_entry
            entry = result.as_comparison_entry()
            entry["condition_id"] = condition.condition_id
            entry["spec_id"] = condition_spec.id
            entry["artifact_dir"] = f"conditions/{condition.condition_id}"
            entries.append(entry)
            for row in entry["metrics_per_run"]:
                for metric_name, value in row.items():
                    observations.setdefault(metric_name, {}).setdefault(
                        condition.condition_id, []
                    ).append(float(value))
    except BaseException:
        if begun:
            with contextlib.suppress(Exception):
                _finalize_matrix()
        raise
    if begun:
        n_failed_final = _finalize_matrix()
        if n_failed_final:
            console.print(
                f"[yellow]{n_failed_final} condition(s) failed; "
                "see matrix_manifest.json for per-condition errors[/yellow]"
            )
            raise typer.Exit(code=1)


def _load_factors(path: str) -> dict[str, Any]:
    import yaml

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigValidationError(f"invalid YAML in {path}: {exc}") from exc
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
    try:
        spec = load_yaml(path)
    except (ConfigValidationError, OSError) as exc:
        _err(str(exc))
    import yaml

    config_data = {"experiment": {"id": spec.id, "name": spec.name, "version": spec.version}}
    try:
        config_data.update(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        _err(f"invalid YAML in {path}: {exc}")
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
    reason: Annotated[str, typer.Option(help="Cancellation reason")] = "",
) -> None:
    client = _server_client()
    payload: dict[str, Any] = {}
    if reason:
        payload["reason"] = reason
    response = client.post(f"/api/v1/experiments/{experiment_id}/cancel", json=payload or None)
    if response.status_code == 404:
        _err(f"experiment `{experiment_id}` not found")
    data = response.json()
    status = data.get("status", "unknown")
    if status == "cancel_requested":
        console.print(
            f"[yellow]Cancellation requested[/yellow] for `{experiment_id}`. "
            "Worker will stop at the next checkpoint."
        )
    elif status == "cancelled":
        console.print(f"[yellow]Cancelled[/yellow] experiment `{experiment_id}`")
    elif "already" in status:
        console.print(f"[dim]Already {status}[/dim] for `{experiment_id}`")
    else:
        console.print(f"[yellow]{status}[/yellow] experiment `{experiment_id}`")


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
