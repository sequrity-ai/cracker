"""Cracker scenarios — each exercises file, tool, and skill attack vectors."""

from cracker.scenario import CrackerScenario

from cracker.scenarios.code_review import CodeReviewScenario
from cracker.scenarios.data_analysis import DataAnalysisScenario
from cracker.scenarios.customer_support import CustomerSupportScenario
from cracker.scenarios.research_report import ResearchReportScenario

ALL_SCENARIOS: list[CrackerScenario] = [
    CodeReviewScenario(),
    DataAnalysisScenario(),
    CustomerSupportScenario(),
    ResearchReportScenario(),
]


def get_scenario(category: str) -> CrackerScenario | None:
    for s in ALL_SCENARIOS:
        if s.category == category:
            return s
    return None
