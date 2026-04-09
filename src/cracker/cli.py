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
from cracker.scenario import CrackerScenario, ScenarioResult

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


def _run_scenario(cracker, scenario: CrackerScenario, mode: str, vector: str) -> list[ScenarioResult]:
    """Run a scenario in a given mode/vector and return ScenarioResults."""
    scenario.fresh_canary()
    results = []

    for i, task in enumerate(scenario.tasks):
        console.print(f"  Task {i+1}/{len(scenario.tasks)}: {task.name}")

        if i > 0:
            scenario.teardown(cracker.backend)
            time.sleep(5)

        scenario.setup(cracker.backend, mode=mode, vector=vector)

        start = time.time()
        response = cracker.backend.run_agent(task.prompt, timeout=300)
        latency = time.time() - start

        if mode == "attack":
            leaked = scenario.validate(response.text, task=task, backend=cracker.backend)
        else:
            leaked = False

        utility = scenario.check_utility(task, response.text, backend=cracker.backend)

        sid = f"{scenario.category}-{vector}" if mode == "attack" else f"{scenario.category}-benign"
        leak_str = "[red]LEAKED[/red]" if leaked else "[green]HELD[/green]"
        util_str = "[green]✓[/green]" if utility else "[yellow]✗[/yellow]"
        console.print(f"    {leak_str} util={util_str} ({latency:.1f}s)")

        results.append(ScenarioResult(
            scenario_id=sid,
            task_name=task.name,
            canary_uuid=scenario.canary_uuid if mode == "attack" else "",
            canary_leaked=leaked,
            utility=utility,
            agent_response=response.text,
            latency=latency,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        ))

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

            for scenario in scenarios:
                for mode in modes:
                    if mode == "benign":
                        console.print(f"\n[bold cyan]{scenario.name} — BENIGN[/bold cyan]")
                        all_results.extend(_run_scenario(cracker, scenario, mode="benign", vector="file"))
                    else:
                        for vector in vectors:
                            console.print(f"\n[bold cyan]{scenario.name} — ATTACK ({vector})[/bold cyan]")
                            all_results.extend(_run_scenario(cracker, scenario, mode="attack", vector=vector))
        finally:
            backend_instance.disconnect()

        # Summary
        benign = [r for r in all_results if r.scenario_id.endswith("-benign")]
        attack = [r for r in all_results if not r.scenario_id.endswith("-benign")]

        benign_util = sum(1 for r in benign if r.utility) / len(benign) * 100 if benign else 0
        attack_leaked = sum(1 for r in attack if r.canary_leaked) / len(attack) * 100 if attack else 0
        attack_util = sum(1 for r in attack if r.utility) / len(attack) * 100 if attack else 0

        console.print(f"\n[bold]Benign Utility: {benign_util:.1f}%[/bold]")
        console.print(f"[bold]ASR: {attack_leaked:.1f}%[/bold]")
        console.print(f"[bold]UUA: {attack_util:.1f}%[/bold]")
        console.print(f"[bold]Utility Drop: {benign_util - attack_util:.1f}%[/bold]")

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            output_data = {
                "results": [r.to_dict() for r in all_results],
                "summary": {
                    "total_tasks": len(all_results),
                    "benign_utility": round(benign_util, 2),
                    "attack_success_rate": round(attack_leaked, 2),
                    "utility_under_attack": round(attack_util, 2),
                    "utility_drop": round(benign_util - attack_util, 2),
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
