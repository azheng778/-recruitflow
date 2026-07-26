from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from docx import Document
from langchain_openai import ChatOpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .ocr import AliyunAdvancedOcrClient
from .services_error import OcrServiceError
from .models import (
    AgentConversation,
    AgentMessage,
    ApprovalRequest,
    AuditLog,
    Candidate,
    CandidateJob,
    CandidateStatusHistory,
    DocumentSyncJob,
    InboundEvent,
    Interview,
    Job,
    Notification,
    Resume,
    User,
    utcnow,
)
from .repositories import candidate_query, get_application, get_candidate, get_job, paginate
from .schemas import (
    ApplicationCreate,
    CandidateCreate,
    CandidatePatch,
    InterviewCreate,
    InterviewFeedback,
    JobCreate,
    JobPatch,
    ResumeConfirm,
    ResumeParsedData,
    StatusChangeProposal,
)


class BusinessError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class ResumeExtraction:
    text: str
    extraction_method: str
    ocr_confidence: Decimal | None
    page_count: int
    review_warnings: list[str]


STAGES = {
    "new",
    "screening",
    "interview_1",
    "interview_2",
    "final_interview",
    "on_hold",
    "offer",
    "hired",
    "rejected",
    "withdrawn",
}
HIGH_RISK = {"offer", "hired", "rejected", "withdrawn"}
AUTO_TRANSITIONS = {
    ("new", "screening"),
    ("screening", "interview_1"),
    ("interview_1", "interview_2"),
    ("interview_1", "final_interview"),
    ("interview_2", "final_interview"),
}
ALLOWED_TRANSITIONS = {
    "new": {"screening", "on_hold", "rejected", "withdrawn"},
    "screening": {"interview_1", "on_hold", "rejected", "withdrawn"},
    "interview_1": {"interview_2", "final_interview", "on_hold", "rejected", "withdrawn"},
    "interview_2": {"final_interview", "offer", "on_hold", "rejected", "withdrawn"},
    "final_interview": {"offer", "on_hold", "rejected", "withdrawn"},
    "on_hold": {"new", "screening", "interview_1", "interview_2", "final_interview", "rejected", "withdrawn"},
    "offer": {"hired", "rejected", "withdrawn"},
    "hired": set(),
    "rejected": set(),
    "withdrawn": set(),
}


def request_id() -> str:
    return str(uuid.uuid4())


def mask_phone(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) < 7:
        return "***"
    return f"{value[:3]}****{value[-4:]}"


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def audit(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: str,
    user: User | None,
    source: str,
    req_id: str,
    before: dict | None = None,
    after: dict | None = None,
    actor_type: str = "human",
) -> None:
    db.add(
        AuditLog(
            request_id=req_id,
            user_id=user.id if user else None,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before_data=before,
            after_data=after,
            source=source,
        )
    )


def enqueue_sync(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    event_key: str,
    sink_type: str = "local_excel",
) -> DocumentSyncJob:
    digest = hashlib.sha256(f"{sink_type}:{entity_type}:{entity_id}:{event_key}".encode()).hexdigest()
    item = DocumentSyncJob(
        sink_type=sink_type,
        entity_type=entity_type,
        entity_id=entity_id,
        operation="upsert",
        payload=payload,
        idempotency_key=digest,
    )
    db.add(item)
    return item


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "job_code": job.job_code,
        "job_name": job.job_name,
        "department": job.department,
        "location": job.location,
        "headcount": job.headcount,
        "owner_id": job.owner_id,
        "status": job.status,
        "version": job.version,
        "created_at": job.created_at,
    }


def candidate_row(candidate: Candidate, application: CandidateJob, job: Job) -> dict:
    return {
        "id": candidate.id,
        "name": candidate.name,
        "phone": mask_phone(candidate.phone),
        "email": mask_email(candidate.email),
        "city": candidate.city,
        "skills": candidate.skills,
        "source": application.source,
        "application_id": application.id,
        "job_id": job.id,
        "job_name": job.job_name,
        "status": application.status,
        "owner_id": application.owner_id,
        "next_action": application.next_action,
        "next_action_at": application.next_action_at,
        "version": application.version,
    }


