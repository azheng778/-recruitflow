"""add resume OCR audit fields

Revision ID: a53f1b9c0d2e
Revises: a52c8e1041be
Create Date: 2026-07-27 10:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a53f1b9c0d2e"
down_revision: Union[str, None] = "a52c8e1041be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("extraction_method", sa.String(length=30), nullable=True))
    op.add_column("resumes", sa.Column("ocr_confidence", sa.Numeric(precision=5, scale=4), nullable=True))
    op.add_column("resumes", sa.Column("page_count", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "page_count")
    op.drop_column("resumes", "ocr_confidence")
    op.drop_column("resumes", "extraction_method")
