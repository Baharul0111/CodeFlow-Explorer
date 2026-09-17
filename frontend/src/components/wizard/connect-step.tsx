"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ModelSpec } from "@/lib/schemas";
import { clearSessionToken, getSessionToken, saveSessionToken } from "@/lib/session";
import { Alert, Button, Card, Field, formatUsd } from "@/components/ui/primitives";

export interface ConnectionChoice {
  modelId: string;
  deepModelId: string | null;
  smartMix: boolean;
  models: ModelSpec[];
}

const KEY_HELP_URL = "https://platform.claude.com/settings/keys";

function priceLine(model: ModelSpec): string {
  if (model.input_price === null || model.output_price === null) return "";
  return `${formatUsd(model.input_price)} in / ${formatUsd(model.output_price)} out per million tokens`;
}

export function ConnectStep({
  onReady,
  initialModels,
}: {
  onReady: (choice: ConnectionChoice) => void;
  initialModels: ModelSpec[];
}) {
  const [apiKey, setApiKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [models, setModels] = useState<ModelSpec[]>(initialModels);
  const [modelId, setModelId] = useState(initialModels[0]?.id ?? "");
  const [smartMix, setSmartMix] = useState(true);
  const [deepModelId, setDeepModelId] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    // A remembered key means we can populate the live model list without asking again.
    if (!getSessionToken()) return;
    void (async () => {
      try {
        const result = await api.getModels();
        if (result.source === "api") {
          setModels(result.models);
          setModelId((current) => current || (result.models[0]?.id ?? ""));
          setConnected(true);
          setNotice("Using the key remembered on this server.");
        }
      } catch {
        /* fall back to the list we already have */
      }
    })();
  }, []);

  const test = async () => {
    setTesting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.testKey(apiKey.trim(), remember);
      saveSessionToken(result.session_token, remember);
      setModels(result.models);
      setModelId(result.suggested_model ?? result.models[0]?.id ?? "");
      setDeepModelId(result.suggested_deep_model);
      setFingerprint(result.key_fingerprint);
      setConnected(true);
      setApiKey("");
      setNotice(`Connected. ${result.models.length} models available.`);
    } catch (err) {
      setConnected(false);
      setError(err instanceof ApiError ? err.message : "Could not test this key.");
    } finally {
      setTesting(false);
    }
  };

  const forget = async () => {
    await api.forgetKey();
    clearSessionToken();
    setConnected(false);
    setFingerprint(null);
    setNotice("Key forgotten. Paste a key to connect again.");
  };

  const chosen = models.find((model) => model.id === modelId);
  const deep = smartMix ? (deepModelId ?? cheapest(models)?.id ?? null) : null;

  return (
    <div className="flex flex-col gap-5">
      <Card className="flex flex-col gap-4 p-5">
        <Field
          label="Anthropic API key"
          htmlFor="api-key"
          error={error}
          hint={
            <>
              Used only on this server to talk to Claude, and never sent back to your browser.{" "}
              <a
                className="font-medium text-accent underline"
                href={KEY_HELP_URL}
                target="_blank"
                rel="noreferrer"
              >
                Where do I get one?
              </a>
            </>
          }
        >
          <div className="flex flex-wrap gap-2">
            <input
              id="api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={
                connected ? `Connected (key ending ${fingerprint ?? "****"})` : "sk-ant-…"
              }
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm text-text placeholder:text-faint"
            />
            <Button onClick={test} loading={testing} disabled={apiKey.trim().length < 8}>
              Test connection
            </Button>
          </div>
        </Field>

        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              id="remember-key"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            Remember key on this server (encrypted)
          </label>
          {connected ? (
            <Button variant="ghost" onClick={forget}>
              Forget my key
            </Button>
          ) : null}
        </div>

        {notice ? <Alert tone="success">{notice}</Alert> : null}
      </Card>

      <Card className="flex flex-col gap-4 p-5">
        <Field
          label="Claude model"
          htmlFor="model"
          hint={
            connected
              ? "This list comes from your account."
              : "Default list. Test your key to load the models your account can use."
          }
        >
          <select
            id="model"
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text"
          >
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name} — {model.id}
                {model.hint ? ` · ${model.hint}` : ""}
              </option>
            ))}
          </select>
        </Field>
        {chosen ? <p className="tabular text-sm text-muted">{priceLine(chosen)}</p> : null}

        <div className="flex flex-col gap-2 rounded-lg border border-border bg-sunken p-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              id="smart-mix"
              checked={smartMix}
              onChange={(event) => setSmartMix(event.target.checked)}
              className="mt-0.5 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="font-semibold">Smart mix (recommended)</span>
              <span className="block text-muted">
                Use {chosen?.display_name ?? "the chosen model"} for the big picture and{" "}
                {models.find((m) => m.id === deep)?.display_name ?? "a cheaper model"} for the small
                details. Usually much cheaper, with the same top-level quality.
              </span>
            </span>
          </label>
        </div>

        <Button
          onClick={() => onReady({ modelId, deepModelId: deep, smartMix, models })}
          disabled={!modelId}
          className="self-start"
        >
          Continue
        </Button>
      </Card>
    </div>
  );
}

function cheapest(models: ModelSpec[]): ModelSpec | undefined {
  return [...models]
    .filter((model) => model.input_price !== null)
    .sort((a, b) => (a.input_price ?? 0) - (b.input_price ?? 0))[0];
}
