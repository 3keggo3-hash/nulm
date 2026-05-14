"""Registration helpers for file-oriented MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext

_LOW_COST_BUDGET_TOKENS = 2000
_LOW_COST_MULTI_FILE_READS = 8
_LOW_COST_SEARCH_RESULTS = 50
_BALANCED_MULTI_FILE_READS = 12
_BALANCED_SEARCH_RESULTS = 100
_MAX_SEARCH_RESULTS = 200


def _multi_file_path_limit(budget_tokens: int) -> int:
    if budget_tokens <= _LOW_COST_BUDGET_TOKENS:
        return _LOW_COST_MULTI_FILE_READS
    if budget_tokens <= 4000:
        return _BALANCED_MULTI_FILE_READS
    return 20


def _search_result_limit(requested: int, budget_tokens: int) -> int:
    if budget_tokens <= _LOW_COST_BUDGET_TOKENS:
        return min(requested, _LOW_COST_SEARCH_RESULTS)
    if budget_tokens <= 4000:
        return min(requested, _BALANCED_SEARCH_RESULTS)
    return min(requested, _MAX_SEARCH_RESULTS)


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
    ai_provider_getter: Callable[[], Any] | None = None,
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )
    _get_ai = ai_provider_getter

    if ctx.should_register("read_file"):

        async def read_file(
            path: str,
            offset: int = 0,
            limit: int = 50,
            budget_tokens: int | None = None,
        ) -> str:
            bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
            started_at = ctx.now_ms()
            result = await read_file_impl(path, offset=offset, limit=limit, budget_tokens=bt)
            return audit_tool_call(
                "read_file",
                {"path": path, "offset": offset, "limit": limit, "budget_tokens": bt},
                result,
                started_at=started_at,
            )

        ctx.register(
            "read_file",
            "Read a file inside the configured workspace. Prefer targeted reads over broad exploration.",
            read_file,
            read_only=True,
        )

    if ctx.should_register("read_multiple_files"):

        async def read_multiple_files(
            paths: list[str],
            offset: int = 0,
            limit: int = 50,
            budget_tokens: int | None = None,
        ) -> str:
            bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
            max_paths = _multi_file_path_limit(bt)
            started_at = ctx.now_ms()
            result = await read_multiple_files_impl(
                paths, offset=offset, limit=limit, budget_tokens=bt, max_paths=max_paths
            )
            return audit_tool_call(
                "read_multiple_files",
                {
                    "paths": paths,
                    "max_paths": max_paths,
                    "offset": offset,
                    "limit": limit,
                    "budget_tokens": bt,
                },
                result,
                started_at=started_at,
            )

        ctx.register(
            "read_multiple_files",
            "Read multiple files at once for comparison or cross-reference.",
            read_multiple_files,
            read_only=True,
        )

    if ctx.should_register("list_directory"):

        async def list_directory(path: str = ".") -> str:
            started_at = ctx.now_ms()
            result = await list_directory_impl(path)
            return audit_tool_call("list_directory", {"path": path}, result, started_at=started_at)

        ctx.register(
            "list_directory",
            "List a directory inside the configured workspace. Use this first to understand structure.",
            list_directory,
            read_only=True,
        )

    if ctx.should_register("write_file"):

        async def write_file(
            path: str,
            content: str,
            overwrite: bool = False,
            create_parents: bool = False,
            max_lines: int = 500,
            auto_commit: bool = True,
        ) -> str:
            started_at = ctx.now_ms()
            result = await write_file_impl(
                path,
                content,
                overwrite=overwrite,
                create_parents=create_parents,
                max_lines=max_lines,
                auto_commit=auto_commit,
                git_commit_fn=git_commit_fn,
                ai_provider=_get_ai() if _get_ai else None,
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

        ctx.register(
            "write_file",
            "Write a new file or overwrite an existing one. Prefer patch_file for edits.",
            write_file,
            destructive=True,
        )

    if ctx.should_register("move_file"):

        async def move_file(
            source: str,
            destination: str,
            overwrite: bool = False,
            create_parents: bool = False,
        ) -> str:
            started_at = ctx.now_ms()
            result = await move_file_impl(
                source,
                destination,
                overwrite=overwrite,
                create_parents=create_parents,
                git_commit_fn=git_commit_fn,
                ai_provider=_get_ai() if _get_ai else None,
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

        ctx.register(
            "move_file",
            "Move or rename a file or directory with approval.",
            move_file,
            destructive=True,
        )

    if ctx.should_register("copy_path"):

        async def copy_path(
            source: str,
            destination: str,
            overwrite: bool = False,
            create_parents: bool = False,
        ) -> str:
            started_at = ctx.now_ms()
            result = await copy_path_impl(
                source,
                destination,
                overwrite=overwrite,
                create_parents=create_parents,
                git_commit_fn=git_commit_fn,
                ai_provider=_get_ai() if _get_ai else None,
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

        ctx.register(
            "copy_path", "Copy a file or directory with approval.", copy_path, destructive=True
        )

    if ctx.should_register("search_in_files"):

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
            effective_limit = _search_result_limit(limit, bt)
            started_at = ctx.now_ms()
            result = await search_in_files_impl(
                query,
                path=path,
                regex=regex,
                case_sensitive=case_sensitive,
                include_glob=include_glob,
                offset=offset,
                limit=effective_limit,
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
                    "effective_limit": effective_limit,
                    "budget_tokens": bt,
                },
                result,
                started_at=started_at,
            )

        ctx.register(
            "search_in_files",
            "Search text across project files. Prefer this over broad shell grep.",
            search_in_files,
            read_only=True,
        )

    if ctx.should_register("patch_file"):

        async def patch_file(file: str, search: str, replace: str, auto_commit: bool = True) -> str:
            started_at = ctx.now_ms()
            result = await patch_file_impl(
                file,
                search,
                replace,
                auto_commit=auto_commit,
                git_commit_fn=git_commit_fn,
                ai_provider=_get_ai() if _get_ai else None,
            )
            return audit_tool_call(
                "patch_file",
                {"file": file, "search": search, "replace": replace, "auto_commit": auto_commit},
                result,
                started_at=started_at,
            )

        ctx.register(
            "patch_file",
            "Apply a targeted SEARCH/REPLACE patch. Keep SEARCH small but unique.",
            patch_file,
            destructive=True,
        )

    if ctx.should_register("preview_patch"):

        async def preview_patch(file: str, search: str, replace: str) -> str:
            started_at = ctx.now_ms()
            result = await preview_patch_impl(file, search, replace)
            return audit_tool_call(
                "preview_patch",
                {"file": file, "search": search, "replace": replace},
                result,
                started_at=started_at,
            )

        ctx.register(
            "preview_patch",
            "Preview a SEARCH/REPLACE patch without changing the file.",
            preview_patch,
            read_only=True,
        )

    if ctx.should_register("undo_last_patch"):

        async def undo_last_patch(confirm: bool = False) -> str:
            started_at = ctx.now_ms()
            result = await undo_last_patch_impl(
                confirm=confirm,
                request_approval_fn=request_approval_fn,
                git_commit_fn=git_commit_fn,
            )
            return audit_tool_call(
                "undo_last_patch", {"confirm": confirm}, result, started_at=started_at
            )

        ctx.register(
            "undo_last_patch",
            "Undo the last Claude Bridge managed file change.",
            undo_last_patch,
            destructive=True,
        )

    return ctx.results
