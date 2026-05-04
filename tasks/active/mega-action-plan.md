# Claude Bridge — Mega Konsolide Aksiyon Planı

> **Oluşturma:** 2026-05-03
> **Kapsam:** Güvenlik hardening, build/devops, token optimizasyonu, test kapsamı, ürün/ekosistem, meta-agent katmanı
> **Kaynaklar:** `tasks/active/security-layer-execution-plan.md`, `tasks/active/doctor-and-competitive-analysis.md`, `docs/merged-execution-plan.md`, `docs/roadmap.md`, `docs/known-issues-and-improvements.md`, `docs/competitive-development-plan.md`, `docs/performance-and-completion-audit.md`
> **Tahmini süre:** 7-9 hafta (paralel çalışabilir)

---

## Bölüm 1: P0 — Acil Güvenlik + Build (3-5 gün)

> **Kaynak:** Security agent raporu (C1-C4), `docs/known-issues-and-improvements.md` #1

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P0.1 | `python3 -c` bypass kapat | `shell_tools.py` | `python -c` ve `python3 -c` komutlarını `blocked_command_reason`'a inline interpreter olarak ekle (arbitrary code execution) | 4 saat |
| P0.2 | `command`/`exec`/`builtin` bypass kapat | `shell_tools.py:275-297` | `_interactive_target()`'a shell builtin prefix strip ekle | 2 saat |
| P0.3 | rg `--` flag injection kapat | `file_tools.py:280-287` | `_run_ripgrep_search()` query önüne `--` ekle | 1 saat |
| P0.4 | `$0` fork bomb varyantı kapat | `shell_tools.py:51-54` | `_FORK_BOMB_RE`'ye `$0` ve nested pattern ekle | 1 saat |
| P0.5 | AI evaluator ham veri sızdırma kapat | `ai_evaluator.py:341-343` | `EvaluationRequest` prompt'undan `content`/`search`/`replace`/`command`'ı `_mask_secrets` ile maskele veya çıkar | 3 saat |
| P0.6 | Build backend fix | `pyproject.toml:3` | `setuptools.backends.legacy` → `setuptools.build_meta` | 15 dk |
| P0.7 | release-gate.sh fix | `scripts/release-gate.sh:11-14` | Global `claude-bridge` bağımlılığını kaldır | 1 saat |

---

## Bölüm 2: P1 — Yüksek Öncelik (1 hafta)

> **Kaynak:** Security agent raporu (H1-H7), `docs/known-issues-and-improvements.md` #1, #5, #6

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P1.1 | Shell whitelist mode | `shell_tools.py`, `guard_policy.py` | Varsayılan DENY + izin verilen komutlar listesi. `.claude-bridge-guard.json`'da `allowed_shell_commands` | 3 gün |
| P1.2 | `.git` dizin tam koruması | `tool_utils.py:128-135` | `sensitive_path_reason`'da `.git/**` hepsini engelle | 4 saat |
| P1.3 | `tee`/`pv` device yazma engeli | `shell_tools.py` | `tee /dev/sd*` gibi komutları engelle | 4 saat |
| P1.4 | Custom secret pattern masking | `tool_utils.py:163-169` | `_mask_secrets`'e guard policy custom pattern'lerini dahil et | 4 saat |
| P1.5 | `patch_file` symlink check | `file_tools.py:1702-1710` | `write_file` ile aynı `is_symlink()` kontrolü | 1 saat |
| P1.6 | Python >=3.10 + CI matrisi | `.github/workflows/ci.yml`, `pyproject.toml` | `requires-python>=3.10`, matris 3.10-3.13, macOS runner | 3 saat |
| P1.7 | PyPI publish workflow | `.github/workflows/publish.yml` | Tag push → build → twine → PyPI (OIDC) | 4 saat |

---

## Bölüm 3: P2 — Token Kullanımı Optimizasyonu (1 gün)

> **Kaynak:** Architecture agent raporu, `docs/merged-execution-plan.md`

