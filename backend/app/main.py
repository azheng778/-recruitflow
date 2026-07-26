from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text

from .api import router
from .config import settings
from .database import SessionLocal, engine
from .models import ApprovalRequest, AgentConversation, AgentMessage, InboundEvent, Interview, Job, User
from .security import authenticate_user, create_access_token, create_csrf_token, optional_user
from .services import BusinessError, dashboard, list_candidates
from .ui_labels import UI_LABELS, zh_label
from .workers import worker_loop


APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["zh"] = zh_label
templates.env.globals["ui_labels"] = UI_LABELS


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_database_boundary()
    settings.ensure_directories()
    stop_event = asyncio.Event()
    task = asyncio.create_task(worker_loop(stop_event)) if settings.background_worker_enabled else None
    yield
    stop_event.set()
    if task:
        await task


app = FastAPI(title="RecruitFlow", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    trace_allowed = settings.app_env == "test" and settings.agent_trace_enabled
    if not trace_allowed:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    from .agent.trace import bind_trace, span
    run_id = request.headers.get("X-Trace-Run-ID") or "test-run"
    trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    with bind_trace(
        run_id=run_id,
        trace_id=trace_id,
        scenario_id=request.headers.get("X-Trace-Scenario-ID"),
        turn_id=request.headers.get("X-Trace-Turn-ID"),
        request_id=request.state.request_id,
    ) as trace_context:
        with span("http.request.total", "http", {"method": request.method, "path": request.url.path}):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        categories = trace_context.category_ms
        response.headers["Server-Timing"] = ", ".join([
            f"total;dur={categories.get('http', 0):.3f}",
            f"agent;dur={categories.get('agent', 0):.3f}",
            f"llm;dur={categories.get('llm', 0):.3f}",
            f"db;dur={categories.get('db', 0):.3f}",
            f"checkpoint;dur={categories.get('checkpoint', 0):.3f}",
            f"tool;dur={categories.get('tool', 0):.3f}",
        ])
        return response


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": None,
            "error": {"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "details": {"errors": exc.errors()}},
            "request_id": request.state.request_id,
        },
    )


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    settings.validate_database_boundary()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": settings.db_name, "wecom": settings.wecom_enabled, "tencent_docs": settings.tencent_docs_enabled}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": type(exc).__name__})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    with SessionLocal() as db:
        user = authenticate_user(db, username, password)
        if not user:
            return templates.TemplateResponse(request=request, name="login.html", context={"error": "用户名或密码错误，或账号暂时锁定"}, status_code=401)
        response = RedirectResponse("/dashboard", status_code=303)
        secure = settings.app_env == "production"
        response.set_cookie("access_token", create_access_token(user), httponly=True, samesite="lax", secure=secure, max_age=settings.access_token_expire_minutes * 60)
        response.set_cookie("csrf_token", create_csrf_token(), httponly=False, samesite="lax", secure=secure, max_age=settings.access_token_expire_minutes * 60)
        return response


def require_page_user(request: Request, user: User | None):
    if not user:
        return RedirectResponse("/login", status_code=303)
    return None


@app.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    # Dependency injection is intentionally explicit for HTML redirects.
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    from .security import decode_token
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        current = db.get(User, payload.get("sub"))
        if not current:
            return RedirectResponse("/login", status_code=303)
        metrics = dashboard(db) if current.role in {"admin", "hr"} else {"summary": {}, "funnel": [], "sources": []}
        return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": current, "metrics": metrics, "active": "dashboard"})


@app.get("/candidates", response_class=HTMLResponse)
def candidates_page(request: Request):
    from .security import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user or user.role not in {"admin", "hr"}:
            return RedirectResponse("/dashboard", status_code=303)
        data = list_candidates(db, page_size=100)
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
        return templates.TemplateResponse(request=request, name="candidates.html", context={"user": user, "items": data["items"], "jobs": jobs, "active": "candidates"})


@app.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    from .security import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user or user.role not in {"admin", "hr"}:
            return RedirectResponse("/dashboard", status_code=303)
        items = db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(100).all()
        return templates.TemplateResponse(request=request, name="approvals.html", context={"user": user, "items": items, "active": "approvals"})


@app.get("/messages", response_class=HTMLResponse)
def messages_page(request: Request):
    from .security import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user or user.role not in {"admin", "hr"}:
            return RedirectResponse("/dashboard", status_code=303)
        events = db.query(InboundEvent).order_by(InboundEvent.created_at.desc()).limit(30).all()
        return templates.TemplateResponse(request=request, name="messages.html", context={"user": user, "events": events, "active": "messages"})


@app.get("/interviews", response_class=HTMLResponse)
def interviews_page(request: Request):
    from .security import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user:
            return RedirectResponse("/login", status_code=303)
        query = db.query(Interview)
        if user.role == "interviewer":
            query = query.filter(Interview.interviewer_id == user.id)
        items = query.order_by(Interview.scheduled_at).limit(100).all()
        return templates.TemplateResponse(request=request, name="interviews.html", context={"user": user, "items": items, "active": "interviews"})


@app.get("/agent", response_class=HTMLResponse)
def agent_page(request: Request):
    from .security import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/login", status_code=303)
    try:
        payload = decode_token(token)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user:
            return RedirectResponse("/login", status_code=303)
        latest_message_id = (
            db.query(func.max(AgentMessage.id))
            .filter(AgentMessage.conversation_id == AgentConversation.id)
            .correlate(AgentConversation)
            .scalar_subquery()
        )
        conversations = db.query(AgentConversation).filter(AgentConversation.user_id == user.id).order_by(AgentConversation.updated_at.desc(), latest_message_id.desc()).limit(20).all()
        return templates.TemplateResponse(request=request, name="agent.html", context={"user": user, "conversations": conversations, "active": "agent"})
