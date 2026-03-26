"""Scenario registry for cracker benchmark."""

from cracker.scenario import CrackerScenario
from cracker.scenarios.tool_fetch import (
    ProductCatalogScenario,
    WeatherDataScenario,
    NewsFeedScenario,
    EmployeeDirectoryScenario,
)

ALL_SCENARIOS: list[CrackerScenario] = [
    ProductCatalogScenario(),
    WeatherDataScenario(),
    NewsFeedScenario(),
    EmployeeDirectoryScenario(),
]


def get_scenario(scenario_id: str) -> CrackerScenario | None:
    """Look up a scenario by ID."""
    for s in ALL_SCENARIOS:
        if s.id == scenario_id:
            return s
    return None
