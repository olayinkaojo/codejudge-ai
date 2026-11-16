"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Code2, LockKeyhole } from "lucide-react";
import { api } from "@/lib/client";
import { ErrorNotice, Logo } from "./ui";
export function AuthForm({ register = false }: { register?: boolean }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(false);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api("/api/auth", {
        method: "POST",
        body: JSON.stringify({
          action: register ? "register" : "login",
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      if (register) {
        setCreated(true);
      } else {
        router.replace("/dashboard");
        router.refresh();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-layout">
      <section className="auth-story">
        <Logo />
        <div className="auth-story-content">
          <span className="eyebrow">THINK. BUILD. UNDERSTAND.</span>
          <h1>
            Good code starts
            <br />
            with a little
            <br />
            <em>curiosity.</em>
          </h1>
          <p>
            Your space to work through Python challenges, shape a solution, and
            understand every result.
          </p>
          <div className="auth-code">
            <div className="window-dots">
              <i />
              <i />
              <i />
              <span>your_next_solution.py</span>
            </div>
            <pre>
              <span className="code-purple">def</span>{" "}
              <span className="code-mint">solve</span>(challenge):{"\n"} idea =
              think(challenge){"\n"} <span className="code-purple">return</span>{" "}
              build(idea){"\n\n"}
              <span className="code-comment">
                # Make something worth understanding.
              </span>
            </pre>
          </div>
        </div>
        <span className="auth-story-footer">
          <Code2 size={16} /> A thoughtful workspace for better solutions.
        </span>
      </section>
      <section className="auth-panel">
        <div className="auth-mobile-logo">
          <Logo />
        </div>
        <div className="auth-form-wrap">
          <div className="auth-icon">
            <LockKeyhole size={24} />
          </div>
          <div className="eyebrow">YOUR NEXT CHAPTER</div>
          <h2>{register ? "Create your workspace" : "Welcome back."}</h2>
          <p className="muted">
            {register
              ? "A fresh place for your challenges and ideas."
              : "Pick up where your curiosity left off."}
          </p>
          {created ? (
            <div className="success-notice">
              <Check />
              <h3>Your account is ready.</h3>
              <p>Sign in to start your first challenge.</p>
              <Link href="/login" className="button primary">
                Continue to sign in <ArrowRight size={16} />
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="form-stack">
              {error && <ErrorNotice message={error} />}
              <label>
                Username
                <input
                  name="username"
                  autoComplete="username"
                  required
                  minLength={3}
                  maxLength={64}
                  pattern="[a-zA-Z0-9_]+"
                  placeholder="Your username"
                />
                <span className="field-help">
                  3–64 letters, numbers, or underscores.
                </span>
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete={register ? "new-password" : "current-password"}
                  required
                  minLength={12}
                  maxLength={128}
                  placeholder="At least 12 characters"
                />
              </label>
              <button className="button primary full" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : register
                    ? "Create account"
                    : "Sign in to workspace"}
                <ArrowRight size={17} />
              </button>
            </form>
          )}
          <p className="auth-switch">
            {register ? "Already have a workspace?" : "New around here?"}{" "}
            <Link href={register ? "/login" : "/register"}>
              {register ? "Sign in" : "Create an account"}
            </Link>
          </p>
          <div className="auth-security">
            <LockKeyhole size={14} />
            Your session stays in a secure, HttpOnly cookie.
          </div>
        </div>
        <div className="auth-panel-footer">
          Write with intention. Learn with every iteration.
        </div>
      </section>
    </main>
  );
}
