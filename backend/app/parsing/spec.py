"""Per-language node-type tables for the generic extractor.

Node type names come from the grammars shipped in the pinned ``tree-sitter-*`` wheels and were
verified by parsing snippets with each grammar (see tests/test_extractor.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

FUNCTION_VALUE_TYPES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)


@dataclass(frozen=True)
class LanguageSpec:
    key: str
    function_types: frozenset[str]
    class_types: frozenset[str]
    call_types: frozenset[str]
    import_types: frozenset[str]
    comment_types: frozenset[str] = frozenset({"comment"})
    param_fields: tuple[str, ...] = ("parameters",)
    return_fields: tuple[str, ...] = ("return_type",)
    body_fields: tuple[str, ...] = ("body",)
    self_names: frozenset[str] = frozenset({"self", "this"})
    # node types whose text counts as a decorator/annotation/attribute on the following def
    decorator_types: frozenset[str] = frozenset()
    # JS-style: variable declarators / properties whose value is a function count as functions
    value_function_holders: frozenset[str] = frozenset()
    skip_types: frozenset[str] = field(default_factory=frozenset)


PYTHON = LanguageSpec(
    key="python",
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"class_definition"}),
    call_types=frozenset({"call"}),
    import_types=frozenset({"import_statement", "import_from_statement"}),
    self_names=frozenset({"self", "cls"}),
    decorator_types=frozenset({"decorator"}),
)

_JS_BASE = {
    "function_types": frozenset(
        {"function_declaration", "generator_function_declaration", "method_definition"}
    ),
    "class_types": frozenset({"class_declaration", "class", "abstract_class_declaration"}),
    "call_types": frozenset({"call_expression", "new_expression"}),
    "import_types": frozenset({"import_statement"}),
    "param_fields": ("parameters",),
    "return_fields": ("return_type",),
    "decorator_types": frozenset({"decorator"}),
    "value_function_holders": frozenset(
        {
            "variable_declarator",
            "pair",
            "assignment_expression",
            "public_field_definition",
            "field_definition",
        }
    ),
    "skip_types": frozenset({"method_signature", "abstract_method_signature"}),
}
JAVASCRIPT = LanguageSpec(key="javascript", **_JS_BASE)  # type: ignore[arg-type]
TYPESCRIPT = LanguageSpec(key="typescript", **_JS_BASE)  # type: ignore[arg-type]
TSX = LanguageSpec(key="tsx", **_JS_BASE)  # type: ignore[arg-type]

JAVA = LanguageSpec(
    key="java",
    function_types=frozenset({"method_declaration", "constructor_declaration"}),
    class_types=frozenset(
        {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
    ),
    call_types=frozenset({"method_invocation", "object_creation_expression"}),
    import_types=frozenset({"import_declaration"}),
    comment_types=frozenset({"line_comment", "block_comment"}),
    return_fields=("type",),
    decorator_types=frozenset({"marker_annotation", "annotation"}),
)

GO = LanguageSpec(
    key="go",
    function_types=frozenset({"function_declaration", "method_declaration"}),
    class_types=frozenset(),
    call_types=frozenset({"call_expression"}),
    import_types=frozenset({"import_spec"}),
    return_fields=("result",),
)

C = LanguageSpec(
    key="c",
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"struct_specifier"}),
    call_types=frozenset({"call_expression"}),
    import_types=frozenset({"preproc_include"}),
    return_fields=("type",),
    skip_types=frozenset({"struct_specifier"}),  # C structs carry no methods; skip as classes
)

CPP = LanguageSpec(
    key="cpp",
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"class_specifier", "struct_specifier"}),
    call_types=frozenset({"call_expression"}),
    import_types=frozenset({"preproc_include"}),
    return_fields=("type",),
)

CSHARP = LanguageSpec(
    key="csharp",
    function_types=frozenset(
        {"method_declaration", "constructor_declaration", "local_function_statement"}
    ),
    class_types=frozenset(
        {"class_declaration", "struct_declaration", "interface_declaration", "record_declaration"}
    ),
    call_types=frozenset({"invocation_expression", "object_creation_expression"}),
    import_types=frozenset({"using_directive"}),
    param_fields=("parameters",),
    return_fields=("returns", "type"),
    decorator_types=frozenset({"attribute_list"}),
)

RUBY = LanguageSpec(
    key="ruby",
    function_types=frozenset({"method", "singleton_method"}),
    class_types=frozenset({"class", "module"}),
    call_types=frozenset({"call"}),
    import_types=frozenset(),  # require / require_relative are calls (handled in extractor)
    param_fields=("parameters",),
    self_names=frozenset({"self"}),
)

PHP = LanguageSpec(
    key="php",
    function_types=frozenset({"function_definition", "method_declaration"}),
    class_types=frozenset(
        {"class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"}
    ),
    call_types=frozenset(
        {
            "function_call_expression",
            "member_call_expression",
            "scoped_call_expression",
            "object_creation_expression",
            "nullsafe_member_call_expression",
        }
    ),
    import_types=frozenset(
        {
            "namespace_use_declaration",
            "require_expression",
            "require_once_expression",
            "include_expression",
            "include_once_expression",
        }
    ),
    param_fields=("parameters",),
    self_names=frozenset({"$this", "self", "static"}),
    decorator_types=frozenset({"attribute_list"}),
)

RUST = LanguageSpec(
    key="rust",
    function_types=frozenset({"function_item"}),
    class_types=frozenset({"impl_item", "struct_item", "enum_item", "trait_item"}),
    call_types=frozenset({"call_expression"}),
    import_types=frozenset({"use_declaration", "mod_item"}),
    comment_types=frozenset({"line_comment", "block_comment"}),
    decorator_types=frozenset({"attribute_item"}),
    skip_types=frozenset({"function_signature_item"}),
)

SPECS: dict[str, LanguageSpec] = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "tsx": TSX,
    "java": JAVA,
    "go": GO,
    "c": C,
    "cpp": CPP,
    "csharp": CSHARP,
    "ruby": RUBY,
    "php": PHP,
    "rust": RUST,
}
