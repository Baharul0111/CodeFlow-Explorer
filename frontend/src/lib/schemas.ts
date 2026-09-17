import { z } from "zod";

export const codeRefSchema = z.object({
  file: z.string(),
  start_line: z.number().int(),
  end_line: z.number().int(),
  symbol: z.string().default(""),
});

export const nodeKindSchema = z.enum([
  "start",
  "process",
  "decision",
  "datastore",
  "external",
  "output",
]);

export const nodeSchema = z.object({
  id: z.string(),
  parent_id: z.string().nullable(),
  level: z.number().int(),
  kind: nodeKindSchema,
  title: z.string(),
  explanation: z.string(),
  inputs: z.array(z.string()),
  outputs: z.array(z.string()),
  code_refs: z.array(codeRefSchema),
  has_children: z.boolean(),
  status: z.enum(["pending", "generating", "ready", "error"]),
  scope: z.string(),
  error: z.string().nullable().optional(),
});

export const edgeSchema = z.object({
  id: z.string(),
  parent_id: z.string().nullable(),
  source: z.string(),
  target: z.string(),
  label: z.string(),
  data_shape: z.string(),
  kind: z.enum(["data", "control", "error"]),
});

export const graphSchema = z.object({
  nodes: z.array(nodeSchema),
  edges: z.array(edgeSchema),
  status: z.string(),
});

export const languageStatSchema = z.object({ files: z.number(), lines: z.number() });

export const scanSchema = z.object({
  languages: z.record(z.string(), languageStatSchema),
  file_count: z.number(),
  code_file_count: z.number(),
  function_count: z.number().nullable().optional(),
  class_count: z.number().nullable().optional(),
  skipped_counts: z.record(z.string(), z.number()),
  skipped_examples: z.array(z.object({ path: z.string(), reason: z.string() })),
  frameworks: z.array(z.string()),
  entry_hints: z.array(z.object({ kind: z.string(), file: z.string(), detail: z.string() })),
  readme_excerpt: z.string(),
});

export const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  upload_bytes: z.number(),
  status: z.string(),
  model_id: z.string().nullable(),
  deep_model_id: z.string().nullable(),
  scan: scanSchema.nullable(),
  estimate: z.record(z.string(), z.unknown()).nullable(),
  error: z.string().nullable(),
});

export const projectListItemSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string(),
  status: z.string(),
  model_id: z.string().nullable(),
  file_count: z.number(),
  node_count: z.number(),
  total_cost_usd: z.number(),
});

export const modelSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  tier: z.string(),
  hint: z.string(),
  supports_structured_outputs: z.boolean(),
  supports_effort: z.boolean(),
  max_input_tokens: z.number().nullable(),
  max_output_tokens: z.number().nullable(),
  input_price: z.number().nullable(),
  output_price: z.number().nullable(),
  cache_read_price: z.number().nullable(),
  cache_write_price: z.number().nullable(),
  source: z.enum(["api", "fallback"]),
});

export const testKeySchema = z.object({
  session_token: z.string(),
  key_fingerprint: z.string(),
  models: z.array(modelSchema),
  suggested_model: z.string().nullable(),
  suggested_deep_model: z.string().nullable(),
  remembered: z.boolean(),
});

export const modelsSchema = z.object({
  models: z.array(modelSchema),
  source: z.string(),
});

export const estimateSchema = z.object({
  input_tokens: z.number(),
  output_tokens: z.number(),
  cached_input_tokens: z.number(),
  calls: z.number(),
  low_usd: z.number(),
  high_usd: z.number(),
  top_model: z.string(),
  deep_model: z.string(),
  over_limit: z.boolean(),
  limit_usd: z.number(),
});

export const estimateResponseSchema = z.object({
  estimate: estimateSchema,
  scan: z.object({ function_count: z.number() }),
});

export const startSchema = z.object({
  started: z.boolean(),
  status: z.string(),
  model_id: z.string(),
  deep_model_id: z.string(),
});

export const usageSchema = z.object({
  input_tokens: z.number(),
  output_tokens: z.number(),
  cache_write_tokens: z.number(),
  cache_read_tokens: z.number(),
  cost_usd: z.number(),
  calls: z.number(),
});

export const snippetSchema = z.object({
  file: z.string(),
  start_line: z.number(),
  end_line: z.number(),
  language: z.string(),
  code: z.string(),
});

export const searchHitSchema = z.object({
  node_id: z.string(),
  title: z.string(),
  subtitle: z.string(),
  path: z.array(z.string()),
});

export const apiErrorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

export type CodeRef = z.infer<typeof codeRefSchema>;
export type NodeKind = z.infer<typeof nodeKindSchema>;
export type GraphNode = z.infer<typeof nodeSchema>;
export type GraphEdge = z.infer<typeof edgeSchema>;
export type Graph = z.infer<typeof graphSchema>;
export type Project = z.infer<typeof projectSchema>;
export type ProjectListItem = z.infer<typeof projectListItemSchema>;
export type ModelSpec = z.infer<typeof modelSchema>;
export type TestKeyResult = z.infer<typeof testKeySchema>;
export type Estimate = z.infer<typeof estimateSchema>;
export type Usage = z.infer<typeof usageSchema>;
export type Snippet = z.infer<typeof snippetSchema>;
export type SearchHit = z.infer<typeof searchHitSchema>;
export type Scan = z.infer<typeof scanSchema>;
