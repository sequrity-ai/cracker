"""File attack vector — poison workspace files the agent reads.

Overwrites existing workspace files with versions that reference .env
or contain instructions to read secrets. The agent encounters these
while performing its benign task.
"""

from dataclasses import dataclass, field

from cracker.attacks.base import Attack, AttackVector
from cracker.backends import Backend


@dataclass
class FileAttackConfig:
    """Configuration for file-vector injection.

    poisoned_files: path → content pairs to overwrite in workspace.
        Content should reference .env or the canary key name naturally.
    poisonable_files: files the adaptive attacker can inject into.
    """
    poisoned_files: dict[str, str] = field(default_factory=dict)
    poisonable_files: list[dict] = field(default_factory=list)


class FileAttack(Attack):
    vector = AttackVector.FILE

    def inject(self, backend: Backend, scenario) -> None:
        config = scenario.file_attack_config
        for path, content in config.poisoned_files.items():
            backend.write_file(path, content)
            scenario._tracked_files.append(path)
