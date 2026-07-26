from __future__ import annotations

import os
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    ApprovalRequest,
    Candidate,
    CandidateJob,
    CandidateStatusHistory,
    DocumentSyncJob,
    Interview,
    Job,
    Notification,
    User,
    utcnow,
)
from app.security import hash_password


NAMESPACE = uuid.UUID("6bdf955d-70af-4dcf-9638-0c7e146a7b35")


def sid(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def main() -> None:
    settings.validate_database_boundary()
    if settings.app_env == "production":
        raise RuntimeError("Seed is disabled in production")
    password = os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"
    now = utcnow()
    with SessionLocal() as db:
        users = [
            User(id=sid("user-admin"), username="admin_demo", display_name="系统管理员", email="admin@example.com", password_hash=hash_password(password), role="admin", department="人力资源部"),
            User(id=sid("user-hr"), username="hr_demo", display_name="林晓 HR", email="hr@example.com", password_hash=hash_password(password), role="hr", department="人力资源部"),
            User(id=sid("user-interviewer"), username="interviewer_demo", display_name="王强", email="interviewer@example.com", password_hash=hash_password(password), role="interviewer", department="技术中心"),
        ]
        for item in users:
            existing = db.get(User, item.id)
            if not existing:
                db.add(item)
            else:
                existing.password_hash = item.password_hash
                existing.is_active = True
        db.flush()

        jobs = [
            Job(id=sid("job-backend"), job_code="BE-2026-001", job_name="Python 后端工程师", department="技术中心", description="负责 AI 招聘平台后端服务", requirements="Python、FastAPI、MySQL，3 年以上经验", location="上海", headcount=2, owner_id=sid("user-hr"), status="open", opened_at=now),
            Job(id=sid("job-agent"), job_code="AI-2026-001", job_name="AI Agent 工程师", department="AI 平台部", description="负责 LangGraph Agent 编排", requirements="LangChain、LangGraph、Tool Calling", location="杭州", headcount=2, owner_id=sid("user-hr"), status="open", opened_at=now),
            Job(id=sid("job-frontend"), job_code="FE-2026-001", job_name="前端工程师", department="技术中心", description="负责招聘工作台体验", requirements="JavaScript、React 或 Vue", location="上海", headcount=1, owner_id=sid("user-hr"), status="open", opened_at=now),
            Job(id=sid("job-closed"), job_code="QA-2025-009", job_name="测试工程师", department="质量部", description="历史招聘岗位", requirements="自动化测试", location="苏州", headcount=1, owner_id=sid("user-hr"), status="closed", opened_at=now - timedelta(days=90), closed_at=now - timedelta(days=20)),
        ]
        for item in jobs:
            if not db.get(Job, item.id):
                db.add(item)
        db.flush()

        people = [
            ("李明", "13800000001", "liming@example.com", "job-backend", "interview_1", ["Python", "FastAPI", "MySQL"], "referral"),
            ("王芳", "13800000002", "wangfang@example.com", "job-agent", "final_interview", ["LangChain", "LangGraph", "Python"], "job_board"),
            ("赵磊", "13800000003", "zhaolei@example.com", "job-backend", "screening", ["Python", "Docker"], "resume"),
            ("陈雪", "13800000004", "chenxue@example.com", "job-frontend", "interview_1", ["Vue", "JavaScript"], "referral"),
            ("周航", "13800000005", "zhouhang@example.com", "job-agent", "interview_2", ["Python", "Tool Calling"], "resume"),
            ("吴桐", "13800000006", "wutong@example.com", "job-backend", "new", ["Python", "SQL"], "job_board"),
            ("孙悦", "13800000007", "sunyue@example.com", "job-frontend", "offer", ["React", "TypeScript"], "resume"),
            ("郑凯", "13800000008", "zhengkai@example.com", "job-agent", "on_hold", ["LangGraph", "MySQL"], "referral"),
            ("冯琳", "13800000009", "fenglin@example.com", "job-backend", "rejected", ["Java", "SQL"], "job_board"),
            ("何俊", "13800000010", "hejun@example.com", "job-agent", "hired", ["Python", "LangChain"], "resume"),
            ("唐佳", "13800000011", "tangjia@example.com", "job-frontend", "withdrawn", ["Vue", "CSS"], "referral"),
            ("许晨", "13800000012", "xuchen@example.com", "job-backend", "screening", ["FastAPI", "PostgreSQL"], "job_board"),
        ]
        for index, (name, phone, email, job_key, stage, skills, source) in enumerate(people, start=1):
            candidate_id = sid(f"candidate-{index}")
            app_id = sid(f"application-{index}")
            if not db.get(Candidate, candidate_id):
                db.add(Candidate(id=candidate_id, name=name, phone=phone, email=email, city="上海", source=source, years_of_experience=Decimal("3.0") + Decimal(index) / Decimal("10"), skills=skills, education=[], work_experience=[], projects=[], summary=f"{name} 的虚构演示档案", created_by=sid("user-hr")))
            if not db.get(CandidateJob, app_id):
                app = CandidateJob(id=app_id, candidate_id=candidate_id, job_id=sid(job_key), owner_id=sid("user-hr"), source=source, status=stage, applied_at=now - timedelta(days=20-index), stage_entered_at=now - timedelta(days=max(1, 12-index)), next_action="跟进候选人" if stage not in {"hired", "rejected", "withdrawn"} else None, next_action_at=now + timedelta(days=(index % 5) + 1) if stage not in {"hired", "rejected", "withdrawn"} else None)
                db.add(app)
                db.add(CandidateStatusHistory(candidate_job_id=app_id, from_status=None, to_status=stage, reason="演示种子数据", operator_type="system", request_id=sid(f"seed-request-{index}")))
        db.flush()

        interview_specs = [
            ("application-1", 2, "second"),
            ("application-2", 1, "final"),
            ("application-4", 3, "first"),
            ("application-5", 5, "second"),
            ("application-3", 7, "screening"),
            ("application-12", -2, "screening"),
        ]
        for index, (app_key, days, round_name) in enumerate(interview_specs, start=1):
            interview_id = sid(f"interview-{index}")
            if not db.get(Interview, interview_id):
                scheduled = now + timedelta(days=days, hours=2)
                status = "completed" if days < 0 else "scheduled"
                db.add(Interview(id=interview_id, candidate_job_id=sid(app_key), round=round_name, interview_type="online", scheduled_at=scheduled, duration_minutes=60, interviewer_id=sid("user-interviewer"), additional_interviewers=[], meeting_url="https://example.com/demo-meeting", status=status, recommendation="pending", created_by=sid("user-hr")))
                if days >= 0:
                    db.add(Notification(id=sid(f"notification-{index}"), candidate_job_id=sid(app_key), interview_id=interview_id, channel="in_app", recipient_type="user", recipient=sid("user-interviewer"), content="虚构面试提醒", scheduled_at=scheduled - timedelta(hours=24)))

        approval_id = sid("approval-demo")
        if not db.get(ApprovalRequest, approval_id):
            db.add(ApprovalRequest(id=approval_id, candidate_job_id=sid("application-2"), request_type="status_change", proposed_action="update_candidate_status", proposed_data={"target_status": "rejected", "reason": "演示高风险审批"}, reason="淘汰候选人必须人工审批", confidence=Decimal("0.93"), target_version=1, idempotency_key=hashlib_sha("seed-approval"), status="pending", requested_by_type="agent", requested_by=sid("user-hr")))

        db.commit()
        print("SEED_OK users=3 jobs=4 candidates=12")


def hashlib_sha(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


if __name__ == "__main__":
    main()
