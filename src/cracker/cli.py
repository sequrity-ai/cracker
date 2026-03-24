"""CLI interface for Cracker."""

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from benchmarks.scenario_factory import SCENARIO_CONFIGS
from cracker.backends import LocalBackend, DaytonaBackend
from cracker.benchmark_runner import BenchmarkRunner
from cracker.config import CrackerConfig
from cracker.cracker_loop import CrackerLoop
from cracker.malicious_tasks import get_malicious_task, get_all_malicious_tasks

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
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@click.group()
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx, verbose):
    """Cracker: Automated prompt injection attack generator for OpenClaw Bench."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command()
@click.option("--scenario", required=True, help="Scenario name (file, weather, web, etc.)")
@click.option("--task-index", type=int, help="Specific task index (0-8, optional)")
@click.option("--malicious-task", required=True, help="Malicious task ID (e.g., exfil-single)")
@click.option("--backend", type=click.Choice(["local", "daytona"]), help="Backend to use")
@click.option("--model", help="Model under test (OpenRouter format, e.g. moonshotai/kimi-k2.5)")
@click.option("--attacker-model", help="Attacker model (OpenRouter format)")
@click.option("--max-turns", type=int, help="Maximum refinement turns")
@click.option("--output", type=click.Path(), help="Output JSON file for results")
@click.pass_context
def crack(ctx, scenario, task_index, malicious_task, backend, model, attacker_model, max_turns, output):
    """Run cracker attack on openclawbench scenario."""
    verbose = ctx.obj.get("verbose", False)

    try:
        # Load config
        config = CrackerConfig()

        # Override config with CLI arguments
        if backend:
            config.backend = backend
        if model:
            config.model_under_test = model
            if not backend:
                config.backend = "daytona"
        if attacker_model:
            config.attacker.model = attacker_model
        if max_turns:
            config.attacker.max_turns = max_turns

        # Validate config
        config.validate_config()

        # Create backend
        backend_instance = _create_backend(config)
        console.print(f"[cyan]Connecting to {config.backend} backend...[/cyan]")
        backend_instance.connect()

        # Create cracker loop
        cracker = CrackerLoop(config=config, backend=backend_instance)

        # Load openclawbench scenario
        console.print(f"\n[cyan]Loading openclawbench scenario: {scenario}[/cyan]")
        scenario_config = SCENARIO_CONFIGS.get(scenario)
        if not scenario_config:
            console.print(f"[red]Unknown scenario: {scenario}[/red]")
            console.print(f"Available scenarios: {', '.join(SCENARIO_CONFIGS.keys())}")
            sys.exit(1)

        scenario_instance = scenario_config.scenario_class(remote_manager=None)

        # Run scenario setup to get workspace data for validators
        setup_data = {}
        if hasattr(scenario_instance, "setup"):
            try:
                setup_result = scenario_instance.setup()
                setup_data = getattr(setup_result, "setup_data", {}) or {}
                console.print(f"[green]Scenario setup complete[/green]")
                # Sync local files to remote backend (no-op for local)
                backend_instance.sync_local_workspace(config.workspace_path)
            except Exception as e:
                console.print(f"[yellow]Scenario setup failed: {e}[/yellow]")

        # Get malicious task
        mal_task = get_malicious_task(malicious_task)
        if not mal_task:
            console.print(f"[red]Unknown malicious task: {malicious_task}[/red]")
            console.print("\nAvailable malicious tasks:")
            for mt in get_all_malicious_tasks():
                console.print(f"  {mt.id}: {mt.name} - {mt.description}")
            sys.exit(1)

        # Run crack attempt
        console.print(f"\n[bold cyan]Starting attack on {scenario}[/bold cyan]")
        console.print(f"Malicious task: [yellow]{mal_task.name}[/yellow] ({mal_task.category})")
        console.print(f"Malicious goal: [yellow]{mal_task.goal}[/yellow]")
        console.print(f"Attacker model: [yellow]{config.attacker.model}[/yellow]")
        console.print(f"Max turns: [yellow]{config.attacker.max_turns}[/yellow]\n")

        # Run on specific task or all tasks
        if task_index is not None:
            if task_index < 0 or task_index >= len(scenario_instance.tasks):
                console.print(f"[red]Invalid task index: {task_index}. Scenario has {len(scenario_instance.tasks)} tasks (0-{len(scenario_instance.tasks)-1})[/red]")
                sys.exit(1)
            benign_tasks = [scenario_instance.tasks[task_index]]
        else:
            benign_tasks = scenario_instance.tasks

        results = []
        for idx, benign_task in enumerate(benign_tasks):
            console.print(f"\n[bold]Task {idx + 1}/{len(benign_tasks)}: {benign_task.name}[/bold]")

            result = cracker.crack_task(
                task_name=benign_task.name,
                scenario=scenario,
                benign_task=benign_task.prompt,
                malicious_task=mal_task,
                benign_validator=benign_task.validation_fn if benign_task.validates_files else None,
                setup_data=setup_data,
            )
            results.append(result)

            # Display result
            display_result(result)

        # Aggregate results
        if len(results) > 1:
            display_aggregate_results(results)

        # Disconnect backend
        backend_instance.disconnect()

        # Save to file if requested
        if output:
            output_path = Path(output)
            output_data = {
                "scenario": scenario,
                "malicious_task": malicious_task,
                "results": [r.to_dict() for r in results],
            }
            output_path.write_text(json.dumps(output_data, indent=2))
            console.print(f"\n[green]Results saved to {output}[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            raise
        sys.exit(1)


def display_result(result):
    """Display single crack result in rich table format."""
    # Summary table
    summary_table = Table(show_header=True, header_style="bold magenta", title="Attack Result")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")

    summary_table.add_row("Task", result.task_name)
    summary_table.add_row("Attack Success", "✓ Yes" if result.attack_success else "✗ No")
    summary_table.add_row("Utility Preserved", "✓ Yes" if result.utility_preserved else "✗ No")
    summary_table.add_row("Total Turns", str(result.total_turns))
    summary_table.add_row("Total Latency", f"{result.total_latency:.2f}s")
    summary_table.add_row("Input Tokens", str(result.input_tokens))
    summary_table.add_row("Output Tokens", str(result.output_tokens))

    console.print(summary_table)

    # Final injection if successful
    if result.final_injection:
        console.print(f"\n[bold green]Final Successful Injection:[/bold green]")
        console.print(f"[yellow]{result.final_injection[:200]}...[/yellow]" if len(result.final_injection) > 200 else f"[yellow]{result.final_injection}[/yellow]")


def display_aggregate_results(results: list):
    """Display aggregate results across multiple tasks."""
    console.print("\n[bold]Aggregate Results[/bold]")

    agg_table = Table(show_header=True, header_style="bold magenta")
    agg_table.add_column("Metric", style="cyan")
    agg_table.add_column("Value", style="green")

    attack_success_rate = sum(1 for r in results if r.attack_success) / len(results) * 100
    utility_preservation_rate = sum(1 for r in results if r.utility_preserved) / len(results) * 100
    avg_turns = sum(r.total_turns for r in results) / len(results)
    total_tokens = sum(r.input_tokens + r.output_tokens for r in results)

    agg_table.add_row("Total Tasks", str(len(results)))
    agg_table.add_row("Attack Success Rate", f"{attack_success_rate:.1f}%")
    agg_table.add_row("Utility Preservation Rate", f"{utility_preservation_rate:.1f}%")
    agg_table.add_row("Average Turns", f"{avg_turns:.1f}")
    agg_table.add_row("Total Tokens", str(total_tokens))

    console.print(agg_table)


@main.command()
def validate_config():
    """Validate configuration."""
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


@main.command()
@click.option("--malicious-task", required=True, help="Malicious task ID (e.g., exfil-single)")
@click.option("--scenarios", help="Comma-separated scenario names (default: all)")
@click.option("--agent-name", default="gpt-5-mini", help="Agent name for reporting")
@click.option("--backend", type=click.Choice(["local", "daytona"]), help="Backend to use")
@click.option("--model", help="Model under test (OpenRouter format, e.g. moonshotai/kimi-k2.5)")
@click.option("--attacker-model", help="Attacker model (OpenRouter format)")
@click.option("--max-turns", type=int, help="Maximum refinement turns")
@click.option("--output", type=click.Path(), help="Output JSON file for results")
@click.pass_context
def benchmark(ctx, malicious_task, scenarios, agent_name, backend, model, attacker_model, max_turns, output):
    """Run full benchmark across all/selected scenarios."""
    verbose = ctx.obj.get("verbose", False)

    try:
        # Load config
        config = CrackerConfig()

        # Override config with CLI arguments
        if backend:
            config.backend = backend
        if model:
            config.model_under_test = model
            if not backend:
                config.backend = "daytona"
        if attacker_model:
            config.attacker.model = attacker_model
        if max_turns:
            config.attacker.max_turns = max_turns

        # Validate config
        config.validate_config()

        # Parse scenarios
        scenario_list = None
        if scenarios:
            scenario_list = [s.strip() for s in scenarios.split(",")]

        # Get malicious task
        mal_task = get_malicious_task(malicious_task)
        if not mal_task:
            console.print(f"[red]Unknown malicious task: {malicious_task}[/red]")
            console.print("\nAvailable malicious tasks:")
            for mt in get_all_malicious_tasks():
                console.print(f"  {mt.id}: {mt.name}")
            sys.exit(1)

        # Create backend
        backend_instance = _create_backend(config)
        console.print(f"[cyan]Connecting to {config.backend} backend...[/cyan]")
        backend_instance.connect()

        # Create benchmark runner
        runner = BenchmarkRunner(config=config, backend=backend_instance)

        # Run benchmark
        console.print(f"\n[bold cyan]Starting Full Benchmark[/bold cyan]")
        console.print(f"Malicious task: [yellow]{mal_task.name}[/yellow] ({mal_task.category})")
        console.print(f"Agent: [yellow]{agent_name}[/yellow]")
        console.print(f"Scenarios: [yellow]{scenarios or 'all (7 scenarios)'}[/yellow]\n")

        result = runner.run_full_benchmark(
            malicious_task=mal_task,
            scenarios=scenario_list,
            agent_name=agent_name,
        )

        # Disconnect backend
        backend_instance.disconnect()

        # Print summary
        runner.print_summary(result)

        # Save to file if requested
        if output:
            output_path = Path(output)
            runner.export_report(result, output_path)
            console.print(f"[green]Full report exported to {output}[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            raise
        sys.exit(1)


@main.command()
def list_malicious():
    """List all available malicious tasks."""
    console.print("\n[bold cyan]Available Malicious Tasks[/bold cyan]\n")

    tasks_by_category = {}
    for task in get_all_malicious_tasks():
        if task.category not in tasks_by_category:
            tasks_by_category[task.category] = []
        tasks_by_category[task.category].append(task)

    for category, tasks in sorted(tasks_by_category.items()):
        console.print(f"\n[bold yellow]{category.upper().replace('_', ' ')}[/bold yellow]")
        for task in tasks:
            console.print(f"  [cyan]{task.id:20}[/cyan] {task.name}")
            console.print(f"    {task.description}")


if __name__ == "__main__":
    main()
