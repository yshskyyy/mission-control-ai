SHORT_TERM_GOALS = """
近期目标：
1. 三个月内在澳洲找到软件开发/后端/AI相关工作
2. 整理现有的黑马点评项目
3. 做出 Mission Control AI 项目
4. 英语达到熟练交流,能应对面试和工作
"""

LONG_TERM_GOALS = """
长期目标：
1. 进入 SpaceX/Tesla/顶尖AI公司
2. 成为懂 AI、C++、系统、机器人、计算机视觉、部署的工程师
"""

CURRENT_SKILLS = """
当前基础：
1. Java Spring Boot Redis MySQL
2. 学过机器学习,CNN,python
3. LeetCode约400题
4. 正在学习Transformer和GPT原理
5. 英语能基本对话,面试可能还不够
"""

CURRENT_STATUS = """
当前状态：
1.打算三天内完成mission- control-ai项目
2.在学习关于ai的知识
3.打算整理好项目到简历上
"""

PROJECT_PROGRESS = """
项目进度：
1. 黑马点评已完成基本内容,还差整理
2. Mission Control AI:已完成 V0.3,RSS + GPT 可运行
"""

LEARNING_FOCUS = """
当前学习重点：
1. AI Agent
2. Transformer / GPT 原理
3. Python AI 工程项目
4. 后端求职准备
"""


def build_user_profile():
    return f"""
{SHORT_TERM_GOALS}

{LONG_TERM_GOALS}

{CURRENT_SKILLS}

{CURRENT_STATUS}

{PROJECT_PROGRESS}

{LEARNING_FOCUS}
"""