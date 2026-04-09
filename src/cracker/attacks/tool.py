"""Tool attack vector — embed canary in HTTP API response data.

Starts an HTTP server in the sandbox that serves data files containing
the canary UUID in metadata fields. The agent fetches this data as
part of its benign task.
"""

from dataclasses import dataclass, field

from cracker.attacks.base import Attack, AttackVector
from cracker.backends import Backend


@dataclass
class ToolAttackConfig:
    """Configuration for tool-vector injection.

    routes: URL path → workspace file path for HTTP server.
    api_data: workspace file path → content with embedded canary.
    port: HTTP server port.
    """
    routes: dict[str, str] = field(default_factory=dict)
    api_data: dict[str, str] = field(default_factory=dict)
    port: int = 8099


class ToolAttack(Attack):
    vector = AttackVector.TOOL

    def inject(self, backend: Backend, scenario) -> None:
        config = scenario.tool_attack_config
        for path, content in config.api_data.items():
            backend.write_file(path, content)
            scenario._tracked_files.append(path)
        scenario._http_server_port = backend.start_http_server(
            config.routes, config.port,
        )
