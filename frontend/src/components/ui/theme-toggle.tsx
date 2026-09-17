"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark" | "system";
const KEY = "codeflow-theme";
const listeners = new Set<() => void>();

function read(): Theme {
  try {
    const saved = window.localStorage.getItem(KEY);
    return saved === "dark" || saved === "light" ? saved : "system";
  } catch {
    return "system";
  }
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

function write(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    if (theme === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, theme);
  } catch {
    /* not persisting is acceptable; the page still switches */
  }
  listeners.forEach((listener) => listener());
}

/** The theme lives in localStorage and on <html>, so it is read as external state. */
export function ThemeToggle() {
  const theme = useSyncExternalStore<Theme>(subscribe, read, () => "system");

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex rounded-lg border border-border bg-surface p-0.5"
    >
      {(["light", "system", "dark"] as const).map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={theme === option}
          onClick={() => write(option)}
          className={`rounded-md px-2 py-1 text-xs font-semibold capitalize transition-colors ${
            theme === option ? "bg-accent-soft text-accent" : "text-muted hover:text-text"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