def list_candidates(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    owner_id: str | None = None,
) -> dict:
    stmt = candidate_query(
        keyword=keyword, job_id=job_id, status=status, source=source, owner_id=owner_id
    ).order_by(Candidate.updated_at.desc())
    total, rows = paginate(db, stmt, page, page_size)
    return {
        "page": page,
        "page_size": min(100, page_size),
        "total": total,
        "items": [candidate_row(*row) for row in rows],
    }


def create_job(db: Session, data: JobCreate, user: User, req_id: str) -> Job:
    if user.role not in {"admin", "hr"}:
        raise BusinessError("PERMISSION_DENIED", "无权创建岗位", 403)
    job = Job(**data.model_dump(mode="python"))
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessError("DUPLICATE_RESOURCE", "岗位编码已存在", 409) from exc
    audit(db, action="job.create", target_type="job", target_id=job.id, user=user, source="web", req_id=req_id, after=job_dict(job))
    db.commit()
    return job


def patch_job(db: Session, job: Job, data: JobPatch, user: User, req_id: str) -> Job:
    if user.role not in {"admin", "hr"}:
        raise BusinessError("PERMISSION_DENIED", "无权修改岗位", 403)
    if job.version != data.version:
        raise BusinessError("VERSION_CONFLICT", "岗位已被其他操作修改", 409)
    before = job_dict(job)
    values = data.model_dump(exclude_none=True, exclude={"version"})
    min_salary = values.get("salary_min", job.salary_min)
    max_salary = values.get("salary_max", job.salary_max)
    if min_salary is not None and max_salary is not None and min_salary > max_salary:
        raise BusinessError("INVALID_REQUEST", "最低薪资不能高于最高薪资", 400)
    for key, value in values.items():
        setattr(job, key, value)
    job.version += 1
    audit(db, action="job.update", target_type="job", target_id=job.id, user=user, source="web", req_id=req_id, before=before, after=job_dict(job))
    db.commit()
    return job


def create_candidate(db: Session, data: CandidateCreate, user: User, req_id: str) -> Candidate:
    values = data.model_dump(exclude={"job_id", "owner_id"}, mode="json")
    if values.get("email"):
        values["email"] = values["email"].lower()
    candidate = Candidate(**values, created_by=user.id)
    db.add(candidate)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessError("DUPLICATE_RESOURCE", "手机号或邮箱已存在，请选择已有候选人", 409) from exc
    audit(db, action="candidate.create", target_type="candidate", target_id=candidate.id, user=user, source="web", req_id=req_id, after={"name": candidate.name, "source": candidate.source})
    if data.job_id:
        create_application_in_transaction(
            db,
            candidate=candidate,
            job_id=data.job_id,
            owner_id=data.owner_id or user.id,
            source=data.source,
            applied_at=utcnow(),
            user=user,
            req_id=req_id,
        )
    db.commit()
    return candidate


def create_application_in_transaction(
    db: Session,
    *,
    candidate: Candidate,
    job_id: str,
    owner_id: str,
    source: str,
    applied_at: datetime,
    user: User,
    req_id: str,
) -> CandidateJob:
    job = get_job(db, job_id)
    if not job:
        raise BusinessError("RESOURCE_NOT_FOUND", "岗位不存在", 404)
    if job.status != "open":
        raise BusinessError("JOB_CLOSED", "岗位未开放或已关闭", 409)
    app = CandidateJob(
        candidate_id=candidate.id,
        job_id=job.id,
        owner_id=owner_id,
        source=source,
        applied_at=applied_at,
        stage_entered_at=applied_at,
    )
    db.add(app)
    db.flush()
    db.add(
        CandidateStatusHistory(
            candidate_job_id=app.id,
            from_status=None,
            to_status="new",
            reason="创建应聘关系",
            operator_type="human",
            operator_id=user.id,
            request_id=req_id,
        )
    )
    audit(db, action="application.create", target_type="candidate_job", target_id=app.id, user=user, source="web", req_id=req_id, after={"candidate_id": candidate.id, "job_id": job.id, "status": "new"})
    enqueue_sync(db, entity_type="application", entity_id=app.id, payload={"candidate_id": candidate.id, "candidate_name": candidate.name, "job_id": job.id, "job_name": job.job_name, "status": "new"}, event_key=req_id)
    return app


