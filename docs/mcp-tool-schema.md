# Nulm MCP Tool Schema Examples

> **Version:** 0.1.1
> **Last Updated:** 2026-05-12

This document provides representative JSON Schema definitions for common MCP tools exposed by
Nulm. The active runtime schema is generated from the registered tools and can vary by
tool profile (`essential`, `standard`, `full`) and optional dependency availability.

## Tool Schema Format

All tools follow the MCP protocol format:

```json
{
  "name": "tool_name",
  "description": "What the tool does",
  "inputSchema": {
    "type": "object",
    "properties": {...},
    "required": [...]
  },
  "annotations": {
    "readOnlyHint": true|false,
    "destructiveHint": true|false,
    "openWorldHint": true|false
  }
}
```

## File Tool Schemas

### read_file
```json
{
  "name": "read_file",
  "description": "Read the contents of a file from the local filesystem. Use offset and limit to control reading specific line ranges.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to read"
      },
      "offset": {
        "type": "integer",
        "description": "Line offset to start reading from (0-indexed, default: 0)"
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of lines to read (default: all)"
      }
    },
    "required": ["path"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### write_file
```json
{
  "name": "write_file",
  "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to write"
      },
      "content": {
        "type": "string",
        "description": "Content to write to the file"
      },
      "create_dirs": {
        "type": "boolean",
        "description": "Create parent directories if they don't exist (default: false)"
      }
    },
    "required": ["path", "content"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "openWorldHint": false
  }
}
```

### list_directory
```json
{
  "name": "list_directory",
  "description": "List directory contents with file metadata.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the directory to list"
      },
      "include_hidden": {
        "type": "boolean",
        "description": "Include hidden files (starting with .) (default: false)"
      }
    },
    "required": ["path"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### search_in_files
```json
{
  "name": "search_in_files",
  "description": "Search for text patterns in files using regex.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pattern": {
        "type": "string",
        "description": "Regex pattern to search for"
      },
      "paths": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Paths to search in (default: all in project)"
      },
      "include_glob": {
        "type": "string",
        "description": "Glob pattern to filter files (e.g., *.py)"
      }
    },
    "required": ["pattern"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### patch_file
```json
{
  "name": "patch_file",
  "description": "Apply a unified diff patch to a file.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to patch"
      },
      "patch": {
        "type": "string",
        "description": "Unified diff patch content"
      }
    },
    "required": ["path", "patch"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "openWorldHint": false
  }
}
```

## Shell Tool Schemas

### run_shell
```json
{
  "name": "run_shell",
  "description": "Execute a shell command with optional timeout and working directory.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "Shell command to execute"
      },
      "timeout": {
        "type": "integer",
        "description": "Timeout in seconds (default: 30)"
      },
      "cwd": {
        "type": "string",
        "description": "Working directory for the command"
      }
    },
    "required": ["command"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "openWorldHint": true
  }
}
```

### analyze_shell_command
```json
{
  "name": "analyze_shell_command",
  "description": "Analyze a shell command for safety without executing it.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "Shell command to analyze"
      }
    },
    "required": ["command"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

## Workflow Tool Schemas

### run_workflow
```json
{
  "name": "run_workflow",
  "description": "Execute a multi-step workflow with quality gates and checkpointing.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "Task description to execute"
      },
      "mode": {
        "type": "string",
        "enum": ["review", "optimize", "quality", "test", "explain", "commit"],
        "description": "Workflow execution mode"
      },
      "max_steps": {
        "type": "integer",
        "description": "Maximum number of workflow steps (default: 10)"
      }
    },
    "required": ["task"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### run_agent_loop_session
```json
{
  "name": "run_agent_loop_session",
  "description": "Run a bounded agent loop session with quality checks at boundaries.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "Task description"
      },
      "max_steps": {
        "type": "integer",
        "description": "Maximum loop iterations (default: 5)"
      },
      "project_dir": {
        "type": "string",
        "description": "Project directory path"
      }
    },
    "required": ["task"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

## Agent Quality Tool Schemas

### advise_next_step
```json
{
  "name": "advise_next_step",
  "description": "Get AI advice for the next step to accomplish a user goal.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "goal": {
        "type": "string",
        "description": "Current user goal or intent"
      },
      "context": {
        "type": "object",
        "description": "Additional context for advice"
      }
    },
    "required": ["goal"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### improve_request
```json
{
  "name": "improve_request",
  "description": "Convert a rough user request into a structured implementation plan.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "request": {
        "type": "string",
        "description": "Vague or rough user request"
      },
      "context": {
        "type": "object",
        "description": "Additional context"
      }
    },
    "required": ["request"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### plan_quality_review
```json
{
  "name": "plan_quality_review",
  "description": "Review an implementation plan for quality and risks.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "plan": {
        "type": "object",
        "description": "Implementation plan to review"
      }
    },
    "required": ["plan"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### review_result_quality
```json
{
  "name": "review_result_quality",
  "description": "Review completed work for correctness, maintainability, and test coverage.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "files_changed": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Paths to files that were changed"
      },
      "context": {
        "type": "object",
        "description": "Review context"
      }
    },
    "required": ["files_changed"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

## Indexing Tool Schemas

### index_codebase
```json
{
  "name": "index_codebase",
  "description": "Build an index of the codebase for semantic search.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path to index (default: project root)"
      }
    },
    "required": []
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### find_relevant_files
```json
{
  "name": "find_relevant_files",
  "description": "Find files relevant to a query using semantic search.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query"
      },
      "max_results": {
        "type": "integer",
        "description": "Maximum number of results (default: 10)"
      }
    },
    "required": ["query"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

## Meta Tool Schemas

### bridge_status
```json
{
  "name": "bridge_status",
  "description": "Get current Nulm status including health and uptime.",
  "inputSchema": {
    "type": "object",
    "properties": {}
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### get_config
```json
{
  "name": "get_config",
  "description": "Get current runtime configuration.",
  "inputSchema": {
    "type": "object",
    "properties": {}
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### set_config_value
```json
{
  "name": "set_config_value",
  "description": "Update a runtime configuration value.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "key": {
        "type": "string",
        "description": "Configuration key to update"
      },
      "value": {
        "type": "any",
        "description": "New value for the key"
      }
    },
    "required": ["key", "value"]
  },
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```

### get_recent_tool_calls
```json
{
  "name": "get_recent_tool_calls",
  "description": "Get recent tool call history for the current session.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "limit": {
        "type": "integer",
        "description": "Maximum number of calls to return (default: 50)"
      }
    }
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": false
  }
}
```
