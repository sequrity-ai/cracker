"""Attack vector implementations for cracker benchmark."""

from cracker.attacks.base import Attack, AttackVector, AttackStrength, ALL_STRENGTHS
from cracker.attacks.file import FileAttack
from cracker.attacks.tool import ToolAttack
from cracker.attacks.skill import SkillAttack

_ATTACKS = {
    AttackVector.FILE: FileAttack(),
    AttackVector.TOOL: ToolAttack(),
    AttackVector.SKILL: SkillAttack(),
}


def get_attack(vector: str | AttackVector) -> Attack:
    if isinstance(vector, str):
        vector = AttackVector(vector)
    return _ATTACKS[vector]