def create_application(db: Session, candidate: Candidate, data: ApplicationCreate, user: User, req_id: str) -> CandidateJob:
    try:
        app = create_application_in_transaction(
            db,
            candidate=candidate,
            job_id=data.job_id,
            owner_id=data.owner_id or user.id,
            source=data.source,
            applied_at=(data.applied_at or utcnow()).replace(tzinfo=None),
            user=user,
            req_id=req_id,
        )
        db.commit()
        return app
    except IntegrityError as exc:
        db.rollback()
        raise BusinessError("DUPLICATE_RESOURCE", "候选人已应聘该岗位", 409) from exc


def patch_candidate(db: Session, candidate: Candidate, data: CandidatePatch, user: User, req_id: str) -> Candidate:
    if candidate.version != data.version:
        raise BusinessError("VERSION_CONFLICT", "候选人已被其他操作修改", 409)
    before = {"name": candidate.name, "phone": mask_phone(candidate.phone), "email": mask_email(candidate.email), "version": candidate.version}
    for key, value in data.model_dump(exclude_none=True, exclude={"version"}, mode="json").items():
        setattr(candidate, key, value)
    candidate.version += 1
    audit(db, action="candidate.update", target_type="candidate", target_id=candidate.id, user=user, source="web", req_id=req_id, before=before, after={"name": candidate.name, "phone": mask_phone(candidate.phone), "email": mask_email(candidate.email), "version": candidate.version})
    db.commit()
    return candidate


def application_payload(db: Session, app: CandidateJob) -> dict:
    candidate = db.get(Candidate, app.candidate_id)
    job = db.get(Job, app.job_id)
    return {
        "candidate_job_id": app.id,
        "candidate_id": app.candidate_id,
        "candidate_name": candidate.name if candidate else None,
        "job_id": app.job_id,
        "job_name": job.job_name if job else None,
        "status": app.status,
        "owner_id": app.owner_id,
        "next_action": app.next_action,
        "next_action_at": app.next_action_at.isoformat() if app.next_action_at else None,
        "updated_at": app.updated_at.isoformat(),
    }


def apply_status_in_transaction(
    db: Session,
    *,
    app: CandidateJob,
    target: str,
    reason: str | None,
    confidence: Decimal | None,
    user: User | None,
    req_id: str,
    actor_type: str,
    approval_id: str | None = None,
    inbound_event_id: int | None = None,
) -> None:
    old = app.status
    app.status = target
    app.stage_entered_at = utcnow()
    app.version += 1
    if target == "rejected":
        app.rejection_reason = reason
    db.add(
        CandidateStatusHistory(
            candidate_job_id=app.id,
            from_status=old,
            to_status=target,
            reason=reason,
            confidence=confidence,
            operator_type=actor_type,
            operator_id=user.id if user and actor_type == "human" else None,
            approval_request_id=approval_id,
            inbound_event_id=inbound_event_id,
            request_id=req_id,
        )
    )
    audit(db, action="application.status_change", target_type="candidate_job", target_id=app.id, user=user, source="agent" if actor_type == "agent" else "web", req_id=req_id, before={"status": old}, after={"status": target}, actor_type=actor_type)
    enqueue_sync(db, entity_type="application", entity_id=app.id, payload=application_payload(db, app), event_key=req_id)


