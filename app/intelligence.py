import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
RSS_SOURCES = {
    "Hacker News AI": "https://hnrss.org/newest?q=AI%20engineering",
    "Hacker News Robotics": "https://hnrss.org/newest?q=robotics",
}


def _http_session() -> requests.Session:
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "MissionControlAI/2.0"})
    return session


def _external_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _keywords(text: str) -> set[str]:
    latin = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    stop = {"with", "from", "that", "this", "the", "and", "for", "一个", "学习", "完成"}
    words = {word for word in latin + chinese if word not in stop}
    aliases = {
        "分布式": {"distributed", "consensus", "raft"},
        "一致性": {"consensus", "raft"},
        "计算机视觉": {"computer", "vision", "image", "inference"},
        "前端": {"frontend", "react", "javascript", "typescript"},
        "智能体": {"agent", "workflow"},
        "知识图谱": {"knowledge", "graph"},
    }
    for phrase, related in aliases.items():
        if phrase in text:
            words.update(related)
    return words


def collect_github(days: int = 30, limit: int = 8) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "MissionControlAI/2.0"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    response = _http_session().get(
        GITHUB_SEARCH_URL,
        params={"q": f"created:>={since} stars:>50", "sort": "stars", "order": "desc",
                "per_page": limit},
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    result = []
    for repo in response.json().get("items", []):
        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)
        result.append({
            "source_type": "GITHUB", "external_id": str(repo["id"]),
            "source_name": "GitHub", "title": repo["full_name"],
            "url": repo["html_url"], "summary": repo.get("description") or "",
            "topics": repo.get("topics", [])[:10],
            "quality_score": min(100, 45 + stars // 100 + forks // 50),
            "trend_score": min(100, 50 + stars // 50),
            "published_at": repo.get("created_at"),
        })
    return result


def collect_news(limit_per_source: int = 4, errors: list[str] | None = None) -> list[dict]:
    result, session = [], _http_session()
    for source_name, url in RSS_SOURCES.items():
        try:
            response = session.get(url, timeout=12)
            response.raise_for_status()
            feed = feedparser.parse(response.text)
        except Exception as exc:
            if errors is not None:
                errors.append(f"{source_name}: {str(exc)[:160]}")
            continue
        for entry in feed.entries[:limit_per_source]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title:
                continue
            result.append({
                "source_type": "NEWS", "external_id": _external_id(link),
                "source_name": source_name, "title": title, "url": link,
                "summary": entry.get("summary", "")[:1000],
                "topics": sorted(_keywords(title))[:10],
                "quality_score": 60, "trend_score": 65,
                "published_at": entry.get("published"),
            })
    return result


def collect_signals() -> tuple[list[dict], list[str]]:
    items, errors = [], []
    try:
        items.extend(collect_github())
    except Exception as exc:
        errors.append(f"GitHub: {str(exc)[:180]}")
    items.extend(collect_news(errors=errors))
    deduplicated = {item["url"]: item for item in items}
    return list(deduplicated.values()), errors


def score_for_goal(item: dict, goal: dict, knowledge_nodes: Iterable[dict]) -> tuple[int, dict, str]:
    profile_text = " ".join([
        goal["title"], goal["current_level"], goal["desired_outcome"],
        goal.get("learning_preferences", ""),
        *[node["name"] + " " + node["description"] for node in knowledge_nodes],
    ])
    item_text = " ".join([item["title"], item.get("summary", ""), *item.get("topics", [])])
    profile_words, item_words = _keywords(profile_text), _keywords(item_text)
    overlap = profile_words & item_words
    relevance = min(100, 25 + len(overlap) * 18)
    gap = min(100, 45 + sum(node["mastery"] < 50 for node in knowledge_nodes) * 5)
    breakdown = {
        "goal_relevance": relevance,
        "knowledge_gap": gap,
        "practical_value": item["quality_score"],
        "trend_strength": item["trend_score"],
    }
    score = round(relevance * .4 + gap * .2 + item["quality_score"] * .25 + item["trend_score"] * .15)
    matched = "、".join(sorted(overlap)[:4]) or "长期技术成长"
    reason = f"与目标画像中的“{matched}”相关；综合项目质量、趋势强度和当前知识缺口评分。"
    return score, breakdown, reason
