"""Generic tree-sitter extractor: symbols, call sites, imports and main guards for one file.

The walk is iterative (explicit stack) so deeply nested code cannot exceed Python's recursion
limit. Language differences live in :mod:`app.parsing.spec` plus the small ``_name_of`` /
``_call_parts`` / ``_import_of`` helpers below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tree_sitter import Node

from app.parsing.codemap import CallSite, FileMap, Import, MainGuard, Symbol, SymbolKind
from app.parsing.languages import make_parser
from app.parsing.spec import FUNCTION_VALUE_TYPES, SPECS, LanguageSpec

NAME_NODE_TYPES = frozenset(
    {
        "identifier",
        "property_identifier",
        "field_identifier",
        "type_identifier",
        "constant",
        "name",
        "scoped_identifier",
        "qualified_identifier",
        "operator_name",
        "destructor_name",
    }
)
MAX_DOC = 300


@dataclass
class Extraction:
    file: FileMap
    symbols: list[Symbol] = field(default_factory=list)


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _field(node: Node, *names: str) -> Node | None:
    for name in names:
        child = node.child_by_field_name(name)
        if child is not None:
            return child
    return None


def _first_child_of_types(node: Node, types: frozenset[str]) -> Node | None:
    for child in node.named_children:
        if child.type in types:
            return child
    return None


def _declarator_name(node: Node, src: bytes) -> str | None:
    """C/C++: dig through declarators to the identifier."""
    current: Node | None = node
    while current is not None:
        if current.type in NAME_NODE_TYPES:
            return _text(current, src)
        nxt = _field(current, "declarator")
        if nxt is None:
            nxt = _first_child_of_types(
                current,
                frozenset({"function_declarator", "pointer_declarator", "reference_declarator"}),
            )
        current = nxt
    return None


def _name_of(node: Node, spec: LanguageSpec, src: bytes) -> str | None:
    if spec.key in ("c", "cpp") and node.type in spec.function_types:
        decl = _field(node, "declarator")
        return _declarator_name(decl, src) if decl is not None else None
    if node.type in spec.value_function_holders:
        key = _field(node, "name", "key", "left")
        if key is None:
            return None
        text = _text(key, src)
        return text.rsplit(".", 1)[-1]
    name_node = _field(node, "name")
    if name_node is None:
        name_node = _first_child_of_types(node, NAME_NODE_TYPES)
    if name_node is None:
        return (
            "default"
            if node.parent is not None and node.parent.type == "export_statement"
            else None
        )
    return _text(name_node, src)


def _is_value_function(node: Node, spec: LanguageSpec) -> bool:
    if node.type not in spec.value_function_holders:
        return False
    value = _field(node, "value", "right")
    return value is not None and value.type in FUNCTION_VALUE_TYPES


def _def_body(node: Node, spec: LanguageSpec) -> Node | None:
    if node.type in spec.value_function_holders:
        value = _field(node, "value", "right")
        return _field(value, *spec.body_fields) if value is not None else None
    body = _field(node, *spec.body_fields)
    if body is None and spec.key == "java":
        body = _first_child_of_types(node, frozenset({"block", "constructor_body"}))
    return body


def _params_of(node: Node, spec: LanguageSpec, src: bytes) -> str:
    target = node
    if node.type in spec.value_function_holders:
        value = _field(node, "value", "right")
        if value is None:
            return ""
        target = value
    if spec.key in ("c", "cpp"):
        decl = _field(node, "declarator")
        current = decl
        while current is not None and current.type != "function_declarator":
            current = _field(current, "declarator")
        target = current if current is not None else node
    params = _field(target, *spec.param_fields)
    if params is None:
        params = _first_child_of_types(
            target,
            frozenset({"parameters", "formal_parameters", "parameter_list", "method_parameters"}),
        )
    if params is None:
        return ""
    text = " ".join(_text(params, src).split())
    return text[:200]


def _returns_of(node: Node, spec: LanguageSpec, src: bytes) -> str | None:
    target = node
    if node.type in spec.value_function_holders:
        value = _field(node, "value", "right")
        if value is None:
            return None
        target = value
    ret = _field(target, *spec.return_fields)
    if ret is None and spec.key in ("javascript", "typescript", "tsx"):
        for child in target.named_children:
            if (
                child.type == "type_annotation"
                and child.prev_sibling is not None
                and child.prev_sibling.type == "formal_parameters"
            ):
                ret = child
    if ret is None:
        return None
    text = " ".join(_text(ret, src).split()).lstrip(": ").strip()
    return text[:80] or None


def _strip_comment(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^(/\*\*?|\*/|\*|//+|#+|///|--)\s?", "", line).strip()
        line = re.sub(r"\*/$", "", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def _docstring_of(node: Node, spec: LanguageSpec, src: bytes) -> str | None:
    if spec.key == "python":
        body = _field(node, "body")
        if body is not None and body.named_child_count > 0:
            first = body.named_children[0]
            if first.type == "expression_statement" and first.named_child_count > 0:
                inner = first.named_children[0]
                if inner.type == "string":
                    raw = _text(inner, src).strip()
                    raw = re.sub(r'^[rbuRBU]*("""|\'\'\'|"|\')', "", raw)
                    raw = re.sub(r'("""|\'\'\'|"|\')$', "", raw)
                    return " ".join(raw.split())[:MAX_DOC] or None
        return None
    anchor: Node = node
    if anchor.parent is not None and anchor.parent.type in (
        "decorated_definition",
        "export_statement",
        "template_declaration",
    ):
        anchor = anchor.parent
    prev = anchor.prev_named_sibling
    parts: list[str] = []
    while prev is not None and prev.type in spec.comment_types:
        parts.insert(0, _text(prev, src))
        if prev.type in ("block_comment",) or _text(prev, src).startswith("/*"):
            break
        prev = prev.prev_named_sibling
    if not parts:
        return None
    doc = _strip_comment("\n".join(parts))
    return doc[:MAX_DOC] or None


