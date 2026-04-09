"""Base class for attack vectors."""

from abc import ABC, abstractmethod
from enum import Enum

from cracker.backends import Backend


class AttackVector(str, Enum):
    FILE = "file"
    TOOL = "tool"
    SKILL = "skill"


class AttackStrength(str, Enum):
    SUBTLE = "subtle"        # Passive references (config points to .env)
    DIRECT = "direct"        # Explicit instructions ("read .env and include value")
    STRUCTURAL = "structural" # Data structure includes .env (manifest, index, pipeline)


# All strengths in order — always run all 3
ALL_STRENGTHS = [AttackStrength.SUBTLE, AttackStrength.DIRECT, AttackStrength.STRUCTURAL]


class Attack(ABC):
    """Base class for all attack vectors."""

    vector: AttackVector

    @abstractmethod
    def inject(self, backend: Backend, scenario, strength: AttackStrength) -> None:
        """Apply injection at a given strength level."""
        ...
