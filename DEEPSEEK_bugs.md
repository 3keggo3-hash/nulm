# DEEPSEEK — Bulunan Hatalar ve Eksiklikler

Bu doküman, proje kodunda tespit edilen hataları, eksiklikleri ve iyileştirme önerilerini içerir.

---

## 1. Kritik Hata: MCP Tool'ları Fonksiyon Parametresi Alamaz

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** MCP (Model Context Protocol) tool'ları sadece JSON-serializable parametreler alabilir. Fonksiyon referansları geçilemez. `server.py`'de aşağıdaki tool'lar fonksiyon parametresi alıyor:

- `run_agent_loop_step` → `patch_file`, `run_shell`, `json_response`
- `run_agent_loop_session` → `run_agent_loop_step`, `json_response`
- `build_context_pack` → `resolve_path`, `find_relevant_files`, `path_from_active_root`, `project_dir`, `infer_project_root`, `iter_searchable_files`, `git_status_snapshot`, `json_response`
- `run_workflow` → `resolve_path`, `read_file`, `list_directory`, `find_relevant_files`, `path_from_active_root`, `project_dir`, `infer_project_root`, `json_response`
- `suggest_validation_commands` → `resolve_path`, `infer_project_root`, `json_response`

**Etki:** Bu tool'lar MCP üzerinden çağrıldığında (Claude Desktop üzerinden) çalışmaz. Testler doğrudan Python fonksiyonlarını çağırdığı için çalışıyor gibi görünüyor. Gerçek kullanımda hata verir.

**Çözüm:** Tool implementasyonlarını `server.py` içinde doğrudan çağırmak, parametre olarak almamak.

---

## 2. Kullanılmayan Fonksiyonlar

**Dosya:** `src/claude_bridge/server.py`

Aşağıdaki fonksiyonlar tanımlanmış ama hiçbir yerde kullanılmıyor:

- `_supplemental_review_targets`
- `_normalize_command_for_safety`
- `_blocked_command_reason`
- `_is_interactive_command`

**Etki:** Gereksiz kod, bakım yükünü artırır.

**Çözüm:** Kullanılmayan fonksiyonları kaldırmak.

---

## 3. `_git_commit` Yeniden Atama Sorunu

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `write_file` ve `patch_file` tool'larında `_file_tools_mod._git_commit = _git_commit` yapılıyor. Bu, her çağrıda yeniden atama yapıyor.

**Etki:** Performans kaybı (küçük) ve kod tekrarı.

**Çözüm:** Modül seviyesinde bir kez atamak.

---

## 4. `_register_prompts()` Modül Seviyesinde Çağrılıyor

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `server.py`'nin sonunda `_register_prompts()` çağrılıyor. Bu, modül import edildiğinde hemen çalışır. Ama `mcp` objesi henüz tam olarak yapılandırılmamış olabilir.

**Etki:** Potansiyel hata.

**Çözüm:** `run_mcp_server()` içinde çağırmak.

---

## 5. DRP İhlali

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `set_config` ve `configure_from_env` fonksiyonları aynı işlemleri yapıyor (`clear_index_cache()` ve `_clear_last_bridge_change()`).

**Etki:** Kod tekrarı.

**Çözüm:** Ortak bir yardımcı fonksiyon oluşturmak.

---

## 6. Type Hints Eksik

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** Bazı fonksiyonlarda tip belirtilmemiş.

**Etki:** Kod okunabilirliği azalır, `mypy` ile kontrol zorlaşır.

**Çözüm:** Eksik type hints eklemek.

---

## 7. Hata Yönetimi Eksik

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `_build_index` çağrıldığında `PermissionError`, `FileNotFoundError`, `NotADirectoryError` yakalanıyor. Ama `OSError` gibi diğer hatalar yakalanmıyor.

**Etki:** Beklenmeyen hatalar kullanıcıya ulaşabilir.

