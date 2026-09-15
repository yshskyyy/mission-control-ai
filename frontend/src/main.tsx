import React, {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  Background,
  Controls,
  Edge,
  MiniMap,
  Node,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles.css";
import {
  beginSubmission,
  failSubmission,
  finishSubmission,
  shouldSubmitOnEnter,
} from "./submissionState";

type Json = Record<string, any>;
type View =
  | "today"
  | "plan"
  | "review"
  | "recommendations"
  | "knowledge"
  | "modules"
  | "runs";
const TOKEN_KEY = "mission-control-token";

async function api(path: string, options: RequestInit = {}): Promise<any> {
  const token = localStorage.getItem(TOKEN_KEY);
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event("auth-expired"));
  }
  if (!response.ok) {
    let message = "请求失败";
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}

function Auth({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [register, setRegister] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await api(register ? "/auth/register" : "/auth/login", {
        method: "POST",
        body: JSON.stringify(data),
      });
      localStorage.setItem(TOKEN_KEY, result.access_token);
      onAuthenticated();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <main className="auth">
      <section>
        <span className="eyebrow">PERSONAL LEARNING OS</span>
        <h1>Mission Control AI</h1>
        <p>用趋势信号、知识画像和学习证据持续校正你的成长路线。</p>
      </section>
      <form onSubmit={submit} className="auth-card">
        <h2>{register ? "创建账户" : "欢迎回来"}</h2>
        {register && (
          <label>
            昵称
            <input name="display_name" minLength={2} required />
          </label>
        )}
        <label>
          邮箱
          <input name="email" type="email" required />
        </label>
        <label>
          密码
          <input
            name="password"
            type="password"
            minLength={register ? 10 : 1}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button>{register ? "注册并登录" : "登录"}</button>
        <button
          type="button"
          className="link"
          onClick={() => setRegister(!register)}
        >
          {register ? "已有账户？登录" : "没有账户？注册"}
        </button>
      </form>
    </main>
  );
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <h2>{title}</h2>
          <button className="icon" onClick={onClose}>
            ×
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function App() {
  const [authenticated, setAuthenticated] = useState(
    !!localStorage.getItem(TOKEN_KEY),
  );
  const [goals, setGoals] = useState<Json[]>([]);
  const [goalId, setGoalId] = useState("");
  const [plan, setPlan] = useState<Json | null>(null);
  const [view, setView] = useState<View>("today");
  const [data, setData] = useState<any>(null);
  const [modal, setModal] = useState<{ kind: string; payload?: Json } | null>(
    null,
  );
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [teachingDraft, setTeachingDraft] = useState({ value: "", pending: false });
  const [quizDraft, setQuizDraft] = useState({ value: "", pending: false });
  const [evidenceDraft, setEvidenceDraft] = useState({ value: "", pending: false });
  const teachingInput = useRef<HTMLTextAreaElement>(null);
  const quizInput = useRef<HTMLTextAreaElement>(null);
  const evidenceInput = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const teachingPending = useRef(false);
  const quizPending = useRef(false);
  const evidencePending = useRef(false);
  const notify = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 3000);
  };
  const loadGoals = useCallback(async () => {
    const list = await api("/api/goals");
    setGoals(list);
    const selected = goalId || list[0]?.id || "";
    setGoalId(selected);
    if (selected) {
      try {
        setPlan(await api(`/api/goals/${selected}/plan`));
      } catch {
        setPlan(null);
      }
    }
  }, [goalId]);
  useEffect(() => {
    const logout = () => setAuthenticated(false);
    window.addEventListener("auth-expired", logout);
    return () => window.removeEventListener("auth-expired", logout);
  }, []);
  useEffect(() => {
    if (authenticated) loadGoals().catch((e) => notify(e.message));
  }, [authenticated]);
  useEffect(() => {
    if (!goalId) return;
    (async () => {
      try {
        if (view === "today")
          setData(await api(`/api/today?goal_id=${goalId}`));
        else if (view === "recommendations")
          setData(await api(`/api/goals/${goalId}/recommendations`));
        else if (view === "knowledge")
          setData(await api(`/api/goals/${goalId}/knowledge-tree`));
        else if (view === "modules")
          setData(await api(`/api/goals/${goalId}/learning-modules`));
        else if (view === "runs") setData(await api("/api/internal/ai-runs"));
        else setData(null);
      } catch (e) {
        notify((e as Error).message);
      }
    })();
  }, [view, goalId, plan]);
  if (!authenticated)
    return <Auth onAuthenticated={() => setAuthenticated(true)} />;
  const goal = goals.find((g) => g.id === goalId);
  const pending = plan?.tasks?.filter((t: Json) => t.status !== "PASSED") || [];
  async function createGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const body: Json = Object.fromEntries(new FormData(event.currentTarget));
      const form = new FormData(event.currentTarget);
      body.daily_hours = Number(body.daily_hours);
      body.study_weekdays = form.getAll("study_weekdays").map(Number);
      body.study_days_per_week = body.study_weekdays.length;
      const created = await api("/api/goals", {
        method: "POST",
        body: JSON.stringify(body),
      });
      await api(`/api/goals/${created.id}/generate-plan`, { method: "POST" });
      setGoalId(created.id);
      setModal(null);
      await loadGoals();
      notify("目标和计划已创建");
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function startTask(id: string) {
    await api(`/api/tasks/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: "IN_PROGRESS" }),
    });
    await loadGoals();
  }
  async function evidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const started = beginSubmission({ ...evidenceDraft, pending: evidencePending.current });
    if (!started) return;
    evidencePending.current = true;
    const fd = new FormData(event.currentTarget), id = modal?.payload?.id;
    setEvidenceDraft(started.next);
    evidenceInput.current?.focus();
    try {
      await api(`/api/tasks/${id}/submissions`, {
        method: "POST",
        body: JSON.stringify({
          evidence_text: started.sent,
          actual_minutes: Number(fd.get("actual_minutes")),
          repository_url: null,
        }),
      });
      setEvidenceDraft((current) => finishSubmission(current.value));
      setModal(null);
      await loadGoals();
      notify("证据已评估");
    } catch (e) {
      setEvidenceDraft((current) => failSubmission(current.value, started.sent));
      notify(`证据提交失败：${(e as Error).message}`);
      evidenceInput.current?.focus();
    } finally {
      evidencePending.current = false;
    }
  }
  async function openTeaching(task: Json) {
    setBusy(true);
    try {
      const session = await api(`/api/tasks/${task.id}/teaching-sessions`, {
        method: "POST",
      });
      setModal({
        kind: "teaching",
        payload: { ...session, title: task.title },
      });
      setTeachingDraft(finishSubmission());
      setQuizDraft(finishSubmission());
    } finally {
      setBusy(false);
    }
  }
  function openEvidence(task: Json) {
    setEvidenceDraft(finishSubmission());
    setModal({ kind: "evidence", payload: task });
  }
  async function teaching(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const started = beginSubmission({ ...teachingDraft, pending: teachingPending.current });
    if (!started) return;
    teachingPending.current = true;
    setTeachingDraft(started.next);
    teachingInput.current?.focus();
    try {
      const session = await api(
        `/api/teaching-sessions/${modal?.payload?.id}/messages`,
        {
          method: "POST",
          body: JSON.stringify({ content: started.sent }),
        },
      );
      setTeachingDraft((current) => finishSubmission(current.value));
      setModal({
        kind: "teaching",
        payload: { ...session, title: modal?.payload?.title },
      });
    } catch (e) {
      setTeachingDraft((current) => failSubmission(current.value, started.sent));
      notify(`消息发送失败：${(e as Error).message}`);
    } finally {
      teachingPending.current = false;
      teachingInput.current?.focus();
    }
  }
  async function teachingAction(action: "reteach" | "quizzes" | "continue") {
    setBusy(true);
    try {
      const session = await api(
        `/api/teaching-sessions/${modal?.payload?.id}/${action}`,
        { method: "POST" },
      );
      setModal({ kind: "teaching", payload: { ...session, title: modal?.payload?.title } });
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function answerQuiz(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const activeQuiz = modal?.payload?.quizzes
      ?.filter((quiz: Json) => quiz.status === "ACTIVE")
      .at(-1);
    const started = beginSubmission({ ...quizDraft, pending: quizPending.current });
    if (!activeQuiz || !started) return;
    quizPending.current = true;
    setQuizDraft(started.next);
    quizInput.current?.focus();
    try {
      const session = await api(
        `/api/teaching-sessions/${modal?.payload?.id}/quizzes/${activeQuiz.id}/attempts`,
        {
          method: "POST",
          headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ answer: started.sent }),
        },
      );
      setQuizDraft((current) => finishSubmission(current.value));
      setModal({ kind: "teaching", payload: { ...session, title: modal?.payload?.title } });
    } catch (e) {
      setQuizDraft((current) => failSubmission(current.value, started.sent));
      notify(`测验提交失败：${(e as Error).message}`);
    } finally {
      quizPending.current = false;
      quizInput.current?.focus();
    }
  }

  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>, pending: boolean) {
    const shouldSubmit = shouldSubmitOnEnter(
      { key: event.key, shiftKey: event.shiftKey,
        isComposing: event.nativeEvent.isComposing || composing.current },
      pending,
      event.currentTarget.value,
    );
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current) {
      event.preventDefault();
      if (shouldSubmit) event.currentTarget.form?.requestSubmit();
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      const job = await api(`/api/goals/${goalId}/recommendations/refresh`, {
        method: "POST",
      });
      for (let i = 0; i < 60; i++) {
        const state = await api(`/api/ingestion-jobs/${job.id}`);
        if (state.status === "SUCCEEDED") {
          setData(await api(`/api/goals/${goalId}/recommendations`));
          notify(`生成 ${state.recommendations_created} 条推荐`);
          return;
        }
        if (state.status === "FAILED") throw new Error(state.error);
        await new Promise((r) => setTimeout(r, 500));
      }
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide(id: string, decision: string) {
    setBusy(true);
    try {
      await api(`/api/recommendations/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setData(await api(`/api/goals/${goalId}/recommendations`));
      await loadGoals();
      notify(decision === "ACCEPT" ? "学习模块已加入计划" : "已记录反馈");
    } finally {
      setBusy(false);
    }
  }
  const nav: [View, string][] = [
    ["today", "今日任务"],
    ["plan", "四周计划"],
    ["review", "每周复盘"],
    ["recommendations", "趋势推荐"],
    ["knowledge", "知识图谱"],
    ["modules", "学习模块"],
    ["runs", "运行记录"],
  ];
  return (
    <div className="app">
      <header className="topbar">
        <div>
          <span className="eyebrow">PERSONAL LEARNING OS</span>
          <h1>Mission Control AI</h1>
        </div>
        <div className="top-actions">
          <span className={busy ? "status busy" : "status"}>
            {busy ? "处理中" : "系统就绪"}
          </span>
          <button
            className="secondary"
            onClick={() => {
              localStorage.removeItem(TOKEN_KEY);
              setAuthenticated(false);
            }}
          >
            退出
          </button>
        </div>
      </header>
      <main className="shell">
        <aside>
          {nav.map(([key, label]) => (
            <button
              key={key}
              className={view === key ? "nav active" : "nav"}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
          <hr />
          <label>
            当前目标
            <select
              value={goalId}
              onChange={async (e) => {
                setGoalId(e.target.value);
                try {
                  setPlan(await api(`/api/goals/${e.target.value}/plan`));
                } catch {
                  setPlan(null);
                }
              }}
            >
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.title}
                </option>
              ))}
            </select>
          </label>
          <button onClick={() => setModal({ kind: "goal" })}>＋ 新目标</button>
        </aside>
        <section className="content">
          {!goal ? (
            <Empty onCreate={() => setModal({ kind: "goal" })} />
          ) : (
            <ViewContent
              view={view}
              goal={goal}
              plan={plan}
              pending={pending}
              data={data}
              startTask={startTask}
              openTeaching={openTeaching}
              openEvidence={openEvidence}
              refresh={refresh}
              decide={decide}
              reload={async () => {
                await loadGoals();
                setData(null);
              }}
            />
          )}
        </section>
      </main>
      {modal?.kind === "goal" && (
        <Modal title="创建学习目标" onClose={() => setModal(null)}>
          <form onSubmit={createGoal}>
            <label>
              目标名称
              <input name="title" required />
            </label>
            <label>
              当前水平
              <textarea name="current_level" required />
            </label>
            <label>
              期望产出
              <textarea name="desired_outcome" required />
            </label>
            <div className="row">
              <label>
                截止日期
                <input name="deadline" type="date" required />
              </label>
              <label>
                每天可用小时
                <input
                  name="daily_hours"
                  type="number"
                  min="0.5"
                  max="12"
                  step="0.5"
                  defaultValue="1.5"
                  required
                />
              </label>
            </div>
            <fieldset>
              <legend>每周学习日</legend>
              <div className="weekday-options">
                {["一", "二", "三", "四", "五", "六", "日"].map((label, index) => (
                  <label key={label}>
                    <input name="study_weekdays" type="checkbox" value={index + 1} defaultChecked={index < 5} />
                    周{label}
                  </label>
                ))}
              </div>
            </fieldset>
            <input name="timezone" type="hidden" value={Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai"} />
            <label>
              学习偏好
              <input name="learning_preferences" />
            </label>
            <button disabled={busy}>创建并生成计划</button>
          </form>
        </Modal>
      )}
      {modal?.kind === "evidence" && (
        <Modal
          title={`提交证据：${modal.payload?.title}`}
          onClose={() => setModal(null)}
        >
          <form onSubmit={evidence}>
            <label>
              实现与验证结果
              <textarea
                ref={evidenceInput}
                name="evidence_text"
                minLength={10}
                rows={7}
                required
                value={evidenceDraft.value}
                onChange={(event) => setEvidenceDraft((state) => ({ ...state, value: event.target.value }))}
              />
            </label>
            <label>
              实际耗时
              <input
                name="actual_minutes"
                type="number"
                min="1"
                defaultValue="60"
                required
              />
            </label>
            <button disabled={evidenceDraft.pending || !evidenceDraft.value.trim()}>
              {evidenceDraft.pending ? "提交中…" : "提交并评估"}
            </button>
          </form>
        </Modal>
      )}
      {modal?.kind === "teaching" && (
        <Modal
          title={`导师辅导：${modal.payload?.title}`}
          onClose={() => setModal(null)}
        >
          <div className="course-status">
            <strong>掌握度 {modal.payload?.mastery}%</strong>
            <span>已完成 {modal.payload?.lesson_progress}/{modal.payload?.sections?.length} 节</span>
            <span>{modal.payload?.status}</span>
          </div>
          <div className={modal.payload?.runtime?.fallback ? "runtime-banner fallback" : "runtime-banner"}>
            <strong>{modal.payload?.runtime?.fallback ? "本地演示模式：回复质量受限" : "OpenAI 教学模式"}</strong>
            <span>
              {modal.payload?.runtime?.provider || "local"} / {modal.payload?.runtime?.model || "local"}
              {modal.payload?.runtime?.prompt_version ? ` · ${modal.payload.runtime.prompt_version}` : ""}
            </span>
          </div>
          <ol className="lesson-outline">
            {modal.payload?.sections?.map((section: Json) => (
              <li key={section.id} className={section.id === modal.payload?.current_section_id ? "current" : ""}>
                <span>{section.position}. {section.title}</span>
                <small>{section.status} · mastery {section.mastery}%</small>
              </li>
            ))}
          </ol>
          <div className="messages">
            {modal.payload?.messages.map((m: Json) => (
              <article
                key={m.id}
                className={
                  m.role === "USER" ? "user-message" : "teacher-message"
                }
              >
                <strong>{m.role === "USER" ? "你" : "导师"}</strong>
                {m.teaching_strategy && <small>策略：{m.teaching_strategy}</small>}
                <p>{m.content}</p>
              </article>
            ))}
          </div>
          {modal.payload?.quiz_attempts?.length > 0 && (() => {
            const attempt = modal.payload!.quiz_attempts.at(-1);
            return (
              <section className={attempt.passed ? "quiz-result passed" : "quiz-result"}>
                <strong>最近评分：{attempt.score} 分</strong>
                <p>{attempt.feedback}</p>
                {attempt.weak_points?.length > 0 && <small>薄弱点：{attempt.weak_points.join("、")}</small>}
              </section>
            );
          })()}
          {modal.payload?.quizzes?.some((quiz: Json) => quiz.status === "ACTIVE") && (
            <form className="quiz-form" onSubmit={answerQuiz}>
              <strong>{modal.payload.quizzes.filter((quiz: Json) => quiz.status === "ACTIVE").at(-1).question}</strong>
              <textarea
                ref={quizInput}
                name="answer"
                required
                placeholder="写下你的答案和验证思路"
                value={quizDraft.value}
                onChange={(event) => setQuizDraft((state) => ({ ...state, value: event.target.value }))}
                onKeyDown={(event) => submitOnEnter(event, quizDraft.pending)}
                onCompositionStart={() => { composing.current = true; }}
                onCompositionEnd={() => { composing.current = false; }}
              />
              <button disabled={quizDraft.pending || !quizDraft.value.trim()}>
                {quizDraft.pending ? "提交中…" : "提交答案"}
              </button>
            </form>
          )}
          {modal.payload?.status !== "COMPLETED" && (
            <div className="teaching-actions">
              <button className="secondary" onClick={() => teachingAction("continue")}>继续学习</button>
              <button className="secondary" onClick={() => teachingAction("reteach")}>换种方式讲</button>
              <button onClick={() => teachingAction("quizzes")}>开始测验</button>
            </div>
          )}
          {modal.payload?.status === "COMPLETED" && (
            <div className="quiz-result passed">课程已完成，可以关闭窗口并返回任务页面提交证据。</div>
          )}
          <form className="chat-form" onSubmit={teaching}>
            <textarea
              ref={teachingInput}
              name="content"
              required
              placeholder="输入你的回答或问题"
              value={teachingDraft.value}
              onChange={(event) => setTeachingDraft((state) => ({ ...state, value: event.target.value }))}
              onKeyDown={(event) => submitOnEnter(event, teachingDraft.pending)}
              onCompositionStart={() => { composing.current = true; }}
              onCompositionEnd={() => { composing.current = false; }}
            />
            <button disabled={teachingDraft.pending || !teachingDraft.value.trim()}>
              {teachingDraft.pending ? "发送中…" : "发送"}
            </button>
          </form>
        </Modal>
      )}
      <div className={toast ? "toast show" : "toast"}>{toast}</div>
    </div>
  );
}

