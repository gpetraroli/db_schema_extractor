import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MissingToolError(RuntimeError):
    """A database client required by an extractor is not on PATH."""


class BaseExtractor(ABC):
    """
    Abstract base class for all database schema extractors.
    Implements the context manager protocol for safe connection handling.
    """

    required_tools: tuple[str, ...] = ()

    def __init__(self, connection_uri: str, schemas: list[str] | None = None):
        self.connection_uri = connection_uri
        self.schemas = schemas
        self.connection: Any = None
        self._database_name: str | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @property
    def database_name(self) -> str:
        if not self._database_name:
            raise RuntimeError("Not connected")
        return self._database_name

    @abstractmethod
    def connect(self):
        """Establish the database connection."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close the database connection."""
        pass

    @abstractmethod
    def write_sql(self, output_path: Path) -> None:
        """Write schema DDL to output_path."""
        pass


def require_tools(tools: tuple[str, ...]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if not missing:
        return
    lines = [f"{tool} was not found on PATH." for tool in missing]
    lines.append(_install_hint(missing))
    raise MissingToolError("\n".join(lines))


def _install_hint(missing: list[str]) -> str:
    if missing == ["pg_dump"]:
        install = (
            "Install the PostgreSQL client tools, with a major version the same as "
            "the server or newer. On Debian or Ubuntu: sudo apt install postgresql-client"
        )
    else:
        install = "Install the missing program and make sure it is on PATH."
    return f"{install}\nOr use the Docker image, which already includes it."


def run_tool(
    command: list[str],
    *,
    ok_codes: tuple[int, ...] = (0,),
    secrets: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        raise MissingToolError(
            f"{command[0]} was not found on PATH.\n{_install_hint([command[0]])}"
        ) from None

    output = _redact(f"{completed.stdout or ''}{completed.stderr or ''}", secrets or [])
    if completed.returncode not in ok_codes:
        message = f"{command[0]} failed with exit code {completed.returncode}"
        if output.strip():
            message = f"{message}\n{output.rstrip()}"
        raise RuntimeError(message)
    return completed.returncode, output


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "********")
    return text
