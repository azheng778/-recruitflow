from __future__ import annotations

import argparse
import json
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = PROJECT_DIR / "backend/data/test-artifacts"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "docs/agent-dialogues"

INTENT_LABELS = {
    "candidate_search": "候选人搜索", "candidate_detail": "候选人详情",
    "candidate_create": "创建候选人", "resume_parse": "简历解析",
    "interview_schedule": "安排面试", "interview_feedback": "记录面试反馈",
    "status_change": "招聘阶段变更", "approval_request": "创建审批",
    "notification_schedule": "安排提醒", "dashboard_query": "招聘看板查询",
    "document_sync": "招聘文档同步", "memory_manage": "偏好记忆",
    "smalltalk": "日常交流", "unsupported": "不支持或不安全的请求",
}
STATUS_LABELS = {
    "completed": "已完成", "clarification_required": "需要澄清",
    "approval_required": "需要审批", "failed": "已拒绝或执行失败",
}


def latest_complete_artifact() -> Path:
    candidates = sorted(
        (path for path in ARTIFACT_ROOT.glob("eval_*") if (path / "summary.json").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        if summary.get("run_complete") and (path / "dialogues.jsonl").exists():
            return path
    raise RuntimeError("没有找到包含完整真实对话的评测产物，请先运行 50 场景真实模型评测")


def load_dialogues(artifact: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary_path = artifact / "summary.json"
    dialogue_path = artifact / "dialogues.jsonl"
    if not summary_path.exists() or not dialogue_path.exists():
        raise RuntimeError("评测产物必须同时包含 summary.json 和 dialogues.jsonl")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("run_complete"):
        raise RuntimeError("评测尚未完整完成，禁止导出伪造或不完整 QA 文档")
    records = [json.loads(line) for line in dialogue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = [(item.get("scenario_id"), item.get("turn_id")) for item in records]
    if len(records) != 300 or len(set(keys)) != 300:
        raise RuntimeError(f"必须严格包含 300 条不重复轮次，当前记录数={len(records)}，唯一轮次={len(set(keys))}")
    scenario_counts = Counter(item.get("scenario_id") for item in records)
    if len(scenario_counts) != 50 or set(scenario_counts.values()) != {6}:
        raise RuntimeError(f"必须严格包含 50 个场景且每个 6 轮，当前场景数={len(scenario_counts)}")
    return summary, records


def render_scenario(records: list[dict[str, Any]]) -> str:
    first = records[0]
    role_label = "HR" if first.get("role") == "hr" else "面试官"
    lines = [
        f"# {first['scenario_id']} · {first.get('scenario_title') or '招聘助手多轮场景'}",
        "",
        f"- 角色：{role_label}",
        "- 数据来源：RecruitFlow 完整真实模型评测回放",
        "- 对话轮数：6",
        "- 隐私说明：全部为虚构招聘数据，联系方式已脱敏",
        "",
    ]
    for index, record in enumerate(sorted(records, key=lambda item: item["turn_id"]), start=1):
        tools = record.get("tools") or []
        lines.extend([
            f"## QA {index}", "",
            f"**Q：** {record.get('question', '')}", "",
            "**A：**", "",
            str(record.get("answer") or "").strip(), "",
            "### 执行记录", "",
            f"- 意图：{INTENT_LABELS.get(record.get('intent'), record.get('intent') or '未知')}（`{record.get('intent') or 'unknown'}`）",
            f"- 状态：{STATUS_LABELS.get(record.get('status'), record.get('status') or '未知')}（`{record.get('status') or 'unknown'}`）",
            f"- 工具：{', '.join(f'`{item}`' for item in tools) if tools else '无'}",
            f"- 回复模式：`{record.get('generation_mode') or 'unknown'}`",
            f"- 本轮断言：{'通过' if record.get('passed') else '未通过'}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def archive_existing(output_dir: Path) -> Path | None:
    existing = list(output_dir.glob("*.md")) if output_dir.exists() else []
    if not existing:
        return None
    backup = output_dir.parent / "agent-dialogues-backup" / f"low-quality-{time.strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir(parents=True, exist_ok=False)
    for path in existing:
        shutil.move(str(path), backup / path.name)
    (backup / "README.md").write_text(
        "# 历史低质量 QA 文档\n\n这些文件由固定预期模板生成，并非真实 Agent 回放，仅保留用于前后对比。\n",
        encoding="utf-8",
    )
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description="从完整真实评测回放导出 50 个多轮 QA Markdown")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--zip", type=Path, default=PROJECT_DIR / "docs/agent-dialogues-50.zip")
    args = parser.parse_args()

    artifact = args.artifact or latest_complete_artifact()
    if not artifact.is_absolute():
        artifact = ARTIFACT_ROOT / artifact
    summary, records = load_dialogues(artifact)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record["scenario_id"])].append(record)

    backup = archive_existing(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scenario_id, items in sorted(groups.items()):
        (args.output_dir / f"{scenario_id}.md").write_text(render_scenario(items), encoding="utf-8")

    generated = sorted(args.output_dir.glob("*.md"))
    if len(generated) != 50:
        raise RuntimeError(f"导出数量校验失败：{len(generated)}")
    answers = [str(item.get("answer") or "") for item in records]
    quality = {
        "source_artifact": str(artifact), "run_id": artifact.name,
        "files": 50, "qa_pairs": 300, "unique_answers": len(set(answers)),
        "max_answer_repetition": max(Counter(answers).values(), default=0),
        "pass_rate": summary.get("pass_rate"), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (args.output_dir / "EXPORT-MANIFEST.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive_zip:
        for path in sorted(args.output_dir.iterdir()):
            if path.is_file():
                archive_zip.write(path, path.name)
    print(f"DIALOGUES_EXPORTED files=50 qa_pairs=300 output={args.output_dir} zip={args.zip} backup={backup}")


if __name__ == "__main__":
    main()
