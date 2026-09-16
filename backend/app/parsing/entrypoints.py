"""Entry-point detection from the code map plus manifest hints from the scan."""

from __future__ import annotations

import re

from app.parsing.codemap import CodeMap, EntryPoint, Symbol
from app.pipeline.scan import EntryHint

ROUTE_DECORATOR = re.compile(
    r"^(?:\w+\.)*(?:route|get|post|put|delete|patch|options|head|api_route|websocket)\s*\(",
    re.IGNORECASE,
)
ROUTE_ANNOTATION = re.compile(
    r"^(?:Get|Post|Put|Delete|Patch|Request)Mapping|^Http(?:Get|Post|Put|Delete|Patch)|^Route\(",
)
ROUTE_CALL_METHODS = frozenset(
    {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "all",
        "use",
        "route",
        "handle",
        "handlefunc",
        "handle_func",
        "any",
    }
)
ROUTE_RECEIVERS = re.compile(
    r"(app|router|route|routes|api|server|mux|r|e|g|bp|blueprint|http|\$app|fastify)$",
    re.IGNORECASE,
)
CLI_DECORATOR = re.compile(r"^(?:\w+\.)*(?:command|group|cli|argument|option)\s*\(?", re.IGNORECASE)
CLI_CALLS = frozenset(
    {"ArgumentParser", "command", "parse_args", "Command", "Typer", "cobra.Command"}
)
TASK_DECORATOR = re.compile(
    r"(task|shared_task|celery|job|consumer|subscribe|listener|EventListener|KafkaListener|RabbitListener|on_event|receiver)",
    re.IGNORECASE,
)
CRON_DECORATOR = re.compile(r"(scheduled|periodic|cron|schedule)", re.IGNORECASE)
CRON_CALLS = frozenset({"schedule", "setInterval", "every", "cron", "AddCronJob", "AddFunc"})
EVENT_CALLS = frozenset({"on", "addEventListener", "subscribe", "consume", "listen_to"})
SERVER_CALLS = frozenset(
    {
        "listen",
        "ListenAndServe",
        "ListenAndServeTLS",
        "serve",
        "run",
        "run_forever",
        "createServer",
        "Run",
        "start",
        "Start",
        "bind",
        "app_run",
        "runserver",
        "run_app",
        "serve_forever",
        "RunAsync",
    }
)
SERVER_RECEIVERS = re.compile(
    r"(app|server|uvicorn|http|https|hypercorn|gunicorn|application|SpringApplication|Host|builder|HttpServer|actix|Server|web)$",
    re.IGNORECASE,
)
FRONTEND_ROOT_CALLS = frozenset(
    {"createRoot", "hydrateRoot", "render", "createApp", "mount", "bootstrapApplication"}
)
FRONTEND_FILES = re.compile(r"(^|/)(page|layout|route|App|main|index|_app)\.(tsx|jsx|ts|js)$")
MAIN_NAMES = frozenset({"main", "Main"})


def _first_call_line(sym: Symbol) -> int:
    return sym.start_line


