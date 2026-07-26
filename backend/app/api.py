from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent.graph import run_agent
from .config import settings
from .database import get_db
from .models import (
    AgentConversation,
    AgentMessage,
    AgentToolRun,
    AgentUserPreference,
    ApprovalRequest,
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
from .repositories import get_candidate, get_job
from .schemas import (
    AgentChatRequest,
    AgentConversationPatch,
    ApplicationCreate,
    ApprovalDecision,
    CandidateCreate,
    CandidatePatch,
    DemoInboundRequest,
    InterviewCreate,
    InterviewFeedback,
    JobCreate,
    JobPatch,
    LoginRequest,
    ResumeConfirm,
    StatusChangeProposal,
)
from .security import (
    authenticate_user,
    create_access_token,
    create_csrf_token,
    get_current_user,
    require_csrf,
    require_roles,
)
from .services import (
    BusinessError,
    approval_dict,
    approve_request,
    candidate_row,
    confirm_resume,
    create_application,
    create_candidate,
    create_delete_approval,
    create_interview,
    create_job,
    dashboard,
    extract_resume_document,
    job_dict,
    list_candidates,
    mask_email,
    mask_phone,
    parse_resume_text,
    patch_candidate,
    patch_job,
    process_inbound_event,
    propose_status_change,
    record_feedback,
    reject_request,
)


router = APIRouter(prefix="/api")


def ok(request: Request, data, status_code: int = 200):
    return {"success": True, "data": data, "error": None, "request_id": request.state.request_id}


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": mask_email(user.email),
        "phone": mask_phone(user.phone),
        "role": user.role,
        "department": user.department,
    }


def interview_dict(item: Interview) -> dict:
    return {
        "id": item.id,
        "candidate_job_id": item.candidate_job_id,
        "round": item.round,
        "interview_type": item.interview_type,
        "scheduled_at": item.scheduled_at,
        "duration_minutes": item.duration_minutes,
        "interviewer_id": item.interviewer_id,
        "status": item.status,
        "recommendation": item.recommendation,
        "ai_summary": item.ai_summary,
        "version": item.version,
    }


