"""add change event semantic analyses

Revision ID: 6d16f204f13f
Revises: fddca4fde52f
Create Date: 2026-09-10 18:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6d16f204f13f"
down_revision: Union[str, None] = "fddca4fde52f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_event_semantic_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_prepared_observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("after_prepared_observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("semantic_label", sa.String(length=64), nullable=False),
        sa.Column("semantic_confidence", sa.Float(), nullable=False),
        sa.Column("abstained", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("inference_method", sa.String(length=64), nullable=False),
        sa.Column("before_land_cover", sa.String(length=128), nullable=True),
        sa.Column("after_land_cover", sa.String(length=128), nullable=True),
        sa.Column("before_ndvi_mean", sa.Float(), nullable=True),
        sa.Column("after_ndvi_mean", sa.Float(), nullable=True),
        sa.Column("ndvi_delta", sa.Float(), nullable=True),
        sa.Column("before_ndwi_mean", sa.Float(), nullable=True),
        sa.Column("after_ndwi_mean", sa.Float(), nullable=True),
        sa.Column("ndwi_delta", sa.Float(), nullable=True),
        sa.Column("before_nbr_mean", sa.Float(), nullable=True),
        sa.Column("after_nbr_mean", sa.Float(), nullable=True),
        sa.Column("nbr_delta", sa.Float(), nullable=True),
        sa.Column("before_built_up_score", sa.Float(), nullable=True),
        sa.Column("after_built_up_score", sa.Float(), nullable=True),
        sa.Column("built_up_delta", sa.Float(), nullable=True),
        sa.Column("embedding_distance", sa.Float(), nullable=True),
        sa.Column("valid_pixel_coverage", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "semantic_label IN ("
            "'vegetation_decrease',"
            "'vegetation_increase',"
            "'built_area_increase',"
            "'built_area_decrease',"
            "'water_expansion',"
            "'water_contraction',"
            "'bare_ground_increase',"
            "'bare_ground_decrease',"
            "'mixed_change',"
            "'uncertain'"
            ")",
            name="ck_change_event_semantic_analyses_label",
        ),
        sa.CheckConstraint(
            "semantic_confidence >= 0 AND semantic_confidence <= 1",
            name="ck_change_event_semantic_analyses_confidence_range",
        ),
        sa.CheckConstraint(
            "valid_pixel_coverage IS NULL OR (valid_pixel_coverage >= 0 AND valid_pixel_coverage <= 1)",
            name="ck_change_event_semantic_analyses_valid_pixel_coverage_range",
        ),
        sa.CheckConstraint(
            "embedding_distance IS NULL OR embedding_distance >= 0",
            name="ck_change_event_semantic_emb_dist_non_negative",
        ),
        sa.ForeignKeyConstraint(["change_event_id"], ["change_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_analysis_id"], ["change_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["before_prepared_observation_id"], ["prepared_observations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["after_prepared_observation_id"], ["prepared_observations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "change_event_id",
            "model_name",
            "model_version",
            "inference_method",
            name="uq_change_event_semantic_analyses_event_model_version_method",
        ),
    )

    op.create_index(
        "ix_change_event_semantic_analyses_event_id",
        "change_event_semantic_analyses",
        ["change_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_change_event_semantic_analyses_analysis_id",
        "change_event_semantic_analyses",
        ["change_analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_change_event_semantic_analyses_semantic_label",
        "change_event_semantic_analyses",
        ["semantic_label"],
        unique=False,
    )
    op.create_index(
        "ix_change_event_semantic_analyses_created_at",
        "change_event_semantic_analyses",
        ["created_at"],
        unique=False,
    )

    op.add_column(
        "monitor_runs",
        sa.Column("semantics_computed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("monitor_runs", "semantics_computed")

    op.drop_index("ix_change_event_semantic_analyses_created_at", table_name="change_event_semantic_analyses")
    op.drop_index("ix_change_event_semantic_analyses_semantic_label", table_name="change_event_semantic_analyses")
    op.drop_index("ix_change_event_semantic_analyses_analysis_id", table_name="change_event_semantic_analyses")
    op.drop_index("ix_change_event_semantic_analyses_event_id", table_name="change_event_semantic_analyses")
    op.drop_table("change_event_semantic_analyses")
