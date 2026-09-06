"""create change events table

Revision ID: 1d3d7df5b4a2
Revises: a7bd6f3f9d12
Create Date: 2026-09-06 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1d3d7df5b4a2"
down_revision: Union[str, None] = "a7bd6f3f9d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Float(), nullable=False),
        sa.Column("perimeter_m", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("mean_change_score", sa.Float(), nullable=False),
        sa.Column("max_change_score", sa.Float(), nullable=False),
        sa.Column("mean_abs_delta_ndvi", sa.Float(), nullable=True),
        sa.Column("mean_spectral_distance", sa.Float(), nullable=True),
        sa.Column("pixel_count", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'new'"), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("area_m2 >= 0", name="ck_change_events_area_m2_non_negative"),
        sa.CheckConstraint("perimeter_m >= 0", name="ck_change_events_perimeter_m_non_negative"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_change_events_confidence_range",
        ),
        sa.CheckConstraint(
            "pixel_count > 0",
            name="ck_change_events_pixel_count_positive",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_change_events_severity",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'reviewed', 'dismissed', 'confirmed')",
            name="ck_change_events_status",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["change_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_change_events_monitor_id", "change_events", ["monitor_id"], unique=False)
    op.create_index("ix_change_events_analysis_id", "change_events", ["analysis_id"], unique=False)
    op.create_index("ix_change_events_first_detected_at", "change_events", ["first_detected_at"], unique=False)
    op.create_index("ix_change_events_severity", "change_events", ["severity"], unique=False)
    op.create_index("ix_change_events_status", "change_events", ["status"], unique=False)
    op.create_index(
        "ix_change_events_geometry_gist",
        "change_events",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_geometry_gist", table_name="change_events")
    op.drop_index("ix_change_events_status", table_name="change_events")
    op.drop_index("ix_change_events_severity", table_name="change_events")
    op.drop_index("ix_change_events_first_detected_at", table_name="change_events")
    op.drop_index("ix_change_events_analysis_id", table_name="change_events")
    op.drop_index("ix_change_events_monitor_id", table_name="change_events")
    op.drop_table("change_events")
