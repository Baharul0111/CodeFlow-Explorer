# CodeFlow Explorer

Upload a project as a `.zip`, connect your own Anthropic API key, and read how the project works
as a flow you can open up — from "where information comes in" down to the individual steps inside
one small function. Every box points at real lines of the code you uploaded.

- **Grounded, not guessed.** tree-sitter builds a map of the real files, functions and calls first.
  Claude may only describe things that map names; any answer that references a file, symbol or
  line that isn't in your upload is rejected and regenerated.
- **Written for people who don't code.** Short titles, plain-English explanations, and edges
  labelled with the actual data that moves ("email + password", not "data").
- **Your key, your bill, your control.** Bring your own Anthropic key, see a cost estimate before
  anything runs, watch the running total, and stop at a limit you set.
- **Shareable.** Copy a link for anyone who can reach your server, or download the whole graph as a
  single HTML file that opens, expands and shows code on any machine, with no server and no internet.
- **Nothing is executed.** Uploaded code is only ever read as text.

---

## Quick start

### Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.12+ is installed for you by uv)
- Node 20+ and [pnpm](https://pnpm.io/)
- An Anthropic API key — see "Getting an API key" below

### Run it

```bash
cp .env.example .env     # optional: every value has a sensible default
make install             # backend deps, frontend deps, Playwright's browser
make dev                 # backend on :8000, frontend on :3000
```

Open <http://localhost:3000>.

### Or with Docker

```bash
docker compose up --build
```

The frontend is on <http://localhost:3000> and the API on <http://localhost:8000>. Uploads and the
database live in named volumes, so they survive a restart.

### Try it without a key

Set `LLM_MODE=mock` to run the whole pipeline against a deterministic fake Claude. It produces a
real, grounded graph from your actual code map — useful for demos and for development.

```bash
cd backend && LLM_MODE=mock uv run uvicorn app.main:app --port 8000
```

There are four ready-made projects to try in [`samples/`](samples). Build their zips with
`make samples`, then upload one from `samples/dist/`.

---

## Getting an API key

1. Sign in at <https://platform.claude.com>.
2. Open **Settings → API keys** and create a key (it starts with `sk-ant-`).
3. Add credits under **Billing** — a new key with no credits cannot make calls.
4. Paste the key into the Connect step and press **Test connection**. The app fetches the list of
   models your key can actually use and fills the dropdown from it.

The key is held in server memory against an opaque session token. The browser only ever stores the
token. If you tick *Remember key on this server*, the key is encrypted with Fernet (using
`KEY_ENCRYPTION_SECRET`) before it touches disk; **Forget my key** deletes it again. Keys are
redacted from every log line and every error message.

---

## How it works

```
zip ──► safe unzip ──► scan & filter ──► tree-sitter code map ──► summaries ──► flow levels ──► graph
        (limits,       (gitignore,       (files, functions,      (bottom-up,   (Claude, JSON    (React
         zip-slip,      binaries,         calls, imports,         batched)      schema +         Flow +
         bombs)         generated)        entry points)                         grounding)       ELK)
```

1. **Unzip safely.** Path traversal, symlinks, encrypted entries, oversized archives and zip bombs
   are all refused with a plain message.
2. **Scan.** Respects `.gitignore`, skips dependencies, build output, lock files, binaries, media,
   generated and minified files, and anything over 1 MB. Detects languages, frameworks and the
   ways the program can start.
3. **Build a code map — zero tokens.** tree-sitter parses Python, JavaScript, TypeScript (incl.
   JSX/TSX), Java, Go, C, C++, C#, Ruby, PHP and Rust into files, classes, functions, parameters,
   return types, docstrings, call sites and imports. Calls are resolved to real symbols only when
   that can be done unambiguously; anything else is marked unknown rather than guessed.
4. **Summarise bottom-up.** One short summary per function, then per file, then per folder. Higher
   levels read summaries, never raw code.
5. **Generate the flow.** Level 0 is the whole system: start node(s), the main stages, output
   node(s). Expanding a node asks Claude to break it down using only a menu of real code units.
   Function-level nodes expand into steps tied to line numbers.
6. **Validate.** Children must cover all of the parent's code, ids must come from the menu, and
   line ranges must sit inside the real function. Problems trigger at most two repair calls that
   send only the error — never the whole context again.

Full design, including the alternatives that were rejected: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Sharing a graph

The graph screen has four ways out, from most to least interactive:

| Button | What you get | Who can open it |
|---|---|---|
| **Copy link** | `…/projects/<id>/graph` | Anyone who can reach your server — live, always current |
| **Share as page** | One `.html` file (a few hundred KB) holding the whole graph, every code snippet and a small viewer | Anyone, anywhere. No server, no internet, no install — double-click it |
| **PNG** | A picture of the current view | Anyone, for a slide or a ticket |
| **JSON** | Nodes and edges, for your own tooling | Anything that reads JSON |

The **shared page** is the one to send to someone who doesn't have the app. Inside it they can pan
and zoom, open and close any step, open everything at once, search, read the same plain-English
explanations, and see the real code with line numbers — exactly what the node points at. It is a
snapshot: it never phones home, and it does not update when you analyse more levels. Re-export to
share a newer version.

---

## What it costs, and how the cost is kept down

Before anything runs you get an estimate built from **real token counts** (Anthropic's
`count_tokens` on a representative sample of your code, extrapolated over the number of calls the
pipeline will make). During the run, the header shows input, output, cache-write and cache-read
tokens with a running dollar total. Prices per model live in
[`backend/config/models.json`](backend/config/models.json) — edit them there, never in code.

Token-saving measures, in rough order of impact:

| Measure | Effect |
|---|---|
| Static analysis first | The entire code map — files, functions, calls, entry points — costs nothing |
| Summaries flow upward | Raw code is only ever sent at function level, and only that function's lines |
| Prompt caching | Two cached system blocks (global rules, project context) are reused by every call |
| Batching | Up to 12 function summaries per call instead of one call each |
| Trivial-function skip | Getters, setters and one-liners are described from static data, with no call |
| Structured outputs | A strict JSON schema means no prose, no retries for format, tight `max_tokens` |
| Content-hash cache | Identical code — across projects or a re-upload — is free |
| Smart mix | Cheap model for the many small deep calls, your chosen model for the big picture |
| Cost limit | Analysis pauses and asks before passing `MAX_COST_PER_PROJECT_USD` |

Reopening an analysed project reads from SQLite and costs **nothing**.

---

## Configuration

Copy `.env.example` to `.env`. Everything has a default.

| Setting | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Optional, local dev only: pre-fills the Connect screen |
| `DEFAULT_MODEL_FALLBACKS` | opus 5, sonnet 5, haiku 4.5 | Models shown before a key is tested |
| `MAX_UPLOAD_MB` | 200 | Largest zip accepted |
| `MAX_UNZIPPED_MB` | 1024 | Largest unpacked size |
| `MAX_FILES` | 20000 | Most files in one project |
| `MAX_COST_PER_PROJECT_USD` | 5 | Spend guard; analysis pauses here |
| `LLM_CONCURRENCY` | 4 | Claude calls in flight at once |
| `BACKGROUND_MAX_NODES` | 200 | Nodes pre-built before switching to on-demand |
| `KEY_ENCRYPTION_SECRET` | auto | Encrypts remembered keys; generated into `workspace/` if unset |
| `DATABASE_URL` | SQLite file | Where projects, nodes and usage are stored |
| `WORKSPACE_RETENTION_DAYS` | 7 | Uploads older than this are deleted at startup |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | The only origin CORS allows |
| `LLM_MODE` | `anthropic` | `mock` runs the pipeline with a deterministic fake Claude |

---

## Commands

| Task | Command |
|---|---|
| Install everything | `make install` |
| Run both servers | `make dev` |
| Backend tests | `make test-backend` |
| Playwright end-to-end | `make e2e` |
| Lint + types (both sides) | `make lint` |
| Everything CI runs | `make check` |
| Format | `make fmt` |
| Rebuild sample zips | `make samples` |

---

## Security

- Uploaded code is **never executed, imported, installed or built** — only read as text and parsed.
- Uploaded code is treated as untrusted data. Prompts tell Claude to ignore any instructions found
  inside it, and model output can only ever become validated graph JSON.
- Zip defences: path traversal, absolute paths, symlinks and device files, encrypted entries, entry
  count, declared size, per-file and whole-archive compression ratio, plus a streaming byte counter
  that catches headers that lie about their size.
- Snippets are served only from inside the project's own workspace, after path normalisation.
- CORS is locked to `FRONTEND_ORIGIN`; secure headers on every response; uploads and analysis are
  rate limited per session or IP.
- API keys never appear in logs, error messages, API responses, or the browser after entry.

---

## Limitations

- **Static analysis only.** Calls made through dynamic dispatch, reflection, dependency injection
  or string-built names cannot be resolved, and are marked unknown rather than guessed.
- **Languages without a grammar** (Kotlin, Swift, Scala, Elixir, shell, …) are still summarised
  from their text, but get no function- or step-level detail.
- **Very large projects** are bounded by `MAX_FILES` and by `BACKGROUND_MAX_NODES`; beyond that,
  levels are generated when you click them rather than up front.
- **Quality follows the model.** A cheap model on deep levels is usually indistinguishable at the
  top; turn Smart mix off if you want one model everywhere.
- **One server, one process.** SQLite and an in-process job queue are deliberate choices for a
  single-node, bring-your-own-key tool; the storage and job interfaces are the seams to replace if
  that ever changes.
- **Not a security tool.** The graph describes what the code appears to do; it does not audit it.
