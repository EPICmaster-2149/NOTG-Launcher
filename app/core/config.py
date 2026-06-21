from __future__ import annotations

import os
import sys
from pathlib import Path


_LOADED_ENV_FILES: set[Path] = set()
FEATURE_NOT_IMPLEMENTED_MESSAGE = "This feature is not yet implemented."


def load_local_env(*roots: Path | str | None) -> None:
    """Load local .env files without overriding real environment variables."""
    for env_file in _candidate_env_files(*roots):
        if env_file in _LOADED_ENV_FILES or not env_file.is_file():
            continue
        if _load_with_python_dotenv(env_file):
            _LOADED_ENV_FILES.add(env_file)
            continue
        _load_simple_env_file(env_file)
        _LOADED_ENV_FILES.add(env_file)


def get_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _candidate_env_files(*roots: Path | str | None) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []

    def add(root: Path | str | None) -> None:
        if root is None:
            return
        try:
            path = Path(root).resolve() / ".env"
        except OSError:
            return
        if path not in seen:
            candidates.append(path)
            seen.add(path)

    for root in roots:
        add(root)

    add(Path.cwd())
    if getattr(sys, "frozen", False):
        add(Path(sys.executable).resolve().parent)
    return candidates


def _load_with_python_dotenv(env_file: Path) -> bool:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    load_dotenv(env_file, override=False)
    return True


def _load_simple_env_file(env_file: Path) -> None:
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value.strip())


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
