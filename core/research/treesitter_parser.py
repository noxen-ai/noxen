"""Noxen - Tree-sitter based multi-language parser.

Parser strutturale basato su tree-sitter per estrarre
funzioni, classi, import da codice sorgente.
Sostituisce il parsing regex con AST reale.

Supporta: Python, JavaScript, TypeScript, Java, Go.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Parser, Node

from core.logger import get_logger

logger = get_logger("noxen.treesitter_parser")


# ── Language setup ───────────────────────────────────────────────────

SUPPORTED_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
}

def _load_language(lang_name: str) -> Language | None:
    """Load a tree-sitter Language from the corresponding package."""
    try:
        if lang_name == "python":
            import tree_sitter_python as mod
            return Language(mod.language())
        elif lang_name == "javascript":
            import tree_sitter_javascript as mod
            return Language(mod.language())
        elif lang_name == "typescript":
            import tree_sitter_typescript as mod
            return Language(mod.language_typescript())
        elif lang_name == "tsx":
            import tree_sitter_typescript as mod
            return Language(mod.language_tsx())
        elif lang_name == "java":
            import tree_sitter_java as mod
            return Language(mod.language())
        elif lang_name == "go":
            import tree_sitter_go as mod
            return Language(mod.language())
    except (ImportError, Exception) as e:
        logger.warning(f"Failed to load tree-sitter language '{lang_name}': {e}")
    return None


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class ParsedFunction:
    """Funzione/metodo estratta dall'AST."""
    name: str
    start_line: int
    end_line: int
    params: list[str] = field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)
    complexity: int = 1  # nodi decisionali nel corpo


@dataclass
class ParsedClass:
    """Classe estratta dall'AST."""
    name: str
    start_line: int
    end_line: int
    methods: list[str] = field(default_factory=list)
    base_classes: list[str] = field(default_factory=list)
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)


@dataclass
class ParsedImport:
    """Import estratto dall'AST."""
    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    is_from: bool = False
    line: int = 0


@dataclass
class ParsedFile:
    """Risultato del parsing di un singolo file."""
    path: str
    language: str
    functions: list[ParsedFunction] = field(default_factory=list)
    classes: list[ParsedClass] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    parse_errors: int = 0
    lines: int = 0


# ── Parser ───────────────────────────────────────────────────────────