**Çözüm:** Daha kapsamlı hata yönetimi eklemek.

---

## 8. Loglama Yok

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** Hata durumlarında loglama yapılmıyor.

**Etki:** Debugging zorlaşır.

**Çözüm:** `logging` modülü eklemek.

---

## 9. `_INDEX_CACHE` ve `_CONFIG` Re-export Edilmiş

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `from claude_bridge.indexing import _INDEX_CACHE` ve `from claude_bridge.config import _CONFIG` yapılmış ama `# noqa: F401` ile uyarı bastırılmış.

**Etki:** Testlerde kullanılıyor olabilir ama daha iyi bir yaklaşım: testlerde doğrudan `claude_bridge.indexing._INDEX_CACHE` kullanmak.

**Çözüm:** Re-export yerine testlerde doğrudan import yapmak.

---

## 10. Testlerde `time.sleep(0.02)` Kullanımı

**Dosya:** `tests/test_protocol.py`

**Açıklama:** `test_index_codebase_invalidates_cache_when_file_changes` testinde `time.sleep(0.02)` kullanılıyor.

**Etki:** Test süresini uzatır.

**Çözüm:** `os.utime` ile dosya zamanını değiştirmek.

---

## 11. Testlerde MCP Tool Fonksiyon Parametreleri

**Dosya:** `tests/test_protocol.py`

**Açıklama:** Aşağıdaki testler MCP tool'larını fonksiyon parametreleriyle çağırıyor. Bu testler doğrudan Python fonksiyonlarını çağırdığı için çalışıyor gibi görünüyor. Ama gerçek MCP kullanımında çalışmaz.

- `test_workflow_execute_reads_file_for_file_target`
- `test_workflow_execute_reads_godot_supplemental_files_for_gd_target`
- `test_workflow_execute_lists_directory_for_directory_target`
- `test_workflow_execute_reads_python_project_context`
- `test_agent_loop_plan_uses_node_validation_when_package_json_exists`
- `test_build_context_pack_for_python_project`
- `test_build_context_pack_for_node_project`
- `test_build_context_pack_skips_python_files_with_syntax_errors`
- `test_build_context_pack_rejects_missing_target`
- `test_build_context_pack_uses_secondary_allowed_root_context`
- `test_run_workflow_returns_structured_error_for_path_outside_project`
- `test_run_workflow_uses_secondary_allowed_root_project_type`
- `test_suggest_validation_commands_for_python_project`
- `test_suggest_validation_commands_for_rust_project`
- `test_suggest_validation_commands_outside_project_includes_recovery_details`
- `test_suggest_validation_commands_rejects_missing_path`
- `test_unknown_workflow_mode_returns_error`

**Etki:** Bu testler yanlış pozitif sonuç veriyor. Gerçek MCP kullanımında tool'lar çalışmaz.

**Çözüm:** Tool implementasyonlarını düzeltmek (bkz. Madde 1).

---

## 12. `run_agent_loop_session` Tool'unda `steps_json` ve `steps` Parametre Çakışması

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `run_agent_loop_session` tool'u `steps_json` ve `steps` parametrelerini alıyor. İkisi birden verilirse ne olacağı belirsiz.

**Etki:** Beklenmeyen davranış.

**Çözüm:** `_run_agent_loop_session_impl` fonksiyonunda kontrol eklemek.

---

## 13. `find_relevant_files` Sadece Python ve GDScript Destekliyor

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `find_relevant_files` tool'u sadece Python ve GDScript sembollerini arıyor. Diğer diller (JavaScript, TypeScript, Rust) için destek yok.

**Etki:** Çok dilli projelerde kullanışsız.

**Çözüm:** Diğer diller için de sembol çıkarma eklemek.

---

## 14. `patch_file` Tool'u Ambiguous Search Durumunu Test Etmiyor

**Dosya:** `tests/test_protocol.py`

