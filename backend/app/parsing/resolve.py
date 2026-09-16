"""Resolve imports to project files and call sites to project symbols.

Static only. A call is resolved when exactly one candidate is defensible (local definition,
imported name, ``self``/``this`` method, or a project-wide unique name). Anything ambiguous stays
unresolved — the graph says "unknown" rather than guessing.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict

from app.parsing.codemap import FileMap, Import, Symbol

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
INDEX_NAMES = tuple(f"index{ext}" for ext in JS_EXTS)


class Resolver:
    def __init__(self, files: dict[str, FileMap], symbols: dict[str, Symbol]) -> None:
        self.files = files
        self.symbols = symbols
        self.file_set = set(files)
        self.by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.by_file_name: dict[tuple[str, str], list[Symbol]] = defaultdict(list)
        for sym in symbols.values():
            self.by_name[sym.name].append(sym)
            self.by_file_name[(sym.file, sym.name)].append(sym)
        self.methods_by_class: dict[str, dict[str, Symbol]] = defaultdict(dict)
        for sym in symbols.values():
            if sym.parent:
                self.methods_by_class[sym.parent].setdefault(sym.name, sym)
        self.py_roots = self._python_roots()
        self.dir_set = {posixpath.dirname(p) for p in files} | {""}

    # ---------------------------------------------------------------- imports
    def _python_roots(self) -> list[str]:
        """Candidate roots for absolute Python imports: repo root plus common source dirs."""
        roots = {""}
        for path in self.files:
            parts = path.split("/")
            for i in range(1, min(len(parts), 4)):
                prefix = "/".join(parts[:i])
                if parts[i - 1] in ("src", "lib", "app", "backend", "server", "api") or any(
                    f"{prefix}/{m}" in self.file_set for m in ("__init__.py", "main.py", "app.py")
                ):
                    roots.add(prefix)
        return sorted(roots, key=len)

    def _exists(self, candidate: str) -> str | None:
        norm = posixpath.normpath(candidate)
        return norm if norm in self.file_set else None

    def resolve_import(self, importer: str, imp: Import) -> str | None:
        lang = self.files[importer].language
        module = imp.module
        base = posixpath.dirname(importer)
        if lang == "python":
            return self._resolve_python(base, module)
        if lang in ("javascript", "typescript"):
            return self._resolve_js(base, module)
        if lang == "go":
            tail = module.rstrip("/").rsplit("/", 1)[-1]
            dirs = [d for d in self.dir_set if d.rsplit("/", 1)[-1] == tail and d]
            if len(dirs) == 1:
                return next((p for p in sorted(self.file_set) if p.startswith(dirs[0] + "/")), None)
            return None
        if lang in ("c", "cpp"):
            return self._exists(posixpath.join(base, module)) or self._suffix_match(module)
        if lang == "java":
            return self._suffix_match(module.replace(".", "/") + ".java")
        if lang == "csharp":
            return None  # namespaces do not map to files without a project model
        if lang == "ruby":
            for cand in (module, module + ".rb"):
                hit = self._exists(posixpath.join(base, cand)) or self._suffix_match(cand)
                if hit:
                    return hit
            return None
        if lang == "php":
            if module.endswith(".php"):
                return self._exists(posixpath.join(base, module)) or self._suffix_match(module)
            return self._suffix_match(module.replace("\\", "/") + ".php")
        if lang == "rust":
            return self._resolve_rust(base, module)
        return None

    def _suffix_match(self, suffix: str) -> str | None:
        suffix = suffix.lstrip("/")
        hits = [p for p in self.file_set if p == suffix or p.endswith("/" + suffix)]
        return hits[0] if len(hits) == 1 else None

    def _resolve_python(self, base: str, module: str) -> str | None:
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            rest = module.lstrip(".")
            directory = base
            for _ in range(dots - 1):
                directory = posixpath.dirname(directory)
            rel = rest.replace(".", "/")
            candidates = [
                posixpath.join(directory, rel + ".py"),
                posixpath.join(directory, rel, "__init__.py"),
            ]
            if not rel:
                candidates = [posixpath.join(directory, "__init__.py")]
            for c in candidates:
                hit = self._exists(c)
                if hit:
                    return hit
            return None
        rel = module.replace(".", "/")
        for root in self.py_roots:
            for c in (posixpath.join(root, rel + ".py"), posixpath.join(root, rel, "__init__.py")):
                hit = self._exists(c)
                if hit:
                    return hit
        # "from pkg.mod import name" where the last segment is a symbol, not a module
        if "." in module:
            parent = module.rsplit(".", 1)[0].replace(".", "/")
            for root in self.py_roots:
                hit = self._exists(posixpath.join(root, parent + ".py"))
                if hit:
                    return hit
        return None

    def _resolve_js(self, base: str, module: str) -> str | None:
        if module.startswith("."):
            target = posixpath.normpath(posixpath.join(base, module))
        elif module.startswith(("@/", "~/")):
            target = module[2:]
            for root in ("src", "app", ""):
                hit = self._resolve_js_target(posixpath.join(root, target))
                if hit:
                    return hit
            return None
        else:
            return None  # bare specifier = external package
        return self._resolve_js_target(target)

    def _resolve_js_target(self, target: str) -> str | None:
        hit = self._exists(target)
        if hit:
            return hit
        stem = target
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
        for ext in JS_EXTS:
            hit = self._exists(stem + ext)
            if hit:
                return hit
        for idx in INDEX_NAMES:
            hit = self._exists(posixpath.join(stem, idx))
            if hit:
                return hit
        return None

    def _resolve_rust(self, base: str, module: str) -> str | None:
        if module.startswith("mod "):
            name = module[4:]
            for c in (posixpath.join(base, name + ".rs"), posixpath.join(base, name, "mod.rs")):
                hit = self._exists(c)
                if hit:
                    return hit
            return None
        parts = [
            p
            for p in module.replace("crate::", "").replace("self::", "").split("::")
            if p and p not in ("*", "super")
        ]
        if not parts:
            return None
        for n in range(len(parts), 0, -1):
            rel = "/".join(parts[:n])
            for c in (
                posixpath.join("src", rel + ".rs"),
                posixpath.join("src", rel, "mod.rs"),
                posixpath.join(base, rel + ".rs"),
            ):
                hit = self._exists(c)
                if hit:
                    return hit
        return None

    def resolve_all_imports(self) -> None:
        for path, fm in self.files.items():
            for imp in fm.imports:
                imp.resolved_file = self.resolve_import(path, imp)

    # ------------------------------------------------------------------ calls
    def _imported_symbol(self, caller_file: str, name: str) -> Symbol | None:
        fm = self.files[caller_file]
        for imp in fm.imports:
            if not imp.resolved_file:
                continue
            if name in imp.names or imp.alias == name:
                hits = self.by_file_name.get((imp.resolved_file, name), [])
                if hits:
                    return hits[0]
            if name in imp.names and imp.names:
                continue
        # module import: "import util" + util.helper() handled through receiver below
        return None

    def _module_alias_symbol(self, caller_file: str, receiver: str, name: str) -> Symbol | None:
        fm = self.files[caller_file]
        for imp in fm.imports:
            if not imp.resolved_file:
                continue
            alias = imp.alias or imp.module.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
            ns_names = [n[5:] for n in imp.names if n.startswith("* as ")]
            if receiver == alias or receiver in ns_names or receiver in imp.names:
                hits = self.by_file_name.get((imp.resolved_file, name), [])
                if hits:
                    return hits[0]
                if fm.language == "python" and receiver in imp.names:
                    # "from pkg import submodule" then submodule.func()
                    sep = "" if imp.module.endswith(".") else "."
                    sub = self._resolve_python(
                        posixpath.dirname(caller_file), f"{imp.module}{sep}{receiver}"
                    )
                    if sub:
                        hits = self.by_file_name.get((sub, name), [])
                        if hits:
                            return hits[0]
        return None

    def resolve_call(
        self, caller: Symbol | None, caller_file: str, name: str, receiver: str | None
    ) -> str | None:
        # self/this/cls method on the enclosing class
        if (
            caller is not None
            and receiver in ("self", "this", "cls", "$this", "static", "self::")
            and caller.parent
        ):
            hit = self.methods_by_class.get(caller.parent, {}).get(name)
            if hit:
                return hit.id
        if receiver is not None:
            # Class.method / module.function / alias.function
            local = self.by_file_name.get((caller_file, receiver.split(".")[-1]), [])
            for cls in local:
                if cls.kind == "class":
                    m = self.methods_by_class.get(cls.id, {}).get(name)
                    if m:
                        return m.id
            hit_sym = self._module_alias_symbol(caller_file, receiver.split(".")[-1], name)
            if hit_sym:
                return hit_sym.id
            for cls in self.by_name.get(receiver.split(".")[-1], []):
                if cls.kind == "class":
                    m = self.methods_by_class.get(cls.id, {}).get(name)
                    if m and len(self.by_name.get(receiver.split(".")[-1], [])) == 1:
                        return m.id
        # local definition in the same file (functions first, then classes for constructors)
        local = [
            s
            for s in self.by_file_name.get((caller_file, name), [])
            if s.kind != "method" or receiver is None
        ]
        if len(local) == 1:
            return local[0].id
        if local:
            funcs = [s for s in local if s.kind == "function"]
            if len(funcs) == 1:
                return funcs[0].id
        imported = self._imported_symbol(caller_file, name)
        if imported:
            return imported.id
        if receiver is None:
            global_hits = [s for s in self.by_name.get(name, []) if s.kind != "method"]
            if len(global_hits) == 1:
                return global_hits[0].id
        else:
            method_hits = [s for s in self.by_name.get(name, []) if s.kind == "method"]
            if len(method_hits) == 1:
                return method_hits[0].id
        return None

    def _resolve_arg_refs(
        self, caller: Symbol | None, caller_file: str, refs: list[str]
    ) -> list[str]:
        out: list[str] = []
        for ref in refs:
            receiver, _, name = ref.rpartition(".")
            hit = self.resolve_call(caller, caller_file, name, receiver or None)
            if hit and hit not in out:
                out.append(hit)
        return out

    def resolve_all_calls(self) -> None:
        for sym in self.symbols.values():
            for call in sym.calls:
                call.resolved = self.resolve_call(sym, sym.file, call.name, call.receiver)
                call.arg_resolved = self._resolve_arg_refs(sym, sym.file, call.arg_refs)
        for path, fm in self.files.items():
            for call in fm.top_level_calls:
                call.resolved = self.resolve_call(None, path, call.name, call.receiver)
                call.arg_resolved = self._resolve_arg_refs(None, path, call.arg_refs)
