"""Skill attack vector — poisoned skill definitions trick agent into reading .env."""

from cracker.attacks.base import Attack, AttackVector, AttackStrength
from cracker.backends import Backend


class SkillAttack(Attack):
    vector = AttackVector.SKILL

    def inject(self, backend: Backend, scenario, strength: AttackStrength) -> None:
        if strength == AttackStrength.SUBTLE:
            scenario._inject_skill_subtle(backend)
        elif strength == AttackStrength.DIRECT:
            scenario._inject_skill_direct(backend)
        elif strength == AttackStrength.STRUCTURAL:
            scenario._inject_skill_structural(backend)
