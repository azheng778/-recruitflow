"""expand agent message status

Revision ID: a52c8e1041be
Revises: a51f2b9d7340
Create Date: 2026-07-26 18:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a52c8e1041be"
down_revision: Union[str, None] = "a51f2b9d7340"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agent_messages", "status",
        existing_type=sa.String(length=20), type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("UPDATE agent_messages SET status='failed' WHERE CHAR_LENGTH(status) > 20")
    op.alter_column(
        "agent_messages", "status",
        existing_type=sa.String(length=30), type_=sa.String(length=20),
        existing_nullable=False,
    )
