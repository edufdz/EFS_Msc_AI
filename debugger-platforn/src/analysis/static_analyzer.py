"""
Static Analysis Engine using Tree-sitter.
Parses Python and TypeScript/JavaScript source files and extracts
functions, classes, imports, decorators, API calls, and variables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser, Node

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())
JS_LANGUAGE = Language(tsjavascript.language())


@dataclass
class Location:
    file: str
    line: int
    column: int = 0


@dataclass
class ParamInfo:
    name: str
    type_annotation: str | None = None
    default: str | None = None


@dataclass
class FunctionInfo:
    name: str
    params: list[ParamInfo]
    docstring: str | None
    decorators: list[str]
    body_text: str
    location: Location
    is_async: bool = False
    calls: list[str] = field(default_factory=list)


@dataclass
class ClassInfo:
    name: str
    bases: list[str]
    docstring: str | None
    methods: list[FunctionInfo]
    decorators: list[str]
    location: Location
    class_variables: list[tuple[str, str | None]]  # (name, value_snippet)


@dataclass
class ImportInfo:
    module: str
    names: list[str]  # imported names; ["*"] for star imports
    alias: str | None
    location: Location


@dataclass
class VariableInfo:
    name: str
    value_text: str | None
    location: Location


@dataclass
class FileSymbols:
    file_path: str
    language: str
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    variables: list[VariableInfo] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


def _get_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_docstring(body_node: Node, source: bytes) -> str | None:
    """Extract docstring from the first statement in a body block."""
    if body_node is None or body_node.child_count == 0:
        return None
    first_stmt = body_node.children[0]
    # Python docstrings are expression_statement -> string
    if first_stmt.type == "expression_statement":
        expr = first_stmt.children[0] if first_stmt.child_count > 0 else None
        if expr and expr.type == "string":
            raw = _get_text(expr, source)
            # Strip triple quotes
            for q in ('"""', "'''", '"', "'"):
                if raw.startswith(q) and raw.endswith(q):
                    return raw[len(q):-len(q)].strip()
            return raw
    return None


def _extract_decorators(node: Node, source: bytes) -> list[str]:
    """Extract decorator names from a decorated definition."""
    decorators = []
    # Walk siblings above the node – tree-sitter wraps decorated defs
    parent = node.parent
    if parent and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                # decorator children: "@" + expression
                parts = [_get_text(c, source) for c in child.children if c.type != "@"]
                dec_text = "".join(parts)
                # Strip parenthesized args to get just the name
                name = dec_text.split("(")[0].strip()
                decorators.append(name)
    return decorators


def _extract_params(params_node: Node, source: bytes) -> list[ParamInfo]:
    """Extract parameter info from a parameters node."""
    params = []
    if params_node is None:
        return params

    for child in params_node.children:
        if child.type in ("identifier",):
            name = _get_text(child, source)
            if name != "self" and name != "cls":
                params.append(ParamInfo(name=name))
        elif child.type == "typed_parameter":
            name_node = child.child_by_field_name("name") or (
                child.children[0] if child.child_count > 0 else None
            )
            type_node = child.child_by_field_name("type")
            name = _get_text(name_node, source) if name_node else "?"
            type_ann = _get_text(type_node, source) if type_node else None
            if name not in ("self", "cls"):
                params.append(ParamInfo(name=name, type_annotation=type_ann))
        elif child.type == "default_parameter":
            name_node = child.child_by_field_name("name") or (
                child.children[0] if child.child_count > 0 else None
            )
            value_node = child.child_by_field_name("value")
            name = _get_text(name_node, source) if name_node else "?"
            default = _get_text(value_node, source) if value_node else None
            if name not in ("self", "cls"):
                params.append(ParamInfo(name=name, default=default))
        elif child.type == "typed_default_parameter":
            name_node = child.child_by_field_name("name") or (
                child.children[0] if child.child_count > 0 else None
            )
            type_node = child.child_by_field_name("type")
            value_node = child.child_by_field_name("value")
            name = _get_text(name_node, source) if name_node else "?"
            type_ann = _get_text(type_node, source) if type_node else None
            default = _get_text(value_node, source) if value_node else None
            if name not in ("self", "cls"):
                params.append(ParamInfo(name=name, type_annotation=type_ann, default=default))

    return params


