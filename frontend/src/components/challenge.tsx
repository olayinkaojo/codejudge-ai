"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Download,
  FileCode2,
  Info,
  ShieldCheck,
} from "lucide-react";
import { api, backend } from "@/lib/client";
import { remember } from "@/lib/history";
import type { Evaluation, Task } from "@/lib/types";
import { ReviewAction } from "./reviews";
import { ErrorNotice, Loading } from "./ui";
import { useUsername } from "./workspace";
const Editor = dynamic(() => import("./python-editor"), {
  ssr: false,
  loading: () => <Loading label="Preparing your Python editor…" />,
});
const starter =
  "# Explore your solution here.\n# This draft stays in memory until you leave this page.\n\ndef solve():\n    pass\n";
export function Challenge({ id }: { id: string }) {
  const username = useUsername();
  const router = useRouter();
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState("");
  const [source, setSource] = useState(starter);
  const [busy, setBusy] = useState(false);
  const [reference, setReference] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  useEffect(() => {
    let active = true;
    api<Task>(`${backend}/tasks/${id}`)
      .then((data) => {
        if (active) setTask(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [id]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (source !== starter) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [source]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([source], { type: "text/x-python" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "solution.py";
    a.click();
    URL.revokeObjectURL(url);
  }
  async function evaluate(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!task || !acknowledged) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Evaluation>(`${backend}/evaluations`, {
        method: "POST",
        body: JSON.stringify({
          task_id: task.id,
          submission_reference: reference,
        }),
      });
      const saved = remember(username, {
        id: result.id,
        taskId: task.id,
        title: task.title,
        createdAt: result.created_at,
      });
      router.push(
        `/results/${result.id}${saved ? "" : "?history=unavailable"}`,
      );
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <>
      <Link href="/dashboard" className="back-link">
        <ArrowLeft size={16} />
        All challenges
      </Link>
      {error && <ErrorNotice message={error} />}
      {!task ? (
        !error && <Loading />
      ) : (
        <>
          <div className="editor-heading">
            <div>
              <div className="eyebrow">YOUR NEXT BREAKTHROUGH</div>
              <h1>{task.title}</h1>
            </div>
            <span className="language-tag">
              Python · {task.max_score} points
            </span>
          </div>
          <div className="coding-layout">
            <section className="problem-panel">
              <div className="panel-label">
                <FileCode2 size={17} />
                The challenge
              </div>
              <h2>Problem statement</h2>
              <p className="problem-description">{task.description}</p>
              <div className="problem-note">
                <ShieldCheck size={20} />
                <div>
                  <strong>A clear boundary.</strong>
                  <p>
                    Solutions run only in an external isolated runner, never in
                    the API or this editor.
                  </p>
                </div>
              </div>
              <div className="problem-note subtle">
                <Info size={20} />
                <div>
                  <strong>Your draft is yours.</strong>
                  <p>
                    Download your code before leaving. Drafts are not uploaded
                    or saved automatically. Use browser back/forward carefully.
                  </p>
                </div>
              </div>
            </section>
            <section className="editor-panel" aria-label="Python editor">
              <div className="editor-tabbar">
                <span>
                  <FileCode2 size={16} />
                  solution.py
                  <span className="draft-dot" />
                </span>
                <button className="download-button" onClick={download}>
                  <Download size={15} />
                  Download
                </button>
              </div>
              <Editor value={source} onChange={setSource} />
              <div className="editor-status">
                <span>
                  <span className="status-dot" />
                  Python
                </span>
                <span>
                  UTF-8 <span>·</span> Draft only
                </span>
              </div>
            </section>
          </div>
          <ReviewAction taskId={task.id} source={source} />
          <section className="submission-panel">
            <div>
              <div className="eyebrow">READY FOR FEEDBACK?</div>
              <h2>Request an evaluation</h2>
              <p className="muted">
                The API accepts an artifact ID, not your editor contents. Upload
                your downloaded solution through your runner’s artifact workflow
                first.
              </p>
            </div>
            <form onSubmit={evaluate} className="submission-form">
              <label>
                Existing artifact ID
                <input
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  placeholder="e.g. solution-artifact-123"
                  required
                  maxLength={256}
                  pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]*"
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                  required
                />
                <span>
                  I understand this evaluates the referenced artifact, not the
                  code in this editor.
                </span>
              </label>
              <button
                className="button primary"
                disabled={busy || !acknowledged}
              >
                {busy ? "Requesting evaluation…" : "Request evaluation"}
                <ArrowRight size={17} />
              </button>
              <p className="field-help">
                Without a configured runner, the job will fail without executing
                code.
              </p>
            </form>
          </section>
        </>
      )}
    </>
  );
}
