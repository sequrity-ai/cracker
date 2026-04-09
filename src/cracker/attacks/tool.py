"""Tool attack vector — poisoned HTTP API responses trick agent into reading .env."""

from cracker.attacks.base import Attack, AttackVector, AttackStrength
from cracker.backends import Backend


class ToolAttack(Attack):
    vector = AttackVector.TOOL

    def inject(self, backend: Backend, scenario, strength: AttackStrength) -> None:
        if strength == AttackStrength.SUBTLE:
            scenario._inject_tool_subtle(backend)
        elif strength == AttackStrength.DIRECT:
            scenario._inject_tool_direct(backend)
        elif strength == AttackStrength.STRUCTURAL:
            scenario._inject_tool_structural(backend)