def _extract_function_calls(body_node: Node, source: bytes) -> list[str]:
    """Extract names of functions called within a body."""
    calls = []
    if body_node is None:
        return calls

    def _walk(node: Node):
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                call_text = _get_text(func_node, source)
                calls.append(call_text)
        for child in node.children:
            _walk(child)

    _walk(body_node)
    return calls


def _extract_class_variables(body_node: Node, source: bytes) -> list[tuple[str, str | None]]:
    """Extract class-level variable assignments."""
    variables = []
    if body_node is None:
        return variables

    for child in body_node.children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.child_count > 0 else None
            if expr and expr.type == "assignment":
                left = expr.child_by_field_name("left")
                right = expr.child_by_field_name("right")
                if left:
                    name = _get_text(left, source)
                    value = _get_text(right, source)[:200] if right else None
                    variables.append((name, value))
        elif child.type == "type_alias_statement":
            # name: type = value
            pass
    return variables


def parse_python_file(file_path: str) -> FileSymbols:
    """
    Parse a Python source file and extract all symbols.

    Returns a FileSymbols object containing functions, classes, imports, and variables.
    """
    symbols = FileSymbols(file_path=file_path, language="python")

    try:
        with open(file_path, "rb") as f:
            source = f.read()
    except (OSError, IOError) as e:
        symbols.parse_errors.append(f"Could not read file: {e}")
        return symbols

    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source)
    root = tree.root_node

    def _process_function(node: Node, file_path: str) -> FunctionInfo:
        """Process a function_definition or decorated function."""
        # If this is inside a decorated_definition, get decorators
        decorators = _extract_decorators(node, source)
        is_async = node.type == "function_definition" and any(
            c.type == "async" for c in (node.parent.children if node.parent else [])
        )

        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")

        name = _get_text(name_node, source) if name_node else "<anonymous>"
        params = _extract_params(params_node, source)
        docstring = _extract_docstring(body_node, source)
        body_text = _get_text(body_node, source) if body_node else ""
        calls = _extract_function_calls(body_node, source)
        line = name_node.start_point[0] if name_node else node.start_point[0]

        return FunctionInfo(
            name=name,
            params=params,
            docstring=docstring,
            decorators=decorators,
            body_text=body_text,
            location=Location(file=file_path, line=line),
            is_async=is_async,
            calls=calls,
        )

    def _process_class(node: Node, file_path: str) -> ClassInfo:
        """Process a class_definition."""
        decorators = _extract_decorators(node, source)
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")

        # Extract base classes
        bases = []
        superclasses_node = node.child_by_field_name("superclasses")
        if superclasses_node is None:
            # Also check argument_list (Python tree-sitter uses this)
            for child in node.children:
                if child.type == "argument_list":
                    superclasses_node = child
                    break

        if superclasses_node:
            for child in superclasses_node.children:
                if child.type in ("identifier", "attribute"):
                    bases.append(_get_text(child, source))

        name = _get_text(name_node, source) if name_node else "<anonymous>"
        docstring = _extract_docstring(body_node, source)

        # Extract methods
        methods = []
        class_vars = []
        if body_node:
            class_vars = _extract_class_variables(body_node, source)
            for child in body_node.children:
                if child.type == "function_definition":
                    methods.append(_process_function(child, file_path))
                elif child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            methods.append(_process_function(sub, file_path))

        line = name_node.start_point[0] if name_node else node.start_point[0]

        return ClassInfo(
            name=name,
            bases=bases,
            docstring=docstring,
            methods=methods,
            decorators=decorators,
            location=Location(file=file_path, line=line),
            class_variables=class_vars,
        )

    def _process_import(node: Node, file_path: str):
        """Process import and from-import statements."""
        line = node.start_point[0]

        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    module = _get_text(child, source)
                    symbols.imports.append(ImportInfo(
                        module=module, names=[], alias=None,
                        location=Location(file=file_path, line=line),
                    ))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    module = _get_text(name_node, source) if name_node else ""
                    alias = _get_text(alias_node, source) if alias_node else None
                    symbols.imports.append(ImportInfo(
                        module=module, names=[], alias=alias,
                        location=Location(file=file_path, line=line),
                    ))

        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = _get_text(module_node, source) if module_node else ""
            names = []
            for child in node.children:
                if child.type == "dotted_name" and child != module_node:
                    names.append(_get_text(child, source))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        names.append(_get_text(name_node, source))
                elif child.type == "wildcard_import":
                    names.append("*")
            symbols.imports.append(ImportInfo(
                module=module, names=names, alias=None,
                location=Location(file=file_path, line=line),
            ))

    def _process_assignment(node: Node, file_path: str):
        """Process top-level variable assignments."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left:
            name = _get_text(left, source)
            value = _get_text(right, source)[:500] if right else None
            symbols.variables.append(VariableInfo(
                name=name,
                value_text=value,
                location=Location(file=file_path, line=node.start_point[0]),
            ))

    # Walk top-level nodes
    for node in root.children:
        if node.type == "function_definition":
            symbols.functions.append(_process_function(node, file_path))

        elif node.type == "decorated_definition":
            for child in node.children:
                if child.type == "function_definition":
                    symbols.functions.append(_process_function(child, file_path))
                elif child.type == "class_definition":
                    symbols.classes.append(_process_class(child, file_path))

        elif node.type == "class_definition":
            symbols.classes.append(_process_class(node, file_path))

        elif node.type in ("import_statement", "import_from_statement"):
            _process_import(node, file_path)

        elif node.type == "expression_statement":
            expr = node.children[0] if node.child_count > 0 else None
            if expr and expr.type == "assignment":
                _process_assignment(expr, file_path)

        elif node.type == "ERROR":
            symbols.parse_errors.append(
                f"Parse error at line {node.start_point[0]}: "
                f"{_get_text(node, source)[:100]}"
            )

    return symbols


def _ts_get_language(file_path: str) -> Language:
    """Return the appropriate tree-sitter language for a TS/JS file."""
    if file_path.endswith(".tsx"):
        return TSX_LANGUAGE
    elif file_path.endswith(".ts"):
        return TS_LANGUAGE
    else:
        return JS_LANGUAGE


def _ts_extract_jsdoc(node: Node, source: bytes) -> str | None:
    """Extract JSDoc comment (/** ... */) preceding a node."""
    # Look for a comment sibling immediately before this node
    prev = node.prev_named_sibling
    if prev and prev.type == "comment":
        text = _get_text(prev, source)
        if text.startswith("/**"):
            # Strip /** and */
            content = text[3:]
            if content.endswith("*/"):
                content = content[:-2]
            # Clean up leading * on each line
            lines = []
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("* "):
                    stripped = stripped[2:]
                elif stripped.startswith("*"):
                    stripped = stripped[1:]
                lines.append(stripped)
            return "\n".join(lines).strip()
    return None


def _ts_extract_decorators(node: Node, source: bytes) -> list[str]:
    """Extract TypeScript/JS decorators from a node or its export parent."""
    decorators = []
    # Decorators appear as children of export_statement (before the declaration)
    parent = node.parent
    if parent and parent.type == "export_statement":
        for child in parent.children:
            if child.type == "decorator":
                parts = [_get_text(c, source) for c in child.children if c.type != "@"]
                name = "".join(parts).split("(")[0].strip()
                decorators.append(name)
    elif node.prev_named_sibling and node.prev_named_sibling.type == "decorator":
        # Non-exported declarations: walk backwards collecting decorator siblings
        sib = node.prev_named_sibling
        while sib and sib.type == "decorator":
            parts = [_get_text(c, source) for c in sib.children if c.type != "@"]
            name = "".join(parts).split("(")[0].strip()
            decorators.insert(0, name)
            sib = sib.prev_named_sibling
    return decorators


def _ts_extract_params(params_node: Node, source: bytes) -> list[ParamInfo]:
    """Extract parameter info from a TS/JS formal_parameters node."""
    params = []
    if params_node is None:
        return params

    for child in params_node.children:
        if child.type == "identifier":
            # Plain JS parameter (no type annotation)
            name = _get_text(child, source)
            if name not in ("this",):
                params.append(ParamInfo(name=name))
        elif child.type in ("required_parameter", "optional_parameter"):
            # Name from 'pattern' field or first identifier
            pattern_node = child.child_by_field_name("pattern")
            if pattern_node:
                if pattern_node.type == "rest_pattern":
                    # ...rest — get the identifier inside
                    for sub in pattern_node.children:
                        if sub.type == "identifier":
                            name = "..." + _get_text(sub, source)
                            break
                    else:
                        name = _get_text(pattern_node, source)
                else:
                    name = _get_text(pattern_node, source)
            else:
                # Fallback: first identifier child
                name = None
                for sub in child.children:
                    if sub.type == "identifier":
                        name = _get_text(sub, source)
                        break
                if not name:
                    continue

            # Skip 'this' parameter (TS method context)
            if name in ("this",):
                continue

            # Type annotation
            type_ann = None
            for sub in child.children:
                if sub.type == "type_annotation":
                    # Get the type itself (skip the ':')
                    for t in sub.children:
                        if t.type != ":":
                            type_ann = _get_text(t, source)
                            break
                    break

            # Default value
            default = None
            value_node = child.child_by_field_name("value")
            if value_node:
                default = _get_text(value_node, source)

            params.append(ParamInfo(name=name, type_annotation=type_ann, default=default))

    return params


def _ts_extract_function_calls(body_node: Node, source: bytes) -> list[str]:
    """Extract function call names from a TS/JS statement_block."""
    calls = []
    if body_node is None:
        return calls

    def _walk(node: Node):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                calls.append(_get_text(func_node, source))
        for child in node.children:
            _walk(child)

    _walk(body_node)
    return calls


def parse_typescript_file_treesitter(file_path: str) -> FileSymbols:
    """
    Parse a TypeScript/JavaScript source file using tree-sitter AST.
    Extracts functions, classes, imports, variables, decorators, JSDoc,
    and function call graphs.
    """
    lang_name = "javascript" if file_path.endswith((".js", ".jsx")) else "typescript"
    symbols = FileSymbols(file_path=file_path, language=lang_name)

    try:
        with open(file_path, "rb") as f:
            source = f.read()
    except (OSError, IOError) as e:
        symbols.parse_errors.append(f"Could not read file: {e}")
        return symbols

    language = _ts_get_language(file_path)
    parser = Parser(language)
    tree = parser.parse(source)
    root = tree.root_node

    def _process_function(node: Node, name_override: str | None = None) -> FunctionInfo:
        """Process function_declaration, method_definition, or arrow_function."""
        is_async = any(c.type == "async" for c in node.children)

        # Get name
        if name_override:
            name = name_override
        else:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _get_text(name_node, source)
            else:
                # method_definition uses property_identifier
                for child in node.children:
                    if child.type in ("property_identifier", "identifier"):
                        name = _get_text(child, source)
                        break
                else:
                    name = "<anonymous>"

        # Parameters
        params_node = node.child_by_field_name("parameters")
        params = _ts_extract_params(params_node, source)

        # Body
        body_node = node.child_by_field_name("body")
        body_text = _get_text(body_node, source)[:500] if body_node else ""

        # Function calls
        calls = _ts_extract_function_calls(body_node, source)

        # JSDoc — check above the node, or above the export_statement parent
        docstring = _ts_extract_jsdoc(node, source)
        if not docstring and node.parent and node.parent.type in ("export_statement", "lexical_declaration"):
            docstring = _ts_extract_jsdoc(node.parent, source)
        # Also check for JSDoc above variable_declarator (for arrow functions)
        if not docstring and node.parent and node.parent.type == "variable_declarator":
            lex = node.parent.parent  # lexical_declaration
            if lex:
                docstring = _ts_extract_jsdoc(lex, source)
                if not docstring and lex.parent and lex.parent.type == "export_statement":
                    docstring = _ts_extract_jsdoc(lex.parent, source)

        # Decorators — check node first, then walk up to parent contexts
        decorators = _ts_extract_decorators(node, source)
        if not decorators and node.parent and node.parent.type == "lexical_declaration":
            # Arrow function: variable_declarator -> lexical_declaration -> export_statement
            lex = node.parent.parent if node.parent.parent else node.parent
            decorators = _ts_extract_decorators(lex, source)

        line = node.start_point[0]

        return FunctionInfo(
            name=name,
            params=params,
            docstring=docstring,
            decorators=decorators,
            body_text=body_text,
            location=Location(file=file_path, line=line),
            is_async=is_async,
            calls=calls,
        )

    def _process_class(node: Node) -> ClassInfo:
        """Process a class_declaration."""
        decorators = _ts_extract_decorators(node, source)

        # Name (type_identifier in TS, identifier in JS)
        name = "<anonymous>"
        for child in node.children:
            if child.type in ("type_identifier", "identifier"):
                name = _get_text(child, source)
                break

        # Base classes and interfaces
        bases = []
        for child in node.children:
            if child.type == "class_heritage":
                for heritage in child.children:
                    if heritage.type == "extends_clause":
                        for sub in heritage.children:
                            if sub.type in ("identifier", "type_identifier", "member_expression"):
                                bases.append(_get_text(sub, source))
                    elif heritage.type == "implements_clause":
                        for sub in heritage.children:
                            if sub.type in ("identifier", "type_identifier", "generic_type"):
                                bases.append(_get_text(sub, source))

        # JSDoc
        docstring = _ts_extract_jsdoc(node, source)
        if not docstring and node.parent and node.parent.type == "export_statement":
            docstring = _ts_extract_jsdoc(node.parent, source)

        # Body: methods and class fields
        methods = []
        class_vars = []
        body_node = None
        for child in node.children:
            if child.type == "class_body":
                body_node = child
                break

        if body_node:
            for child in body_node.children:
                if child.type == "method_definition":
                    methods.append(_process_function(child))
                elif child.type in ("public_field_definition", "property_definition"):
                    # Class field: name and optional value
                    prop_name = None
                    for sub in child.children:
                        if sub.type in ("property_identifier", "identifier"):
                            prop_name = _get_text(sub, source)
                            break
                    if prop_name:
                        value = _get_text(child, source)[:200]
                        class_vars.append((prop_name, value))

        line = node.start_point[0]

        return ClassInfo(
            name=name,
            bases=bases,
            docstring=docstring,
            methods=methods,
            decorators=decorators,
            location=Location(file=file_path, line=line),
            class_variables=class_vars,
        )

    def _process_import(node: Node):
        """Process an import_statement."""
        line = node.start_point[0]
        module = ""
        names = []

        # Find the module string (source path)
        source_node = node.child_by_field_name("source")
        if source_node:
            module = _get_text(source_node, source).strip("'\"")
        else:
            for child in node.children:
                if child.type == "string":
                    module = _get_text(child, source).strip("'\"")
                    break

        # Find imported names from import_clause
        alias = None
        for child in node.children:
            if child.type == "import_clause":
                for sub in child.children:
                    if sub.type == "named_imports":
                        for spec in sub.children:
                            if spec.type == "import_specifier":
                                spec_name = _get_text(spec, source).split(" as ")[0].strip()
                                names.append(spec_name)
                    elif sub.type == "identifier":
                        # Default import: import X from '...'
                        names.append(_get_text(sub, source))
                    elif sub.type == "namespace_import":
                        # import * as X from '...'
                        names.append("*")
                        for ns_child in sub.children:
                            if ns_child.type == "identifier":
                                alias = _get_text(ns_child, source)

        symbols.imports.append(ImportInfo(
            module=module, names=names, alias=alias,
            location=Location(file=file_path, line=line),
        ))

    def _process_variable_declaration(node: Node, is_exported: bool = False):
        """Process a lexical_declaration (const/let/var)."""
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if not name_node:
                    # Fallback: first identifier
                    for sub in child.children:
                        if sub.type == "identifier":
                            name_node = sub
                            break

                if not name_node:
                    continue

                name = _get_text(name_node, source)

                # Check if value is an arrow function or function expression
                if value_node and value_node.type in ("arrow_function", "function"):
                    # This is a function assigned to a variable
                    func_info = _process_function(value_node, name_override=name)
                    symbols.functions.append(func_info)
                else:
                    # Regular variable
                    if is_exported or value_node:
                        # For tool arrays, allow up to 6000 chars
                        max_len = 6000 if is_exported else 500
                        value_text = _get_text(value_node, source)[:max_len] if value_node else None
                        symbols.variables.append(VariableInfo(
                            name=name,
                            value_text=value_text,
                            location=Location(file=file_path, line=node.start_point[0]),
                        ))

    def _process_node(node: Node):
        """Process a top-level AST node."""
        if node.type == "export_statement":
            # Export wraps other declarations
            for child in node.children:
                if child.type == "function_declaration":
                    symbols.functions.append(_process_function(child))
                elif child.type == "class_declaration":
                    symbols.classes.append(_process_class(child))
                elif child.type == "lexical_declaration":
                    _process_variable_declaration(child, is_exported=True)
                elif child.type == "interface_declaration":
                    _process_interface_or_type(child)
                elif child.type == "type_alias_declaration":
                    _process_interface_or_type(child)

        elif node.type == "function_declaration":
            symbols.functions.append(_process_function(node))

        elif node.type == "class_declaration":
            symbols.classes.append(_process_class(node))

        elif node.type == "lexical_declaration":
            _process_variable_declaration(node, is_exported=False)

        elif node.type == "import_statement":
            _process_import(node)

        elif node.type == "interface_declaration":
            _process_interface_or_type(node)

        elif node.type == "type_alias_declaration":
            _process_interface_or_type(node)

        elif node.type == "expression_statement":
            # Handle: module.exports = ..., require(...) at top level
            _process_cjs_exports(node)

        elif node.type == "ERROR":
            symbols.parse_errors.append(
                f"Parse error at line {node.start_point[0]}: "
                f"{_get_text(node, source)[:100]}"
            )

    def _process_interface_or_type(node: Node):
        """Extract interface/type alias as metadata variable (useful for tool schema detection)."""
        name = None
        for child in node.children:
            if child.type == "type_identifier":
                name = _get_text(child, source)
                break
        if name:
            value_text = _get_text(node, source)[:500]
            symbols.variables.append(VariableInfo(
                name=name,
                value_text=value_text,
                location=Location(file=file_path, line=node.start_point[0]),
            ))

    def _process_cjs_exports(node: Node):
        """Handle CommonJS patterns: module.exports = ..., const x = require(...)."""
        expr = node.children[0] if node.child_count > 0 else None
        if expr and expr.type == "assignment_expression":
            left = expr.child_by_field_name("left")
            right = expr.child_by_field_name("right")
            if left and right:
                left_text = _get_text(left, source)
                if left_text.startswith("module.exports"):
                    symbols.variables.append(VariableInfo(
                        name="module.exports",
                        value_text=_get_text(right, source)[:6000],
                        location=Location(file=file_path, line=node.start_point[0]),
                    ))

    # Walk top-level nodes
    for node in root.children:
        _process_node(node)

    return symbols


def parse_typescript_file_regex(file_path: str) -> FileSymbols:
    """
    Regex-based fallback parser for TypeScript/JavaScript files.
    Used when tree-sitter parsing fails.
    """
    import re

    symbols = FileSymbols(file_path=file_path, language="typescript")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except (OSError, IOError) as e:
        symbols.parse_errors.append(f"Could not read file: {e}")
        return symbols

    # Extract imports
    import_pattern = r'import\s+(?:(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)(?:\s*,\s*(?:\{[^}]*\}|\*\s+as\s+\w+|\w+))*\s+from\s+)?["\']([^"\']+)["\']'
    for match in re.finditer(import_pattern, source):
        module = match.group(1)
        line = source[:match.start()].count('\n') + 1
        symbols.imports.append(ImportInfo(
            module=module, names=[], alias=None,
            location=Location(file=file_path, line=line),
        ))

    # Extract function declarations
    func_patterns = [
        r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(',
        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
        r'(?:export\s+)?(?:async\s+)?(\w+)\s*:\s*\([^)]*\)\s*=>',
    ]

    for pattern in func_patterns:
        for match in re.finditer(pattern, source):
            name = match.group(1)
            line = source[:match.start()].count('\n') + 1
            start_pos = match.end()
            brace_count = 0
            body_start = None
            body_text = ""
            for i, char in enumerate(source[start_pos:], start_pos):
                if char == '{':
                    if brace_count == 0:
                        body_start = i + 1
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and body_start:
                        body_text = source[body_start:i]
                        break

            symbols.functions.append(FunctionInfo(
                name=name, params=[], docstring=None, decorators=[],
                body_text=body_text[:500],
                location=Location(file=file_path, line=line),
                is_async="async" in match.group(0), calls=[],
            ))

    # Extract class declarations
    class_pattern = r'(?:export\s+)?class\s+(\w+)'
    for match in re.finditer(class_pattern, source):
        name = match.group(1)
        line = source[:match.start()].count('\n') + 1
        symbols.classes.append(ClassInfo(
            name=name, bases=[], docstring=None, methods=[], decorators=[],
            location=Location(file=file_path, line=line), class_variables=[],
        ))

    # Extract exported constants/variables
    export_pattern = r'export\s+(?:const|let|var)\s+(\w+)'
    for match in re.finditer(export_pattern, source):
        name = match.group(1)
        line = source[:match.start()].count('\n') + 1
        window = source[match.end():match.end() + 8000]
        value_match = re.search(r'\s*=\s*([^;]+)', window)
        value_text = value_match.group(1).strip() if value_match else None
        symbols.variables.append(VariableInfo(
            name=name,
            value_text=value_text[:6000] if value_text else None,
            location=Location(file=file_path, line=line),
        ))

    return symbols


def parse_typescript_file(file_path: str) -> FileSymbols:
    """
    Parse a TypeScript/JavaScript file. Uses tree-sitter AST parsing,
    falling back to regex if tree-sitter fails.
    """
    try:
        return parse_typescript_file_treesitter(file_path)
    except Exception as e:
        logger.warning(
            "Tree-sitter parsing failed for %s, falling back to regex: %s",
            file_path, e,
        )
        return parse_typescript_file_regex(file_path)


def analyze_files(file_paths: list[str]) -> list[FileSymbols]:
    """Parse multiple source files and return their symbols."""
    results = []
    for fp in file_paths:
        if fp.endswith(".py"):
            results.append(parse_python_file(fp))
        elif fp.endswith((".ts", ".tsx", ".js", ".jsx")):
            results.append(parse_typescript_file(fp))
    return results
