"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-contrast hover:bg-accent-hover disabled:bg-border disabled:text-faint",
  secondary:
    "border border-border bg-surface text-text hover:border-border-strong hover:bg-sunken disabled:text-faint",
  ghost: "text-muted hover:bg-sunken hover:text-text",
  danger: "border border-danger/30 bg-danger-soft text-danger hover:border-danger/60",
};

export function Button({
  variant = "primary",
  className = "",
  loading = false,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled ?? loading}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Working"
      className={`inline-block size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

export function Card({
  children,
  className = "",
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "li";
}) {
  return (
    <Tag
      className={`rounded-[var(--radius)] border border-border bg-surface shadow-[var(--shadow-sm)] ${className}`}
    >
      {children}
    </Tag>
  );
}

export function Field({
  label,
  hint,
  htmlFor,
  children,
  error,
}: {
  label: string;
  hint?: ReactNode;
  htmlFor: string;
  children: ReactNode;
  error?: string | null;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-semibold text-text">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-sm text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function Alert({
  tone = "error",
  title,
  children,
}: {
  tone?: "error" | "warning" | "success" | "info";
  title?: string;
  children: ReactNode;
}) {
  const tones = {
    error: "border-danger/30 bg-danger-soft text-danger",
    warning: "border-warning/30 bg-warning-soft text-warning",
    success: "border-success/30 bg-success-soft text-success",
    info: "border-border bg-sunken text-muted",
  } as const;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border px-3 py-2.5 text-sm ${tones[tone]}`}
    >
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-0.5" : ""}>{children}</div>
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "Progress"}
      className="h-2 w-full overflow-hidden rounded-full bg-sunken"
    >
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatUsd(value: number): string {
  if (value === 0) return "$0.00";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokens(value: number): string {
  if (value < 1000) return `${value}`;
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)}k`;
  return `${(value / 1_000_000).toFixed(2)}M`;
}
