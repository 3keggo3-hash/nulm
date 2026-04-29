# Ana Bug: Claude Desktop İlk Mesajda MCP Tool'ları Yüklemez

> **Tarih:** 2026-04-27  
> **Bulganan:** Claude Desktop + claude-bridge MCP entegrasyonunda

---

## Hata Tanımı

Claude Desktop'ta yeni bir sohbet açıldığında, ilk mesaj Claude'a MCP tool'larını (claude-bridge) kullanma imkanı sunmaz. Claude, "Bu dizine doğrudan erişimim yok" gibi yanıtlar verir. İkinci mesajda ise "Used claude-bridge integration, loaded tools" notuyla tool'lar aktif olur ve dosya erişimi çalışır.

Bu, tutarsız bir kullanıcı deneyimi yaratır — aynı sohbetin ilk mesajında erişim yok, ikinci mesajında var.

---

## Semptomlar

```
# 1. mesaj (sohbet başlangıcı):
User: /Users/keremdilker/Desktop/claudey code pathinde kodlarda hata var mı kontrol et
Claude: Bu dizine doğrudan erişimim yok — yerel dosya sisteminize bağlanamam.

# 2. mesaj (aynı sohbet, devamı):
User: /Users/keremdilker/Desktop/claudey code pathinde kaç dosya var
Claude: Used claude-bridge integration, loaded tools
        Root dizinde 13 dosya var (dizinler hariç).
```

---

## Kök Neden Analizi

Bu hata claude-bridge kaynak kodundan değil, **Claude Desktop'ın MCP istemci davranışından** kaynaklanmaktadır. Nedenleri:

### 1. Claude Desktop "System Prompt" Temelli Tool Keşfi

Claude Desktop, MCP sunucusuna ilk mesaj gönderilmeden önce `initialize` ve `tools/list` çağrıları yapar. Ancak tool listesini Claude modeline **sistem prompt'una ekleyip eklememe** kararı Claude Desktop'ın kendi içindeki bir mantıkla verilir:

- Claude Desktop, ilk mesajın içeriğine bakarak "bu mesaj MCP tool gerektiriyor mu" diye karar verir
- Eğer karar veremezse veya ilk mesaj yeterince açık değilse, tool'ları sistem prompt'una eklemez
- Claude, tool listesi olmadan respond verir → "erişimim yok" der
- İkinci mesajda Claude Desktop tool listesini ekler → "loaded tools" görünür

**Kanıt:** İkinci sohbettool'ların yüklendiğini açıkça belirtir: `Used claude-bridge integration, loaded tools`. Bu mesaj Claude Desktop'ın kendi UI katmanından gelir.

### 2. claude-bridge Tarafındaki İlgili Yapı

claude-bridge tarafında MCP sunucusu doğru başlatılır:

- `mcp_server.py:50-51` → `configure_from_env()` + `run_mcp_server()`
- `server.py:118` → `mcp = FastMCP("Claude Bridge")`
- `server.py:578-580` → `mcp.run(transport="stdio")`
- `server.py:583` → `_register_prompts()` modül yüklemesinde çağrılır

Sunucu tarafında bir hata yok. `tools/list` isteği geldiğinde tüm tool'lar doğru şekilde listelenir. Sorun, Claude Desktop'ın bu listeyi ne zaman modele aktardığıdır.

### 3. Neden Bazen İlk Mesajda Çalışır?

Claude Desktop'ın tool keşif stratejisi muhtemelen:
- Mesajda açık bir dosya yolu var mı? (`/Users/.../dosya.py`)
- "oku", "aç", "listele", "çalıştır" gibi eylem kelimeleri var mı?
- Bu kelimeler tool description'larıyla eşleşiyor mu?

İlk mesaj "hata var mı kontrol et" şeklinde belirsiz bir istek içerdiğinde, Claude Desktop tool'ları modele aktarmayı seçmeyebilir. İkinci mesaj "kaç dosya var" gibi daha somut bir istek olduğunda veya sohbet devam ettiğinde tool'lar yüklenir.

---

## Tüm Olası Çözümler ve Değerlendirmeleri

