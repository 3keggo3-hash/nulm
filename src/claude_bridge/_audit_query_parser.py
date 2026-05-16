"""SQL-like query parser for audit trail records."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any

from claude_bridge.guard_policy import validate_regex_pattern

# Supported query fields
_VALID_QUERY_FIELDS = frozenset(
    {
        "tool_name",
        "ok",
        "decision_action",
        "decision_source",
        "decision_risk_level",
        "timestamp",
        "duration_ms",
        "session_id",
    }
)

# Operators supported in WHERE clause
_VALID_OPERATORS = frozenset({"=", "!=", ">", "<", ">=", "<=", "LIKE", "LIKE%", "%LIKE", "%LIKE%"})

# Reserved words
_RESERVED_WORDS = frozenset(
    {"SELECT", "WHERE", "ORDER", "BY", "LIMIT", "ASC", "DESC", "AND", "OR", "FROM"}
)


class QueryError(Exception):
    """Raised when query parsing fails."""

    pass


class SortOrder(str, Enum):
    """Sort direction for ORDER BY."""

    ASC = "ASC"
    DESC = "DESC"


@dataclass
class WhereCondition:
    """A single condition in a WHERE clause."""

    field: str
    operator: str
    value: str | int | float | bool
    case_sensitive: bool = False


@dataclass
class WhereClause:
    """A parsed WHERE clause supporting AND/OR."""

    conditions: list[WhereCondition]
    logic: str = "AND"  # "AND" or "OR"


@dataclass
class OrderByClause:
    """An ORDER BY specification."""

    field: str
    direction: SortOrder = SortOrder.DESC


@dataclass
class AuditQueryAST:
    """Abstract syntax tree for an audit trail query."""

    select_fields: list[str] = dc_field(default_factory=list)  # empty means *
    where: WhereClause | None = None
    order_by: OrderByClause | None = None
    limit: int | None = None

    @classmethod
    def default(cls) -> "AuditQueryAST":
        """Return an AST that selects all records with no filters."""
        return cls(select_fields=[], where=None, order_by=None, limit=None)


class AuditQueryParser:
    """Parser for SQL-like audit trail queries.

    Supported syntax:
        SELECT <fields>     -- comma-separated, default: *
        WHERE <conditions> -- field op value, supports AND/OR
        ORDER BY <field> [ASC|DESC]
        LIMIT <n>

    Supported fields: tool_name, ok, decision_action, decision_source,
                      decision_risk_level, timestamp, duration_ms, session_id

    Supported operators: =, !=, >, <, >=, <=, LIKE, LIKE%, %LIKE, %LIKE%
    """

    _TOKEN_RE = re.compile(
        r"""
        (?P<keyword>SELECT|WHERE|ORDER\s+BY|LIMIT|ASC|DESC|AND|OR|LIKE)
        |(?P<identifier>[a-zA-Z_][a-zA-Z0-9_]*)
        |(?P<string>'(?:[^'\\]|\\.)*')
        |(?P<number>-?\d+(?:\.\d+)?)
        |(?P<operator><=|>=|!=|<|>|=)
        |(?P<punct>[,])
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    def __init__(self, max_query_length: int = 2000):
        self.max_query_length = max_query_length
        self._regex_cache: dict[str, re.Pattern | None] = {}

    def parse(self, query: str) -> AuditQueryAST:
        """Parse a SQL-like query string into an AST.

        Args:
            query: SQL-like query string (e.g., "SELECT tool_name WHERE ok = true LIMIT 10")

        Returns:
            AuditQueryAST representing the parsed query

        Raises:
            QueryError: If the query is malformed or contains invalid syntax
        """
        if not query or not isinstance(query, str):
            raise QueryError("Query cannot be empty")

        query = query.strip()
        if len(query) > self.max_query_length:
            raise QueryError(f"Query exceeds maximum length of {self.max_query_length}")

        ast = AuditQueryAST.default()
        tokens = list(self._tokenize(query))
        if not tokens:
            raise QueryError("Failed to tokenize query")

        pos = 0
        tok = tokens[pos]

        # Parse SELECT clause
        if self._keyword_matches(tok, "SELECT"):
            pos, ast.select_fields = self._parse_select(tokens, pos)

        # Parse WHERE clause
        if pos < len(tokens) and self._keyword_matches(tokens[pos], "WHERE"):
            pos, ast.where = self._parse_where(tokens, pos)

        # Parse ORDER BY clause
        if pos < len(tokens) and self._keyword_matches(tokens[pos], "ORDER"):
            pos, ast.order_by = self._parse_order_by(tokens, pos)

        # Parse LIMIT clause
        if pos < len(tokens) and self._keyword_matches(tokens[pos], "LIMIT"):
            pos, ast.limit = self._parse_limit(tokens, pos)

        return ast

    def _keyword_matches(self, tok: tuple, keyword: str) -> bool:
        return tok[0] == "KEYWORD" and tok[1].upper() == keyword

    def _tokenize(self, query: str) -> list[tuple]:
        """Convert query string into a list of (type, value) tokens."""
        tokens = []
        for match in self._TOKEN_RE.finditer(query):
            kind = match.lastgroup
            value = match.group()
            if kind == "keyword":
                upper = value.upper()
                if upper == "ORDER":
                    # Check if next is BY
                    tokens.append(("KEYWORD", "ORDER BY"))
                elif upper in ("ASC", "DESC"):
                    tokens.append(("DIRECTION", value.upper()))
                elif upper in ("AND", "OR"):
                    tokens.append(("LOGIC", upper))
                else:
                    tokens.append(("KEYWORD", upper))
            elif kind == "identifier":
                tokens.append(("IDENTIFIER", value))
            elif kind == "string":
                tokens.append(("STRING", value[1:-1]))  # Strip quotes
            elif kind == "number":
                num = float(value)
                tokens.append(("NUMBER", int(num) if num.is_integer() else num))
            elif kind == "operator":
                tokens.append(("OPERATOR", value))
            elif kind == "punct":
                tokens.append(("PUNCT", value))
        return tokens

    def _parse_select(self, tokens: list[tuple], pos: int) -> tuple[int, list[str]]:
        """Parse SELECT clause. Returns (new_pos, fields)."""
        pos += 1  # Skip SELECT keyword
        fields = []
        while pos < len(tokens):
            tok_type, tok_val = tokens[pos]
            if tok_type == "IDENTIFIER":
                field = tok_val.lower()
                if field not in _VALID_QUERY_FIELDS:
                    raise QueryError(f"Unknown field in SELECT: {tok_val}")
                fields.append(field)
                pos += 1
            elif tok_type == "PUNCT" and tok_val == ",":
                pos += 1
                continue
            else:
                break
        return pos, fields if fields else []

    def _parse_where(self, tokens: list[tuple], pos: int) -> tuple[int, WhereClause | None]:
        """Parse WHERE clause. Returns (new_pos, WhereClause)."""
        pos += 1  # Skip WHERE keyword
        conditions = []
        logic = "AND"

        while pos < len(tokens):
            tok_type, tok_val = tokens[pos]
            if tok_type == "LOGIC":
                logic = tok_val
                pos += 1
                continue
            if tok_type != "IDENTIFIER":
                break

            field = tok_val.lower()
            if field not in _VALID_QUERY_FIELDS:
                raise QueryError(f"Unknown field in WHERE: {tok_val}")

            # Expect operator
            if pos + 1 >= len(tokens) or tokens[pos + 1][0] != "OPERATOR":
                raise QueryError(f"Expected operator after field '{field}'")
            pos += 1
            op = tokens[pos][1]
            if op not in _VALID_OPERATORS:
                raise QueryError(f"Unknown operator: {op}")
            pos += 1

            # Expect value
            if pos >= len(tokens) or tokens[pos][0] not in ("STRING", "NUMBER", "IDENTIFIER"):
                raise QueryError(f"Expected value after operator '{op}'")
            tok_type, tok_val = tokens[pos]
            pos += 1

            # Coerce value
            value: str | int | float | bool = tok_val
            if tok_type == "NUMBER":
                value = (
                    int(tok_val) if isinstance(tok_val, float) and tok_val.is_integer() else tok_val
                )
            elif tok_type == "IDENTIFIER":
                if tok_val.lower() in ("true", "false"):
                    value = tok_val.lower() == "true"
                elif tok_val.lower() in ("null", "none"):
                    value = None
            # else string stays as-is

            # Validate LIKE patterns for ReDoS
            if op.upper() in ("LIKE", "LIKE%", "%LIKE", "%LIKE%"):
                if isinstance(value, str):
                    error = validate_regex_pattern(value)
                    if error is not None:
                        raise QueryError(f"Invalid LIKE pattern: {error}")

            conditions.append(WhereCondition(field=field, operator=op, value=value))
            pos += 1

            # Check if we're done
            if pos >= len(tokens) or (
                tokens[pos][0] == "KEYWORD" and tokens[pos][1] in ("ORDER BY", "LIMIT")
            ):
                break

        if not conditions:
            return pos, None
        return pos, WhereClause(conditions=conditions, logic=logic)

    def _parse_order_by(self, tokens: list[tuple], pos: int) -> tuple[int, OrderByClause | None]:
        """Parse ORDER BY clause. Returns (new_pos, OrderByClause)."""
        # tokens[pos] is ORDER, tokens[pos+1] should be BY
        if pos + 1 >= len(tokens) or tokens[pos][1] != "ORDER BY":
            raise QueryError("Expected ORDER BY")
        pos += 2

        if pos >= len(tokens) or tokens[pos][0] != "IDENTIFIER":
            raise QueryError("Expected field name after ORDER BY")
        field = tokens[pos][1].lower()
        if field not in _VALID_QUERY_FIELDS:
            raise QueryError(f"Unknown field in ORDER BY: {field}")
        pos += 1

        direction = SortOrder.DESC
        if pos < len(tokens) and tokens[pos][0] == "DIRECTION":
            direction = SortOrder(tokens[pos][1])
            pos += 1

        return pos, OrderByClause(field=field, direction=direction)

    def _parse_limit(self, tokens: list[tuple], pos: int) -> tuple[int, int | None]:
        """Parse LIMIT clause. Returns (new_pos, limit_value)."""
        pos += 1  # Skip LIMIT keyword
        if pos >= len(tokens) or tokens[pos][0] != "NUMBER":
            raise QueryError("Expected number after LIMIT")
        limit_val = tokens[pos][1]
        if not isinstance(limit_val, (int, float)) or limit_val < 0:
            raise QueryError("LIMIT must be a non-negative number")
        pos += 1
        return pos, int(limit_val)

    def execute(self, ast: AuditQueryAST, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute a parsed AST against a list of audit records.

        Args:
            ast: Parsed query AST
            records: List of audit record dictionaries

        Returns:
            Filtered, sorted, and limited records matching the query
        """
        result = list(records)

        # Apply WHERE filter
        if ast.where:
            result = self._apply_where(result, ast.where)

        # Apply ORDER BY
        if ast.order_by:
            result = self._apply_order_by(result, ast.order_by)

        # Apply LIMIT
        if ast.limit is not None:
            result = result[: ast.limit]

        return result

    def _apply_where(
        self, records: list[dict[str, Any]], where: WhereClause
    ) -> list[dict[str, Any]]:
        """Apply WHERE clause to filter records."""
        filtered = []
        for record in records:
            matches = []
            for cond in where.conditions:
                if self._evaluate_condition(record, cond):
                    matches.append(True)
                else:
                    matches.append(False)

            if where.logic == "AND":
                passed = all(matches)
            else:
                passed = any(matches)

            if passed:
                filtered.append(record)
        return filtered

    def _evaluate_condition(self, record: dict[str, Any], cond: WhereCondition) -> bool:
        """Evaluate a single condition against a record."""
        field = cond.field
        op = cond.operator
        expected = cond.value

        raw = record.get(field)
        actual = raw

        # Coerce comparison based on field type
        if field == "ok":
            actual = bool(record.get("ok", False))
            if isinstance(expected, bool):
                return actual == expected if op == "=" else actual != expected

        elif field in ("duration_ms", "timestamp"):
            # Try numeric coercion for duration_ms
            if field == "duration_ms":
                try:
                    actual = float(raw) if raw is not None else 0.0
                    if isinstance(expected, (int, float)):
                        return self._compare_numeric(actual, op, float(expected))
                except (ValueError, TypeError):
                    return False
            # timestamp string comparison
            actual = str(raw) if raw is not None else ""

        # String comparison with LIKE operators
        actual_str = str(actual) if actual is not None else ""
        expected_str = str(expected) if expected is not None else ""

        if op.upper() in ("LIKE", "LIKE%"):
            pattern = expected_str.replace("%", ".*")
            return bool(re.match(f"^{pattern}$", actual_str, re.IGNORECASE))
        elif op.upper() == "%LIKE":
            pattern = expected_str.replace("%", ".*")
            return bool(re.match(f"{pattern}$", actual_str, re.IGNORECASE))
        elif op.upper() == "%LIKE%":
            pattern = expected_str.replace("%", ".*")
            return bool(re.search(pattern, actual_str, re.IGNORECASE))
        elif op == "=":
            return actual_str.lower() == expected_str.lower()
        elif op == "!=":
            return actual_str.lower() != expected_str.lower()
        elif op in (">", "<", ">=", "<="):
            # For strings, use lexicographic comparison
            return (
                self._compare_numeric(float(actual), op, float(expected))
                if field == "duration_ms"
                else (
                    actual_str > expected_str
                    if op == ">"
                    else (actual_str < expected_str if op == "<" else False)
                )
            )

        return False

    def _compare_numeric(self, actual: float, op: str, expected: float) -> bool:
        """Compare two numeric values with the given operator."""
        if op == ">":
            return actual > expected
        elif op == "<":
            return actual < expected
        elif op == ">=":
            return actual >= expected
        elif op == "<=":
            return actual <= expected
        elif op == "=":
            return actual == expected
        elif op == "!=":
            return actual != expected
        return False

    def _apply_order_by(
        self, records: list[dict[str, Any]], order_by: OrderByClause
    ) -> list[dict[str, Any]]:
        """Apply ORDER BY clause to sort records."""
        field = order_by.field
        reverse = order_by.direction == SortOrder.DESC

        def sort_key(rec: dict[str, Any]) -> tuple:
            val = rec.get(field)
            if field == "ok":
                return (0 if bool(val) else 1,)
            if field == "duration_ms":
                try:
                    return (float(val) if val is not None else 0.0,)
                except (ValueError, TypeError):
                    return (0.0,)
            # timestamp and string fields
            return (str(val) if val is not None else "",)

        return sorted(records, key=sort_key, reverse=reverse)
