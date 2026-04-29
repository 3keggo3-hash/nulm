# DesktopCommanderMCP — İkinci Araştırma Analizi

> Kaynak: Çoklu araştırma metni + README deep-dive + kaynak kod incelemesi
> Tarih: 29 Nisan 2026
> Amacı: DesktopCommanderMCP'den Claude Bridge'e aktarılabilecek yeni bulgular

Bu analiz, önceki kaynak kod incelemesi (`docs/desktop-commander-source-analysis.md`) ve stratejik yol haritası (`docs/strategic-roadmap.md`) ile **çakışmayan**, ek değer üreten bulguları içerir.

---

## 1. Tool Description = Prompt (Kritik UX Tasarımı)

DesktopCommander'ın en güçlü ama en az tartışılan tarafı: tool description'ları Claude'un davranışını belirliyor.

**Mevcut eleştiri:** "Tool descriptions are written for humans, not AI" — issues'da şikayet var.

**DesktopCommander'ın yaklaşımı:**
- Tool tanımı = mini instruction set
- Her tool, Claude'a "nasıl davranacağını" söylüyor
- "Always check for dangerous commands"
- "Use timeout when necessary"
- "Prefer small edits over full rewrites"

**Claude Bridge'in mevcut durumu:** Tool description'ları kısa ve teknik:

```python
@mcp.tool(description="Find the most relevant files in the project.")
async def find_relevant_files(query: str, path: str = ".", limit: int = 5) -> str:
```

**Claude Bridge'e uyarlanması:** Her tool description'u "instruction-heavy" yap:

```python
@mcp.tool(description=(
    "Find the most relevant files for a given query using token-based scoring. "
    "Use this BEFORE reading files to understand the codebase. "
    "Prefer specific queries over broad ones. "
    "Limit results to 5-10 files unless the user asks for a comprehensive analysis."
))
async def find_relevant_files(query: str, path: str = ".", limit: int = 5) -> str:
```

```python
@mcp.tool(description=(
    "Apply a targeted SEARCH/REPLACE edit to a file. "
    "ALWAYS prefer this over write_file for existing files. "
    "Keep SEARCH text as small and unique as possible to avoid ambiguous matches. "
    "Do NOT rewrite entire files unless absolutely necessary."
))
async def patch_file(file: str, search: str, replace: str) -> str:
```

```python
@mcp.tool(description=(
    "Run a non-interactive shell command. "
    "Prefer read-only commands (pytest, git status, ls, cat). "
    "Never run sudo, rm -rf, or pipe curl to shell. "
    "If a command fails, analyze the error before retrying."
))
async def run_shell(command: str) -> str:
```

**Öncelik:** FAZ 1 — Sıfır kod değişikliği, sadece description güncellemesi. En yüksek ROI.

---

## 2. In-Memory Code Execution (Bellek İçi Kod Çalıştırma)

DesktopCommander'ın kaynak kodunda `node:local` virtual session olarak implement edilmiş:

```typescript
// Special case: node:local creates virtual Node.js sessions
// Falls back to temp .mjs files for stateless server-side execution
// No files are saved to disk — code runs in memory
```

**Kullanım senaryoları:**
- "Analyze sales.csv" → Python kodu çalışır, dosya oluşturmaz
- "Quick math calculation" → tek satırlık Python/Node.js
- "Parse this JSON and summarize" → inline veri işleme

**Claude Bridge'e uyarlanması:**

```python
@mcp.tool(description=(
    "Execute Python or Node.js code in memory without saving to disk. "
    "Use this for quick data analysis, calculations, or one-off scripts. "
    "Do NOT use for long-running processes or code that needs persistent state."
))
async def execute_code(language: str, code: str, timeout: int = 30) -> str:
    if language == "python":
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(project_dir()),
        )
        return json_response(
            result.returncode == 0,
            f"Code executed ({language})",
            details={
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
                "exit_code": result.returncode,
            },
        )
    elif language == "node":
        result = subprocess.run(
            ["node", "-e", code],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(project_dir()),
        )
        ...
    else:
        return json_response(False, f"Unsupported language: {language}", ...)
```

