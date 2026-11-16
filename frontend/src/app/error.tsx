"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="standalone-message">
      <h1>Something interrupted your workspace.</h1>
      <p className="muted">
        Please try again. Your server-side evaluations are still stored by the
        backend.
      </p>
      <button className="button primary" onClick={reset}>
        Try again
      </button>
    </main>
  );
}
