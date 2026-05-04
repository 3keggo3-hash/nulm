# Claude Bridge — Birleştirilmiş İcra Planı

> **Amaç:** Bu doküman, iki ayrı derinlemesine kod analizinden çıkan tüm bulguları,
> önceliklendirilmiş görevleri, zorluk seviyelerini ve bağımlılık sıralarını tek bir
> kaynakta birleştirir. Yeni bir AI agent'ı bu dokümanı okuyarak projede neyin
> yapılması gerektiğini anlayabilir ve icraya başlayabilir.
>
> **Hazırlanma tarihi:** 2026-05
> **Son güncelleme:** Revizyon 3 — metrikler güncellendi, K7 çıkarıldı, K2/O5 birleştirildi,
> Z2 kaldırıldı (zaten yapılmış), K4 O1a'dan önceye alındı, O3 güvenlik spec'i eklendi,
> Z6 multi-client notu eklendi, Z11 "security design required" etiketiyle en sona itildi.
>
> **Kaynak analizler:**
> - Birinci analiz (Claude Code içinden)
> - İkinci analiz (harici kod inceleme)
> - `docs/known-issues-and-improvements.md`
> - `docs/performance-and-completion-audit.md`
> - `docs/strategic-roadmap.md`
> - `docs/competitive-development-plan.md`
> - `docs/roadmap.md`

---

## İçindekiler