**Güvenlik:** `subprocess.run(shell=False)` + timeout + project_dir sınırı + denylist kontrolü.

**Öncelik:** FAZ 2.

---

## 3. read_multiple_files — Paralel Dosya Okuma

DesktopCommander'da var, Claude Bridge'de yok:

```json
read_multiple_files({ "paths": ["src/server.py", "src/config.py", "src/indexing.py"] })
```

**Neden kritik:** Claude genellikle bir dosyayı okuduktan sonra ilişkili dosyaları da okumak ister. Şu an her biri için ayrı `read_file` çağırıyor — 3 dosya = 3 tool call = 3 round-trip.

```python
@mcp.tool(description=(
    "Read multiple files at once. Use this when you need to compare "
    "or cross-reference multiple files. More efficient than calling read_file multiple times."
))
async def read_multiple_files(paths: list[str], offset: int = 0, limit: int = 200) -> str:
    results = []
    for path in paths:
        target = resolve_path(path)
        if not target.exists() or not target.is_file():
            results.append({"path": path, "error": f"File not found: {path}"})
            continue
        sensitive_reason = sensitive_path_reason(target)
        if sensitive_reason:
            results.append({"path": path, "error": f"Blocked: {sensitive_reason}"})
            continue
        content = safe_read_text(target)
        lines = content.splitlines()
        page = lines[offset:offset + limit]
        results.append({
            "path": path,
            "total_lines": len(lines),
            "offset": offset,
            "limit": limit,
            "content": "\n".join(page),
            "has_more": offset + limit < len(lines),
        })
    return json_response(True, f"Read {len(results)} files", details={"files": results})
```

**Öncelik:** FAZ 1 — Düşük efor, UX iyileştirmesi.

---

## 4. Negative Offset File Reading (Unix tail)

Kaynak kodda `reverse reading in 8KB chunks` olarak implement edilmiş:

```typescript
// Tail reads on large files: reverse reading in 8KB chunks
// Dosyanın sonundan offset kadar satır okuma
```

**Claude Bridge'in mevcut read_file'ı:** Sadece pozitif offset destekliyor (veya hiç yok).

**Kullanım senaryoları:**
- `read_file("app.log", offset=-100)` → son 100 satır (log analizi)
- `read_file("large_file.csv", offset=-20)` → CSV son satırları

```python
async def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    content = safe_read_text(target)
    lines = content.splitlines()
    if offset < 0:
        offset = max(0, len(lines) + offset)
    elif offset == 0 and limit > len(lines):
        limit = len(lines)
    page = lines[offset:offset + limit]
    return json_response(True, f"Read {len(page)} lines", details={
        "path": path, "total_lines": len(lines),
        "offset": offset, "limit": limit,
        "has_more": (offset + limit) < len(lines),
        "content": "\n".join(page),
    })
```

**Öncelik:** FAZ 1 — read_file pagination ile birlikte.

---

## 5. "Deterministic Editing" Zorunluluğu

DesktopCommander'ın en güçlü UX kararlarından biri:

**Kural:** Full file rewrite yerine `edit_block` (SEARCH/REPLACE) kullanımını zorunlu kıl.

**Claude Bridge'de:** `write_file` ve `patch_file` yan yana duruyor. Claude herhangi birini seçebilir.

**DesktopCommander'ın yaklaşımı:**
- `fileWriteLineLimit` (50 satır) → büyük yazma uyarı ver
- Tool description'da "Prefer edit_block over write_file"
- Açık uyarı: "For optimal speed, consider chunking files into <=30 line pieces"

**Claude Bridge'e uyarlanması:**
1. `write_file` tool description'una uyarı ekle:
   ```
   "WARNING: Prefer patch_file for existing files. Only use write_file for new files.
    If content exceeds 50 lines, split into smaller patch_file calls."
   ```
2. `write_file` implementasyonuna soft limit:
   ```python
   lines = content.splitlines()
   if len(lines) > 50:
       return json_response(True, f"Wrote file: {path}", details={
           ...
           "warning": f"Content was {len(lines)} lines. Consider using patch_file for existing files.",
       })
   ```

