from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uuid4_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_role_active", "role", "is_active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_owner", "status", "owner_id"),
        Index("ix_jobs_department", "department"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    job_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    job_name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    headcount: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_name", "name"),
        Index("ix_candidates_source_deleted", "source", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    city: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    current_company: Mapped[str | None] = mapped_column(String(150))
    years_of_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    skills: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    education: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    work_experience: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    projects: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CandidateJob(Base):
    __tablename__ = "candidate_jobs"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uk_candidate_jobs_candidate_job"),
        Index("ix_candidate_jobs_job_status", "job_id", "status"),
        Index("ix_candidate_jobs_owner_next", "owner_id", "next_action_at"),
        Index("ix_candidate_jobs_stage_time", "status", "stage_entered_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="new", nullable=False)
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, nullable=False
    )
    next_action: Mapped[str | None] = mapped_column(String(255))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index("ix_resumes_candidate", "candidate_id"),
        Index("ix_resumes_status_created", "parse_status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    corrected_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parse_status: Mapped[str] = mapped_column(String(30), default="uploaded", nullable=False)
    parser_model: Mapped[str | None] = mapped_column(String(100))
    extraction_method: Mapped[str | None] = mapped_column(String(30))
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    page_count: Mapped[int | None] = mapped_column(SmallInteger)
    parser_error_code: Mapped[str | None] = mapped_column(String(80))
    parser_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_candidate_job", "candidate_job_id", "scheduled_at"),
        Index("ix_interviews_interviewer_time", "interviewer_id", "scheduled_at"),
        Index("ix_interviews_status_time", "status", "scheduled_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    candidate_job_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    round: Mapped[str] = mapped_column(String(20), nullable=False)
    interview_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, default=60, nullable=False)
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    additional_interviewers: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    feedback_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Communication(Base):
    __tablename__ = "communications"
    __table_args__ = (
        Index("ix_communications_candidate_time", "candidate_id", "occurred_at"),
        Index("ix_communications_application", "candidate_job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False)
    candidate_job_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_jobs.id", ondelete="RESTRICT"))
    inbound_event_id: Mapped[int | None] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(80))
    next_action: Mapped[str | None] = mapped_column(String(255))
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_due", "status", "scheduled_at", "next_retry_at"),
        Index("ix_notifications_interview", "interview_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    candidate_job_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_jobs.id", ondelete="RESTRICT"))
    interview_id: Mapped[str | None] = mapped_column(ForeignKey("interviews.id", ondelete="RESTRICT"))
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_target", "target_type", "target_id", "created_at"),
        Index("ix_audit_user_time", "user_id", "created_at"),
        Index("ix_audit_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (Index("ix_agent_conversations_user_time", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    summary_through_message_id: Mapped[int | None] = mapped_column(BigInteger)
    memory_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("ix_agent_messages_conversation_time", "conversation_id", "created_at"),
        Index("ix_agent_messages_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(80))
    tool_input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tool_output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class AgentUserPreference(Base):
    __tablename__ = "agent_user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "preference_key", name="uk_agent_preferences_user_key"),
        Index("ix_agent_preferences_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    preference_key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class AgentToolRun(Base):
    __tablename__ = "agent_tool_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uk_agent_tool_runs_idempotency"),
        Index("ix_agent_tool_runs_conversation_request", "conversation_id", "request_id"),
        Index("ix_agent_tool_runs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    step_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    side_effect: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approvals_status_created", "status", "created_at"),
        Index("ix_approvals_application", "candidate_job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    candidate_job_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_jobs.id", ondelete="RESTRICT"))
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"))
    interview_id: Mapped[str | None] = mapped_column(ForeignKey("interviews.id", ondelete="RESTRICT"))
    request_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(80), nullable=False)
    proposed_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    requested_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision_comment: Mapped[str | None] = mapped_column(String(500))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    graph_thread_id: Mapped[str | None] = mapped_column(String(36))
    graph_checkpoint_ns: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class InboundEvent(Base):
    __tablename__ = "inbound_events"
    __table_args__ = (
        UniqueConstraint("source", "external_event_id", name="uk_inbound_source_event"),
        Index("ix_inbound_status_created", "processing_status", "created_at"),
        Index("ix_inbound_room_time", "room_external_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_external_id: Mapped[str | None] = mapped_column(String(128))
    room_external_id: Mapped[str | None] = mapped_column(String(128))
    message_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    relevance: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    processing_status: Mapped[str] = mapped_column(String(30), default="received", nullable=False)
    approval_request_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id", ondelete="RESTRICT"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )


class CandidateStatusHistory(Base):
    __tablename__ = "candidate_status_history"
    __table_args__ = (
        Index("ix_status_history_application_time", "candidate_job_id", "created_at"),
        Index("ix_status_history_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_job_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    operator_type: Mapped[str] = mapped_column(String(20), nullable=False)
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approval_request_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id", ondelete="RESTRICT"))
    inbound_event_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_events.id", ondelete="RESTRICT"))
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class DocumentSyncJob(Base):
    __tablename__ = "document_sync_jobs"
    __table_args__ = (
        Index("ix_sync_due", "status", "next_retry_at", "created_at"),
        Index("ix_sync_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sink_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_version: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    external_record_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, nullable=False
    )
