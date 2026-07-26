from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserRole(str, Enum):
    admin = "admin"
    hr = "hr"
    interviewer = "interviewer"


class JobStatus(str, Enum):
    draft = "draft"
    open = "open"
    closed = "closed"


class RecruitmentStage(str, Enum):
    new = "new"
    screening = "screening"
    interview_1 = "interview_1"
    interview_2 = "interview_2"
    final_interview = "final_interview"
    on_hold = "on_hold"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class JobCreate(StrictModel):
    job_code: str = Field(min_length=2, max_length=40)
    job_name: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=2)
    requirements: str = Field(min_length=2)
    location: str | None = Field(default=None, max_length=120)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    headcount: int = Field(default=1, ge=1, le=10000)
    owner_id: str
    status: JobStatus = JobStatus.draft

    @model_validator(mode="after")
    def validate_salary(self) -> "JobCreate":
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("salary_min must not exceed salary_max")
        return self


class JobPatch(StrictModel):
    version: int = Field(ge=1)
    job_name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=2)
    requirements: str | None = Field(default=None, min_length=2)
    location: str | None = Field(default=None, max_length=120)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    headcount: int | None = Field(default=None, ge=1, le=10000)
    owner_id: str | None = None


class CandidateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    city: str | None = Field(default=None, max_length=100)
    source: str = Field(default="manual", max_length=40)
    current_company: str | None = Field(default=None, max_length=150)
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=60)
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    work_experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
    job_id: str | None = None
    owner_id: str | None = None


class CandidatePatch(StrictModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    city: str | None = Field(default=None, max_length=100)
    current_company: str | None = Field(default=None, max_length=150)
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=60)
    skills: list[str] | None = None
    summary: str | None = None


class ApplicationCreate(StrictModel):
    job_id: str
    owner_id: str | None = None
    source: str = Field(default="manual", max_length=40)
    applied_at: datetime | None = None


class StatusChangeProposal(StrictModel):
    candidate_job_id: str
    target_status: RecruitmentStage
    reason: str | None = Field(default=None, max_length=500)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=64)


class InterviewCreate(StrictModel):
    candidate_job_id: str
    round: Literal["screening", "first", "second", "final"]
    interview_type: Literal["phone", "online", "onsite"]
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    interviewer_id: str
    additional_interviewers: list[str] = Field(default_factory=list)
    meeting_url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)


class InterviewFeedback(StrictModel):
    version: int = Field(ge=1)
    strengths: str = Field(min_length=1)
    weaknesses: str = Field(min_length=1)
    feedback: str = Field(min_length=1)
    recommendation: Literal["pass", "reject", "hold"]


class ApprovalDecision(StrictModel):
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)


class ResumeParsedData(StrictModel):
    name: str = ""
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    current_company: str | None = None
    years_of_experience: Decimal | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    work_experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
    confidence: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)


class ResumeConfirm(StrictModel):
    corrected_data: ResumeParsedData
    candidate_id: str | None = None
    job_id: str
    owner_id: str | None = None


class DemoInboundRequest(StrictModel):
    external_event_id: str | None = Field(default=None, max_length=128)
    sender_external_id: str = Field(default="hr_demo", max_length=128)
    room_external_id: str = Field(default="recruitment_demo_group", max_length=128)
    content: str = Field(min_length=1, max_length=4000)
    occurred_at: datetime | None = None


class AgentChatRequest(StrictModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=16, max_length=64)
    action_response: "AgentActionResponse | None" = None
    client_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)


class AgentActionResponse(StrictModel):
    action_id: str = Field(min_length=16, max_length=128)
    choice_id: str = Field(min_length=1, max_length=128)


class AgentConversationPatch(StrictModel):
    title: str = Field(min_length=1, max_length=80)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: ErrorBody | None = None
    request_id: str


class Page(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[Any]