function Empty({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="hero panel">
      <span className="eyebrow">START HERE</span>
      <h2>建立你的长期学习系统</h2>
      <p>从目标、证据和技术趋势中构建可持续演进的个人知识图谱。</p>
      <button onClick={onCreate}>创建目标</button>
    </div>
  );
}

function ViewContent(p: any) {
  const { view, goal, plan, pending, data } = p;
  if (view === "today")
    return (
      <>
        <Heading eyebrow="TODAY" title={goal.title} />
        <div className="stats">
          <Stat
            n={`${plan?.tasks?.filter((t: Json) => t.status === "PASSED").length || 0}/${plan?.tasks?.length || 0}`}
            label="已通过任务"
          />
          <Stat
            n={`${data?.scheduled_hours || 0}/${goal.daily_hours}h`}
            label="今日预计学习"
          />
          <Stat n={`${goal.study_days_per_week} 天`} label="每周学习日" />
        </div>
        <div className="list">
          {(data?.tasks || []).map((t: Json) => (
            <Task key={t.id} task={t} {...p} />
          ))}
        </div>
      </>
    );
  if (view === "plan")
    return (
      <>
        <Heading
          eyebrow="ROADMAP"
          title={`四周计划 · v${plan?.version || "-"}`}
        />
        <div className="notice">{plan?.rationale}</div>
        {plan?.planning_risks?.map((risk: Json) => (
          <div className="notice risk" key={risk.code}>{risk.code}：{risk.message}</div>
        ))}
        {plan?.adjustment_suggestions?.length > 0 && (
          <div className="notice">建议：{plan.adjustment_suggestions.join("、")}</div>
        )}
        <div className="weeks">
          {[1, 2, 3, 4].map((w) => (
            <section className="panel week" key={w}>
              <h3>Week {w}</h3>
              {plan?.tasks
                ?.filter((t: Json) => t.week_number === w)
                .map((t: Json) => (
                  <div className="plan-task" key={t.id}>
                    <strong>{t.title}</strong>
                    <span>
                      {t.scheduled_date} · {t.estimated_minutes} 分钟 · {t.status}
                    </span>
                  </div>
                ))}
            </section>
          ))}
        </div>
      </>
    );
  if (view === "review") return <Review goal={goal} reload={p.reload} />;
  if (view === "recommendations")
    return (
      <>
        <Heading
          eyebrow="INTELLIGENCE"
          title="趋势推荐"
          action={<button onClick={p.refresh}>刷新技术信号</button>}
        />
        <div className="list">
          {(data || []).map((r: Json) => (
            <article className="panel recommendation" key={r.id}>
              <div>
                <span className="badge">{r.source_type}</span>
                <h3>{r.content_title}</h3>
                <p>{r.summary}</p>
                <small>{r.reason}</small>
                <div className="chips">
                  {Object.entries(r.score_breakdown).map(([k, v]) => (
                    <span key={k}>
                      {k} {String(v)}
                    </span>
                  ))}
                </div>
                <a href={r.url} target="_blank" rel="noreferrer">
                  原始来源 ↗
                </a>
              </div>
              <aside>
                <b>{r.score}</b>
                <span>匹配度</span>
                {r.status === "RECOMMENDED" && (
                  <>
                    <button onClick={() => p.decide(r.id, "ACCEPT")}>
                      生成模块
                    </button>
                    <button
                      className="secondary"
                      onClick={() => p.decide(r.id, "DISMISS")}
                    >
                      忽略
                    </button>
                  </>
                )}
              </aside>
            </article>
          ))}
        </div>
      </>
    );
  if (view === "knowledge") return <KnowledgeGraph tree={data} />;
  if (view === "modules")
    return (
      <>
        <Heading eyebrow="CURRICULUM" title="学习模块" />
        <div className="list">
          {(data || []).map((m: Json) => (
            <article className="panel module" key={m.id}>
              <div>
                <span className="badge">{m.status}</span>
                <h3>{m.title}</h3>
                <p>{m.rationale}</p>
              </div>
              <ol>
                {m.tasks.map((t: Json) => (
                  <li key={t.id}>
                    <strong>{t.title}</strong>
                    <span>
                      {t.estimated_minutes} 分钟 · {t.deliverable}
                    </span>
                  </li>
                ))}
              </ol>
            </article>
          ))}
        </div>
      </>
    );
  return (
    <>
      <Heading eyebrow="OBSERVABILITY" title="AI 运行记录" />
      <div className="panel table">
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>状态</th>
              <th>模型</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((r: Json) => (
              <tr key={r.id}>
                <td>{r.run_type}</td>
                <td>{r.status}</td>
                <td>{r.model}</td>
                <td>{r.latency_ms}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Heading({
  eyebrow,
  title,
  action,
}: {
  eyebrow: string;
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {action}
    </header>
  );
}
function Stat({ n, label }: { n: string; label: string }) {
  return (
    <div className="stat">
      <strong>{n}</strong>
      <span>{label}</span>
    </div>
  );
}
function Task({ task, startTask, openTeaching, openEvidence }: any) {
  return (
    <article className="panel task">
      <div>
        <span className="badge">{task.status}</span>
        <h3>{task.title}</h3>
        <small>
          第 {task.week_number} 周 · {task.estimated_minutes} 分钟 ·{" "}
          {task.deliverable}
        </small>
        <p>{task.description}</p>
      </div>
      <div className="task-actions">
        {task.status === "TODO" && (
          <button className="secondary" onClick={() => startTask(task.id)}>
            开始
          </button>
        )}
        <button className="secondary" onClick={() => openTeaching(task)}>
          导师辅导
        </button>
        <button onClick={() => openEvidence(task)}>提交证据</button>
      </div>
    </article>
  );
}
function Review({ goal, reload }: any) {
  const [review, setReview] = useState<Json | null>(null);
  async function create() {
    setReview(
      await api(`/api/goals/${goal.id}/weekly-reviews`, {
        method: "POST",
      }),
    );
  }
  async function decide(d: string) {
    await api(`/api/weekly-reviews/${review?.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision: d }),
    });
    setReview(null);
    await reload();
  }
  return (
    <>
      <Heading
        eyebrow="REFLECT"
        title="每周复盘"
        action={<button onClick={create}>生成复盘</button>}
      />
      {review && (
        <article className="panel module">
          <div>
            <h3>{review.summary}</h3>
            <p>{review.proposed_changes}</p>
          </div>
          <div>
            <button onClick={() => decide("ACCEPT")}>接受重排</button>
            <button className="secondary" onClick={() => decide("REJECT")}>
              保留计划
            </button>
          </div>
        </article>
      )}
    </>
  );
}
function KnowledgeGraph({ tree }: { tree: Json | null }) {
  const nodes: Node[] = useMemo(
    () =>
      (tree?.nodes || []).map((n: Json, i: number) => ({
        id: n.id,
        position: { x: (i % 4) * 230, y: Math.floor(i / 4) * 150 },
        data: { label: `${n.name} · ${n.mastery}%` },
        style: {
          border: `2px solid ${n.status === "MASTERED" ? "#58a76d" : "#1e5b42"}`,
          borderRadius: 14,
          padding: 12,
          background: "#fffdf7",
          width: 190,
        },
      })),
    [tree],
  );
  const edges: Edge[] = useMemo(
    () =>
      (tree?.edges || []).map((e: Json) => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        label: e.relation_type,
        animated: e.relation_type === "REQUIRES",
      })),
    [tree],
  );
  return (
    <>
      <Heading eyebrow="PROFILE GRAPH" title="交互式知识图谱" />
      <div className="graph panel">
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <MiniMap />
          <Controls />
        </ReactFlow>
      </div>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