def propose_status_change(
    db: Session,
    data: StatusChangeProposal,
    user: User | None,
    req_id: str,
    *,
    actor_type: str = "human",
    inbound_event_id: int | None = None,
) -> dict:
    app = get_application(db, data.candidate_job_id)
    if not app:
        raise BusinessError("RESOURCE_NOT_FOUND", "应聘关系不存在", 404)
    if app.version != data.version:
        raise BusinessError("VERSION_CONFLICT", "应聘关系已变化", 409)
    target = data.target_status.value
    previous_status = app.status
    if target not in ALLOWED_TRANSITIONS.get(app.status, set()):
        requires_approval = True
        risk_reason = f"非法或倒退阶段：{app.status} → {target}"
    else:
        confidence = data.confidence if data.confidence is not None else Decimal("1")
        requires_approval = (
            target in HIGH_RISK
            or (app.status, target) not in AUTO_TRANSITIONS
            or confidence < Decimal("0.85")
        )
        risk_reason = "高风险、低置信度或非常规阶段变更"
    if requires_approval:
        existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.idempotency_key == data.idempotency_key))
        if existing:
            return {
                "execution": "approval_required",
                "approval": {**approval_dict(existing), "candidate_job": application_payload(db, app)},
                "candidate_job": application_payload(db, app),
            }
        approval = ApprovalRequest(
            candidate_job_id=app.id,
            request_type="status_change",
            proposed_action="update_candidate_status",
            proposed_data={"target_status": target, "reason": data.reason, "inbound_event_id": inbound_event_id},
            reason=risk_reason,
            confidence=data.confidence,
            target_version=app.version,
            idempotency_key=data.idempotency_key,
            requested_by_type=actor_type,
            requested_by=user.id if user else None,
        )
        db.add(approval)
        db.flush()
        audit(db, action="approval.create", target_type="approval_request", target_id=approval.id, user=user, source="agent" if actor_type == "agent" else "web", req_id=req_id, after={"action": approval.proposed_action, "target_status": target}, actor_type=actor_type)
        db.commit()
        return {
            "execution": "approval_required",
            "approval": {**approval_dict(approval), "candidate_job": application_payload(db, app)},
            "candidate_job": application_payload(db, app),
        }
    apply_status_in_transaction(db, app=app, target=target, reason=data.reason, confidence=data.confidence, user=user, req_id=req_id, actor_type=actor_type, inbound_event_id=inbound_event_id)
    db.commit()
    return {
        "execution": "applied",
        "candidate_job": application_payload(db, app),
        "previous_status": previous_status,
        "reason": data.reason,
        "sync_status": "已加入同步队列",
    }


def approval_dict(item: ApprovalRequest) -> dict:
    return {
        "id": item.id,
        "candidate_job_id": item.candidate_job_id,
        "candidate_id": item.candidate_id,
        "request_type": item.request_type,
        "proposed_action": item.proposed_action,
        "proposed_data": item.proposed_data,
        "reason": item.reason,
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at,
    }


def approve_request(db: Session, approval: ApprovalRequest, version: int, user: User, req_id: str, comment: str | None = None) -> dict:
    if approval.status == "approved":
        return approval_dict(approval)
    if approval.status != "pending" or approval.version != version:
        raise BusinessError("VERSION_CONFLICT", "审批已处理或版本冲突", 409)
    if approval.proposed_action == "update_candidate_status":
        app = get_application(db, approval.candidate_job_id or "")
        if not app or app.version != approval.target_version:
            approval.status = "conflict"
            approval.version += 1
            db.commit()
            raise BusinessError("VERSION_CONFLICT", "目标数据已变化，请重新发起审批", 409)
        target = str(approval.proposed_data["target_status"])
        apply_status_in_transaction(db, app=app, target=target, reason=approval.proposed_data.get("reason"), confidence=approval.confidence, user=user, req_id=req_id, actor_type="human", approval_id=approval.id, inbound_event_id=approval.proposed_data.get("inbound_event_id"))
    elif approval.proposed_action == "soft_delete_candidate":
        candidate = get_candidate(db, approval.candidate_id or "", include_deleted=True)
        if not candidate or candidate.version != approval.target_version:
            approval.status = "conflict"
            approval.version += 1
            db.commit()
            raise BusinessError("VERSION_CONFLICT", "候选人已变化，请重新发起审批", 409)
        candidate.deleted_at = utcnow()
        candidate.version += 1
        audit(db, action="candidate.soft_delete", target_type="candidate", target_id=candidate.id, user=user, source="web", req_id=req_id, after={"deleted_at": candidate.deleted_at.isoformat()})
    else:
        raise BusinessError("INVALID_REQUEST", "不支持的审批动作", 400)
    approval.status = "approved"
    approval.decided_by = user.id
    approval.decision_comment = comment
    approval.decided_at = utcnow()
    approval.version += 1
    audit(db, action="approval.approve", target_type="approval_request", target_id=approval.id, user=user, source="web", req_id=req_id, after={"status": "approved"})
    db.commit()
    return approval_dict(approval)