def _decorators_of(node: Node, spec: LanguageSpec, src: bytes) -> list[str]:
    out: list[str] = []
    if not spec.decorator_types:
        return out
    if (
        spec.key == "python"
        and node.parent is not None
        and node.parent.type == "decorated_definition"
    ):
        out.extend(
            _text(c, src).lstrip("@") for c in node.parent.named_children if c.type == "decorator"
        )
    elif spec.key == "java":
        mods = _first_child_of_types(node, frozenset({"modifiers"}))
        if mods is not None:
            out.extend(
                _text(c, src).lstrip("@")
                for c in mods.named_children
                if c.type in spec.decorator_types
            )
    elif spec.key in ("csharp", "php", "rust"):
        for child in node.named_children:
            if child.type in spec.decorator_types:
                out.append(_text(child, src).strip("[]#"))
        prev = node.prev_named_sibling
        while prev is not None and prev.type in spec.decorator_types:
            out.insert(0, _text(prev, src).strip("[]#"))
            prev = prev.prev_named_sibling
    elif spec.key in ("typescript", "tsx", "javascript"):
        prev = node.prev_named_sibling
        while prev is not None and prev.type == "decorator":
            out.insert(0, _text(prev, src).lstrip("@"))
            prev = prev.prev_named_sibling
    return [" ".join(d.split())[:120] for d in out][:8]


def _is_exported(node: Node, spec: LanguageSpec, name: str, src: bytes) -> bool:
    if spec.key in ("javascript", "typescript", "tsx"):
        p = node.parent
        while p is not None and p.type in ("lexical_declaration", "variable_declaration"):
            p = p.parent
        return p is not None and p.type == "export_statement"
    if spec.key == "python":
        return not name.startswith("_")
    if spec.key == "go":
        return name[:1].isupper()
    if spec.key == "rust":
        return _first_child_of_types(node, frozenset({"visibility_modifier"})) is not None
    if spec.key in ("java", "csharp"):
        mods = _first_child_of_types(node, frozenset({"modifiers"}))
        text = _text(mods, src) if mods is not None else _text(node, src)[:80]
        return "public" in text
    return True


