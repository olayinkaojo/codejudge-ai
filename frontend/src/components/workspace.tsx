"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowUpRight,
  ChevronRight,
  Clock3,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldCheck,
  ScanText,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/client";
import { clearHistory } from "@/lib/history";
import { ErrorNotice, Loading, Logo } from "./ui";
function navigationItems(node: HTMLElement | null) {
  return Array.from(
    node?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)") ?? [],
  ).filter((item) => item.getClientRects().length > 0);
}
const Identity = createContext("");
export const useUsername = () => useContext(Identity);
export function Workspace({ children }: { children: React.ReactNode }) {
  const navRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  async function load() {
    setError("");
    try {
      const data = await api<{ username: string }>("/api/auth");
      setUsername(data.username);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401)
        router.replace("/login?expired=1");
      else setError((e as Error).message);
    }
  }
  useEffect(() => {
    let active = true;
    api<{ username: string }>("/api/auth")
      .then((data) => {
        if (active) setUsername(data.username);
      })
      .catch((e) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 401)
          router.replace("/login?expired=1");
        else setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [router]);
  useEffect(() => {
    if (!open) return;
    navigationItems(navRef.current)[0]?.focus();
    const toggle = toggleRef.current;
    return () => toggle?.focus();
  }, [open]);
  useEffect(() => {
    const closeDesktop = () => {
      if (window.matchMedia("(min-width: 851px)").matches) setOpen(false);
    };
    window.addEventListener("resize", closeDesktop);
    return () => window.removeEventListener("resize", closeDesktop);
  }, []);
  async function logout() {
    setLoggingOut(true);
    setError("");
    try {
      await api("/api/auth", {
        method: "POST",
        body: JSON.stringify({ action: "logout" }),
      });
      clearHistory(username);
      router.replace("/login");
    } catch (e) {
      setError((e as Error).message);
      setLoggingOut(false);
    }
  }
  const nav = [
    { href: "/dashboard", name: "Challenges", icon: LayoutDashboard },
    { href: "/history", name: "Evaluation history", icon: Clock3 },
    { href: "/reviews", name: "Code reviews", icon: ScanText },
  ];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="mobile-header">
        <Logo />
        <button
          ref={toggleRef}
          className="icon-button"
          aria-controls="workspace-navigation"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? <X /> : <Menu />}
        </button>
      </header>
      {open && (
        <button
          className="nav-scrim"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        id="workspace-navigation"
        ref={navRef}
        className={`sidebar ${open ? "nav-open" : ""}`}
        role={open ? "dialog" : undefined}
        aria-modal={open || undefined}
        aria-label="Workspace navigation"
        onKeyDown={(event) => {
          if (!open) return;
          if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
          }
          if (event.key === "Tab") {
            const elements = navigationItems(navRef.current);
            if (!elements?.length) return;
            const first = elements[0],
              last = elements[elements.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }
        }}
      >
        {open && (
          <button
            className="icon-button nav-close"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          >
            <X size={20} />
          </button>
        )}
        <div className="desktop-logo">
          <Logo />
        </div>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          {nav.map(({ href, name, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={
                pathname === href ||
                (href === "/reviews" && pathname.startsWith("/reviews/"))
                  ? "page"
                  : undefined
              }
              onClick={() => setOpen(false)}
              className={`nav-item ${pathname === href || (href === "/dashboard" && pathname.startsWith("/challenges")) || (href === "/reviews" && pathname.startsWith("/reviews/")) ? "active" : ""}`}
            >
              <Icon size={18} />
              <span>{name}</span>
              {pathname === href && (
                <ChevronRight size={14} className="nav-chevron" />
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="small-icon">
            <ShieldCheck size={19} />
          </span>
          <strong>Built for honest results.</strong>
          <p>Every score comes from your configured evaluation runner.</p>
          <Link href="/history" onClick={() => setOpen(false)}>
            Explore your activity <ArrowUpRight size={14} />
          </Link>
        </div>
        <div className="sidebar-user">
          <span className="avatar">
            {username ? username[0].toUpperCase() : "…"}
          </span>
          <div>
            <strong>{username || "Your account"}</strong>
            <span>Personal workspace</span>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            title="Sign out"
            disabled={loggingOut || !username}
            onClick={logout}
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="workspace-content" inert={open}>
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={14} />{" "}
            <strong>
              {pathname.startsWith("/reviews")
                ? "Code reviews"
                : pathname.startsWith("/history")
                  ? "Evaluation history"
                  : pathname.startsWith("/results")
                    ? "Evaluation details"
                    : pathname.startsWith("/challenges")
                      ? "Challenge workspace"
                      : "Challenges"}
            </strong>
          </span>
          <span className="topbar-tag">
            <span />
            Python workspace
          </span>
        </header>
        <main id="main" className="main-content">
          {error && (
            <div className="mb-6">
              <ErrorNotice message={error} />
              {!username && (
                <button className="button secondary mt-4" onClick={load}>
                  Retry connection
                </button>
              )}
            </div>
          )}
          {username ? (
            <Identity.Provider value={username}>{children}</Identity.Provider>
          ) : (
            !error && <Loading />
          )}
        </main>
        <footer className="workspace-footer">
          <span>CodeJudge AI · A clearer path from code to feedback.</span>
          <span>
            Python <span className="footer-separator">/</span> Private workspace
          </span>
        </footer>
      </div>
    </div>
  );
}