class TreeSitterParser:
    """Parser multi-linguaggio basato su tree-sitter.

    Interfaccia unificata per tutti i linguaggi supportati.
    Usa AST reale invece di regex per estrazione accurata.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._logger = get_logger("treesitter_parser")

    def _get_parser(self, language: str) -> Parser | None:
        """Lazy init dei parser per linguaggio."""
        if language not in self._parsers:
            lang = self._languages.get(language)
            if not lang:
                lang = _load_language(language)
                if not lang:
                    return None
                self._languages[language] = lang
            self._parsers[language] = Parser(lang)
        return self._parsers[language]

    def parse_file(self, file_path: Path, content: str) -> ParsedFile | None:
        """Parsa un file e ritorna struttura arricchita.

        Returns None se il linguaggio non e' supportato.
        """
        language = self._detect_language(file_path)
        if not language:
            return None

        parser = self._get_parser(language)
        if not parser:
            return None

        try:
            tree = parser.parse(content.encode("utf-8"))
        except Exception as e:
            self._logger.warning(f"Parse failed for {file_path}: {e}")
            return None

        root = tree.root_node

        return ParsedFile(
            path=str(file_path),
            language=language,
            functions=self._extract_functions(root, content, language),
            classes=self._extract_classes(root, content, language),
            imports=self._extract_imports(root, content, language),
            parse_errors=self._count_errors(root),
            lines=content.count("\n") + 1,
        )

    # ── Function extraction ──────────────────────────────────────────

    def _extract_functions(
        self, root: Node, content: str, language: str
    ) -> list[ParsedFunction]:
        """Estrae funzioni dall'AST."""
        functions: list[ParsedFunction] = []

        if language == "python":
            self._extract_python_functions(root, content, functions)
        elif language in ("javascript", "typescript", "tsx"):
            self._extract_js_functions(root, content, functions)
        elif language == "go":
            self._extract_go_functions(root, content, functions)
        elif language == "java":
            self._extract_java_functions(root, content, functions)

        return functions

    def _extract_python_functions(
        self, node: Node, content: str, result: list[ParsedFunction]
    ) -> None:
        """Estrae funzioni Python (function_definition, decorated_definition)."""
        for child in node.children:
            if child.type == "decorated_definition":
                decorators = []
                func_node = None
                for sub in child.children:
                    if sub.type == "decorator":
                        dec_text = self._node_text(sub, content).strip()
                        decorators.append(dec_text)
                    elif sub.type in ("function_definition", "async_function_definition"):
                        func_node = sub

                if func_node:
                    f = self._parse_python_func_node(func_node, content)
                    if f:
                        f.decorators = decorators
                        result.append(f)

            elif child.type in ("function_definition", "async_function_definition"):
                f = self._parse_python_func_node(child, content)
                if f:
                    result.append(f)

            elif child.type == "class_definition":
                # Extract methods from class body
                body = child.child_by_field_name("body")
                if body:
                    self._extract_python_functions(body, content, result)

    def _parse_python_func_node(
        self, node: Node, content: str
    ) -> ParsedFunction | None:
        """Parse a single Python function_definition node."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        name = self._node_text(name_node, content)
        is_async = any(c.type == "async" for c in node.children)

        # Parameters
        params = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "identifier":
                    params.append(self._node_text(p, content))
                elif p.type in ("typed_parameter", "typed_default_parameter",
                                "default_parameter"):
                    # typed_default_parameter has 'name' field
                    pname = p.child_by_field_name("name")
                    if pname:
                        params.append(self._node_text(pname, content))
                    else:
                        # typed_parameter: first child identifier is the name
                        for sub in p.children:
                            if sub.type == "identifier":
                                params.append(self._node_text(sub, content))
                                break

        # Filter 'self' and 'cls'
        params = [p for p in params if p not in ("self", "cls")]

        # Return type
        return_type = None
        rt_node = node.child_by_field_name("return_type")
        if rt_node:
            return_type = self._node_text(rt_node, content)

        # Docstring
        docstring = self._extract_docstring(node, content, "python")

        # Complexity
        body = node.child_by_field_name("body")
        complexity = self._calculate_complexity(body) if body else 1

        return ParsedFunction(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            params=params,
            return_type=return_type,
            docstring=docstring,
            is_async=is_async,
            complexity=complexity,
        )

    def _extract_js_functions(
        self, node: Node, content: str, result: list[ParsedFunction]
    ) -> None:
        """Estrae funzioni JS/TS (function_declaration, method_definition, arrow)."""
        for child in node.children:
            if child.type == "export_statement":
                # Unwrap export
                self._extract_js_functions(child, content, result)
                continue

            if child.type in ("function_declaration", "generator_function_declaration"):
                f = self._parse_js_func_node(child, content)
                if f:
                    result.append(f)

            elif child.type == "class_declaration":
                # Extract methods from class body
                body = child.child_by_field_name("body")
                if body:
                    for member in body.children:
                        if member.type == "method_definition":
                            f = self._parse_js_method_node(member, content)
                            if f:
                                result.append(f)

            elif child.type == "lexical_declaration":
                # const foo = async () => {} or const foo = function() {}
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        name_node = decl.child_by_field_name("name")
                        value_node = decl.child_by_field_name("value")
                        if name_node and value_node:
                            if value_node.type in ("arrow_function", "function_expression",
                                                   "generator_function"):
                                is_async = any(c.type == "async" for c in value_node.children)
                                result.append(ParsedFunction(
                                    name=self._node_text(name_node, content),
                                    start_line=child.start_point[0] + 1,
                                    end_line=child.end_point[0] + 1,
                                    is_async=is_async,
                                ))

    def _parse_js_func_node(
        self, node: Node, content: str
    ) -> ParsedFunction | None:
        """Parse JS function_declaration."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        is_async = any(c.type == "async" for c in node.children)

        params = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type in ("identifier", "required_parameter", "optional_parameter"):
                    pn = p.child_by_field_name("pattern") or p
                    if pn.type == "identifier":
                        params.append(self._node_text(pn, content))

        return ParsedFunction(
            name=self._node_text(name_node, content),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            params=params,
            is_async=is_async,
        )

    def _parse_js_method_node(
        self, node: Node, content: str
    ) -> ParsedFunction | None:
        """Parse JS method_definition."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        is_async = any(c.type == "async" for c in node.children)
        name = self._node_text(name_node, content)

        return ParsedFunction(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=is_async,
        )

    def _extract_go_functions(
        self, node: Node, content: str, result: list[ParsedFunction]
    ) -> None:
        """Estrae funzioni Go (function_declaration, method_declaration)."""
        for child in node.children:
            if child.type in ("function_declaration", "method_declaration"):
                name_node = child.child_by_field_name("name")
                if not name_node:
                    continue

                params = []
                params_node = child.child_by_field_name("parameters")
                if params_node:
                    for p in params_node.children:
                        if p.type == "parameter_declaration":
                            for sub in p.children:
                                if sub.type == "identifier":
                                    params.append(self._node_text(sub, content))
                                    break

                body = child.child_by_field_name("body")
                complexity = self._calculate_complexity(body) if body else 1

                result.append(ParsedFunction(
                    name=self._node_text(name_node, content),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    params=params,
                    complexity=complexity,
                ))

    def _extract_java_functions(
        self, node: Node, content: str, result: list[ParsedFunction]
    ) -> None:
        """Estrae metodi Java da class_declaration e top-level."""
        for child in node.children:
            if child.type in ("class_declaration", "interface_declaration"):
                body = child.child_by_field_name("body")
                if body:
                    for member in body.children:
                        if member.type in ("method_declaration", "constructor_declaration"):
                            f = self._parse_java_method_node(member, content)
                            if f:
                                result.append(f)

    def _parse_java_method_node(
        self, node: Node, content: str
    ) -> ParsedFunction | None:
        """Parse Java method_declaration."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        params = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "formal_parameter":
                    pname = p.child_by_field_name("name")
                    if pname:
                        params.append(self._node_text(pname, content))

        return_type = None
        type_node = node.child_by_field_name("type")
        if type_node:
            return_type = self._node_text(type_node, content)

        body = node.child_by_field_name("body")
        complexity = self._calculate_complexity(body) if body else 1

        return ParsedFunction(
            name=self._node_text(name_node, content),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            params=params,
            return_type=return_type,
            complexity=complexity,
        )

    # ── Class extraction ─────────────────────────────────────────────

    def _extract_classes(
        self, root: Node, content: str, language: str
    ) -> list[ParsedClass]:
        """Estrae classi dall'AST."""
        classes: list[ParsedClass] = []

        if language == "python":
            self._extract_python_classes(root, content, classes)
        elif language in ("javascript", "typescript", "tsx"):
            self._extract_js_classes(root, content, classes)
        elif language == "go":
            self._extract_go_structs(root, content, classes)
        elif language == "java":
            self._extract_java_classes(root, content, classes)

        return classes

    def _extract_python_classes(
        self, node: Node, content: str, result: list[ParsedClass]
    ) -> None:
        """Estrae classi Python."""
        for child in node.children:
            class_node = None
            decorators = []

            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type == "decorator":
                        decorators.append(self._node_text(sub, content).strip())
                    elif sub.type == "class_definition":
                        class_node = sub
            elif child.type == "class_definition":
                class_node = child

            if not class_node:
                continue

            name_node = class_node.child_by_field_name("name")
            if not name_node:
                continue

            # Base classes
            bases = []
            superclasses = class_node.child_by_field_name("superclasses")
            if superclasses:
                for arg in superclasses.children:
                    if arg.type in ("identifier", "attribute"):
                        bases.append(self._node_text(arg, content))

            # Methods
            methods = []
            body = class_node.child_by_field_name("body")
            if body:
                for member in body.children:
                    func_node = None
                    if member.type in ("function_definition", "async_function_definition"):
                        func_node = member
                    elif member.type == "decorated_definition":
                        for sub in member.children:
                            if sub.type in ("function_definition", "async_function_definition"):
                                func_node = sub
                    if func_node:
                        mn = func_node.child_by_field_name("name")
                        if mn:
                            methods.append(self._node_text(mn, content))

            # Docstring
            docstring = self._extract_docstring(class_node, content, "python")

            result.append(ParsedClass(
                name=self._node_text(name_node, content),
                start_line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                methods=methods,
                base_classes=bases,
                docstring=docstring,
                decorators=decorators,
            ))

    def _extract_js_classes(
        self, node: Node, content: str, result: list[ParsedClass]
    ) -> None:
        """Estrae classi JS/TS."""
        for child in node.children:
            if child.type == "export_statement":
                self._extract_js_classes(child, content, result)
                continue

            if child.type != "class_declaration":
                continue

            name_node = child.child_by_field_name("name")
            if not name_node:
                continue

            # Superclass (extends)
            bases = []
            heritage = child.child_by_field_name("heritage") or None
            # In JS grammar, the heritage is a "class_heritage" node
            for sub in child.children:
                if sub.type == "class_heritage":
                    for h in sub.children:
                        if h.type == "identifier":
                            bases.append(self._node_text(h, content))

            # Methods
            methods = []
            body = child.child_by_field_name("body")
            if body:
                for member in body.children:
                    if member.type == "method_definition":
                        mn = member.child_by_field_name("name")
                        if mn:
                            methods.append(self._node_text(mn, content))

            result.append(ParsedClass(
                name=self._node_text(name_node, content),
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                methods=methods,
                base_classes=bases,
            ))

    def _extract_go_structs(
        self, node: Node, content: str, result: list[ParsedClass]
    ) -> None:
        """Estrae struct Go (type_declaration con struct_type)."""
        for child in node.children:
            if child.type != "type_declaration":
                continue
            for spec in child.children:
                if spec.type == "type_spec":
                    name_node = spec.child_by_field_name("name")
                    type_node = spec.child_by_field_name("type")
                    if name_node and type_node and type_node.type == "struct_type":
                        result.append(ParsedClass(
                            name=self._node_text(name_node, content),
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                        ))

    def _extract_java_classes(
        self, node: Node, content: str, result: list[ParsedClass]
    ) -> None:
        """Estrae classi Java."""
        for child in node.children:
            if child.type == "class_declaration":
                name_node = child.child_by_field_name("name")
                if not name_node:
                    continue

                bases = []
                # superclass
                sc = child.child_by_field_name("superclass")
                if sc:
                    # The superclass field wraps "extends Type"
                    for sub in sc.children:
                        if sub.type == "type_identifier":
                            bases.append(self._node_text(sub, content))
                # interfaces (super_interfaces → type_list → type_identifier)
                ifaces = child.child_by_field_name("interfaces")
                if ifaces:
                    for sub in ifaces.children:
                        if sub.type == "type_identifier":
                            bases.append(self._node_text(sub, content))
                        elif sub.type == "type_list":
                            for t in sub.children:
                                if t.type == "type_identifier":
                                    bases.append(self._node_text(t, content))

                # Methods
                methods = []
                body = child.child_by_field_name("body")
                if body:
                    for member in body.children:
                        if member.type in ("method_declaration", "constructor_declaration"):
                            mn = member.child_by_field_name("name")
                            if mn:
                                methods.append(self._node_text(mn, content))

                result.append(ParsedClass(
                    name=self._node_text(name_node, content),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    methods=methods,
                    base_classes=bases,
                ))

    # ── Import extraction ────────────────────────────────────────────

    def _extract_imports(
        self, root: Node, content: str, language: str
    ) -> list[ParsedImport]:
        """Estrae import dall'AST."""
        imports: list[ParsedImport] = []

        if language == "python":
            self._extract_python_imports(root, content, imports)
        elif language in ("javascript", "typescript", "tsx"):
            self._extract_js_imports(root, content, imports)
        elif language == "go":
            self._extract_go_imports(root, content, imports)
        elif language == "java":
            self._extract_java_imports(root, content, imports)

        return imports

    def _extract_python_imports(
        self, node: Node, content: str, result: list[ParsedImport]
    ) -> None:
        """Estrae import Python."""
        for child in node.children:
            if child.type == "import_statement":
                # import X, import X as Y
                name_node = child.child_by_field_name("name")
                if name_node:
                    module = self._node_text(name_node, content)
                    alias = None
                    alias_node = child.child_by_field_name("alias")
                    if alias_node:
                        alias = self._node_text(alias_node, content)
                    result.append(ParsedImport(
                        module=module,
                        is_from=False,
                        alias=alias,
                        line=child.start_point[0] + 1,
                    ))

            elif child.type == "import_from_statement":
                # from X import Y, Z
                module_node = child.child_by_field_name("module_name")
                if module_node:
                    module = self._node_text(module_node, content)
                else:
                    # Fallback: find dotted_name after 'from'
                    module = ""
                    for sub in child.children:
                        if sub.type == "dotted_name" and module == "":
                            module = self._node_text(sub, content)
                            break
                        elif sub.type == "relative_import":
                            module = self._node_text(sub, content)
                            break

                names = []
                for sub in child.children:
                    if sub.type == "dotted_name" and self._node_text(sub, content) != module:
                        names.append(self._node_text(sub, content))
                    elif sub.type == "aliased_import":
                        name_sub = sub.child_by_field_name("name")
                        if name_sub:
                            names.append(self._node_text(name_sub, content))

                result.append(ParsedImport(
                    module=module,
                    names=names,
                    is_from=True,
                    line=child.start_point[0] + 1,
                ))

    def _extract_js_imports(
        self, node: Node, content: str, result: list[ParsedImport]
    ) -> None:
        """Estrae import JS/TS."""
        for child in node.children:
            if child.type == "import_statement":
                # import X from 'module'
                source = None
                for sub in child.children:
                    if sub.type == "string":
                        source = self._node_text(sub, content).strip("'\"")
                if source:
                    result.append(ParsedImport(
                        module=source,
                        is_from=True,
                        line=child.start_point[0] + 1,
                    ))

    def _extract_go_imports(
        self, node: Node, content: str, result: list[ParsedImport]
    ) -> None:
        """Estrae import Go."""
        for child in node.children:
            if child.type == "import_declaration":
                for sub in child.children:
                    if sub.type == "import_spec":
                        path_node = sub.child_by_field_name("path")
                        if path_node:
                            module = self._node_text(path_node, content).strip('"')
                            result.append(ParsedImport(
                                module=module,
                                line=sub.start_point[0] + 1,
                            ))
                    elif sub.type == "import_spec_list":
                        for spec in sub.children:
                            if spec.type == "import_spec":
                                path_node = spec.child_by_field_name("path")
                                if path_node:
                                    module = self._node_text(path_node, content).strip('"')
                                    result.append(ParsedImport(
                                        module=module,
                                        line=spec.start_point[0] + 1,
                                    ))

    def _extract_java_imports(
        self, node: Node, content: str, result: list[ParsedImport]
    ) -> None:
        """Estrae import Java."""
        for child in node.children:
            if child.type == "import_declaration":
                # The full import path is in a scoped_identifier or identifier chain
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        module = self._node_text(sub, content)
                        result.append(ParsedImport(
                            module=module,
                            line=child.start_point[0] + 1,
                        ))
                        break

    # ── Utility methods ──────────────────────────────────────────────

    def _count_errors(self, root: Node) -> int:
        """Conta nodi ERROR nell'AST."""
        count = 0
        cursor = root.walk()
        reached_root = False
        while True:
            if cursor.node.type == "ERROR":
                count += 1
            if cursor.goto_first_child():
                continue
            if cursor.goto_next_sibling():
                continue
            while True:
                if not cursor.goto_parent():
                    reached_root = True
                    break
                if cursor.goto_next_sibling():
                    break
            if reached_root:
                break
        return count

    def _extract_docstring(
        self, node: Node, content: str, language: str
    ) -> str | None:
        """Estrae docstring dal primo statement del body."""
        body = node.child_by_field_name("body")
        if not body:
            return None

        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        text = self._node_text(sub, content)
                        # Strip triple quotes
                        if text.startswith(('"""', "'''")):
                            text = text[3:-3].strip()
                        elif text.startswith(('"', "'")):
                            text = text[1:-1].strip()
                        return text
                break  # Only check first statement
            elif child.type not in ("comment", "newline"):
                break

        return None

    def _calculate_complexity(self, node: Node) -> int:
        """Complessita' ciclomatica approssimata.

        Conta nodi if/for/while/case/and/or/catch.
        """
        decision_nodes = {
            "if_statement", "elif_clause", "else_clause",
            "for_statement", "for_in_statement",
            "while_statement",
            "case_clause", "catch_clause",
            "boolean_operator",  # Python and/or
            "binary_expression",  # JS &&/||
            "conditional_expression", "ternary_expression",
        }
        count = 1  # base complexity
        cursor = node.walk()
        reached_root = False
        while True:
            if cursor.node.type in decision_nodes:
                count += 1
            if cursor.goto_first_child():
                continue
            if cursor.goto_next_sibling():
                continue
            while True:
                if not cursor.goto_parent():
                    reached_root = True
                    break
                if cursor.node == node:
                    reached_root = True
                    break
                if cursor.goto_next_sibling():
                    break
            if reached_root:
                break
        return count

    def _detect_language(self, file_path: Path) -> str | None:
        """Detecta linguaggio dal suffisso del file."""
        return SUPPORTED_LANGUAGES.get(file_path.suffix.lower())

    def _node_text(self, node: Node, content: str) -> str:
        """Estrae testo di un nodo dall'AST."""
        return content[node.start_byte:node.end_byte]
