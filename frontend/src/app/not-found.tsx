import Link from "next/link";
export default function NotFound() {
  return (
    <main className="standalone-message">
      <span className="eyebrow">A SMALL DETOUR</span>
      <h1>This page isn’t here.</h1>
      <p className="muted">Let’s get you back to your workspace.</p>
      <Link className="button primary" href="/dashboard">
        Back to challenges
      </Link>
    </main>
  );
}
