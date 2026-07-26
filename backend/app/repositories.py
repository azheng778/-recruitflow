from __future__ import annotations

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from .models import Candidate, CandidateJob, Job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def get_candidate(db: Session, candidate_id: str, include_deleted: bool = False) -> Candidate | None:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    if not include_deleted:
        stmt = stmt.where(Candidate.deleted_at.is_(None))
    return db.scalar(stmt)


def get_application(db: Session, application_id: str) -> CandidateJob | None:
    return db.get(CandidateJob, application_id)


def candidate_query(
    *,
    keyword: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    owner_id: str | None = None,
) -> Select:
    stmt = (
        select(Candidate, CandidateJob, Job)
        .join(CandidateJob, CandidateJob.candidate_id == Candidate.id)
        .join(Job, Job.id == CandidateJob.job_id)
        .where(Candidate.deleted_at.is_(None))
    )
    if keyword:
        term = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(
            Candidate.name.like(term),
            Job.job_name.like(term),
            cast(Candidate.skills, String).like(term),
        ))
    if job_id:
        stmt = stmt.where(CandidateJob.job_id == job_id)
    if status:
        stmt = stmt.where(CandidateJob.status == status)
    if source:
        stmt = stmt.where(CandidateJob.source == source)
    if owner_id:
        stmt = stmt.where(CandidateJob.owner_id == owner_id)
    return stmt


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[int, list]:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return int(total), rows
