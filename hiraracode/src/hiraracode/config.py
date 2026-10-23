"""Runtime configuration for Hiraracode.

The security-relevant defaults are deliberately strict: no network, a read-only
root filesystem, dropped capabilities, a non-root user, and CPU/memory/pids/time
caps. Everything is overridable by environment variable, but the *safe* choice
is the default and you opt out of it, never into it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

# A caller names a *language*, never an image. This is the core containment
# decision: the set of images that can ever run is fixed here on the server,
# so a malicious caller cannot ask the daemon to run an arbitrary image.
#
# Each entry: image (allowlisted), cmd (argv run inside the container), and
# filename (where the submitted code is written in the workspace).
DEFAULT_LANGUAGES: dict[str, dict] = {
    "python": {
        "image": "python:3.12-slim",
        "cmd": ["python", "/workspace/main.py"],
        "filename": "main.py",
    },
    "node": {
        "image": "node:20-slim",
        "cmd": ["node", "/workspace/main.js"],
        "filename": "main.js",
    },
    "bash": {
        "image": "bash:5",
        "cmd": ["bash", "/workspace/main.sh"],
        "filename": "main.sh",
    },
}


@dataclass(frozen=True)
class LanguageSpec:
    """One runnable language: an allowlisted image and how to invoke it."""

    name: str
    image: str
    cmd: list[str]
    filename: str


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _load_languages() -> dict[str, LanguageSpec]:
    """Build the language allowlist: defaults, overlaid by CCODE_IMAGES JSON.

    CCODE_IMAGES is a JSON object mapping language name -> {image, cmd,
    filename}. It *adds to and overrides* the defaults, so an operator can add
    ``go`` or ``ruby`` (multi-language via images) or pin a different tag,
    without editing code.
    """
    langs = {
        name: LanguageSpec(name=name, **spec) for name, spec in DEFAULT_LANGUAGES.items()
    }
    raw = os.getenv("CCODE_IMAGES", "").strip()
    if raw:
        try:
            extra = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CCODE_IMAGES is not valid JSON: {exc}") from exc
        for name, spec in extra.items():
            if not isinstance(spec, dict) or "image" not in spec:
                raise ValueError(f"CCODE_IMAGES['{name}'] must include at least 'image'")
            cmd = spec.get("cmd")
            filename = spec.get("filename", f"main.{name}")
            if cmd is None:
                raise ValueError(f"CCODE_IMAGES['{name}'] must include 'cmd'")
            langs[name] = LanguageSpec(
                name=name, image=spec["image"], cmd=list(cmd), filename=filename
            )
    return langs


@dataclass(frozen=True)
class ExecConfig:
    """Sandbox knobs. Strict by default; loosen per host if you must."""

    languages: dict[str, LanguageSpec] = field(default_factory=_load_languages)

    # Wall-clock cap per execution. A run past this is killed and flagged.
    timeout: float = 30.0
    max_timeout: float = 120.0  # ceiling a caller-supplied timeout is clamped to

    # Container resource limits.
    memory: str = "256m"  # docker mem_limit; swap is pinned to this (no swap)
    cpus: float = 1.0  # fractional CPUs -> nano_cpus
    pids_limit: int = 128  # cap process count — blunts fork bombs

    # Writable tmpfs sizes (root fs is read-only; these are the only writable
    # mounts the code gets, and they vanish with the container).
    workspace_size: str = "64m"
    tmp_size: str = "64m"

    # Truncate each of stdout/stderr to this many bytes in the response.
    max_output_bytes: int = 100_000

    # Networking is OFF by default. Set CCODE_ALLOW_NETWORK=true only on a
    # trusted host: executed code with network can exfiltrate or phone home.
    allow_network: bool = False
    network: str = "bridge"  # docker network to attach when network is allowed

    # UID:GID the code runs as. 65534 is nobody:nogroup on Debian/Alpine slim
    # images. Never 0 — a root process in the container is a bigger blast
    # radius if a container escape is ever found.
    user: str = "65534:65534"

    # Pull an allowlisted image if the daemon does not have it yet. The image
    # still comes only from the allowlist above, never from the caller.
    auto_pull: bool = True

    # Remove the container after each run. Off only for debugging.
    remove: bool = True

    # Background jobs (job_start): wall-clock default and ceiling, how many
    # may run at once, and how long a finished job's logs are kept.
    job_timeout: float = 600.0
    job_max_timeout: float = 3600.0
    max_jobs: int = 4
    job_retention: float = 3600.0

    @classmethod
    def from_env(cls) -> "ExecConfig":
        base = cls(
            languages=_load_languages(),
            timeout=_env_float("CCODE_TIMEOUT", cls.timeout),
            max_timeout=_env_float("CCODE_MAX_TIMEOUT", cls.max_timeout),
            memory=os.getenv("CCODE_MEMORY", cls.memory).strip() or cls.memory,
            cpus=_env_float("CCODE_CPUS", cls.cpus),
            pids_limit=_env_int("CCODE_PIDS_LIMIT", cls.pids_limit),
            workspace_size=os.getenv("CCODE_WORKSPACE_SIZE", cls.workspace_size),
            tmp_size=os.getenv("CCODE_TMP_SIZE", cls.tmp_size),
            max_output_bytes=_env_int("CCODE_MAX_OUTPUT_BYTES", cls.max_output_bytes),
            allow_network=_env_bool("CCODE_ALLOW_NETWORK", cls.allow_network),
            network=os.getenv("CCODE_NETWORK", cls.network).strip() or cls.network,
            user=os.getenv("CCODE_USER", cls.user).strip() or cls.user,
            auto_pull=_env_bool("CCODE_AUTO_PULL", cls.auto_pull),
            remove=_env_bool("CCODE_REMOVE", cls.remove),
            job_timeout=_env_float("CCODE_JOB_TIMEOUT", cls.job_timeout),
            job_max_timeout=_env_float("CCODE_JOB_MAX_TIMEOUT", cls.job_max_timeout),
            max_jobs=_env_int("CCODE_MAX_JOBS", cls.max_jobs),
            job_retention=_env_float("CCODE_JOB_RETENTION", cls.job_retention),
        )
        return base

    def clamp_timeout(self, requested: float | None) -> float:
        """A caller may lower the timeout but never raise it past the ceiling."""
        if requested is None:
            return min(self.timeout, self.max_timeout)
        return max(0.1, min(float(requested), self.max_timeout))

    def with_languages(self, languages: dict[str, LanguageSpec]) -> "ExecConfig":
        return replace(self, languages=languages)


__all__ = ["DEFAULT_LANGUAGES", "ExecConfig", "LanguageSpec"]
