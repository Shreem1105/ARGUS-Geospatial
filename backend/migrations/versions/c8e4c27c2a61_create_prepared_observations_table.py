"""create prepared observations table

Revision ID: c8e4c27c2a61
Revises: f3180b7e2c7d
Create Date: 2026-09-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c8e4c27c2a61"
down_revision: Union[str, None] = "f3180b7e2c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prepared_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'processing'"), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("valid_mask_uri", sa.Text(), nullable=True),
        sa.Column("preview_uri", sa.Text(), nullable=True),
        sa.Column("crs", sa.String(length=64), nullable=True),
        sa.Column("resolution_m", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("band_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cloud_fraction", sa.Float(), nullable=True),
        sa.Column("valid_fraction", sa.Float(), nullable=True),
        sa.Column("nodata_value", sa.Float(), nullable=True),
        sa.Column("processing_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_prepared_observations_status",
        ),
        sa.CheckConstraint(
            "cloud_fraction IS NULL OR (cloud_fraction >= 0 AND cloud_fraction <= 1)",
            name="ck_prepared_observations_cloud_fraction_range",
        ),
        sa.CheckConstraint(
            "valid_fraction IS NULL OR (valid_fraction >= 0 AND valid_fraction <= 1)",
            name="ck_prepared_observations_valid_fraction_range",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observation_id"], ["satellite_observations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "observation_id",
            name="uq_prepared_observations_monitor_observation",
        ),
    )
    op.create_index(
        "ix_prepared_observations_monitor_id",
        "prepared_observations",
        ["monitor_id"],
        unique=False,
    )
    op.create_index(
        "ix_prepared_observations_observation_id",
        "prepared_observations",
        ["observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_prepared_observations_status",
        "prepared_observations",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_prepared_observations_status", table_name="prepared_observations")
    op.drop_index("ix_prepared_observations_observation_id", table_name="prepared_observations")
    op.drop_index("ix_prepared_observations_monitor_id", table_name="prepared_observations")
    op.drop_table("prepared_observations")