**Neden kritik:** Bu tek karar, Claude'un davranış kalitesini ciddi artırır. Hallucination riskini azaltır, token israfını önler, geri alma kolaylaşır.

**Öncelik:** FAZ 1 — Description değişikliği + soft limit.

---

## 6. Prompt Design Pattern: "Önce Keşfet, Sonra Değiştir"

DesktopCommander'ın prompt mimarisinin temel prensibi:

```
1. list_directory → ortamı tanı
2. read_file → bağlamı anla
3. edit_block → küçük değişiklik
4. execute_command → doğrula
5. hata varsa → analiz et ve düzelt
```

**Claude Bridge'de:** Bu pattern zaten var ama tool description'larda vurgulanmıyor.

**Claude Bridge'e uyarlanması:** System prompt veya tool description'larda:

```
WORKFLOW PATTERN:
1. Explore: list_directory to understand project structure
2. Read: read_file or find_relevant_files to gather context
3. Plan: Think before acting — small, reversible changes
4. Edit: Use patch_file for existing files, write_file only for new files
5. Verify: Run tests or lint to confirm the change works
6. Fix: If verification fails, analyze the error and try again
```

**Öncelik:** FAZ 1 — System prompt güncellemesi.

---

## 7. Tool Annotations (MCP 2025+)

Kaynak kod incelemesinde keşfedilen, README'de geçmeyen MCP özelliği:

```typescript
// Her tool'a annotation:
readOnlyHint: true      → read_file, list_directory, get_config
destructiveHint: true   → write_file, edit_block, move_file
openWorldHint: true     → start_process, write_file
```

Claude Desktop bu hint'ları UI'da kullanıyor — read-only tool'lar farklı ikon, destructive tool'lar onay gerektiriyor.

**Claude Bridge'de:** Tool annotation yok.

**Claude Bridge'e uyarlanması (FastMCP ile):**

```python
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("Claude Bridge")

@mcp.tool(
    name="read_file",
    description="Read file contents...",
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def read_file(path: str) -> str:
    ...

@mcp.tool(
    name="patch_file",
    description="Apply SEARCH/REPLACE edit...",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def patch_file(file: str, search: str, replace: str) -> str:
    ...

@mcp.tool(
    name="run_shell",
    description="Execute shell command...",
    annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
)
async def run_shell(command: str) -> str:
    ...
```

**Öncelik:** FAZ 1 — Çok düşük efor.

---

## 8. "Auto-Dev Agent Loop" — DesktopCommander'ın Gizli Gücü

DesktopCommander'ın asıl değer önerisi:

```
"Fix all TypeScript errors"
  → search_files
  → read_file (hata satırları)
  → edit_block (düzeltme)
  → execute_command (tsc)
  → hata varsa tekrar
```

Bu, DesktopCommander'ın README'sinde açıkça belirtilmiyor ama tool set'inin doğal sonucu.

**Claude Bridge avantajı:** Claude Bridge'in `run_workflow(mode="agent_loop")` ve `run_agent_loop_session` bunu zaten yapıyor. Ama DesktopCommander'ın "her tool'u bir mini-agent" yaklaşımını kopyalamalıyız.

**Öncelik:** FAZ 2 — Agent loop'ı mevcut tool'larla zaten destekliyoruz. Tool description'ları "agent loop-friendly" yapılmalı.

---

## 9. Context Overflow Koruma Stratejisi

DesktopCommander context overflow'u 3 katmanda önlüyor:

| Katman | Yöntem | Varsayılan |
|-------|--------|-----------|
| read_file | Satır limiti + pagination | 1000 satır |
| process output | Offset-based pagination | 1000 satır |
| list_directory | Depth limit + 100-item cap | depth=2 |
| search | Streaming + offset-based pagination | 100 sonuç/page |
| edit_block | Satır limiti uyarısı | 50 satır arama/replace |

