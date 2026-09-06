"""ensure postgis extension

Revision ID: 6574ffbbccff
Revises: 
Create Date: 2026-09-05 18:53:51.305200

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6574ffbbccff'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")


def downgrade() -> None:
    """Downgrade schema conservatively without dropping the PostGIS extension."""
    pass