| # | Görev | Dosya | Değişiklik | Etki |
|---|-------|-------|-----------|------|
| T1 | Response kısaltma | `tool_utils.py:63-100` | `details`'te sadece gerekli alanları tut, `null` değerleri at | ~%30 azalma |
| T2 | File read limit | `file_tools.py` | `_MAX_READ_FILE_LINES` 200 → 50 | ~%75 azalma |
| T3 | Shell output limit | `shell_tools.py:78` | `_MAX_SHELL_OUTPUT_CHARS` 12K → 2K | ~%83 azalma |
| T4 | Search sonuç limiti | `file_tools.py` | `search_in_files` varsayılan `limit` 50 → 20 | ~%60 azalma |
| T5 | AI evaluator prompt kısaltma | `ai_evaluator.py:341-343` | `content`/`command` → `[_MASKED_]` | ~%50 azalma |
| T6 | Audit record trim | `audit.py` | `result_summary` 500 karakter sınırı | ~%20 azalma |

---

## Bölüm 4: P3 — Test Kapsamı (1 hafta)

> **Kaynak:** QA agent raporu, `docs/known-issues-and-improvements.md` #6, #8, #9

| # | Görev | Test Dosyası | Kapsam | Tahmini |
|---|-------|-------------|--------|---------|
| P3.1 | `workflow_tools.py` | `tests/test_workflow_tools.py` | `detect_project_type`, `suggest_validation_commands`, `build_context_pack`, `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session` | 3 gün |
| P3.2 | `insights.py` | `tests/test_insights.py` | `project_stats`, `todo_scan`, `recent_files`, `language_distribution`, `git_log_summary` | 2 gün |
| P3.3 | `meta_tool_server.py` | `tests/test_meta_tool_server.py` | `get_recent_tool_calls`, `session_insights`, `bridge_status`, `appeal_decision` | 2 gün |
| P3.4 | `indexing.py` derinlemesine | `tests/test_indexing.py` | `extract_symbols` (14 dil), `build_index`, `iter_searchable_files` | 2 gün |
| P3.5 | `config.py` | `tests/test_config.py` | `apply_config` validasyon, `resolve_approval_mode`, thread safety | 1 gün |
| P3.6 | `test_protocol.py` bölme | `tests/` | 2400+ satır → `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`, `test_workflow_tools.py` | 1 gün |

---

## Bölüm 5: P4 — Ürün + Ekosistem (2-3 hafta)

> **Kaynak:** Product agent raporu, Ecosystem agent raporu, `docs/roadmap.md`, `docs/competitive-development-plan.md`

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P4.1 | AI Evaluator cloud provider | `ai_evaluator.py` | Anthropic, OpenAI, Ollama provider implementasyonu | 1 hafta |
| P4.2 | Onboarding sihirbazı | `cli.py` | `claude-bridge init` — interaktif proje dizini, onay modu, allowed roots | 3 gün |
| P4.3 | Trust Score MVP | `trust_score.py` (yeni) | Audit log'dan: deny rate, anomaly frequency, approval rejection trend → basit skor | 3 gün |
| P4.4 | README Quick Start fix | `README.md` | `pipx install` yerine source install veya PyPI publish | 2 saat |
| P4.5 | tasks/active → tasks/done | `tasks/` | Bitmiş taskları taşı, `needs-review.md` güncelle | 1 saat |
| P4.6 | `read_url` tool'u | `url_tools.py` (yeni) | Ayrı tool: `read_file`'a dokunma. http/https, timeout, max 1MB, redirect limit 5 | 1 gün |
| P4.7 | Auto-update (check-only) | `update.py` (yeni), `cli.py` | `claude-bridge update` → mevcut sürüm, PyPI son sürüm, öneri | 4 saat |
| P4.8 | Feedback mechanism | `feedback.py` (yeni) | `send_feedback(rating, comment, include_session=True)` | 4 saat |
| P4.9 | PR açıklaması otomatik yaz | `git_ops.py` | `git diff` çıktısından Claude'a özetlet | 4 saat |

---

## Bölüm 6: P5 — Mevcut Aktif Dokümanlardan Uygulanmamış Task'ler

> **Kaynak:** `tasks/active/doctor-and-competitive-analysis.md`, `docs/roadmap.md`, `docs/merged-execution-plan.md`, `docs/known-issues-and-improvements.md`

### P5.1 — `tasks/active/doctor-and-competitive-analysis.md` Kalanları

