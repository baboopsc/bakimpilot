"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleAlert, Loader2, OctagonX } from "lucide-react";

import { ApiError } from "@/lib/api";
import type { Airworthiness, DueStatus } from "@/lib/types";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ className, children, title, actions }: {
  className?: string;
  children: React.ReactNode;
  title?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <section className={clsx("rounded-lg border border-border bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  variant = "secondary",
  loading,
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={clsx(
        "inline-flex min-h-9 cursor-pointer items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-primary text-primary-fg hover:brightness-110",
        variant === "secondary" && "border border-border bg-surface-2 hover:border-muted",
        variant === "danger" && "bg-danger text-white hover:brightness-110",
        variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-fg",
        className,
      )}
    >
      {loading && <Loader2 aria-hidden className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={clsx(
        "min-h-9 w-full rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm placeholder:text-muted",
        props.className,
      )}
    />
  );
}

export function Field({ label, htmlFor, hint, children }: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

// Status is always shown as icon + text, never colour alone (colour-blind safe).
const STATUS_STYLE: Record<string, { cls: string; Icon: typeof CheckCircle2; label: string }> = {
  OK: { cls: "text-ok border-ok/40 bg-ok/10", Icon: CheckCircle2, label: "OK" },
  AIRWORTHY: { cls: "text-ok border-ok/40 bg-ok/10", Icon: CheckCircle2, label: "Airworthy" },
  DUE_SOON: { cls: "text-warn border-warn/40 bg-warn/10", Icon: AlertTriangle, label: "Due soon" },
  ATTENTION: { cls: "text-warn border-warn/40 bg-warn/10", Icon: AlertTriangle, label: "Attention" },
  WARNING: { cls: "text-warn border-warn/40 bg-warn/10", Icon: AlertTriangle, label: "Warning" },
  OVERDUE: { cls: "text-danger border-danger/40 bg-danger/10", Icon: OctagonX, label: "Overdue" },
  GROUNDED: { cls: "text-danger border-danger/40 bg-danger/10", Icon: OctagonX, label: "Grounded" },
  CRITICAL: { cls: "text-danger border-danger/40 bg-danger/10", Icon: OctagonX, label: "Critical" },
};

export function StatusBadge({ status }: { status: DueStatus | Airworthiness | string }) {
  const s = STATUS_STYLE[status] ?? { cls: "text-info border-info/40 bg-info/10", Icon: CircleAlert, label: status };
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium whitespace-nowrap", s.cls)}>
      <s.Icon aria-hidden className="size-3.5" />
      {s.label}
    </span>
  );
}

export function Tag({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "info" | "warn" | "danger" | "ok" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
        tone === "muted" && "bg-surface-2 text-muted",
        tone === "info" && "bg-info/10 text-info",
        tone === "warn" && "bg-warn/10 text-warn",
        tone === "danger" && "bg-danger/10 text-danger",
        tone === "ok" && "bg-ok/10 text-ok",
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-muted">
      <Loader2 aria-hidden className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const msg = error instanceof ApiError ? error.message : "Something went wrong. Is the API running?";
  return (
    <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-4 text-sm text-danger">
      {msg}
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="p-6 text-center text-sm text-muted">{children}</p>;
}

export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th scope="col" className={clsx("border-b border-border px-3 py-2 text-xs font-semibold tracking-wide text-muted uppercase", className)}>
      {children}
    </th>
  );
}

export function Td({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <td className={clsx("border-b border-border/60 px-3 py-2 align-top", className)}>{children}</td>;
}

export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";

export const fmtDateTime = (s: string | null | undefined) =>
  s
    ? new Date(s).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";

export const fmtNum = (s: string | number | null | undefined, digits = 1) =>
  s === null || s === undefined || s === "" ? "—" : Number(s).toLocaleString("en-GB", { maximumFractionDigits: digits });
