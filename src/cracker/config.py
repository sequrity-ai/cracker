"""Configuration for Cracker."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from project root
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


class AttackerConfig(BaseModel):
    """Configuration for the attacker model (OpenRouter)."""

    model: str = Field(
        default_factory=lambda: os.getenv("ATTACKER_MODEL", "minimax/minimax-01"),
        description="Attacker model (OpenRouter format: provider/model)",
    )
    max_turns: int = Field(
        default_factory=lambda: int(os.getenv("ATTACKER_MAX_TURNS", "5")),
        description="Maximum refinement iterations",
    )
    temperature: float = Field(default=1.0)
    top_p: float = Field(default=0.5)


class CrackerConfig(BaseModel):
    """Main configuration for Cracker."""

    # API keys
    openrouter_api_key: str = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""),
    )
    openai_api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", ""),
    )

    # Backend selection
    backend: str = Field(
        default_factory=lambda: os.getenv("CRACKER_BACKEND", "local"),
        description="Backend type: 'local' or 'daytona'",
    )

    # Local backend
    local_agent_id: str = Field(
        default_factory=lambda: os.getenv("AGENT_ID", "main"),
    )

    # Daytona backend
    daytona_api_key: str | None = Field(
        default_factory=lambda: os.getenv("DAYTONA_API_KEY"),
    )
    daytona_api_url: str = Field(
        default_factory=lambda: os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api"),
    )
    daytona_image: str = Field(
        default_factory=lambda: os.getenv("DAYTONA_IMAGE", "ubuntu:22.04"),
    )

    # Attacker configuration
    attacker: AttackerConfig = Field(default_factory=AttackerConfig)

    # Workspace
    workspace_path: str = Field(default="/workspace")

    # Logging
    verbose: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    def validate_config(self) -> None:
        """Validate required configuration based on backend."""
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")

        if self.backend == "daytona":
            if not self.daytona_api_key:
                raise ValueError("DAYTONA_API_KEY is required for Daytona backend")
        elif self.backend not in ["local", "daytona"]:
            raise ValueError(f"Invalid backend: {self.backend}. Must be 'local' or 'daytona'")
