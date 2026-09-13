import os

from dotenv import load_dotenv
from openai import OpenAI

from profile import build_user_profile
from learning_manager import (
    load_learning_tree_text,
    load_project_learning_text,
    format_recommended_learning_items
)


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60
)


def generate_ai_plan(
    news_analysis: str,
    github_analysis: str,
    latest_review: str,
    latest_brief: str,
    available_hours: int = 10
) -> str:

    user_profile = build_user_profile()
    learning_tree = load_learning_tree_text()
    project_learning = load_project_learning_text()
    recommended_items = format_recommended_learning_items()

    prompt = f"""
You are my Mission Control AI personal planning assistant.

Your job is to generate a concrete, realistic, executable daily plan.

================ INPUT CONTEXT ================

[My Background]
{user_profile}

[Yesterday Review]
{latest_review}

[Yesterday Daily Brief]
{latest_brief}

[Today News Analysis]
{news_analysis}

[Today GitHub Trend Analysis]
{github_analysis}

[Current Long-Term Learning Tree]
{learning_tree}

[Current Project Learning Status]
{project_learning}

[System Recommended Learning Candidates]
{recommended_items}

[Available Time Today]
{available_hours} hours

================ PRIORITY RULES ================

Priority must strictly follow this order:

1. Mission Control AI project delivery
2. Job search, resume, GitHub, applications
3. English interview expression
4. Long-term technical capability
5. News-related knowledge expansion
6. GitHub trend project reading

News and GitHub trends can influence direction, but cannot hijack today's main mission.

================ KNOWLEDGE RULES ================

1. Choose knowledge points only from Learning Tree, Project Learning, or System Recommended Learning Candidates.
2. Do not invent new broad directions.
3. If Status = Done, do not assign basic learning tasks.
4. If Status = Learning, assign only its Next Action.
5. If Status = Paused, do not assign it today.
6. Each knowledge point must be a small knowledge unit.
7. Do not write broad tasks like "learn Transformer".

================ ANTI-REPETITION RULES ================

1. Read Yesterday Review and Yesterday Daily Brief before planning.
2. Do not repeat yesterday's tasks unless yesterday review shows they were unfinished.
3. Do not repeat yesterday's learning roadmap unless:
- it is required for today's project delivery
- it is a smaller next step
- yesterday review shows it was not completed
4. If yesterday had a broad task, convert it into a smaller concrete action today.
5. If yesterday's task was completed, do not assign the same task again.

================ TASK RULES ================

Each main task must include:
- filename
- exact action
- completion standard

Bad example:
- Optimize project structure.

Good example:
- Modify main.py, make morning flow call tree update suggestion before generate_ai_plan(). Done when morning mode runs without error.
- Modify planner.py, remove tree update suggestions from Learning Roadmap. Done when the output only contains today's learning tasks.
- Create memory_data/project_learning.md, record current Mission Control AI problems and next actions. Done when planner.py can read project status.

================ OUTPUT FORMAT ================

================ TODAY'S MISSION ================

[Today's Single Core Mission]
One sentence.

[Why Today]
Maximum 2 sentences.

[Estimated Time]
Example: 4 hours.

[Todo List]
Output 3-5 concrete steps using "-".
Each step must include filename, exact action, and completion standard.

[Completion Standard]
Use "[ ]".
Must be checkable.

================ LEARNING ROADMAP ================

Choose only 1-3 knowledge points worth learning today.
If project tasks are heavy, choose only 1.

For each item, use this format:

[Direction]
[Knowledge Point]
[Why Today]
[20-40 Minute Task]
[Completion Standard]
[Completion Evidence]

================ MISSION PROGRESS ================

[Australia Software Developer Job]
Current Stage:
Current Biggest Bottleneck:
Most Valuable Metric Today:

[AI Engineer Direction]
Current Stage:
Current Biggest Bottleneck:
Most Valuable Metric Today:

[SpaceX / Tesla Long-Term Goal]
Current Stage:
Current Biggest Bottleneck:
Most Valuable Metric Today:

================ THIS WEEK'S FOCUS ================

Give the 3 most important things to keep doing in the next 7 days.

================ NOT TODAY ================

List 3 things that should not be done today.

Format:
- What not to do.
Reason: Explain in one sentence why it is not worth today's time.

================ OUTPUT RULES ================

1. Do not repeat the news analysis.
2. Do not repeat the GitHub trend analysis.
3. Do not generate new news or fake GitHub repositories.
4. Do not output long paragraphs.
5. Do not assign more than 5 main tasks.
6. Do not assign tasks that cannot be completed today.
7. The output style should look like a personal dashboard, not an analysis report.
8. The user should know what to do today within 30 seconds.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    return response.output_text
