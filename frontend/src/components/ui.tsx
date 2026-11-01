import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { classNames } from "../lib/format";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Card({
  children,
  className,
  title,
  hint,
  actions,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  hint?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={classNames("card", className)}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {hint && <p>{hint}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  detail,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "accent" | "warning" | "danger";
}) {
  return (
    <div className={classNames("stat-card", `tone-${tone}`)}>
      <div className="stat-top">
        <span>{label}</span>
        {icon && <span className="stat-icon">{icon}</span>}
      </div>
      <div className="stat-value">{value}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

export type BadgeTone = "neutral" | "green" | "amber" | "red" | "blue" | "violet" | "slate";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={classNames("badge", `badge-${tone}`)}>{children}</span>;
}

export function relationshipTone(value: string): BadgeTone {
  switch (value) {
    case "ADDRESSES":
    case "strong":
    case "accepted":
    case "completed":
    case "succeeded":
      return "green";
    case "PARTIALLY_ADDRESSES":
    case "partial":
    case "running":
    case "ingesting":
    case "extracting":
      return "blue";
    case "queued":
      return "amber";
    case "NEEDS_REVIEW":
    case "needs_review":
    case "validating":
      return "amber";
    case "RELATED_BUT_NOT_SOLVING":
    case "weak":
      return "violet";
    case "NO_CLEAR_RELATIONSHIP":
    case "unsupported":
    case "failed":
      return "red";
    case "CONTRADICTS_OR_OUT_OF_SCOPE":
      return "slate";
    default:
      return "neutral";
  }
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="state-block">
      <LoaderCircle className="spin" size={26} />
      <p>{label || "Loading..."}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-block error">
      <AlertCircle size={26} />
      <p>{message}</p>
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="state-block">
      <Inbox size={26} />
      <p className="strong">{title}</p>
      {detail && <p>{detail}</p>}
    </div>
  );
}

export function Progress({ value, tone = "accent" }: { value: number; tone?: "accent" | "green" | "amber" | "red" }) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="progress">
      <span className={`progress-${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton-stack">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="skeleton" style={{ width: `${90 - index * 9}%` }} key={index} />
      ))}
    </div>
  );
}
