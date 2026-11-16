"use client";
import { AlertCircle, ArrowUpRight, Braces, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { stateLabels, type EvaluationStatus } from "@/lib/types";
export function Logo() {
  return (
    <Link href="/dashboard" className="logo" aria-label="CodeJudge AI home">
      <span className="logo-mark">
        <Braces size={23} strokeWidth={2.4} />
      </span>
      <span>
        CodeJudge<span className="logo-ai">AI</span>
      </span>
    </Link>
  );
}
export function Badge({ status }: { status: EvaluationStatus }) {
  return (
    <span className={`badge ${status}`}>
      <span className="status-dot" />
      {stateLabels[status] || status}
    </span>
  );
}
export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  );
}
export function Loading({
  label = "Loading your workspace…",
}: {
  label?: string;
}) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} />
      <p>{label}</p>
    </div>
  );
}
export function Empty({
  icon,
  title,
  children,
}: {
  icon?: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon || <Braces size={28} />}</div>
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      {action}
    </div>
  );
}
export function TextLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className="text-link">
      {children}
      <ArrowUpRight size={16} />
    </Link>
  );
}
export function date(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
