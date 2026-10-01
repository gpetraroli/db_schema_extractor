import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseExtractor(ABC):
    """
    Abstract base class for all database schema extractors.
    Implements the context manager protocol for safe connection handling.
    """

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
        raise RuntimeError(f"{command[0]} was not found on PATH") from None

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