### Çözüm 1: Claude Desktop Project Instructions Kullanımı

**Mekanizma:** Claude Desktop, her sohbetin başında "Project Instructions" olarak adlandırılan bir sistem prompt'u modele gönderir. Bu alana claude-bridge'in tool'larını kullanma talimatı yazılabilir.

**Uygulama:**
1. Claude Desktop > Settings > Developer > Project Instructions'a şunu ekle:
   ```
   Bu projede claude-bridge MCP sunucusu aktif. Kullanıcı dosya, dizin, 
   shell veya kod inceleme isteklerinde claude-bridge tool'larını 
   (read_file, list_directory, run_shell, search_in_files vb.) her zaman kullan.
   Dosya erişimi olmadığını iddia etme — tool'lar her zaman kullanılabilir.
   ```

**Artıları:**
- Claude Desktop her mesajda bu talimatı modele gönderir
- Model tool'ları bilmese bile "erişimim yok" demek yerine tool çağırma eğiliminde olur
- claude-bridge kodunu değiştirmez

**Eksileri:**
- Her proje/kullanıcı için manuel ayar gerektirir
- Claude Desktop'ın tool-routing kararını tamamen kontrol edemez (model yine de tool kullanmayı seçmeyebilir)
- Sistem prompt'u çok uzun olması token tüketimini artırır

**Uygulanabilirlik:** Yüksek. Kullanıcıya önerilecek en pratik çözüm.

---

### Çözüm 2: claude-bridge setup Komutuna System Prompt Çıktısı Ekleme

**Mekanizma:** `claude-bridge setup` komutu, Claude Desktop config'inin yanında bir "Project Instructions" metni de üretir. Bu metni kullanıcı Claude Desktop'a kopyalar.

**Uygulama:**
`cli.py`'de `setup` komutunun çıktısına bir panel daha ekle:
```python
console.print("\n[bold]Claude Desktop Project Instructions:[/bold]")
console.print(
    Panel(
        "Bu projede claude-bridge MCP sunucusu aktif. Dosya, dizin ve "
        "shell isteklerinde claude-bridge tool'larını her zaman kullan.",
        title="Claude Desktop > Settings > Project Instructions",
        border_style="yellow",
    )
)
```

**Artıları:**
- Kurulum akışının bir parçası olur, kullanıcı hatırlamaz
- claude-bridge'in kendi docs'u içinde tutulur
- README ile uyumlu bir akış

**Eksileri:**
- Kullanıcı her seferinde bu metni Claude Desktop'a manuel eklemeli
- Claude Desktop'ın tool-routing davranışını garanti etmez

**Uygulanabilirlik:** Yüksek. Minimum kod değişikliği ile maksimum etki.

---

### Çözüm 3: Claude Desktop Config'e `disabled` Olmayan Tool Metadata Ekleme

**Mekanizma:** FastMCP ile kaydedilen tool'ların description'larını, Claude'un tool-routing kararını etkileyecek şekilde güçlendirme.

**Uygulama:**
`server.py`'deki tool description'larını daha açıklayıcı yap:
```python
# Şu an:
@mcp.tool(description="Read a file inside the configured project directory.")

# Olması gereken:
@mcp.tool(description="Read a file. ALWAYS use this tool when the user asks "
    "about files, code, or project contents. Do NOT say you cannot access files.")
```

**Artıları:**
- Claude modeli tool'ları daha agresif kullanır
- Kod değişikliği minimal
- Otomatik — kullanıcı manuel bir şey yapmaz

**Eksileri:**
- Tool description'ların çok uzun olması API token limitlerine etki edebilir
- Claude Desktop'ın tool-routing'i model seviyesinde değil, client seviyesinde olabilir
- Description değişikliği Claude'un diğer tool kullanım kararlarını da etkiler

**Uygulanabilirlik:** Orta. Deneysel, etkisi belirsiz.

---

### Çözüm 4: MCP Protocol Seviyesinde Tool'ları Gruplama