def reject_request(db: Session, approval: ApprovalRequest, version: int, user: User, req_id: str, comment: str | None) -> dict:
    if not comment:
        raise BusinessError("VALIDATION_ERROR", "拒绝审批必须填写原因", 422)
    if approval.status != "pending" or approval.version != version:
        raise BusinessError("VERSION_CONFLICT", "审批已处理或版本冲突", 409)
    approval.status = "rejected"
    approval.decided_by = user.id
    approval.decision_comment = comment
    approval.decided_at = utcnow()
    approval.version += 1
    audit(db, action="approval.reject", target_type="approval_request", target_id=approval.id, user=user, source="web", req_id=req_id, after={"status": "rejected"})
    db.commit()
    return approval_dict(approval)


def create_delete_approval(db: Session, candidate: Candidate, version: int, reason: str, idempotency_key: str, user: User, req_id: str) -> ApprovalRequest:
    if candidate.version != version:
        raise BusinessError("VERSION_CONFLICT", "候选人已变化", 409)
    existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.idempotency_key == idempotency_key))
    if existing:
        return existing
    approval = ApprovalRequest(
        candidate_id=candidate.id,
        request_type="delete_candidate",
        proposed_action="soft_delete_candidate",
        proposed_data={},
        reason=reason,
        target_version=candidate.version,
        idempotency_key=idempotency_key,
        requested_by_type="human",
        requested_by=user.id,
    )
    db.add(approval)
    db.flush()
    audit(db, action="approval.create", target_type="approval_request", target_id=approval.id, user=user, source="web", req_id=req_id, after={"action": "soft_delete_candidate"})
    db.commit()
    return approval


def create_interview(db: Session, data: InterviewCreate, user: User, req_id: str) -> Interview:
    app = get_application(db, data.candidate_job_id)
    if not app:
        raise BusinessError("RESOURCE_NOT_FOUND", "应聘关系不存在", 404)
    job = get_job(db, app.job_id)
    if not job or job.status != "open":
        raise BusinessError("JOB_CLOSED", "岗位已关闭", 409)
    interview = Interview(**data.model_dump(mode="python"), created_by=user.id)
    if interview.scheduled_at.tzinfo:
        interview.scheduled_at = interview.scheduled_at.astimezone().replace(tzinfo=None)
    db.add(interview)
    db.flush()
    remind_at = interview.scheduled_at - timedelta(hours=24)
    if remind_at < utcnow():
        remind_at = utcnow()
    db.add(Notification(candidate_job_id=app.id, interview_id=interview.id, channel="in_app", recipient_type="user", recipient=interview.interviewer_id, content=f"面试提醒：{interview.scheduled_at.isoformat(timespec='minutes')}", scheduled_at=remind_at))
    audit(db, action="interview.create", target_type="interview", target_id=interview.id, user=user, source="web", req_id=req_id, after={"candidate_job_id": app.id, "scheduled_at": interview.scheduled_at.isoformat()})
    db.commit()
    return interview


def record_feedback(db: Session, interview: Interview, data: InterviewFeedback, user: User, req_id: str) -> Interview:
    if interview.version != data.version:
        raise BusinessError("VERSION_CONFLICT", "面试记录已变化", 409)
    if user.role == "interviewer" and interview.interviewer_id != user.id:
        raise BusinessError("PERMISSION_DENIED", "只能填写分配给自己的面试", 403)
    interview.strengths = data.strengths
    interview.weaknesses = data.weaknesses
    interview.feedback = data.feedback
    interview.recommendation = data.recommendation
    interview.ai_summary = f"优势：{data.strengths[:120]}；风险：{data.weaknesses[:120]}；建议：{data.recommendation}"
    interview.feedback_submitted_at = interview.feedback_submitted_at or utcnow()
    interview.status = "completed"
    interview.version += 1
    audit(db, action="interview.feedback", target_type="interview", target_id=interview.id, user=user, source="web", req_id=req_id, after={"recommendation": data.recommendation})
    db.commit()
    return interview


def get_aliyun_ocr_client() -> AliyunAdvancedOcrClient:
    return AliyunAdvancedOcrClient()


