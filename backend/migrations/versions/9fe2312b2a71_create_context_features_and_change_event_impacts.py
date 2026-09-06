"""create context features and change event impacts

Revision ID: 9fe2312b2a71
Revises: 1d3d7df5b4a2
Create Date: 2026-09-06 23:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9fe2312b2a71"
down_revision: Union[str, None] = "1d3d7df5b4a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "context_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_feature_id", sa.String(length=128), nullable=False),
        sa.Column("feature_type", sa.String(length=32), nullable=False),
        sa.Column("feature_subtype", sa.String(length=128), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
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
            "feature_type IN ('road', 'building', 'waterway', 'administrative')",
            name="ck_context_features_feature_type",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "provider",
            "provider_feature_id",
            "feature_type",
            name="uq_context_features_monitor_provider_feature_type",
        ),
    )

    op.create_index("ix_context_features_monitor_id", "context_features", ["monitor_id"], unique=False)
    op.create_index("ix_context_features_provider", "context_features", ["provider"], unique=False)
    op.create_index("ix_context_features_feature_type", "context_features", ["feature_type"], unique=False)
    op.create_index("ix_context_features_feature_subtype", "context_features", ["feature_subtype"], unique=False)
    op.create_index("ix_context_features_fetched_at", "context_features", ["fetched_at"], unique=False)
    op.create_index(
        "ix_context_features_geometry_gist",
        "context_features",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "change_event_impacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_feature_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("impact_type", sa.String(length=32), nullable=False),
        sa.Column(
            "intersection_geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("intersection_area_m2", sa.Float(), nullable=True),
        sa.Column("intersection_length_m", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "impact_type IN ('intersects', 'within_buffer', 'contains')",
            name="ck_change_event_impacts_impact_type",
        ),
        sa.CheckConstraint(
            "intersection_area_m2 IS NULL OR intersection_area_m2 >= 0",
            name="ck_change_event_impacts_intersection_area_non_negative",
        ),
        sa.CheckConstraint(
            "intersection_length_m IS NULL OR intersection_length_m >= 0",
            name="ck_change_event_impacts_intersection_length_non_negative",
        ),
        sa.CheckConstraint(
            "distance_m >= 0",
            name="ck_change_event_impacts_distance_non_negative",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["change_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["context_feature_id"], ["context_features.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "context_feature_id",
            "impact_type",
            name="uq_change_event_impacts_event_feature_impact_type",
        ),
    )

    op.create_index("ix_change_event_impacts_event_id", "change_event_impacts", ["event_id"], unique=False)
    op.create_index(
        "ix_change_event_impacts_context_feature_id",
        "change_event_impacts",
        ["context_feature_id"],
        unique=False,
    )
    op.create_index("ix_change_event_impacts_impact_type", "change_event_impacts", ["impact_type"], unique=False)
    op.create_index(
        "ix_change_event_impacts_intersection_geometry_gist",
        "change_event_impacts",
        ["intersection_geometry"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_change_event_impacts_intersection_geometry_gist",
        table_name="change_event_impacts",
    )
    op.drop_index("ix_change_event_impacts_impact_type", table_name="change_event_impacts")
    op.drop_index("ix_change_event_impacts_context_feature_id", table_name="change_event_impacts")
    op.drop_index("ix_change_event_impacts_event_id", table_name="change_event_impacts")
    op.drop_table("change_event_impacts")

    op.drop_index("ix_context_features_geometry_gist", table_name="context_features")
    op.drop_index("ix_context_features_fetched_at", table_name="context_features")
    op.drop_index("ix_context_features_feature_subtype", table_name="context_features")
    op.drop_index("ix_context_features_feature_type", table_name="context_features")
    op.drop_index("ix_context_features_provider", table_name="context_features")
    op.drop_index("ix_context_features_monitor_id", table_name="context_features")
    op.drop_table("context_features")

