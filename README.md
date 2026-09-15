# Mission Control AI

一个工程化的 AI 学习操作系统：围绕长期目标生成动态计划，以任务证据驱动评估和重排，用导师对话辅助学习，并从技术新闻和 GitHub 项目中形成个性化学习模块与知识图谱。

## 已实现功能

- 多用户注册、登录、Argon2 密码哈希、JWT 鉴权和目标级数据隔离
- 四周计划、今日任务、证据评估、周复盘和容量约束的动态重排
- Evidence-driven Teaching：结构化课程、章节进度、追问、换讲、测验、错题反馈、掌握度和完课状态
- GitHub/技术资讯采集、可解释推荐、接受/忽略决策和失败重试
- 推荐自动生成学习模块、扩展个人知识树并创建新版学习计划
- React + TypeScript 前端；React Flow 提供可缩放、拖拽的知识图谱
- PostgreSQL + SQLAlchemy Core + Alembic；SQLite 仅用于本地开发和测试
- Redis AOF + RQ 持久任务队列；LangGraph 提供推荐工作流检查点和恢复
- Sentry、OpenTelemetry OTLP、Prometheus `/metrics`
- 模型调用审计、离线 AI eval harness、pytest 和 GitHub Actions CI

完整结构见 [docs/architecture.md](docs/architecture.md)。

## 推荐运行方式：Docker Compose

```bash
cp .env.example .env
# 至少修改 JWT_SECRET；生产环境也要修改 POSTGRES_PASSWORD
docker compose up --build
```

打开 <http://127.0.0.1:8000>，先注册账户。API 文档在 <http://127.0.0.1:8000/docs>，Prometheus 指标在 <http://127.0.0.1:8000/metrics/>。

Compose 会启动 API、PostgreSQL、Redis、RQ worker 和趋势采集 scheduler，并在 API 启动前执行 Alembic migration。

## 本地开发

要求 Python 3.12+、Node 22+。不配置 `DATABASE_URL` 时使用 SQLite；不配置 `REDIS_URL` 时趋势刷新使用进程内任务。

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend ci
cp .env.example .env
python -m alembic upgrade head
npm --prefix frontend run build
python -m uvicorn app.main:app --reload
```

启用 Redis 后另行启动后台进程：

```bash
make queue-worker
make worker
```

## 关键配置

- `DATABASE_URL`: 生产使用 `postgresql+psycopg://...`
- `REDIS_URL`: RQ/Redis 地址
- `JWT_SECRET`: 至少 32 字符的随机密钥
- `OPENAI_API_KEY`, `OPENAI_MODEL`: 模型连接；留空使用 fallback
- `GITHUB_TOKEN`: 提升 GitHub API 限额
- `SENTRY_DSN`: 开启错误上报
- `OTEL_EXPORTER_OTLP_ENDPOINT`: 开启 OTLP trace 导出
- `AUTH_DISABLED=true`: 仅本地演示/测试使用

未配置 `OPENAI_API_KEY` 时，Teaching 使用确定性本地演示逻辑：固定生成三个递进章节，
并用有限的白话、类比、例子和逐步讲解策略完成追问与重讲。它可以完整演示追问、答错、
重讲、重新测验、mastery 更新和完课，但只用于验证工程闭环，不代表真实 LLM 的语义理解、
评分能力或教学质量。Teaching 页面会明确显示 provider、model、Prompt version 和 fallback 状态。

学习目标使用每天可用小时、ISO 学习日（1 表示周一、7 表示周日）和 IANA timezone 排期。
`study_days_per_week` 由具体学习日数量推导。旧 `weekly_hours` 数据保留原值，并按“优先五个工作日、
保持原周预算不变”的确定规则补齐新字段；API 的 `budget_derivation` 会说明采用的兼容方式。

## 自动验证

```bash
make test
make eval
make frontend-check
make frontend-build
make check
docker compose config -q
```

测试覆盖后端业务、Teaching Agent 和异步可靠性，并包含 22 个计划、Teaching、评估及推荐质量案例。详见 [docs/evaluation.md](docs/evaluation.md)。

## 手工验收路径

1. 注册两个账户，各自创建目标，确认无法读取对方数据。
2. 生成计划，在“今日”提交证据，检查评分和任务状态。
3. 开启 Teaching 连续追问，检查回答是否引用当前任务上下文。
4. 刷新趋势推荐，观察 job 进入 `COMPLETED`。
5. 接受推荐，确认学习模块、知识图谱和新计划版本同步出现。
6. 拖拽、缩放知识图谱，检查节点及先修关系。
7. 查看 `/metrics/`，配置后检查 Sentry 和 OTLP 后端收到数据。