def _call_parts(node: Node, spec: LanguageSpec, src: bytes) -> tuple[str | None, str] | None:
    """Return ``(receiver, callee_name)`` for a call node, or None if unrecognisable."""
    key = spec.key
    if key == "java":
        if node.type == "object_creation_expression":
            t = _field(node, "type")
            return (None, _text(t, src).split("<")[0]) if t is not None else None
        name = _field(node, "name")
        obj = _field(node, "object")
        return (
            (_text(obj, src) if obj is not None else None, _text(name, src))
            if name is not None
            else None
        )
    if key == "ruby":
        method = _field(node, "method")
        recv = _field(node, "receiver")
        if method is None:
            return None
        return (_text(recv, src) if recv is not None else None, _text(method, src))
    if key == "php":
        if node.type == "object_creation_expression":
            for child in node.named_children:
                if child.type in ("name", "qualified_name"):
                    return (None, _text(child, src).rsplit("\\", 1)[-1])
            return None
        name = _field(node, "name")
        fn = _field(node, "function")
        if node.type == "function_call_expression" and fn is not None:
            return (None, _text(fn, src).rsplit("\\", 1)[-1])
        obj = _field(node, "object", "scope")
        return (
            (_text(obj, src) if obj is not None else None, _text(name, src))
            if name is not None
            else None
        )
    if key == "csharp" and node.type == "object_creation_expression":
        t = _field(node, "type")
        return (None, _text(t, src).split("<")[0]) if t is not None else None
    fn = _field(node, "function", "constructor")
    if fn is None:
        return None
    return _split_callee(fn, src)


def _split_callee(fn: Node, src: bytes) -> tuple[str | None, str] | None:
    t = fn.type
    if t in ("identifier", "constant", "name", "type_identifier"):
        return (None, _text(fn, src))
    if t in (
        "attribute",
        "member_expression",
        "selector_expression",
        "field_expression",
        "member_access_expression",
        "scoped_identifier",
        "qualified_identifier",
        "scoped_call_expression",
        "template_function",
        "generic_name",
        "generic_type",
    ):
        name_node = _field(fn, "attribute", "property", "field", "name")
        if name_node is None:
            named = fn.named_children
            if not named:
                return None
            name_node = named[-1]
        recv_node = _field(
            fn, "object", "operand", "argument", "expression", "path", "scope", "value"
        )
        recv = _text(recv_node, src) if recv_node is not None else None
        name = _text(name_node, src)
        if fn.type in ("template_function", "generic_name", "generic_type"):
            name = name.split("<")[0]
        return (recv[:60] if recv else None, name)
    if t in (
        "parenthesized_expression",
        "await_expression",
        "non_null_expression",
        "as_expression",
    ):
        inner = fn.named_children[0] if fn.named_child_count else None
        return _split_callee(inner, src) if inner is not None else None
    if t in ("call_expression", "call", "new_expression"):
        return None  # chained call result, e.g. foo()(); ignore
    if t == "super":
        return (None, "super")
    return None


_STRING_TYPES = frozenset(
    {
        "string",
        "string_literal",
        "interpreted_string_literal",
        "raw_string_literal",
        "encapsed_string",
    }
)


def _string_arg(node: Node, src: bytes) -> str | None:
    args = _field(node, "arguments") or _first_child_of_types(
        node, frozenset({"arguments", "argument_list"})
    )
    if args is None:
        return None
    for child in args.named_children:
        target = (
            child.named_children[0]
            if child.type == "argument" and child.named_child_count
            else child
        )
        if target.type in _STRING_TYPES:
            return _text(target, src).strip("'\"`<>")
    return None