def _prepare_image_for_ocr(image_bytes: bytes) -> bytes:
    """Validate image dimensions and make a compliant OCR payload without persisting pixels."""
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            source.verify()
        with Image.open(BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise BusinessError("INVALID_IMAGE", "图片文件损坏或格式不受支持", 422) from exc
    width, height = image.size
    if min(width, height) < 15:
        raise BusinessError("INVALID_IMAGE_DIMENSIONS", "图片最短边不得小于 15 像素", 422)
    if width * height > 80_000_000:
        raise BusinessError("IMAGE_TOO_LARGE", "图片像素过大，无法安全解析", 413)
    max_edge = 8192
    if max(width, height) > max_edge:
        ratio = max_edge / max(width, height)
        image = image.resize((max(15, int(width * ratio)), max(15, int(height * ratio))), Image.Resampling.LANCZOS)

    # The provider caps base64 at 25 MB. JPEG is only used after a resize/re-encode is required.
    def as_jpeg(current: Image.Image, quality: int) -> bytes:
        output = BytesIO()
        current.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()

    encoded_size = lambda raw: ((len(raw) + 2) // 3) * 4
    prepared = image_bytes if max(width, height) <= max_edge else as_jpeg(image, 90)
    if encoded_size(prepared) <= 25 * 1024 * 1024:
        return prepared
    while encoded_size(prepared) > 25 * 1024 * 1024 and min(image.size) >= 15:
        image = image.resize((max(15, int(image.width * 0.78)), max(15, int(image.height * 0.78))), Image.Resampling.LANCZOS)
        prepared = as_jpeg(image, 85)
    if encoded_size(prepared) > 25 * 1024 * 1024:
        raise BusinessError("OCR_IMAGE_TOO_LARGE", "图片压缩后仍超过 OCR 服务 25MB 限制", 413)
    return prepared


def _ocr_image(image_bytes: bytes) -> tuple[str, Decimal | None]:
    try:
        result = get_aliyun_ocr_client().recognize_image(_prepare_image_for_ocr(image_bytes))
    except OcrServiceError as exc:
        raise BusinessError(exc.code, exc.message, exc.status_code) from exc
    confidence = Decimal(str(round(result.confidence, 4))) if result.confidence is not None else None
    return result.text, confidence


def extract_resume_document(path: Path, file_type: str) -> ResumeExtraction:
    if file_type == "docx":
        document = Document(path)
        return ResumeExtraction(
            text="\n".join(paragraph.text for paragraph in document.paragraphs),
            extraction_method="docx_text",
            ocr_confidence=None,
            page_count=1,
            review_warnings=[],
        )
    if file_type in {"png", "jpg", "jpeg"}:
        text, confidence = _ocr_image(path.read_bytes())
        warnings = ["图片简历已使用 OCR 识别，请在入库前核对关键字段。"]
        if confidence is not None and confidence < Decimal("0.70"):
            warnings.append("OCR 置信度较低，请重点核对姓名、联系方式和工作经历。")
        return ResumeExtraction(text, "aliyun_ocr", confidence, 1, warnings)
    if file_type != "pdf":
        raise BusinessError("UNSUPPORTED_FILE_TYPE", "只支持 PDF、DOCX、PNG、JPG 和 JPEG", 415)

    try:
        document = fitz.open(path)
    except (fitz.FileDataError, RuntimeError) as exc:
        raise BusinessError("INVALID_PDF", "PDF 文件损坏或无法读取", 422) from exc
    with document:
        page_count = document.page_count
        if page_count < 1:
            raise BusinessError("INVALID_PDF", "PDF 不包含可解析页面", 422)
        if page_count > settings.aliyun_ocr_max_page_count:
            raise BusinessError("PDF_PAGE_LIMIT_EXCEEDED", f"PDF 最多支持 {settings.aliyun_ocr_max_page_count} 页", 413)
        page_texts = [page.get_text("text").strip() for page in document]
        direct_text = "\n".join(item for item in page_texts if item)
        if len(re.sub(r"\s", "", direct_text)) >= 100:
            return ResumeExtraction(direct_text, "pdf_text", None, page_count, [])

        texts: list[str] = []
        confidences: list[Decimal] = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
            text, confidence = _ocr_image(pixmap.tobytes("png"))
            texts.append(text)
            if confidence is not None:
                confidences.append(confidence)
        average = sum(confidences) / len(confidences) if confidences else None
        warnings = ["扫描版 PDF 已逐页使用 OCR 识别，请在入库前核对关键字段。"]
        if average is not None and average < Decimal("0.70"):
            warnings.append("OCR 平均置信度较低，请重点核对姓名、联系方式和工作经历。")
        return ResumeExtraction("\n".join(texts), "aliyun_ocr", average, page_count, warnings)


def extract_resume_text(path: Path, file_type: str) -> str:
    """Compatibility wrapper for callers that only need plain text."""
    return extract_resume_document(path, file_type).text


def rule_parse_resume(text: str) -> ResumeParsedData:
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text)
    name_match = re.search(r"(?:姓名[:：\s]*)?([\u4e00-\u9fa5]{2,4})", text)
    skill_vocab = ["Python", "FastAPI", "LangChain", "LangGraph", "MySQL", "SQL", "Docker", "Java", "React", "Vue"]
    skills = [skill for skill in skill_vocab if skill.lower() in text.lower()]
    years = re.search(r"(\d{1,2})\s*年(?:工作)?经验", text)
    return ResumeParsedData(
        name=name_match.group(1) if name_match else "待确认",
        phone=phone_match.group(0) if phone_match else None,
        email=email_match.group(0).lower() if email_match else None,
        years_of_experience=Decimal(years.group(1)) if years else None,
        skills=skills,
        summary=text[:300].replace("\n", " "),
        confidence=Decimal("0.72"),
    )


def parse_resume_text(text: str) -> tuple[ResumeParsedData, str]:
    if not settings.llm_api_key:
        return rule_parse_resume(text), "rule"
    model = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=0,
    ).with_structured_output(ResumeParsedData, method="json_mode")
    schema = json.dumps(ResumeParsedData.model_json_schema(), ensure_ascii=False)
    prompt = (
        "你是招聘简历结构化工具。只提取简历明确事实，不推测敏感属性。"
        "必须只返回一个 JSON 对象，不要使用 Markdown。confidence 表示整体字段把握，0到1。"
        f"返回值必须符合以下 JSON Schema：{schema}\n简历文本：\n" + text[:20000]
    )
    try:
        parsed = model.invoke(prompt)
        return parsed, settings.llm_model
    except (ValidationError, Exception) as exc:
        raise BusinessError("AI_TEMPORARILY_UNAVAILABLE", f"简历解析暂不可用：{type(exc).__name__}", 503) from exc


