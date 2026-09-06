"""create satellite observations table

Revision ID: f3180b7e2c7d
Revises: 39c0dd284444
Create Date: 2026-09-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3180b7e2c7d"
down_revision: Union[str, None] = "39c0dd284444"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "satellite_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("collection", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("sensor", sa.String(length=64), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_cover", sa.Float(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("assets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cloud_cover IS NULL OR (cloud_cover >= 0 AND cloud_cover <= 100)",
            name="ck_satellite_observations_cloud_cover_range",
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitors.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "provider",
            "collection",
            "item_id",
            name="uq_satellite_observations_monitor_provider_collection_item",
        ),
    )
    op.create_index(
        "ix_satellite_observations_monitor_id",
        "satellite_observations",
        ["monitor_id"],
        unique=False,
    )
    op.create_index(
        "ix_satellite_observations_acquired_at",
        "satellite_observations",
        ["acquired_at"],
        unique=False,
    )
    op.create_index(
        "ix_satellite_observations_monitor_acquired_at",
        "satellite_observations",
        ["monitor_id", "acquired_at"],
        unique=False,
    )
    op.create_index(
        "ix_satellite_observations_geometry_gist",
        "satellite_observations",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_satellite_observations_geometry_gist", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_monitor_acquired_at", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_acquired_at", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_monitor_id", table_name="satellite_observations")
    op.drop_table("satellite_observations")
