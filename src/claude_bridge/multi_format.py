"""Optional multi-format readers for Claude Bridge."""

from __future__ import annotations

import base64
import importlib
from pathlib import Path
from typing import Any

from claude_bridge.tool_utils import (
    json_response,
    path_outside_project_details,
    resolve_path,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

_IMAGE_MAX_BYTES = 10 * 1024 * 1024
_PDF_MAX_BYTES = 10 * 1024 * 1024
_PDF_PAGE_LIMIT = 10
_IMAGE_FORMATS = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".webp": "image/webp",
}
_PIL_FORMATS = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "ICO": "image/x-icon",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}

_IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"BM": "image/bmp",
    b"II\x2a\x00": "image/tiff",
    b"MM\x00\x2a": "image/tiff",
    b"\x00\x00\x01\x00": "image/x-icon",
}


def _missing_dependency_response(dependency: str) -> str:
    return json_response(
        False,
        "Optional multi-format dependency is not installed. Install claude-bridge[multi-format].",
        code="dependency_missing",
        details={
            "dependency": dependency,
            "extra": "multi-format",
            "install": "pip install claude-bridge[multi-format]",
        },
    )


def _resolve_read_target(path: str) -> tuple[Path | None, str | None]:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return None, json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return None, json_response(
            False,
            f"File not found: {path}",
            code="file_not_found",
            details={"path": path},
        )
    if not target.is_file():
        return None, json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path, "resolved_path": str(target)},
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return None, json_response(
            False,
            "Sensitive files are blocked from direct reading",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
        )
    return target, None


def _import_image_module() -> Any:
    return importlib.import_module("PIL.Image")


def _import_pdf_module() -> Any:
    return importlib.import_module("PyPDF2")


def _detect_format_by_magic(data: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return mime
    return None


def read_image(path: str) -> str:
    """Read supported image metadata and base64 content from a workspace path."""
    target, error = _resolve_read_target(path)
    if error is not None:
        return error
    assert target is not None

    suffix = target.suffix.lower()
    expected_mime_type = _IMAGE_FORMATS.get(suffix)
    if expected_mime_type is None:
        return json_response(
            False,
            "Unsupported image format. Supported formats: PNG, JPEG, GIF, WebP.",
            code="unsupported_file_type",
            details={
                "path": path,
                "resolved_path": str(target),
                "supported_extensions": sorted(_IMAGE_FORMATS),
            },
        )

    byte_size = target.stat().st_size
    if byte_size > _IMAGE_MAX_BYTES:
        return json_response(
            False,
            "Image is too large to read safely.",
            code="file_too_large",
            details={
                "path": path,
                "resolved_path": str(target),
                "byte_size": byte_size,
                "max_byte_size": _IMAGE_MAX_BYTES,
                "truncated": True,
            },
        )

    try:
        image_module = _import_image_module()
    except ImportError:
        return _missing_dependency_response("Pillow")

    try:
        with image_module.open(target) as image:
            image_format = str(getattr(image, "format", "") or "").upper()
            width, height = image.size
        mime_type = _PIL_FORMATS.get(image_format, expected_mime_type)
        if mime_type not in _IMAGE_FORMATS.values():
            return json_response(
                False,
                "Unsupported image format. Supported formats: PNG, JPEG, GIF, WebP.",
                code="unsupported_file_type",
                details={
                    "path": path,
                    "resolved_path": str(target),
                    "detected_format": image_format,
                    "supported_formats": sorted(_PIL_FORMATS),
                },
            )
        content_base64 = base64.b64encode(target.read_bytes()).decode("ascii")
    except OSError as exc:
        return json_response(
            False,
            f"Failed to read image: {exc}",
            code="image_read_error",
            details={"path": path, "resolved_path": str(target)},
        )

    return json_response(
        True,
        f"Read image: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "mime_type": mime_type,
            "byte_size": byte_size,
            "width": int(width),
            "height": int(height),
            "content_base64": content_base64,
            "truncated": False,
            "max_byte_size": _IMAGE_MAX_BYTES,
        },
    )


async def read_pdf(path: str, page_start: int = 1, page_end: int | None = None) -> str:
    """Extract text from a PDF with page-level pagination."""
    target, error = _resolve_read_target(path)
    if error is not None:
        return error
    assert target is not None

    if target.suffix.lower() != ".pdf":
        return json_response(
            False,
            "Unsupported document format. read_pdf only supports PDF files.",
            code="unsupported_file_type",
            details={"path": path, "resolved_path": str(target), "supported_extensions": [".pdf"]},
        )

    byte_size = target.stat().st_size
    if byte_size > _PDF_MAX_BYTES:
        return json_response(
            False,
            "PDF is too large to read safely.",
            code="file_too_large",
            details={
                "path": path,
                "resolved_path": str(target),
                "byte_size": byte_size,
                "max_byte_size": _PDF_MAX_BYTES,
                "truncated": True,
            },
        )

    if page_start < 1:
        return json_response(
            False,
            "page_start must be 1 or greater.",
            code="invalid_page_range",
            details={"path": path, "page_start": page_start, "page_end": page_end},
        )
    if page_end is not None and page_end < page_start:
        return json_response(
            False,
            "page_end must be greater than or equal to page_start.",
            code="invalid_page_range",
            details={"path": path, "page_start": page_start, "page_end": page_end},
        )

    try:
        pdf_module = _import_pdf_module()
    except ImportError:
        return _missing_dependency_response("PyPDF2")

    try:
        with target.open("rb") as handle:
            reader = pdf_module.PdfReader(handle)
            if bool(getattr(reader, "is_encrypted", False)):
                return json_response(
                    False,
                    "Encrypted PDFs are not supported.",
                    code="pdf_encrypted",
                    details={"path": path, "resolved_path": str(target)},
                )

            total_pages = len(reader.pages)
            start_index = page_start - 1
            if start_index >= total_pages:
                return json_response(
                    False,
                    "page_start is beyond the end of the PDF.",
                    code="invalid_page_range",
                    details={
                        "path": path,
                        "page_start": page_start,
                        "page_end": page_end,
                        "total_pages": total_pages,
                    },
                )

            requested_end = page_end if page_end is not None else total_pages
            capped_end = min(requested_end, page_start + _PDF_PAGE_LIMIT - 1, total_pages)
            texts: list[str] = []
            for page_number in range(page_start, capped_end + 1):
                page_text = reader.pages[page_number - 1].extract_text()
                texts.append(page_text or "")
    except Exception as exc:
        return json_response(
            False,
            f"Failed to read PDF: {exc}",
            code="pdf_read_error",
            details={"path": path, "resolved_path": str(target)},
        )

    text = "\n\n".join(texts)
    truncated = capped_end < requested_end or capped_end < total_pages
    return json_response(
        True,
        f"Read PDF: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "text": text,
            "byte_size": byte_size,
            "total_pages": total_pages,
            "page_start": page_start,
            "page_end": capped_end,
            "requested_page_end": requested_end,
            "returned_page_count": len(texts),
            "page_limit": _PDF_PAGE_LIMIT,
            "char_count": len(text),
            "truncated": truncated,
            "has_more": capped_end < total_pages,
            "max_byte_size": _PDF_MAX_BYTES,
        },
    )
