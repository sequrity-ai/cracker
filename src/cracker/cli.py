"""CLI interface for Cracker."""

import argparse
import json
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cracker.backends import LocalBackend, DaytonaBackend
from cracker.config import CrackerConfig
from cracker.cracker_loop import CrackerLoop

console = Console()


def _create_backend(config: CrackerConfig):
    """Create the appropriate backend based on config."""
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


def cmd_scenario(args):
    """Run cracker scenarios (self-contained prompt injection tests)."""
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
        if args.attacker_model:
            config.attacker.model = args.attacker_model
        if args.max_turns:
            config.attacker.max_turns = args.max_turns

        config.validate_config()

        # Select scenarios
        if args.scenario:
            scenario = get_scenario(args.scenario)
            if not scenario:
                console.print(f"[red]Unknown scenario: {args.scenario}[/red]")
                console.print("Available scenarios:")
                for s in ALL_SCENARIOS:
                    console.print(f"  {s.id}: {s.name} ({s.vector.value})")
                sys.exit(1)
            scenarios = [scenario]
        else:
            scenarios = ALL_SCENARIOS

        if args.vector:
            from cracker.scenario import AttackVector
            vec = AttackVector(args.vector)
            scenarios = [s for s in scenarios if s.vector == vec]
            if not scenarios:
                console.print(f"[red]No scenarios found for vector: {args.vector}[/red]")
                sys.exit(1)

        backend_instance = _create_backend(config)
        console.print(f"[cyan]Connecting to {config.backend} backend...[/cyan]")
        backend_instance.connect()

        cracker = CrackerLoop(config=config, backend=backend_instance)
        adaptive = args.adaptive

        all_results = []
        for scenario in scenarios:
            console.print(f"\n[bold cyan]Scenario: {scenario.name}[/bold cyan]")
            console.print(f"  Vector: {scenario.vector.value}")
            console.print(f"  Tasks: {len(scenario.tasks)}")
            console.print(f"  Mode: {'adaptive' if adaptive else 'static'}")
            console.print(f"  {scenario.description}\n")

            results = cracker.run_scenario(scenario, adaptive=adaptive)
            all_results.extend(results)

            for r in results:
                leak = "[red]LEAKED[/red]" if r.canary_leaked else "[green]HELD[/green]"
                util = "[green]✓[/green]" if r.utility else "[yellow]✗[/yellow]"
                console.print(
                    f"  {r.task_name}: {leak} util={util} "
                    f"({r.latency:.1f}s, {r.input_tokens + r.output_tokens} tokens)"
                )

        # Summary
        total = len(all_results)
        leaked = sum(1 for r in all_results if r.canary_leaked)
        utility = sum(1 for r in all_results if r.utility)
        console.print(
            f"\n[bold]Attack: {leaked}/{total} leaked ({leaked/total*100:.1f}%) | "
            f"Utility: {utility}/{total} passed ({utility/total*100:.1f}%)[/bold]"
        )

        backend_instance.disconnect()

        if args.output:
            output_data = {
                "scenarios": [r.to_dict() for r in all_results],
                "summary": {
                    "total_tasks": total,
                    "canaries_leaked": leaked,
                    "leak_rate": leaked / total * 100 if total else 0,
                    "utility_passed": utility,
                    "utility_rate": utility / total * 100 if total else 0,
                },
            }
            Path(args.output).write_text(json.dumps(output_data, indent=2))
            console.print(f"[green]Results saved to {args.output}[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if args.verbose:
            raise
        sys.exit(1)


def cmd_validate_config(args):
    """Validate configuration."""
    setup_logging(args.verbose)

    try:
        config = CrackerConfig()
        config.validate_config()
        console.print("[green]✓ Configuration valid[/green]")
        console.print(f"Backend: {config.backend}")
        console.print(f"Attacker model: {config.attacker.model}")
        console.print(f"Max turns: {config.attacker.max_turns}")
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)


def cmd_list_scenarios(args):
    """List all available scenarios."""
    from cracker.scenarios import ALL_SCENARIOS

    console.print("\n[bold cyan]Available Scenarios[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Vector")
    table.add_column("Tasks", justify="right")
    table.add_column("Description")

    for s in ALL_SCENARIOS:
        table.add_row(s.id, s.name, s.vector.value, str(len(s.tasks)), s.description)

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Cracker: Prompt injection benchmark for AI agents",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scenario
    sp = subparsers.add_parser("scenario", help="Run prompt injection scenarios")
    sp.add_argument("--scenario", help="Specific scenario ID (default: all)")
    sp.add_argument("--backend", choices=["local", "daytona"], help="Backend to use")
    sp.add_argument("--model", help="Model under test (OpenRouter format)")
    sp.add_argument("--adaptive", action="store_true", help="Use attacker LLM to poison files")
    sp.add_argument("--attacker-model", help="Attacker model (adaptive mode)")
    sp.add_argument("--max-turns", type=int, help="Max attacker turns (adaptive mode)")
    sp.add_argument("--vector", choices=["file", "tool", "skill"], help="Run only scenarios of this attack vector")
    sp.add_argument("--output", help="Output JSON file")
    sp.set_defaults(func=cmd_scenario)

    # list
    subparsers.add_parser("list", help="List available scenarios").set_defaults(
        func=cmd_list_scenarios
    )

    # validate-config
    subparsers.add_parser("validate-config", help="Validate configuration").set_defaults(
        func=cmd_validate_config
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
