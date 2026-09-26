# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Stable error codes shared by CLI, REST, and MCP."""

STATUS = {
    "CONFIG_INVALID": 400,
    "COLLECTION_NOT_FOUND": 404,
    "COLLECTION_BUSY": 409,
    "PATH_NOT_ALLOWED": 403,
    "SOURCE_NOT_FOUND": 404,
    "UNSUPPORTED_MEDIA_TYPE": 415,
    "FILE_TOO_LARGE": 413,
    "EXTRACTION_FAILED": 422,
    "OCR_FAILED": 422,
    "TRANSCRIPTION_FAILED": 422,
    "OLLAMA_UNAVAILABLE": 503,
    "EMBEDDING_FAILED": 502,
    "VECTOR_SCHEMA_MISMATCH": 409,
    "DATABASE_CORRUPT": 500,
    "JOB_CANCELLED": 409,
    "CONFIRMATION_REQUIRED": 400,
    "JOB_NOT_FOUND": 404,
    "NOT_IMPLEMENTED": 501,
    "INTERNAL": 500,
}


class RagError(Exception):
    def __init__(self, code: str, message: str, context: dict | None = None):
        self.code, self.message, self.context = code, message, context
        super().__init__(f"[{code}] {message}")

    @property
    def status_code(self) -> int:
        return STATUS.get(self.code, 500)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            **({"context": self.context} if self.context else {}),
        }


def require_confirmation(confirm: bool) -> None:
    if not confirm:
        raise RagError("CONFIRMATION_REQUIRED", "Explicit confirm=true is required")
