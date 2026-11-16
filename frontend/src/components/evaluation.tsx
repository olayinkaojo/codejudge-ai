"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  Clock3,
  Copy,
  FileCode2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api, backend } from "@/lib/client";
import { readHistory } from "@/lib/history";
import {
  errorMessage,
  type Evaluation,
  type HistoryEntry,
  type Task,
} from "@/lib/types";
import { Badge, date, Empty, ErrorNotice, Loading, PageHeading } from "./ui";
import { useUsername } from "./workspace";
export async function fetchHistory(username: string) {
  const entries = readHistory(username);
  const results: Record<string, Evaluation> = {};
  const errors: Record<string, string> = {};
  // Bound concurrent refreshes instead of flooding the backend with up to 100 requests.
  for (let offset = 0; offset < entries.length; offset += 5) {
    let unavailable = false;
    await Promise.all(
      entries.slice(offset, offset + 5).map(async (entry) => {
        try {
          results[entry.id] = await api<Evaluation>(
            `${backend}/evaluations/${entry.id}`,
          );
        } catch (e) {
          errors[entry.id] = (e as Error).message;
          if (
            e &&
            typeof e === "object" &&
            "status" in e &&
            [0, 401, 502, 503, 504].includes(Number(e.status))
          )
            unavailable = true;
        }
      }),
    );
    if (unavailable) {
      for (const entry of entries.slice(offset + 5))
        errors[entry.id] =
          "Refresh paused while the API is unavailable. Retry when connected.";
      break;
    }
  }
  return { entries, results, errors };
}
export function EvaluationHistory() {
  const router = useRouter();
  const username = useUsername();
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [results, setResults] = useState<Record<string, Evaluation>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    const data = await fetchHistory(username);
    setEntries(data.entries);
    setResults(data.results);
    setErrors(data.errors);
    setLoading(false);
  }, [username]);
  useEffect(() => {
    let active = true;
    fetchHistory(username).then((data) => {
      if (active) {
        setEntries(data.entries);
        setResults(data.results);
        setErrors(data.errors);
        setLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, [username]);
  return (
    <>
      <PageHeading
        eyebrow="EVERY ITERATION TELLS A STORY"
        title="Your evaluation history."
        description="A record of the evaluations you’ve requested from this browser."
        action={
          <button
            className="button secondary"
            onClick={() => {
              setLoading(true);
              void load();
            }}
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? "spin" : ""} />
            Refresh
          </button>
        }
      />
      <div className="info-banner">
        <InfoIcon />
        <p>
          History is stored locally as evaluation IDs, not tokens or source
          code. It is cleared on sign-out and doesn’t sync across devices. Each
          status below is fetched from the backend.
        </p>
      </div>
      {loading ? (
        <Loading label="Checking your evaluations…" />
      ) : entries.length ? (
        <section className="history-list" aria-label="Evaluations">
          {entries.map((entry) => {
            const evaluation = results[entry.id];
            return (
              <Link
                key={entry.id}
                href={`/results/${entry.id}`}
                className="history-row"
              >
                <span className="history-icon">
                  <FileCode2 size={22} />
                </span>
                <div className="history-title">
                  <h2>{entry.title}</h2>
                  <span>
                    {date(entry.createdAt)}{" "}
                    <span className="dot-separator">·</span>{" "}
                    {evaluation?.submission_reference || entry.id.slice(0, 8)}
                  </span>
                  {errors[entry.id] && (
                    <p className="inline-error">{errors[entry.id]}</p>
                  )}
                </div>
                <div className="history-outcome">
                  {evaluation && <Badge status={evaluation.status} />}
                  <strong>
                    {evaluation?.status === "succeeded" &&
                    evaluation.score !== null
                      ? `${evaluation.score} points`
                      : "No score"}
                  </strong>
                </div>
                <ArrowRight className="history-arrow" size={19} />
              </Link>
            );
          })}
        </section>
      ) : (
        <Empty
          icon={<Clock3 size={28} />}
          title="Your first iteration is ahead."
        >
          <p>
            Request an evaluation from a challenge workspace.
            <br />
            Its progress and result will appear here.
          </p>
          <Link href="/dashboard" className="button primary mt-5">
            Explore challenges
            <ArrowRight size={16} />
          </Link>
        </Empty>
      )}
      <div className="lookup-panel">
        <div>
          <h3>Have an evaluation ID?</h3>
          <p className="muted">
            Open a result from another device. Access is checked against your
            account.
          </p>
        </div>
        <form
          action={(form) => {
            const id = String(form.get("id"));
            if (/^[0-9a-f-]{36}$/i.test(id)) router.push(`/results/${id}`);
          }}
        >
          <input
            name="id"
            aria-label="Evaluation ID"
            placeholder="Evaluation UUID"
            required
            pattern="[0-9a-fA-F-]{36}"
          />
          <button className="button secondary">
            Open result
            <ArrowRight size={16} />
          </button>
        </form>
      </div>
    </>
  );
}
function InfoIcon() {
  return <ShieldCheck size={20} />;
}
export function EvaluationDetails({
  id,
  historyUnavailable = false,
}: {
  id: string;
  historyUnavailable?: boolean;
}) {
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<Evaluation>(`${backend}/evaluations/${id}`);
        if (!active) return;
        setEvaluation(value);
        setError("");
        if (value.status === "queued" || value.status === "running")
          timer = setTimeout(poll, 3000);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, retry]);
  const taskId = evaluation?.task_id;
  useEffect(() => {
    let active = true;
    if (taskId)
      api<Task>(`${backend}/tasks/${taskId}`)
        .then((value) => {
          if (active) setTask(value);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [taskId]);
  const complete = evaluation?.status === "succeeded";
  const failed = evaluation?.status === "failed";
  return (
    <>
      <Link href="/history" className="back-link">
        <ArrowLeft size={16} />
        Evaluation history
      </Link>
      <PageHeading
        eyebrow="THE DETAILS BEHIND THE RESULT"
        title={task?.title || "Evaluation details"}
        description="Real progress. Clear feedback. No guesswork."
        action={evaluation && <Badge status={evaluation.status} />}
      />
      {historyUnavailable && (
        <div className="info-banner">
          <ShieldCheck size={20} />
          <p>
            This browser could not save the history entry. Copy this evaluation
            ID or keep the result URL to return later.
          </p>
        </div>
      )}
      {error && (
        <>
          <ErrorNotice message={error} />
          <button
            className="button secondary mt-4"
            onClick={() => setRetry((v) => v + 1)}
          >
            <RefreshCw size={16} />
            Retry connection
          </button>
        </>
      )}
      {!evaluation ? (
        !error && <Loading />
      ) : (
        <>
          <section
            className={`result-hero ${complete ? "result-success" : failed ? "result-failed" : "result-pending"}`}
            aria-live="polite"
          >
            <span className="result-icon">
              {complete ? (
                <Check size={30} />
              ) : failed ? (
                <CircleAlert size={30} />
              ) : (
                <Clock3 size={30} />
              )}
            </span>
            <div>
              <span className="eyebrow">
                {complete
                  ? "RUNNER RESULT RECEIVED"
                  : failed
                    ? "EVALUATION STOPPED"
                    : "EVALUATION IN PROGRESS"}
              </span>
              <h2>
                {complete
                  ? "Your results are in."
                  : failed
                    ? "This evaluation couldn’t finish."
                    : evaluation.status === "queued"
                      ? "Your artifact is in the queue."
                      : "Your artifact is being evaluated."}
              </h2>
              <p>
                {complete
                  ? "The configured runner returned these results. They reflect the referenced artifact."
                  : failed
                    ? errorMessage(evaluation.error)
                    : "This page checks the backend every few seconds. A score appears only after a valid runner result."}
              </p>
            </div>
            <div className="result-score">
              <strong>
                {complete && evaluation.score !== null ? evaluation.score : "—"}
                <span>{complete && task ? ` / ${task.max_score}` : ""}</span>
              </strong>
              <span>{complete ? "points awarded" : "No score available"}</span>
            </div>
          </section>
          <div className="result-grid">
            <section className="detail-card">
              <h2>Test outcomes</h2>
              {complete ? (
                <>
                  <div className="test-count">
                    <strong>
                      {evaluation.tests_passed}
                      <span> / {evaluation.tests_total}</span>
                    </strong>
                    <span>tests passed</span>
                  </div>
                  <div className="progress-track">
                    <div
                      style={{
                        width: `${evaluation.tests_total ? ((evaluation.tests_passed || 0) / evaluation.tests_total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <p className="muted">
                    Reported by your external runner. Per-test output is not
                    provided by the API.
                  </p>
                </>
              ) : (
                <div className="no-test-results">
                  <FileCode2 size={26} />
                  <h3>No test results available</h3>
                  <p className="muted">
                    {failed
                      ? "The runner did not produce an accepted result."
                      : "Waiting for an accepted runner response."}
                  </p>
                </div>
              )}
            </section>
            <section className="detail-card">
              <h2>Evaluation record</h2>
              <dl className="record-list">
                <div>
                  <dt>Evaluation ID</dt>
                  <dd className="copy-id">
                    <code>{evaluation.id}</code>
                    <button
                      className="icon-button"
                      aria-label="Copy evaluation ID"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(evaluation.id);
                          setCopied(true);
                        } catch {
                          setCopied(false);
                        }
                      }}
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </dd>
                </div>
                <div>
                  <dt>Artifact reference</dt>
                  <dd>
                    <code>{evaluation.submission_reference}</code>
                  </dd>
                </div>
                <div>
                  <dt>Requested</dt>
                  <dd>{date(evaluation.created_at)}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>
                    {evaluation.completed_at
                      ? date(evaluation.completed_at)
                      : "Not completed"}
                  </dd>
                </div>
                {evaluation.error && (
                  <div>
                    <dt>Error code</dt>
                    <dd>
                      <code>{evaluation.error}</code>
                    </dd>
                  </div>
                )}
              </dl>
            </section>
          </div>
          <section className="detail-card feedback-card">
            <div className="panel-label">
              <ShieldCheck size={18} />
              Runner feedback
            </div>
            <h2>
              {complete
                ? "A little clarity for your next iteration."
                : failed
                  ? "No runner feedback is available."
                  : "Feedback is not available yet."}
            </h2>
            <p className="feedback-text">
              {complete
                ? evaluation.feedback ||
                  "The runner returned no additional feedback."
                : failed
                  ? "This evaluation ended without an accepted runner result."
                  : "Feedback will only be shown when returned with an accepted evaluation result."}
            </p>
          </section>
          <div className="results-footer">
            <Link
              href={`/challenges/${evaluation.task_id}`}
              className="button primary"
            >
              Back to challenge
              <ArrowRight size={16} />
            </Link>
            <p className="muted">
              Your editor draft is not included in the evaluation record.
            </p>
          </div>
        </>
      )}
    </>
  );
}