def detect_entry_points(cm: CodeMap, hints: list[EntryHint]) -> list[EntryPoint]:
    eps: list[EntryPoint] = []
    seen: set[tuple[str, str, int]] = set()

    def add(
        kind: str, file: str, line: int, symbol_id: str | None = None, detail: str = ""
    ) -> None:
        key = (kind, file, line)
        if key in seen:
            return
        seen.add(key)
        eps.append(
            EntryPoint(kind=kind, file=file, line=line, symbol_id=symbol_id, detail=detail[:200])
        )

    for path, fm in cm.files.items():
        for guard in fm.main_guards:
            add("main_guard", path, guard.start_line, None, 'if __name__ == "__main__"')
        for call in fm.top_level_calls:
            recv = (call.receiver or "").rsplit(".", 1)[-1]
            if call.name.lower() in ROUTE_CALL_METHODS and ROUTE_RECEIVERS.search(recv):
                handler = call.arg_resolved[0] if call.arg_resolved else None
                add("route", path, call.line, handler, f"{call.receiver}.{call.name}(...)")
            elif call.name in SERVER_CALLS and (
                SERVER_RECEIVERS.search(recv) or call.name in ("ListenAndServe", "createServer")
            ):
                add(
                    "server_start",
                    path,
                    call.line,
                    None,
                    f"{call.receiver + '.' if call.receiver else ''}{call.name}(...)",
                )
            elif call.name in FRONTEND_ROOT_CALLS and fm.language in ("javascript", "typescript"):
                add("frontend_root", path, call.line, None, f"{call.name}(...)")
            elif call.name in CRON_CALLS:
                add("cron", path, call.line, None, f"{call.name}(...)")
            elif call.name in EVENT_CALLS and call.receiver:
                add("event_handler", path, call.line, None, f"{call.receiver}.{call.name}(...)")
            elif call.name in CLI_CALLS:
                add("cli", path, call.line, None, f"{call.name}(...)")
        if fm.language == "csharp" and not fm.symbols and fm.top_level_calls:
            add("main_function", path, 1, None, "top-level statements")
        if fm.language in ("javascript", "typescript") and FRONTEND_FILES.search(path):
            exported = [
                cm.symbols[s] for s in fm.symbols if s in cm.symbols and cm.symbols[s].is_exported
            ]
            if exported:
                s0 = exported[0]
                kind = (
                    "frontend_page"
                    if re.search(r"(page|layout|route|_app)\.", path)
                    else "frontend_root"
                )
                add(kind, path, s0.start_line, s0.id, s0.name)

    for sym in cm.symbols.values():
        if sym.kind == "class":
            continue
        if (sym.name in MAIN_NAMES and sym.kind == "function") or (
            sym.name in MAIN_NAMES
            and sym.kind == "method"
            and cm.files[sym.file].language in ("java", "csharp")
        ):
            add("main_function", sym.file, sym.start_line, sym.id, sym.qualname)
        for dec in sym.decorators:
            if ROUTE_DECORATOR.search(dec) or ROUTE_ANNOTATION.search(dec):
                add("route", sym.file, sym.start_line, sym.id, dec)
            elif CLI_DECORATOR.search(dec) and re.search(
                r"(click|typer|app|cli|command|group)", dec, re.IGNORECASE
            ):
                add("cli", sym.file, sym.start_line, sym.id, dec)
            elif TASK_DECORATOR.search(dec):
                add("event_handler", sym.file, sym.start_line, sym.id, dec)
            elif CRON_DECORATOR.search(dec):
                add("cron", sym.file, sym.start_line, sym.id, dec)
        for call in sym.calls:
            recv = (call.receiver or "").rsplit(".", 1)[-1]
            if (
                call.name in SERVER_CALLS
                and SERVER_RECEIVERS.search(recv)
                and sym.name in MAIN_NAMES | {"start", "serve", "create_app", "run"}
            ):
                add(
                    "server_start", sym.file, call.line, sym.id, f"{call.receiver}.{call.name}(...)"
                )
            elif (
                call.name.lower() in ROUTE_CALL_METHODS
                and ROUTE_RECEIVERS.search(recv)
                and call.arg_resolved
            ):
                add(
                    "route",
                    sym.file,
                    call.line,
                    call.arg_resolved[0],
                    f"{call.receiver}.{call.name}(...)",
                )

    for hint in hints:
        target = _hint_target(cm, hint)
        add(f"manifest:{hint.kind}", target or hint.file, 1, None, hint.detail)
    order = {
        "main_guard": 0,
        "main_function": 1,
        "server_start": 2,
        "route": 3,
        "cli": 4,
        "frontend_root": 5,
        "frontend_page": 6,
        "event_handler": 7,
        "cron": 8,
    }
    eps.sort(key=lambda e: (order.get(e.kind, 9), e.file, e.line))
    return eps


def _hint_target(cm: CodeMap, hint: EntryHint) -> str | None:
    tokens: list[str] = re.findall(
        r"[\w./-]+\.(?:py|js|ts|tsx|jsx|mjs|go|rb|php|rs|java|cs)", hint.detail
    )
    base = hint.file.rsplit("/", 1)[0] + "/" if "/" in hint.file else ""
    for tok in tokens:
        cand = str(tok).lstrip("./")
        for path in (base + cand, cand):
            if path in cm.files:
                return path
    m = re.search(r"([\w.]+):(\w+)", hint.detail)
    if m:
        mod = str(m.group(1)).replace(".", "/") + ".py"
        hits: list[str] = [p for p in cm.files if p.endswith(mod)]
        if len(hits) == 1:
            return hits[0]
    return None
