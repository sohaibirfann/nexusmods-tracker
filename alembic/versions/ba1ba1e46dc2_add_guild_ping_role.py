"""add guild ping role

Revision ID: ba1ba1e46dc2
Revises: 4441d002c874
Create Date: 2026-07-13 13:13:55.852354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba1ba1e46dc2'
down_revision: Union[str, Sequence[str], None] = '4441d002c874'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('guilds', sa.Column('ping_role_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('guilds', 'ping_role_id')
