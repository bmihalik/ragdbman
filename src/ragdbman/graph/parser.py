# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Tree-sitter syntax observations, conservative bindings and AST chunk boundaries."""

from __future__ import annotations

import hashlib
import importlib
import posixpath
import re
import threading
import warnings
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from tree_sitter import Language, Parser

from ..extract.text import decode
from ..models import Block, Document

EXTENSIONS = {
    "py": "python",
    "pyi": "python",
    "rs": "rust",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "hpp": "cpp",
    "hh": "cpp",
    "hxx": "cpp",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "tsx",
    "go": "go",
    "java": "java",
    "cs": "c_sharp",
}
LANGUAGES = sorted(set(EXTENSIONS.values()))
REVISION = "syntax-graph-1"
_local = threading.local()
STRUCTURAL = {
    "function",
    "method",
    "class",
    "struct",
    "trait",
    "interface",
    "enum",
    "namespace",
    "module",
    "implementation",
    "type_alias",
}
DEFINITIONS = {
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "function_signature_item": "function",
    "method_definition": "method",
    "method_declaration": "method",
    "method_signature": "method",
    "constructor_declaration": "method",
    "class_definition": "class",
    "class_declaration": "class",
    "class_specifier": "class",
    "struct_item": "struct",
    "struct_specifier": "struct",
    "struct_declaration": "struct",
    "trait_item": "trait",
    "interface_declaration": "interface",
    "enum_item": "enum",
    "enum_specifier": "enum",
    "enum_declaration": "enum",
    "namespace_definition": "namespace",
    "namespace_declaration": "namespace",
    "mod_item": "module",
    "type_item": "type_alias",
    "type_alias_declaration": "type_alias",
}
CALLS = {
    "call",
    "call_expression",
    "method_invocation",
    "invocation_expression",
    "object_creation_expression",
    "new_expression",
}
IDENTIFIERS = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "namespace_identifier",
    "package_identifier",
}
IMPORT_NODES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "use_declaration",
    "using_directive",
    "preproc_include",
}


def normalize(name):
    return re.sub(r"(?:::|->)", ".", name.strip()).replace("?.", ".")


def uid(*parts):
    return hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()[:32]


def language_for(path):
    return EXTENSIONS.get(path.suffix.lower().lstrip("."))


@lru_cache(maxsize=32)
def parser_version(language):
    if not language:
        return REVISION + ":unsupported"
    package = "typescript" if language == "tsx" else language.replace("_", "-")
    return f"{REVISION}:{language}:{version('tree-sitter')}:{version('tree-sitter-' + package)}"


def parser_for(language, timeout_ms):
    parsers = getattr(_local, "parsers", None)
    if parsers is None:
        parsers = _local.parsers = {}
    if language not in parsers:
        module = importlib.import_module("tree_sitter_" + ("typescript" if language == "tsx" else language))
        factory = (
            getattr(module, "language_" + language) if language in {"typescript", "tsx"} else module.language
        )
        parsers[language] = Parser(Language(factory()))
    parser = parsers[language]
    parser.reset()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        parser.timeout_micros = timeout_ms * 1000
    return parser


def namespace(path, roots):
    path = Path(path).resolve()
    candidates = [
        Path(r).expanduser().resolve() for r in roots if path.is_relative_to(Path(r).expanduser().resolve())
    ]
    root = max(candidates, key=lambda r: len(r.parts)) if candidates else path.parent
    relative = path.relative_to(root).as_posix()
    return uid(str(root)), relative


def module_key(path, language):
    stem = posixpath.splitext(path)[0]
    if language == "python":
        return stem.removesuffix("/__init__").replace("/", ".")
    if language == "rust":
        stem = stem.removeprefix("src/").removesuffix("/mod")
        return "crate" if stem in {"lib", "main", "mod"} else "crate." + stem.replace("/", ".")
    if language in {"javascript", "typescript", "tsx"}:
        return stem.removesuffix("/index").replace("/", ".")
    if language == "go":
        return posixpath.dirname(path).replace("/", ".") or "main"
    return stem.replace("/", ".") if language not in {"c", "cpp"} else path