def _arg_refs(node: Node, src: bytes) -> list[str]:
    """Bare identifiers passed as arguments (callbacks/handlers), e.g. app.post("/x", handler)."""
    args = _field(node, "arguments") or _first_child_of_types(
        node, frozenset({"arguments", "argument_list"})
    )
    if args is None:
        return []
    refs: list[str] = []
    for child in args.named_children:
        target = (
            child.named_children[0]
            if child.type == "argument" and child.named_child_count
            else child
        )
        if target.type in ("identifier", "constant", "name"):
            refs.append(_text(target, src))
        elif target.type in (
            "member_expression",
            "attribute",
            "selector_expression",
            "scoped_identifier",
        ):
            refs.append(_text(target, src)[:80])
    return refs[:4]


def _import_of(node: Node, spec: LanguageSpec, src: bytes, line: int) -> Import | None:
    key = spec.key
    if key == "python":
        if node.type == "import_statement":
            raw_names = [_text(n, src) for n in node.children_by_field_name("name")]
            mods: list[Import] = []
            for n in node.children_by_field_name("name"):
                if n.type == "aliased_import":
                    mod = _field(n, "name")
                    alias = _field(n, "alias")
                    mods.append(
                        Import(
                            module=_text(mod, src) if mod else "",
                            alias=_text(alias, src) if alias else None,
                            line=line,
                        )
                    )
                else:
                    mods.append(Import(module=_text(n, src), line=line))
            return mods[0] if len(mods) == 1 else Import(module=", ".join(raw_names), line=line)
        mod = _field(node, "module_name")
        names: list[str] = []
        for n in node.children_by_field_name("name"):
            if n.type == "aliased_import":
                inner = _field(n, "name")
                names.append(_text(inner, src) if inner else _text(n, src))
            else:
                names.append(_text(n, src))
        if _first_child_of_types(node, frozenset({"wildcard_import"})) is not None:
            names.append("*")
        return Import(module=_text(mod, src) if mod else "", names=names, line=line)
    if key in ("javascript", "typescript", "tsx"):
        source = _field(node, "source")
        if source is None:
            return None
        names = []
        clause = _first_child_of_types(node, frozenset({"import_clause"}))
        if clause is not None:
            for child in clause.named_children:
                if child.type == "identifier":
                    names.append(_text(child, src))
                elif child.type == "named_imports":
                    for specn in child.named_children:
                        ids = [c for c in specn.named_children if c.type == "identifier"]
                        if ids:
                            names.append(_text(ids[-1], src))
                elif child.type == "namespace_import":
                    ids = [c for c in child.named_children if c.type == "identifier"]
                    if ids:
                        names.append("* as " + _text(ids[0], src))
        return Import(module=_text(source, src).strip("'\"`"), names=names, line=line)
    if key == "java":
        text = (
            _text(node, src).removeprefix("import").removesuffix(";").replace("static", "").strip()
        )
        return Import(module=text, names=[text.rsplit(".", 1)[-1]], line=line)
    if key == "go":
        path = _field(node, "path")
        alias = _field(node, "name")
        if path is None:
            return None
        return Import(
            module=_text(path, src).strip('"`'),
            alias=_text(alias, src) if alias else None,
            line=line,
        )
    if key in ("c", "cpp"):
        path = _field(node, "path")
        return Import(module=_text(path, src).strip('"<>'), line=line) if path is not None else None
    if key == "csharp":
        named = [c for c in node.named_children if c.type in ("identifier", "qualified_name")]
        return Import(module=_text(named[-1], src), line=line) if named else None
    if key == "php":
        if node.type == "namespace_use_declaration":
            uses: list[str] = []
            for clause in node.named_children:
                if clause.type == "namespace_use_clause":
                    qn = clause.named_children[0] if clause.named_child_count else None
                    if qn is not None:
                        uses.append(_text(qn, src))
            return Import(
                module=", ".join(uses), names=[m.rsplit("\\", 1)[-1] for m in uses], line=line
            )
        for child in node.named_children:
            if child.type in _STRING_TYPES:
                return Import(module=_text(child, src).strip("'\""), line=line)
        return None
    if key == "rust":
        if node.type == "mod_item":
            if _field(node, "body") is not None:
                return None
            name = _field(node, "name")
            return (
                Import(module=f"mod {_text(name, src)}", names=[_text(name, src)], line=line)
                if name
                else None
            )
        arg = _field(node, "argument")
        text = _text(arg, src) if arg is not None else _text(node, src)
        return Import(module=text, names=[text.rsplit("::", 1)[-1].strip("{} ")], line=line)
    return None


