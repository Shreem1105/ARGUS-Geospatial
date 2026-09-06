"""create change analyses table

Revision ID: a7bd6f3f9d12
Revises: c8e4c27c2a61
Create Date: 2026-09-06 21:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7bd6f3f9d12"
down_revision: Union[str, None] = "c8e4c27c2a61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_prepared_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("after_prepared_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'processing'"), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("change_score_uri", sa.Text(), nullable=True),
        sa.Column("change_mask_uri", sa.Text(), nullable=True),
        sa.Column("valid_comparison_mask_uri", sa.Text(), nullable=True),
        sa.Column("preview_uri", sa.Text(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("minimum_change_area_m2", sa.Float(), nullable=False),
        sa.Column("changed_pixel_count", sa.Integer(), nullable=True),
        sa.Column("valid_pixel_count", sa.Integer(), nullable=True),
        sa.Column("changed_fraction", sa.Float(), nullable=True),
        sa.Column("changed_area_m2", sa.Float(), nullable=True),
        sa.Column("mean_change_score", sa.Float(), nullable=True),
        sa.Column("max_change_score", sa.Float(), nullable=True),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('processing', 'ready', 'failed')", name="ck_change_analyses_status"),
        sa.CheckConstraint(
            "before_prepared_id <> after_prepared_id",
            name="ck_change_analyses_distinct_prepared_ids",
        ),
        sa.CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_change_analyses_threshold_range",
        ),
        sa.CheckConstraint(
            "minimum_change_area_m2 >= 0",
            name="ck_change_analyses_minimum_change_area_non_negative",
        ),
        sa.CheckConstraint(
            "changed_pixel_count IS NULL OR changed_pixel_count >= 0",
            name="ck_change_analyses_changed_pixel_count_non_negative",
        ),
        sa.CheckConstraint(
            "valid_pixel_count IS NULL OR valid_pixel_count >= 0",
            name="ck_change_analyses_valid_pixel_count_non_negative",
        ),
        sa.CheckConstraint(
            "changed_fraction IS NULL OR (changed_fraction >= 0 AND changed_fraction <= 1)",
            name="ck_change_analyses_changed_fraction_range",
        ),
        sa.CheckConstraint(
            "changed_area_m2 IS NULL OR changed_area_m2 >= 0",
            name="ck_change_analyses_changed_area_non_negative",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["before_prepared_id"], ["prepared_observations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["after_prepared_id"], ["prepared_observations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitor_id",
            "before_prepared_id",
            "after_prepared_id",
            "algorithm",
            "algorithm_version",
            "threshold",
            "minimum_change_area_m2",
            name="uq_change_analyses_idempotent_key",
        ),
    )

    op.create_index("ix_change_analyses_monitor_id", "change_analyses", ["monitor_id"], unique=False)
    op.create_index("ix_change_analyses_created_at", "change_analyses", ["created_at"], unique=False)
    op.create_index(
        "ix_change_analyses_before_prepared_id",
        "change_analyses",
        ["before_prepared_id"],
        unique=False,
    )
    op.create_index(
        "ix_change_analyses_after_prepared_id",
        "change_analyses",
        ["after_prepared_id"],
        unique=False,
    )
    op.create_index("ix_change_analyses_status", "change_analyses", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_change_analyses_status", table_name="change_analyses")
    op.drop_index("ix_change_analyses_after_prepared_id", table_name="change_analyses")
    op.drop_index("ix_change_analyses_before_prepared_id", table_name="change_analyses")
    op.drop_index("ix_change_analyses_created_at", table_name="change_analyses")
    op.drop_index("ix_change_analyses_monitor_id", table_name="change_analyses")
    op.drop_table("change_analyses")