| # | Görev | Açıklama | Tahmini |
|---|-------|----------|---------|
| P5.1.1 | Minimal/full extras mock ayrımı | Testlerde minimal ortam ve full extras davranışını mock ile ayır | 4 saat |
| P5.1.2 | CI validation sırası dokümantasyonu | CI için önerilen validation akışını yaz | 2 saat |
| P5.1.3 | Uygulanabilir fikirleri yeni tasklara böl | Competitive analysis'den çıkan uygulanabilir fikirleri task'lara dönüştür | 2 saat |

### P5.2 — `docs/roadmap.md` Kalanları

| # | Görev | Açıklama | Tahmini |
|---|-------|----------|---------|
| P5.2.1 | macOS dışı platform testi | Linux önce, Windows sonra | 1 gün |
| P5.2.2 | PR açıklaması otomatik yaz | `git diff`'den otomatik PR açıklaması | 4 saat |
| P5.2.3 | Conflict resolution öneri | Git conflict durumunda öneri sunma | 4 saat |
| P5.2.4 | Benchmark sonuçlarını belgele | Gerçek açık kaynak repo örnekleriyle benchmark sonuçları | 4 saat |
| P5.2.5 | Relevans veri seti genişletme | Java, Ruby ve karma mono-repo vakaları ekle | 4 saat |
| P5.2.6 | `find_relevant_files` cache | Sorgu sonucu cache veya token bazlı ön-indeksleme | 1 gün |
| P5.2.7 | Linux çapraz platform doğrulama | İlk uçtan uca Linux doğrulaması | 1 gün |
| P5.2.8 | CI'da Tree-sitter ayrı job | Opsiyonel Tree-sitter bağımlılığı için ayrı CI job | 2 saat |

### P5.3 — `docs/merged-execution-plan.md` Kalanları (Kolay/Orta)

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P5.3.1 | `_LAST_BRIDGE_CHANGE` project-root scoped | `file_tools.py` | Global değişkeni active project root'a göre sakla | 1 saat |
| P5.3.2 | Smart onboarding genişletme | `onboarding.py` | 3 → 6 aşama, proje tipine göre öneri | 4 saat |
| P5.3.3 | `.gitignore` mtime-based cache | `indexing.py` | `read_gitignore_patterns()` her çağrıda disk okuyor, `{path: (mtime, patterns)}` cache | 2 saat |
| P5.3.4 | `selection_reason` | `relevance.py` | `find_relevant_files` sonucunda neden seçildiği bilgisi | 2 saat |
| P5.3.5 | Disk cache boyut kotası | `indexing.py`, `workflow_tools.py` | Dosya sayısı sınırına ek toplam boyut limiti (~50MB) | 2 saat |
| P5.3.6 | Paralel test izolasyonu | `tests/conftest.py` | `autouse` fixture: her test sonrası state reset | 2 saat |
| P5.3.7 | Binary tespiti: tam okuma kaldır | `indexing.py` | `is_likely_binary` pre-filter var ama sonrasında hala tam dosya okunuyor (`file.read_bytes()`), onu kaldır | 1 saat |

### P5.4 — `docs/merged-execution-plan.md` Kalanları (Zor)

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P5.4.1 | Excel desteği | `multi_format.py` | `read_excel`, `openpyxl` | 3 gün |
| P5.4.2 | Tree-sitter parser cache | `indexing.py` | `_load_tree_sitter_parser()` için `@lru_cache(maxsize=16)` | 2 saat |
| P5.4.3 | `_iter_tree_sitter_nodes` iterative | `indexing.py` | Recursive → stack-based iterative | 4 saat |
| P5.4.4 | `self_healing_loop` | `workflow_tools.py` | Validation fail → stderr analizi → hedefli patch → tekrar valide | 2 gün |
| P5.4.5 | `dry_run` modu | `workflow_tools.py` | Global config-based: `set_config_value(key="dry_run", value=true)` | 1 gün |
| P5.4.6 | `reproducible_task_pack` | `task_pack.py` (yeni) | JSON görev zinciri, `$prev` referans çözümleme | 3 gün |
| P5.4.7 | Cross-platform CI | `.github/workflows/` | Linux + Windows smoke test | 1 gün |
| P5.4.8 | Golden relevance dataset genişletme | `tests/test_relevance_golden.py` | Java, Ruby, monorepo vakaları | 1 gün |
| P5.4.9 | Python 3.8 Tree-sitter CI | CI + test | CI matrisine 3.8 + treesitter ekle | 2 saat |
| P5.4.10 | In-memory code execution | `sandbox.py` (yeni) | **Security design required.** Timeout, memory limit, import whitelist | 1 hafta |
| P5.4.11 | Semantic relevance | `semantic_relevance.py` (yeni) | Embedding tabanlı alternatif scoring | 1 hafta |