**Mekanizma:** MCP protokolü `tools/list` yanıtlarında tool gruplamayı destekler. claude-bridge tool'larını bir "file-system" ve "shell" grubu olarak sunarak Claude Desktop'ın routing kararını iyileştirme.

**Uygulama:**
FastMCP'de tool gruplama mekanizması yok. Ancak `server.py:118`'de `mcp = FastMCP("Claude Bridge")` satırında sunucu ismi zaten veriliyor. Claude Desktop bu ismi kullanarak routing yapabilir.

**Artıları:**
- MCP standartlarına uygun
- Client implementasyonuna bağımlı

**Eksileri:**
- FastMCP mevcut tool gruplama API'sini desteklemiyor
- Claude Desktop'ın bu bilgiyi routing'de kullanıp kullanmadığı belirsiz
- Uygulama karmaşıklığı yüksek, etki belirsiz

**Uygulanabilirlik:** Düşük. Pratik değil.

---

### Çözüm 5: Warm-up / Heartbeat Mekanizması

**Mekanizma:** claude-bridge sunucusu başladığında, Claude Desktop'a主动 bir "hazır" mesajı göndererek tool keşfini tetikleme.

**Uygulama:**
MCP protokolü sunucu tarafından istemciye mesaj göndermeyi desteklemez (request-response model). Ancak `initialize` sonrası sunucu bir `notifications/initialized` gönderebilir. Bu zaten yapılıyor.

**Artıları:**
- Standart MCP davranışı

**Eksileri:**
- MCP protokolü sunucudan istemciye tool çağrısı yapılmasına izin vermez
- "Warm-up" mesajı göndermek protokol ihlali
- Claude Desktop zaten initialize ve tools/list çağrısını yapıyor

**Uygulanabilirlik:** Impossible. MCP protokolü buna izin vermez.

---

### Çözüm 6: Claude Desktop Kaynak Kodunu İnceleme / Anthropic'e Bug Raporu

**Mekanizma:** Claude Desktop'ın tool-routing mantığı açık kaynak değil (Electron app). Ancak davranış Anthropic'e bug report olarak raporlanabilir.

**Uygulama:**
- https://github.com/anthropics/claude-code/issues (veya Claude Desktop için uygun kanal)
- Davranış açıkla: "MCP sunucusu configure edilmiş olmasına rağmen, ilk mesajda tool'lar modele aktarılmıyor"

**Artıları:**
- Kök neden Claude Desktop tarafında, doğru yere raporlanır
- Anthropic düzeltirse tüm MCP sunucuları için faydalı olur

**Eksileri:**
- Düzeltme garantisi yok
- Zaman alabilir
- claude-bridge'in kontrolü dışında

**Uygulanabilirlik:** Orta. Uzun vadeli çözüm, kısa vadede işe yaramaz.

---

### Çözüm 7: Kullanıcı Tarafında İlk Mesaj Formatı Standardizasyonu

**Mekanizma:** claude-bridge README'sinde ve setup çıktısında, ilk mesajın belirli bir formatta yazılması gerektiğini belirtme.

**Uygulama:**
README'ye ekle:
```markdown
## İlk Mesaj İpucu
Claude Desktop bazen ilk mesajda MCP tool'larını aktif etmeyebilir.
İlk mesajınızda dosya yolu veya tool adı kullanın:

- "src/claude_bridge/server.py dosyasını oku"
- "list_directory ile proje yapısını göster"
- "run_shell pytest"

Claude "erişimim yok" derse, aynı mesajı tekrar göndermeniz yeterli.
```

**Artıları:**
- Sıfır kod değişikliği
- Kullanıcı anında çözebilir
- Belgelendirme iyileştirmesi

**Eksileri:**
- Kullanıcı docs'u okumadan deneyecektir
- UX problemi, teknik çözüm değil

**Uygulanabilirlik:** Yüksek. En hızlı uygulanabilir çözüm.

---

### Çözüm 8: claude-bridge'in Kendi Tool Routing Yanıtı Üretmesi

**Mekanizma:** claude-bridge, Claude Desktop'tan gelen mesajları intercept edip, dosya/klasör/shell ile ilgili kelimeler içeriyorsa otomatik olarak ilgili tool'u çağırma. Bu, bir "proxy" veya "middleware" katmanı anlamına gelir.

