"""Backend implementations for Cracker: Local and Daytona."""

import json
import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from agent after running a task."""

    text: str
    success: bool
    latency: float
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    error: str | None = None


class Backend(ABC):
    """Abstract backend for running agents."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the backend (setup resources)."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the backend (cleanup resources)."""
        pass

    @abstractmethod
    def run_agent(self, prompt: str, timeout: int = 120) -> AgentResponse:
        """Run the agent with given prompt.

        Args:
            prompt: The task prompt/instruction
            timeout: Timeout in seconds

        Returns:
            AgentResponse with bot output
        """
        pass

    @abstractmethod
    def setup_workspace(self, setup_script: str | None = None) -> bool:
        """Setup workspace with seed data.

        Args:
            setup_script: Optional setup script to run

        Returns:
            True if setup succeeded
        """
        pass

    @abstractmethod
    def get_file_contents(self, file_path: str) -> str | None:
        """Get contents of a file from workspace.

        Args:
            file_path: Path to file (relative to workspace)

        Returns:
            File contents or None if not found
        """
        pass


class LocalBackend(Backend):
    """Local backend - runs openclaw CLI as subprocess."""

    def __init__(self, agent_id: str = "main", workspace_path: str = "/workspace"):
        self.agent_id = agent_id
        self.workspace_path = workspace_path

    def connect(self) -> None:
        """Local backend requires no connection setup."""
        logger.info("LocalBackend: Ready (no connection needed)")

    def disconnect(self) -> None:
        """Local backend requires no disconnection."""
        logger.info("LocalBackend: Cleanup complete")

    def run_agent(self, prompt: str, timeout: int = 120) -> AgentResponse:
        """Run openclaw agent CLI with prompt."""
        import time

        start_time = time.time()

        try:
            # Call: openclaw agent --message "..." --json
            result = subprocess.run(
                ["openclaw", "agent", "--message", prompt, "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            latency = time.time() - start_time

            if result.returncode == 0:
                # Parse JSON response
                try:
                    data = json.loads(result.stdout)
                    return AgentResponse(
                        text=data.get("response", result.stdout),
                        success=True,
                        latency=latency,
                        input_tokens=data.get("input_tokens", 0),
                        output_tokens=data.get("output_tokens", 0),
                        reasoning_tokens=data.get("reasoning_tokens", 0),
                        cache_read_tokens=data.get("cache_read_tokens", 0),
                    )
                except json.JSONDecodeError:
                    # Fallback to raw text
                    return AgentResponse(
                        text=result.stdout,
                        success=True,
                        latency=latency,
                    )
            else:
                return AgentResponse(
                    text=result.stdout or result.stderr,
                    success=False,
                    latency=latency,
                    error=result.stderr,
                )

        except subprocess.TimeoutExpired:
            return AgentResponse(
                text="",
                success=False,
                latency=timeout,
                error="Agent timed out",
            )
        except Exception as e:
            return AgentResponse(
                text="",
                success=False,
                latency=time.time() - start_time,
                error=str(e),
            )

    def setup_workspace(self, setup_script: str | None = None) -> bool:
        """Setup workspace by running setup script."""
        if not setup_script:
            return True

        try:
            result = subprocess.run(
                ["bash", "-c", setup_script],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.workspace_path,
            )
            if result.returncode != 0:
                logger.error(f"Setup failed: {result.stderr}")
                return False
            logger.info("Workspace setup complete")
            return True
        except Exception as e:
            logger.error(f"Setup error: {e}")
            return False

    def get_file_contents(self, file_path: str) -> str | None:
        """Read file from local filesystem."""
        from pathlib import Path

        full_path = Path(self.workspace_path) / file_path
        try:
            return full_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read {full_path}: {e}")
            return None


class DaytonaBackend(Backend):
    """Daytona backend - runs in cloud sandbox."""

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://app.daytona.io/api",
        image: str = "ubuntu:22.04",
        workspace_path: str = "/workspace",
    ):
        self.api_key = api_key
        self.api_url = api_url
        self.image = image
        self.workspace_path = workspace_path
        self._daytona = None
        self._sandbox = None

    def connect(self) -> None:
        """Create and start Daytona sandbox."""
        from daytona_sdk import Daytona, DaytonaConfig, CreateSandboxFromImageParams

        if self._sandbox is not None:
            return

        logger.info("Creating Daytona sandbox...")
        self._daytona = Daytona(DaytonaConfig(api_key=self.api_key, api_url=self.api_url))

        params = CreateSandboxFromImageParams(
            image=self.image,
            labels={"purpose": "cracker"},
        )

        self._sandbox = self._daytona.create(params, timeout=120)
        logger.info(f"Sandbox created: {self._sandbox.id}")

        # Install openclaw in sandbox
        self._exec_command("pip install openclaw")

    def disconnect(self) -> None:
        """Stop and delete Daytona sandbox."""
        if self._sandbox is not None:
            try:
                self._daytona.delete(self._sandbox)
                logger.info(f"Sandbox deleted: {self._sandbox.id}")
            except Exception as e:
                logger.warning(f"Failed to delete sandbox: {e}")
            self._sandbox = None

    def _exec_command(self, command: str, timeout: int = 60) -> tuple[int, str, str]:
        """Execute command in sandbox."""
        if self._sandbox is None:
            raise RuntimeError("Not connected. Call connect() first.")

        logger.debug(f"Executing: {command}")
        result = self._sandbox.process.exec(command, timeout=timeout)

        exit_code = getattr(result, "exit_code", 0)
        stdout = getattr(result, "result", str(result))
        stderr = getattr(result, "error", "")

        return exit_code, stdout, stderr

    def run_agent(self, prompt: str, timeout: int = 120) -> AgentResponse:
        """Run openclaw agent in Daytona sandbox."""
        import time

        start_time = time.time()

        try:
            # Escape quotes in prompt
            escaped_prompt = prompt.replace('"', '\\"')
            command = f'openclaw agent --message "{escaped_prompt}" --json'

            exit_code, stdout, stderr = self._exec_command(command, timeout=timeout)
            latency = time.time() - start_time

            if exit_code == 0:
                try:
                    data = json.loads(stdout)
                    return AgentResponse(
                        text=data.get("response", stdout),
                        success=True,
                        latency=latency,
                        input_tokens=data.get("input_tokens", 0),
                        output_tokens=data.get("output_tokens", 0),
                        reasoning_tokens=data.get("reasoning_tokens", 0),
                        cache_read_tokens=data.get("cache_read_tokens", 0),
                    )
                except json.JSONDecodeError:
                    return AgentResponse(text=stdout, success=True, latency=latency)
            else:
                return AgentResponse(
                    text=stdout or stderr,
                    success=False,
                    latency=latency,
                    error=stderr,
                )

        except Exception as e:
            return AgentResponse(
                text="",
                success=False,
                latency=time.time() - start_time,
                error=str(e),
            )

    def setup_workspace(self, setup_script: str | None = None) -> bool:
        """Setup workspace in sandbox."""
        if not setup_script:
            return True

        try:
            exit_code, stdout, stderr = self._exec_command(
                f"cd {self.workspace_path} && {setup_script}"
            )
            if exit_code != 0:
                logger.error(f"Setup failed: {stderr}")
                return False
            logger.info("Workspace setup complete")
            return True
        except Exception as e:
            logger.error(f"Setup error: {e}")
            return False

    def get_file_contents(self, file_path: str) -> str | None:
        """Read file from sandbox."""
        try:
            command = f"cat {self.workspace_path}/{file_path}"
            exit_code, stdout, stderr = self._exec_command(command)
            if exit_code == 0:
                return stdout
            else:
                logger.error(f"Failed to read {file_path}: {stderr}")
                return None
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return None