def prepare(path, source_id, digest, roots, config):
    language = language_for(path)
    root_key, relative = namespace(path, roots)
    snapshot = dict(
        source_id=source_id,
        content_hash=digest,
        parser_version=parser_version(language),
        root_key=root_key,
        path=relative,
        module_key=module_key(relative, language),
        language=language,
        status="unsupported_language",
        warnings=[],
        imports=[],
        entities=[],
        relationships=[],
    )
    if not language:
        return snapshot, None
    if path.stat().st_size > config.max_file_size_mb * 1024 * 1024:
        snapshot.update(status="size_limit", warnings=["Source exceeds configured graph parsing size limit"])
        return snapshot, None
    raw = path.read_bytes()
    snapshot["content_hash"] = hashlib.sha256(raw).hexdigest()
    text = decode(raw)
    data = text.encode("utf-8")
    try:
        tree = parser_for(language, config.parse_timeout_ms).parse(data)
        if tree is None or tree.root_node.has_error:
            snapshot.update(
                status="parse_error", warnings=["Tree-sitter reported syntax errors; graph facts omitted"]
            )
            return snapshot, None
        extractor = Extractor(snapshot, data, config)
        extractor.build(tree.root_node)
        snapshot["status"] = "truncated" if extractor.truncated else "parsed"
        if extractor.truncated:
            snapshot["warnings"].append("Graph extraction budget reached; graph is partial")
        return snapshot, ast_document(text, path, snapshot["entities"]) if not extractor.truncated else None
    except (ValueError, RuntimeError, RecursionError) as exc:
        snapshot.update(
            status="parse_error",
            warnings=[f"Tree-sitter parsing failed: {type(exc).__name__}"],
            entities=[],
            relationships=[],
            imports=[],
        )
        return snapshot, None


