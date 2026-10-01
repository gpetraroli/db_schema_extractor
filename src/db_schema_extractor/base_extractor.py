from abc import ABC, abstractmethod
from typing import Any
from .models import SchemaDump

class BaseExtractor(ABC):
    """
    Abstract base class for all database schema extractors.
    Implements the context manager protocol for safe connection handling.
    """
    
    def __init__(self, connection_uri: str, schemas: list[str] | None = None):
        self.connection_uri = connection_uri
        self.schemas = schemas
        self.connection: Any = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @abstractmethod
    def connect(self):
        """Establish the database connection."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close the database connection."""
        pass

    @abstractmethod
    def extract_schema(self) -> SchemaDump:
        """Extract the structural schema and return standardized metadata."""
        pass
