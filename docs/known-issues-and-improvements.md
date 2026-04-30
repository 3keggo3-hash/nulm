# Claude Bridge — Bilinen Eksiklikler ve İyileştirme Planı

Bu doküman, kod incelemeleri ve test analizleri sonucunda tespit edilen eksiklikleri ve çözüm önerilerini içerir.

---

## Yüksek Öncelik

### 1. Shell kara liste bypass vektörleri

**Mevcut durum:** `shlex.split` + token bazlı analiz var ama sadece isim bazlı kontrol yapılıyor.

**Eksik vektörler:**
- `env python3`, `env bash` gibi indirection
- `fish`, `ksh`, `tcsh`, `elvish`, `nushell` interactive shell'leri listede yok
- Tam path ile çağrı: `/usr/bin/bash`, `/usr/local/bin/fish`
- `python3 -c 'import os; os.system("bash")'` inline komutlar

**Çözüm önerisi:**
- `_INTERACTIVE_COMMANDS` listesine `fish`, `ksh`, `tcsh`, `elvish`, `nushell` ekle
- `analyze_shell_command`'a ilk token'ın basename'ini çıkaran normalizasyon ekle (tam path → basename)
- `env` prefix'i için özel kontrol: `env <shell>` pattern'ini tespit et

**Etkilenecek dosyalar:** `src/claude_bridge/shell_tools.py`, `tests/test_security.py`

### 2. Output truncation semantik bütünlüğü

**Mevcut durum:** `_MAX_SHELL_OUTPUT_CHARS = 12000` ile kesiliyor, `[truncated X chars]` mesajı var ama LLM'in buna dikkat etmesi garanti değil.

**Risk:** Model kesik çıktıyı tam sanıp yanlış karar verebilir.

**Çözüm önerisi:**
- Truncation sonrası output'u her zaman `TRUNCATED` ile işaretle
- Tool description'larından zaten "large output may be truncated" mesajı var ama Claude'a yönlendirici description'ı güçlendir
- İsteğe bağlı: truncation sonrası tail/offset kullanımı öneren bir metadata alanı ekle

**Etkilenecek dosyalar:** `src/claude_bridge/shell_tools.py`

---

## Orta Öncelik

### 3. Global state lock tutarsızlığı

**Mevcut durum:** `file_tools.py`'de `_LAST_BRIDGE_CHANGE` `threading.Lock()`, `config.py`'de `_CONFIG` `threading.RLock()` kullanıyor. Koordinasyonsuz.

**Risk:** Çok session kullanımında race condition potansiyeli.

**Çözüm önerisi:**
- Tek bir merkezi lock modülü oluştur (`src/claude_bridge/state.py`)
- Tüm global mutable state bu modülden yönetilsin
- Ya da: şu an single-threaded MCP stdio akışında bu pratikte sorun yaratmıyor; belgele ve izle

**Etkilenecek dosyalar:** `src/claude_bridge/tool_utils.py` veya yeni `state.py`

### 4. server.py God Object eğilimi

**Mevcut durum:** `server.py` ~1060 satır, tüm MCP tool registration tek dosyada.

**Çözüm önerisi:**
- Tool'ları kategoriye göre ayır: `file_server.py`, `shell_server.py`, `meta_server.py`, `workflow_server.py`
- Her modül kendi tool'larını `mcp` instance'ına kaydetsin
- `server.py` sadece `mcp = FastMCP(...)` ve `run_mcp_server()` içersin

**Etkilenecek dosyalar:** `src/claude_bridge/server.py`, `src/claude_bridge/mcp_server.py`

### 5. Disk cache boyut kotası

**Mevcut durum:** `_prune_workflow_disk_cache` sadece dosya sayısını (64) sınırlandırıyor, boyut bilmiyor.

**Çözüm önerisi:**
- Cache dosyaları için toplam boyut limiti ekle (örn. 50MB)
- En eski/eksik dosyaları temizle
- Her cache yazımında kontrol

**Etkilenecek dosyalar:** `src/claude_bridge/workflow_tools.py`

### 6. client_managed_approval=True test eksikliği

**Mevcut durum:** `auto_approve=False, client_managed_approval=False` test ediliyor ama gerçek `client_managed_approval=True` akışı mock ile test edilmemiş.

**Çözüm önerisi:**
- Mock approval handler ile `client_managed_approval=True` senaryosunu test et
- CLI ve MCP seviyesinde doğrulama

**Etkilenecek dosyalar:** `tests/test_security.py`, `tests/test_protocol.py`

---

## Düşük Öncelik

### 7. Python 3.8 tree-sitter uyumluluğu

**Mevcut durum:** `requires-python = ">=3.8"` ama `[treesitter]` extras'ı 3.8'de test edilmemiş.

**Çözüm önerisi:**
- CI matrisine Python 3.8 ekle (treesitter optional)
- Ya da: minimum Python sürümünü 3.9'a çıkar (zaten `from __future__ import annotations` kullanılıyor)

### 8. test_protocol.py büyüklüğü

**Mevcut durum:** 2118 satır, tek dosyada tüm MCP tool testleri.

**Çözüm önerisi:**
- Kategoriye göre böl: `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`, `test_workflow_tools.py`
- Shared fixtures `conftest.py`'de

### 9. Parallel test izolasyonu

**Mevcut durum:** Global state (mcp_server.set_config) paralel testte (pytest-xdist) problem yaratır.

**Çözüm önerisi:**
- Fixture'lar her testten sonra state'i reset etsin
- Ya da: xdist kullanmama politikası belgelenmiş olsun

---

## Çözüldü / Kısmen Çözüldü

- **power-user auto_approve riski** → Audit logging (Paket 2) ile kısmen çözüldü
- **Python 3.8 annotations** → `from __future__ import annotations` ile çözüldü
- **Async test dekoratörü eksikliği** → `asyncio_mode = "auto"` pyproject.toml'da mevcut, sorun yok

---

## Kaynaklar

- Claude Code kod incelemesi (2026-04-29)
- DesktopCommanderMCP karşılaştırma analizi
