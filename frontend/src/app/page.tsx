"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ModelSpec, Project } from "@/lib/schemas";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { UploadStep } from "@/components/wizard/upload-step";
import { ConnectStep } from "@/components/wizard/connect-step";
import type { ConnectionChoice } from "@/components/wizard/connect-step";
import { EstimateStep } from "@/components/wizard/estimate-step";
import { ProgressStep } from "@/components/wizard/progress-step";

const STEPS = [
  { id: "upload", title: "Upload", blurb: "Drop in a zip of the project" },
  { id: "connect", title: "Connect Claude", blurb: "Your key, your choice of model" },
  { id: "estimate", title: "Check the cost", blurb: "See the price before spending" },
  { id: "analyse", title: "Watch it build", blurb: "Open the flow as soon as it exists" },
] as const;

type StepId = (typeof STEPS)[number]["id"];

export default function HomePage() {
  const [step, setStep] = useState<StepId>("upload");
  const [project, setProject] = useState<Project | null>(null);
  const [choice, setChoice] = useState<ConnectionChoice | null>(null);
  const [models, setModels] = useState<ModelSpec[]>([]);

  useEffect(() => {
    void api
      .getModels()
      .then((result) => setModels(result.models))
      .catch(() => setModels([]));
  }, []);

  const activeIndex = STEPS.findIndex((entry) => entry.id === step);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-8 sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Read code like a map</p>
          <h1 className="mt-1 font-display text-3xl font-semibold sm:text-4xl">
            CodeFlow Explorer
          </h1>
          <p className="mt-2 max-w-xl text-muted">
            Upload a project and get a picture of how it works: where information comes in, what
            happens to it, and what comes out. Open any step to see what is inside, right down to
            the lines of one small function.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/projects"
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-semibold hover:bg-sunken"
          >
            Past projects
          </Link>
          <ThemeToggle />
        </div>
      </header>

      <ol className="grid gap-3 sm:grid-cols-4">
        {STEPS.map((entry, index) => {
          const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "todo";
          return (
            <li
              key={entry.id}
              className={`rounded-[var(--radius)] border px-3 py-2.5 ${
                state === "active" ? "border-accent bg-accent-soft" : "border-border bg-surface"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`flex size-5 items-center justify-center rounded-full text-[10px] font-bold ${
                    state === "done"
                      ? "bg-success-soft text-success"
                      : state === "active"
                        ? "bg-accent text-accent-contrast"
                        : "bg-sunken text-faint"
                  }`}
                >
                  {state === "done" ? "✓" : index + 1}
                </span>
                <p className="font-display text-sm font-semibold">{entry.title}</p>
              </div>
              <p className="mt-1 text-xs text-muted">{entry.blurb}</p>
            </li>
          );
        })}
      </ol>

      <main>
        {step === "upload" ? (
          <UploadStep
            onUploaded={(uploaded) => {
              setProject(uploaded);
              setStep("connect");
            }}
          />
        ) : null}

        {step === "connect" ? (
          <ConnectStep
            initialModels={models}
            onReady={(selection) => {
              setChoice(selection);
              setStep("estimate");
            }}
          />
        ) : null}

        {step === "estimate" && project && choice ? (
          <EstimateStep project={project} choice={choice} onStarted={() => setStep("analyse")} />
        ) : null}

        {step === "analyse" && project ? <ProgressStep projectId={project.id} /> : null}
      </main>

      <footer className="mt-auto border-t border-border pt-4 text-sm text-muted">
        Your code is read as text and never run. Your API key stays on the server and is never
        written to logs.
      </footer>
    </div>
  );
}
