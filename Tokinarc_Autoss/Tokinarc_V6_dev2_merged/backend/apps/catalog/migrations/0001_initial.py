"""
Tokinarc V6.C — apps/catalog/migrations/0001_initial.py

Initial schema cho catalog:
  - Tạo extension pgvector (yêu cầu Postgres user có quyền CREATE EXTENSION;
    nếu không, chạy thủ công: psql -c 'CREATE EXTENSION IF NOT EXISTS vector;'
    rồi đặt SEPARATE_DATABASE_AND_STATE_MIGRATION=True).
  - 12 bảng: Torch, Part, CompatibilityEdge, TorchPartMapping, ProcessEdge,
    GasFlowEdge, ConsumableSet, ConsumableSetItem, NegativeRule,
    CategoryVocabulary, PartNoAlias, PartEmbedding, SeedMeta.
  - HNSW index trên PartEmbedding.vector (cosine_ops, m=16, ef_construction=64).

Sau migration này, chạy:
    python manage.py seed_from_json data/tokinarc_data_v19.json
"""
import django.db.models.deletion
from django.db import migrations, models
import pgvector.django


def _create_vector_extension(apps, schema_editor):
    """Chỉ tạo extension pgvector trên Postgres. SQLite/khác → bỏ qua."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS vector;')


def _noop(apps, schema_editor):
    pass


def _create_part_embedding_db(apps, schema_editor):
    """Tạo bảng catalog_part_embedding theo từng vendor.

    - Postgres → cột vector(1024) + HNSW index (pgvector thật).
    - SQLite/khác → cột text, không HNSW (đủ để dev/test schema build sạch).
    """
    vendor = schema_editor.connection.vendor
    if vendor == 'postgresql':
        schema_editor.execute(
            """
            CREATE TABLE catalog_part_embedding (
                part_no    varchar(40) NOT NULL PRIMARY KEY,
                text_hash  varchar(64) NOT NULL,
                vector     vector(1024) NOT NULL,
                model_ver  varchar(40) NOT NULL,
                updated_at timestamptz NOT NULL
            );
            """
        )
        schema_editor.execute(
            'CREATE INDEX catalog_part_embedding_text_hash_idx '
            'ON catalog_part_embedding (text_hash);'
        )
        schema_editor.execute(
            'CREATE INDEX part_emb_hnsw ON catalog_part_embedding '
            'USING hnsw (vector vector_cosine_ops) '
            'WITH (m = 16, ef_construction = 64);'
        )
    else:
        # SQLite / khác: cột text thay cho vector, bỏ HNSW.
        schema_editor.execute(
            """
            CREATE TABLE catalog_part_embedding (
                part_no    varchar(40) NOT NULL PRIMARY KEY,
                text_hash  varchar(64) NOT NULL,
                vector     text NOT NULL,
                model_ver  varchar(40) NOT NULL,
                updated_at datetime NOT NULL
            );
            """
        )
        schema_editor.execute(
            'CREATE INDEX catalog_part_embedding_text_hash_idx '
            'ON catalog_part_embedding (text_hash);'
        )


def _drop_part_embedding_db(apps, schema_editor):
    schema_editor.execute('DROP TABLE IF EXISTS catalog_part_embedding;')


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        # ── 1. Cài extension pgvector (chỉ Postgres) ───────────────────────
        migrations.RunPython(_create_vector_extension, _noop),

        # ── 2. Torch ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Torch',
            fields=[
                ('model_code',       models.CharField(max_length=40, primary_key=True, serialize=False)),
                ('display_name_vi',  models.CharField(max_length=200)),
                ('display_name_en',  models.CharField(blank=True, max_length=200)),
                ('family',           models.CharField(blank=True, db_index=True, max_length=20)),
                ('ecosystem',        models.CharField(db_index=True, max_length=10)),
                ('current_class',    models.CharField(db_index=True, max_length=20)),
                ('body_type',        models.CharField(blank=True, max_length=20)),
                ('cooling',          models.CharField(blank=True, db_index=True, max_length=20)),
                ('process',          models.JSONField(default=list)),
                ('welding_process',  models.JSONField(default=list)),
                ('wire_size',        models.CharField(blank=True, max_length=40)),
                ('rated_dc_a',       models.IntegerField(blank=True, null=True)),
                ('rated_co2_a',      models.IntegerField(blank=True, null=True)),
                ('rated_mag_a',      models.IntegerField(blank=True, null=True)),
                ('rated_mig_a',      models.IntegerField(blank=True, null=True)),
                ('duty_cycle_pct',   models.IntegerField(blank=True, null=True)),
                ('duty_co2_pct',     models.IntegerField(blank=True, null=True)),
                ('duty_mag_pct',     models.IntegerField(blank=True, null=True)),
                ('weight_g',         models.IntegerField(blank=True, null=True)),
                ('has_shock_sensor', models.BooleanField(default=False)),
                ('shock_sensor_type',models.CharField(blank=True, max_length=40)),
                ('has_cylinder',     models.BooleanField(default=False)),
                ('has_air_cylinder', models.BooleanField(default=False)),
                ('is_detachable',    models.BooleanField(default=False)),
                ('is_ultralight',    models.BooleanField(default=False)),
                ('mounting',         models.CharField(blank=True, max_length=20)),
                ('connection_types', models.JSONField(default=list)),
                ('connector_type',   models.CharField(blank=True, max_length=40)),
                ('compatible_parts', models.JSONField(default=list)),
                ('editorial_picks',  models.JSONField(default=list)),
                ('tpm_count',        models.IntegerField(default=0)),
                ('price_vnd',        models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True)),
                ('price_unit',       models.CharField(default='cái', max_length=10)),
                ('price_note',       models.TextField(blank=True)),
                ('is_contact_price', models.BooleanField(default=False)),
                ('is_priority_sell', models.BooleanField(db_index=True, default=False)),
                ('price_updated',    models.CharField(blank=True, max_length=10)),
                ('price_tier',       models.CharField(blank=True, max_length=20)),
                ('specs',            models.JSONField(default=dict)),
                ('notes',            models.TextField(blank=True)),
                ('source',           models.CharField(blank=True, max_length=40)),
            ],
            options={
                'db_table': 'catalog_torch',
                'indexes': [
                    models.Index(fields=['ecosystem', 'current_class', 'cooling'], name='cat_torch_eco_cur_cool_idx'),
                    models.Index(fields=['family', 'current_class'], name='cat_torch_fam_cur_idx'),
                    models.Index(fields=['body_type', 'cooling'], name='cat_torch_body_cool_idx'),
                ],
            },
        ),

        # ── 3. Part ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Part',
            fields=[
                ('tokin_part_no',    models.CharField(max_length=40, primary_key=True, serialize=False)),
                ('category',         models.CharField(db_index=True, max_length=40)),
                ('ecosystem',        models.CharField(blank=True, db_index=True, max_length=10)),
                ('current_class',    models.CharField(blank=True, db_index=True, max_length=20)),
                ('display_name_vi',  models.CharField(max_length=200)),
                ('display_name_en',  models.CharField(blank=True, max_length=200)),
                ('wire_size_mm',     models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
                ('total_length_mm',  models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('body_length_mm',   models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('thread_type',      models.CharField(blank=True, max_length=30)),
                ('material',         models.CharField(blank=True, max_length=40)),
                ('tip_type',         models.CharField(blank=True, max_length=20)),
                ('wire_material',    models.CharField(blank=True, max_length=40)),
                ('supported_processes', models.JSONField(default=list)),
                ('p_part_nos',       models.JSONField(default=list)),
                ('d_part_nos',       models.JSONField(default=list)),
                ('o_part_nos',       models.JSONField(default=list)),
                ('p_model_codes',    models.JSONField(default=list)),
                ('d_model_codes',    models.JSONField(default=list)),
                ('o_model_codes',    models.JSONField(default=list)),
                ('compatible_with',  models.JSONField(default=list)),
                ('used_with',        models.JSONField(default=list)),
                ('torch_models',     models.JSONField(default=list)),
                ('applicable_torches', models.JSONField(default=list)),
                ('editorial_picks',  models.JSONField(default=list)),
                ('price_vnd',        models.DecimalField(blank=True, decimal_places=0, max_digits=14, null=True)),
                ('price_unit',       models.CharField(default='cái', max_length=10)),
                ('price_note',       models.TextField(blank=True)),
                ('is_contact_price', models.BooleanField(default=False)),
                ('is_priority_sell', models.BooleanField(db_index=True, default=False)),
                ('price_updated',    models.CharField(blank=True, max_length=10)),
                ('price_tier',       models.CharField(blank=True, max_length=20)),
                ('specs',            models.JSONField(default=dict)),
                ('source',           models.CharField(blank=True, max_length=40)),
                ('confidence',       models.DecimalField(decimal_places=2, default=1, max_digits=3)),
                ('notes',            models.TextField(blank=True)),
            ],
            options={
                'db_table': 'catalog_part',
                'indexes': [
                    models.Index(fields=['category', 'ecosystem'], name='cat_part_cat_eco_idx'),
                    models.Index(fields=['category', 'current_class'], name='cat_part_cat_cur_idx'),
                    models.Index(fields=['ecosystem', 'current_class', 'category'], name='cat_part_eco_cur_cat_idx'),
                    models.Index(fields=['is_priority_sell', 'category'], name='cat_part_prio_cat_idx'),
                ],
            },
        ),

        # ── 4. CompatibilityEdge ────────────────────────────────────────────
        migrations.CreateModel(
            name='CompatibilityEdge',
            fields=[
                ('id',            models.BigAutoField(primary_key=True, serialize=False)),
                ('from_part',     models.CharField(db_index=True, max_length=40)),
                ('to_part',       models.CharField(db_index=True, max_length=40)),
                ('relation_type', models.CharField(db_index=True, default='compatible_with', max_length=30)),
                ('priority_rank', models.IntegerField(default=0)),
                ('is_mandatory',  models.BooleanField(default=False)),
                ('confidence',    models.DecimalField(decimal_places=2, default=1, max_digits=3)),
                ('note',          models.CharField(blank=True, max_length=300)),
                ('source',        models.CharField(blank=True, max_length=40)),
                ('result_part',   models.CharField(blank=True, max_length=40)),
            ],
            options={
                'db_table': 'catalog_compatibility_edge',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('from_part', 'to_part', 'relation_type'),
                        name='uniq_compat_edge_triple',
                    ),
                ],
                'indexes': [
                    models.Index(fields=['from_part', 'relation_type', 'priority_rank'], name='cat_ce_from_rel_idx'),
                    models.Index(fields=['to_part', 'relation_type'], name='cat_ce_to_rel_idx'),
                ],
            },
        ),

        # ── 5. TorchPartMapping ─────────────────────────────────────────────
        migrations.CreateModel(
            name='TorchPartMapping',
            fields=[
                ('id',           models.BigAutoField(primary_key=True, serialize=False)),
                ('torch_model',  models.CharField(db_index=True, max_length=40)),
                ('part_no',      models.CharField(db_index=True, max_length=40)),
                ('part_role',    models.CharField(db_index=True, max_length=40)),
                ('ref_no',       models.CharField(blank=True, max_length=20)),
                ('is_mandatory', models.BooleanField(default=False)),
                ('confidence',   models.DecimalField(decimal_places=2, default=1, max_digits=3)),
                ('note',         models.CharField(blank=True, max_length=300)),
                ('source',       models.CharField(blank=True, max_length=40)),
                ('robot_model',  models.CharField(blank=True, max_length=40)),
                ('connection_type', models.CharField(blank=True, max_length=20)),
                ('wire_size_applicability', models.JSONField(default=list)),
            ],
            options={
                'db_table': 'catalog_torch_part_mapping',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('torch_model', 'part_no', 'part_role', 'ref_no'),
                        name='uniq_tpm',
                    ),
                ],
                'indexes': [
                    models.Index(fields=['torch_model', 'part_role'], name='cat_tpm_torch_role_idx'),
                    models.Index(fields=['part_no'], name='cat_tpm_part_idx'),
                ],
            },
        ),

        # ── 6. ProcessEdge ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProcessEdge',
            fields=[
                ('id',           models.BigAutoField(primary_key=True, serialize=False)),
                ('from_part',    models.CharField(db_index=True, max_length=40)),
                ('to_process',   models.CharField(db_index=True, max_length=20)),
                ('relation_type',models.CharField(default='supports_process', max_length=30)),
                ('is_preferred', models.BooleanField(default=False)),
                ('note',         models.CharField(blank=True, max_length=300)),
                ('source',       models.CharField(blank=True, max_length=40)),
            ],
            options={
                'db_table': 'catalog_process_edge',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('from_part', 'to_process', 'relation_type'),
                        name='uniq_process_edge',
                    ),
                ],
            },
        ),

        # ── 7. GasFlowEdge ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='GasFlowEdge',
            fields=[
                ('id',           models.BigAutoField(primary_key=True, serialize=False)),
                ('from_orifice', models.CharField(db_index=True, max_length=40)),
                ('to_nozzle',    models.CharField(db_index=True, max_length=40)),
                ('relation_type',models.CharField(default='fits_in_nozzle', max_length=30)),
                ('reason',       models.CharField(blank=True, max_length=500)),
                ('source',       models.CharField(blank=True, max_length=40)),
            ],
            options={
                'db_table': 'catalog_gas_flow_edge',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('from_orifice', 'to_nozzle', 'relation_type'),
                        name='uniq_gas_flow_edge',
                    ),
                ],
            },
        ),

        # ── 8. ConsumableSet ────────────────────────────────────────────────
        migrations.CreateModel(
            name='ConsumableSet',
            fields=[
                ('set_id',              models.CharField(max_length=60, primary_key=True, serialize=False)),
                ('display_name_vi',     models.CharField(max_length=200)),
                ('torch_current_class', models.CharField(blank=True, max_length=20)),
                ('ecosystem',           models.CharField(blank=True, max_length=10)),
                ('cooling_method',      models.CharField(blank=True, max_length=20)),
                ('default_wire_size_mm',models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
                ('torch_models',        models.JSONField(default=list)),
                ('notes',               models.TextField(blank=True)),
            ],
            options={'db_table': 'catalog_consumable_set'},
        ),

        # ── 9. ConsumableSetItem ────────────────────────────────────────────
        migrations.CreateModel(
            name='ConsumableSetItem',
            fields=[
                ('id',               models.BigAutoField(primary_key=True, serialize=False)),
                ('part_no',          models.CharField(db_index=True, max_length=40)),
                ('part_role',        models.CharField(blank=True, max_length=40)),
                ('priority_rank',    models.IntegerField(default=0)),
                ('is_mandatory',     models.BooleanField(default=False)),
                ('default_quantity', models.IntegerField(default=1)),
                ('note',             models.CharField(blank=True, max_length=300)),
                ('consumable_set',   models.ForeignKey(
                    db_column='consumable_set_id',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='catalog.consumableset',
                )),
            ],
            options={
                'db_table': 'catalog_consumable_set_item',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('consumable_set', 'part_no', 'part_role'),
                        name='uniq_consumable_item',
                    ),
                ],
            },
        ),

        # ── 10. NegativeRule ────────────────────────────────────────────────
        migrations.CreateModel(
            name='NegativeRule',
            fields=[
                ('rule_id',              models.CharField(max_length=60, primary_key=True, serialize=False)),
                ('description',          models.CharField(max_length=300)),
                ('from_category',        models.CharField(blank=True, max_length=40)),
                ('to_category',          models.CharField(blank=True, max_length=40)),
                ('from_ecosystem',       models.CharField(blank=True, max_length=10)),
                ('to_ecosystem',         models.CharField(blank=True, max_length=10)),
                ('from_current_class',   models.CharField(blank=True, max_length=20)),
                ('relation_type',        models.CharField(default='incompatible_with', max_length=30)),
                ('incompatibility_reason', models.TextField(blank=True)),
                ('confidence',           models.DecimalField(decimal_places=2, default=1, max_digits=3)),
                ('source',               models.CharField(blank=True, max_length=40)),
                ('extras',               models.JSONField(default=dict)),
            ],
            options={'db_table': 'catalog_negative_rule'},
        ),

        # ── 11. CategoryVocabulary ──────────────────────────────────────────
        migrations.CreateModel(
            name='CategoryVocabulary',
            fields=[
                ('en_term',       models.CharField(max_length=60, primary_key=True, serialize=False)),
                ('vi_term',       models.CharField(max_length=60)),
                ('part_category', models.CharField(db_index=True, max_length=40)),
                ('vi_aliases',    models.JSONField(default=list)),
            ],
            options={'db_table': 'catalog_category_vocabulary'},
        ),

        # ── 12. PartNoAlias ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='PartNoAlias',
            fields=[
                ('fake_pno', models.CharField(max_length=40, primary_key=True, serialize=False)),
                ('primary',  models.CharField(db_index=True, max_length=40)),
                ('alts',     models.JSONField(default=list)),
                ('note',     models.CharField(blank=True, max_length=300)),
            ],
            options={'db_table': 'catalog_part_no_alias'},
        ),

        # ── 13. PartEmbedding (vector + HNSW) — portable ────────────────────
        # State (model Django nhìn thấy) luôn là schema chuẩn Postgres:
        #   vector = VectorField(1024) + HnswIndex.
        # Database thật:
        #   - Postgres → tạo cột vector(1024) + HNSW index (pgvector).
        #   - SQLite/khác (dev/test) → tạo cột text, bỏ HNSW → migrate chạy sạch.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='PartEmbedding',
                    fields=[
                        ('part_no',    models.CharField(max_length=40, primary_key=True, serialize=False)),
                        ('text_hash',  models.CharField(db_index=True, max_length=64)),
                        ('vector',     pgvector.django.VectorField(dimensions=1024)),
                        ('model_ver',  models.CharField(default='BAAI/bge-m3', max_length=40)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'db_table': 'catalog_part_embedding',
                        'indexes': [
                            pgvector.django.HnswIndex(
                                name='part_emb_hnsw',
                                fields=['vector'],
                                m=16,
                                ef_construction=64,
                                opclasses=['vector_cosine_ops'],
                            ),
                        ],
                    },
                ),
            ],
            database_operations=[
                migrations.RunPython(_create_part_embedding_db, _drop_part_embedding_db),
            ],
        ),


        # ── 14. SeedMeta ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='SeedMeta',
            fields=[
                ('id',        models.IntegerField(default=1, primary_key=True, serialize=False)),
                ('version',   models.CharField(max_length=20)),
                ('seed_at',   models.DateTimeField(auto_now=True)),
                ('json_meta', models.JSONField(default=dict)),
                ('counts',    models.JSONField(default=dict)),
            ],
            options={'db_table': 'catalog_seed_meta'},
        ),
    ]
