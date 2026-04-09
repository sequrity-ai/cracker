"""File attack vector — poisoned workspace files trick agent into reading .env."""

from cracker.attacks.base import Attack, AttackVector, AttackStrength
from cracker.backends import Backend


class FileAttack(Attack):
    vector = AttackVector.FILE

    def inject(self, backend: Backend, scenario, strength: AttackStrength) -> None:
        if strength == AttackStrength.SUBTLE:
            scenario._inject_file_subtle(backend)
        elif strength == AttackStrength.DIRECT:
            scenario._inject_file_direct(backend)
        elif strength == AttackStrength.STRUCTURAL:
            scenario._inject_file_structural(backend)
