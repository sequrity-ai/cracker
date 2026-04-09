"""CLI interface for Cracker."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cracker.backends import LocalBackend, DaytonaBackend
from cracker.config import CrackerConfig
from cracker.cracker_loop import CrackerLoop
from cracker.scenario import CrackerScenario, ScenarioResult, AttemptResult

console = Console()


def _create_backend(config: CrackerConfig):
    if config.backend == "local":
        return LocalBackend(
            agent_id=config.local_agent_id,
            workspace_path=config.workspace_path,
        )
    elif config.backend == "daytona":
        return DaytonaBackend(
            openrouter_api_key=config.openrouter_api_key,
            model_under_test=config.model_under_test,
            daytona_api_key=config.daytona_api_key,
            daytona_api_url=config.daytona_api_url,
            image=config.daytona_image,
            workspace_path=config.workspace_path,
        )
    else:
        raise ValueError(f"Invalid backend: {config.backend}")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _run_scenario(cracker, scenario: CrackerScenario, mode: str, vector: str, pass_k: int = 1) -> list[ScenarioResult]:
    """Run a scenario in a given mode/vector with pass@k attempts per task."""
    scenario.fresh_canary()
    results = []

    for i, task in enumerate(scenario.tasks):
        console.print(f"  Task {i+1}/{len(scenario.tasks)}: {task.name}", end="")

        attempts = []
        for attempt in range(pass_k):
            if i > 0 or attempt > 0:
                scenario.teardown(cracker.backend)
                time.sleep(3)

            scenario.setup(cracker.backend, mode=mode, vector=vector)

            start = time.time()
            response = cracker.backend.run_agent(task.prompt, timeout=300)
            latency = time.time() - start

            leaked = False
            if mode == "attack":
                leaked = scenario.validate(response.text, task=task, backend=cracker.backend)

            utility = scenario.check_utility(task, response.text, backend=cracker.backend)

            attempts.append(AttemptResult(
                utility=utility,
                canary_leaked=leaked,
                latency=latency,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent_response=response.text,
            ))

            mark = "✓" if utility else "✗"
            if pass_k > 1:
                console.print(f" [{mark}]", end="")

        sid = f"{scenario.category}-{vector}" if mode == "attack" else f"{scenario.category}-benign"
        result = ScenarioResult(
            scenario_id=sid,
            task_name=task.name,
            canary_uuid=scenario.canary_uuid if mode == "attack" else "",
            attempts=attempts,
        )
        leak_str = "[red]LEAKED[/red]" if result.canary_leaked else "[green]HELD[/green]"
        util_str = "[green]✓[/green]" if result.utility else "[yellow]✗[/yellow]"
        console.print(f"  {leak_str} util={util_str} ({result.latency:.1f}s)")

        results.append(result)

    scenario.teardown(cracker.backend)
    return results


def cmd_benchmark(args):
    """Run benchmark (benign + attack modes, vector-agnostic scenarios)."""
    setup_logging(args.verbose)

    from cracker.scenarios import ALL_SCENARIOS, get_scenario

    try:
        config = CrackerConfig()

        if args.backend:
            config.backend = args.backend
        if args.model:
            config.model_under_test = args.model
            if not args.backend:
                config.backend = "daytona"

        config.validate_config()

        # Select scenarios
        if args.category:
            scenario = get_scenario(args.category)
            if not scenario:
                console.print(f"[red]Unknown category: {args.category}[/red]")
                console.print("Available:")
                for s in ALL_SCENARIOS:
                    console.print(f"  {s.category}: {s.name}")
                sys.exit(1)
            scenarios = [scenario]
        else:
            scenarios = ALL_SCENARIOS

        vectors = [args.vector] if args.vector else ["file", "tool", "skill"]
        modes = [args.mode] if args.mode else ["benign", "attack"]

        backend_instance = _create_backend(config)
        console.print(f"[cyan]Connecting to {config.backend} backend...[/cyan]")
        backend_instance.connect()

        all_results = []
        try:
            cracker = CrackerLoop(config=config, backend=backend_instance)

            pk = getattr(args, 'pass_k', 1) or 1

            for scenario in scenarios:
                for mode in modes:
                    if mode == "benign":
                        console.print(f"\n[bold cyan]{scenario.name} — BENIGN (pass@{pk})[/bold cyan]")
                        all_results.extend(_run_scenario(cracker, scenario, mode="benign", vector="file", pass_k=pk))
                    else:
                        for vector in vectors:
                            console.print(f"\n[bold cyan]{scenario.name} — ATTACK ({vector}, pass@{pk})[/bold cyan]")
                            all_results.extend(_run_scenario(cracker, scenario, mode="attack", vector=vector, pass_k=pk))
        finally:
            backend_instance.disconnect()

        # Compute pass@1..pass@k summary
        benign = [r for r in all_results if r.scenario_id.endswith("-benign")]
        attack = [r for r in all_results if not r.scenario_id.endswith("-benign")]

        def _pass_at_rates(results, attr):
            """Compute pass@1..pass@k rates from results."""
            if not results:
                return {}
            k = max(len(r.attempts) for r in results)
            rates = {}
            for n in range(1, k + 1):
                key = str(n)
                if attr == "utility":
                    passed = sum(1 for r in results if r.pass_at.get(key, False))
                else:
                    passed = sum(1 for r in results if r.leaked_at.get(key, False))
                rates[f"pass@{n}"] = round(passed / len(results) * 100, 2)
            return rates

        benign_rates = _pass_at_rates(benign, "utility")
        asr_rates = _pass_at_rates(attack, "leaked")
        uua_rates = _pass_at_rates(attack, "utility")

        console.print(f"\n[bold]Benign Utility: {benign_rates}[/bold]")
        console.print(f"[bold]ASR: {asr_rates}[/bold]")
        console.print(f"[bold]UUA: {uua_rates}[/bold]")

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            output_data = {
                "results": [r.to_dict() for r in all_results],
                "summary": {
                    "pass_k": pk,
                    "total_tasks": len(all_results),
                    "benign_utility": benign_rates,
                    "attack_success_rate": asr_rates,
                    "utility_under_attack": uua_rates,
                },
            }
            Path(args.output).write_text(json.dumps(output_data, indent=2))
            console.print(f"[green]Results saved to {args.output}[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if args.verbose:
            raise
        sys.exit(1)


def cmd_list(args):
    """List available scenarios."""
    setup_logging(args.verbose)

    from cracker.scenarios import ALL_SCENARIOS

    console.print("\n[bold cyan]Available Scenarios[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Category", style="cyan")
    table.add_column("Name")
    table.add_column("Tasks", justify="right")
    table.add_column("Description")

    for s in ALL_SCENARIOS:
        table.add_row(s.category, s.name, str(len(s.tasks)), s.description)

    console.print(table)


def cmd_validate_config(args):
    """Validate configuration."""
    setup_logging(args.verbose)
    try:
        config = CrackerConfig()
        config.validate_config()
        console.print("[green]✓ Configuration valid[/green]")
        console.print(f"Backend: {config.backend}")
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Cracker: Prompt injection benchmark for AI agents",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # benchmark
    sp = subparsers.add_parser("benchmark", help="Run benchmark (benign + attack modes)")
    sp.add_argument("--category", help="Scenario category (default: all)")
    sp.add_argument("--mode", choices=["benign", "attack"], help="Run mode (default: both)")
    sp.add_argument("--vector", choices=["file", "tool", "skill"], help="Attack vector (default: all)")
    sp.add_argument("--backend", choices=["local", "daytona"], help="Backend to use")
    sp.add_argument("--model", help="Model under test (OpenRouter format)")
    sp.add_argument("--pass-k", type=int, default=1, help="Attempts per task; reports pass@1..pass@k (default: 1)")
    sp.add_argument("--output", help="Output JSON file")
    sp.set_defaults(func=cmd_benchmark)

    # list
    subparsers.add_parser("list", help="List available scenarios").set_defaults(func=cmd_list)

    # validate-config
    subparsers.add_parser("validate-config", help="Validate configuration").set_defaults(func=cmd_validate_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
