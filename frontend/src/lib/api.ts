"use client";

import type { z } from "zod";
import { getSessionToken } from "./session";
import {
  apiErrorSchema,
  estimateResponseSchema,
  graphSchema,
  modelsSchema,
  projectListItemSchema,
  projectSchema,
  searchHitSchema,
  snippetSchema,
  startSchema,
  testKeySchema,
  usageSchema,
} from "./schemas";
import type { Graph, ModelSpec, Project } from "./schemas";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/** An error carrying a message already written for a non-programmer. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function headers(extra?: HeadersInit): HeadersInit {
  const token = getSessionToken();
  return {
    ...(extra ?? {}),
    ...(token ? { "X-Session-Token": token } : {}),
  };
}

async function toError(response: Response): Promise<ApiError> {
  let message = "Something went wrong. Please try again.";
  let code = "error";
  try {
    const parsed = apiErrorSchema.safeParse(await response.json());
    if (parsed.success) {
      message = parsed.data.error.message;
      code = parsed.data.error.code;
    }
  } catch {
    /* keep the default message */
  }
  return new ApiError(message, code, response.status);
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit & { raw?: boolean },
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: headers(init?.headers),
  });
  if (!response.ok) throw await toError(response);
  return schema.parse(await response.json());
}

export const api = {
  async uploadProject(file: File, onProgress?: (fraction: number) => void): Promise<Project> {
    // XHR rather than fetch: upload progress is what makes a 50 MB zip bearable.
    return new Promise<Project>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_URL}/api/projects`);
      const token = getSessionToken();
      if (token) xhr.setRequestHeader("X-Session-Token", token);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        try {
          const body: unknown = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(projectSchema.parse(body));
            return;
          }
          const parsed = apiErrorSchema.safeParse(body);
          reject(
            new ApiError(
              parsed.success ? parsed.data.error.message : "Upload failed.",
              parsed.success ? parsed.data.error.code : "upload_failed",
              xhr.status,
            ),
          );
        } catch {
          reject(new ApiError("Upload failed.", "upload_failed", xhr.status));
        }
      };
      xhr.onerror = () => reject(new ApiError("Could not reach the server.", "offline", 0));
      xhr.send(form);
    });
  },

  getProject: (id: string) => request(`/api/projects/${id}`, projectSchema),

  listProjects: () => request("/api/projects", projectListItemSchema.array()),

  deleteProject: async (id: string): Promise<void> => {
    const response = await fetch(`${API_URL}/api/projects/${id}`, {
      method: "DELETE",
      headers: headers(),
    });
    if (!response.ok) throw await toError(response);
  },

  testKey: (apiKey: string, remember: boolean) =>
    request("/api/keys/test", testKeySchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey, remember }),
    }),

  getModels: (): Promise<{ models: ModelSpec[]; source: string }> =>
    request("/api/keys/models", modelsSchema),

  forgetKey: async (): Promise<void> => {
    await fetch(`${API_URL}/api/keys/forget`, { method: "POST", headers: headers() });
  },

  estimate: (projectId: string, body: EstimateBody) =>
    request(`/api/projects/${projectId}/analysis/estimate`, estimateResponseSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  startAnalysis: (projectId: string, body: EstimateBody) =>
    request(`/api/projects/${projectId}/analysis/start`, startSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  cancelAnalysis: async (projectId: string): Promise<void> => {
    await fetch(`${API_URL}/api/projects/${projectId}/analysis/cancel`, {
      method: "POST",
      headers: headers(),
    });
  },

  usage: (projectId: string) => request(`/api/projects/${projectId}/analysis/usage`, usageSchema),

  getGraph: (projectId: string): Promise<Graph> =>
    request(`/api/projects/${projectId}/graph`, graphSchema),

  expandNode: (projectId: string, nodeId: string): Promise<Graph> =>
    request(`/api/projects/${projectId}/graph/nodes/${nodeId}/expand`, graphSchema, {
      method: "POST",
    }),

  search: (projectId: string, query: string) =>
    request(
      `/api/projects/${projectId}/graph/search?q=${encodeURIComponent(query)}`,
      searchHitSchema.array(),
    ),

  snippet: (projectId: string, file: string, startLine: number, endLine: number) =>
    request(
      `/api/projects/${projectId}/graph/snippet?file=${encodeURIComponent(file)}&start_line=${startLine}&end_line=${endLine}`,
      snippetSchema,
    ),

  exportUrl: (projectId: string) => `${API_URL}/api/projects/${projectId}/graph/export`,

  /** A single HTML file holding the whole graph, its snippets and a viewer — works offline. */
  exportPageUrl: (projectId: string) => `${API_URL}/api/projects/${projectId}/graph/export.html`,
};

export interface EstimateBody {
  model_id: string;
  smart_mix: boolean;
  deep_model_id?: string | null;
  cost_limit_usd?: number | null;
}

export interface ProgressEvent {
  type: string;
  data: Record<string, unknown>;
}

/** Subscribe to the live analysis stream. Returns an unsubscribe function. */
export function subscribeToProgress(
  projectId: string,
  onEvent: (event: ProgressEvent) => void,
): () => void {
  const source = new EventSource(`${API_URL}/api/projects/${projectId}/analysis/events`);
  const types = [
    "stage",
    "progress",
    "nodes",
    "usage",
    "graph_ready",
    "done",
    "error",
    "cancelled",
    "limit_reached",
    "node_generating",
    "node_error",
  ];
  const handlers = types.map((type) => {
    const handler = (event: MessageEvent<string>) => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        /* an event with no payload is still meaningful */
      }
      onEvent({ type, data });
    };
    source.addEventListener(type, handler as EventListener);
    return { type, handler };
  });
  return () => {
    handlers.forEach(({ type, handler }) =>
      source.removeEventListener(type, handler as EventListener),
    );
    source.close();
  };
}