**Uygulama:**
MCP stdio transport katmanında mesajları parse edip, kullanıcı mesajı dosya erişimi gerektiriyorsaClaude'a "bu tool'ları kullanmalısın" tavsiyesi ile birlikte iletimek. Ancak MCP protokolü buna izin vermez — sunucu sadece tool çağrılarına yanıt verir, istemci mesajlarını değiştiremez.

**Artıları:**
- Teorik olarak en güçlü çözüm

**Eksileri:**
- MCP protokolü buna izin vermez
- claude-bridge bir proxy değil, bir MCP sunucusu
- Uygulama neredeyse impossible

**Uygulanabilirlik:** Impossible. MCP mimarisi buna uygun değil.

---

### Çözüm 9: claude-bridge'e Ek Bir "Discovery" Tool'u Ekleme

**Mekanizma:** claude-bridge'e, Claude Desktop'ın ilk mesajda mutlaka göreceği bir tool ekleyerek tool keşfini zorlama. Bu tool, kullanıcının mesajını analiz edip hangi tool'ların çağrılması gerektiğini söyleyen bir "meta-tool" olabilir.

**Uygulama:**
```python
@mcp.tool(
    description="REQUIRED: Always call this tool first when the user mentions "
    "files, directories, code, or projects. Returns which claude-bridge "
    "tools to use based on the user's request."
)
async def analyze_request(query: str) -> str:
    return json_response(True, "Use claude-bridge tools", details={
        "suggested_tools": ["read_file", "list_directory", "search_in_files"],
        "note": "The user is asking about a project. Use the tools above."
    })
```

**Artıları:**
- Claude modeli ilk mesajda bile en az bir tool çağırma eğiliminde olur
- Zincirleme reaksiyon: bir tool çağrıldıktan sonra diğer tool'lar da görünür

**Eksileri:**
- Claude Desktop client-side routing yapıyorsa model tool listesini hiç görmeyebilir
- Gereksiz bir tool çağrısı demek — her istekte fazladan bir round-trip
- Claude bu tool'u her çağırmak zorunda değil

**Uygulanabilirlik:** Düşük-Orta. Deneysel, garanti yok.

---

### Çözüm 10: Claude Desktop'ı CLI'den Başlatma (Alternative Launcher)

**Mekanizma:** claude-bridge, Claude Desktop yerine doğrudan Claude API ile konuşan kendi küçük bir GUI/CLI istemcisi sunabilir. Bu istemci her mesajda tool listesini modele gönderir.

**Uygulama:**
Bu, Claude Desktop'ın yerine geçen tamamen yeni bir proje anlamına gelir. claude-bridge'in kapsamı dışında.

**Artıları:**
- Tool routing tamamen kontrol edilebilir
- claude-bridge'in mevcut MCP sunucusu aynen kullanılır

**Eksileri:**
- Claude API anahtarı gerektirir
- Claude Desktop UX'ini yeniden oluşturmak büyük iş
- claude-bridge'in "Claude Desktop için yardımcı" konumlandırmasına aykırı

**Uygulanabilirlik:** Çok düşük. Farklı bir proje.

---

## Önerilen Uygulama Planı

### Hemen Yapılabilecek (claude-bridge Tarafı, Kod Değişikliği Minimal)

1. **Çözüm 2** — `claude-bridge setup` çıktısına Project Instructions paneli ekle
2. **Çözüm 7** — README'ye "İlk Mesaj İpucu" bölümü ekle
3. **Çözüm 3** — Tool description'ları güçlendir (deneme amaçlı)

### Claude Desktop Tarafında (Kullanıcı Tarafı)

4. **Çözüm 1** — Project Instructions'a tool kullanma talimatı ekle

### Uzun Vadeli

5. **Çözüm 6** — Anthropic'e bug report gönder
6. **Çözüm 4** — MCP tool gruplama (FastMCP güncellemesiyle)

### Impossible / Uygulanamaz

