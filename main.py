import sys


def run_morning():
    from news import get_today_news, format_news
    from analyzer import analyze_news
    from github_trends import get_github_trend_analysis
    from planner import generate_ai_plan
    from memory import save_daily_brief, load_latest_review, load_latest_brief
    from learning_manager import (
        generate_tree_patch,
        preview_tree_patch,
        apply_tree_patch
    )

    available_hours = int(input("How many hours do you have today? "))

    latest_review = load_latest_review()
    latest_brief = load_latest_brief()

    news = get_today_news()
    news_text = format_news(news)

    news_analysis = analyze_news(news_text)
    github_analysis = get_github_trend_analysis()

    tree_patch = generate_tree_patch(
        latest_review=latest_review,
        news_analysis=news_analysis
    )

    print("\n================ Learning Tree Patch Preview ================\n")
    print(preview_tree_patch(tree_patch))

    answer = input("\nApply this learning tree patch? (y/n): ")

    if answer.lower() == "y":
        tree_update_result = apply_tree_patch(tree_patch)
    else:
        tree_update_result = "Skipped learning tree update."

    plan = generate_ai_plan(
        news_analysis=news_analysis,
        github_analysis=github_analysis,
        latest_review=latest_review,
        latest_brief=latest_brief,
        available_hours=available_hours
    )

    brief = f"""
================ Mission Control AI ================

[Today News]
{news_text}

[News Analysis]
{news_analysis}

[GitHub Trend Analysis]
{github_analysis}

[Learning Tree Update Result]
{tree_update_result}

[Today Plan]
{plan}

====================================================
"""

    save_daily_brief(
        brief,
        available_hours=available_hours,
        news=news_text,
        news_analysis=news_analysis,
        github_analysis=github_analysis,
        tree_update_result=tree_update_result,
        plan=plan,
    )
    print(brief)


def run_review():
    from review import get_review_input
    from memory import save_daily_review

    review = get_review_input()
    save_daily_review(review)
    print("Review saved successfully.")


def run_build_tree():
    from learning_tree_page import build_learning_tree_page

    build_learning_tree_page()


def run_db_init():
    from database import DATABASE_PATH, import_markdown_history

    briefs, reviews = import_markdown_history()
    print(f"Database ready: {DATABASE_PATH}")
    print(f"Imported {briefs} briefs and {reviews} reviews.")


def run_history():
    from database import DATABASE_PATH, list_recent_briefs

    rows = list_recent_briefs()
    print(f"Database: {DATABASE_PATH}")
    if not rows:
        print("No daily briefs saved yet.")
        return

    print("\nRecent daily briefs:")
    for row in rows:
        hours = row["available_hours"] if row["available_hours"] is not None else "-"
        print(f'- {row["brief_date"]} | available hours: {hours} | updated: {row["updated_at"]}')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"

    if mode == "morning":
        run_morning()

    elif mode == "review":
        run_review()

    elif mode == "build-tree":
        run_build_tree()

    elif mode == "db-init":
        run_db_init()

    elif mode == "history":
        run_history()

    else:
        print("Unknown mode.")
        print("Use:")
        print("python main.py morning")
        print("python main.py review")
        print("python main.py build-tree")
        print("python main.py db-init")
        print("python main.py history")


if __name__ == "__main__":
    main()
