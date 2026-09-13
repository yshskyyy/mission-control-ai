import feedparser
import requests


RSS_SOURCES = {
    "AI": "https://hnrss.org/newest?q=AI",
    "Robotics": "https://hnrss.org/newest?q=robotics",
    "Computer Vision": "https://hnrss.org/newest?q=computer%20vision",
    "NVIDIA": "https://hnrss.org/newest?q=NVIDIA",
}


def fetch_news_from_rss(source_name, rss_url, limit=2):
    print(f"开始抓取: {source_name}")

    try:
        response = requests.get(
            rss_url,
            timeout=10,
            headers={
                "User-Agent": "MissionControlAI/1.0"
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(response.text)

        news_list = []

        for entry in feed.entries[:limit]:
            news_item = {
                "source": source_name,
                "title": entry.get("title", ""),
                "link": entry.get("link", "")
            }

            news_list.append(news_item)

        print(f"完成抓取: {source_name}, 共 {len(news_list)} 条")
        return news_list

    except requests.exceptions.Timeout:
        print(f"抓取超时: {source_name}")
        return []

    except requests.exceptions.RequestException as e:
        print(f"网络请求失败: {source_name}, 原因: {e}")
        return []

    except Exception as e:
        print(f"解析失败: {source_name}, 原因: {e}")
        return []


def remove_duplicate_news(news_list):
    seen = set()
    result = []

    for item in news_list:
        if item["title"] not in seen:
            seen.add(item["title"])
            result.append(item)

    return result


def get_today_news():
    all_news = []

    for source_name, rss_url in RSS_SOURCES.items():
        try:
            news = fetch_news_from_rss(source_name, rss_url, limit=2)
            all_news.extend(news)
        except Exception as e:
            print(f"抓取 {source_name} 新闻失败: {e}")
            continue

    all_news = remove_duplicate_news(all_news)

    return all_news


def format_news(news_list):
    text = ""

    for item in news_list:
        text += f"- [{item['source']}] {item['title']}\n"
        text += f"  Link: {item['link']}\n"

    return text