### P5.5 — `docs/known-issues-and-improvements.md` Kalanları

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P5.5.1 | Shell kara liste bypass vektörleri | `shell_tools.py` | `env python3`, `env bash` indirection, tam path çağrı, `python3 -c` | 4 saat |
| P5.5.2 | Output truncation semantik bütünlüğü | `shell_tools.py` | `TRUNCATED` ile işaretle, tool description güçlendir | 2 saat |
| P5.5.3 | Global state lock tutarsızlığı | `tool_utils.py` veya `state.py` | Tek merkezi lock modülü veya belgele ve izle | 1 gün |
| P5.5.4 | Disk cache boyut kotası | `workflow_tools.py` | `_prune_workflow_disk_cache` toplam boyut limiti ekle | 2 saat |

### P5.6 — `docs/performance-and-completion-audit.md` Kalanları

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P5.6.1 | Tab completion / shell completion | `cli.py` | Typer yerleşik shell completion aktifleştir | 2 saat |
| P5.6.2 | Terminal bağlantı yavaşlığı optimizasyonu | `server.py` | Startup latency — lazy import ile %40-60 hızlanma | 1 gün |
| P5.6.3 | İndeksleme performansı | `indexing.py` | Disk I/O ve dosya sistemi etkisi optimizasyonu | 2 gün |
| P5.6.4 | Relevance sorgu performansı | `relevance.py` | Cache veya token bazlı ön-indeksleme | 1 gün |

### P5.7 — Kod İncelemesinde Tespit Edilen Yeni Eksikler

> **Kaynak:** `docs/performance-and-completion-audit.md`, 2026-05-03 kod incelemesi

| # | Görev | Dosya | Açıklama | Tahmini |
|---|-------|-------|----------|---------|
| P5.7.1 | `git rev-parse` repo root cache | `git_ops.py` | Her `git_commit()` çağrısında `git rev-parse --show-toplevel` tekrar çalışıyor, cache'le | 1 saat |
| P5.7.2 | `auto_commit=False` + batch commit | `file_tools.py`, `server.py` | Opsiyonel commit parametresi, `commit_changes` toplu commit tool'u | 3 saat |
| P5.7.3 | Haystacks lowercase pre-compute | `relevance.py` | `item["content"].lower()` her query'de tekrar hesaplanıyor, index sırasında pre-compute et | 1 saat |
| P5.7.4 | MCP-level `autocomplete` tool | `server.py` (yeni tool) | Claude Desktop'ta kısmi girdi önerisi için `autocomplete(partial_input)` | 2 saat |
| P5.7.5 | `.bridgeignore` özel engelleme listesi | `tool_utils.py`, `config.py` | Kullanıcı proje bazlı engelleme kalıpları tanımlayabilsin | 3 saat |
| P5.7.6 | Progress/stderr loglama | `indexing.py` | Uzun işlemlerde (build_index, search) `stderr`'e ilerleme yaz | 2 saat |
| P5.7.7 | Prompt registration lazy | `server.py` | `register_prompts()` modül seviyesinde değil, `run_mcp_server()` içinde çağrılsın | 1 saat |
| P5.7.8 | Shell timeout komut bazlı artırma | `shell_tools.py` | `npm install`, `cargo build` gibi uzun komutlar için timeout otomatik 120sn | 2 saat |
| P5.7.9 | `iter_source_files` stat birleştirme | `indexing.py` | Dosya listesi dönerken stat bilgisini de dön, `build_index` tekrar stat yapmasın | 3 saat |
| P5.7.10 | `git_ops` subprocess birleştirme | `git_ops.py` | `git add` + `git commit` tek subprocess'te birleştir | 1 saat |

---

## Bölüm 7: P6 — Meta-Agent Katmanı (2-3 hafta)

> **Amaç:** AI'nin kendi kendine plan yapması, farklı yaklaşımları denemesi, sonuçları karşılaştırması ve karar vermesi

### Yeni MCP Araçları

