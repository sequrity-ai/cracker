"""Cracker scenarios — vector-agnostic with benign/attack modes."""

from cracker.scenario import CrackerScenario

from cracker.scenarios.file_processing import FileProcessingScenario
from cracker.scenarios.data_analysis import DataAnalysisScenario
from cracker.scenarios.summarization import SummarizationScenario
from cracker.scenarios.web_api import WebApiScenario
from cracker.scenarios.code_review import CodeReviewScenario

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
