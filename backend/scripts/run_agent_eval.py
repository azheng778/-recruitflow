from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import threading
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Establish the database boundary before importing any app module that creates an
# SQLAlchemy engine. This makes the Python entry point as safe as the PowerShell
# wrapper and prevents DATABASE_URL from silently overriding TEST_DB_NAME.
from dotenv import dotenv_values

PROJECT_ROOT = BACKEND_DIR.parent
FILE_ENV = dotenv_values(PROJECT_ROOT / ".env")
EVAL_TEST_DB = os.getenv("TEST_DB_NAME") or FILE_ENV.get("TEST_DB_NAME") or "hr_recruitment_test"
os.environ["APP_ENV"] = "test"
os.environ["TEST_DB_NAME"] = EVAL_TEST_DB
os.environ["DB_NAME"] = EVAL_TEST_DB
os.environ["DATABASE_URL"] = ""

import httpx
import pymysql
from jinja2 import Template

from app.agent.evaluation import AgentScenario
from app.config import PROJECT_DIR, settings


_ARTIFACT_WRITE_LOCK = threading.Lock()


def json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def jsonl_append(path: Path, value: Any) -> None:
    with _ARTIFACT_WRITE_LOCK:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


def redact_artifact_text(value: str) -> str:
    value = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
    return re.sub(
        r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        r"\1***\2",
        value,
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if "passed" in row:
            row["passed"] = str(row["passed"]).lower() == "true"
    return rows


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_trace_events(artifact: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    merged_path = artifact / "traces.jsonl"
    with merged_path.open("w", encoding="utf-8") as merged:
        for path in (artifact / "traces.server.jsonl", artifact / "traces.client.jsonl"):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    merged.write(line)
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        jsonl_append(artifact / "errors.jsonl", {
                            "error_code": "INVALID_TRACE_JSON", "source": path.name,
                            "line_sha256": hashlib.sha256(line.encode()).hexdigest(),
                        })
    return events


def enrich_turn_rows(turn_rows: list[dict[str, Any]], traces: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in traces:
        scenario_id, turn_id = event.get("scenario_id"), event.get("turn_id")
        if scenario_id and turn_id:
            grouped[(scenario_id, turn_id)].append(event)
    root_names = {
        "llm": {"llm.intent.invoke"},
        "db": {"db.sql.execute"},
        "checkpoint": {"checkpoint.get", "checkpoint.put", "checkpoint.put_writes"},
        "tool": set(),
    }
    for row in turn_rows:
        events = grouped.get((str(row["scenario_id"]), str(row["turn_id"])), [])
        event_names = {str(event.get("name") or "") for event in events}
        required = {"client.turn.total", "http.request.total", "agent.request.total"}
        if "agent.idempotent_replay" not in event_names:
            required.add("langgraph.invoke.total")
        missing = sorted(required - event_names)
        llm_events = [event for event in events if event.get("name") in {"llm.intent.invoke", "llm.response.invoke"}]
        token_attrs = [(event.get("attributes") or {}) for event in llm_events]
        row["input_tokens"] = sum(int(item.get("input_tokens") or 0) for item in token_attrs)
        row["output_tokens"] = sum(int(item.get("output_tokens") or 0) for item in token_attrs)
        row["total_tokens"] = sum(int(item.get("total_tokens") or 0) for item in token_attrs)
        row["llm_retries"] = max([int(item.get("retry_count") or 0) for item in token_attrs] or [0])
        row["sql_query_count"] = sum(1 for event in events if event.get("name") == "db.sql.execute")
        row["trace_span_count"] = len(events)
        row["checkpoint_ms_precise"] = round(sum(
            float(event.get("duration_ms") or 0) for event in events
            if event.get("name") in root_names["checkpoint"]
        ), 3)
        row["db_sql_ms"] = round(sum(
            float(event.get("duration_ms") or 0) for event in events
            if event.get("name") in root_names["db"]
        ), 3)
        tool_events = [event for event in events if str(event.get("name", "")).startswith("tool.invoke.")]
        row["tool_invoke_ms"] = round(sum(float(event.get("duration_ms") or 0) for event in tool_events), 3)
        node_events = [event for event in events if event.get("category") == "agent_node"]
        slowest = max(node_events or events, key=lambda event: float(event.get("duration_ms") or 0), default=None)
        row["slowest_span"] = slowest.get("name") if slowest else ""
        row["slowest_span_ms"] = round(float(slowest.get("duration_ms") or 0), 3) if slowest else 0
        agent_total = float(row.get("agent_ms") or 0)
        node_total = sum(float(event.get("duration_ms") or 0) for event in node_events)
        row["unclassified_agent_ms"] = round(max(0.0, agent_total - node_total), 3)
        row["unclassified_over_5pct"] = bool(agent_total and (agent_total - node_total) / agent_total > 0.05)
        if llm_events:
            for event in llm_events:
                attributes = event.get("attributes") or {}
                if not attributes.get("model"):
                    missing.append(f"{event.get('name')}:model")
                if "total_tokens" not in attributes:
                    missing.append(f"{event.get('name')}:total_tokens")
                if "retry_count" not in attributes:
                    missing.append(f"{event.get('name')}:retry_count")
        row["trace_missing"] = "|".join(sorted(set(missing)))
        if missing:
            row["passed"] = False
            trace_error = f"trace_missing={','.join(sorted(set(missing)))}"
            row["errors"] = "; ".join(item for item in [str(row.get("errors") or ""), trace_error] if item)


def scan_artifact_leaks(artifact: Path) -> list[dict[str, str]]:
    patterns = {
        "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    }
    findings: list[dict[str, str]] = []
    candidates = list(artifact.glob("*.jsonl")) + list(artifact.glob("*.log")) + list(artifact.glob("*.csv"))
    for path in candidates:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        scan_content = content
        if path.name.startswith("traces") and path.suffix == ".jsonl":
            # Trace IDs, timestamps and numeric duration fields can coincidentally
            # look like phone numbers. Only user-derived attributes/error text are
            # relevant to the sensitive-data scan.
            semantic_values = []
            for line in content.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                semantic_values.append(json.dumps({
                    "attributes": event.get("attributes") or {},
                    "error_code": event.get("error_code"),
                }, ensure_ascii=False))
            scan_content = "\n".join(semantic_values)
            scan_content = re.sub(
                r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
                "[uuid]",
                scan_content,
            )
        for kind, pattern in patterns.items():
            if pattern.search(scan_content):
                findings.append({"file": path.name, "type": kind})
        if settings.llm_api_key and settings.llm_api_key in content:
            findings.append({"file": path.name, "type": "llm_api_key"})
        if settings.db_password and settings.db_password in content:
            findings.append({"file": path.name, "type": "db_password"})
    json_write(artifact / "security-scan.json", {"passed": not findings, "finding_count": len(findings), "findings": findings})
    return findings


def reset_test_database(env: dict[str, str]) -> None:
    name = env.get("DB_NAME", "")
    expected = env.get("TEST_DB_NAME", "")
    if env.get("APP_ENV") != "test" or name != expected:
        raise RuntimeError("Refusing reset: APP_ENV=test and DB_NAME=TEST_DB_NAME are required")
    if name != "hr_recruitment_test" or not name.endswith("_test") or name in {"hr_recruitment", "langchain_db"}:
        raise RuntimeError(f"Refusing unsafe database target: {name}")
    connection = pymysql.connect(
        host=env.get("DB_HOST", settings.db_host), port=int(env.get("DB_PORT", settings.db_port)),
        user=env.get("DB_USERNAME", settings.db_username), password=env.get("DB_PASSWORD", settings.db_password),
        charset="utf8mb4", autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
            cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    finally:
        connection.close()
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(PROJECT_DIR / "backend" / "alembic.ini"), "upgrade", "head"], cwd=PROJECT_DIR, env=env, check=True)
    subprocess.run([sys.executable, str(PROJECT_DIR / "backend" / "scripts" / "seed.py")], cwd=PROJECT_DIR, env=env, check=True)


def load_scenarios(directory: Path, scenario_id: str | None, tag: str | None) -> list[AgentScenario]:
    items = [AgentScenario.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*/*.json"))]
    if scenario_id:
        requested_ids = {value.strip() for value in scenario_id.split(",") if value.strip()}
        items = [item for item in items if item.scenario_id in requested_ids]
    if tag:
        items = [item for item in items if tag in item.tags]
    if not items:
        raise RuntimeError("No scenarios matched the selection")
    return items


def create_fixture(scenario: AgentScenario) -> dict[str, str]:
    from app.database import SessionLocal
    from app.models import Candidate, CandidateJob, Interview, Job, User, utcnow
    from app.security import hash_password

    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"recruitflow-eval:{scenario.scenario_id}")
    identifier = lambda value: str(uuid.uuid5(namespace, value))
    candidate_id, job_id, app_id, interview_id = (identifier("candidate"), identifier("job"), identifier("application"), identifier("interview"))
    candidate_b_id, app_b_id = identifier("candidate_b"), identifier("application_b")
    hr_id, interviewer_id = identifier("hr"), identifier("interviewer")
    fixture = scenario.fixture
    with SessionLocal() as db:
        base_hr = db.query(User).filter(User.username == "hr_demo").one()
        base_interviewer = db.query(User).filter(User.username == "interviewer_demo").one()
        for item in (
            User(id=hr_id, username=f"hr_{scenario.scenario_id}", display_name=f"评测HR {scenario.scenario_id}", password_hash=hash_password(os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"), role="hr", department="评测人力资源部"),
            User(id=interviewer_id, username=f"iv_{scenario.scenario_id}", display_name=f"评测面试官 {scenario.scenario_id}", password_hash=hash_password(os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"), role="interviewer", department="评测技术中心"),
        ):
            if not db.get(User, item.id): db.add(item)
        # Some legacy ORM columns do not declare the database FK metadata, so an
        # explicit flush establishes parent rows before dependent fixture rows.
        db.flush()
        if not db.get(Job, job_id):
            db.add(Job(id=job_id, job_code=f"EVAL-{scenario.scenario_id}", job_name=fixture["job_name"], department="评测部门", description="虚构评测岗位", requirements="Python FastAPI LangGraph", location="上海", headcount=2, owner_id=hr_id, status="open", opened_at=utcnow()))
        if "candidate_create_resume" not in scenario.tags:
            suffix = int(hashlib.sha256(scenario.scenario_id.encode()).hexdigest()[:7], 16) % 10_000_000
            if not db.get(Candidate, candidate_id):
                db.add(Candidate(id=candidate_id, name=fixture["candidate_name"], phone=f"139{suffix:08d}", email=f"{scenario.scenario_id}@example.invalid", city="上海", source="eval", skills=["Python","FastAPI"], education=[], work_experience=[], projects=[], created_by=hr_id))
            if "ambiguity_security" in scenario.tags and not db.get(Candidate, candidate_b_id):
                db.add(Candidate(id=candidate_b_id, name=fixture["candidate_name"], phone=f"137{suffix:08d}", email=f"{scenario.scenario_id}.duplicate@example.invalid", city="杭州", source="eval", skills=["Python"], education=[], work_experience=[], projects=[], created_by=hr_id))
            db.flush()
            if not db.get(CandidateJob, app_id):
                db.add(CandidateJob(id=app_id, candidate_id=candidate_id, job_id=job_id, owner_id=hr_id, source="eval", status="new", applied_at=utcnow(), stage_entered_at=utcnow()))
            if "ambiguity_security" in scenario.tags and not db.get(CandidateJob, app_b_id):
                db.add(CandidateJob(id=app_b_id, candidate_id=candidate_b_id, job_id=job_id, owner_id=hr_id, source="eval", status="new", applied_at=utcnow(), stage_entered_at=utcnow()))
            db.flush()
            if scenario.role == "interviewer" or "interview_feedback" in scenario.tags:
                if not db.get(Interview, interview_id):
                    db.add(Interview(id=interview_id, candidate_job_id=app_id, round="first", interview_type="online", scheduled_at=utcnow()+timedelta(days=1), duration_minutes=60, interviewer_id=interviewer_id, additional_interviewers=[], status="scheduled", recommendation="pending", created_by=hr_id))
        db.commit()
    return {"candidate_id":candidate_id,"candidate_b_id":candidate_b_id,"job_id":job_id,"candidate_job_id":app_id,"interview_id":interview_id,"hr_id":hr_id,"interviewer_id":interviewer_id,"hr_username":f"hr_{scenario.scenario_id}","interviewer_username":f"iv_{scenario.scenario_id}"}


def login(base_url: str, username: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=120)
    response = client.post("/api/auth/login", json={"username":username,"password":os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"})
    response.raise_for_status()
    csrf = client.cookies.get("csrf_token")
    client.headers.update({"X-CSRF-Token":csrf or ""})
    return client


def parse_server_timing(value: str) -> dict[str, float]:
    result = {}
    for entry in value.split(","):
        parts = entry.strip().split(";")
        if len(parts) == 2 and parts[1].startswith("dur="):
            try: result[parts[0]] = float(parts[1][4:])
            except ValueError: pass
    return result


def assert_turn(expect, data: dict[str, Any], response_text: str) -> list[str]:
    errors = []
    intent = (data.get("intent") or {}).get("name")
    confidence = (data.get("intent") or {}).get("confidence") or 0
    tools = [item.get("name") for item in data.get("tool_calls", [])]
    if intent != expect.intent: errors.append(f"intent expected={expect.intent} actual={intent}")
    if confidence < expect.min_confidence: errors.append(f"confidence expected>={expect.min_confidence} actual={confidence}")
    if data.get("status") != expect.status: errors.append(f"status expected={expect.status} actual={data.get('status')}")
    if tools != expect.tools: errors.append(f"tools expected={expect.tools} actual={tools}")
    if len(tools) > expect.max_tool_calls: errors.append("tool call limit exceeded")
    for word in expect.response_contains:
        if word not in response_text: errors.append(f"response missing={word}")
    if expect.approval_required is True and not data.get("approval"): errors.append("approval missing")
    return errors


def final_assertions(scenario: AgentScenario, aliases: dict[str, str]) -> list[str]:
    from app.database import SessionLocal
    from app.models import AgentConversation, AgentToolRun, AgentUserPreference, ApprovalRequest, CandidateJob, DocumentSyncJob, Interview, Notification
    errors = []
    with SessionLocal() as db:
        for assertion in scenario.final_assertions:
            if assertion.type == "candidate_job_status":
                actual = getattr(db.get(CandidateJob, aliases["candidate_job_id"]), "status", None)
                if actual != assertion.expected: errors.append(f"final candidate status expected={assertion.expected} actual={actual}")
            elif assertion.type == "approval_count":
                actual = db.query(ApprovalRequest).filter(ApprovalRequest.candidate_job_id == aliases["candidate_job_id"]).count()
                if actual < int(assertion.expected): errors.append(f"approval_count expected>={assertion.expected} actual={actual}")
            elif assertion.type == "interview_count":
                actual = db.query(Interview).filter(Interview.candidate_job_id == aliases["candidate_job_id"]).count()
                if actual < int(assertion.expected): errors.append(f"interview_count expected>={assertion.expected} actual={actual}")
            elif assertion.type == "notification_count":
                actual = db.query(Notification).filter(Notification.candidate_job_id == aliases["candidate_job_id"]).count()
                if actual < int(assertion.expected): errors.append(f"notification_count expected>={assertion.expected} actual={actual}")
            elif assertion.type == "document_sync_count":
                actual = db.query(DocumentSyncJob).filter(DocumentSyncJob.entity_id == aliases["candidate_job_id"]).count()
                if actual != int(assertion.expected): errors.append(f"document_sync_count expected={assertion.expected} actual={actual}")
            elif assertion.type == "preference":
                actual = db.query(AgentUserPreference).filter(AgentUserPreference.user_id == aliases["hr_id"], AgentUserPreference.status == "active").count()
                if actual < 1: errors.append("preference was not persisted")
            elif assertion.type == "no_duplicate_write":
                actual = (
                    db.query(AgentToolRun)
                    .join(AgentConversation, AgentConversation.id == AgentToolRun.conversation_id)
                    .filter(
                        AgentConversation.user_id == aliases["interviewer_id"],
                        AgentToolRun.tool_name == "record_interview_feedback",
                        AgentToolRun.status == "completed",
                    )
                    .count()
                )
                if actual != 1: errors.append(f"idempotent feedback write expected=1 actual={actual}")
    return errors


def client_trace(path: Path, run_id: str, scenario_id: str, turn_id: str, duration_ms: float, status: str) -> None:
    jsonl_append(path, {"timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"run_id":run_id,"trace_id":f"{scenario_id}:{turn_id}","span_id":str(uuid.uuid4()),"parent_span_id":None,"scenario_id":scenario_id,"turn_id":turn_id,"request_id":None,"conversation_id":None,"user_role":None,"name":"client.turn.total","category":"client","duration_ms":round(duration_ms,6),"status":status,"error_code":None if status=="ok" else "ASSERTION_FAILED","attributes":{}})


def generate_report(artifact: Path, turn_rows: list[dict], scenario_rows: list[dict], traces: list[dict]) -> None:
    from app.agent.graph import TOOL_WHITELIST

    durations = [float(row["duration_ms"]) for row in turn_rows]
    categories = defaultdict(float)
    for trace in traces:
        categories[trace.get("category","unknown")] += float(trace.get("duration_ms",0))
    tokens = sum(int(row.get("total_tokens") or 0) for row in turn_rows)
    request_events = [event for event in traces if event.get("name") == "http.request.total" and event.get("scenario_id")]
    request_starts: list[datetime] = []
    request_ends: list[datetime] = []
    for event in request_events:
        try:
            ended = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
            request_ends.append(ended)
            request_starts.append(ended - timedelta(milliseconds=float(event.get("duration_ms") or 0)))
        except (KeyError, TypeError, ValueError):
            pass
    wall_time_ms = (max(request_ends) - min(request_starts)).total_seconds() * 1000 if request_starts and request_ends else sum(durations)
    environment = json.loads((artifact / "environment.json").read_text(encoding="utf-8")) if (artifact / "environment.json").exists() else {}
    passed = sum(1 for row in turn_rows if row["passed"])
    intent_correct = sum(1 for row in turn_rows if row.get("expected_intent") == row.get("actual_intent"))
    tool_correct = sum(1 for row in turn_rows if row.get("expected_tools") == row.get("actual_tools"))
    expected_tools = {name for row in turn_rows for name in str(row.get("expected_tools") or "").split("|") if name}
    actual_tools = {name for row in turn_rows for name in str(row.get("actual_tools") or "").split("|") if name}
    security_scan = json.loads((artifact / "security-scan.json").read_text(encoding="utf-8")) if (artifact / "security-scan.json").exists() else {"finding_count": 0}
    checkpoint_lock_events = [event for event in traces if event.get("name") == "checkpoint.lock_wait"]
    permanent_provider_errors = [
        event for event in traces
        if event.get("name") == "llm.intent.invoke" and event.get("status") == "error"
        and event.get("error_code") in {"AuthenticationError", "BadRequestError", "NotFoundError", "PermissionDeniedError"}
    ]
    circuit_fallbacks = [
        event for event in traces
        if event.get("name") == "llm.intent.fallback"
        and str((event.get("attributes") or {}).get("reason") or "").startswith("circuit:")
    ]
    provider_failure_turns = {
        (event.get("scenario_id"), event.get("turn_id"))
        for event in permanent_provider_errors + circuit_fallbacks
        if event.get("scenario_id") and event.get("turn_id")
    }
    dialogues: list[dict[str, Any]] = []
    dialogue_path = artifact / "dialogues.jsonl"
    if dialogue_path.exists():
        for line in dialogue_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                dialogues.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    answers = [str(item.get("answer") or "").strip() for item in dialogues]
    answer_counts = Counter(answers)
    modes = Counter(str(item.get("generation_mode") or "unknown") for item in dialogues)
    generic_pattern = re.compile(r"^(?:操作已完成|已返回结果|已完成|请求已处理)[。！!\s]*$")
    generic_answer_count = sum(1 for answer in answers if generic_pattern.fullmatch(answer))
    candidate_intents = {
        "candidate_search", "candidate_detail", "candidate_create", "interview_schedule",
        "interview_feedback", "status_change", "approval_request", "document_sync",
    }
    candidate_success = [
        item for item in dialogues
        if item.get("intent") in candidate_intents
        and item.get("status") in {"completed", "approval_required"}
    ]
    candidate_fact_complete = sum(
        1 for item in candidate_success
        if any(label in json.dumps(item.get("answer_card") or {}, ensure_ascii=False) for label in ["候选人", "姓名"])
        and "岗位" in json.dumps(item.get("answer_card") or {}, ensure_ascii=False)
    )
    summary = {
        "scenarios": len(scenario_rows), "turns": len(turn_rows), "passed_turns": passed,
        "pass_rate": round(passed/max(1,len(turn_rows)),4),
        "intent_accuracy": round(intent_correct/max(1,len(turn_rows)),4),
        "tool_accuracy": round(tool_correct/max(1,len(turn_rows)),4),
        "p50_ms":round(percentile(durations,.5),3), "p90_ms":round(percentile(durations,.9),3),
        "p95_ms":round(percentile(durations,.95),3), "p99_ms":round(percentile(durations,.99),3),
        "max_ms":round(max(durations,default=0),3), "total_tokens":tokens,
        "category_duration_ms":dict(categories),
        "unclassified_over_5pct_turns": sum(1 for row in turn_rows if row.get("unclassified_over_5pct")),
        "expected_uncovered_tools": sorted(set(TOOL_WHITELIST) - expected_tools),
        "actual_unexecuted_tools": sorted(set(TOOL_WHITELIST) - actual_tools),
        "sensitive_leak_count": int(security_scan.get("finding_count") or 0),
        "concurrency": int(environment.get("concurrency") or 1),
        "wall_time_ms": round(wall_time_ms, 3),
        "throughput_turns_per_minute": round(len(turn_rows) / max(wall_time_ms / 60_000, 0.000001), 3),
        "checkpoint_lock_wait_ms": round(sum(float(event.get("duration_ms") or 0) for event in checkpoint_lock_events), 3) if checkpoint_lock_events else None,
        "run_complete": not provider_failure_turns and len(scenario_rows) == 50 and len(turn_rows) == 300 and len(dialogues) == 300,
        "provider_failure_turns": len(provider_failure_turns),
        "idempotent_replay_turns": len({
            (event.get("scenario_id"), event.get("turn_id")) for event in traces
            if event.get("name") == "agent.idempotent_replay"
        }),
        "dialogue_records": len(dialogues),
        "unique_answers": len(answer_counts),
        "max_answer_repetition": max(answer_counts.values(), default=0),
        "generic_answer_count": generic_answer_count,
        "answer_generation_modes": dict(modes),
        "polish_success_rate": round(modes.get("llm_grounded", 0) / max(1, sum(modes.values())), 4),
        "polish_fallback_rate": round(modes.get("deterministic_fallback", 0) / max(1, sum(modes.values())), 4),
        "candidate_fact_coverage": round(candidate_fact_complete / max(1, len(candidate_success)), 4),
    }
    json_write(artifact / "summary.json", summary)
    slow = sorted(turn_rows, key=lambda row: float(row["duration_ms"]), reverse=True)[:20]
    error_counts = Counter(
        error.strip().split(" ", 1)[0]
        for row in turn_rows for error in str(row.get("errors") or "").split(";") if error.strip()
    )
    intent_pairs = Counter((str(row.get("expected_intent") or ""), str(row.get("actual_intent") or "")) for row in turn_rows)
    group_rows = []
    for dimension in ("role", "actual_intent"):
        values = sorted({str(row.get(dimension) or "未知") for row in turn_rows})
        for value in values:
            samples = [float(row["duration_ms"]) for row in turn_rows if str(row.get(dimension) or "未知") == value]
            group_rows.append({"dimension": "角色" if dimension == "role" else "意图", "value": value, "count": len(samples), "avg": sum(samples)/len(samples), "p95": percentile(samples, .95)})
    specialty_rows = []
    specialty_map = {
        "安全与注入": {"injection_security"}, "权限": {"interviewer_denied"},
        "消歧": {"ambiguity_security"}, "审批": {"approval_risk"},
        "幂等": {"interview_feedback", "notification_sync"}, "偏好记忆": {"memory_preference"},
    }
    for label, tags in specialty_map.items():
        matching = [row for row in scenario_rows if tags.intersection(set(str(row.get("tags") or "").split("|")))]
        specialty_rows.append({"label": label, "count": len(matching), "passed": sum(1 for row in matching if row.get("passed"))})
    trace_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for trace in traces:
        if trace.get("scenario_id") and trace.get("turn_id"):
            trace_groups[(str(trace["scenario_id"]), str(trace["turn_id"]))].append(trace)
    waterfalls = []
    for row in slow:
        spans = sorted(trace_groups.get((str(row["scenario_id"]), str(row["turn_id"])), []), key=lambda item: float(item.get("duration_ms") or 0), reverse=True)[:8]
        waterfalls.append({"row": row, "spans": spans, "maximum": max([float(item.get("duration_ms") or 0) for item in spans] or [1])})
    category_total = sum(categories.values()) or 1
    template = Template("""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>RecruitFlow Agent 评测</title><style>body{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:32px;color:#18332b;background:#f5f3ec}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,table,.waterfall{background:white;border:1px solid #dce4df;border-radius:12px;padding:16px}strong{font-size:27px;display:block}table{width:100%;border-collapse:collapse;margin-top:18px}th,td{padding:9px;border-bottom:1px solid #eee;text-align:left}.bar{height:12px;background:#145c45;border-radius:8px;min-width:2px}.bad{color:#b84e45}.muted{color:#687b74;font-size:13px}.waterfall{margin:10px 0}.span{display:grid;grid-template-columns:240px 1fr 90px;gap:8px;margin:6px}.span .bar{background:#dc9c35}</style><h1>RecruitFlow Agent 真实模型评测</h1><p class='muted'>分类耗时为 Span 累计值，父子 Span 可能重叠；逐轮 CSV 中提供精确 SQL、Checkpoint、工具和未分类开销。</p><div class='grid'><div class='card'>场景 / 轮次<strong>{{s.scenarios}} / {{s.turns}}</strong></div><div class='card'>并发 / 吞吐<strong>{{s.concurrency}} / {{s.throughput_turns_per_minute}} rpm</strong></div><div class='card'>通过率<strong>{{'%.1f'|format(s.pass_rate*100)}}%</strong></div><div class='card'>墙钟时间<strong>{{'%.1f'|format(s.wall_time_ms/1000)}} s</strong></div><div class='card'>Token<strong>{{s.total_tokens}}</strong></div><div class='card'>意图 / 工具准确率<strong>{{'%.1f'|format(s.intent_accuracy*100)}}% / {{'%.1f'|format(s.tool_accuracy*100)}}%</strong></div><div class='card'>P95 / P99<strong>{{s.p95_ms}} / {{s.p99_ms}} ms</strong></div><div class='card'>锁等待 / 泄露<strong>{{(s.checkpoint_lock_wait_ms|string + ' ms') if s.checkpoint_lock_wait_ms is not none else '未采集'}} / {{s.sensitive_leak_count}}</strong></div></div><h2>专项结果与覆盖</h2><table><tr><th>专项</th><th>通过/总数</th></tr>{% for row in specialty %}<tr><td>{{row.label}}</td><td>{{row.passed}} / {{row.count}}</td></tr>{% endfor %}<tr><td>预期未覆盖工具</td><td>{{s.expected_uncovered_tools|join(', ') or '无'}}</td></tr><tr><td>实际未执行工具</td><td>{{s.actual_unexecuted_tools|join(', ') or '无'}}</td></tr></table><h2>耗时分类</h2><table><tr><th>分类</th><th>累计耗时</th><th>占比</th></tr>{% for name,value in categories %}<tr><td>{{name}}</td><td>{{'%.3f'|format(value)}} ms</td><td><div class='bar' style='width:{{value/category_total*100}}%'></div>{{'%.1f'|format(value/category_total*100)}}%</td></tr>{% endfor %}</table><h2>按角色与意图</h2><table><tr><th>维度</th><th>值</th><th>轮数</th><th>平均</th><th>P95</th></tr>{% for row in groups %}<tr><td>{{row.dimension}}</td><td>{{row.value}}</td><td>{{row.count}}</td><td>{{'%.1f'|format(row.avg)}} ms</td><td>{{'%.1f'|format(row.p95)}} ms</td></tr>{% endfor %}</table><h2>意图混淆矩阵（非零项）</h2><table><tr><th>预期</th><th>实际</th><th>次数</th></tr>{% for pair,count in intent_pairs %}<tr><td>{{pair[0]}}</td><td>{{pair[1]}}</td><td>{{count}}</td></tr>{% endfor %}</table><h2>错误分布</h2><table><tr><th>错误类型</th><th>次数</th></tr>{% for name,count in errors %}<tr><td>{{name}}</td><td>{{count}}</td></tr>{% else %}<tr><td colspan='2'>无</td></tr>{% endfor %}</table><h2>最慢20轮与 Span 瀑布</h2>{% for item in waterfalls %}<div class='waterfall'><b>{{item.row.scenario_id}} / {{item.row.turn_id}}</b> · {{item.row.duration_ms}} ms · {{'通过' if item.row.passed else item.row.errors}}{% for sp in item.spans %}<div class='span'><span>{{sp.name}}</span><div class='bar' style='width:{{sp.duration_ms/item.maximum*100}}%'></div><span>{{'%.2f'|format(sp.duration_ms)}} ms</span></div>{% endfor %}</div>{% endfor %}</html>""")
    html = template.render(
        s=summary, categories=sorted(categories.items(),key=lambda x:x[1],reverse=True),
        category_total=category_total, groups=group_rows,
        intent_pairs=sorted(intent_pairs.items()), errors=error_counts.most_common(),
        waterfalls=waterfalls, specialty=specialty_rows,
    )
    quality_html = (
        "<h2>回答质量</h2><div class='grid'>"
        f"<div class='card'>真实对话记录<strong>{summary['dialogue_records']}</strong></div>"
        f"<div class='card'>不同回答<strong>{summary['unique_answers']}</strong></div>"
        f"<div class='card'>最大重复 / 空泛<strong>{summary['max_answer_repetition']} / {summary['generic_answer_count']}</strong></div>"
        f"<div class='card'>事实覆盖率<strong>{summary['candidate_fact_coverage'] * 100:.1f}%</strong></div>"
        f"<div class='card'>润色成功率<strong>{summary['polish_success_rate'] * 100:.1f}%</strong></div>"
        f"<div class='card'>确定性降级率<strong>{summary['polish_fallback_rate'] * 100:.1f}%</strong></div>"
        "</div>"
    )
    html = html.replace("<h2>专项结果与覆盖</h2>", quality_html + "<h2>专项结果与覆盖</h2>")
    (artifact / "report.html").write_text(html, encoding="utf-8")


def run_one_scenario(
    *, base_url: str, run_id: str, artifact: Path,
    scenario: AgentScenario, fail_fast: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    aliases = create_fixture(scenario)
    username = aliases["hr_username"] if scenario.role == "hr" else aliases["interviewer_username"]
    client = login(base_url, username)
    conversation_id = None
    scenario_errors: list[str] = []
    rows: list[dict[str, Any]] = []
    scenario_started = time.perf_counter()
    pending = None
    previous_key = None
    turn_keys: dict[str, str] = {}
    try:
        for turn in scenario.turns:
            if turn.reuse_idempotency_from:
                key = turn_keys.get(turn.reuse_idempotency_from)
                if not key:
                    raise RuntimeError(f"{turn.turn_id} references unknown idempotency source {turn.reuse_idempotency_from}")
            else:
                key = previous_key if turn.repeat_previous_idempotency_key and previous_key else f"eval-{scenario.scenario_id}-{turn.turn_id}-{uuid.uuid4().hex}"
            previous_key = key
            turn_keys[turn.turn_id] = key
            payload = {
                "conversation_id": conversation_id, "message": turn.message,
                "idempotency_key": key, "client_timezone": "Asia/Shanghai",
            }
            selection_error = None
            if turn.select_choice_by_label:
                if not pending:
                    selection_error = "expected clarification card was not available"
                else:
                    alias_key = {"candidate_a": "candidate_id", "candidate_b": "candidate_b_id"}.get(turn.select_choice_by_label)
                    choice = next((
                        item for item in pending.get("choices", [])
                        if turn.select_choice_by_label in item["label"]
                        or (alias_key and (item.get("value") or {}).get("candidate_id") == aliases.get(alias_key))
                    ), None)
                    if choice:
                        payload["action_response"] = {"action_id": pending["action_id"], "choice_id": choice["id"]}
                    else:
                        selection_error = f"clarification choice not found for alias={turn.select_choice_by_label}"
            headers = {
                "X-Trace-Run-ID": run_id, "X-Trace-Scenario-ID": scenario.scenario_id,
                "X-Trace-Turn-ID": turn.turn_id, "X-Request-ID": str(uuid.uuid4()),
            }
            started = time.perf_counter()
            errors: list[str] = [selection_error] if selection_error else []
            data: dict[str, Any] = {}
            response_text = ""
            try:
                response = client.post("/api/agent/chat", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()["data"]
                response_text = data.get("message", "")
                conversation_id = data.get("conversation_id") or conversation_id
                pending = data.get("clarification")
                errors.extend(assert_turn(turn.expect, data, response_text))
                timing = parse_server_timing(response.headers.get("Server-Timing", ""))
            except Exception as exc:
                errors.append(f"request_error {type(exc).__name__}: {str(exc)[:300]}")
                timing = {}
            duration_ms = (time.perf_counter() - started) * 1000
            errors = [error for error in errors if error]
            passed = not errors
            scenario_errors.extend(f"{turn.turn_id}: {error}" for error in errors)
            row = {
                "scenario_id": scenario.scenario_id, "role": scenario.role, "turn_id": turn.turn_id,
                "expected_intent": turn.expect.intent, "actual_intent": (data.get("intent") or {}).get("name"),
                "confidence": (data.get("intent") or {}).get("confidence"),
                "expected_tools": "|".join(turn.expect.tools),
                "actual_tools": "|".join(item.get("name", "") for item in data.get("tool_calls", [])),
                "status": data.get("status"), "duration_ms": round(duration_ms, 3),
                "server_total_ms": timing.get("total", 0), "agent_ms": timing.get("agent", 0),
                "llm_ms": timing.get("llm", 0), "db_ms": timing.get("db", 0),
                "checkpoint_ms": timing.get("checkpoint", 0), "tool_ms": timing.get("tool", 0),
                "passed": passed, "errors": "; ".join(errors),
                "generation_mode": (data.get("answer_card") or {}).get("generation_mode"),
            }
            rows.append(row)
            jsonl_append(artifact / "dialogues.jsonl", {
                "run_id": run_id,
                "scenario_id": scenario.scenario_id,
                "scenario_title": scenario.title,
                "role": scenario.role,
                "turn_id": turn.turn_id,
                "question": redact_artifact_text(turn.message),
                "answer": response_text,
                "answer_card": data.get("answer_card"),
                "intent": (data.get("intent") or {}).get("name"),
                "confidence": (data.get("intent") or {}).get("confidence"),
                "status": data.get("status"),
                "tools": [item.get("name") for item in data.get("tool_calls", [])],
                "tool_result_summary": data.get("data"),
                "generation_mode": (data.get("answer_card") or {}).get("generation_mode") or "legacy",
                "passed": passed,
                "errors": errors,
            })
            client_trace(artifact / "traces.client.jsonl", run_id, scenario.scenario_id, turn.turn_id, duration_ms, "ok" if passed else "error")
            if errors:
                jsonl_append(artifact / "errors.jsonl", row)
            if errors and fail_fast:
                raise RuntimeError(errors[0])
        scenario_errors.extend(final_assertions(scenario, aliases))
    finally:
        client.close()
    scenario_row = {
        "scenario_id": scenario.scenario_id, "role": scenario.role, "title": scenario.title,
        "tags": "|".join(scenario.tags), "turns": 6,
        "passed_turns": sum(1 for row in rows if row["passed"]),
        "duration_ms": round((time.perf_counter() - scenario_started) * 1000, 3),
        "passed": not scenario_errors, "errors": "; ".join(scenario_errors),
    }
    return rows, scenario_row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-dir", type=Path, default=PROJECT_DIR / "backend/tests/scenarios/agent_multiturn")
    parser.add_argument("--real-llm", action="store_true")
    parser.add_argument("--reset-db", action="store_true")
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--scenario")
    parser.add_argument("--tag")
    parser.add_argument("--rerun-failed-from")
    parser.add_argument("--run-id")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    if args.concurrency < 1 or args.concurrency > 5:
        raise SystemExit("--concurrency must be between 1 and 5 for the SQLite-checkpoint evaluator")
    concurrency = 1 if args.sequential else args.concurrency
    if args.real_llm and os.getenv("RUN_REAL_LLM_TESTS") != "1":
        raise SystemExit("Set RUN_REAL_LLM_TESTS=1 before real Qwen evaluation")
    artifact_root = PROJECT_DIR / "backend/data/test-artifacts"
    if args.resume and not args.run_id:
        resumable = sorted(
            (path for path in artifact_root.glob("eval_*") if (path / "run-state.json").exists()),
            key=lambda path: path.stat().st_mtime, reverse=True,
        )
        if not resumable:
            raise SystemExit("No resumable evaluation found; pass --run-id or start a new run")
        run_id = resumable[0].name
    else:
        run_id = args.run_id or time.strftime("eval_%Y%m%d_%H%M%S")
    artifact = artifact_root / run_id
    artifact.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"APP_ENV":"test","DB_NAME":settings.test_db_name,"TEST_DB_NAME":settings.test_db_name,"AGENT_TRACE_ENABLED":"true","AGENT_TRACE_DIR":str(artifact),"AGENT_TRACE_SAMPLE_RATE":"1.0","BACKGROUND_WORKER_ENABLED":"false","AGENT_LLM_ROUTER_ENABLED":"true" if args.real_llm else "false","RESPONSE_LLM_ENABLED":"true" if args.real_llm else "false","RESPONSE_LLM_TIMEOUT_SECONDS":"20" if args.real_llm else "8","LANGGRAPH_CHECKPOINT_PATH":str(artifact/"checkpoints.sqlite"),"PYTHONPATH":str(PROJECT_DIR/"backend")})
    state_path = artifact / "run-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if args.resume and state_path.exists() else {"completed":[]}
    if args.reset_db and not (args.resume and state.get("completed")):
        reset_test_database(env)
    scenarios = load_scenarios(args.scenario_dir, args.scenario, args.tag)
    if args.rerun_failed_from:
        source = Path(args.rerun_failed_from)
        if not source.is_absolute():
            source = artifact_root / source
        failed_rows = read_csv_rows(source / "scenarios.csv")
        failed_ids = {row["scenario_id"] for row in failed_rows if not row.get("passed")}
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id in failed_ids]
        if not scenarios:
            raise SystemExit("No failed scenarios found in --rerun-failed-from")
    expected_turns = sum(len(item.turns) for item in scenarios if item.scenario_id not in state["completed"])
    print(f"EVAL_START run_id={run_id} scenarios={len(scenarios)} pending_turns={expected_turns} real_llm={args.real_llm} concurrency={concurrency}", flush=True)
    json_write(artifact / "environment.json", {"run_id":run_id,"python":sys.version,"platform":platform.platform(),"model":settings.llm_model,"prompt_version":settings.agent_prompt_version,"scenario_count":len(scenarios),"real_llm":args.real_llm,"concurrency":concurrency})
    server_out=(artifact/"server.out.log").open("w",encoding="utf-8"); server_err=(artifact/"server.err.log").open("w",encoding="utf-8")
    server = subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--app-dir",str(PROJECT_DIR/"backend"),"--host","127.0.0.1","--port",str(args.port)],cwd=PROJECT_DIR,env=env,stdout=server_out,stderr=server_err)
    base_url=f"http://127.0.0.1:{args.port}"
    for _ in range(60):
        try:
            if httpx.get(base_url+"/health/ready",timeout=1).status_code==200: break
        except Exception: pass
        time.sleep(.5)
    else:
        server.terminate(); raise RuntimeError("Evaluation server failed to start")
    turn_rows = read_csv_rows(artifact / "turns.csv") if args.resume else []
    scenario_rows = read_csv_rows(artifact / "scenarios.csv") if args.resume else []
    evaluation_started = time.perf_counter()
    pending_scenarios = [scenario for scenario in scenarios if scenario.scenario_id not in state["completed"]]

    def accept_result(scenario: AgentScenario, result: tuple[list[dict[str, Any]], dict[str, Any]]) -> None:
        rows, scenario_row = result
        turn_rows.extend(rows)
        scenario_rows.append(scenario_row)
        state["completed"].append(scenario.scenario_id)
        json_write(state_path, state)
        completed_count = len(state["completed"])
        if completed_count % 10 == 0 or completed_count == len(scenarios):
            elapsed = time.perf_counter() - evaluation_started
            passed_now = sum(1 for row in turn_rows if row["passed"])
            print(f"PROGRESS {completed_count}/{len(scenarios)} pass_rate={passed_now/max(1,len(turn_rows)):.1%} elapsed_s={elapsed:.1f}", flush=True)

    try:
        if concurrency == 1:
            for scenario in pending_scenarios:
                accept_result(scenario, run_one_scenario(
                    base_url=base_url, run_id=run_id, artifact=artifact,
                    scenario=scenario, fail_fast=args.fail_fast,
                ))
        else:
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="agent-eval") as executor:
                futures = {
                    executor.submit(
                        run_one_scenario, base_url=base_url, run_id=run_id,
                        artifact=artifact, scenario=scenario, fail_fast=args.fail_fast,
                    ): scenario
                    for scenario in pending_scenarios
                }
                for future in as_completed(futures):
                    scenario = futures[future]
                    try:
                        accept_result(scenario, future.result())
                    except Exception as exc:
                        jsonl_append(artifact / "errors.jsonl", {
                            "scenario_id": scenario.scenario_id,
                            "error_code": "SCENARIO_RUNNER_ERROR",
                            "error_type": type(exc).__name__, "message": str(exc)[:300],
                        })
                        if args.fail_fast:
                            for pending_future in futures:
                                pending_future.cancel()
                            raise
    finally:
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill()
        server_out.close(); server_err.close()
    traces = load_trace_events(artifact)
    turn_rows.sort(key=lambda row: (str(row.get("scenario_id")), str(row.get("turn_id"))))
    scenario_rows.sort(key=lambda row: str(row.get("scenario_id")))
    enrich_turn_rows(turn_rows, traces)
    for scenario_row in scenario_rows:
        matching = [row for row in turn_rows if row["scenario_id"] == scenario_row["scenario_id"]]
        scenario_row["passed_turns"] = sum(1 for row in matching if row.get("passed"))
        scenario_row["passed"] = bool(matching) and all(row.get("passed") for row in matching) and not scenario_row.get("errors")
        scenario_row["total_tokens"] = sum(int(row.get("total_tokens") or 0) for row in matching)
        slowest = max(matching, key=lambda row: float(row.get("duration_ms") or 0), default=None)
        scenario_row["slowest_turn"] = slowest.get("turn_id") if slowest else ""
        scenario_row["slowest_node"] = slowest.get("slowest_span") if slowest else ""
    write_csv_rows(artifact / "turns.csv", turn_rows)
    write_csv_rows(artifact / "scenarios.csv", scenario_rows)
    findings = scan_artifact_leaks(artifact)
    if findings:
        jsonl_append(artifact / "errors.jsonl", {"error_code": "SENSITIVE_LOG_LEAK", "finding_count": len(findings), "findings": findings})
    generate_report(artifact,turn_rows,scenario_rows,traces)
    final_summary = json.loads((artifact / "summary.json").read_text(encoding="utf-8"))
    if final_summary.get("run_complete", True):
        marker = "EVAL_COMPLETE"
    elif final_summary.get("provider_failure_turns"):
        marker = "EVAL_INCOMPLETE_PROVIDER_FAILURE"
    else:
        marker = "EVAL_INCOMPLETE"
    print(f"{marker} artifact={artifact} scenarios={len(scenario_rows)} turns={len(turn_rows)}")


if __name__ == "__main__":
    main()
