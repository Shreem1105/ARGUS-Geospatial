"""create monitors table

Revision ID: 39c0dd284444
Revises: 6574ffbbccff
Create Date: 2026-09-05 19:03:39.230371

"""
from typing import Sequence, Union

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '39c0dd284444'
down_revision: Union[str, Sequence[str], None] = '6574ffbbccff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "monitors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("monitor_type", sa.String(length=64), nullable=False),
        sa.Column("sensitivity", sa.Float(), nullable=False),
        sa.Column("minimum_change_area_m2", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "minimum_change_area_m2 >= 0",
            name="ck_monitors_minimum_change_area_m2_non_negative",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitors")),
    )
    op.create_index(
        "ix_monitors_geometry_gist",
        "monitors",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_monitors_geometry_gist", table_name="monitors")
    op.drop_table("monitors")
