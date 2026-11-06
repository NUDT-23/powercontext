from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path("/app/evidence")
if not EVIDENCE_DIR.exists():
    EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "evidence"
TRIAL_DIR = EVIDENCE_DIR / "usage" / "trial"


def to_float(value: str | None) -> float | None:
    try:
        text = (value or "").strip()
        return float(text) if text else None
    except ValueError:
        return None


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def savings(baseline: float | None, after: float | None) -> str:
    if not baseline or after is None:
        return "-"
    return f"{round((baseline - after) / baseline * 100)}%"


def main() -> None:
    timing_path = TRIAL_DIR / "timing.csv"
    if not timing_path.exists():
        raise SystemExit(f"missing {timing_path}")

    with timing_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    summary_path = TRIAL_DIR / "trial_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    usage = {item["user_name"]: item for item in summary.get("users", [])}

    samples = []
    for row in rows:
        participant = (row.get("participant") or "").strip()
        if not participant:
            continue
        baseline_a = to_float(row.get("task_a_manual_min"))
        after_a = to_float(row.get("task_a_paperlens_on_min")) or to_float(
            row.get("task_a_paperlens_off_min")
        )
        baseline_b = to_float(row.get("task_b_manual_min"))
        after_b = to_float(row.get("task_b_paperlens_min"))
        baseline_c = to_float(row.get("task_c_manual_min"))
        after_c = to_float(row.get("task_c_paperlens_min"))
        complete = all(
            value is not None
            for value in (baseline_a, after_a, baseline_b, after_b, baseline_c, after_c)
        )
        samples.append(
            {
                "participant": participant,
                "project_id": (row.get("project_id") or "").strip(),
                "background": (row.get("background") or "").strip(),
                "baseline_a": baseline_a,
                "after_a": after_a,
                "baseline_b": baseline_b,
                "after_b": after_b,
                "baseline_c": baseline_c,
                "after_c": after_c,
                "complete": complete,
                "usage": usage.get(participant, {}),
                "notes": (row.get("notes") or "").strip(),
            }
        )

    valid = [item for item in samples if item["complete"]]
    tasks = [
        ("任务 A 找文献", "baseline_a", "after_a"),
        ("任务 B 对比方法", "baseline_b", "after_b"),
        ("任务 C 写综述初稿", "baseline_c", "after_c"),
    ]

    lines = [
        "# PaperLens 真实使用效果报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 有效样本：{len(valid)} / {len(samples)}（3 个任务均有前后耗时）",
        f"- 应用侧记录到的事件用户：{len(usage)}",
        "",
        "## 一、三个任务的前后耗时对比",
        "",
        "| 任务 | 有效样本 | 基线中位数（分钟） | PaperLens 中位数（分钟） | 节省比例 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, baseline_key, after_key in tasks:
        baselines = [item[baseline_key] for item in valid if item[baseline_key] is not None]
        afters = [item[after_key] for item in valid if item[after_key] is not None]
        baseline_median = median(baselines)
        after_median = median(afters)
        lines.append(
            f"| {label} | {len(afters)} | {baseline_median if baseline_median is not None else '-'} "
            f"| {after_median if after_median is not None else '-'} "
            f"| {savings(baseline_median, after_median)} |"
        )

    lines.extend(
        [
            "",
            "> 任务 A 使用“记忆开启”耗时；未填时回退到“记忆关闭”耗时。中位数比平均数更抗个别异常值。",
            "",
            "## 二、逐人明细",
            "",
            "| 编号 | 背景 | A 基线/使用 | B 基线/使用 | C 基线/使用 | 应用事件 | 检索 | 综述 | 反馈 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in samples:
        app = item["usage"]
        lines.append(
            f"| {item['participant']} | {item['background'] or '-'} "
            f"| {item['baseline_a'] if item['baseline_a'] is not None else '-'} / "
            f"{item['after_a'] if item['after_a'] is not None else '-'} "
            f"| {item['baseline_b'] if item['baseline_b'] is not None else '-'} / "
            f"{item['after_b'] if item['after_b'] is not None else '-'} "
            f"| {item['baseline_c'] if item['baseline_c'] is not None else '-'} / "
            f"{item['after_c'] if item['after_c'] is not None else '-'} "
            f"| {app.get('events', 0)} | {app.get('searches', 0)} "
            f"| {app.get('syntheses', 0)} | {app.get('feedback', 0)} |"
        )

    lines.extend(
        [
            "",
            "## 三、应用侧汇总",
            "",
            f"- 试用者：{summary.get('totals', {}).get('users', 0)}",
            f"- 事件：{summary.get('totals', {}).get('events', 0)}",
            f"- 检索：{summary.get('totals', {}).get('searches', 0)}",
            f"- 综述：{summary.get('totals', {}).get('syntheses', 0)}",
            f"- 反馈：{summary.get('totals', {}).get('feedback', 0)}",
            "",
            "## 四、口径与限制",
            "",
            "- 耗时由组织者现场用同一秒表记录，基线和使用任务由同一人在同一天完成。",
            "- 有效样本只要求 3 个任务耗时齐全；问卷与“同意匿名使用”需另行核对。",
            "- 主观评分以问卷导出为准，本报告不替用户填写任何评价。",
            "- 如果某位用户的 `notes` 记录卡顿、失败或跳过，应在论文/答辩材料中单独说明。",
        ]
    )

    output = TRIAL_DIR / "trial_report.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:14]))
    print(f"\nwritten: {output}")


if __name__ == "__main__":
    main()