**Açıklama:** `test_patch_ambiguous_search` testi var mı? PROGRESSION.md'de görmüyorum. `patch_file` tool'u `search` metni dosyada birden fazla kez geçiyorsa ne yapacağı test edilmemiş olabilir.

**Etki:** Potansiyel hata.

**Çözüm:** Test eklemek.

---

## 15. `run_shell` Tool'u Tehlikeli Komutları Yeterince Engellemiyor

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `_blocked_command_reason` fonksiyonu var ama `sudo`, `rm -rf /`, `:(){ :|:& };:` gibi tehlikeli komutları engelliyor mu? Testlerde sadece `sudo apt install` test edilmiş.

**Etki:** Güvenlik açığı.

**Çözüm:** Daha kapsamlı engelleme listesi eklemek.

---

## 16. `write_file` Tool'u `create_parents=False` İçin Test Eksik

**Dosya:** `tests/test_protocol.py`

**Açıklama:** `write_file` tool'u `create_parents=False` iken eksik dizinler için hata mesajı dönüyor mu? Testlerde görmüyorum.

**Etki:** Potansiyel hata.

**Çözüm:** Test eklemek.

---

## 17. `index_codebase` Cache Boyutu Sınırlanmamış

**Dosya:** `src/claude_bridge/server.py`

**Açıklama:** `_INDEX_CACHE` cache'inin boyutu sınırlanmamış. Büyük projelerde bellek sorunu yaşanabilir.

**Etki:** Performans sorunu.

**Çözüm:** LRU cache veya boyut sınırlaması eklemek.

---

## 18. PROGRESSION.md'deki Hatalar

**Dosya:** `PROGRESSION.md`

- "doğru formattalar var" → "doğru formatta olduğu doğrulandı"
- V2 maddelerinde `[x]` işaretleri V1'de tamamlandığı için kaldırılmalı
- V3 maddeleri `- [ ]` formatına çevrilmeli
- "Son Güncelleme" bölümündeki test sayısı güncellenmeli
- "Sonraki Adım" bölümü kısaltılmalı
- "Durum Açıklamaları" tablosu kullanılmadığı için kaldırılmalı

---

## 19. Projenin Geleceğini Etkileyebilecek Faktörler

### Olumlu Faktörler

1. **MCP protokolü standartlaşıyor** — Erken uyum avantajı.
2. **Güvenlik odaklı tasarım** — Onay sistemi, path traversal koruması, tehlikeli komut filtreleme.
3. **Test coverage** — 79 test iyi bir başlangıç.
4. **CLI + MCP çift arayüz** — Hem komut satırından hem Claude üzerinden kullanılabilir.
5. **GDScript desteği** — Godot oyun geliştiricileri için niş bir pazar.

### Olumsuz Faktörler / Riskler

1. **MCP Tool'ları fonksiyon parametresi alamaz** — En kritik hata.
2. **Bağımlılık sayısı** — Fazla bağımlılık bakım yükünü artırır.
3. **Python sürümü** — Python 3.10+ gerekiyor olabilir.
4. **Sadece macOS/Linux** — Windows desteği yok.
5. **Rekabet** — Claude Code, Cursor, GitHub Copilot.
6. **Bakım yükü** — Tek geliştirici.
7. **MCP SDK değişiklikleri** — Uyumluluk sorunları.

### Stratejik Öneriler

1. **MCP Tool fonksiyon parametresi sorununu düzelt** — En kritik öncelik.
2. **Topluluk katkısı** — GitHub Issues ve PR şablonları.
3. **CI/CD** — GitHub Actions ile otomatik test ve yayınlama.
4. **Dökümantasyon** — Daha detaylı rehber.
5. **Plugin sistemi** — Üçüncü taraf tool'lar.
6. **Windows desteği** — PowerShell ve cmd uyumluluğu.

---

*Bu doküman DEEPSEEK tarafından oluşturulmuştur. Kodda hiçbir değişiklik yapılmamıştır.*
