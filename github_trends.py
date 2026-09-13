from datetime import datetime, timedelta
import os

from dotenv import load_dotenv
from openai import OpenAI
import requests

from profile import build_user_profile


GITHUB_API_BASE = "https://api.github.com"
SEARCH_TOPICS = [
    "llm",
    "ai-agent",
    "rag",
    "computer-vision",
    "robotics",
]


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60
)


def build_github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MissionControlAI/1.0",
    }

    token = os.getenv("GITHUB_TOKEN")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def fetch_github_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=build_github_headers(),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def search_recent_repositories(days=14, per_topic=5):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    repositories = {}

    for topic in SEARCH_TOPICS:
        query = f"topic:{topic} created:>={since} stars:>20"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_topic,
        }

        try:
            data = fetch_github_json(
                f"{GITHUB_API_BASE}/search/repositories",
                params=params,
            )
        except Exception as error:
            print(f"GitHub trend search failed for {topic}: {error}")
            continue

        for repo in data.get("items", []):
            repositories[repo["full_name"]] = repo

    return sorted(
        repositories.values(),
        key=lambda repo: (
            repo.get("stargazers_count", 0),
            repo.get("forks_count", 0),
        ),
        reverse=True,
    )


def format_repository_candidates(repositories, max_items=10):
    if not repositories:
        return "No GitHub trend candidates found."

    lines = []

    for repo in repositories[:max_items]:
        topics = ", ".join(repo.get("topics", [])[:8])
        lines.append(
            f"- {repo['full_name']} | "
            f"Stars: {repo.get('stargazers_count', 0)} | "
            f"Forks: {repo.get('forks_count', 0)} | "
            f"Language: {repo.get('language') or 'Unknown'} | "
            f"Topics: {topics}\n"
            f"  Description: {repo.get('description') or ''}\n"
            f"  URL: {repo.get('html_url')}"
        )

    return "\n".join(lines)


def fetch_repository_root_files(full_name):
    try:
        data = fetch_github_json(f"{GITHUB_API_BASE}/repos/{full_name}/contents")
    except Exception as error:
        return f"Could not fetch repository file tree: {error}"

    lines = []

    for item in data[:40]:
        item_type = item.get("type", "file")
        name = item.get("name", "")
        lines.append(f"- {item_type}: {name}")

    return "\n".join(lines)


def fetch_repository_readme(full_name, max_chars=6000):
    try:
        response = requests.get(
            f"{GITHUB_API_BASE}/repos/{full_name}/readme",
            headers={
                **build_github_headers(),
                "Accept": "application/vnd.github.raw",
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as error:
        return f"Could not fetch README: {error}"

    return response.text[:max_chars]


def choose_repository_for_learning(repositories):
    if not repositories:
        return None

    preferred_languages = {
        "Python": 4,
        "TypeScript": 3,
        "JavaScript": 3,
        "Jupyter Notebook": 2,
        "C++": 2,
    }

    def score(repo):
        language_score = preferred_languages.get(repo.get("language"), 1)
        topic_text = " ".join(repo.get("topics", [])).lower()
        goal_score = 0

        for keyword in ["agent", "llm", "rag", "robot", "vision", "inference"]:
            if keyword in topic_text:
                goal_score += 2

        return (
            language_score * 20
            + goal_score
            + min(repo.get("stargazers_count", 0), 1000) / 20
            + min(repo.get("forks_count", 0), 300) / 10
        )

    return max(repositories, key=score)


def analyze_github_trends(repositories, selected_repo, root_files, readme_text):
    prompt = f"""
You are my Mission Control AI GitHub trend analyst.

Your job is to turn GitHub repository signals into one concrete learning target.

================ MY BACKGROUND ================
{build_user_profile()}

================ GITHUB TREND CANDIDATES ================
{format_repository_candidates(repositories)}

================ SELECTED REPOSITORY ================
{selected_repo.get('full_name') if selected_repo else 'None'}
{selected_repo.get('html_url') if selected_repo else ''}

================ SELECTED ROOT FILES ================
{root_files}

================ SELECTED README EXCERPT ================
{readme_text}

================ OUTPUT FORMAT ================

================ GITHUB TREND BRIEF ================

[Trend Signal]
3 bullet points. Explain what is becoming popular and why it matters.

[Recommended Project]
Repository:
Why this project:
Why it fits my goals:
Risk / limitation:

[Architecture Reading]
Explain the architecture from the README and file tree only.
Use this structure:
- Entry points:
- Core modules:
- Data / model flow:
- External dependencies:
- What to inspect first:

[Learning Plan]
Give a 60-90 minute learning plan.
Every step must be concrete and observable.

[Resume / Project Inspiration]
Explain how I can borrow ideas for Mission Control AI without copying code.

================ RULES ================
1. Do not pretend you read files that are not in the README or root tree.
2. If architecture is unclear, say exactly what needs to be opened next.
3. Prefer practical engineering insight over hype.
4. Keep the output concise.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )

    return response.output_text


def get_github_trend_analysis():
    repositories = search_recent_repositories()

    if not repositories:
        return "No GitHub trends available today. GitHub search returned no usable repositories."

    selected_repo = choose_repository_for_learning(repositories)
    full_name = selected_repo["full_name"]
    root_files = fetch_repository_root_files(full_name)
    readme_text = fetch_repository_readme(full_name)

    return analyze_github_trends(
        repositories=repositories,
        selected_repo=selected_repo,
        root_files=root_files,
        readme_text=readme_text,
    )
