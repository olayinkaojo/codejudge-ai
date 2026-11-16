"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  Code2,
  Eye,
  EyeOff,
  LockKeyhole,
} from "lucide-react";
import { api, ApiError } from "@/lib/client";
import { ErrorNotice, Logo } from "./ui";
export function AuthForm({
  register = false,
  expired = false,
}: {
  register?: boolean;
  expired?: boolean;
}) {
  const router = useRouter();
  const pending = useRef(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(false);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
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
      setError(
        e instanceof ApiError && [0, 502, 503, 504].includes(e.status)
          ? register
            ? "The API may be waking up or unavailable. Registration may have completed; try signing in before registering again."
            : "The API may be waking up or unavailable. Wait a moment, check your connection, and try signing in again."
          : (e as Error).message,
      );
    } finally {
      pending.current = false;
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
            <div className="success-notice" role="status">
              <Check />
              <h3>Registration request processed.</h3>
              <p>
                If the username was available, your account was created. Already
                registered? Sign in with your existing password.
              </p>
              <Link href="/login" className="button primary">
                Continue to sign in <ArrowRight size={16} />
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="form-stack" aria-busy={busy}>
              {expired && !register && (
                <p className="connection-note" role="status">
                  Your session has expired or is unavailable. Sign in to
                  continue. Unsaved drafts are not retained after navigation.
                </p>
              )}
              {error && (
                <div ref={errorRef} tabIndex={-1}>
                  <ErrorNotice message={error} />
                </div>
              )}
              <div className="form-field">
                <label htmlFor="username-input">Username</label>
                <input
                  id="username-input"
                  name="username"
                  disabled={busy}
                  aria-describedby="username-help"
                  autoComplete="username"
                  required
                  minLength={3}
                  maxLength={64}
                  pattern="[a-zA-Z0-9_]+"
                  placeholder="Your username"
                />
                <span id="username-help" className="field-help">
                  3–64 letters, numbers, or underscores.
                </span>
              </div>
              <div className="form-field">
                <label htmlFor="password-input">Password</label>
                <span className="password-field">
                  <input
                    id="password-input"
                    name="password"
                    disabled={busy}
                    type={showPassword ? "text" : "password"}
                    autoComplete={
                      register ? "new-password" : "current-password"
                    }
                    required
                    minLength={12}
                    maxLength={128}
                    placeholder="At least 12 characters"
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </span>
              </div>
              <button className="button primary full" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : register
                    ? "Create account"
                    : "Sign in to workspace"}
                <ArrowRight size={17} />
              </button>
              {busy && (
                <p className="connection-note" role="status">
                  Connecting securely… Free hosting may need a moment to wake
                  up. Please keep this page open.
                </p>
              )}
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
