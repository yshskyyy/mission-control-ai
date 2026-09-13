# Mission Control AI

一个基于学习证据持续调整计划的个人学习助手：

```text
创建目标 → 四周计划 → 今日任务 → 提交证据 → 逐项评估 → 每周复盘 → 新计划版本
```

## MVP 功能

- 创建带截止日期、每周时间预算和期望产出的学习目标
- 生成四周任务，每项任务包含耗时、产出和验收标准
- 展示当前最优先的三个任务及进度
- 提交文字证据和可选 GitHub/Commit 链接
- 按验收标准返回结构化评分和修改建议
- 生成每周复盘，确认后创建新计划版本
- 记录模型、Prompt 版本、状态、延迟和错误
- 没有 OpenAI API Key 时自动使用确定性本地降级，完整闭环仍可演示

## 技术结构

```text
Browser (HTML/CSS/JS)
        │ REST
FastAPI modular monolith
  ├── API / validation
  ├── planning & assessment services
  ├── LLM gateway + local fallback
  └── repository
        │
      SQLite
```

当前版本刻意保持模块化单体。LangGraph、消息队列和 PostgreSQL 会在出现长期工作流、异步负载或并发需求后引入，避免 MVP 阶段制造无效复杂度。

## 本地运行

要求 Python 3.12+。

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000>。API 文档位于 <http://127.0.0.1:8000/docs>。

`.env` 中的 `OPENAI_API_KEY` 可留空，此时系统使用本地降级逻辑。

## Docker 运行

```bash
docker compose up --build
```

打开 <http://127.0.0.1:8000>。SQLite 数据保存在 `memory_data/`，不会进入 Git。

## 验证

```bash
make test
make check
```

测试覆盖目标和计划创建、时间预算约束、证据评估、任务状态、周复盘版本更新和输入校验。

## 数据与安全

- `.env`、数据库、虚拟环境和运行产物已排除在 Git 外
- AI 不会声称访问用户提交的外部链接；MVP 只评估文本中提供的证据
- 业务事实保存在关系表中，模型输出先经过严格 JSON Schema 校验
- 计划更新创建新版本，不覆盖旧版本

## 旧版 CLI

仓库保留了最初的 CLI 原型，用于展示项目演进历史：

```bash
python main.py morning
python main.py review
python main.py build-tree
python main.py history
```

Web MVP 的入口是 `app.main:app`，旧版 CLI 与新版表结构可以共存。
