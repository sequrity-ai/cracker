"""Scenario registry for cracker benchmark."""

from cracker.scenario import CrackerScenario, AttackVector
from cracker.scenarios.file.naive_injection import NaiveInjection
from cracker.scenarios.file.manifest_processing import ManifestProcessing
from cracker.scenarios.file.config_pipeline import ConfigPipeline
from cracker.scenarios.file.index_lookup import IndexLookup
from cracker.scenarios.file.build_script import BuildScript
from cracker.scenarios.tool import (
    SalesReportScenario,
    CustomerFeedbackScenario,
    SystemLogsScenario,
    MeetingNotesScenario,
)
from cracker.scenarios.skill_inject import (
    DeployCheckScenario,
    CodeReviewScenario,
    OnboardScenario,
)


ALL_SCENARIOS: list[CrackerScenario] = [
    # File vector
    NaiveInjection(),
    ManifestProcessing(),
    ConfigPipeline(),
    IndexLookup(),
    BuildScript(),
    # Tool vector
    SalesReportScenario(),
    CustomerFeedbackScenario(),
    SystemLogsScenario(),
    MeetingNotesScenario(),
    # Skill-injection scenarios
    DeployCheckScenario(),
    CodeReviewScenario(),
    OnboardScenario(),
]


def get_scenario(scenario_id: str) -> CrackerScenario | None:
    for s in ALL_SCENARIOS:
        if s.id == scenario_id:
            return s
    return None


def get_scenarios_by_vector(vector: AttackVector) -> list[CrackerScenario]:
    return [s for s in ALL_SCENARIOS if s.vector == vector]


def list_scenarios() -> list[dict]:
    return [
        {"id": s.id, "name": s.name, "vector": s.vector.value, "tasks": len(s.tasks)}
        for s in ALL_SCENARIOS
    ]
