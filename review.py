from datetime import datetime


def get_review_input():
    print("\n========== Daily Review ==========\n")

    completed = input("今天完成了什么？\n> ")
    blocked = input("今天最大的阻碍是什么？\n> ")
    tomorrow = input("明天最重要的一件事是什么？\n> ")

    review = f"""
Date: {datetime.now().strftime("%Y-%m-%d")}

Completed:
{completed}

Biggest Obstacle:
{blocked}

Tomorrow's Priority:
{tomorrow}
"""

    return review