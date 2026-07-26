from __future__ import annotations

from app.agent.response import (
    FactItem,
    FactPacket,
    PolishPlan,
    _polish_is_safe,
    build_fact_packet,
    deterministic_card,
    render_answer_card,
)
from app.agent.types import IntentName, IntentResult


def test_candidate_search_renders_real_rows_instead_of_completion_template():
    packet = build_fact_packet(
        IntentResult(intent=IntentName.candidate_search, confidence=0.99),
        status="completed",
        data={
            "total": 1,
            "items": [{
                "name": "林安", "job_name": "Python 后端工程师",
                "status": "interview_1", "skills": ["Python", "FastAPI"], "source": "resume",
            }],
        },
        tool_results=[],
    )
    message = render_answer_card(deterministic_card(packet))
    assert "林安" in message
    assert "Python 后端工程师" in message
    assert "一面" in message
    assert "操作已完成" not in message


def test_response_polish_rejects_unknown_fact_key_action_and_contact():
    packet = FactPacket(
        intent="candidate_detail", status="completed", title="候选人详情",
        summary="已查询脱敏详情。",
        facts=[FactItem(key="candidate_name", label="候选人", value="林安")],
        allowed_actions={"detail": "查看详情"},
    )
    assert _polish_is_safe(
        PolishPlan(opening="候选人信息已核对。", fact_keys=["candidate_name"], action_ids=["detail"]),
        packet,
    )
    assert not _polish_is_safe(
        PolishPlan(opening="候选人信息已核对。", fact_keys=["salary"], action_ids=["detail"]),
        packet,
    )
    assert not _polish_is_safe(
        PolishPlan(opening="请拨打13800138000。", fact_keys=["candidate_name"], action_ids=["detail"]),
        packet,
    )


def test_approval_answer_never_claims_business_change_was_applied():
    packet = build_fact_packet(
        IntentResult(intent=IntentName.status_change, confidence=0.99),
        status="approval_required",
        data={
            "approval": {
                "id": "12345678-1234-5678-1234-567812345678",
                "status": "pending", "reason": "高风险阶段变更",
                "proposed_data": {"target_status": "rejected"},
                "candidate_job": {"candidate_name": "林安", "job_name": "Python 后端工程师", "status": "interview_1"},
            }
        },
        tool_results=[],
    )
    message = render_answer_card(deterministic_card(packet))
    assert "批准前不会修改" in message
    assert "拟变更阶段：已淘汰" in message
    assert "阶段已更新" not in message