| Araç | Parametreler | Açıklama |
|------|-------------|----------|
| `create_plan(goal, steps_json)` | `goal: str`, `steps: list[str]` | `plans/{plan_id}.json` oluştur |
| `execute_step(plan_id, step_id)` | `plan_id: str`, `step_id: int` | Plan adımını çalıştır, state güncelle |
| `get_plan_status(plan_id)` | `plan_id: str` | Plan durumunu ve sonuçları döndür |
| `explore_approaches(problem, count)` | `problem: str`, `count: int` | N farklı yaklaşım üret, `approaches/` altına kaydet |
| `execute_approach(approach_id)` | `approach_id: str` | Yaklaşımı test et, sonuçları kaydet |
| `compare_approaches(approach_ids)` | `approach_ids: list[str]` | Karşılaştırma raporu: test sonuçları, satır sayısı, complexity |
| `self_critique(scope, criteria)` | `scope: str`, `criteria: list[str]` | Kodu review et, bulguları raporla |
| `create_checkpoint(name)` | `name: str` | Git commit + plan state snapshot |
| `restore_checkpoint(name)` | `name: str` | `git checkout` + plan state'i geri yükle |

### Yeni Modüller

| Modül | Dosya | Görev |
|-------|-------|-------|
| Plan Engine | `src/claude_bridge/plan_engine.py` | Plan CRUD, step execution, state persistence |
| Approach Explorer | `src/claude_bridge/approach_explorer.py` | Yaklaşım üretme, karşılaştırma, metrik toplama |
| Self-Critique | `src/claude_bridge/self_critique.py` | AST + regex + test sonuçları analizi (deterministik) |

---

## Paralelleştirilebilir İşler

Aynı anda bağımsız olarak yapılabilir:

- **P0 + P1.6 + P1.7:** Güvenlik + Build/DevOps (farklı dosyalar)
- **P3:** Test yazımı (tümü `tests/` altında, source'a dokunmaz)
- **P4.2 + P4.4:** Onboarding + README (tamamen ayrı)
- **P5.3.x (Kolay/Orta):** Refactor'lar (birbirinden bağımsız modüller)
- **P6:** Meta-agent (yeni dosyalar, mevcut kodu değiştirmez)

---

## Bağımlılık Zinciri

```
P0 (güvenlik) ──> P1.1 (whitelist) ──> P4.1 (AI provider)
P0 (build fix) ──> P1.7 (PyPI) ──> P4.4 (README)
P3 (test) ──> P2 (token) ──> P4 (ürün)
P4.1 (AI provider) ──> P6 (meta-agent)
```

---

## Başarı Kriterleri

Her bölüm tamamlandığında:

- **P0:** `mypy src && ruff check . && pytest` temiz, 7 kritik açık kapatılmış
- **P1:** Shell whitelist çalışır, CI 3.10-3.13 + macOS, PyPI publish workflow hazır
- **P2:** Token kullanımı benchmark'la ölçülür, hedef %50 azalma
- **P3:** 7 yeni test dosyası, her biri >80% coverage, tümü geçiyor
- **P4:** AI provider en az 2'si çalışır, onboarding wizard interaktif, trust score hesaplanır
- **P5:** `merged-execution-plan.md` ve `known-issues-and-improvements.md` checkbox'ları güncellenir
- **P6:** Meta-agent araçları MCP surface'da görünür, örnek plan oluşturulabilir

---

## Notlar

- **Meta-agent derinliği:** Basit versiyon — tek prompt'ta multi-perspective critique. Derin versiyon (her perspektif ayrı call) sonraki iterasyonda.
- **Plan persistence:** JSON dosyaları (`plans/`, `approaches/`) — basit, okunabilir, git-trackable.
- **Scope kontrolü:** Bu plan mevcut değer önerisinden (MCP güvenlik katmanı) sapmaz, genişletir.
- **Aktif dokümanlar:** Bu plan oluşturulduktan sonra `tasks/active/` ve `docs/roadmap.md` güncellenmeli, tamamlanan maddeler işaretlenmeli.

---

*Bu plan `tasks/active/security-layer-execution-plan.md`, `tasks/active/doctor-and-competitive-analysis.md`, `docs/merged-execution-plan.md`, `docs/roadmap.md`, `docs/known-issues-and-improvements.md`, `docs/competitive-development-plan.md`, `docs/performance-and-completion-audit.md` kaynaklarından derlenmiştir.*