7. **Çözüm 5** — MCP protokolü izin vermez
8. **Çözüm 8** — MCP protokolü izin vermez
9. **Çözüm 10** — Farklı proje kapsamı

---

## claude-bridge Kodunda İyileştirme İmkânı

claude-bridge bu sorunu çözemese de, **ilk tool çağrısının başarısız olma durumunu daha iyi yönetebilir**:

Şu an sunucu her mesajda `tools/list` yanıtını doğru döndürür. Sorun Claude Desktop'ın bu listeyi modele iletmemesidir. claude-bridge'in yapabileceği bir şey yoktur.

Ancak `claude_desktop_config.snippet.json` dosyası hala `CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL=1` içeriyor (satır 10). Bu, C0 bug'ı olarak bugs.md'de zaten raporlanmış durumda ve README'de düzeltilmiş olsa da snippet dosyasında hala var.

---

## İkinci Sohbet'te Claude'un Tespit Ettiği Hatalar — Doğrulama

Claude Desktop ikinci sohbette (tool'lar yüklendikten sonra) şu hataları tespit etti:

### 1. "file_tools.py root değişkeni tanımlanıp yanlış bağlamda kullanılıyor" — KISMAN DOĞRU

`file_tools.py:461` → `root = target if target.is_dir() else target.parent`  
`file_tools.py:464` → `iter_searchable_files(target if target.is_dir() else target, ...)`

`root` değişkeni sadece satır 495'te kullanılıyor:
```python
relative_path = file_path.relative_to(root).as_posix() if target.is_dir() else file_path.name
```

Burada `target.is_dir()` True ise `root = target` kullanılıyor, False ise `file_path.name` kullanılıyor. Mantıksal olarak çalışıyor ama `root` değişkeni gereksiz ve yanıltıcı. bugs.md'de B6 olarak zaten raporlanmış. **Düşük öncelik**.

### 2. "server.py _git_commit monkey-patch, thread-unsafe" — DOĞRU

`server.py:209,271,282` → hala `_file_tools_mod._git_commit = _git_commit` yapılıyor. bugs.md'de H1 olarak raporlanmış. **Düzeltilmemiş.**

### 3. "tool_utils.py Symlink traversal zafiyeti" — YANLIŞ

`tool_utils.py:96-101` → `is_within_root` fonksiyonu `resolve()` sonrası kontrol yapıyor:
```python
def is_within_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False
```

Ancak `resolve_path` (satır 104-117) → `target.resolve()` çağırıyor. `resolve()` symlink'leri takip eder. Yani:
- `/allowed/dir/symlink → /etc/passwd` → `resolve()` → `/etc/passwd`
- `is_within_root(/etc/passwd, /allowed/dir)` → `ValueError` → `False`

Symlink traversal **engellenmiş durumdadır**. Claude'un bu bulgusu **yanlış**.

### 4. "shell_tools.py Bitişik pipe kontrolü" — KISMAN DOĞRU

Claude, `control_tokens_present`'in çalıştığını ama "testlerde kapsamı doğrulanmamış" diyor. shell_tools.py:40-43'te token-içi kontrol var. bugs.md'de H2 olarak raporlanmış ve kodda düzeltilmiş. **Düzeltilmiş.**

### 5. "git_ops.py init: True her zaman yanıltıcı" — DOĞRU

`git_ops.py:12` → `result = {"init": True, ...}` başlangıçta True. Repo zaten varsa `git init` çalışmaz ama `init` hala True kalır. `git init` çalıştıktan sonra (satır 30) `result["init"] = init.returncode == 0` güncelleniyor, ancak repo mevcut olduğunda bu satır hiç çalışmaz. **Düşük öncelik, bilgi tutarsızlığı.**

### 6. "indexing.py GDScript parser eksik" — DOĞRU AMA TASARIM KARARI

GDScript parsing sade tutulmuş, sadece `func ` ile başlayan fonksiyonlar yakalanıyor. `static func`, `@static_method` gibi varyantlar eksik. Bu bir bug değil, bilinçli bir tasarım sınırlaması. **Düşük öncelik.**
