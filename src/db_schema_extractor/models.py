from typing import List, Optional
from pydantic import BaseModel

class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    foreign_key_target: Optional[str] = None
    description: Optional[str] = None

class TableMetadata(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[ColumnMetadata]

class SchemaDump(BaseModel):
    database_name: str
    tables: List[TableMetadata]