@router.post("/auth/login")
def login(request: Request, payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise BusinessError("INVALID_CREDENTIALS", "用户名或密码错误，或账号暂时锁定", 401)
    token = create_access_token(user)
    csrf = create_csrf_token()
    secure = settings.app_env == "production"
    response.set_cookie("access_token", token, httponly=True, samesite="lax", secure=secure, max_age=settings.access_token_expire_minutes * 60)
    response.set_cookie("csrf_token", csrf, httponly=False, samesite="lax", secure=secure, max_age=settings.access_token_expire_minutes * 60)
    return ok(request, {"user": user_dict(user), "csrf_token": csrf})


@router.post("/auth/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return ok(request, {"logged_out": True})


@router.get("/auth/me")
def me(request: Request, user: User = Depends(get_current_user)):
    return ok(request, user_dict(user))


@router.get("/jobs")
def jobs_list(
    request: Request,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    if user.role == "interviewer":
        stmt = stmt.join(CandidateJob).join(Interview).where(Interview.interviewer_id == user.id).distinct()
    items = [job_dict(item) for item in db.scalars(stmt.order_by(Job.created_at.desc())).all()]
    return ok(request, items)


@router.post("/jobs", dependencies=[Depends(require_csrf)])
def jobs_create(
    request: Request,
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    return ok(request, job_dict(create_job(db, payload, user, request.state.request_id)))


@router.get("/jobs/{job_id}")
def jobs_get(request: Request, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = get_job(db, job_id)
    if not job:
        raise BusinessError("RESOURCE_NOT_FOUND", "岗位不存在", 404)
    return ok(request, job_dict(job))


@router.patch("/jobs/{job_id}", dependencies=[Depends(require_csrf)])
def jobs_patch(
    request: Request,
    job_id: str,
    payload: JobPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    job = get_job(db, job_id)
    if not job:
        raise BusinessError("RESOURCE_NOT_FOUND", "岗位不存在", 404)
    return ok(request, job_dict(patch_job(db, job, payload, user, request.state.request_id)))


@router.post("/jobs/{job_id}/open", dependencies=[Depends(require_csrf)])
def jobs_open(request: Request, job_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    job = get_job(db, job_id)
    if not job:
        raise BusinessError("RESOURCE_NOT_FOUND", "岗位不存在", 404)
    if job.status == "closed":
        raise BusinessError("INVALID_STATUS_TRANSITION", "关闭岗位不能直接重新开放", 409)
    job.status = "open"
    job.opened_at = job.opened_at or utcnow()
    job.version += 1
    db.commit()
    return ok(request, job_dict(job))


@router.post("/jobs/{job_id}/close", dependencies=[Depends(require_csrf)])
def jobs_close(request: Request, job_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    job = get_job(db, job_id)
    if not job:
        raise BusinessError("RESOURCE_NOT_FOUND", "岗位不存在", 404)
    job.status = "closed"
    job.closed_at = utcnow()
    job.version += 1
    db.commit()
    return ok(request, job_dict(job))


@router.get("/candidates")
def candidates_list(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    owner_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    return ok(request, list_candidates(db, page=page, page_size=page_size, keyword=keyword, job_id=job_id, status=status, source=source, owner_id=owner_id))


@router.post("/candidates", dependencies=[Depends(require_csrf)])
def candidates_create(
    request: Request,
    payload: CandidateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    item = create_candidate(db, payload, user, request.state.request_id)
    return ok(request, {"id": item.id, "name": item.name, "version": item.version})


@router.get("/candidates/{candidate_id}")
def candidates_get(request: Request, candidate_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在", 404)
    apps = db.execute(
        select(CandidateJob, Job).join(Job, Job.id == CandidateJob.job_id).where(CandidateJob.candidate_id == candidate.id)
    ).all()
    if user.role == "interviewer":
        allowed_ids = set(db.scalars(select(Interview.candidate_job_id).where(Interview.interviewer_id == user.id)).all())
        apps = [row for row in apps if row[0].id in allowed_ids]
        if not apps:
            raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在或不可访问", 404)
    return ok(request, {
        "id": candidate.id,
        "name": candidate.name,
        "phone": mask_phone(candidate.phone),
        "email": mask_email(candidate.email),
        "city": candidate.city,
        "skills": candidate.skills,
        "summary": candidate.summary,
        "version": candidate.version,
        "applications": [candidate_row(candidate, app, job) for app, job in apps],
    })


@router.patch("/candidates/{candidate_id}", dependencies=[Depends(require_csrf)])
def candidates_patch(
    request: Request,
    candidate_id: str,
    payload: CandidatePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在", 404)
    item = patch_candidate(db, candidate, payload, user, request.state.request_id)
    return ok(request, {"id": item.id, "name": item.name, "version": item.version})


@router.post("/candidates/{candidate_id}/applications", dependencies=[Depends(require_csrf)])
def applications_create(
    request: Request,
    candidate_id: str,
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在", 404)
    app = create_application(db, candidate, payload, user, request.state.request_id)
    return ok(request, {"id": app.id, "status": app.status, "version": app.version})


@router.post("/candidates/{candidate_id}/delete-proposal", dependencies=[Depends(require_csrf)])
def candidate_delete_proposal(
    request: Request,
    candidate_id: str,
    version: int,
    reason: str,
    idempotency_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr")),
):
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        raise BusinessError("RESOURCE_NOT_FOUND", "候选人不存在", 404)
    approval = create_delete_approval(db, candidate, version, reason, idempotency_key, user, request.state.request_id)
    return ok(request, approval_dict(approval))


@router.post("/candidates/import-resume", dependencies=[Depends(require_csrf)])
async def import_resume(
    request: Request,
    file: UploadFile = File(...),
    job_id: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "hr", "interviewer")),
):
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"pdf", "docx", "png", "jpg", "jpeg"}:
        raise BusinessError("UNSUPPORTED_FILE_TYPE", "只支持 PDF、DOCX、PNG、JPG 和 JPEG", 415)
    content = await file.read(settings.max_resume_size_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_resume_size_mb * 1024 * 1024:
        raise BusinessError("FILE_TOO_LARGE", "简历文件超过大小限制", 413)
    if extension == "pdf" and not content.startswith(b"%PDF"):
        raise BusinessError("UNSUPPORTED_FILE_TYPE", "文件内容不是有效 PDF", 415)
    if extension == "docx" and not zipfile.is_zipfile(io.BytesIO(content)):
        raise BusinessError("UNSUPPORTED_FILE_TYPE", "文件内容不是有效 DOCX", 415)
    job = db.get(Job, job_id)
    if not job or job.status != "open":
        raise BusinessError("RESOURCE_NOT_FOUND", "请选择一个开放中的招聘岗位", 404)
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(Resume).where(Resume.file_sha256 == digest))
    if existing:
        can_view = user.role in {"admin", "hr"} or existing.uploaded_by == user.id
        return ok(request, {
            "resume_id": existing.id,
            "parse_status": existing.parse_status,
            "duplicate": True,
            "parsed_data": existing.parsed_data if can_view else None,
            "extraction_method": existing.extraction_method,
            "ocr_confidence": float(existing.ocr_confidence) if existing.ocr_confidence is not None else None,
            "page_count": existing.page_count,
            "review_warnings": ["该文件已由其他用户上传，不能查看解析预览。"] if not can_view else [],
        })
    settings.ensure_directories()
    resume_id = str(uuid.uuid4())
    target = settings.upload_dir / f"{resume_id}.{extension}"
    target.write_bytes(content)
    resume = Resume(id=resume_id, uploaded_by=user.id, original_file_name=Path(file.filename or "resume").name, storage_path=str(target.relative_to(settings.upload_dir.parent)), file_type=extension, file_sha256=digest, file_size=len(content), parse_status="extracting")
    db.add(resume)
    db.commit()
    try:
        extracted = extract_resume_document(target, extension)
        text = extracted.text
        resume.raw_text = text
        resume.extraction_method = extracted.extraction_method
        resume.ocr_confidence = extracted.ocr_confidence
        resume.page_count = extracted.page_count
        if len(re.sub(r"\s", "", text)) < 100:
            resume.parse_status = "unsupported"
            resume.parser_error_code = "INSUFFICIENT_EXTRACTED_TEXT"
            resume.parser_error_message = "文档中没有足够的可提取文本"
            db.commit()
            raise BusinessError("INSUFFICIENT_EXTRACTED_TEXT", "未识别到足够的简历文字，请上传更清晰的文件", 422)
        resume.parse_status = "parsing"
        db.commit()
        parsed, parser_model = parse_resume_text(text)
        resume.parsed_data = parsed.model_dump(mode="json")
        resume.parser_model = parser_model
        resume.parse_status = "review_required"
        db.commit()
        return ok(request, {
            "resume_id": resume.id,
            "job_id": job_id,
            "parse_status": resume.parse_status,
            "duplicate": False,
            "parsed_data": resume.parsed_data,
            "extraction_method": resume.extraction_method,
            "ocr_confidence": float(resume.ocr_confidence) if resume.ocr_confidence is not None else None,
            "page_count": resume.page_count,
            "review_warnings": extracted.review_warnings,
        })
    except BusinessError as exc:
        if resume.parse_status not in {"unsupported", "failed"}:
            resume.parse_status = "failed"
            resume.parser_error_code = exc.code
            resume.parser_error_message = exc.message[:500]
            db.commit()
        raise
    except Exception as exc:
        resume.parse_status = "failed"
        resume.parser_error_code = type(exc).__name__
        resume.parser_error_message = str(exc)[:500]
        db.commit()
        raise BusinessError("RESUME_PARSE_FAILED", "简历解析失败，可稍后重试", 422) from exc


@router.get("/resumes/{resume_id}")
def resume_get(request: Request, resume_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise BusinessError("RESOURCE_NOT_FOUND", "简历不存在", 404)
    if user.role not in {"admin", "hr"} and resume.uploaded_by != user.id:
        raise BusinessError("PERMISSION_DENIED", "只能查看自己上传的简历解析预览", 403)
    return ok(request, {
        "id": resume.id,
        "file_name": resume.original_file_name,
        "parse_status": resume.parse_status,
        "parsed_data": resume.parsed_data,
        "corrected_data": resume.corrected_data,
        "error_code": resume.parser_error_code,
        "extraction_method": resume.extraction_method,
        "ocr_confidence": float(resume.ocr_confidence) if resume.ocr_confidence is not None else None,
        "page_count": resume.page_count,
    })


@router.post("/resumes/{resume_id}/confirm", dependencies=[Depends(require_csrf)])
def resume_confirm(request: Request, resume_id: str, payload: ResumeConfirm, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise BusinessError("RESOURCE_NOT_FOUND", "简历不存在", 404)
    candidate = confirm_resume(db, resume, payload, user, request.state.request_id)
    return ok(request, {"candidate_id": candidate.id, "name": candidate.name})


@router.get("/interviews")
def interviews_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Interview)
    if user.role == "interviewer":
        stmt = stmt.where(Interview.interviewer_id == user.id)
    return ok(request, [interview_dict(x) for x in db.scalars(stmt.order_by(Interview.scheduled_at)).all()])


@router.post("/interviews", dependencies=[Depends(require_csrf)])
def interviews_create(request: Request, payload: InterviewCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    return ok(request, interview_dict(create_interview(db, payload, user, request.state.request_id)))


@router.post("/interviews/{interview_id}/feedback", dependencies=[Depends(require_csrf)])
def interviews_feedback(request: Request, interview_id: str, payload: InterviewFeedback, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    interview = db.get(Interview, interview_id)
    if not interview:
        raise BusinessError("RESOURCE_NOT_FOUND", "面试不存在", 404)
    return ok(request, interview_dict(record_feedback(db, interview, payload, user, request.state.request_id)))


@router.post("/applications/status-proposals", dependencies=[Depends(require_csrf)])
def status_proposal(request: Request, payload: StatusChangeProposal, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    return ok(request, propose_status_change(db, payload, user, request.state.request_id))


@router.get("/approvals")
def approvals_list(request: Request, status: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    stmt = select(ApprovalRequest)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    return ok(request, [approval_dict(x) for x in db.scalars(stmt.order_by(ApprovalRequest.created_at.desc())).all()])


@router.post("/approvals/{approval_id}/approve", dependencies=[Depends(require_csrf)])
def approvals_approve(request: Request, approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    item = db.get(ApprovalRequest, approval_id)
    if not item:
        raise BusinessError("RESOURCE_NOT_FOUND", "审批不存在", 404)
    result = approve_request(db, item, payload.version, user, request.state.request_id, payload.comment)
    from .agent.runtime import mark_approval_resumed
    result["graph_resumed"] = mark_approval_resumed(db, approval_id, "approved")
    return ok(request, result)


@router.post("/approvals/{approval_id}/reject", dependencies=[Depends(require_csrf)])
def approvals_reject(request: Request, approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    item = db.get(ApprovalRequest, approval_id)
    if not item:
        raise BusinessError("RESOURCE_NOT_FOUND", "审批不存在", 404)
    result = reject_request(db, item, payload.version, user, request.state.request_id, payload.comment)
    from .agent.runtime import mark_approval_resumed
    result["graph_resumed"] = mark_approval_resumed(db, approval_id, "rejected")
    return ok(request, result)


@router.post("/agent/chat", dependencies=[Depends(require_csrf)])
def agent_chat(request: Request, payload: AgentChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ok(
        request,
        run_agent(
            db, user, payload.message, payload.conversation_id, payload.idempotency_key,
            action_response=payload.action_response.model_dump() if payload.action_response else None,
            client_timezone=payload.client_timezone,
        ),
    )


@router.get("/agent/conversations")
def agent_conversations(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    latest_message_id = (
        select(func.max(AgentMessage.id))
        .where(AgentMessage.conversation_id == AgentConversation.id)
        .correlate(AgentConversation)
        .scalar_subquery()
    )
    stmt = (
        select(AgentConversation)
        .where(AgentConversation.user_id == user.id, AgentConversation.status != "archived")
        .order_by(AgentConversation.updated_at.desc(), latest_message_id.desc())
    )
    return ok(request, [{"id": x.id, "title": x.title, "status": x.status, "updated_at": x.updated_at} for x in db.scalars(stmt).all()])


@router.patch("/agent/conversations/{conversation_id}", dependencies=[Depends(require_csrf)])
def agent_conversation_patch(
    request: Request,
    conversation_id: str,
    payload: AgentConversationPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or (conversation.user_id != user.id and user.role != "admin"):
        raise BusinessError("RESOURCE_NOT_FOUND", "会话不存在或不可访问", 404)
    conversation.title = payload.title.strip()
    conversation.updated_at = utcnow()
    db.commit()
    return ok(
        request,
        {"id": conversation.id, "title": conversation.title, "updated_at": conversation.updated_at},
    )


@router.get("/agent/conversations/{conversation_id}/messages")
def agent_messages(request: Request, conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or (conversation.user_id != user.id and user.role != "admin"):
        raise BusinessError("RESOURCE_NOT_FOUND", "会话不存在或不可访问", 404)
    stmt = select(AgentMessage).where(AgentMessage.conversation_id == conversation_id).order_by(AgentMessage.created_at)
    return ok(request, [
        {
            "id": x.id,
            "role": x.role,
            "content": x.content,
            "tool_name": x.tool_name,
            "status": x.status,
            "created_at": x.created_at,
            "answer_card": (x.tool_output or {}).get("answer_card") if x.role == "assistant" else None,
        }
        for x in db.scalars(stmt).all()
    ])


@router.post("/agent/conversations/{conversation_id}/archive", dependencies=[Depends(require_csrf)])
def agent_conversation_archive(
    request: Request,
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or (conversation.user_id != user.id and user.role != "admin"):
        raise BusinessError("RESOURCE_NOT_FOUND", "会话不存在或不可访问", 404)
    conversation.status = "archived"
    conversation.updated_at = utcnow()
    db.commit()
    return ok(request, {"id": conversation.id, "status": conversation.status})


@router.get("/agent/conversations/{conversation_id}/memory")
def agent_conversation_memory(
    request: Request,
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or (conversation.user_id != user.id and user.role != "admin"):
        raise BusinessError("RESOURCE_NOT_FOUND", "会话不存在或不可访问", 404)
    entities = dict(conversation.context_snapshot or {}).get("active_entities", {})
    public_entities = {
        name: {key: value for key, value in data.items() if key in {"id", "name"}}
        for name, data in entities.items() if isinstance(data, dict)
    }
    return ok(request, {
        "conversation_id": conversation.id,
        "summary": conversation.summary,
        "active_entities": public_entities,
        "memory_version": conversation.memory_version,
        "summary_through_message_id": conversation.summary_through_message_id,
    })


@router.delete("/agent/conversations/{conversation_id}/memory", dependencies=[Depends(require_csrf)])
def agent_conversation_memory_delete(
    request: Request,
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or (conversation.user_id != user.id and user.role != "admin"):
        raise BusinessError("RESOURCE_NOT_FOUND", "会话不存在或不可访问", 404)
    from .agent.memory import clear_conversation_memory
    clear_conversation_memory(conversation)
    db.commit()
    return ok(request, {"conversation_id": conversation.id, "memory_cleared": True})


@router.get("/agent/preferences")
def agent_preferences(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = db.scalars(
        select(AgentUserPreference).where(
            AgentUserPreference.user_id == user.id,
            AgentUserPreference.status == "active",
        ).order_by(AgentUserPreference.preference_key)
    ).all()
    return ok(request, [
        {"key": item.preference_key, "value": item.value_json.get("value"), "updated_at": item.updated_at}
        for item in items
    ])


@router.delete("/agent/preferences/{preference_key}", dependencies=[Depends(require_csrf)])
def agent_preference_delete(
    request: Request,
    preference_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.scalar(select(AgentUserPreference).where(
        AgentUserPreference.user_id == user.id,
        AgentUserPreference.preference_key == preference_key,
        AgentUserPreference.status == "active",
    ))
    if not item:
        raise BusinessError("RESOURCE_NOT_FOUND", "偏好不存在", 404)
    item.status = "deleted"
    item.updated_at = utcnow()
    db.commit()
    return ok(request, {"key": preference_key, "deleted": True})


@router.get("/dashboard")
def dashboard_get(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    return ok(request, dashboard(db))


@router.post("/inbound/demo", dependencies=[Depends(require_csrf)])
def inbound_demo(request: Request, payload: DemoInboundRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    external_id = payload.external_event_id or str(uuid.uuid4())
    existing = db.scalar(select(InboundEvent).where(InboundEvent.source == "demo", InboundEvent.external_event_id == external_id))
    if existing:
        return ok(request, {"event_id": existing.id, "status": existing.processing_status, "duplicate": True, "extracted": existing.extracted_data})
    event = InboundEvent(source="demo", external_event_id=external_id, sender_external_id=payload.sender_external_id, room_external_id=payload.room_external_id, message_type="text", content=payload.content, occurred_at=(payload.occurred_at or utcnow()).replace(tzinfo=None), raw_payload={"demo": True})
    db.add(event)
    db.commit()
    db.refresh(event)
    result = process_inbound_event(db, event, user, request.state.request_id)
    result["duplicate"] = False
    return ok(request, result)


@router.get("/inbound/events")
def inbound_events(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    items = db.scalars(select(InboundEvent).order_by(InboundEvent.created_at.desc()).limit(100)).all()
    return ok(request, [{"id": x.id, "source": x.source, "content": x.content, "status": x.processing_status, "extracted_data": x.extracted_data, "error_code": x.error_code, "created_at": x.created_at} for x in items])


@router.get("/inbound/wecom")
def wecom_verify(request: Request):
    if not settings.wecom_enabled:
        raise BusinessError("INTEGRATION_DISABLED", "企业微信适配器未启用", 503)
    raise BusinessError("NOT_IMPLEMENTED_FOR_DEMO", "请配置企业微信签名参数", 501)


@router.post("/inbound/wecom")
def wecom_callback(request: Request):
    if not settings.wecom_enabled:
        raise BusinessError("INTEGRATION_DISABLED", "企业微信适配器未启用", 503)
    raise BusinessError("NOT_IMPLEMENTED_FOR_DEMO", "真实回调需要企业管理员凭证", 501)


@router.get("/sync/jobs")
def sync_jobs(request: Request, status: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    stmt = select(DocumentSyncJob)
    if status:
        stmt = stmt.where(DocumentSyncJob.status == status)
    items = db.scalars(stmt.order_by(DocumentSyncJob.created_at.desc()).limit(100)).all()
    return ok(request, [{"id": x.id, "sink_type": x.sink_type, "entity_type": x.entity_type, "entity_id": x.entity_id, "status": x.status, "retry_count": x.retry_count, "error_code": x.error_code, "created_at": x.created_at} for x in items])


@router.post("/sync/jobs/{job_id}/retry", dependencies=[Depends(require_csrf)])
def sync_retry(request: Request, job_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr"))):
    item = db.get(DocumentSyncJob, job_id)
    if not item:
        raise BusinessError("RESOURCE_NOT_FOUND", "同步任务不存在", 404)
    if item.status != "failed" or item.retry_count >= 3:
        raise BusinessError("INVALID_REQUEST", "该任务当前不能重试", 409)
    item.status = "pending"
    item.next_retry_at = utcnow()
    db.commit()
    return ok(request, {"id": item.id, "status": item.status})


@router.get("/sync/health")
def sync_health(request: Request, user: User = Depends(require_roles("admin"))):
    return ok(request, {"local_excel": {"enabled": True, "healthy": True}, "tencent_docs": {"enabled": settings.tencent_docs_enabled, "healthy": False if not settings.tencent_docs_enabled else None}})


@router.get("/notifications")
def notifications(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Notification)
    if user.role == "interviewer":
        stmt = stmt.where(Notification.recipient == user.id)
    items = db.scalars(stmt.order_by(Notification.scheduled_at.desc()).limit(100)).all()
    return ok(request, [{"id": x.id, "content": x.content, "scheduled_at": x.scheduled_at, "status": x.status, "channel": x.channel} for x in items])
