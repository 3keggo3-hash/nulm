"""Registration helpers for file-oriented MCP tools."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


def register_file_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    resolve_path: Callable[[str], Path],
    json_response: Callable[..., str],
    effective_budget_tokens: Callable[[], int],
    read_file_impl: Any,
    read_multiple_files_impl: Any,
    list_directory_impl: Any,
    write_file_impl: Any,
    move_file_impl: Any,
    copy_path_impl: Any,
    search_in_files_impl: Any,
    patch_file_impl: Any,
    preview_patch_impl: Any,
    undo_last_patch_impl: Any,
    git_commit_fn: Callable[..., dict[str, Any]],
    request_approval_fn: Any,
) -> dict[str, Any]:
    @mcp.tool(
        **tool_options(
            "Read a file inside the configured workspace. Use this after you know which file matters. "
            "Prefer targeted reads over broad exploration, and expect large files to be truncated for context safety.",
            read_only=True,
        )
    )
    async def read_file(
        path: str,
        offset: int = 0,
        limit: int = 200,
        budget_tokens: int | None = None,
    ) -> str:
        bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
        started_at = time.perf_counter()
        result = await read_file_impl(path, offset=offset, limit=limit, budget_tokens=bt)
        return audit_tool_call(
            "read_file",
            {"path": path, "offset": offset, "limit": limit, "budget_tokens": bt},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Read multiple files at once. Use this when you need to compare or cross-reference a small set of files more efficiently than repeated read_file calls.",
            read_only=True,
        )
    )
    async def read_multiple_files(
        paths: list[str],
        offset: int = 0,
        limit: int = 200,
        budget_tokens: int | None = None,
    ) -> str:
        bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
        started_at = time.perf_counter()
        result = await read_multiple_files_impl(paths, offset=offset, limit=limit, budget_tokens=bt)
        return audit_tool_call(
            "read_multiple_files",
            {"paths": paths, "offset": offset, "limit": limit, "budget_tokens": bt},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "List a directory inside the configured workspace. Use this first to understand structure before reading or editing files. "
            "Prefer narrow paths over listing the whole repository.",
            read_only=True,
        )
    )
    async def list_directory(path: str = ".") -> str:
        started_at = time.perf_counter()
        result = await list_directory_impl(path)
        return audit_tool_call("list_directory", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Write a new file or overwrite an existing one with approval. Prefer this for creating new files. "
            "For existing files, prefer patch_file so edits stay small, auditable, and easier to validate.",
            destructive=True,
        )
    )
    async def write_file(
        path: str,
        content: str,
        overwrite: bool = False,
        create_parents: bool = False,
        max_lines: int = 500,
        auto_commit: bool = True,
    ) -> str:
        started_at = time.perf_counter()
        result = await write_file_impl(
            path,
            content,
            overwrite=overwrite,
            create_parents=create_parents,
            max_lines=max_lines,
            auto_commit=auto_commit,
            git_commit_fn=git_commit_fn,
        )
        return audit_tool_call(
            "write_file",
            {
                "path": path,
                "content": content,
                "overwrite": overwrite,
                "create_parents": create_parents,
                "max_lines": max_lines,
                "auto_commit": auto_commit,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Move or rename a file or directory inside the configured workspace with approval.",
            destructive=True,
        )
    )
    async def move_file(
        source: str,
        destination: str,
        overwrite: bool = False,
        create_parents: bool = False,
    ) -> str:
        started_at = time.perf_counter()
        result = await move_file_impl(
            source,
            destination,
            overwrite=overwrite,
            create_parents=create_parents,
            git_commit_fn=git_commit_fn,
        )
        return audit_tool_call(
            "move_file",
            {
                "source": source,
                "destination": destination,
                "overwrite": overwrite,
                "create_parents": create_parents,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Copy a file or directory inside the configured workspace with approval.",
            destructive=True,
        )
    )
    async def copy_path(
        source: str,
        destination: str,
        overwrite: bool = False,
        create_parents: bool = False,
    ) -> str:
        started_at = time.perf_counter()
        result = await copy_path_impl(
            source,
            destination,
            overwrite=overwrite,
            create_parents=create_parents,
            git_commit_fn=git_commit_fn,
        )
        return audit_tool_call(
            "copy_path",
            {
                "source": source,
                "destination": destination,
                "overwrite": overwrite,
                "create_parents": create_parents,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Search text across project files without dropping to shell. Use this to narrow the candidate files before reading them. "
            "Prefer this over broad shell grep commands when exploring code. Use offset and limit to page through large result sets.",
            read_only=True,
        )
    )
    async def search_in_files(
        query: str,
        path: str = ".",
        regex: bool = False,
        case_sensitive: bool = False,
        include_glob: str | None = None,
        offset: int = 0,
        limit: int = 50,
        budget_tokens: int | None = None,
    ) -> str:
        bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
        started_at = time.perf_counter()
        result = await search_in_files_impl(
            query,
            path=path,
            regex=regex,
            case_sensitive=case_sensitive,
            include_glob=include_glob,
            offset=offset,
            limit=limit,
            budget_tokens=bt,
        )
        return audit_tool_call(
            "search_in_files",
            {
                "query": query,
                "path": path,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "include_glob": include_glob,
                "offset": offset,
                "limit": limit,
                "budget_tokens": bt,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Apply a targeted SEARCH/REPLACE patch to an existing file. Prefer this over write_file for edits. "
            "Keep SEARCH text small but unique so the replacement is deterministic and easy to review.",
            destructive=True,
        )
    )
    async def patch_file(file: str, search: str, replace: str, auto_commit: bool = True) -> str:
        started_at = time.perf_counter()
        result = await patch_file_impl(file, search, replace, auto_commit=auto_commit, git_commit_fn=git_commit_fn)
        return audit_tool_call(
            "patch_file",
            {"file": file, "search": search, "replace": replace, "auto_commit": auto_commit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Preview a SEARCH/REPLACE patch without changing the file. Use this before applying non-trivial edits or when you need to explain risk.",
            read_only=True,
        )
    )
    async def preview_patch(file: str, search: str, replace: str) -> str:
        started_at = time.perf_counter()
        result = await preview_patch_impl(file, search, replace)
        return audit_tool_call(
            "preview_patch",
            {"file": file, "search": search, "replace": replace},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Undo the last Claude Bridge managed file change using the stored snapshot. Use this only when the last Bridge action should be reverted.",
            destructive=True,
        )
    )
    async def undo_last_patch(confirm: bool = False) -> str:
        started_at = time.perf_counter()
        result = await undo_last_patch_impl(
            confirm=confirm,
            request_approval_fn=request_approval_fn,
            git_commit_fn=git_commit_fn,
        )
        return audit_tool_call(
            "undo_last_patch", {"confirm": confirm}, result, started_at=started_at
        )

    return {
        "read_file": read_file,
        "read_multiple_files": read_multiple_files,
        "list_directory": list_directory,
        "write_file": write_file,
        "move_file": move_file,
        "copy_path": copy_path,
        "search_in_files": search_in_files,
        "patch_file": patch_file,
        "preview_patch": preview_patch,
        "undo_last_patch": undo_last_patch,
    }
