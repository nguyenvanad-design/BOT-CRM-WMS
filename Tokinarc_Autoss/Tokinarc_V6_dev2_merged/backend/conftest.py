"""
Tokinarc V6 — pytest conftest.

Tự bật bypass pgvector + CREATE EXTENSION khi DB là SQLite (test mặc định).
Không ảnh hưởng khi DB là Postgres thật.
"""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tokinarc.settings.test')

# Bypass pgvector HNSW index khi không phải Postgres
import pgvector.django as _pg
_orig_create = _pg.HnswIndex.create_sql

def _safe_create(self, model, schema_editor, using=''):
    if schema_editor.connection.vendor != 'postgresql':
        return ''
    return _orig_create(self, model, schema_editor, using)

_pg.HnswIndex.create_sql = _safe_create

# Bypass CREATE EXTENSION RunSQL khi không phải Postgres
from django.db.migrations.operations.special import RunSQL  # noqa: E402

_orig_db_forwards = RunSQL.database_forwards

def _safe_db_forwards(self, app_label, schema_editor, from_state, to_state):
    sql = self.sql if isinstance(self.sql, str) else ' '.join(self.sql)
    if 'CREATE EXTENSION' in sql and schema_editor.connection.vendor != 'postgresql':
        return
    return _orig_db_forwards(self, app_label, schema_editor, from_state, to_state)

RunSQL.database_forwards = _safe_db_forwards
