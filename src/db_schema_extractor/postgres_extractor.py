import psycopg
from psycopg.rows import dict_row

from .base_extractor import BaseExtractor
from .models import SchemaDump, TableMetadata, ColumnMetadata

class PostgresExtractor(BaseExtractor):
    db_type = "postgres"

    def connect(self):
        self.connection = psycopg.connect(self.connection_uri, row_factory=dict_row)

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def extract_schema(self) -> SchemaDump:
        tables = []
        db_name = self.connection.info.dbname

        # Query updated to fetch table descriptions
        tables_query = """
            SELECT 
                table_name,
                table_schema,
                pg_catalog.obj_description((table_schema || '.' || table_name)::regclass, 'pg_class') AS description
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
        """
        
        # Query updated to fetch column descriptions based on their ordinal position
        columns_query = """
            SELECT 
                c.column_name, 
                c.data_type, 
                c.is_nullable,
                tc.constraint_type,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                pg_catalog.col_description((c.table_schema || '.' || c.table_name)::regclass::oid, c.ordinal_position) AS description
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu
                ON c.column_name = kcu.column_name AND c.table_name = kcu.table_name
            LEFT JOIN information_schema.table_constraints tc
                ON kcu.constraint_name = tc.constraint_name AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name AND tc.constraint_type = 'FOREIGN KEY'
            WHERE c.table_name = %s AND c.table_schema = %s;
        """

        with self.connection.cursor() as cursor:
            table_rows = cursor.execute(tables_query).fetchall()
            
            for tbl in table_rows:
                table_name = tbl['table_name']
                table_schema = tbl['table_schema']
                table_desc = tbl['description']
                
                col_rows = cursor.execute(columns_query, (table_name, table_schema)).fetchall()
                
                columns = []
                for col in col_rows:
                    fk_target = None
                    if col['constraint_type'] == 'FOREIGN KEY' and col['foreign_table_name']:
                        fk_target = f"{col['foreign_table_name']}.{col['foreign_column_name']}"

                    columns.append(ColumnMetadata(
                        name=col['column_name'],
                        data_type=col['data_type'],
                        is_nullable=(col['is_nullable'] == 'YES'),
                        is_primary_key=(col['constraint_type'] == 'PRIMARY KEY'),
                        foreign_key_target=fk_target,
                        description=col['description']
                    ))
                    
                tables.append(TableMetadata(
                    name=table_name, 
                    description=table_desc,
                    columns=columns
                ))

        return SchemaDump(database_name=db_name, tables=tables)