1. [Proje Hakkında](#1-proje-hakkında)
2. [Mevcut Durum](#2-mevcut-durum)
3. [Rakip Karşılaştırması](#3-rakip-karşılaştırması-desktopcommandermcp)
4. [Gerçek Bug'lar — Hemen Düzeltilmeli](#4-gerçek-buglar--hemen-düzeltilmeli)
5. [Tüm Görevler — Zorluk Bazlı](#5-tüm-görevler--zorluk-bazlı)
6. [Bağımlılık Sıralı İcra Planı](#6-bağımlılık-sıralı-icra-planı)
7. [Delegasyon Paketleri](#7-delegasyon-paketleri-vibe-coding-için)
8. [DesktopCommanderMCP'yi Geçme Stratejisi](#8-desktopcommandermcpyi-geçme-stratejisi)
9. [Değiştirilmemesi Gerekenler](#9-değiştirilmemesi-gerekenler)
10. [Tasarım Kararları](#10-tasarım-kararları-bekleyen)
11. [AI Agent Handoff ve Entegrasyon](#11-ai-agent-handoff-ve-entegrasyon)

---

## 1. Proje Hakkında

**Claude Bridge**, Claude Desktop ve diğer MCP istemcileri için yerel dosya sistemi,
shell ve kontrollü patch akışlarını sunan Python tabanlı bir MCP sunucusudur.

```text
claudey code/
├── src/claude_bridge/       # Uygulama kodu (23 .py dosyası)
│   ├── server.py            # Ana MCP sunucusu (~1870 satır, 30+ tool)
│   ├── config.py            # Runtime konfigürasyon state'i
│   ├── shell_tools.py       # Shell komut yürütme ve process yönetimi
│   ├── file_tools.py        # Dosya okuma/yazma/patch/listeleme
│   ├── indexing.py          # Kod tabanı indeksleme (çok dilli)
│   ├── relevance.py         # İndekslenmiş kodda relevans skorlaması
│   ├── audit.py             # Yapılandırılmış audit logging (JSONL)
│   ├── workflow_tools.py    # Workflow, agent loop, context pack
│   ├── workflow_presets.py  # Statik workflow şablonları
│   ├── insights.py          # Proje analiz araçları (TODO tarama, git log, vb.)
│   ├── smart.py             # Token sayımı, encoding tespiti
│   ├── git_ops.py           # Git yardımcıları
│   ├── doctor.py            # Ortam sağlık kontrolü
│   ├── onboarding.py        # İlk kullanım ipuçları
│   ├── benchmarking.py      # Performans benchmark
│   ├── prompt.py            # Sistem prompt'u ve setup guide
│   ├── fun_content.py       # Eğlenceli içerik üretici
│   ├── tool_utils.py        # Paylaşılan yardımcılar (path, onay, hassas dosya)
│   ├── cli.py               # CLI arayüzü (typer)
│   ├── insights_tool_registration.py  # Insights tool'ları MCP'ye kaydetme
│   └── smart_tool_registration.py     # Smart tool'ları MCP'ye kaydetme
├── tests/                   # pytest (292 test, tümü geçiyor)
├── docs/                    # Kalıcı dokümantasyon
├── tasks/                   # Aktif ve tamamlanmış görevler
└── benchmarks/              # Benchmark profilleri
```

**Teknik özellikler:**
- Python 3.8+ uyumluluğu
- Black formatlama (100 karakter satır limiti)
- Ruff linting
- Mypy strict type checking
- FastMCP üzerine inşa edilmiş MCP sunucusu
- Opsiyonel dependency grupları: `[dev]`, `[smart]`, `[treesitter]`

---

## 2. Mevcut Durum

| Metrik | Değer |
|--------|-------|
| Test sayısı | 292 (tümü geçiyor) |
| `ruff check` | Temiz |
| `mypy src` | Temiz |
| `black` format | Uyumlu |
| MCP tool sayısı | 30+ |
| MCP prompt sayısı | 13 |
| Onay modu preset'leri | 4 (read-only, dev-safe, ci-like, power-user) |
| Bütçe profilleri | 3 (low-cost, balanced, deep) |
| Workflow modları | 9 (review, optimize, orchestrate, agent_loop, quality, test, todo, explain, commit) |
| Desteklenen diller (sembol çıkarımı) | Python, JS/TS, Rust, Go, Java, Kotlin, C#, Ruby, PHP, GDScript |

**Güçlü yanlar:**
- Audit logging (JSONL, hash'li, telemetrili, gizli bilgi sızdırmaz)
- Çok dilli indeksleme (AST + regex fallback + Tree-sitter opsiyonel)
- Token/field-aware relevans skorlaması
- Fail-closed güvenlik modeli (kara liste + `shell=False` + path sınırları)
- Agent loop ve workflow orkestrasyonu
- Runtime config değiştirme (approval preset, budget profile, onboarding toggle)
- `claude-bridge doctor` ortam sağlık kontrolü

**Zaten yapılmış, planda yok:**
- `stat()` optimizasyonu — `indexing.py#L661` zaten tek `file.stat()` çağrısı kullanıyor
- `_command_basename()` — tam path → basename normalizasyonu mevcut
- `_INTERACTIVE_COMMANDS` — tüm bilinen interaktif shell'leri içeriyor
- `_truncate_output()` — truncation marker mevcut

---

## 3. Rakip Karşılaştırması: DesktopCommanderMCP

DesktopCommanderMCP, aynı MCP alanındaki en olgun rakiptir. Karşılaştırmalı analiz:

| Alan | Claude Bridge | DesktopCommanderMCP | Durum |
|------|--------------|---------------------|-------|
| **Shell execution** | `run_shell`, `start_process`, `interact_with_process` | Aynı + `force_terminate` | DC hafif önde |
| **Process yönetimi** | `start`, `read`, `interact`, `kill`, `list` | Benzer + `force_terminate` | DC hafif önde |
| **File move** | Yok | `move_file` | **Eksik** |
| **URL okuma** | Yok | `read_file` ile URL fetch | **Eksik** |
| **Multi-format** | Yok | Excel, PDF, DOCX, PNG, JPEG | **Eksik** |
| **In-memory execution** | Yok | `execute_code` sandbox | **Eksik** |
| **Auto-update** | Yok | `auto_update`, `auto_uninstall` | **Eksik** |
| **Feedback** | Yok | `send_feedback` | **Eksik** |
| **File write line limit** | Yok | AI token israfını engelleyen sınır | **Eksik** |
| **Onboarding** | Hafif 3 aşamalı inline tool-tip | Kapsamlı multi-message sistem | DC önde |
| **Audit logging** | Yapılandırılmış JSONL, hash, telemetri | Temel | **CB üstün** |
| **Indexing/relevance** | Çok dilli sembolik + Tree-sitter, token scoring | Yok (sadece grep) | **CB üstün** |
| **Workflow/prompt** | 13 prompt + 9 mod + agent loop | Yok | **CB üstün** |
| **Runtime config** | `set_config_value`, 4 preset, 3 bütçe profili | Temel | **CB üstün** |
| **Doctor** | `claude-bridge doctor` | Yok | **CB üstün** |
| **Fuzzy matching** | `_log_fuzzy_match_attempt` (dahili) | Log analizi ve görünür feedback | DC önde |
| **Output pagination** | Var (offset/limit) | Daha gelişmiş streaming | DC önde |

**Özet:**
- Claude Bridge 5 alanda üstün (altyapısal)
- DesktopCommanderMCP 9 alanda üstün (kullanıcıya dokunan)
- 3 alanda eşit

---

## 4. Gerçek Bug'lar — Hemen Düzeltilmeli

### B1: `index_codebase` unreachable code + undefined variable

**Dosya:** `src/claude_bridge/server.py`, satır ~1004-1018

**Sorun:** `except NotADirectoryError` bloğunda `return _audit_tool_call(...)` sonrasında
`if not isinstance(payload, dict)` kontrolü var. Bu kod asla çalışmaz (unreachable).
Ayrıca `payload` değişkeni bu scope'ta tanımlı değil.

**Çözüm:** İlk sprintte en risksiz düzeltme, unreachable defensive bloğu silmektir.
`_build_index()` internal bir fonksiyon ve beklenen payload yapısını dönüyor. Daha sonra
ekstra defensive validation istenirse bu kontrol `except` bloklarının dışına ayrı bir
değişiklik olarak eklenebilir.

```python
# Şu anki hatalı yapı:
    except NotADirectoryError:
        ...
        return _audit_tool_call("index_codebase", ...)

        # ⚠️ Unreachable, payload tanımsız
        if not isinstance(payload, dict) or "files" not in payload:
            ...

# İlk sprintte uygulanacak yapı:
    except NotADirectoryError:
        ...
        return _audit_tool_call("index_codebase", ...)

    # Unreachable payload kontrolü kaldırılır.
```

---

## 5. Tüm Görevler — Zorluk Bazlı

### 🟢 Kolay (8 görev, toplam ~1.5-2.5 saat)

Her biri tek dosya, net girdi/çıktı, bağımlılıksız. Düşük risk, hemen yapılabilir.

| ID | Görev | Dosya(lar) | Açıklama |
|----|-------|-----------|----------|
| **K1** | `index_codebase` unreachable code fix | `server.py` | **En acil.** B1'deki bug. İlk sprintte en risksiz çözüm: `return` sonrası unreachable bloğu sil. Defensive payload validation istenirse ayrı değişiklik olarak `except` dışına eklenebilir. |
| **K2** | `switch_project_root` onboarding reset | `server.py` | `set_config` ve `configure_from_env` `reset_onboarding_state()` çağırıyor, `switch_project_root` çağırmıyor — tutarsız. Tek satır ekle. |
| **K3** | `_LAST_BRIDGE_CHANGE` project-root scoped state | `file_tools.py` | Global değişkeni ilk aşamada active project root'a göre sakla (`key = resolved project_dir`). Böylece workspace switch sonrası undo/last-change karışmaz. **Sadece bu global'i düzelt — `state.py` modülü oluşturma.** MCP stdio single-thread, erken soyutlamaya gerek yok. |
| **K4** | `prompt_shortcuts` ↔ `_register_prompts` birleştir | `server.py`, `workflow_presets.py` | Aynı 13 prompt iki yerde tanımlı. `_register_prompts`, `PROMPT_SHORTCUTS` listesinden beslensin. **O1a'dan ÖNCE yap — yoksa aynı alanı iki kere oynarız.** |
| **K5** | File write line limit | `file_tools.py`, `server.py` | DesktopCommanderMCP feature. `write_file`'a `max_lines` parametresi ekle (varsayılan 500). Aşınca **bloklama yapma**; yazma başarılı olsun ama structured warning dön: `"content has N lines (max_lines=500), consider patch_file for targeted edits or increase max_lines"`. |
| **K6** | `move_file` tool'u | `file_tools.py`, `server.py` | DesktopCommanderMCP feature. Dosya taşıma/rename. `resolve_path` + `sensitive_path_reason` + audit. Bonus: `copy_path` da ekle (DC'de yok). |
| **K7** | Binary tespiti: ilk N byte | `indexing.py` | `iter_searchable_files` dosyanın tamamını binary kontrolü için okuyor. İlk 512 byte yeterli. `is_likely_binary()` ekle. |
| **K8** | `_audit_tool_call` tip daraltma | `server.py` | `onboarding_enabled` kontrolünde `bool()` cast'i zaten var, sadece tip annotation daraltması. |

> **Not:** `allowed_roots()` lock-içi defensive copy (`config.py#L162`) **değiştirilmemeli.**
> Düşük değerli, riskli/yanıltıcı bir "optimizasyon" olur. Mevcut hali doğru.

---

### 🟡 Orta (13 görev, toplam ~13-18 saat)

Birden fazla dosya, tasarım kararı gerektiren, ama net spec'i olan görevler.

| ID | Görev | Dosya(lar) | Açıklama |
|----|-------|-----------|----------|
| **O1a** | Prompt/meta registration ayrıştır ⭐ | `meta_tool_server.py` (yeni) + `server.py` | **İlk küçük PR, en düşük riskli.** `server.py`'den şunlar çıkar: `bridge_status`, `tools_overview`, `get_config`, `set_config_value`, `get_recent_tool_calls`, `session_insights`, `usage_insights`, `workspace_status`, `switch_project_root`, `compact_user_intent`, `prompt_shortcuts` + `_register_prompts()`. `meta_tool_server.py`'de `register_meta_tools(mcp, ...)` imzası. Mevcut `insights_tool_registration.py` pattern'ini takip et. **K4 bundan önce yapılmalı.** |
| **O1b** | File tool wrapper'larını çıkar | `file_tool_server.py` (yeni) + `server.py` | **İkinci küçük PR.** `read_file`, `read_multiple_files`, `list_directory`, `write_file`, `search_in_files`, `patch_file`, `preview_patch`, `undo_last_patch` → `file_tool_server.py`. `register_file_tools(...)` imzası. |
| **O1c** | Shell/workflow registration çıkar | `shell_tool_server.py`, `workflow_tool_server.py` (yeni) + `server.py` | **Üçüncü küçük PR.** Shell: `analyze_shell_command`, `run_shell`, `start_process`, `read_process_output`, `list_process_sessions`, `kill_process`, `interact_with_process` → `shell_tool_server.py`. Workflow: `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session`, `build_context_pack`, `narrow_context`, `suggest_validation_commands` → `workflow_tool_server.py`. `server.py` registration entrypoint olarak kalmalı ve önemli ölçüde küçülmeli; kesin satır sayısı kabul kriteri değildir. |
| **O2** | Smart onboarding genişletme | `onboarding.py` | DesktopCommanderMCP feature. Mevcut 3 → 6 aşama. 1. çağrı: `bridge_status`. 3: `tools_overview`. 5: proje tipine göre öneri. `_ONBOARDING_TRIGGER_CALLS` → `{1, 3, 5, 8, 12}`. |
| **O3** | `read_url` tool'u (ayrı tool) | Yeni `url_tools.py` + `server.py` | **Ayrı tool, `read_file`'a dokunma.** `read_url(url: str) -> str`. Güvenlik spec'i: **sadece http/https**, timeout (10sn), max byte limiti (1MB), redirect limiti (5), content-type kontrolü (text/* kabul, binary red), audit'te URL + hash/log summary (içerik değil). `urllib` (stdlib) ile başla, opsiyonel `httpx`. |
| **O4** | Auto-update (check-only) | Yeni `update.py`, `cli.py` | **Sadece kontrol, yükleme yok.** `claude-bridge update` → mevcut sürüm (`importlib.metadata`), PyPI son sürüm, önerilen `pip install` komutu, changelog linki. `--apply` sonradan, onaylı şekilde eklenecek. |
| **O6** | `.gitignore` mtime-based cache | `indexing.py` | `read_gitignore_patterns()` her çağrıda disk okuyor. `{path: (mtime, patterns)}` cache'i. |
| **O7** | `selection_reason` | `relevance.py`, `server.py` | `find_relevant_files` sonucunda `selection_reason: {path_match: [...], function_match: [...], ...}`. |
| **O8** | Disk cache boyut kotası | `indexing.py`, `workflow_tools.py` | Dosya sayısı sınırına ek olarak toplam boyut limiti: ~50MB. |
| **O9** | `client_managed_approval=True` testleri | `tests/test_security.py` | Mock approval handler ile `=True` senaryosunu test et. |
| **O10** | `test_protocol.py` bölme | `tests/` | 2400+ satır → `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`, `test_workflow_tools.py`. |
| **O11** | Paralel test izolasyonu | `tests/conftest.py` | `autouse` fixture: her test sonrası state reset. Veya xdist kullanma. |
| **O12** | Inline interpreter politikası | `shell_tools.py` + doküman | Seçenek B önerilir: `_INLINE_INTERPRETER_FLAGS = {"perl -e", "ruby -e", "node -e", "php -r", "lua -e"}` set'i, `blocked_command_reason()`'dan dönsün. `python3 -c` izinli kalsın (backward compat). |

> **Not:** Eski O5 (merkezi state.py) iptal edildi. `_LAST_BRIDGE_CHANGE`
> project-root scoped state K3'te ele alınıyor.

---

### 🔴 Zor (12 görev, toplam ~8-15 gün)

Yeni alt sistemler, harici kütüphaneler, karmaşık state machine'ler, kapsamlı test.

| ID | Görev | Dosya(lar) | Açıklama |
|----|-------|-----------|----------|
| **Z1a** | Multi-Format MVP ⭐ | Yeni `multi_format.py`, `server.py` | **En yüksek kullanıcı değeri.** Sadece `read_image` + `read_pdf` (text-only, PyPDF2). `[multi-format]` extras: Pillow + PyPDF2. Detaylı spec aşağıda. |
| **Z1b** | Excel desteği | `multi_format.py` genişletme | Z1a'dan sonra. `read_excel`, `openpyxl`. Sheet/range/pagination. |
| **Z1c** | Gelişmiş Multi-Format | `multi_format.py` genişletme | En son. DOCX, PDF görseller, Excel arama, relevance bağlantısı. |
| **Z3** | Tree-sitter parser cache | `indexing.py` | `_load_tree_sitter_parser()` her dosya için import yapıyor. Dil başına `@lru_cache(maxsize=16)`. |
| **Z4** | `_iter_tree_sitter_nodes` iterative | `indexing.py` | Recursive → stack-based iterative. `RecursionError` riski gerçek. |
| **Z5** | `self_healing_loop` | `workflow_tools.py` | Validation fail → stderr analizi → hedefli patch → tekrar valide. |
| **Z6** | `dry_run` modu | `workflow_tools.py` | Global config-based: `set_config_value(key="dry_run", value=true)`. **Not:** Global config tüm session'ları etkiler. MCP stdio'da tek client için sorun yok. **İleride multi-client olursa session-scoped dry_run gerekebilir.** |
| **Z7** | `reproducible_task_pack` | Yeni `task_pack.py` | JSON görev zinciri. `$prev` referans çözümleme, validation gate'ler. |
| **Z8** | Cross-platform CI | `.github/workflows/` | Linux + Windows smoke test. |
| **Z9** | Golden relevance dataset genişletme | `tests/test_relevance_golden.py` | Java, Ruby, monorepo vakaları. CI regresyon kapısı. |
| **Z10** | Python 3.8 Tree-sitter CI | CI + test | CI matrisine 3.8 + treesitter ekle. |
| **Z11** | In-memory code execution ⚠️ | Yeni `sandbox.py` | **⚠️ Security design required.** DesktopCommanderMCP feature. `execute_code(language, code)`. `[sandbox]` extras, timeout, memory limit, import whitelist. En sona bırak, önce güvenlik tasarımı yap. "DC'de var" diye erkene çekme. |
| **Z12** | Semantic relevance (opsiyonel) | Yeni `semantic_relevance.py` | Embedding tabanlı alternatif scoring. `[semantic]` extras. En deneysel. |
| **Z13** | Feedback mechanism | Yeni `feedback.py`, `server.py` | `send_feedback(rating, comment, include_session=True)`. Audit log iliştir. |

> **Not:** Z2 (`stat()` optimizasyonu) **zaten yapılmış.** `indexing.py#L661`'de `_file_signature` tek `file.stat()` çağrısı kullanıyor. Plandan çıkarıldı.

---

### Z1a Detaylı Spec: Multi-Format MVP

**Hedef:** Claude Bridge'e kod dışı dosyaları okuyabilme yeteneği ekle: görseller ve PDF'ler.

**Kapsam:**
- Yeni modül: `src/claude_bridge/multi_format.py`
- Yeni optional extra: `[multi-format]`
- Yeni tool: `read_image`
- Yeni tool: `read_pdf`
- `server.py` tool registration
- Test fixture'ları ve unit testler

**Dependency'ler (pyproject.toml):**
```toml
[project.optional-dependencies]
multi-format = [
    "Pillow>=10.0.0",      # image metadata
    "PyPDF2>=3.0.0",       # PDF text extraction (hafif)
]
```

**`read_image` davranışı:**
- Workspace path güvenlik kontrollerini kullan (`resolve_path` + `is_within_root`)
- Desteklenen formatlar: PNG, JPEG, GIF, WebP
- MIME type, byte size, width/height metadata döndür
- Claude Desktop'ın anlayabileceği base64 içerik veya MCP image content tipinde payload
- Büyük görseller için boyut limiti (örn. 10MB)
- Binary/sensitive path guardrail'leri korunsun

**`read_pdf` davranışı:**
- Workspace path güvenlik kontrollerini kullan
- İlk sürüm **text-only** (görsel çıkarma yok)
- Sayfa sayısı, dönen sayfa aralığı, karakter sayısı metadata
- `offset` / `limit` benzeri sayfa pagination (`page_start`, `page_end`)
- Şifreli, bozuk veya text çıkarılamayan PDF'lerde structured error
- PyPDF2 ile hafif başla; ileride pymupdf düşünülebilir

**Graceful degradation:**
- Core kurulum opsiyonel bağımlılıklar olmadan çalışmaya devam etmeli
- Eksik dependency `"Install claude-bridge[multi-format]"` mesajı vermeli, import-time crash olmamalı
- `mypy src` core ortamda kırılmamalı

**Testler:**
- Küçük PNG fixture
- Küçük text PDF fixture
- Unsupported extension testi
- Path outside workspace testi
- Missing optional dependency testi
- Büyük dosya limit davranışı testi

**Tasarım ilkeleri:**
- Local file güvenlik modeli gevşetilmemeli
- Büyük dosyalar context'i şişirmemeli; pagination ve truncation zorunlu
- İlk sürüm "en geniş format desteği" değil, "sağlam ve güvenli temel" olmalı

---

## 6. Bağımlılık Sıralı İcra Planı

Bazı görevler diğerlerinin ön koşulu. Aşağıdaki sıra bağımlılıkları gözetir:

```text
AŞAMA 1 — İlk Sprint: Bug Fix + Hızlı Kazançlar
├── K1: index_codebase unreachable code fix (EN ACİL)
├── K2: switch_project_root onboarding reset
├── K7: binary ilk N byte kontrolü
├── K8: _audit_tool_call tip daraltma
└── K4: prompt dedup (O1a'dan ÖNCE — yoksa aynı alan iki kere oynanır)

AŞAMA 2 — Yapısal Zemin (3 küçük PR, sıralı)
├── O1a: prompt/meta registration ayrıştır (EN DÜŞÜK RİSK)
├── O1b: file tool wrapper'larını çıkar
├── O1c: shell/workflow registration çıkar
├── O10: test_protocol.py bölme (O1'lerden sonra)
└── O11: paralel test izolasyonu (O10'dan sonra)

AŞAMA 3 — Kolay Feature'lar (paralel, Aşama 2'den bağımsız)
├── K3: _LAST_BRIDGE_CHANGE project-root scoped state (ilk sprintten çıkarıldı, ihtiyaç netleşince)
├── K5: file write line limit
├── K6: move_file + copy_path
└── O12: inline interpreter politikası + implementasyon

AŞAMA 4 — Orta Feature'lar (paralel, Aşama 2'den sonra) 🔄 Kısmen tamamlandı (O9 ✅; O2/O3/O4/O6/O7/O8 kaldı)
├── O2: smart onboarding genişletme
├── O3: read_url tool'u (güvenlik spec'iyle)
├── O4: auto-update (check-only)
├── O6: .gitignore cache
├── O7: selection_reason
├── O8: disk cache boyut kotası
└── O9: client_managed_approval testleri

AŞAMA 5 — Zor Feature'lar (kısmen paralel, kısmen sıralı) 🔄 Kısmen tamamlandı (Z1a ✅; diğerleri kaldı)
│
├── Paralel Grup A: İndeks Performansı
│   ├── Z3: Tree-sitter parser cache
│   └── Z4: _iter_tree_sitter_nodes iterative
│
├── Paralel Grup B: CI / Kalite
│   ├── Z8: cross-platform CI
│   ├── Z9: golden dataset genişletme
│   └── Z10: Python 3.8 Tree-sitter CI
│
├── Multi-Format (fazlı)
│   ├── Z1a: MVP — read_image + read_pdf (bağımsız, hemen başlatılabilir)
│   ├── Z1b: Excel desteği (Z1a'dan sonra)
│   └── Z1c: Gelişmiş multi-format (Z1b'den sonra)
│
├── Bağımsız Zor Görevler
│   └── Z13: feedback mechanism (bağımsız)
│
├── Sıralı Zor Görevler (birbirine bağımlı)
│   ├── Z6: dry_run modu (global config-based; ileride session-scoped olabilir)
│   ├── Z5: self_healing_loop (Z6 üstüne inşa)
│   └── Z7: task_pack (Z5 + Z6 üstüne inşa)
│
└── En Son
    ├── Z11: in-memory execution ⚠️ (önce güvenlik tasarımı şart)
    └── Z12: semantic relevance (opsiyonel, en deneysel)
```

---

## 7. Delegasyon Paketleri (Vibe Coding İçin)

Her paket bağımsız bir AI agent'a verilebilecek şekilde kapsamlandırılmıştır.

### Paket A: İlk Sprint — Temizlik + Hızlı Kazançlar
> **Zorluk:** 🟢 Kolay | **Süre:** 1-1.5 saat | **Risk:** Düşük

**İçerik:** K1, K2, K7, K8, K4

**Sıra önemli:** K1 → K2 → K7 → K8 → K4 (K4 en sonda, O1a'dan hemen önce).

**Açıklama:** Bug fix ve prompt dedup. K4 prompt dedup **O1a'dan önce yapılmalı** — yoksa prompt/meta registration taşınınca aynı alan iki kere oynanır.

**Doğrulama:** `pytest`, `ruff check`, `mypy src`

---

### Paket B1: Prompt/Meta Registration Ayrıştır (PR 1/3) ✅ TAMAMLANDI
> **Zorluk:** 🟡 Orta | **Süre:** 1-2 saat | **Risk:** Düşük | **Durum:** ✅ Tamamlandı (2026-05)

**İçerik:** O1a

**Açıklama:** `server.py`'den en düşük riskli parça. K4 (prompt dedup) bu paketten önce yapılmış olmalı.

**✅ Sonuç:** `meta_tool_server.py` oluşturuldu. 11 meta tool + `register_prompts()` taşındı. 305 test, mypy, ruff temiz.

**Detaylı spec:**
- `meta_tool_server.py` oluştur
- `register_meta_tools(mcp, tool_options, audit_tool_call, ...)` fonksiyonu
- Şu tool'ları taşı: `bridge_status`, `tools_overview`, `get_config`, `set_config_value`, `get_recent_tool_calls`, `session_insights`, `usage_insights`, `workspace_status`, `switch_project_root`, `compact_user_intent`, `prompt_shortcuts`
- `_register_prompts()` fonksiyonunu da taşı
- `server.py`'de sadece import ve çağrı kalsın

**Doğrulama:** 292 testin tamamı geçmeli, `mypy src` temiz, `ruff check .` temiz.

---

### Paket B2: File Tool Wrapper'ları (PR 2/3)
> **Zorluk:** 🟡 Orta | **Süre:** 1-2 saat | **Risk:** Düşük-Orta

**İçerik:** O1b

**Detaylı spec:**
- `file_tool_server.py` oluştur
- `register_file_tools(mcp, tool_options, audit_tool_call, ...)` fonksiyonu
- Taşı: `read_file`, `read_multiple_files`, `list_directory`, `write_file`, `search_in_files`, `patch_file`, `preview_patch`, `undo_last_patch`

**Bağımlılık:** B1'den sonra. **Doğrulama:** 292 test.

---

### Paket B3: Shell/Workflow Registration (PR 3/3)
> **Zorluk:** 🟡 Orta | **Süre:** 1-2 saat | **Risk:** Orta

**İçerik:** O1c

**Detaylı spec:**
- `shell_tool_server.py`: `register_shell_tools(...)` — shell komut tool'ları
- `workflow_tool_server.py`: `register_workflow_tools(...)` — workflow/agent loop tool'ları
- `server.py` registration entrypoint olarak kalsın ve önemli ölçüde küçülsün.
  Kesin satır sayısı kabul kriteri değildir.

**Bağımlılık:** B2'den sonra. **Doğrulama:** 292 test.

---

### Paket C: Test Altyapısı
> **Zorluk:** 🟡 Orta | **Süre:** 3-4 saat | **Risk:** Düşük

**İçerik:** O9, O10, O11

**Detaylı spec:**

1. **O10 — Test split:**
   - `tests/test_file_tools.py`, `tests/test_shell_tools.py`, `tests/test_meta_tools.py`, `tests/test_workflow_tools.py`
   - `tests/conftest.py`: shared fixture'lar

2. **O11 — Test izolasyonu:**
   - `conftest.py`'ye `autouse` fixture: her testten sonra state reset
   - VEYA: xdist kullanma politikası

3. **O9 — Approval testleri:**
   - `test_client_managed_approval_with_mock_handler`
   - Mock `request_approval` ile `client_managed_approval=True`

**Bağımlılık:** B paketlerinden sonra.

---

### Paket D: Yeni Tool'lar
> **Zorluk:** 🟢-🟡 | **Süre:** 2-3 saat | **Risk:** Düşük

**İçerik:** K5, K6, O12

**Detaylı spec:**

1. **K5 — File write line limit:**
   ```python
   async def write_file(path: str, content: str, ..., max_lines: int = 500) -> str:
       lines = content.split("\n")
       if len(lines) > max_lines:
           return _json_response(True,  # ok=True, yazma başarılı; bloklama yok
               f"Content written ({len(lines)} lines, max_lines={max_lines}). "
               "Consider patch_file for targeted edits next time.",
               details={"line_count": len(lines), "max_lines": max_lines,
                        "warning": "content_exceeds_line_limit",
                        "suggestion": "Use patch_file or increase max_lines"})
   ```

2. **K6 — `move_file`:** `resolve_path` + `sensitive_path_reason` + `shutil.move` + audit. Bonus: `copy_path`.

3. **O12 — Inline interpreter:** `_INLINE_INTERPRETER_FLAGS` set'i → `blocked_command_reason()`. `python3 -c` izinli kalsın.

---

### Paket E: UX Paketi
> **Zorluk:** 🟡 Orta | **Süre:** 4-6 saat | **Risk:** Düşük-Orta

**İçerik:** O2, O3, O4, O6, O7, O8

**Detaylı spec:**

1. **O2 — Smart onboarding:** `_ONBOARDING_TRIGGER_CALLS` → `{1, 3, 5, 8, 12}`, 6 aşama.

2. **O3 — `read_url` (güvenlik spec'iyle):**
   - Ayrı tool, `read_file`'a dokunma
   - Güvenlik limitleri: **sadece http/https**, timeout=10sn, max_bytes=1MB, redirect limit=5
   - Content-Type kontrolü: sadece `text/*` kabul et, binary reddet
   - Audit'te **URL + hash/log summary** (tam içerik değil)
   - `urllib` (stdlib) ile başla, opsiyonel `httpx`

3. **O4 — Auto-update (check-only):** Mevcut sürüm, PyPI son sürüm, önerilen komut, changelog. `--apply` yok.

4. **O6 — .gitignore cache:** `{path: (mtime, patterns)}`.

5. **O7 — selection_reason:** `{path_match: [...], function_match: [...], class_match: [...], ...}`.

6. **O8 — Disk cache kotası:** Toplam ~50MB limit.

---

### Paket F: Multi-Format MVP
> **Zorluk:** 🔴 Zor | **Süre:** 1-2 gün | **Risk:** Orta
> **DesktopCommanderMCP'ye yaklaşma potansiyeli:** EN YÜKSEK.
> Z1a tek başına feature-parity sağlamaz; Z1b/Z1c ile geçme iddiası güçlenir.

**İçerik:** Z1a

**Özet:** `multi_format.py`, `[multi-format]` extras (Pillow + PyPDF2), `read_image` + `read_pdf`.
Detay: [Z1a Detaylı Spec](#z1a-detaylı-spec-multi-format-mvp) bölümünde.

---

### Paket F2: Excel Desteği
> **Zorluk:** 🔴 Zor | **Süre:** 1 gün | **Risk:** Düşük-Orta

**İçerik:** Z1b — `read_excel`, `openpyxl`, sheet/range/pagination.

**Bağımlılık:** F'den sonra.

---

### Paket G: İndeks Performansı
> **Zorluk:** 🔴 Zor | **Süre:** 1-2 gün | **Risk:** Orta

**İçerik:** Z3, Z4

**Detaylı spec:**

1. **Z3 — Tree-sitter parser cache:**
   ```python
   from functools import lru_cache
   @lru_cache(maxsize=16)
   def _load_tree_sitter_parser(language: str): ...
   ```

2. **Z4 — Iterative AST traversal:**
   ```python
   def _iter_tree_sitter_nodes(node):
       stack = [node]
       while stack:
           current = stack.pop()
           yield current
           stack.extend(reversed(current.children))
   ```

---

### Paket H: Agent Loop Ürünleştirme
> **Zorluk:** 🔴 Zor | **Süre:** 2-4 gün | **Risk:** Yüksek

**İçerik:** Z6, Z5, Z7 (sıralı)

**Detaylı spec:**

1. **Z6 — Dry-run (global config-based):**
   - `set_config_value(key="dry_run", value=true)`
   - Tüm destructive tool'lar simülasyon modunda
   - **Not:** Global config tüm session'ları etkiler. MCP stdio'da sorun yok. İleride multi-client → session-scoped dry_run.

2. **Z5 — Self-healing loop:** Validation fail → stderr analizi → hedefli patch → tekrar valide.

3. **Z7 — Task pack:** JSON görev zinciri, `$prev` referans, validation gate.

---

### Paket I: CI / Kalite Altyapısı
> **Zorluk:** 🔴 Zor | **Süre:** 1-2 gün | **Risk:** Düşük

**İçerik:** Z8, Z9, Z10

- **Z8:** Linux + Windows smoke test
- **Z9:** Java, Ruby, monorepo golden dataset
- **Z10:** Python 3.8 + treesitter CI job

---

### Paket J: Gelişmiş Feature'lar (En Son)
> **Zorluk:** 🔴 Zor | **Süre:** 2-4 gün | **Risk:** Değişken

**İçerik:** Z11, Z12, Z13

**Önem sırası:** Z13 (feedback) → Z12 (semantic) → Z11 (in-memory execution, en son, önce güvenlik tasarımı şart).

1. **Z13 — Feedback:** `send_feedback(rating, comment, include_session=True)`. Audit log iliştir.

2. **Z12 — Semantic relevance:** `[semantic]` extras, embedding tabanlı scoring. En deneysel.

3. **Z11 — In-memory execution ⚠️:**
   - **Security design required.** "DC'de var" diye erkene çekilmemeli.
   - `[sandbox]` extras, timeout, memory limit, import whitelist
   - Ayrı güvenlik tasarım dokümanı yazıldıktan sonra implemente edilmeli

---

## 8. DesktopCommanderMCP'yi Geçme Stratejisi

DC'nin kazandığı her alan için karşı hamle:

| DC'nin Üstün Olduğu Alan | Nasıl Geçeriz? | Hangi Görev? | Zorluk |
|--------------------------|----------------|-------------|--------|
| **Multi-format** | Z1a→Z1b→Z1c fazlı. `[multi-format]` extras. | Z1a | 🔴 |
| **Onboarding UX** | DC'nin multi-message modeli + proje tipine özel öneriler | O2 | 🟡 |
| **Auto-update** | Check-only başla, `--apply` sonradan | O4 | 🟡 |
| **URL support** | Ayrı `read_url` tool'u, kendi güvenlik modeliyle | O3 | 🟡 |
| **`move_file`** | Ekle + bonus `copy_path` (DC'de yok) | K6 | 🟢 |
| **`force_terminate`** | `kill_process`'e `force=True` parametresi | K6 yanına | 🟢 |
| **Feedback** | `send_feedback` + oturum audit log'u iliştir | Z13 | 🔴 |
| **File write line limit** | `write_file`'a `max_lines`, bloklamaz, warning | K5 | 🟢 |
| **In-memory execution** | ⚠️ En son, önce güvenlik tasarımı | Z11 | 🔴 |

---

## 9. Değiştirilmemesi Gerekenler

| Ne? | Neden? |
|-----|--------|
| **`shell=False` kullanımı** | `subprocess.run(..., shell=False)`. Asla `shell=True`'a çevirme. |
| **Fail-closed approval** | Varsayılan reddet. `auto_approve=True` sadece power-user preset'inde. |
| **Path sınırları** | `resolve_path()` → `is_within_root`. Gevşetme. |
| **Kara liste modeli** | `blocked_command_reason()`. Yeni pattern eklenebilir, mevcutlar çıkarılmamalı. |
| **JSON response formatı** | `{ok, message, details, code}`. Değiştirme. |
| **Audit logging** | Hash'li, telemetrili, gizli bilgi sızdırmaz. |
| **Modüler mimari** | `config.py`, `audit.py`, `relevance.py` sorumluluk sınırları. |
| **Test disiplini** | 292 test, temiz lint/mypy. Yeni kod testle gelsin. |
| **Python 3.8+ uyumluluğu** | `from __future__ import annotations`. |
| **Opsiyonel dependency'ler** | `[smart]`, `[treesitter]`, `[multi-format]`, `[sandbox]`, `[semantic]` — `try/except ImportError`. |
| **`allowed_roots()` defensive copy** | `config.py#L162` lock içinde `list()` döndürüyor. **Değiştirme.** Düşük değerli, riskli "optimizasyon". |

---

## 10. Tasarım Kararları

### 1. Inline interpreter komutları (O12)

**Karar:** Seçenek B. `_INLINE_INTERPRETER_FLAGS = {"perl -e", "ruby -e", "node -e", "php -r", "lua -e"}` → `blocked_command_reason()`. `python3 -c` izinli kalsın (backward compat).

### 2. Python 3.8 desteği (Z10)

**Karar:** Önce CI'da dene. Çalışmazsa minimum 3.9'a çık.

### 3. Dry-run implementasyonu (Z6)

**Karar:** Global dry-run modu → `set_config_value(key="dry_run", value=true)`. Her tool'a ayrı parametre eklenmeyecek. **İleride multi-client olursa session-scoped dry_run gerekebilir.**

### 4. Multi-format fazlama (Z1)

**Karar:** Z1a MVP (image+PDF) → Z1b Excel → Z1c Gelişmiş. İlk dependency'ler hafif: Pillow + PyPDF2.

### 5. `read_url` vs `read_file` (O3)

**Karar:** Ayrı `read_url` tool'u. Güvenlik: sadece http/https, timeout 10sn, max 1MB, redirect limit 5, content-type text/*, audit'te URL hash.

### 6. Auto-update kapsamı (O4)

**Karar:** Check-only. Mevcut/PyPI/changelog göster, yükleme yapma. `--apply` sonradan.

### 7. `state.py` merkezi lock modülü

**Karar:** Yapma. MCP stdio single-thread, sorun yok, erken soyutlama. Sadece
`_LAST_BRIDGE_CHANGE` için project-root scoped state yeterli (K3).

### 8. `allowed_roots()` optimizasyonu

**Karar:** Yapma. `config.py#L162`'deki lock-içi defensive copy doğru. Düşük değerli, riskli değişiklik.

---

## Özet Metrikler

| Zorluk | Görev Sayısı | Tahmini Süre | Paketler |
|--------|-------------|-------------|----------|
| 🟢 Kolay | 8 | 1.5-2.5 saat | A |
| 🟡 Orta | 13 | 13-18 saat | B1, B2, B3, C, D, E |
| 🔴 Zor | 12 | 8-15 gün | F, F2, G, H, I, J |
| **Toplam** | **33** | **~10-18 gün** | **12 paket** |

**İlk sprint (bug fix + hızlı kazançlar):**
1. K1: `index_codebase` bug fix
2. K2: `switch_project_root` onboarding reset
3. K7: binary ilk N byte
4. K8: `_audit_tool_call` tip daraltma
5. **K4: prompt dedup** (O1a'dan önce şart)

**Ardından:**
6. B1: Prompt/meta registration ayrıştır
7. B2: File tool wrapper'ları
8. B3: Shell/workflow registration
9. F: Multi-Format MVP ← DC'ye yaklaştığımız an; Z1b/Z1c ile geçme iddiası güçlenir

---

## 11. AI Agent Handoff ve Entegrasyon

Bu bölüm, planın farklı AI modellerine bölünerek uygulanması için takip ve
entegrasyon kurallarını tanımlar. Amaç token israfını, çakışan patch'leri ve
paket dışı refactor riskini azaltmaktır.

### 11.1 Handoff Status

| Paket | Zorluk | Önerilen model | Durum | Branch/PR | Merge sırası | Not |
|---|---|---|---|---|---|---|---|
| Paket A — İlk Sprint | Kolay | Low / fast model | Merged | main | 1 | K1(no issue), K2✅, K7🔄(pre-filter var, tam okuma kaldı), K8(no issue), K4✅. |
| Paket B1 — Prompt/Meta Registration | Orta | Medium model | Merged | main | 2 | meta_tool_server.py (706 satır), 11 meta tool + register_prompts. |
| Paket B2 — File Tool Wrapper'ları | Orta | Medium model | Merged | main | 3 | file_tool_server.py (294 satır), 10 tool. |
| Paket B3 — Shell/Workflow Registration | Orta | Medium model | Merged | main | 4 | shell_tool_server.py (189 satır), workflow_tool_server.py (396 satır). |
| Paket C — Test Altyapısı | Orta | Medium model | In progress |  | 7 | O9✅ (client_managed_approval testi var), O10❌, O11❌. |
| Paket D — Yeni Tool'lar | Kolay-Orta | Medium model | Merged | main | 5 | K5✅(max_lines var), K6(ek dosyadan), move_file✅, copy_path✅, O12✅. |
| Paket E — UX Paketi | Orta | Medium model | In progress |  | 6 | O2/O3/O4/O6/O7/O8 hiçbiri yapılmadı. Güvenlik sınırları korunmalı. |
| Paket F — Multi-Format MVP | Zor | High model | Merged | main | 8 | Z1a✅ (multi_format.py, read_image+read_pdf MCP surface'da). |
| Paket F2 — Excel | Zor | High model | Not started |  | 9 | read_excel yok, openpyxl dependency gerekiyor. |
| Paket G — İndeks Performansı | Zor | High model | Not started |  | 10 | Z3/Z4. Benchmark ile doğrulanmalı. |
| Paket H — Agent Loop | Zor | High model | Not started |  | 11 | Z6 → Z5 → Z7 sıralı. |
| Paket I — CI / Kalite | Zor | High model | Not started |  | 12 | Cross-platform dikkatli ele alınmalı. |
| Paket J — Gelişmiş Feature'lar | Zor | High model | Not started |  | 13 | Z11 en son; önce security design şart. |

Durum değerleri:

- `Not started`: Henüz kodlatılmadı.
- `In progress`: Bir AI agent üzerinde çalışıyor.
- `Ready for review`: Patch geldi, henüz merge edilmedi.
- `Merged`: Merge edildi ve doğrulandı.
- `Blocked`: Çakışma, test hatası veya tasarım kararı bekliyor.

### 11.2 Entegrasyon Sırası

Önerilen merge sırası:

1. Paket A
2. Paket B1
3. Paket B2
4. Paket B3
5. Paket D
6. Paket E
7. Paket C
8. Paket F
9. Paket F2
10. Paket G
11. Paket H
12. Paket I
13. Paket J

Önemli notlar:

- B1, B2, B3 paralel kodlanabilir ama **sırayla merge edilmelidir**.
- B1/B2/B3 `server.py` üzerinde çalışacağı için çakışma ihtimali yüksektir.
- Paket D ve E de `server.py`, `file_tools.py`, `indexing.py` ve `onboarding.py`
  üzerinde değişiklik yapabilir; B paketleriyle aynı anda merge edilmemelidir.
- Paket F multi-format bağımsız görünebilir ama tool registration nedeniyle
  B paketlerinden sonra alınması daha güvenlidir.
- Paket J içindeki Z11, yalnızca ayrı güvenlik tasarım dokümanı yazıldıktan sonra
  uygulanmalıdır.

### 11.3 Merge Öncesi Kontrol Listesi

Her patch veya PR için:

- Paket kapsamı dışına çıkılmış mı?
- Güvenlik modeli gevşetilmiş mi?
- `shell=True`, path boundary bypass, approval bypass veya destructive komut
  gevşetmesi var mı?
- Opsiyonel dependency import-time crash yaratıyor mu?
- `mypy src` core ortamda temiz mi?
- Yeni tool eklenmişse audit log'a bağlanmış mı?
- Yeni destructive tool eklenmişse approval akışı korunmuş mu?
- JSON response formatı `{ok, message, details, code}` ile uyumlu mu?
- Yeni feature için hedefli test var mı?
- README/docs/task plan gerekiyorsa güncellenmiş mi?

Zorunlu doğrulama:

```bash
ruff check .
mypy src
pytest
```

Paket bazlı ek doğrulamalar:

- Paket F/F2: opsiyonel dependency yokken graceful error testi, dependency varken
  hedef testler.
- Paket G: benchmark önce/sonra karşılaştırması.
- Paket H: dry-run ve destructive tool davranışı için negatif testler.
- Paket I: GitHub Actions matrix sonuçları.

### 11.4 Bu Sohbette Alınan Kararlar

- İşler düşük, orta ve yüksek modele göre bölündü.
- Düşük/fast modele yalnızca Paket A verilecek.
- Orta modele B1, B2, B3, D ve E paketleri ayrı ayrı verilecek.
- Yüksek modele F ve sonraki zor paketler verilecek.
- B1/B2/B3 aynı anda merge edilmeyecek; sırayla entegre edilecek.
- Yeni kod yazmaya başlamadan önce dış agent'ların patch'leri beklenecek.
- Bu aşamada ana rol entegrasyon, review ve doğrulama olacak.
- Plan dokümanı uygulama emri değil, koordinasyon kaynağıdır; her agent sadece
  kendisine verilen paketi uygulamalıdır.

### 11.5 Sonraki Strateji

Kısa vadede:

1. Devam eden AI agent çıktıları beklenir.
2. Gelen ilk patch Paket A ise önce o incelenir.
3. Paket A temiz merge edilmeden B1 merge edilmez.
4. Her merge sonrası test/lint/type kapıları çalıştırılır.
5. `merged-execution-plan.md` içindeki Handoff Status tablosu güncellenir.

Orta vadede:

1. B1/B2/B3 ile `server.py` registration yapısı sadeleştirilir.
2. Paket D/E ile DC'ye görünen feature paritesi artırılır.
3. Paket F ile multi-format MVP alınır.

Uzun vadede:

1. Z1b/Z1c ile multi-format genişletilir.
2. Z6/Z5/Z7 ile workflow/agent loop ürünleştirilir.
3. Z8/Z9/Z10 ile CI ve kalite kapıları güçlendirilir.
4. Z11 ancak ayrı security design sonrası ele alınır.

### 11.6 Entegrasyonda Dikkat Edilecek Dosyalar

Çakışma riski yüksek dosyalar:

- `src/claude_bridge/server.py`
- `src/claude_bridge/file_tools.py`
- `src/claude_bridge/shell_tools.py`
- `src/claude_bridge/workflow_tools.py`
- `src/claude_bridge/indexing.py`
- `src/claude_bridge/workflow_presets.py`
- `tests/test_protocol.py`

Bu dosyalarda gelen patch'ler özellikle dikkatle incelenmelidir. Aynı dosyada birden
fazla agent değişiklik yaptıysa önce daha küçük ve daha temel paket merge edilmeli,
diğer patch sonrasında rebase/yeniden uygulanmalıdır.
