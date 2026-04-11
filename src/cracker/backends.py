"""Backend implementations for Cracker: Local and Daytona."""

import json
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from agent after running a task."""

    text: str
    success: bool
    latency: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class Backend(ABC):
    """Abstract backend for running agents."""

    workspace_path: str

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def run_agent(self, prompt: str, timeout: int = 120) -> AgentResponse:
        pass

    @abstractmethod
    def write_file(self, file_path: str, content: str) -> bool:
        pass

    @abstractmethod
    def read_file(self, file_path: str) -> str | None:
        pass

    @abstractmethod
    def file_exists(self, file_path: str) -> bool:
        pass

    @abstractmethod
    def delete_file(self, file_path: str) -> bool:
        pass

    @abstractmethod
    def list_files(self, directory: str = ".") -> list[str]:
        """List all files in the workspace (relative paths). Recursive."""
        pass

    def sync_local_workspace(self, local_path: str) -> None:
        """Upload local workspace files to the backend. No-op for local backend."""
        pass

    def start_http_server(self, routes: dict[str, str], port: int = 8099) -> int:
        """Start an HTTP server that serves workspace files at the given routes.

        Args:
            routes: Map of URL paths to workspace-relative file paths.
                    e.g. {"/api/products": "api_data/products.json"}
            port: Port to listen on. 0 = OS picks a free port.

        Returns:
            The actual port the server is listening on.
        """
        raise NotImplementedError("This backend does not support HTTP servers")

    def stop_http_server(self) -> None:
        """Stop the HTTP server if running."""
        pass


class LocalBackend(Backend):
    """Local backend - runs openclaw CLI as subprocess."""

    def __init__(self, agent_id: str = "main", workspace_path: str = "/tmp/openclaw_benchmark"):
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self._session_counter = 0
        self._http_server = None

    def connect(self) -> None:
        logger.info("LocalBackend: Ready (no connection needed)")

    def disconnect(self) -> None:
        self.stop_http_server()
        logger.info("LocalBackend: Cleanup complete")

    def start_http_server(self, routes: dict[str, str], port: int = 8099) -> int:
        from cracker.http_server import WorkspaceHTTPServer

        self.stop_http_server()
        self._http_server = WorkspaceHTTPServer(
            serve_dir=self.workspace_path,
            routes=routes,
            port=port,
        )
        return self._http_server.start()

    def stop_http_server(self) -> None:
        if self._http_server is not None:
            self._http_server.stop()
            self._http_server = None

    def _new_session_id(self) -> str:
        self._session_counter += 1
        return f"cracker-{int(time.time())}-{self._session_counter}"

    def run_agent(self, prompt: str, timeout: int = 120) -> AgentResponse:
        """Run openclaw agent CLI with prompt."""
        start_time = time.time()
        session_id = self._new_session_id()

        try:
            result = subprocess.run(
                [
                    "openclaw", "agent",
                    "--local",
                    "--agent", self.agent_id,
                    "--session-id", session_id,
                    "--message", prompt,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            latency = time.time() - start_time

            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    text = self._extract_response_text(data)
                    usage = data.get("meta", {}).get("agentMeta", {}).get("usage", {})
                    return AgentResponse(
                        text=text,
                        success=True,
                        latency=latency,
                        input_tokens=usage.get("input", 0),
                        output_tokens=usage.get("output", 0),
                        cache_read_tokens=usage.get("cacheRead", 0),
                        cost_usd=float(usage.get("cost", 0) or 0),
                    )
                except json.JSONDecodeError:
                    return AgentResponse(text=result.stdout, success=True, latency=latency)
            else:
                return AgentResponse(
                    text=result.stdout or result.stderr,
                    success=False,
                    latency=latency,
                    error=result.stderr,
                )

        except subprocess.TimeoutExpired:
            return AgentResponse(text="", success=False, latency=timeout, error="Agent timed out")
        except Exception as e:
            return AgentResponse(
                text="", success=False, latency=time.time() - start_time, error=str(e)
            )

    @staticmethod
    def _extract_response_text(data: dict) -> str:
        payloads = data.get("payloads", [])
        if payloads:
            # Collect text from ALL payloads — agent may return planning + result
            texts = []
            for payload in payloads:
                raw_text = payload.get("text", "")
                if not raw_text:
                    continue
                try:
                    inner = json.loads(raw_text)
                    if "final_return_value" in inner:
                        texts.append(str(inner["final_return_value"].get("value", raw_text)))
                    else:
                        texts.append(raw_text)
                except (json.JSONDecodeError, TypeError):
                    texts.append(raw_text)
            return "\n".join(texts) if texts else ""
        return data.get("response", str(data))

    def write_file(self, file_path: str, content: str) -> bool:
        full_path = Path(self.workspace_path) / file_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            logger.info(f"Wrote {full_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write {full_path}: {e}")
            return False

    def read_file(self, file_path: str) -> str | None:
        full_path = Path(self.workspace_path) / file_path
        try:
            return full_path.read_text()
        except Exception:
            return None

    def file_exists(self, file_path: str) -> bool:
        return (Path(self.workspace_path) / file_path).exists()

    def delete_file(self, file_path: str) -> bool:
        full_path = Path(self.workspace_path) / file_path
        try:
            full_path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def list_files(self, directory: str = ".") -> list[str]:
        root = Path(self.workspace_path) / directory
        if not root.exists():
            return []
        return [
            str(p.relative_to(self.workspace_path))
            for p in root.rglob("*")
            if p.is_file() and p.name != "_cracker_server.js"
        ]


class DaytonaBackend(Backend):
    """Daytona backend — runs openclaw agent in a cloud sandbox.

    Creates a Daytona sandbox with openclaw installed and configured to use
    the model under test via OpenRouter. The agent runs with real tool access
    (file read/write/exec) inside the sandbox, just like the local backend
    but isolated and with a configurable model.

    Sandbox is created on connect() and deleted on disconnect().
    """

    def __init__(
        self,
        openrouter_api_key: str,
        model_under_test: str,
        daytona_api_key: str,
        daytona_api_url: str = "https://app.daytona.io/api",
        image: str = "node:22-bookworm",
        workspace_path: str = "/tmp/openclaw_benchmark",
    ):
        self.openrouter_api_key = openrouter_api_key
        self.model_under_test = model_under_test
        self.daytona_api_key = daytona_api_key
        self.daytona_api_url = daytona_api_url
        self.image = image
        self.workspace_path = workspace_path
        self._daytona = None
        self._sandbox = None
        self._session_counter = 0
        self._http_server_port = None

    def connect(self) -> None:
        from daytona_sdk import Daytona, DaytonaConfig, CreateSandboxFromImageParams, Resources

        if self._sandbox is not None:
            return

        logger.info("Creating Daytona sandbox...")
        self._daytona = Daytona(DaytonaConfig(
            api_key=self.daytona_api_key,
            api_url=self.daytona_api_url,
        ))
        params = CreateSandboxFromImageParams(
            image=self.image,
            labels={"purpose": "cracker"},
            resources=Resources(cpu=2, memory=4, disk=10),
        )
        self._sandbox = self._daytona.create(params, timeout=120)
        logger.info(f"Sandbox created: {self._sandbox.id}")

        self._install_openclaw()
        self._exec(f"mkdir -p {self.workspace_path}")

    def disconnect(self) -> None:
        self.stop_http_server()
        if self._sandbox is not None:
            sandbox_id = self._sandbox.id
            try:
                self._daytona.delete(self._sandbox)
                logger.info(f"Sandbox deleted: {sandbox_id}")
            except Exception as e:
                logger.warning(f"Failed to delete sandbox {sandbox_id}: {e}")
            self._sandbox = None

    def start_http_server(self, routes: dict[str, str], port: int = 8099) -> int:
        """Start a Node.js HTTP server inside the sandbox.

        Writes a small server script, starts it in the background, and polls
        until it's listening. Node.js is guaranteed (sandbox uses node image).
        """
        self.stop_http_server()

        routes_json = json.dumps(routes)
        server_script = (
            "const http = require('http');\n"
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            f"const ROUTES = {routes_json};\n"
            f"const SERVE_DIR = '{self.workspace_path}';\n"
            f"const PORT = {port};\n"
            "const server = http.createServer((req, res) => {\n"
            "  const urlPath = req.url.split('?')[0];\n"
            "  const file = ROUTES[urlPath];\n"
            "  if (!file) { res.writeHead(404); res.end('Not found'); return; }\n"
            "  const full = path.join(SERVE_DIR, file);\n"
            "  fs.readFile(full, 'utf8', (err, data) => {\n"
            "    if (err) { res.writeHead(500); res.end(err.message); return; }\n"
            "    const ct = file.endsWith('.json') ? 'application/json' : 'text/plain';\n"
            "    res.writeHead(200, {'Content-Type': ct});\n"
            "    res.end(data);\n"
            "  });\n"
            "});\n"
            "server.listen(PORT, '127.0.0.1', () => {\n"
            "  console.log('READY:' + PORT);\n"
            "});\n"
        )

        # Upload and start the server
        script_path = f"{self.workspace_path}/_cracker_server.js"
        self._sandbox.fs.upload_file(
            server_script.encode("utf-8"), script_path
        )
        self._exec(f"nohup node {script_path} > /tmp/_cracker_server.log 2>&1 &")

        # Poll until server is listening (up to 5 seconds)
        import time
        for _ in range(10):
            time.sleep(0.5)
            exit_code, out = self._exec(
                f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/ 2>/dev/null || echo 'fail'"
            )
            if "404" in out or "200" in out:
                logger.info(f"Daytona HTTP server ready on port {port}")
                self._http_server_port = port
                return port

        logger.warning(f"Daytona HTTP server may not be ready on port {port}")
        self._http_server_port = port
        return port

    def stop_http_server(self) -> None:
        if self._http_server_port is not None:
            # Kill the node server process
            self._exec(
                f"pkill -f '_cracker_server.js' 2>/dev/null || true"
            )
            self._exec(
                f"rm -f {self.workspace_path}/_cracker_server.js"
            )
            logger.info("Daytona HTTP server stopped")
            self._http_server_port = None

    def _exec(self, command: str, timeout: int = 120) -> tuple[int, str]:
        if self._sandbox is None:
            raise RuntimeError("Not connected")
        result = self._sandbox.process.exec(command, timeout=timeout)
        exit_code = getattr(result, "exit_code", 0)
        stdout = getattr(result, "result", str(result))
        return exit_code, stdout

    def _install_openclaw(self) -> None:
        """Install openclaw and configure it with OpenRouter + model under test."""
        logger.info("Installing openclaw in sandbox...")

        # Check what we have
        exit_code, out = self._exec("which node && node --version && which npm && npm --version")
        logger.info(f"Node check: {out.strip()}")

        # If npm not found, install Node.js via nodesource
        if "not found" in out or exit_code != 0:
            logger.info("Node.js not found, installing via nodesource...")
            self._exec(
                "apt-get update -qq && apt-get install -y -qq curl ca-certificates > /dev/null 2>&1",
                timeout=120,
            )
            self._exec(
                "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - > /dev/null 2>&1",
                timeout=120,
            )
            self._exec(
                "apt-get install -y -qq nodejs > /dev/null 2>&1",
                timeout=120,
            )
            exit_code, out = self._exec("node --version && npm --version")
            logger.info(f"Node installed: {out.strip()}")

        # Install openclaw — use Sequrity fork for sequrity models
        if self.model_under_test.startswith("sequrity/"):
            logger.info("Installing openclaw from Sequrity fork (pre-built tarball)...")
            tarball = Path("/home/openclaw/openclaw/openclaw-2026.3.14.tgz")
            if not tarball.exists():
                raise RuntimeError(f"Sequrity openclaw tarball not found at {tarball}")
            self._sandbox.fs.upload_file(tarball.read_bytes(), "/tmp/openclaw.tgz")
            exit_code, out = self._exec("npm install -g /tmp/openclaw.tgz", timeout=180)
        else:
            exit_code, out = self._exec("npm install -g openclaw", timeout=180)
        if exit_code != 0:
            raise RuntimeError(f"Failed to install openclaw: {out.strip()[-300:]}")
        logger.info(f"openclaw installed: {out.strip()[-200:]}")

        # Write openclaw config
        config = self._build_openclaw_config()
        config_json = json.dumps(config, indent=2)
        self._exec("mkdir -p /root/.openclaw")
        self._sandbox.fs.upload_file(config_json.encode("utf-8"), "/root/.openclaw/openclaw.json")
        logger.info(f"openclaw configured with model: {self.model_under_test}")

        # Verify
        exit_code, version = self._exec("openclaw --version")
        if exit_code != 0 or "not found" in version:
            raise RuntimeError(f"openclaw not available after install: {version.strip()}")
        logger.info(f"openclaw version: {version.strip()}")

    def _build_openclaw_config(self) -> dict:
        """Build openclaw config for the model under test.

        Supports two providers:
        - sequrity/*: Uses Sequrity API with dual-LLM policy enforcement
        - anything else: Uses OpenRouter
        """
        model_id = self.model_under_test

        if model_id.startswith("sequrity/"):
            return self._build_sequrity_config(model_id)

        return {
            "models": {
                "providers": {
                    "openrouter": {
                        "baseUrl": "https://openrouter.ai/api/v1",
                        "apiKey": self.openrouter_api_key,
                        "api": "openai-completions",
                        "authHeader": True,
                        "models": [
                            {
                                "id": model_id,
                                "name": self.model_under_test,
                                "reasoning": False,
                                "input": ["text"],
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                                "contextWindow": 128000,
                                "maxTokens": 8192,
                            }
                        ],
                    }
                }
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary": f"openrouter/{model_id}",
                        "fallbacks": [],
                    },
                    "workspace": self.workspace_path,
                    "timeoutSeconds": 600,
                }
            },
            "gateway": {
                "port": 18789,
                "mode": "local",
                "bind": "loopback",
                "auth": {"mode": "token", "token": "cracker_bench_token"},
            },
        }

    def _build_sequrity_config(self, model_id: str) -> dict:
        """Build openclaw config using Sequrity proxy with policy enforcement.

        Supports two formats:
        - sequrity/gpt-5.2 → route via sequrity_azure (internal GPT-5.2)
        - sequrity/openrouter/minimax/minimax-m2.7 → route via openrouter proxy
        """
        import os
        seq_api_key = os.getenv("SEQURITY_API_KEY", "")

        # Parse model_id: "sequrity/<rest>"
        rest = model_id.split("/", 1)[1]  # "gpt-5.2" or "openrouter/minimax/minimax-m2.7"

        if rest.startswith("openrouter/"):
            # Sequrity proxying to OpenRouter
            upstream_model = rest[len("openrouter/"):]  # "minimax/minimax-m2.7"
            base_url = "https://api.sequrity.ai/control/chat/openrouter/v1"
            x_api_key = self.openrouter_api_key  # OpenRouter key for upstream
            model_name = upstream_model
        else:
            # Direct Sequrity (Azure GPT-5.2)
            base_url = "https://api.sequrity.ai/control/chat/sequrity_azure/v1"
            x_api_key = os.getenv("SEQURITY_AZURE_KEY", "")
            model_name = rest

        return {
            "models": {
                "providers": {
                    "sequrity": {
                        "baseUrl": base_url,
                        "apiKey": seq_api_key,
                        "api": "openai-completions",
                        "authHeader": True,
                        "headers": {
                            "X-Features": '{"agent_arch":"dual-llm"}',
                            "X-Policy": json.dumps({
                                "mode": "standard",
                                "codes": {
                                    "code": (
                                        'tool "read" {\n'
                                        '    must deny when path.value in {".env", ".secrets", ".credentials", "config/secrets.cfg"};\n'
                                        '    should allow always;\n'
                                        '}\n'
                                    ),
                                    "language": "sqrt",
                                },
                                "presets": {
                                    "default_allow": True,
                                    "default_allow_enforcement_level": "soft",
                                },
                            }),
                            "X-Config": '{"fsm":{"enable_multistep_planning":true,"disable_rllm":true,"max_n_turns":50,"max_pllm_steps":50,"max_pllm_failed_steps":10,"history_mismatch_policy":"restart_turn"},"response_format":{"strip_response_content":true}}',
                            "X-Api-Key": x_api_key,
                        },
                        "models": [
                            {
                                "id": model_name,
                                "name": f"Sequrity {model_name}",
                                "reasoning": False,
                                "input": ["text"],
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                                "contextWindow": 200000,
                                "maxTokens": 16384,
                                "compat": {
                                    "supportsDeveloperRole": False,
                                    "supportsUsageInStreaming": False,
                                    "supportsStrictMode": True,
                                },
                            }
                        ],
                    }
                }
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary": f"sequrity/{model_name}",
                        "fallbacks": [],
                    },
                    "workspace": self.workspace_path,
                    "timeoutSeconds": 600,
                }
            },
            "gateway": {
                "port": 18789,
                "mode": "local",
                "bind": "loopback",
                "auth": {"mode": "token", "token": "cracker_bench_token"},
            },
        }

    def _new_session_id(self) -> str:
        self._session_counter += 1
        return f"cracker-{int(time.time())}-{self._session_counter}"

    _RATE_LIMIT_PATTERNS = ["rate limit", "429", "rate_limit", "temporarily rate-limited"]
    _MAX_RETRIES = 3
    _BASE_DELAY = 30  # seconds

    @staticmethod
    def _is_rate_limited(text: str) -> bool:
        lower = text.lower()
        return any(p in lower for p in DaytonaBackend._RATE_LIMIT_PATTERNS)

    def run_agent(self, prompt: str, timeout: int = 300) -> AgentResponse:
        """Run openclaw agent inside the Daytona sandbox with rate-limit retry."""
        overall_start = time.time()

        for attempt in range(self._MAX_RETRIES + 1):
            start_time = time.time()
            session_id = self._new_session_id()

            cmd = (
                f"openclaw agent --agent main "
                f"--session-id {session_id} "
                f"--message {json.dumps(prompt)} "
                f"--json --timeout {timeout}"
            )
            logger.debug(f"Running in sandbox: openclaw agent --message '{prompt[:80]}...'")

            try:
                exit_code, stdout = self._exec(cmd, timeout=timeout + 60)
                latency = time.time() - start_time

                if not stdout or not stdout.strip():
                    if attempt < self._MAX_RETRIES:
                        delay = self._BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"Empty response (attempt {attempt+1}/{self._MAX_RETRIES+1}), "
                            f"retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        continue
                    return AgentResponse(
                        text="", success=False, latency=latency, error="Empty response from agent"
                    )

                # Parse JSON (may have non-JSON lines before it)
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError:
                    json_start = stdout.find("{")
                    if json_start >= 0:
                        try:
                            data = json.loads(stdout[json_start:])
                        except json.JSONDecodeError:
                            return AgentResponse(
                                text=stdout, success=False, latency=latency,
                                error=f"Failed to parse response",
                            )
                    else:
                        return AgentResponse(
                            text=stdout, success=False, latency=latency, error="No JSON in response",
                        )

                # Extract response text (same format as local backend)
                text = LocalBackend._extract_response_text(data)

                # Retry on rate limit
                if attempt < self._MAX_RETRIES and self._is_rate_limited(text):
                    delay = self._BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Rate limited (attempt {attempt+1}/{self._MAX_RETRIES+1}), "
                        f"retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue

                meta = data.get("meta", {})
                usage = meta.get("agentMeta", {}).get("usage", {})

                return AgentResponse(
                    text=text,
                    success=True,
                    latency=time.time() - overall_start,
                    input_tokens=usage.get("input", 0),
                    output_tokens=usage.get("output", 0),
                    cache_read_tokens=usage.get("cacheRead", 0),
                    cost_usd=float(usage.get("cost", 0) or 0),
                )

            except Exception as e:
                return AgentResponse(
                    text="", success=False, latency=time.time() - overall_start, error=str(e),
                )

        # All retries exhausted
        return AgentResponse(
            text="", success=False, latency=time.time() - overall_start,
            error=f"Rate limited after {self._MAX_RETRIES + 1} attempts",
        )

    def write_file(self, file_path: str, content: str) -> bool:
        try:
            full_path = file_path if file_path.startswith("/") else f"{self.workspace_path}/{file_path}"
            self._exec(f"mkdir -p $(dirname {full_path})")
            self._sandbox.fs.upload_file(content.encode("utf-8"), full_path)
            logger.info(f"Wrote {full_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write {file_path}: {e}")
            return False

    def read_file(self, file_path: str) -> str | None:
        try:
            full_path = file_path if file_path.startswith("/") else f"{self.workspace_path}/{file_path}"
            data = self._sandbox.fs.download_file(full_path)
            if data is not None:
                return data.decode("utf-8")
            return None
        except Exception:
            return None

    def file_exists(self, file_path: str) -> bool:
        try:
            full_path = file_path if file_path.startswith("/") else f"{self.workspace_path}/{file_path}"
            exit_code, _ = self._exec(f"test -f {full_path}")
            return exit_code == 0
        except Exception:
            return False

    def delete_file(self, file_path: str) -> bool:
        try:
            full_path = file_path if file_path.startswith("/") else f"{self.workspace_path}/{file_path}"
            self._exec(f"rm -f {full_path}")
            return True
        except Exception:
            return False

    def list_files(self, directory: str = ".") -> list[str]:
        result = []
        self._list_files_recursive(f"{self.workspace_path}/{directory}", self.workspace_path, result)
        return result

    def _list_files_recursive(self, remote_dir: str, base: str, result: list[str]) -> None:
        try:
            items = self._sandbox.fs.list_files(remote_dir)
        except Exception:
            return
        for item in items:
            name = item.name if hasattr(item, "name") else str(item)
            remote_path = f"{remote_dir}/{name}"
            is_dir = item.is_dir if hasattr(item, "is_dir") else False
            if is_dir:
                self._list_files_recursive(remote_path, base, result)
            else:
                rel = remote_path[len(base) + 1:]  # strip base + "/"
                if name != "_cracker_server.js":
                    result.append(rel)

    def sync_local_workspace(self, local_path: str) -> None:
        """Upload all files from a local workspace directory to the Daytona sandbox."""
        local_root = Path(local_path)
        if not local_root.exists():
            logger.warning(f"Local workspace {local_path} does not exist, skipping sync")
            return

        count = 0
        for local_file in local_root.rglob("*"):
            if not local_file.is_file():
                continue
            rel_path = local_file.relative_to(local_root)
            remote_path = f"{self.workspace_path}/{rel_path}"
            try:
                self._exec(f"mkdir -p $(dirname {remote_path})")
                self._sandbox.fs.upload_file(local_file.read_bytes(), remote_path)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to upload {rel_path}: {e}")

        logger.info(f"Synced {count} files from {local_path} to sandbox:{self.workspace_path}")

