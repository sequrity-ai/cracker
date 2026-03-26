"""Scenario registry for cracker benchmark."""

from cracker.scenario import CrackerScenario
from cracker.scenarios.tool_fetch import (
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
    # Tool-fetch scenarios
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
    """Look up a scenario by ID."""
    for s in ALL_SCENARIOS:
        if s.id == scenario_id:
            return s
    return None
