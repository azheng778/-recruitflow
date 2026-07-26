from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

from app.agent.evaluation import AgentScenario
from app.agent.graph import TOOL_WHITELIST
from app.config import PROJECT_DIR


SCENARIO_DIR = Path(__file__).parent / "scenarios" / "agent_multiturn"


def load_scenarios() -> list[AgentScenario]:
    return [
        AgentScenario.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(SCENARIO_DIR.glob("*/*.json"))
    ]


def test_agent_scenario_cardinality_and_roles():
    scenarios = load_scenarios()
    roles = Counter(item.role for item in scenarios)
    assert len(scenarios) == 50
    assert sum(len(item.turns) for item in scenarios) == 300
    assert roles == {"hr": 35, "interviewer": 15}
    assert len({item.scenario_id for item in scenarios}) == 50
    questions = [turn.message for scenario in scenarios for turn in scenario.turns]
    assert len(set(questions)) >= 200


def test_all_whitelisted_tools_are_covered():
    covered = {tool for item in load_scenarios() for tool in item.covered_tools}
    assert covered == set(TOOL_WHITELIST)


def test_manifest_hashes_match_assets():
    with (SCENARIO_DIR / "manifest.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 50
    for row in rows:
        path = PROJECT_DIR / row["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]


def test_scenarios_do_not_contain_real_contact_data():
    for path in SCENARIO_DIR.glob("*/*.json"):
        text = path.read_text(encoding="utf-8")
        assert "@example.com" not in text
        assert "LLM_API_KEY" not in text
        assert "DB_PASSWORD" not in text
