"""agent v2 memory and tool runs

Revision ID: a51f2b9d7340
Revises: d2e439e15d77
Create Date: 2026-07-26 18:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a51f2b9d7340"
down_revision: Union[str, None] = "d2e439e15d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_conversations", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("agent_conversations", sa.Column("context_snapshot", sa.JSON(), nullable=True))
    op.add_column("agent_conversations", sa.Column("summary_through_message_id", sa.BigInteger(), nullable=True))
    op.add_column("agent_conversations", sa.Column("memory_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("agent_conversations", sa.Column("prompt_version", sa.String(length=40), nullable=True))

    op.create_table(
        "agent_user_preferences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_message_id"], ["agent_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "preference_key", name="uk_agent_preferences_user_key"),
    )
    op.create_index("ix_agent_preferences_user_status", "agent_user_preferences", ["user_id", "status"])

    op.create_table(
        "agent_tool_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.SmallInteger(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=True),
        sa.Column("side_effect", sa.String(length=20), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uk_agent_tool_runs_idempotency"),
    )
    op.create_index("ix_agent_tool_runs_conversation_request", "agent_tool_runs", ["conversation_id", "request_id"])
    op.create_index("ix_agent_tool_runs_status_created", "agent_tool_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_runs_status_created", table_name="agent_tool_runs")
    op.drop_index("ix_agent_tool_runs_conversation_request", table_name="agent_tool_runs")
    op.drop_table("agent_tool_runs")
    op.drop_index("ix_agent_preferences_user_status", table_name="agent_user_preferences")
    op.drop_table("agent_user_preferences")
    op.drop_column("agent_conversations", "prompt_version")
    op.drop_column("agent_conversations", "memory_version")
    op.drop_column("agent_conversations", "summary_through_message_id")
    op.drop_column("agent_conversations", "context_snapshot")
    op.drop_column("agent_conversations", "summary")
