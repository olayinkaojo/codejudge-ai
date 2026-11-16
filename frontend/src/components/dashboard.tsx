"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowRight,
  Braces,
  Clock3,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { createMutation } from "@/lib/mutation";
import { api, backend } from "@/lib/client";
import { readHistory } from "@/lib/history";
import type { Task } from "@/lib/types";
import { Dialog } from "./dialog";
import { useUsername } from "./workspace";
import { date, Empty, ErrorNotice, Loading, PageHeading } from "./ui";
export function Dashboard() {
  const username = useUsername();
  const mutation = useRef(createMutation());
  const [tasks, setTasks] = useState<Task[]>([]);
  const [historyCount, setHistoryCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [more, setMore] = useState(false);
  const load = useCallback(async () => {
    try {
      const rows = await api<Task[]>(`${backend}/tasks?limit=20&offset=0`);
      setError("");
      setTasks(rows);
      setMore(rows.length === 20);
      setHistoryCount(readHistory(username).length);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [username]);
  useEffect(() => {
    let active = true;
    api<Task[]>(`${backend}/tasks?limit=20&offset=0`)
      .then((rows) => {
        if (active) {
          setTasks(rows);
          setMore(rows.length === 20);
          setHistoryCount(readHistory(username).length);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [username]);
  async function loadMore() {
    setSaving(true);
    setError("");
    try {
      const rows = await api<Task[]>(
        `${backend}/tasks?limit=20&offset=${tasks.length}`,
      );
      setTasks((old) => [...old, ...rows]);
      setMore(rows.length === 20);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function create(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSaving(true);
    setFormError("");
    try {
      await mutation.current(`${backend}/tasks`, {
        title: data.get("title"),
        description: data.get("description"),
        max_score: Number(data.get("max_score")),
      });
      setCreating(false);
      await load();
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const visible = tasks.filter((task) =>
    `${task.title} ${task.description}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        eyebrow="A LITTLE PROGRESS, EVERY DAY"
        title="Your next solution starts here."
        description={`Welcome back, ${username}. Make room for a good challenge.`}
        action={
          <button
            className="button primary"
            onClick={() => {
              setCreating(true);
              setFormError("");
            }}
          >
            <Plus size={17} />
            New challenge
          </button>
        }
      />
      <section className="hero-banner">
        <div className="hero-copy">
          <span className="pill">
            <Sparkles size={13} />
            THE WORKSPACE FOR YOUR WHAT-IF
          </span>
          <h2>
            Less guesswork.
            <br />
            <span>More breakthroughs.</span>
          </h2>
          <p>
            Take an idea from first draft to thoughtful feedback.
            <br className="desktop-break" /> One Python challenge at a time.
          </p>
          <a href="#challenge-list" className="hero-link">
            Find your next challenge <ArrowRight size={17} />
          </a>
        </div>
        <div className="hero-illustration" aria-hidden="true">
          <span className="orbit orbit-one" />
          <span className="orbit orbit-two" />
          <span className="hero-spark spark-one">+</span>
          <span className="hero-spark spark-two">✳</span>
          <div className="code-card">
            <div className="window-dots">
              <i />
              <i />
              <i />
              <span>possibility.py</span>
            </div>
            <pre>
              <span className="code-comment"># Small steps. Better code.</span>
              {"\n"}
              <span className="code-purple">def</span>{" "}
              <span className="code-mint">find_your_flow</span>():{"\n"}{" "}
              curiosity = <span className="code-amber">True</span>
              {"\n"} <span className="code-purple">while</span> curiosity:{"\n"}{" "}
              learn.something_new()
            </pre>
          </div>
          <div className="floating-tag">
            <Braces size={17} />
            <span>Built one line at a time</span>
          </div>
        </div>
      </section>
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-icon mint">
            <Braces size={20} />
          </span>
          <div>
            <span>Challenges loaded</span>
            <strong>
              {tasks.length}
              {more ? "+" : ""}
            </strong>
          </div>
          <span className="stat-caption">Your collection</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon purple">
            <Clock3 size={20} />
          </span>
          <div>
            <span>Evaluations tracked</span>
            <strong>{historyCount}</strong>
          </div>
          <span className="stat-caption">In this browser</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon amber">
            <Sparkles size={20} />
          </span>
          <div>
            <span>Your language</span>
            <strong className="stat-language">Python</strong>
          </div>
          <span className="stat-caption">Room to experiment</span>
        </div>
      </div>
      <section id="challenge-list" className="challenge-section">
        <div className="section-header">
          <div>
            <h2>
              Your challenges <span className="count">{tasks.length}</span>
            </h2>
            <p className="muted">Choose a problem. Follow the possibilities.</p>
          </div>
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="Search loaded challenges"
              placeholder="Search loaded challenges…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {error && (
          <>
            <ErrorNotice message={error} />
            <button
              onClick={() => {
                setLoading(true);
                void load();
              }}
              className="button secondary mt-4"
            >
              Retry
            </button>
          </>
        )}
        {loading ? (
          <Loading label="Finding your challenges…" />
        ) : visible.length ? (
          <div className="challenge-grid">
            {visible.map((task, index) => (
              <Link
                className="challenge-card"
                key={task.id}
                href={`/challenges/${task.id}`}
              >
                <div className="card-top">
                  <span className={`challenge-symbol symbol-${index % 3}`}>
                    <Braces size={24} />
                  </span>
                  <span className="language-tag">
                    <span />
                    Python
                  </span>
                </div>
                <h3>{task.title}</h3>
                <p>{task.description}</p>
                <div className="card-meta">
                  <span>{task.max_score} possible points</span>
                  <span>{date(task.created_at)}</span>
                </div>
                <div className="card-bottom">
                  <span>Open workspace</span>
                  <ArrowRight size={18} />
                </div>
              </Link>
            ))}
          </div>
        ) : (
          !error && (
            <Empty
              title={
                query
                  ? "No matching challenges"
                  : "A blank page. A lot of possibility."
              }
            >
              <p>
                {query
                  ? "Try another search, or load more challenges."
                  : "Create your first challenge to start writing a solution."}
              </p>
              {!query && (
                <button
                  className="button primary mt-5"
                  onClick={() => setCreating(true)}
                >
                  <Plus size={16} />
                  Create a challenge
                </button>
              )}
            </Empty>
          )
        )}
        {more && (
          <button
            className="button secondary load-more"
            disabled={saving}
            onClick={loadMore}
          >
            Load more challenges <ArrowDown size={16} />
          </button>
        )}
      </section>
      {creating && (
        <Dialog onClose={() => setCreating(false)} busy={saving}>
          <section className="modal">
            <div className="modal-heading">
              <div>
                <span className="eyebrow">A FRESH START</span>
                <h2 id="create-title">Create a challenge</h2>
              </div>
              <button
                aria-label="Close new challenge"
                className="icon-button"
                disabled={saving}
                onClick={() => setCreating(false)}
              >
                <X />
              </button>
            </div>
            <p className="muted">
              Define a problem for your workspace. Runner test suites are
              configured separately.
            </p>
            <form className="form-stack" onSubmit={create}>
              {formError && <ErrorNotice message={formError} />}
              <label>
                Title
                <input
                  autoFocus
                  name="title"
                  minLength={3}
                  maxLength={150}
                  required
                  placeholder="e.g. Find the missing number"
                />
              </label>
              <label>
                Problem description
                <textarea
                  name="description"
                  required
                  minLength={10}
                  maxLength={20000}
                  rows={5}
                  placeholder="Explain the problem, inputs, and expected output…"
                />
              </label>
              <label>
                Maximum score
                <input
                  type="number"
                  name="max_score"
                  defaultValue={100}
                  min={1}
                  max={1000}
                  required
                />
              </label>
              <div className="modal-actions">
                <button
                  type="button"
                  className="button secondary"
                  disabled={saving}
                  onClick={() => setCreating(false)}
                >
                  Cancel
                </button>
                <button className="button primary" disabled={saving}>
                  {saving ? "Creating…" : "Create challenge"}
                  <ArrowRight size={16} />
                </button>
              </div>
            </form>
          </section>
        </Dialog>
      )}
    </>
  );
}
