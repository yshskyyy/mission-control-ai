import json
import time
from typing import Any

from openai import OpenAI

from app.config import settings
from app import repository


PLAN_PROMPT_VERSION = "plan-v1"
ASSESS_PROMPT_VERSION = "assessment-v1"


def _client() -> OpenAI | None:
    return OpenAI(api_key=settings.openai_api_key, timeout=60) if settings.openai_api_key else None


def _structured_call(run_type: str, entity_id: str, prompt_version: str, prompt: str,
                     schema_name: str, schema: dict[str, Any]) -> dict | None:
    client = _client()
    if not client:
        repository.save_ai_run(run_type, entity_id, "FALLBACK", "local", prompt_version)
        return None
    started = time.monotonic()
    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=prompt,
            text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        )
        result = json.loads(response.output_text)
        repository.save_ai_run(
            run_type, entity_id, "SUCCEEDED", settings.openai_model, prompt_version,
            int((time.monotonic() - started) * 1000),
        )
        return result
    except Exception as exc:
        repository.save_ai_run(
            run_type, entity_id, "FAILED", settings.openai_model, prompt_version,
            int((time.monotonic() - started) * 1000), str(exc)[:500],
        )
        return None


def generate_plan(goal: dict) -> tuple[str, list[dict], str]:
    task_schema = {
        "type": "object",
        "properties": {
            "rationale": {"type": "string"},
            "tasks": {
                "type": "array", "minItems": 8, "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "week_number": {"type": "integer", "minimum": 1, "maximum": 4},
                        "title": {"type": "string"}, "description": {"type": "string"},
                        "estimated_minutes": {"type": "integer", "minimum": 20, "maximum": 240},
                        "deliverable": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "minItems": 2, "maxItems": 4,
                                                "items": {"type": "string"}},
                    },
                    "required": ["week_number","title","description","estimated_minutes","deliverable","acceptance_criteria"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["rationale", "tasks"], "additionalProperties": False,
    }
    prompt = f"""为个人学习者制定四周可执行计划。目标：{goal['title']}；当前水平：{goal['current_level']}；
期望产出：{goal['desired_outcome']}；截止日期：{goal['deadline']}；每周时间预算：{goal['weekly_hours']}小时；
偏好：{goal['learning_preferences']}。任务必须有可提交产物和客观验收标准，每周总时长不得超过预算。"""
    result = _structured_call("PLAN_GENERATION", goal["id"], PLAN_PROMPT_VERSION, prompt, "learning_plan", task_schema)
    if result:
        return result["rationale"], result["tasks"], settings.openai_model
    return _fallback_plan(goal) + ("local-fallback",)


def _fallback_plan(goal: dict) -> tuple[str, list[dict]]:
    subjects = [
        ("拆解目标与建立基线", "列出目标所需能力并完成一次基线自测", "能力差距清单"),
        ("掌握核心概念", "学习核心概念并用自己的语言解释", "概念说明文档"),
        ("完成最小实践", "实现一个最小可运行示例", "可运行代码与 README"),
        ("补充自动化测试", "覆盖主流程和一个失败场景", "测试代码与运行结果"),
        ("扩展真实场景", "把最小示例应用到一个真实问题", "功能演示记录"),
        ("分析失败与边界", "记录失败案例并实现错误处理", "失败案例与修复说明"),
        ("重构与工程化", "整理模块边界、配置和日志", "架构说明与重构提交"),
        ("综合项目冲刺", "将已学内容组合为可展示项目", "完整项目演示"),
        ("复盘知识缺口", "根据项目结果重新测试薄弱环节", "复盘与改进清单"),
        ("形成输出", "整理技术文章或项目讲解", "项目文章或讲解稿"),
        ("模拟评审", "按照验收目标评审并修复问题", "评审记录与修复提交"),
        ("最终验收", "演示成果并对照目标逐项验收", "最终演示与总结"),
    ]
    per_task = max(30, min(120, goal["weekly_hours"] * 60 // 3))
    tasks = []
    for index, (title, description, deliverable) in enumerate(subjects):
        tasks.append({
            "week_number": index // 3 + 1,
            "title": title,
            "description": f"围绕“{goal['title']}”：{description}。",
            "estimated_minutes": per_task,
            "deliverable": deliverable,
            "acceptance_criteria": [f"已提交{deliverable}", "内容能够被复查", "说明完成过程与遇到的问题"],
        })
    return "本地降级计划：按理解、实践、工程化、验收四个阶段推进。", tasks


def assess(task: dict, submission: dict) -> tuple[dict, str]:
    criteria = json.loads(task["acceptance_criteria"])
    schema = {
        "type": "object",
        "properties": {
            "result": {"type": "string", "enum": ["PASSED", "NEEDS_REVISION"]},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "feedback": {"type": "string"},
            "criterion_results": {"type": "array", "items": {"type": "object", "properties": {
                "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["criterion","passed","reason"], "additionalProperties": False}},
        },
        "required": ["result","score","feedback","criterion_results"], "additionalProperties": False,
    }
    prompt = f"""只依据用户提交的证据评估任务，不得假装访问链接。
任务：{task['title']}；说明：{task['description']}；产出：{task['deliverable']}；验收标准：{criteria}；
用户证据：{submission['evidence_text']}；仓库链接：{submission.get('repository_url') or '无'}。
逐条返回验收结果；证据不足必须判定未通过。"""
    result = _structured_call("ASSESSMENT", task["id"], ASSESS_PROMPT_VERSION, prompt, "task_assessment", schema)
    if result:
        return result, settings.openai_model
    evidence = submission["evidence_text"].strip()
    passed = len(evidence) >= 120 and any(word in evidence.lower() for word in ["test", "测试", "结果", "实现"])
    criterion_results = [{
        "criterion": criterion,
        "passed": passed,
        "reason": "提交包含可复查的实现与测试说明。" if passed else "证据过短或缺少实现/测试结果。",
    } for criterion in criteria]
    return {
        "result": "PASSED" if passed else "NEEDS_REVISION",
        "score": 80 if passed else 45,
        "feedback": "证据满足本地规则。" if passed else "请补充具体实现、测试命令与运行结果。",
        "criterion_results": criterion_results,
    }, "local-fallback"
