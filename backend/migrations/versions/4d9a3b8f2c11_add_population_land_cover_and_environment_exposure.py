"""add population land-cover and environmental exposure tables

Revision ID: 4d9a3b8f2c11
Revises: 9fe2312b2a71
Create Date: 2026-09-07 00:35:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4d9a3b8f2c11"
down_revision: Union[str, None] = "9fe2312b2a71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "population_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("source_feature_id", sa.String(length=128), nullable=False),
        sa.Column("geography_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "population IS NULL OR population >= 0",
            name="ck_population_features_population_non_negative",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "provider",
            "dataset",
            "source_feature_id",
            name="uq_population_features_monitor_provider_dataset_source",
        ),
    )
    op.create_index("ix_population_features_monitor_id", "population_features", ["monitor_id"], unique=False)
    op.create_index("ix_population_features_dataset", "population_features", ["dataset"], unique=False)
    op.create_index(
        "ix_population_features_dataset_version",
        "population_features",
        ["dataset_version"],
        unique=False,
    )
    op.create_index("ix_population_features_fetched_at", "population_features", ["fetched_at"], unique=False)
    op.create_index(
        "ix_population_features_geometry_gist",
        "population_features",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "change_event_population_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("population_feature_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intersection_area_m2", sa.Float(), nullable=False),
        sa.Column("source_area_m2", sa.Float(), nullable=False),
        sa.Column("intersection_fraction", sa.Float(), nullable=False),
        sa.Column("source_population", sa.Integer(), nullable=True),
        sa.Column("estimated_exposed_population", sa.Float(), nullable=True),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "intersection_area_m2 >= 0",
            name="ck_ce_pop_exp_intersection_area_nn",
        ),
        sa.CheckConstraint(
            "source_area_m2 > 0",
            name="ck_ce_pop_exp_source_area_pos",
        ),
        sa.CheckConstraint(
            "intersection_fraction >= 0 AND intersection_fraction <= 1",
            name="ck_ce_pop_exp_fraction_range",
        ),
        sa.CheckConstraint(
            "source_population IS NULL OR source_population >= 0",
            name="ck_ce_pop_exp_source_pop_nn",
        ),
        sa.CheckConstraint(
            "estimated_exposed_population IS NULL OR estimated_exposed_population >= 0",
            name="ck_ce_pop_exp_est_pop_nn",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["change_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["population_feature_id"], ["population_features.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "population_feature_id",
            name="uq_ce_pop_exp_event_pop_feat",
        ),
    )
    op.create_index(
        "ix_ce_pop_exp_event_id",
        "change_event_population_exposures",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_ce_pop_exp_population_feature_id",
        "change_event_population_exposures",
        ["population_feature_id"],
        unique=False,
    )

    op.create_table(
        "monitor_land_cover_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("source_item_id", sa.String(length=255), nullable=False),
        sa.Column("asset_key", sa.String(length=128), nullable=False),
        sa.Column("asset_href", sa.Text(), nullable=False),
        sa.Column("asset_media_type", sa.String(length=128), nullable=True),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "provider",
            "dataset",
            name="uq_monitor_land_cover_sources_monitor_provider_dataset",
        ),
    )
    op.create_index(
        "ix_monitor_land_cover_sources_monitor_id",
        "monitor_land_cover_sources",
        ["monitor_id"],
        unique=False,
    )
    op.create_index("ix_monitor_land_cover_sources_dataset", "monitor_land_cover_sources", ["dataset"], unique=False)
    op.create_index(
        "ix_monitor_land_cover_sources_dataset_version",
        "monitor_land_cover_sources",
        ["dataset_version"],
        unique=False,
    )
    op.create_index(
        "ix_monitor_land_cover_sources_fetched_at",
        "monitor_land_cover_sources",
        ["fetched_at"],
        unique=False,
    )

    op.create_table(
        "change_event_land_cover_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("class_code", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(length=128), nullable=False),
        sa.Column("area_m2", sa.Float(), nullable=False),
        sa.Column("fraction_of_event", sa.Float(), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("area_m2 >= 0", name="ck_change_event_land_cover_exposures_area_non_negative"),
        sa.CheckConstraint(
            "fraction_of_event >= 0 AND fraction_of_event <= 1",
            name="ck_change_event_land_cover_exposures_fraction_range",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["change_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "dataset",
            "dataset_version",
            "class_code",
            name="uq_change_event_land_cover_exposures_event_dataset_class",
        ),
    )
    op.create_index(
        "ix_change_event_land_cover_exposures_event_id",
        "change_event_land_cover_exposures",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_change_event_land_cover_exposures_dataset",
        "change_event_land_cover_exposures",
        ["dataset"],
        unique=False,
    )
    op.create_index(
        "ix_change_event_land_cover_exposures_class_code",
        "change_event_land_cover_exposures",
        ["class_code"],
        unique=False,
    )

    op.create_table(
        "environmental_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("source_feature_id", sa.String(length=128), nullable=False),
        sa.Column("feature_type", sa.String(length=64), nullable=False),
        sa.Column("feature_subtype", sa.String(length=128), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("designation", sa.String(length=255), nullable=True),
        sa.Column("manager", sa.String(length=255), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "provider",
            "dataset",
            "source_feature_id",
            name="uq_environmental_features_monitor_provider_dataset_source",
        ),
    )
    op.create_index(
        "ix_environmental_features_monitor_id",
        "environmental_features",
        ["monitor_id"],
        unique=False,
    )
    op.create_index("ix_environmental_features_dataset", "environmental_features", ["dataset"], unique=False)
    op.create_index(
        "ix_environmental_features_dataset_version",
        "environmental_features",
        ["dataset_version"],
        unique=False,
    )
    op.create_index(
        "ix_environmental_features_feature_type",
        "environmental_features",
        ["feature_type"],
        unique=False,
    )
    op.create_index(
        "ix_environmental_features_feature_subtype",
        "environmental_features",
        ["feature_subtype"],
        unique=False,
    )
    op.create_index(
        "ix_environmental_features_fetched_at",
        "environmental_features",
        ["fetched_at"],
        unique=False,
    )
    op.create_index(
        "ix_environmental_features_geometry_gist",
        "environmental_features",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "change_event_environmental_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environmental_feature_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), nullable=False),
        sa.Column("intersection_area_m2", sa.Float(), nullable=True),
        sa.Column("intersection_fraction_of_event", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "relationship_type IN ('intersects', 'within_buffer')",
            name="ck_ce_env_exp_rel_type",
        ),
        sa.CheckConstraint(
            "intersection_area_m2 IS NULL OR intersection_area_m2 >= 0",
            name="ck_ce_env_exp_intersection_area_nn",
        ),
        sa.CheckConstraint(
            "intersection_fraction_of_event IS NULL OR "
            "(intersection_fraction_of_event >= 0 AND intersection_fraction_of_event <= 1)",
            name="ck_ce_env_exp_fraction_range",
        ),
        sa.CheckConstraint(
            "distance_m >= 0",
            name="ck_ce_env_exp_distance_nn",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["change_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environmental_feature_id"], ["environmental_features.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "environmental_feature_id",
            "relationship_type",
            name="uq_ce_env_exp_event_feature_rel",
        ),
    )
    op.create_index(
        "ix_ce_env_exp_event_id",
        "change_event_environmental_exposures",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_ce_env_exp_environmental_feature_id",
        "change_event_environmental_exposures",
        ["environmental_feature_id"],
        unique=False,
    )
    op.create_index(
        "ix_ce_env_exp_relationship_type",
        "change_event_environmental_exposures",
        ["relationship_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ce_env_exp_relationship_type",
        table_name="change_event_environmental_exposures",
    )
    op.drop_index(
        "ix_ce_env_exp_environmental_feature_id",
        table_name="change_event_environmental_exposures",
    )
    op.drop_index(
        "ix_ce_env_exp_event_id",
        table_name="change_event_environmental_exposures",
    )
    op.drop_table("change_event_environmental_exposures")

    op.drop_index("ix_environmental_features_geometry_gist", table_name="environmental_features")
    op.drop_index("ix_environmental_features_fetched_at", table_name="environmental_features")
    op.drop_index("ix_environmental_features_feature_subtype", table_name="environmental_features")
    op.drop_index("ix_environmental_features_feature_type", table_name="environmental_features")
    op.drop_index("ix_environmental_features_dataset_version", table_name="environmental_features")
    op.drop_index("ix_environmental_features_dataset", table_name="environmental_features")
    op.drop_index("ix_environmental_features_monitor_id", table_name="environmental_features")
    op.drop_table("environmental_features")

    op.drop_index(
        "ix_change_event_land_cover_exposures_class_code",
        table_name="change_event_land_cover_exposures",
    )
    op.drop_index(
        "ix_change_event_land_cover_exposures_dataset",
        table_name="change_event_land_cover_exposures",
    )
    op.drop_index(
        "ix_change_event_land_cover_exposures_event_id",
        table_name="change_event_land_cover_exposures",
    )
    op.drop_table("change_event_land_cover_exposures")

    op.drop_index("ix_monitor_land_cover_sources_fetched_at", table_name="monitor_land_cover_sources")
    op.drop_index("ix_monitor_land_cover_sources_dataset_version", table_name="monitor_land_cover_sources")
    op.drop_index("ix_monitor_land_cover_sources_dataset", table_name="monitor_land_cover_sources")
    op.drop_index("ix_monitor_land_cover_sources_monitor_id", table_name="monitor_land_cover_sources")
    op.drop_table("monitor_land_cover_sources")

    op.drop_index(
        "ix_ce_pop_exp_population_feature_id",
        table_name="change_event_population_exposures",
    )
    op.drop_index(
        "ix_ce_pop_exp_event_id",
        table_name="change_event_population_exposures",
    )
    op.drop_table("change_event_population_exposures")

    op.drop_index("ix_population_features_geometry_gist", table_name="population_features")
    op.drop_index("ix_population_features_fetched_at", table_name="population_features")
    op.drop_index("ix_population_features_dataset_version", table_name="population_features")
    op.drop_index("ix_population_features_dataset", table_name="population_features")
    op.drop_index("ix_population_features_monitor_id", table_name="population_features")
    op.drop_table("population_features")
