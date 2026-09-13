import os
import re
import json

from dotenv import load_dotenv
from openai import OpenAI


LEARNING_TREE_FILE = "memory_data/learning_tree.md"
PROJECT_LEARNING_FILE = "memory_data/project_learning.md"


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60
)


def safe_read(filepath):
    if not os.path.exists(filepath):
        return ""

    with open(filepath, "r", encoding="utf-8") as file:
        return file.read()


def safe_write(filepath, text):
    folder = os.path.dirname(filepath)

    if folder:
        os.makedirs(folder, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as file:
        file.write(text)


def load_learning_tree_text():
    return safe_read(LEARNING_TREE_FILE)


def load_project_learning_text():
    return safe_read(PROJECT_LEARNING_FILE)


def parse_learning_tree():
    tree = {}
    current_category = None

    text = load_learning_tree_text()
    lines = text.splitlines()

    for line in lines:
        line = line.strip()

        if line.startswith("## "):
            current_category = line.replace("## ", "").strip()
            tree[current_category] = []

        elif line.startswith("[") and current_category:
            match = re.match(
                r"\[(\d)\]\[(.*?)\]\[(.*?)\]\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*)",
                line
            )

            if match:
                level = int(match.group(1))
                priority = match.group(2).strip()
                status = match.group(3).strip()
                name = match.group(4).strip()
                goal = match.group(5).strip()
                next_step = match.group(6).strip()

                tree[current_category].append({
                    "category": current_category,
                    "name": name,
                    "level": level,
                    "priority": priority,
                    "status": status,
                    "goal": goal,
                    "next_step": next_step
                })

    return tree


def get_recommended_learning_items(max_items=3):
    tree = parse_learning_tree()
    items = []

    for category, skills in tree.items():
        for skill in skills:
            status = skill["status"].lower()

            if status in ["done", "paused"]:
                continue

            if skill["level"] <= 2:
                items.append(skill)

    priority_order = {
        "HIGH": 0,
        "MEDIUM": 1,
        "LOW": 2
    }

    items.sort(
        key=lambda item: (
            priority_order.get(item["priority"], 99),
            item["level"]
        )
    )

    return items[:max_items]


def format_recommended_learning_items(max_items=3):
    items = get_recommended_learning_items(max_items)

    if not items:
        return "No recommended learning items."

    lines = []

    for item in items:
        lines.append(
            f"- {item['category']} | "
            f"{item['name']} | "
            f"Level {item['level']} | "
            f"{item['priority']} | "
            f"{item['status']} | "
            f"Next: {item['next_step']}"
        )

    return "\n".join(lines)


def extract_json(text):
    text = text.strip()

    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()

    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response.")

    return text[start:end + 1]


def generate_tree_patch(latest_review, news_analysis):
    learning_tree = load_learning_tree_text()
    project_learning = load_project_learning_text()

    prompt = f"""
You are the learning tree patch generator for my Mission Control AI system.

Your job is to decide whether memory_data/learning_tree.md should be updated based on:
- yesterday review
- today's news analysis
- current learning tree
- current project learning status

You must NOT generate today's plan.
You must NOT recommend today's tasks.
You must only generate a minimal JSON patch.

================ INPUT CONTEXT ================

[Yesterday Review]
{latest_review}

[Today News Analysis]
{news_analysis}

[Current Learning Tree]
{learning_tree}

[Current Project Learning Status]
{project_learning}

================ PATCH RULES ================

Only suggest a patch if there is clear evidence.

Good reasons to update:
1. Review says I completed a knowledge point.
2. Review says I struggled with a knowledge point.
3. News reveals a concrete important topic related to AI, systems, robotics, CV, hardware, or job search.
4. Project status shows a new required skill.
5. A topic already exists in the tree and should move from BACKLOG to ACTIVE.

Do not update just because a topic is interesting.
Do not duplicate existing knowledge points.
Do not change Status to Done unless the review gives clear evidence.
Do not add broad topics like "AI", "Transformer", or "Robotics".
Use small knowledge units only.

Prefer "replace" when an existing line already exists.
Use "add_after_category" only when the knowledge point does not exist.

================ OUTPUT RULES ================

Only output valid JSON.
No markdown.
No explanation.
No comments.

JSON format:

{{
  "should_update": true,
  "summary": "short reason",
  "changes": [
    {{
      "type": "replace",
      "old_line": "[0][MEDIUM][BACKLOG] OpenCV 5 New Features | 跟进行业工具升级 | 阅读Release Note记录3点",
      "new_line": "[0][MEDIUM][ACTIVE] OpenCV 5 New Features | 跟进行业工具升级 | 阅读官方发布说明, 记录重要特性及应用场景"
    }},
    {{
      "type": "add_after_category",
      "category": "Computer Vision & Robotics",
      "new_line": "[0][MEDIUM][BACKLOG] Robotics Game Engine | 了解机器人游戏引擎工具链 | 理解机器人开发标准化与模块化趋势"
    }}
  ]
}}

If no update is needed, output:

{{
  "should_update": false,
  "summary": "No clear evidence to update learning_tree.md.",
  "changes": []
}}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    return response.output_text


def preview_tree_patch(patch_text):
    try:
        patch_json = extract_json(patch_text)
        patch = json.loads(patch_json)
    except Exception as error:
        return f"Invalid patch JSON: {error}\n\nRaw response:\n{patch_text}"

    if not patch.get("should_update"):
        return "No learning tree update needed."

    lines = []
    lines.append(f"Summary: {patch.get('summary', '')}")
    lines.append("")
    lines.append("Changes:")

    for index, change in enumerate(patch.get("changes", []), start=1):
        change_type = change.get("type")

        lines.append(f"\n{index}. Type: {change_type}")

        if change_type == "replace":
            lines.append(f"Old: {change.get('old_line', '')}")
            lines.append(f"New: {change.get('new_line', '')}")

        elif change_type == "add_after_category":
            lines.append(f"Category: {change.get('category', '')}")
            lines.append(f"New: {change.get('new_line', '')}")

        else:
            lines.append(f"Unsupported change type: {change_type}")

    return "\n".join(lines)


def apply_tree_patch(patch_text):
    patch_json = extract_json(patch_text)
    patch = json.loads(patch_json)

    if not patch.get("should_update"):
        return "No learning tree update applied."

    text = load_learning_tree_text()
    changes = patch.get("changes", [])
    applied_count = 0
    failed_changes = []

    for change in changes:
        change_type = change.get("type")

        if change_type == "replace":
            old_line = change.get("old_line", "")
            new_line = change.get("new_line", "")

            if old_line and old_line in text:
                text = text.replace(old_line, new_line, 1)
                applied_count += 1
            else:
                failed_changes.append(f"Old line not found: {old_line}")

        elif change_type == "add_after_category":
            category = change.get("category", "")
            new_line = change.get("new_line", "")

            category_header = f"## {category}"

            if category_header not in text:
                failed_changes.append(f"Category not found: {category}")
                continue

            lines = text.splitlines()
            output_lines = []
            inserted = False

            for index, line in enumerate(lines):
                output_lines.append(line)

                if line.strip() == category_header and not inserted:
                    output_lines.append(new_line)
                    inserted = True
                    applied_count += 1

            text = "\n".join(output_lines) + "\n"

        else:
            failed_changes.append(f"Unsupported change type: {change_type}")

    safe_write(LEARNING_TREE_FILE, text)

    if failed_changes:
        return (
            f"Applied {applied_count} change(s), "
            f"but {len(failed_changes)} change(s) failed:\n"
            + "\n".join(failed_changes)
        )

    return f"Applied {applied_count} learning tree change(s)."