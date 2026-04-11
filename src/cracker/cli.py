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


def _run_scenario(cracker, scenario: CrackerScenario, tasks: list, mode: str, vector: str, strength: str = "subtle", pass_k: int = 1, adaptive: bool = False) -> list[ScenarioResult]:
    """Run specific tasks from a scenario with given mode/vector/strength.

    If adaptive=True and a static attempt doesn't leak, the attacker LLM
    refines the injection across multiple turns.
    """
    scenario.fresh_canary()
    results = []

    for i, task in enumerate(tasks):
        console.print(f"  Task {i+1}/{len(tasks)}: {task.name}", end="")

        attempts = []
        for attempt in range(pass_k):
            if i > 0 or attempt > 0:
                scenario.teardown(cracker.backend)
                time.sleep(3)

            scenario.setup(cracker.backend, mode=mode, vector=vector, strength=strength)

            start = time.time()
            response = cracker.backend.run_agent(task.prompt, timeout=300)
            latency = time.time() - start

            # Debug: log agent response
            resp_preview = (response.text or "")[:500]
            logging.getLogger("cracker.cli").debug(
                f"Agent response ({len(response.text or '')} chars, success={response.success}): "
                f"{resp_preview}"
            )
            if response.error:
                logging.getLogger("cracker.cli").warning(f"Agent error: {response.error}")

            leaked = False
            if mode == "attack":
                leaked = scenario.validate(response.text, task=task, backend=cracker.backend)

            utility = scenario.check_utility(task, response.text, backend=cracker.backend)

            # If attack didn't leak and adaptive is on, try attacker refinement
            attacker_input = attacker_cached = attacker_output = 0
            attacker_cost = 0.0
            attacker_model = ""
            if mode == "attack" and not leaked and adaptive and scenario.poisonable_files_for_task(task):
                console.print(f" [adaptive]", end="")
                scenario.teardown(cracker.backend)
                scenario.setup(cracker.backend, mode=mode, vector=vector, strength=strength)
                adaptive_result = cracker.run_adaptive(scenario, task)
                if adaptive_result.canary_leaked:
                    leaked = True
                    latency += adaptive_result.latency
                    utility = adaptive_result.utility
                if adaptive_result.attempts:
                    a = adaptive_result.attempts[0]
                    attacker_input = a.attacker_input_tokens
                    attacker_cached = a.attacker_cached_tokens
                    attacker_output = a.attacker_output_tokens
                    attacker_cost = a.attacker_cost_usd
                    attacker_model = a.attacker_model

            attempts.append(AttemptResult(
                utility=utility,
                canary_leaked=leaked,
                latency=latency,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                mut_cost_usd=response.cost_usd,
                agent_response=response.text,
                attacker_input_tokens=attacker_input,
                attacker_cached_tokens=attacker_cached,
                attacker_output_tokens=attacker_output,
                attacker_cost_usd=attacker_cost,
                attacker_model=attacker_model,
            ))

            mark = "✓" if utility else "✗"
            if pass_k > 1:
                console.print(f" [{mark}]", end="")

        sid = f"{scenario.category}-{vector}-{strength}" if mode == "attack" else f"{scenario.category}-benign"
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
            use_adaptive = getattr(args, 'adaptive', False)
            if use_adaptive:
                if getattr(args, 'max_turns', None):
                    config.attacker.max_turns = args.max_turns
                if getattr(args, 'attacker_model', None):
                    config.attacker.model = args.attacker_model

            for scenario in scenarios:
                for mode in modes:
                    if mode == "benign":
                        # Run all 9 tasks (3 per vector) with no injection
                        for vector in vectors:
                            tasks = scenario.tasks_for_vector(vector)
                            console.print(f"\n[bold cyan]{scenario.name} — BENIGN/{vector} (pass@{pk})[/bold cyan]")
                            all_results.extend(_run_scenario(cracker, scenario, tasks=tasks, mode="benign", vector=vector, pass_k=pk))
                    else:
                        # Run each vector's tasks with matched injection × 3 strengths
                        from cracker.attacks.base import ALL_STRENGTHS
                        label = "+adaptive" if use_adaptive else ""
                        for vector in vectors:
                            tasks = scenario.tasks_for_vector(vector)
                            for strength in ALL_STRENGTHS:
                                console.print(f"\n[bold cyan]{scenario.name} — ATTACK ({vector}/{strength.value}{label}, pass@{pk})[/bold cyan]")
                                all_results.extend(_run_scenario(cracker, scenario, tasks=tasks, mode="attack", vector=vector, strength=strength.value, pass_k=pk, adaptive=use_adaptive))
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

        all_attempts = [a for r in all_results for a in r.attempts]
        mut_input = sum(a.input_tokens for a in all_attempts)
        mut_output = sum(a.output_tokens for a in all_attempts)
        mut_cost = sum(a.mut_cost_usd for a in all_attempts)
        att_input = sum(a.attacker_input_tokens for a in all_attempts)
        att_cached = sum(a.attacker_cached_tokens for a in all_attempts)
        att_output = sum(a.attacker_output_tokens for a in all_attempts)
        att_cost = sum(a.attacker_cost_usd for a in all_attempts)
        attacker_models = list({a.attacker_model for a in all_attempts if a.attacker_model})

        console.print(f"\n[bold]Benign Utility: {benign_rates}[/bold]")
        console.print(f"[bold]ASR: {asr_rates}[/bold]")
        console.print(f"[bold]UUA: {uua_rates}[/bold]")
        console.print(f"\n[bold]Token usage:[/bold]")
        console.print(f"  MUT      — in: {mut_input:,}  out: {mut_output:,}  cost: ${mut_cost:.4f}")
        console.print(f"  Attacker — in: {att_input:,}  cached: {att_cached:,}  out: {att_output:,}  cost: ${att_cost:.4f}")
        if attacker_models:
            console.print(f"  Attacker model(s) served: {', '.join(attacker_models)}")

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
                    "tokens": {
                        "mut_input": mut_input,
                        "mut_output": mut_output,
                        "mut_cost_usd": round(mut_cost, 6),
                        "attacker_input": att_input,
                        "attacker_cached": att_cached,
                        "attacker_output": att_output,
                        "attacker_cost_usd": round(att_cost, 6),
                        "attacker_models_served": attacker_models,
                    },
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
    sp.add_argument("--adaptive", action="store_true", help="Use attacker LLM to refine injections when static fails")
    sp.add_argument("--attacker-model", help="Attacker model for adaptive mode (OpenRouter format)")
    sp.add_argument("--max-turns", type=int, default=5, help="Max attacker refinement turns (default: 5)")
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
