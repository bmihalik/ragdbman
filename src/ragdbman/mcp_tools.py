# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Generated MCP declarations. Edit operations.py, then run tools/generate_mcp_tools.py.

Literal tool names and boolean hints are intentional for static source inspection.
The canonical signatures/validation still come from the shared operation catalog."""

from typing import Literal, Optional

from mcp.types import CallToolResult, ToolAnnotations

from .models import SearchFilters
from .operations import invoke, signature


def canonical_signature(name):
    """Preserve model constraints and default factories in the runtime tool schema."""

    def decorate(function):
        function.__signature__ = signature(name, mcp=True)
        function.__annotations__ = {p.name: p.annotation for p in function.__signature__.parameters.values()}
        function.__annotations__["return"] = CallToolResult
        return function

    return decorate


def register_tools(server, engine, admin, present):
    """Register three query tools and, only when enabled, named administrative tools."""

    @server.tool(
        name="corpus_query",
        description="Query one or more document, source-code or Knowledge Card collections. Modes: keyword, semantic, hybrid, structured. Expert perspective applies to cards. Use format=llm for readable evidence or raw for full metadata; structured mode rejects cards.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @canonical_signature("corpus_query")
    async def corpus_query(
        *,
        format: Literal["raw", "llm"] = "llm",
        include_graph_context: bool | None = None,
        query: str,
        collections: list[str] | None = None,
        mode: Literal["keyword", "semantic", "hybrid", "structured"] = "hybrid",
        perspective: Literal["general", "expert"] = "general",
        limit: int = 5,
        minimum_score: float | None = None,
        filters: Optional[SearchFilters] = None,
        include_text: bool = True,
        include_links: bool = True,
    ) -> CallToolResult:
        arguments = {
            "format": format,
            "include_graph_context": include_graph_context,
            "query": query,
            "collections": collections,
            "mode": mode,
            "perspective": perspective,
            "limit": limit,
            "minimum_score": minimum_score,
            "filters": filters,
            "include_text": include_text,
            "include_links": include_links,
        }
        if filters is None:
            arguments.pop("filters")
        return present(await invoke(engine, "corpus_query", arguments, admin=admin))

    @server.tool(
        name="corpus_graph",
        description="Read a source-code syntax graph: find, neighbors, callers, callees, dependencies, inheritance or impact. Static resolution is not a runtime call graph.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @canonical_signature("corpus_graph")
    async def corpus_graph(
        *,
        format: Literal["raw", "llm"] = "llm",
        collection: str,
        action: Literal[
            "find", "neighbors", "callers", "callees", "dependencies", "inheritance", "impact"
        ] = "neighbors",
        symbol: str | None = None,
        entity_id: str | None = None,
        source_id: str | None = None,
        direction: Literal["outgoing", "incoming", "both"] = "outgoing",
        relationships: list[
            Literal[
                "contains",
                "imports",
                "calls",
                "inherits",
                "implements",
                "type_base",
                "references",
                "depends_on",
            ]
        ]
        | None = None,
        depth: int = 1,
        limit: int = 50,
    ) -> CallToolResult:
        arguments = {
            "format": format,
            "collection": collection,
            "action": action,
            "symbol": symbol,
            "entity_id": entity_id,
            "source_id": source_id,
            "direction": direction,
            "relationships": relationships,
            "depth": depth,
            "limit": limit,
        }
        return present(await invoke(engine, "corpus_graph", arguments, admin=admin))

    @server.tool(
        name="corpus_describe",
        description="Discover collections or describe selected collections and capabilities.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @canonical_signature("corpus_describe")
    async def corpus_describe(
        *,
        collections: list[str] | None = None,
    ) -> CallToolResult:
        arguments = {
            "collections": collections,
        }
        return present(await invoke(engine, "corpus_describe", arguments, admin=admin))

    if admin:

        @server.tool(
            name="collections_registry_repair",
            description="Reconstruct the registry from collection databases; no index rebuild. Reject while indexing is active.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collections_registry_repair")
        async def collections_registry_repair() -> CallToolResult:
            return present(await invoke(engine, "collections_registry_repair", {}, admin=admin))

        @server.tool(
            name="collections_list",
            description="List collection configuration and counts for the administrator.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collections_list")
        async def collections_list() -> CallToolResult:
            return present(await invoke(engine, "collections_list", {}, admin=admin))

        @server.tool(
            name="collection_get",
            description="Inspect one collection's settings and counts.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_get")
        async def collection_get(
            *,
            name: str,
        ) -> CallToolResult:
            arguments = {
                "name": name,
            }
            return present(await invoke(engine, "collection_get", arguments, admin=admin))

        @server.tool(
            name="collection_create",
            description="Create an empty collection; probes its embedding model. Registering roots does not start scanning.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_create")
        async def collection_create(
            *,
            name: str,
            description: str | None = None,
            source_roots: Optional[list[str]] = None,
            kind: Literal["general", "source_code", "knowledge_cards"] = "general",
            embedding_model: str | None = None,
            chunk_size_tokens: int | None = None,
            chunk_overlap_tokens: int | None = None,
        ) -> CallToolResult:
            arguments = {
                "name": name,
                "description": description,
                "source_roots": source_roots,
                "kind": kind,
                "embedding_model": embedding_model,
                "chunk_size_tokens": chunk_size_tokens,
                "chunk_overlap_tokens": chunk_overlap_tokens,
            }
            if source_roots is None:
                arguments.pop("source_roots")
            return present(await invoke(engine, "collection_create", arguments, admin=admin))

        @server.tool(
            name="collection_config_update",
            description="Set the description; omission clears it. Kind, embedding model and chunk settings are immutable.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_config_update")
        async def collection_config_update(
            *,
            name: str,
            description: str | None = None,
        ) -> CallToolResult:
            arguments = {
                "name": name,
                "description": description,
            }
            return present(await invoke(engine, "collection_config_update", arguments, admin=admin))

        @server.tool(
            name="collection_delete",
            description="Delete collection indexes with confirm=true. delete_files also deletes managed originals, never external roots.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_delete")
        async def collection_delete(
            *,
            name: str,
            confirm: bool = False,
            delete_files: bool = False,
        ) -> CallToolResult:
            arguments = {
                "name": name,
                "confirm": confirm,
                "delete_files": delete_files,
            }
            return present(await invoke(engine, "collection_delete", arguments, admin=admin))

        @server.tool(
            name="collection_list_files",
            description="List tracked files, statuses and source IDs with pagination.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_list_files")
        async def collection_list_files(
            *,
            collection: str,
            extension: str | None = None,
            path_prefix: str | None = None,
            status: Optional[
                Literal[
                    "discovered",
                    "extracting",
                    "embedding",
                    "indexed",
                    "failed",
                    "unsupported",
                    "queued",
                    "missing",
                ]
            ] = None,
            limit: int = 50,
            offset: int = 0,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "extension": extension,
                "path_prefix": path_prefix,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
            return present(await invoke(engine, "collection_list_files", arguments, admin=admin))

        @server.tool(
            name="collection_get_file",
            description="Inspect file metadata and diagnostics by source ID.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_get_file")
        async def collection_get_file(
            *,
            collection: str,
            source_id: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "source_id": source_id,
            }
            return present(await invoke(engine, "collection_get_file", arguments, admin=admin))

        @server.tool(
            name="collection_add_file",
            description="Index one allowed existing file; wait for completion.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_add_file")
        async def collection_add_file(
            *,
            collection: str,
            path: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "path": path,
            }
            return present(await invoke(engine, "collection_add_file", arguments, admin=admin))

        @server.tool(
            name="collection_upload_file",
            description="Upload base64 content to managed storage and index it.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_upload_file")
        async def collection_upload_file(
            *,
            collection: str,
            filename: str,
            content_base64: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "filename": filename,
                "content_base64": content_base64,
            }
            return present(await invoke(engine, "collection_upload_file", arguments, admin=admin))

        @server.tool(
            name="collection_remove_file",
            description="Remove source index data with confirm=true; optional original deletion is limited to managed files.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_remove_file")
        async def collection_remove_file(
            *,
            collection: str,
            source_id: str,
            confirm: bool = False,
            delete_original_managed_file: bool = False,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "source_id": source_id,
                "confirm": confirm,
                "delete_original_managed_file": delete_original_managed_file,
            }
            return present(await invoke(engine, "collection_remove_file", arguments, admin=admin))

        @server.tool(
            name="collection_list_roots",
            description="List registered roots and their IDs.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_list_roots")
        async def collection_list_roots(
            *,
            collection: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
            }
            return present(await invoke(engine, "collection_list_roots", arguments, admin=admin))

        @server.tool(
            name="collection_add_root",
            description="Register an allowed directory without scanning.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_add_root")
        async def collection_add_root(
            *,
            collection: str,
            path: str,
            recursive: bool = True,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "path": path,
                "recursive": recursive,
            }
            return present(await invoke(engine, "collection_add_root", arguments, admin=admin))

        @server.tool(
            name="collection_remove_root",
            description="Unregister a root with confirm=true; keep files and indexes.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_remove_root")
        async def collection_remove_root(
            *,
            collection: str,
            root_id: str,
            confirm: bool = False,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "root_id": root_id,
                "confirm": confirm,
            }
            return present(await invoke(engine, "collection_remove_root", arguments, admin=admin))

        @server.tool(
            name="scan_start",
            description="Start incremental directory indexing. Missing-file pruning requires confirm=true.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("scan_start")
        async def scan_start(
            *,
            collection: str,
            root: str,
            recursive: bool = True,
            prune_missing: bool = False,
            confirm: bool = False,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "root": root,
                "recursive": recursive,
                "prune_missing": prune_missing,
                "confirm": confirm,
            }
            return present(await invoke(engine, "scan_start", arguments, admin=admin))

        @server.tool(
            name="scan_jobs_list",
            description="List indexing jobs by collection and optional status.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("scan_jobs_list")
        async def scan_jobs_list(
            *,
            collection: str,
            status: Optional[
                Literal[
                    "queued", "running", "paused", "completed", "completed_with_errors", "failed", "cancelled"
                ]
            ] = None,
            limit: int = 50,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "status": status,
                "limit": limit,
            }
            return present(await invoke(engine, "scan_jobs_list", arguments, admin=admin))

        @server.tool(
            name="scan_job_get",
            description="Inspect one job's progress, timing and errors.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("scan_job_get")
        async def scan_job_get(
            *,
            collection: str,
            job_id: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "job_id": job_id,
            }
            return present(await invoke(engine, "scan_job_get", arguments, admin=admin))

        @server.tool(
            name="scan_job_cancel",
            description="Request cooperative cancellation by globally unique job ID.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("scan_job_cancel")
        async def scan_job_cancel(
            *,
            job_id: str,
        ) -> CallToolResult:
            arguments = {
                "job_id": job_id,
            }
            return present(await invoke(engine, "scan_job_cancel", arguments, admin=admin))

        @server.tool(
            name="scan_job_resume",
            description="Resume paused or failed/partial work, resetting attempt counters.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("scan_job_resume")
        async def scan_job_resume(
            *,
            collection: str,
            job_id: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "job_id": job_id,
            }
            return present(await invoke(engine, "scan_job_resume", arguments, admin=admin))

        @server.tool(
            name="collection_list_keywords",
            description="List canonical keyword vocabulary and frequencies.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_list_keywords")
        async def collection_list_keywords(
            *,
            collection: str,
            query: str | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "query": query,
                "limit": limit,
                "offset": offset,
            }
            return present(await invoke(engine, "collection_list_keywords", arguments, admin=admin))

        @server.tool(
            name="collection_list_metadata_fields",
            description="List supported numeric/date filter fields.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_list_metadata_fields")
        async def collection_list_metadata_fields(
            *,
            collection: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
            }
            return present(await invoke(engine, "collection_list_metadata_fields", arguments, admin=admin))

        @server.tool(
            name="collection_export_manifest",
            description="Return collection and source metadata, not a database backup.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_export_manifest")
        async def collection_export_manifest(
            *,
            collection: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
            }
            return present(await invoke(engine, "collection_export_manifest", arguments, admin=admin))

        @server.tool(
            name="collection_rebuild",
            description="Clear derived indexes then reindex tracked files; confirm=true required.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_rebuild")
        async def collection_rebuild(
            *,
            collection: str,
            confirm: bool = False,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
                "confirm": confirm,
            }
            return present(await invoke(engine, "collection_rebuild", arguments, admin=admin))

        @server.tool(
            name="collection_vacuum",
            description="Reclaim unused primary SQLite pages; does not reindex.",
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("collection_vacuum")
        async def collection_vacuum(
            *,
            collection: str,
        ) -> CallToolResult:
            arguments = {
                "collection": collection,
            }
            return present(await invoke(engine, "collection_vacuum", arguments, admin=admin))

        @server.tool(
            name="health_status",
            description="Check engine, vector extension and configured Ollama service.",
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        @canonical_signature("health_status")
        async def health_status() -> CallToolResult:
            return present(await invoke(engine, "health_status", {}, admin=admin))