class Extractor:
    def __init__(self, snapshot, data, config):
        self.graph, self.data, self.config = snapshot, data, config
        self.language = snapshot["language"]
        self.by_node, self.owners, self.name_nodes, self.import_nodes = {}, {}, set(), set()
        self.nodes, self.entities, self.edges = [], snapshot["entities"], snapshot["relationships"]
        self.bindings, self.counts = {}, {}
        self.declared_names = set()
        self.truncated = False

    def text(self, node):
        return self.data[node.start_byte : node.end_byte].decode("utf-8") if node else ""

    def field(self, node, name):
        return node.child_by_field_name(name)

    def span(self, node):
        return node.start_point.row + 1, max(
            node.start_point.row + 1, node.end_point.row + bool(node.end_point.column)
        )

    def descendants(self, node):
        stack = [node]
        visited = 0
        while stack:
            visited += 1
            if visited > self.config.max_parse_nodes:
                self.truncated = True
                break
            current = stack.pop()
            yield current
            stack.extend(reversed(current.named_children))

    def entity(self, node, kind, name, owner):
        if len(self.entities) >= self.config.max_entities_per_file:
            self.truncated = True
            return owner
        name = normalize(name)
        scope = owner["qualified_name"] if owner else ""
        qualified = ".".join(filter(None, (scope, name)))
        ordinal = self.counts.get((kind, qualified), 0)
        self.counts[kind, qualified] = ordinal + 1
        start, end = self.span(node)
        body = self.field(node, "body")
        signature = self.data[node.start_byte : body.start_byte if body else node.end_byte].decode("utf-8")
        item = dict(
            id=uid(self.graph["source_id"], kind, qualified, ordinal),
            kind=kind,
            name=name.rsplit(".", 1)[-1],
            qualified_name=qualified,
            scope=scope,
            line_start=start,
            line_end=end,
            byte_start=node.start_byte,
            byte_end=node.end_byte,
            signature=re.sub(r"\s+", " ", signature)[:512],
        )
        self.entities.append(item)
        self.declared_names.add(qualified)
        self.by_node[node.id] = item
        if owner:
            self.edge(owner, "contains", item["qualified_name"], node, hint=item["id"])
        return item

    def edge(self, owner, kind, target, node, mode="lexical", key=None, hint=None):
        if not target or not owner:
            return
        if len(self.edges) >= self.config.max_relationships_per_file:
            self.truncated = True
            return
        start, end = self.span(node)
        target = normalize(target)
        key = normalize(key if key is not None else target)
        if mode == "lexical":
            first, _, tail = key.partition(".")
            binding = self.bindings.get(first)
            # A lexical declaration shadows a file import. Do not guess through it.
            scope = owner["qualified_name"]
            while binding:
                qualified = ".".join(filter(None, (scope, first)))
                if qualified in self.declared_names:
                    binding = None
                    break
                if not scope:
                    break
                scope = scope.rsplit(".", 1)[0] if "." in scope else ""
            if binding:
                mode = binding["mode"]
                key = ".".join(filter(None, (binding["key"], tail)))
        item = dict(
            id=uid(owner["id"], kind, key, node.start_byte, node.end_byte),
            from_id=owner["id"],
            kind=kind,
            target_name=target,
            target_key=key,
            target_leaf=key.rsplit(".", 1)[-1],
            target_mode=mode,
            target_hint=hint,
            line_start=start,
            line_end=end,
            evidence=re.sub(r"\s+", " ", self.text(node))[:240],
        )
        if not any(e["id"] == item["id"] for e in self.edges[-8:]):
            self.edges.append(item)

    def declaration(self, node):
        kind = DEFINITIONS.get(node.type)
        named = self.field(node, "name")
        if node.type in {"struct_specifier", "class_specifier", "enum_specifier"} and not self.field(
            node, "body"
        ):
            return None, None
        if node.type == "mod_item" and not self.field(node, "body"):
            return None, None
        if node.type == "type_spec":
            value = self.field(node, "type")
            kind = {"struct_type": "struct", "interface_type": "interface"}.get(
                value.type if value else "", "type_alias"
            )
        if node.type == "type_definition":
            named = self.field(node, "declarator")
            value = self.field(node, "type")
            kind = "struct" if value and value.type == "struct_specifier" else "type_alias"
        if node.type == "variable_declarator":
            value = self.field(node, "value")
            if value and value.type in {"arrow_function", "function_expression", "generator_function"}:
                kind = "function"
            else:
                kind = "variable"
        if node.type in {"let_declaration", "const_item", "static_item"}:
            named = self.field(node, "pattern") or named
            kind = "variable"
        if node.type == "assignment":
            named = self.field(node, "left")
            kind = "variable"
        if node.type in {
            "parameter",
            "parameter_declaration",
            "formal_parameter",
            "required_parameter",
            "optional_parameter",
            "typed_parameter",
            "default_parameter",
            "typed_default_parameter",
        }:
            kind = "parameter"
            named = named or self.field(node, "pattern") or self.field(node, "declarator")
            if named is None:
                named = next((n for n in node.named_children if n.type == "identifier"), None)
        if (
            node.type == "identifier"
            and node.parent
            and node.parent.type in {"parameters", "formal_parameters"}
        ):
            return "parameter", node
        if kind and named is None:
            declarator = self.field(node, "declarator")
            while declarator and declarator.type not in IDENTIFIERS | {"qualified_identifier"}:
                declarator = self.field(declarator, "declarator")
            named = declarator
        if kind and named and named.type in IDENTIFIERS | {"qualified_identifier"}:
            return kind, named
        return None, None

    def import_observations(self, node, module):
        raw = self.text(node)
        imports = []

        def add(alias, target, mode="qualified", dependency=None):
            if len(self.graph["imports"]) + len(imports) >= self.config.max_relationships_per_file:
                self.truncated = True
                return
            target = normalize(target)
            if alias:
                self.bindings[alias] = dict(key=target, mode=mode)
            imports.append(dict(alias=alias, target=target, mode=mode, statement=raw[:512]))
            self.edge(module, "imports", target, node, mode=mode)
            self.edge(module, "depends_on", dependency or target, node, mode=mode)

        if self.language == "python":
            base = self.text(self.field(node, "module_name"))
            if base.startswith("."):
                dots = len(base) - len(base.lstrip("."))
                package = self.graph["module_key"].split(".")
                if not self.graph["path"].endswith("__init__.py"):
                    package = package[:-1]
                base = ".".join(package[: max(0, len(package) - dots + 1)] + [base.lstrip(".")]).strip(".")
            for child in node.children_by_field_name("name"):
                name = (
                    self.text(self.field(child, "name"))
                    if child.type == "aliased_import"
                    else self.text(child)
                )
                alias = (
                    self.text(self.field(child, "alias"))
                    if child.type == "aliased_import"
                    else name.split(".")[0]
                )
                target = ".".join(filter(None, (base, name)))
                if node.type == "import_statement" and child.type != "aliased_import":
                    add(alias, name, dependency=name)
                    if alias in self.bindings:
                        self.bindings[alias]["key"] = alias
                else:
                    add(alias, target, dependency=target)
        elif self.language in {"javascript", "typescript", "tsx"}:
            source = self.text(self.field(node, "source")).strip("'\"")
            mode = "qualified" if source.startswith(".") else "external"
            path = posixpath.normpath(posixpath.join(posixpath.dirname(self.graph["path"]), source))
            key = module_key(path, self.language) if mode == "qualified" else source
            if path.startswith("../"):
                mode = "external"
            specifiers = [n for n in self.descendants(node) if n.type == "import_specifier"]
            for spec in specifiers:
                name = self.text(self.field(spec, "name"))
                alias = self.text(self.field(spec, "alias")) or name
                add(alias, f"{key}.{name}", mode, key)
            for child in self.descendants(node):
                if child.type == "namespace_import":
                    alias = next((self.text(n) for n in child.named_children if n.type == "identifier"), "")
                    add(alias, key, mode, key)
                elif child.type == "import_clause":
                    for part in child.named_children:
                        if part.type == "identifier":
                            add(self.text(part), f"{key}.default", mode, key)
            if not imports:
                add("", key, mode, key)
        elif self.language in {"c", "cpp"} and node.type == "preproc_include":
            value = self.text(self.field(node, "path"))
            relative = value.startswith('"')
            target = value.strip('<>"')
            if relative:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(self.graph["path"]), target))
            add("", target, "file" if relative and not target.startswith("../") else "external")
        elif self.language == "rust":
            argument = self.field(node, "argument")

            def use(n, prefix=""):
                if n.type == "use_as_clause":
                    target = ".".join(filter(None, (prefix, normalize(self.text(self.field(n, "path"))))))
                    add(self.text(self.field(n, "alias")), rust_target(target, self.graph["module_key"]))
                elif n.type == "scoped_use_list":
                    base = normalize(self.text(self.field(n, "path")))
                    for child in self.field(n, "list").named_children:
                        use(child, ".".join(filter(None, (prefix, base))))
                elif n.type == "use_list":
                    for child in n.named_children:
                        use(child, prefix)
                else:
                    target = ".".join(filter(None, (prefix, normalize(self.text(n)))))
                    add(target.rsplit(".", 1)[-1], rust_target(target, self.graph["module_key"]))

            if argument:
                use(argument)
        elif self.language == "go":
            for spec in self.descendants(node):
                if spec.type == "import_spec":
                    target = self.text(self.field(spec, "path")).strip('"`')
                    alias = self.text(self.field(spec, "name")) or target.rsplit("/", 1)[-1]
                    add(alias, target, "external")
        elif self.language == "java":
            target = raw.removeprefix("import").strip().removeprefix("static").strip().rstrip(";").strip()
            add(target.rsplit(".", 1)[-1], target)
        elif self.language == "c_sharp":
            target = raw.removeprefix("using").strip().rstrip(";").strip()
            if "=" in target:
                alias, target = map(str.strip, target.split("=", 1))
                add(alias, target)
            else:
                add("", target)
        self.graph["imports"].extend(imports)
        self.import_nodes.update(n.id for n in self.descendants(node))

    def build(self, root):
        if self.language == "java":
            package = next(
                (
                    self.text(n).removeprefix("package").strip().rstrip(";")
                    for n in root.named_children
                    if n.type == "package_declaration"
                ),
                "",
            )
            self.graph["module_key"] = package
        module = self.entity(root, "module", "", None)
        module["name"] = self.graph["path"]
        module["signature"] = self.graph["path"]
        stack = [(root, module)]
        while stack:
            node, owner = stack.pop()
            if len(self.nodes) >= self.config.max_parse_nodes:
                self.truncated = True
                break
            self.nodes.append(node)
            if node.type in IMPORT_NODES:
                old_bindings = dict(self.bindings)
                old_import_count = len(self.graph["imports"])
                self.import_observations(node, owner)
                if owner is not module:
                    # Scoped imports are observed but not used for file-wide binding.
                    for item in self.graph["imports"][old_import_count:]:
                        if item["alias"]:
                            self.entity(node, "variable", item["alias"], owner)
                    self.bindings = old_bindings
                continue
            if node is not root:
                if node.type == "impl_item":
                    target = normalize(self.text(self.field(node, "type")))
                    owner = self.entity(node, "implementation", target, module)
                else:
                    kind, name_node = self.declaration(node)
                    if kind:
                        name = self.text(name_node)
                        self.name_nodes.update(n.id for n in self.descendants(name_node))
                        if kind == "function" and owner["kind"] in {
                            "class",
                            "struct",
                            "trait",
                            "interface",
                            "implementation",
                        }:
                            kind = "method"
                        if self.language == "go" and node.type == "method_declaration":
                            receiver = self.field(node, "receiver")
                            types = (
                                [
                                    self.text(n)
                                    for n in self.descendants(receiver)
                                    if n.type == "type_identifier"
                                ]
                                if receiver
                                else []
                            )
                            if types:
                                name = types[-1] + "." + name
                        ent = self.entity(node, kind, name, owner)
                        if kind in STRUCTURAL:
                            owner = ent
            self.owners[node.id] = owner
            stack.extend((n, owner) for n in reversed(node.named_children))
        for node in self.nodes:
            if node.id in self.import_nodes:
                continue
            owner = self.owners.get(node.id, module)
            definition = self.by_node.get(node.id)
            if definition:
                self.bases(node, definition)
            if node.type in CALLS:
                fn = (
                    self.field(node, "function")
                    or self.field(node, "name")
                    or self.field(node, "type")
                    or self.field(node, "constructor")
                )
                target = self.text(fn)
                obj = self.field(node, "object")
                if node.type == "method_invocation" and obj:
                    target = self.text(obj) + "." + target
                if re.fullmatch(r"[\w.$:>-]+", target):
                    target = normalize(target)
                    if target.startswith(("self.", "this.", "cls.", "Self.")):
                        target = ".".join(filter(None, (owner["scope"], target.split(".", 1)[1])))
                    self.edge(owner, "calls", target, node)
            if node.type in IDENTIFIERS and node.id not in self.name_nodes:
                parent = node.parent
                if parent and parent.type in {
                    "attribute",
                    "member_expression",
                    "field_expression",
                    "selector_expression",
                }:
                    # Attribute/field names alone do not identify their runtime target.
                    if (
                        node == self.field(parent, "attribute")
                        or node == self.field(parent, "property")
                        or node == self.field(parent, "field")
                    ):
                        continue
                self.edge(owner, "references", self.text(node), node)
            if node.type == "mod_item" and not self.field(node, "body"):
                target = self.graph["module_key"] + "." + self.text(self.field(node, "name"))
                self.edge(module, "depends_on", target, node, mode="qualified")

    def bases(self, node, entity):
        if node.type == "impl_item":
            target = normalize(self.text(self.field(node, "type")))
            candidates = [
                e
                for e in self.entities
                if e["qualified_name"] == target and e["kind"] in {"struct", "class", "enum"}
            ]
            subject = candidates[0] if len(candidates) == 1 else entity
            trait = self.field(node, "trait")
            if trait:
                self.edge(subject, "implements", self.text(trait), node)
            self.edge(entity, "references", target, node)
            return
        base_nodes = []
        for field, kind in (
            ("superclasses", "inherits"),
            ("superclass", "inherits"),
            ("interfaces", "implements"),
        ):
            value = self.field(node, field)
            if value:
                base_nodes.append((value, kind))
        for child in node.named_children:
            if child.type in {"class_heritage", "base_class_clause", "extends_type_clause", "base_list"}:
                base_nodes.append((child, "type_base" if child.type == "base_list" else "inherits"))
        for base, kind in base_nodes:
            stack = [(base, kind)]
            while stack:
                current, relation = stack.pop()
                if current.type in {
                    "type_arguments",
                    "type_parameters",
                    "keyword_argument",
                    "list_splat",
                    "dictionary_splat",
                    "call",
                    "call_expression",
                }:
                    continue
                if current.type == "subscript":
                    value = self.field(current, "value")
                    if value:
                        stack.append((value, relation))
                    continue
                if current.type == "implements_clause":
                    relation = "implements"
                if current.type in {
                    "identifier",
                    "type_identifier",
                    "qualified_identifier",
                    "scoped_type_identifier",
                    "attribute",
                    "member_expression",
                    "nested_type_identifier",
                    "qualified_name",
                }:
                    self.edge(entity, relation, self.text(current), current)
                else:
                    stack.extend((child, relation) for child in reversed(current.named_children))


def rust_target(name, module):
    if name.startswith("self."):
        return module + name[4:]
    if name.startswith("super."):
        return module.rsplit(".", 1)[0] + name[5:]
    return name


def ast_document(text, path, entities):
    lines = text.splitlines()
    boundaries = {1, len(lines) + 1}
    definitions = [e for e in entities if e["kind"] in STRUCTURAL and e["qualified_name"]]
    for entity in definitions:
        boundaries.update((entity["line_start"], min(len(lines) + 1, entity["line_end"] + 1)))
    points = sorted(boundaries)
    blocks = []
    for start, end in zip(points, points[1:], strict=False):
        content = "\n".join(lines[start - 1 : end - 1])
        if not content.strip():
            continue
        owners = [e for e in definitions if e["line_start"] <= start <= e["line_end"]]
        owner = min(owners, key=lambda e: e["line_end"] - e["line_start"]) if owners else None
        section = owner["qualified_name"] if owner else "<module>"
        blocks.append(
            Block(content, heading=section, section_path=section, line_start=start, line_end=end - 1)
        )
    return Document(blocks, "source_code_ast", title=path.name, language=language_for(path))
