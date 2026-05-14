"""Tests for optional multi-format readers."""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from claude_bridge import multi_format
from claude_bridge import server as mcp_server

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "multi_format"


def parse_payload(result: str) -> dict[str, Any]:
    return json.loads(result)


def write_b64_fixture(project: Path, fixture_name: str, output_name: str) -> Path:
    raw = base64.b64decode((FIXTURE_DIR / fixture_name).read_text(encoding="ascii"))
    target = project / output_name
    target.write_bytes(raw)
    return target


@pytest.fixture
def temp_project() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


class FakeImage:
    format = "PNG"
    size = (1, 1)

    def __enter__(self) -> "FakeImage":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeImageModule:
    def open(self, target: Path) -> FakeImage:
        assert target.name == "sample.png"
        return FakeImage()


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakePdfReader:
    is_encrypted = False

    def __init__(self, handle: object) -> None:
        self.pages = [FakePage(f"page {index}") for index in range(1, 13)]


class FakePdfModule:
    PdfReader = FakePdfReader


class EncryptedPdfReader:
    is_encrypted = True
    pages: list[FakePage] = []

    def __init__(self, handle: object) -> None:
        return None


class EncryptedPdfModule:
    PdfReader = EncryptedPdfReader


class TestReadImage:
    async def test_read_image_returns_metadata_and_base64(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.png.b64", "sample.png")
        monkeypatch.setattr(multi_format, "_import_image_module", lambda: FakeImageModule())

        payload = parse_payload(await mcp_server.read_image("sample.png"))

        assert payload["ok"] is True
        assert payload["details"]["mime_type"] == "image/png"
        assert payload["details"]["byte_size"] > 0
        assert payload["details"]["width"] == 1
        assert payload["details"]["height"] == 1
        assert payload["details"]["content_base64"]
        assert payload["details"]["truncated"] is False

    async def test_read_image_missing_dependency_is_structured(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.png.b64", "sample.png")

        def missing() -> object:
            raise ImportError("no pillow")

        monkeypatch.setattr(multi_format, "_import_image_module", missing)

        payload = parse_payload(await mcp_server.read_image("sample.png"))

        assert payload["ok"] is False
        assert payload["code"] == "dependency_missing"
        assert payload["details"]["install"] == "pip install claude-bridge[multi-format]"

    async def test_read_image_rejects_unsupported_extension(self, temp_project: Path) -> None:
        (temp_project / "sample.tga").write_bytes(b"TGA")
        payload = parse_payload(await mcp_server.read_image("sample.tga"))
        assert payload["ok"] is False
        assert payload["code"] == "unsupported_file_type"

    async def test_read_image_blocks_outside_workspace(self, temp_project: Path) -> None:
        outside = temp_project.parent / "outside.png"
        outside.write_bytes(b"not really an image")
        try:
            payload = parse_payload(await mcp_server.read_image("../outside.png"))
        finally:
            outside.unlink(missing_ok=True)

        assert payload["ok"] is False
        assert payload["code"] == "path_outside_project"

    async def test_read_image_reports_large_file_limit(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.png.b64", "sample.png")
        monkeypatch.setattr(multi_format, "_IMAGE_MAX_BYTES", 1)

        payload = parse_payload(await mcp_server.read_image("sample.png"))

        assert payload["ok"] is False
        assert payload["code"] == "file_too_large"
        assert payload["details"]["truncated"] is True
        assert payload["details"]["max_byte_size"] == 1

    async def test_read_image_real_fixture_when_pillow_is_available(
        self, temp_project: Path
    ) -> None:
        pytest.importorskip("PIL.Image")
        write_b64_fixture(temp_project, "sample.png.b64", "sample.png")

        payload = parse_payload(await mcp_server.read_image("sample.png"))

        assert payload["ok"] is True
        assert payload["details"]["mime_type"] == "image/png"
        assert payload["details"]["width"] == 1
        assert payload["details"]["height"] == 1


class TestReadPdf:
    async def test_read_pdf_returns_paginated_text(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")
        monkeypatch.setattr(multi_format, "_import_pdf_module", lambda: FakePdfModule())

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf", page_start=2))

        assert payload["ok"] is True
        assert payload["details"]["text"].startswith("page 2")
        assert "page 11" in payload["details"]["text"]
        assert "page 12" not in payload["details"]["text"]
        assert payload["details"]["total_pages"] == 12
        assert payload["details"]["page_start"] == 2
        assert payload["details"]["page_end"] == 11
        assert payload["details"]["returned_page_count"] == 10
        assert payload["details"]["page_limit"] == 10
        assert payload["details"]["truncated"] is True
        assert payload["details"]["has_more"] is True

    async def test_read_pdf_respects_page_end(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")
        monkeypatch.setattr(multi_format, "_import_pdf_module", lambda: FakePdfModule())

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf", page_start=3, page_end=4))

        assert payload["ok"] is True
        assert payload["details"]["text"] == "page 3\n\npage 4"
        assert payload["details"]["truncated"] is True
        assert payload["details"]["has_more"] is True

    async def test_read_pdf_missing_dependency_is_structured(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")

        def missing() -> object:
            raise ImportError("no pypdf2")

        monkeypatch.setattr(multi_format, "_import_pdf_module", missing)

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf"))

        assert payload["ok"] is False
        assert payload["code"] == "dependency_missing"
        assert payload["details"]["dependency"] == "PyPDF2"

    async def test_read_pdf_rejects_unsupported_extension(self, temp_project: Path) -> None:
        (temp_project / "notes.txt").write_text("hello", encoding="utf-8")

        payload = parse_payload(await mcp_server.read_pdf("notes.txt"))

        assert payload["ok"] is False
        assert payload["code"] == "unsupported_file_type"

    async def test_read_pdf_blocks_outside_workspace(self, temp_project: Path) -> None:
        outside = temp_project.parent / "outside.pdf"
        outside.write_bytes(b"%PDF-1.4")
        try:
            payload = parse_payload(await mcp_server.read_pdf("../outside.pdf"))
        finally:
            outside.unlink(missing_ok=True)

        assert payload["ok"] is False
        assert payload["code"] == "path_outside_project"

    async def test_read_pdf_reports_large_file_limit(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")
        monkeypatch.setattr(multi_format, "_PDF_MAX_BYTES", 1)

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf"))

        assert payload["ok"] is False
        assert payload["code"] == "file_too_large"
        assert payload["details"]["truncated"] is True
        assert payload["details"]["max_byte_size"] == 1

    async def test_read_pdf_rejects_invalid_page_range(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")
        monkeypatch.setattr(multi_format, "_import_pdf_module", lambda: FakePdfModule())

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf", page_start=0))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_page_range"

    async def test_read_pdf_reports_encrypted_pdf(
        self, temp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")
        monkeypatch.setattr(multi_format, "_import_pdf_module", lambda: EncryptedPdfModule())

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf"))

        assert payload["ok"] is False
        assert payload["code"] == "pdf_encrypted"

    async def test_read_pdf_real_fixture_when_pypdf2_is_available(self, temp_project: Path) -> None:
        pytest.importorskip("PyPDF2")
        write_b64_fixture(temp_project, "sample.pdf.b64", "sample.pdf")

        payload = parse_payload(await mcp_server.read_pdf("sample.pdf"))

        assert payload["ok"] is True
        assert "Hello PDF fixture" in payload["details"]["text"]
        assert payload["details"]["total_pages"] == 1