def confirm_resume(db: Session, resume: Resume, data: ResumeConfirm, user: User, req_id: str) -> Candidate:
    if resume.parse_status not in {"review_required", "completed"}:
        raise BusinessError("INVALID_REQUEST", "当前简历状态不可确认", 409)
    parsed = data.corrected_data.model_dump(mode="json", exclude={"confidence"})
    if data.candidate_id:
        candidate = get_candidate(db, data.candidate_id)
        if not candidate:
            raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在", 404)
    else:
        candidate = Candidate(**parsed, source="resume", created_by=user.id)
        db.add(candidate)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise BusinessError("DUPLICATE_RESOURCE", "联系方式已存在，请关联已有候选人", 409) from exc
    resume.candidate_id = candidate.id
    resume.corrected_data = data.corrected_data.model_dump(mode="json")
    resume.parse_status = "completed"
    create_application_in_transaction(db, candidate=candidate, job_id=data.job_id, owner_id=data.owner_id or user.id, source="resume", applied_at=utcnow(), user=user, req_id=req_id)
    audit(db, action="resume.confirm", target_type="resume", target_id=resume.id, user=user, source="web", req_id=req_id, after={"candidate_id": candidate.id})
    db.commit()
    return candidate


def extract_recruitment_message(content: str) -> dict[str, Any] | None:
    status_rules = [
        ("已入职", "hired"),
        ("入职", "hired"),
        ("发offer", "offer"),
        ("offer", "offer"),
        ("淘汰", "rejected"),
        ("不通过", "rejected"),
        ("放弃", "withdrawn"),
        ("终面", "final_interview"),
        ("二面", "interview_2"),
        ("一面", "interview_1"),
        ("筛选", "screening"),
    ]
    target = next((stage for word, stage in status_rules if word.lower() in content.lower()), None)
    if not target:
        return None
    name_match = re.search(r"([\u4e00-\u9fa5]{2,4})(?:候选人|同学|的|已|一面|二面|终面|筛选)", content)
    if not name_match:
        name_match = re.search(r"^([\u4e00-\u9fa5]{2,4})", content.strip())
    return {
        "candidate_name": name_match.group(1) if name_match else None,
        "target_status": target,
        "reason": content[:500],
        "confidence": 0.92 if name_match else 0.6,
    }


