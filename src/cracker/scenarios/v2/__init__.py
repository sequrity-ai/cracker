"""Cracker scenarios — vector-agnostic with benign/attack modes."""

from cracker.scenario import AttackVector
from cracker.scenario_v2 import CrackerScenario

from cracker.scenarios.v2.file_processing import FileProcessingScenario
from cracker.scenarios.v2.data_analysis import DataAnalysisScenario
from cracker.scenarios.v2.summarization import SummarizationScenario
from cracker.scenarios.v2.web_api import WebApiScenario
from cracker.scenarios.v2.code_review import CodeReviewScenario

ALL_SCENARIOS: list[CrackerScenario] = [
    FileProcessingScenario(),
    DataAnalysisScenario(),
    SummarizationScenario(),
    WebApiScenario(),
    CodeReviewScenario(),
]


def get_scenario(category: str) -> CrackerScenario | None:
    for s in ALL_SCENARIOS:
        if s.category == category:
            return s
    return None


def list_scenarios() -> list[dict]:
    return [
        {"category": s.category, "name": s.name, "task_count": len(s.tasks)}
        for s in ALL_SCENARIOS
    ]
