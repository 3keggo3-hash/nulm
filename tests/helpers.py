"""Shared test helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge.audit import reset_audit_session


def parse_payload(result: str) -> dict:
    return json.loads(result)


class FakeTSNode:
    def __init__(
        self,
        node_type: str,
        text: str = "",
        *,
        children: list["FakeTSNode"] | None = None,
        fields: dict[str, "FakeTSNode"] | None = None,
    ) -> None:
        self.type = node_type
        self._text = text
        self.children = children or []
        self._fields = fields or {}
        self.start_byte = 0
        self.end_byte = len(text.encode("utf-8"))

    def child_by_field_name(self, name: str):
        return self._fields.get(name)


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


@pytest.fixture
def temp_audit_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        audit_dir = project / ".audit"
        os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()
        yield project, audit_dir
        try:
            del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]
        except KeyError:
            pass
        reset_audit_session()