def process_inbound_event(db: Session, event: InboundEvent, user: User, req_id: str) -> dict:
    event.processing_status = "processing"
    extracted = extract_recruitment_message(event.content or "")
    if not extracted:
        event.relevance = "irrelevant"
        event.processing_status = "ignored"
        event.processed_at = utcnow()
        db.commit()
        return {"event_id": event.id, "status": "ignored"}
    event.relevance = "relevant"
    event.extracted_data = extracted
    event.confidence = Decimal(str(extracted["confidence"]))
    name = extracted.get("candidate_name")
    if not name:
        event.processing_status = "failed"
        event.error_code = "CANDIDATE_AMBIGUOUS"
        event.error_message = "无法识别候选人姓名"
        db.commit()
        return {"event_id": event.id, "status": "failed", "error": event.error_code}
    rows = db.execute(
        select(CandidateJob, Candidate, Job)
        .join(Candidate, Candidate.id == CandidateJob.candidate_id)
        .join(Job, Job.id == CandidateJob.job_id)
        .where(Candidate.name == name, Candidate.deleted_at.is_(None), Job.status == "open")
    ).all()
    if len(rows) != 1:
        event.processing_status = "failed"
        event.error_code = "CANDIDATE_AMBIGUOUS"
        event.error_message = f"匹配到 {len(rows)} 条在招应聘关系"
        db.commit()
        return {"event_id": event.id, "status": "failed", "error": event.error_code}
    app, candidate, job = rows[0]
    proposal = StatusChangeProposal(
        candidate_job_id=app.id,
        target_status=extracted["target_status"],
        reason=extracted["reason"],
        confidence=Decimal(str(extracted["confidence"])),
        version=app.version,
        idempotency_key=hashlib.sha256(f"inbound:{event.id}:{app.id}:{extracted['target_status']}".encode()).hexdigest(),
    )
    result = propose_status_change(db, proposal, user, req_id, actor_type="agent", inbound_event_id=event.id)
    event = db.get(InboundEvent, event.id)
    event.processing_status = "pending_approval" if result["execution"] == "approval_required" else "completed"
    event.approval_request_id = result.get("approval", {}).get("id")
    event.processed_at = utcnow()
    db.commit()
    return {"event_id": event.id, "status": event.processing_status, "extracted": extracted, "result": result}


def dashboard(db: Session) -> dict:
    funnel_rows = db.execute(
        select(CandidateJob.status, func.count(CandidateJob.id)).group_by(CandidateJob.status)
    ).all()
    funnel_map = {status: count for status, count in funnel_rows}
    funnel = [{"stage": stage, "count": int(funnel_map.get(stage, 0))} for stage in ["new", "screening", "interview_1", "interview_2", "final_interview", "offer", "hired", "rejected", "withdrawn", "on_hold"]]
    source_rows = db.execute(select(CandidateJob.source, func.count(CandidateJob.id)).group_by(CandidateJob.source)).all()
    now = utcnow()
    upcoming = db.scalar(select(func.count(Interview.id)).where(Interview.status == "scheduled", Interview.scheduled_at.between(now, now + timedelta(days=7)))) or 0
    approvals = db.scalar(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")) or 0
    sync_failed = db.scalar(select(func.count(DocumentSyncJob.id)).where(DocumentSyncJob.status == "failed")) or 0
    open_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
    return {
        "funnel": funnel,
        "sources": [{"source": source, "count": int(count)} for source, count in source_rows],
        "summary": {"open_jobs": int(open_jobs), "upcoming_interviews": int(upcoming), "pending_approvals": int(approvals), "sync_failures": int(sync_failed)},
    }
