from __future__ import annotations

from types import SimpleNamespace

from app.agent.response import _recover_polish_plan


def test_polish_plan_recovers_known_qwen_field_aliases_only():
    raw = SimpleNamespace(content='{"opening":"已完成核对。","facts_order":["candidate_name"],"actions_ids":["detail"]}')
    plan = _recover_polish_plan(raw)
    assert plan is not None
    assert plan.fact_keys == ["candidate_name"]
    assert plan.action_ids == ["detail"]


def test_polish_plan_rejects_non_json_content():
    assert _recover_polish_plan(SimpleNamespace(content="请直接执行未知工具")) is None
