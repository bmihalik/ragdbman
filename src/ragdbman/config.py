# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Validated TOML application configuration."""

from __future__ import annotations

import ipaddress
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import RagError


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ServerConfig(Settings):
    bind: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    mcp_path: str = "/mcp"
    mcp_admin_enabled: bool = False
    mcp_default_collections: list[str] = Field(default_factory=list)
    mcp_allowed_collections: list[str] | None = None
    web_auth_mode: Literal["local", "password", "oauth_proxy"] = "local"
    allow_remote_bind: bool = False
    shutdown_grace_seconds: float = Field(5, gt=0, allow_inf_nan=False)
    shutdown_timeout_seconds: float = Field(30, gt=0, allow_inf_nan=False)


class StorageConfig(Settings):
    data_dir: str = "~/.local/share/ragdbman"
    registry_path: str = "~/.config/ragdbman/collections.json"
    temp_dir: str = "~/.local/share/ragdbman/tmp"
    allowed_source_roots: list[str] = Field(default_factory=list)
    audit_log_retention_days: int = Field(365, ge=1)
    markdown_sidecar_enabled: bool = True
    markdown_sidecar_dir_name: str = ".ragdbman"


class OllamaConfig(Settings):
    base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "bge-m3:567m"
    source_code_embedding_model: str = "unclemusclez/jina-embeddings-v2-base-code:f16"
    keep_alive: str = "24h"
    request_timeout_seconds: float = Field(300, gt=0)
    embedding_batch_size: int = Field(32, ge=1)
    max_concurrent_embedding_requests: int = Field(4, ge=1, le=32)
    health_check_seconds: int = Field(30, ge=1)
    bge_m3_options: dict = Field(default_factory=dict)


class DefaultsConfig(Settings):
    chunk_size_tokens: int = Field(256, ge=1)
    chunk_overlap_tokens: int = Field(64, ge=0)
    scan_batch_size: int = Field(100, ge=1)
    max_concurrent_files: int = Field(4, ge=1, le=32)
    max_file_size_mb: int = Field(500, ge=1)
    recursive_scan: bool = True
    follow_symlinks: bool = False
    store_derived_text: bool = True
    preserve_artifacts: bool = True
    index_hidden_files: bool = False
    allow_approximate_tokenizer: bool = False
    locale: str = "en"


class SourceCodeConfig(Settings):
    chunk_size_tokens: int = Field(400, ge=1)
    chunk_overlap_tokens: int = Field(60, ge=0)


class SearchConfig(Settings):
    default_top_k: int = Field(8, ge=1)
    max_top_k: int = Field(50, ge=1)
    vector_weight: float = Field(0.65, ge=0)
    keyword_weight: float = Field(0.35, ge=0)
    rrf_k: int = Field(60, ge=1)
    return_context_chars_per_chunk: int = Field(2400, ge=1)


class MediaConfig(Settings):
    pdf_backend: Literal["auto", "pypdf", "mineru", "marker", "pymupdf"] = "auto"
    pdf_fallback: bool = True
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    whisper_backend: Literal["whisper_cpp", "faster_whisper", "external_command"] = "whisper_cpp"
    whisper_command: str | None = None
    whisper_model_path: str | None = None
    transcription_language: str = "auto"
    keep_extracted_audio: bool = False
    libreoffice_path: str | None = None
    tesseract_path: str | None = None
    marker_command: str | None = None
    mineru_command: str | None = None
    mineru_cli: Literal["legacy", "parse"] = "legacy"
    mineru_extra_args: list[str] = Field(default_factory=list)
    subprocess_timeout_seconds: float = Field(600, gt=0)
    scratch_dir: str | None = None

    @model_validator(mode="after")
    def validate_mineru_args(self):
        # ragdbman owns input/output paths and full-document page selection.
        reserved = ("--path", "--output", "--pages")
        for arg in self.mineru_extra_args:
            if (
                "\x00" in arg
                or arg in reserved
                or any(arg.startswith(flag + "=") for flag in reserved)
                or arg.startswith(("-p", "-o"))
            ):
                raise ValueError("mineru_extra_args cannot override input/output paths or --pages")
        return self


class SecurityConfig(Settings):
    allow_file_uri_links: bool = True
    allow_http_source_urls: bool = True
    allow_arbitrary_paths_from_mcp: bool = False


class LoggingConfig(Settings):
    level: Literal["critical", "error", "warning", "warn", "info", "verbose", "debug", "trace"] = "info"


class GlobalConfig(Settings):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    source_code: SourceCodeConfig = Field(default_factory=SourceCodeConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def validate_relationships(self):
        if self.server.shutdown_grace_seconds >= self.server.shutdown_timeout_seconds:
            raise ValueError("shutdown_timeout_seconds must exceed shutdown_grace_seconds")
        for section in (self.defaults, self.source_code):
            if section.chunk_overlap_tokens >= section.chunk_size_tokens:
                raise ValueError("chunk_overlap_tokens must be less than chunk_size_tokens")
        if self.search.default_top_k > self.search.max_top_k:
            raise ValueError("default_top_k must be <= max_top_k")
        sidecar = self.storage.markdown_sidecar_dir_name
        if sidecar in {"", ".", ".."} or "/" in sidecar or "\\" in sidecar:
            raise ValueError("markdown_sidecar_dir_name must be a single directory name")
        if (
            not self.server.mcp_path.startswith("/")
            or self.server.mcp_path.rstrip("/") != self.server.mcp_path
            or self.server.mcp_path.split("/")[1]
            in {"", "api", "static", "collections", "docs", "openapi.json"}
            or any(c in self.server.mcp_path for c in "?#%\\")
            or any(p in {".", "..", ""} for p in self.server.mcp_path.split("/")[1:])
        ):
            raise ValueError("mcp_path must be a distinct absolute URL path")
        allowed = self.server.mcp_allowed_collections
        if allowed is not None and not set(self.server.mcp_default_collections).issubset(allowed):
            raise ValueError("MCP default collections must be in mcp_allowed_collections")
        try:
            local = ipaddress.ip_address(self.server.bind).is_loopback
        except ValueError:
            local = self.server.bind == "localhost"
        if not local and not self.server.allow_remote_bind:
            raise ValueError("Non-loopback bind requires allow_remote_bind")
        if self.server.allow_remote_bind and self.server.web_auth_mode == "local":
            raise ValueError("Remote access requires authentication")
        return self

    @classmethod
    def load(cls, path: str | Path) -> GlobalConfig:
        path = Path(path).expanduser()
        try:
            return cls.model_validate(tomllib.loads(path.read_text()) if path.exists() else {})
        except (ValueError, OSError) as exc:
            raise RagError("CONFIG_INVALID", str(exc)) from exc

    def checked_path(self, path: str | Path, managed_root: str | Path | None = None) -> Path:
        candidate = Path(path).expanduser().resolve()
        roots = [Path(p).expanduser().resolve() for p in self.storage.allowed_source_roots]
        if managed_root:
            roots.append(Path(managed_root).resolve())
        if not self.security.allow_arbitrary_paths_from_mcp and not any(
            candidate.is_relative_to(root) for root in roots
        ):
            raise RagError("PATH_NOT_ALLOWED", f"Path is outside allowed_source_roots: {candidate}")
        return candidate
