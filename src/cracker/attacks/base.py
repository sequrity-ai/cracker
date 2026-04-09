"""Base class for attack vectors."""

from abc import ABC, abstractmethod
from enum import Enum

from cracker.backends import Backend


class AttackVector(str, Enum):
    FILE = "file"
    TOOL = "tool"
    SKILL = "skill"


class Attack(ABC):
    """Base class for all attack vectors.

    Each attack knows how to inject a canary into a scenario's workspace
    using a specific vector (file poisoning, HTTP API, skill definition).
    """

    vector: AttackVector

    @abstractmethod
    def inject(self, backend: Backend, scenario) -> None:
        """Apply injection to the scenario's workspace.

        Args:
            backend: Execution backend (Daytona/local)
            scenario: CrackerScenario instance with attack config
        """
        ...
