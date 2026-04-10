"""Bridge between cracker's scenario interface and openclawbench's task discovery.

openclawbench uses filesystem-based task discovery (task_runner.discover_tasks).
Cracker expects a SCENARIO_CONFIGS dict mapping scenario names to config objects
with a scenario_class that produces instances with .tasks and optional .setup().
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from task_runner import TaskSpec, discover_tasks


# Default tasks directory — resolved relative to openclawbench package
_TASKS_DIR = Path(__file__).resolve().parents[3] / "openclawbench" / "tasks"


@dataclass
class BenignTask:
    """Adapter matching the interface cracker expects for each task."""

    name: str
    prompt: str
    validates_files: bool = True
    validation_fn: Callable | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _spec: TaskSpec | None = field(default=None, repr=False)


class Scenario:
    """Wraps openclawbench's discovered tasks as a scenario instance."""

    def __init__(self, scenario_name: str, tasks_dir: Path = _TASKS_DIR, remote_manager: Any = None):
        self._scenario_name = scenario_name
        specs = discover_tasks(tasks_dir, scenario=scenario_name)
        self.tasks = [
            BenignTask(
                name=f"{spec.scenario}/{spec.name}",
                prompt=spec.instruction,
                validates_files=(spec.validation_type == "file"),
                metadata={"difficulty": spec.difficulty, "category": spec.category, "tags": spec.tags},
                _spec=spec,
            )
            for spec in specs
        ]

    def setup(self):
        """No-op setup — openclawbench tasks use per-task environment scripts."""
        return type("SetupResult", (), {"setup_data": {}})()


@dataclass
class ScenarioConfig:
    """Config entry for SCENARIO_CONFIGS."""

    name: str
    scenario_class: type

    def __init__(self, name: str, tasks_dir: Path = _TASKS_DIR):
        self.name = name
        # Create a class that binds the scenario name
        self.scenario_class = lambda remote_manager=None, _n=name, _d=tasks_dir: Scenario(
            scenario_name=_n, tasks_dir=_d, remote_manager=remote_manager
        )


# Auto-discover available scenarios from the tasks directory
def _build_scenario_configs(tasks_dir: Path = _TASKS_DIR) -> dict[str, ScenarioConfig]:
    configs = {}
    if tasks_dir.exists():
        for child in sorted(tasks_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                configs[child.name] = ScenarioConfig(child.name, tasks_dir)
    return configs


SCENARIO_CONFIGS: dict[str, ScenarioConfig] = _build_scenario_configs()