**Claude Bridge'in mevcut durumu:** Hiçbir limit yok. Büyük dosya + büyük proje = context overflow.

**Claude Bridge'e uyarlanması:**

```python
# Config'e ekle:
DEFAULT_READ_LIMIT = 200       # read_file default
MAX_READ_LIMIT = 2000          # read_file max
DEFAULT_LIST_DEPTH = 2         # list_directory recursive depth
MAX_SEARCH_RESULTS = 100       # search_in_files max
DEFAULT_WRITE_LIMIT = 50       # write_file warning threshold
MAX_PROCESS_OUTPUT = 2000      # run_shell output truncation
```

**Öncelik:** FAZ 1.

---

## 10. Usage Stats ve "Learning from History"

DesktopCommander iki meta tool sunuyor:

**`get_usage_stats`:** Kişisel kullanım istatistikleri — başarı oranı, performans metrikleri.

**`get_recent_tool_calls`:** Son tool çağrılarının geçmişi — argümanlar ve çıktılarla birlikte.

Bu iki tool'un birleşimi = "Claude kendi geçmişini öğreniyor."

**Claude Bridge'de:** `get_recent_tool_calls` yok. Audit log var (planlanmış) ama Claude'un erişemediği.

**Öncelik:** FAZ 1 — Audit log ile birlikte, `get_recent_tool_calls` tool'u ekle.

---

## 11. "Skills" Sistemi — Gelecek Özellik (Planlı)

DesktopCommander'ın README'sinde "Coming soon" olarak işaretlenmiş:

> Skills system, dictation, background scheduled tasks, and more

**Bu ne demek:** Tekrar kullanılabilir task tanımları. Örn:

```
Skill: "Run tests and fix failures"
  1. pytest
  2. if fail: read error
  3. edit_file
  4. pytest again
  5. repeat until pass
```

**Claude Bridge avantajı:** Bridge'in `run_workflow` ve `context_pack` zaten bu işi yapıyor ama "user-defined skill" konsepti yok.

**Claude Bridge'e uyarlanması:** Reproducible task packs (Faz 2'de planlanmış) bu boşluğu doldurur.

---

## Öncelik Sırasına Göre Yeni Özellikler

| Öncelik | Özellik | Efor | Fayda |
|---------|---------|------|------|
| **1** | Tool description'larını "instruction-heavy" yap | Çok düşük | Claude davranış kalitesi artar |
| **2** | Tool annotations (readOnly/destructive/openWorld) | Çok düşük | Claude Desktop UI iyileşir |
| **3** | "Deterministic editing" zorunluluğu (description + soft limit) | Çok düşük | Hallucination riski azalır |
| **4** | Context overflow limitleri (read/write/search/list) | Düşük | Büyük projelerde stabil çalışma |
| **5** | read_multiple_files tool'u | Düşük | Paralel okuma, round-trip azalır |
| **6** | read_file pagination + negative offset | Düşük | Büyük dosya desteği |
| **7** | get_recent_tool_calls tool'u | Düşük | Debugging + learning |
| **8** | In-memory code execution | Orta | Veri analizi senaryoları |
| **9** | "Önce keşfet, sonra değiştir" system prompt | Çok düşük | Claude workflow kalitesi |

---

## DesktopCommander'ın Claude Bridge'den Geride Kaldığı Yerler (Tekrar Vurgu)

Bu araştırmada da doğrulanan Claude Bridge avantajları:

| Claude Bridge'de VAR, DesktopCommander'da YOK |
|----------------------------------------------|
| Tree-sitter indexing (AST-level code intelligence) |
| Token-based relevance scoring |
| 9 structured workflow modes |
| Context pack system |
| Agent loop with bounded iterations |
| Secret pattern detection (API_KEY=, password=, AWS key) |
| Python syntax check (ast.parse) |
| Project type auto-detection |
| Git auto-commit with diff |
| Patch risk analysis (low/medium/high) |
| Suggest validation commands |

**Bu avantajlar kaybedilmemeli.** DesktopCommander'ın özelliklerini kopyalarken bu farklılaşma eksenini korumak kritik.
