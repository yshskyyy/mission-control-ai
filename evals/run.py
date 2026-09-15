import argparse
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import ai, db, intelligence, repository, services
from app.config import settings as application_settings
from evals.graders import grade_assessment, grade_plan, grade_recommendation, grade_teaching


ROOT = Path(__file__).resolve().parent
SUITES = ("planning", "teaching", "assessment", "recommendation")


@dataclass(frozen=True)
class EvalSettings:
    database_path: Path
    openai_api_key: str | None
    openai_model: str


def load_jsonl(suite: str) -> list[dict]:
    path = ROOT / "datasets" / f"{suite}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_planning(case: dict) -> tuple[list[dict], str]:
    goal = repository.create_goal(case["goal"])
    plan = services.create_plan(goal["id"])
    return grade_plan(goal, plan), plan["rationale"]


def run_teaching(case: dict) -> tuple[list[dict], str]:
    reply, evaluator = ai.teach(case["task"], case.get("messages", []))
    return grade_teaching(case, reply), evaluator


def run_assessment(case: dict) -> tuple[list[dict], str]:
    task = dict(case["task"])
    task["acceptance_criteria"] = json.dumps(task["acceptance_criteria"], ensure_ascii=False)
    result, evaluator = ai.assess(task, case["submission"])
    return grade_assessment(case, result), evaluator


def run_recommendation(case: dict) -> tuple[list[dict], str]:
    ranked = []
    for candidate in case["candidates"]:
        item = {**candidate, "source_type": "GITHUB", "source_name": "eval", "url": "https://example.com"}
        score, breakdown, reason = intelligence.score_for_goal(item, case["goal"], case["nodes"])
        ranked.append({**candidate, "score": score, "breakdown": breakdown, "reason": reason})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return grade_recommendation(case, ranked), "deterministic-scorer"


RUNNERS: dict[str, Callable[[dict], tuple[list[dict], str]]] = {
    "planning": run_planning,
    "teaching": run_teaching,
    "assessment": run_assessment,
    "recommendation": run_recommendation,
}


def execute_suite(suite: str) -> dict:
    results = []
    started = time.monotonic()
    for case in load_jsonl(suite):
        case_started = time.monotonic()
        try:
            checks, evaluator = RUNNERS[suite](case)
            error = None
        except Exception as exc:
            checks = [{"name": "execution", "passed": False, "detail": str(exc)[:500]}]
            evaluator, error = "error", str(exc)[:500]
        results.append({
            "id": case["id"], "passed": all(item["passed"] for item in checks),
            "checks": checks, "evaluator": evaluator, "error": error,
            "latency_ms": round((time.monotonic() - case_started) * 1000),
        })
    passed = sum(item["passed"] for item in results)
    return {
        "suite": suite, "cases": len(results), "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "latency_ms": round((time.monotonic() - started) * 1000), "results": results,
    }


def evaluate_gate(report: dict, baseline: dict) -> tuple[bool, list[str]]:
    failures = []
    rates = {suite["suite"]: suite["pass_rate"] for suite in report["suites"]}
    total_cases = sum(suite["cases"] for suite in report["suites"])
    total_passed = sum(suite["passed"] for suite in report["suites"])
    overall = total_passed / total_cases if total_cases else 0
    report["overall_pass_rate"] = overall
    if overall < baseline["minimum_overall_pass_rate"]:
        failures.append(
            f"overall pass rate {overall:.1%} < {baseline['minimum_overall_pass_rate']:.1%}"
        )
    for suite, rate in rates.items():
        minimum = baseline["minimum_suite_pass_rate"].get(suite, 0)
        if rate < minimum:
            failures.append(f"{suite} pass rate {rate:.1%} < {minimum:.1%}")
    return not failures, failures


def markdown_report(report: dict) -> str:
    lines = [
        "# Mission Control AI Eval Report", "",
        f"- Generated: {report['generated_at']}",
        f"- Mode: {report['mode']}",
        f"- Model: {report['model']}",
        f"- Overall: {report['overall_pass_rate']:.1%}",
        f"- Gate: {'PASS' if report['gate_passed'] else 'FAIL'}", "",
        "| Suite | Passed | Total | Rate | Latency |", "|---|---:|---:|---:|---:|",
    ]
    for suite in report["suites"]:
        lines.append(
            f"| {suite['suite']} | {suite['passed']} | {suite['cases']} | "
            f"{suite['pass_rate']:.1%} | {suite['latency_ms']} ms |"
        )
    failures = [
        (suite["suite"], case) for suite in report["suites"]
        for case in suite["results"] if not case["passed"]
    ]
    if failures:
        lines.extend(["", "## Failed cases", ""])
        for suite, case in failures:
            lines.append(f"### {suite} / {case['id']}")
            lines.append("")
            for item in case["checks"]:
                if not item["passed"]:
                    lines.append(f"- `{item['name']}`: {item['detail']}")
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Mission Control AI offline evaluation harness")
    parser.add_argument("--suite", choices=(*SUITES, "all"), default="all")
    parser.add_argument("--live", action="store_true", help="Use configured OpenAI model")
    parser.add_argument("--no-gate", action="store_true", help="Report failures without non-zero exit")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    if args.live and not application_settings.openai_api_key:
        parser.error("--live requires OPENAI_API_KEY")

    suites = SUITES if args.suite == "all" else (args.suite,)
    with tempfile.TemporaryDirectory(prefix="mission-control-eval-") as directory:
        eval_settings = EvalSettings(
            database_path=Path(directory) / "eval.db",
            openai_api_key=application_settings.openai_api_key if args.live else None,
            openai_model=application_settings.openai_model if args.live else "local-fallback",
        )
        original_db_settings, original_ai_settings = db.settings, ai.settings
        db.settings = eval_settings
        ai.settings = eval_settings
        try:
            db.init_db()
            suite_reports = [execute_suite(suite) for suite in suites]
        finally:
            db.settings = original_db_settings
            ai.settings = original_ai_settings

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "live" if args.live else "offline-fallback",
        "model": eval_settings.openai_model,
        "prompt_versions": {
            "planning": ai.PLAN_PROMPT_VERSION, "teaching": ai.TEACHING_PROMPT_VERSION,
            "assessment": ai.ASSESS_PROMPT_VERSION,
        },
        "suites": suite_reports,
    }
    baseline = json.loads((ROOT / "baseline.json").read_text(encoding="utf-8"))
    gate_passed, failures = evaluate_gate(report, baseline)
    report["gate_passed"], report["gate_failures"] = gate_passed, failures
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "latest.md").write_text(markdown_report(report), encoding="utf-8")
    print(markdown_report(report))
    return 0 if gate_passed or args.no_gate else 1


if __name__ == "__main__":
    sys.exit(main())
