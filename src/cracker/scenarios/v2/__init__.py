"""V2 scenarios — vector-agnostic with benign/attack modes."""

from cracker.scenario import AttackVector
from cracker.scenario_v2 import CrackerScenarioV2

from cracker.scenarios.v2.file_processing import FileProcessingScenario

ALL_V2_SCENARIOS: list[CrackerScenarioV2] = [
    FileProcessingScenario(),
]


def get_v2_scenario(category: str) -> CrackerScenarioV2 | None:
    for s in ALL_V2_SCENARIOS:
        if s.category == category:
            return s
    return None


def list_v2_scenarios() -> list[dict]:
    return [
        {"category": s.category, "name": s.name, "task_count": len(s.tasks)}
        for s in ALL_V2_SCENARIOS
    ]
