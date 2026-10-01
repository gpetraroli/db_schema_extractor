from typing import List, Optional
from pydantic import BaseModel

class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    description: Optional[str] = None

class ForeignKeyMetadata(BaseModel):
    name: str
    columns: List[str]
    target_table: str
    target_columns: List[str]

class TableMetadata(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[ColumnMetadata]
    foreign_keys: List[ForeignKeyMetadata] = []

class SchemaDump(BaseModel):
    database_name: str
    tables: List[TableMetadata]