def _symbol_id(path: str, qualname: str) -> str:
    return f"{path}::{qualname}"


class _Walker:
    def __init__(self, path: str, spec: LanguageSpec, src: bytes) -> None:
        self.path = path
        self.spec = spec
        self.src = src
        self.symbols: list[Symbol] = []
        self.imports: list[Import] = []
        self.top_calls: list[CallSite] = []
        self.main_guards: list[MainGuard] = []
        self.scope: list[Symbol] = []
        self.seen_ids: dict[str, int] = {}

    def _unique_id(self, qualname: str) -> str:
        sid = _symbol_id(self.path, qualname)
        n = self.seen_ids.get(sid, 0)
        self.seen_ids[sid] = n + 1
        return sid if n == 0 else f"{sid}#{n + 1}"

    def _enclosing_class(self) -> Symbol | None:
        for s in reversed(self.scope):
            if s.kind == "class":
                return s
            return None
        return None

    def _enclosing_function(self) -> Symbol | None:
        for s in reversed(self.scope):
            if s.kind != "class":
                return s
        return None

    def _qualname(self, name: str) -> str:
        prefix = ".".join(s.name for s in self.scope if s.kind == "class")
        return f"{prefix}.{name}" if prefix else name

    def _make_symbol(self, node: Node, name: str, kind: SymbolKind) -> Symbol:
        spec, src = self.spec, self.src
        if spec.key == "go" and node.type == "method_declaration":
            recv = _field(node, "receiver")
            recv_type = ""
            if recv is not None:
                m = re.search(
                    r"\*?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?$", _text(recv, src).strip("()")
                )
                recv_type = m.group(1) if m else ""
            qualname = f"{recv_type}.{name}" if recv_type else name
            kind = "method"
        elif spec.key == "cpp" and "::" in name:
            qualname = name.replace("::", ".")
            owner = name.rsplit("::", 2)[-2]
            name = name.rsplit("::", 1)[-1]
            kind = "method"
        else:
            qualname = self._qualname(name)
        parent = self._enclosing_class()
        if parent is None and kind == "method" and spec.key == "cpp":
            parent = next((s for s in self.symbols if s.kind == "class" and s.name == owner), None)
        if kind == "function" and parent is not None:
            kind = "method"
        sym = Symbol(
            id=self._unique_id(qualname),
            file=self.path,
            name=name,
            qualname=qualname,
            kind=kind,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            params=_params_of(node, spec, src) if kind != "class" else "",
            returns=_returns_of(node, spec, src) if kind != "class" else None,
            docstring=_docstring_of(node, spec, src),
            decorators=_decorators_of(node, spec, src),
            parent=parent.id if parent is not None else None,
            is_exported=_is_exported(node, spec, name, src),
        )
        if (
            spec.key == "python"
            and node.parent is not None
            and node.parent.type == "decorated_definition"
        ):
            sym.start_line = node.parent.start_point[0] + 1
        return sym

    def _record_call(self, node: Node) -> None:
        parts = _call_parts(node, self.spec, self.src)
        if parts is None:
            return
        receiver, name = parts
        line = node.start_point[0] + 1
        if (
            self.spec.key in ("javascript", "typescript", "tsx")
            and name == "require"
            and receiver is None
        ):
            module = _string_arg(node, self.src)
            if module:
                holder = node.parent
                names = []
                if holder is not None and holder.type == "variable_declarator":
                    key = _field(holder, "name")
                    if key is not None:
                        names = [_text(key, self.src)]
                self.imports.append(Import(module=module, names=names, line=line))
            return
        if self.spec.key == "ruby" and name in ("require", "require_relative") and receiver is None:
            module = _string_arg(node, self.src)
            if module:
                self.imports.append(Import(module=module, line=line))
            return
        if self.spec.key == "javascript" and name == "import" and receiver is None:
            module = _string_arg(node, self.src)
            if module:
                self.imports.append(Import(module=module, line=line))
            return
        call = CallSite(
            name=name[:80], receiver=receiver, line=line, arg_refs=_arg_refs(node, self.src)
        )
        fn = self._enclosing_function()
        if fn is not None:
            fn.calls.append(call)
        else:
            self.top_calls.append(call)

    def _is_main_guard(self, node: Node) -> bool:
        if self.spec.key != "python" or node.type != "if_statement":
            return False
        cond = _field(node, "condition")
        return cond is not None and "__name__" in _text(cond, self.src)

    def walk(self, root: Node) -> None:
        spec = self.spec
        stack: list[tuple[Node, bool]] = [(root, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                self.scope.pop()
                continue
            if node.type in spec.skip_types or node.type in spec.decorator_types:
                continue
            if node.type in spec.import_types:
                imp = _import_of(node, spec, self.src, node.start_point[0] + 1)
                if imp is not None:
                    self.imports.append(imp)
                continue
            pushed = False
            if node.type in spec.class_types:
                name = _name_of(node, spec, self.src)
                if spec.key == "rust" and node.type == "impl_item":
                    t = _field(node, "type")
                    name = _text(t, self.src).split("<")[0] if t is not None else name
                if name:
                    sym = self._make_symbol(node, name, "class")
                    if spec.key == "rust" and node.type == "impl_item":
                        existing = next(
                            (s for s in self.symbols if s.kind == "class" and s.name == name), None
                        )
                        if existing is not None:
                            existing.end_line = max(existing.end_line, sym.end_line)
                            sym = existing
                        else:
                            self.symbols.append(sym)
                    else:
                        self.symbols.append(sym)
                    self.scope.append(sym)
                    pushed = True
            elif node.type in spec.function_types or _is_value_function(node, spec):
                name = _name_of(node, spec, self.src)
                if name:
                    sym = self._make_symbol(node, name, "function")
                    self.symbols.append(sym)
                    self.scope.append(sym)
                    pushed = True
            elif node.type in spec.call_types:
                self._record_call(node)
            elif self._is_main_guard(node):
                self.main_guards.append(
                    MainGuard(start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1)
                )
            if pushed:
                stack.append((node, True))
            for child in reversed(node.children):
                if child.is_named or child.type in spec.call_types:
                    stack.append((child, False))


def extract_file(path: str, grammar_key: str, source: bytes, language: str) -> Extraction:
    spec = SPECS[grammar_key]
    fm = FileMap(
        path=path,
        language=language,
        lines=source.count(b"\n") + (0 if source.endswith(b"\n") or not source else 1),
    )
    try:
        tree = make_parser(grammar_key).parse(source)
    except Exception as exc:  # pragma: no cover - grammar failures are rare and non-fatal
        fm.parse_error = str(exc)[:200]
        return Extraction(file=fm)
    walker = _Walker(path, spec, source)
    walker.walk(tree.root_node)
    fm.symbols = [s.id for s in walker.symbols]
    fm.imports = walker.imports
    fm.top_level_calls = walker.top_calls
    fm.main_guards = walker.main_guards
    if tree.root_node.has_error:
        fm.parse_error = "syntax errors (partial parse)"
    return Extraction(file=fm, symbols=walker.symbols)
