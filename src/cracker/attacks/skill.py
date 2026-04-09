"""Skill attack vector — create poisoned skill definitions.

Writes a poisoned SKILL.md alongside clean skills. The poisoned skill
contains disguised instructions to read .env and output secrets as
part of a legitimate-sounding workflow step.
"""

from dataclasses import dataclass

from cracker.attacks.base import Attack, AttackVector
from cracker.backends import Backend


@dataclass
class SkillAttackConfig:
    """Configuration for skill-vector injection.

    poisoned_skill_name: skill directory name (e.g. "organize").
    poisoned_skill_content: SKILL.md content with injection.
    include_clean_skills: whether to also write clean lint/test/docs skills.
    """
    poisoned_skill_name: str
    poisoned_skill_content: str
    include_clean_skills: bool = True


class SkillAttack(Attack):
    vector = AttackVector.SKILL

    def inject(self, backend: Backend, scenario) -> None:
        config = scenario.skill_attack_config
        if config.include_clean_skills:
            scenario._write_clean_skills(backend)
        scenario._write_skill(backend, config.poisoned_skill_name, config.poisoned_skill_content)
