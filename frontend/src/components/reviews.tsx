"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ScanText, ArrowRight, ShieldCheck } from "lucide-react";
import { api, backend } from "@/lib/client";
import { reviewError, type CodeReview, type ReviewConfig } from "@/lib/reviews";
import { date, Empty, ErrorNotice, Loading, PageHeading } from "./ui";

export function ReviewContent({ review }: { review: CodeReview }) {
  return (
    <div className="review-content">
      <div className="review-meta">
        <span
          className={`badge ${review.status === "failed" ? "failed" : "queued"}`}
        >
          {review.provider === "mock"
            ? "Simulated · mock"
            : "External AI · OpenAI"}
        </span>
        <span className="language-tag">{review.status}</span>
      </div>
      <p className="review-disclosure">
        <ShieldCheck size={18} /> Text review only. Code was not executed. No
        test results or score are produced.
      </p>
      {review.status === "processing" && (
        <Loading label="This request is still processing. Interrupted requests are marked failed after the deadline; they are never retried automatically." />
      )}
      {review.status === "failed" && (
        <ErrorNotice message={reviewError(review.error)} />
      )}
      {review.status === "completed" && review.result && (
        <>
          <p className="review-summary">{review.result.summary}</p>
          <h3>
            Findings{" "}
            <span className="muted">({review.result.findings.length})</span>
          </h3>
          {!review.result.findings.length && (
            <p className="muted">
              No findings returned. This does not establish correctness or
              security.
            </p>
          )}
          {review.result.findings.map((finding, index) => (
            <article
              className={`review-finding severity-${finding.severity}`}
              key={index}
            >
              <div className="review-meta">
                <span className="review-severity">{finding.severity}</span>
                <span>
                  {finding.line === null
                    ? "No reliable line reference"
                    : `Line ${finding.line}`}
                </span>
                <span>
                  {finding.evidence === "text_pattern"
                    ? "Text pattern · may match comments"
                    : "Model hypothesis · unverified"}
                </span>
              </div>
              <h4>{finding.title}</h4>
              <p>{finding.explanation}</p>
              <p>
                <strong>Suggested improvement:</strong> {finding.suggestion}
              </p>
              {finding.snippet && (
                <>
                  <span className="field-help">
                    Suggested snippet · review manually before use
                  </span>
                  <pre>
                    <code>{finding.snippet}</code>
                  </pre>
                </>
              )}
            </article>
          ))}
          <div className="review-notes">
            <section>
              <h3>Positive observations</h3>
              <ul>
                {review.result.positives.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </section>
            <section>
              <h3>Uncertainty & limitations</h3>
              <ul>
                {review.result.limitations.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
      <p className="field-help">
        Saved until {date(review.expires_at)}. Source text is not retained;
        review suggestions may contain code fragments.
      </p>
    </div>
  );
}

export function ReviewAction({
  taskId,
  source,
}: {
  taskId: string;
  source: string;
}) {
  const [config, setConfig] = useState<ReviewConfig | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<CodeReview | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    api<ReviewConfig>(`${backend}/reviews/config`)
      .then((data) => {
        if (active) {
          setConfig(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  const tooLarge =
    source.length > 16000 || new TextEncoder().encode(source).length > 32768;
  async function request() {
    setBusy(true);
    setError("");
    setReview(null);
    try {
      setReview(
        await api<CodeReview>(`${backend}/reviews`, {
          method: "POST",
          body: JSON.stringify({
            task_id: taskId,
            source,
            language: "python",
            external_consent: consent,
          }),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="review-panel" aria-label="Code review">
      <div className="review-panel-heading">
        <div>
          <div className="eyebrow">A SECOND LOOK</div>
          <h2>Review your Python</h2>
        </div>
        <ScanText size={25} />
      </div>
      <p className="muted">
        Get feedback on the editor contents without running them. Reviews are
        separate from evaluations and never award a score.
      </p>
      {error && <ErrorNotice message={error} />}
      {!config ? (
        error ? (
          <button
            className="button secondary"
            onClick={() => setAttempt(attempt + 1)}
          >
            Retry provider information
          </button>
        ) : (
          <Loading label="Checking review provider…" />
        )
      ) : (
        <>
          <p className="review-disclosure">
            {config.external
              ? "External AI review: your complete editor contents will be sent to OpenAI only when you consent and request a review. Do not include secrets or personal data. Provider retention policies also apply."
              : "Simulated mock review: deterministic text patterns, no AI API call, no external transmission. Findings can match strings and comments."}
          </p>
          <p className="field-help">
            Up to {config.user_daily_limit} requests per day and 3 per minute;
            shared limits also apply. No automatic retries. Results are retained
            for {config.retention_days} days. Source text is not stored.
          </p>
          {config.external && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span>
                I consent to sending this code to OpenAI for this review.
              </span>
            </label>
          )}
          {!config.available && (
            <ErrorNotice message="This provider is not configured. No review will be sent." />
          )}
          {tooLarge && (
            <ErrorNotice message="Review source is limited to 16,000 characters and 32,768 UTF-8 bytes." />
          )}
          <button
            className="button primary"
            onClick={request}
            disabled={
              busy ||
              !config.available ||
              (config.external && !consent) ||
              tooLarge ||
              !source.trim()
            }
          >
            {busy ? "Reviewing code…" : "Review code"}
            <ArrowRight size={17} />
          </button>
        </>
      )}
      {busy && (
        <Loading label="Reviewing text only. Your code is not being executed…" />
      )}
      {review && (
        <>
          <p className="field-help">
            Feedback applies to the editor snapshot sent when you selected
            Review code. Later edits are not included.
          </p>
          <ReviewContent review={review} />
          <Link className="text-link" href={`/reviews/${review.id}`}>
            Open saved review <ArrowRight size={16} />
          </Link>
        </>
      )}
    </section>
  );
}

export function ReviewHistory() {
  const [reviews, setReviews] = useState<CodeReview[] | null>(null);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    api<CodeReview[]>(`${backend}/reviews?limit=20&offset=${offset}`)
      .then((data) => {
        if (active) {
          setReviews(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [offset, attempt]);
  function move(value: number) {
    setReviews(null);
    setError("");
    setOffset(value);
  }
  return (
    <>
      <PageHeading
        eyebrow="FEEDBACK LIBRARY"
        title="Your code reviews."
        description="Private, saved text feedback. Separate from runner evaluations. Reviews expire after 30 days."
      />
      {error && (
        <>
          <ErrorNotice message={error} />
          <button
            className="button secondary"
            onClick={() => setAttempt(attempt + 1)}
          >
            Retry loading reviews
          </button>
        </>
      )}
      {!reviews && !error && <Loading />}
      {reviews?.length === 0 && (
        <Empty icon={<ScanText size={28} />} title="No reviews on this page">
          <p>Open a challenge and choose Review code to get started.</p>
          <Link href="/dashboard" className="text-link">
            Explore challenges
          </Link>
        </Empty>
      )}
      <div className="review-history">
        {reviews?.map((item) => (
          <Link
            className="review-history-card"
            href={`/reviews/${item.id}`}
            key={item.id}
          >
            <ScanText size={22} />
            <div>
              <strong>
                {item.provider === "mock"
                  ? "Simulated Python review"
                  : "External AI Python review"}
              </strong>
              <p className="muted">
                {date(item.created_at)} · {item.status}
              </p>
              <span className="field-help">
                {item.result?.findings.length ?? "—"} findings · No execution
              </span>
            </div>
            <ArrowRight size={18} />
          </Link>
        ))}
      </div>
      {reviews && (
        <div className="review-pagination">
          <button
            className="button secondary"
            disabled={offset === 0}
            onClick={() => move(Math.max(0, offset - 20))}
          >
            Previous
          </button>
          <span className="muted">Page {offset / 20 + 1}</span>
          <button
            className="button secondary"
            disabled={reviews.length < 20 || offset >= 10000}
            onClick={() => move(offset + 20)}
          >
            Next
          </button>
        </div>
      )}
    </>
  );
}

export function ReviewDetails({ id }: { id: string }) {
  const [review, setReview] = useState<CodeReview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    function load() {
      api<CodeReview>(`${backend}/reviews/${id}`)
        .then((data) => {
          if (active) {
            setReview(data);
            setError("");
            if (data.status === "processing") timer = setTimeout(load, 5000);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }
    load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, attempt]);
  return (
    <>
      <Link className="back-link" href="/reviews">
        ← All code reviews
      </Link>
      <PageHeading
        eyebrow="TEXT FEEDBACK"
        title="Review details."
        description="Use these suggestions as a starting point. Validate changes with your own tests and isolated execution."
      />
      {error && (
        <>
          <ErrorNotice message={error} />
          <button
            className="button secondary"
            onClick={() => setAttempt(attempt + 1)}
          >
            Retry loading review
          </button>
        </>
      )}
      {!review && !error && <Loading />}
      {review && (
        <section className="review-panel">
          <ReviewContent review={review} />
          {review.task_id && (
            <Link className="text-link" href={`/challenges/${review.task_id}`}>
              Return to challenge (draft not retained)
            </Link>
          )}
        </section>
      )}
    </>
  );
}
