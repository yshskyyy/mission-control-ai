import os

from learning_manager import parse_learning_tree

OUTPUT_FILE = "output/learning_tree.html"


def get_status_class(level):
    if level >= 4:
        return "mastered"
    elif level >= 2:
        return "learning"
    else:
        return "not-started"


def generate_html(tree):
    cards_html = ""

    for category, skills in tree.items():
        skill_items = ""

        for skill in skills:
            status_class = get_status_class(skill["level"])

            skill_items += f"""
        <div class="skill {status_class}">
            <div class="skill-name">{skill['name']}</div>
            <div class="skill-meta">
                Level {skill['level']} / 5 · {skill['priority']} · {skill['status']}
            </div>
            <div class="skill-goal">
                Goal: {skill['goal']}
            </div>
            <div class="skill-next">
                Next: {skill['next_step']}
            </div>
        </div>
        """

        cards_html += f"""
        <section class="category-card">
            <h2>{category}</h2>
            <div class="skills">
                {skill_items}
            </div>
        </section>
        """

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Mission Knowledge Tree</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f172a;
            color: #e5e7eb;
            margin: 0;
            padding: 40px;
        }}

        h1 {{
            text-align: center;
            margin-bottom: 10px;
        }}

        .subtitle {{
            text-align: center;
            color: #94a3b8;
            margin-bottom: 40px;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
        }}

        .category-card {{
            background: #111827;
            border: 1px solid #334155;
            border-radius: 18px;
            padding: 22px;
            box-shadow: 0 12px 30px rgba(0,0,0,0.25);
        }}

        .category-card h2 {{
            margin-top: 0;
            font-size: 22px;
            color: #f8fafc;
        }}

        .skills {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .skill {{
            padding: 14px 16px;
            border-radius: 12px;
            border-left: 6px solid;
            background: #1f2937;
        }}

        .skill-name {{
            font-size: 16px;
            font-weight: 600;
        }}

        .skill-meta {{
            margin-top: 6px;
            font-size: 13px;
            color: #cbd5e1;
        }}
        .skill-goal {{
            margin-top: 8px;
            font-size: 13px;
            color: #cbd5e1;
        }}

        .skill-next {{
            margin-top: 6px;
            font-size: 13px;
            color: #93c5fd;
        }}

        .mastered {{
            border-left-color: #22c55e;
        }}

        .learning {{
            border-left-color: #eab308;
        }}

        .not-started {{
            border-left-color: #ef4444;
        }}

        .legend {{
            margin: 30px auto;
            text-align: center;
            color: #cbd5e1;
        }}
    </style>
</head>
<body>
    <h1>Mission Knowledge Tree</h1>
    <div class="subtitle">
        Personal skill map for AI + Systems + Robotics path
    </div>

    <div class="legend">
        🟢 Level 4-5 = mastered · 🟡 Level 2-3 = learning · 🔴 Level 0-1 = not started
    </div>

    <main class="grid">
        {cards_html}
    </main>
</body>
</html>
"""

    return html


def build_learning_tree_page():
    os.makedirs("output", exist_ok=True)

    tree = parse_learning_tree()
    html = generate_html(tree)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(html)

    print(f"Learning tree generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_learning_tree_page()