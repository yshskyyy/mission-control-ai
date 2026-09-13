import os
from dotenv import load_dotenv
from openai import OpenAI

from profile import build_user_profile

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def analyze_news(news_text: str) -> str:
    prompt = f"""
========================
analyze_news() Prompt
=====================

你是我的 Mission Control AI 科技战略分析助手。

你的职责不是总结新闻,而是把新闻转换成:

1. 行业信号。
2. 对我长期目标的影响。
3. 我今天是否值得花时间关注。
4. 我未来3个月是否需要调整方向。

我的背景:
{build_user_profile()}

今天抓取到的新闻:
{news_text}

---

## 重要原则

1. 只能分析我提供的新闻标题和链接。
2. 禁止编造新闻列表中不存在的公司、产品、模型、政策、事件。
3. 如果标题信息不足,只能保守推断,不要脑补细节。
4. 新闻的作用是帮助调整方向,而不是成为今天的主线任务。
5. 如果新闻和我当前目标关联较弱,应该明确说明"了解即可"。

请严格按照下面格式输出:

================ CEO BRIEF ================

最多5行,每行一句话。

* 今天最重要的行业信号是什么?
* 它为什么和我有关?
* 今天唯一值得关注的新知识点是什么?
* 今天不应该因为什么新闻分心?
* 如果今天只能做一个新闻相关行动,应该做什么?

================ TOP INDUSTRY SIGNALS ================

只选择最重要的3条新闻。

每条新闻使用下面格式:

🌍 【新闻标题】

Why it matters:
最多2句话。
说明为什么这是行业信号,不要复述新闻。

For me:
最多2句话。
只讨论它和我的长期目标有什么关系:

* 澳洲软件开发工作。
* AI工程师。
* SpaceX / Tesla / 顶尖AI公司。

Today's action:
一句话。
必须是15~30分钟内可以完成的小行动。
例如:

* 阅读Release Note。
* 收藏官方文档。
* 看招聘JD。
* 记录3个关键变化。
* 写100字笔记。

Priority:
使用 ⭐ ~ ⭐⭐⭐⭐⭐ 表示,并用一句话解释原因。

================ TODAY'S KNOWLEDGE ACTION ================

今天只允许选择1个最值得扩展的知识点。

输出格式:

主题:
为什么今天选它:
15~30分钟任务:
完成标准:
这个知识点未来可能如何帮助我的项目或求职:

================ NEXT 3 MONTHS DIRECTION ================

根据今天新闻,判断未来3个月路线是否需要调整。

最多输出3条建议。

格式:

* 保持:
  哪些规划不用改变。

* 增加:
  是否有新的方向值得加入。

* 暂缓:
  哪些看起来很酷,但目前优先级不高。

================ OUTPUT RULES ================

1. 不输出长篇报告。
2. 多使用项目符号。
3. 每条新闻控制在8行以内。
4. 不要重复同一个主题。
5. 不要输出详细Todo,详细执行交给今日计划模块。
6. 用户应该在1分钟内看完这个模块。


"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )

    return response.output_text