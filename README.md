# Claude Bridge

> Claude Pro aboneliğiniz varsa, Claude Code olmadan Claude Code deneyimi yaşayın.

Claude Bridge, Claude Desktop veya diğer MCP uyumlu client'lara yerel dosya sistemi ve terminal erişimi kazandıran hafif bir **MCP sunucusudur**. `pipx` ile kurulur, tek komutla çalışır, hiçbir karmaşık yapılandırma gerektirmez.

## Neden Var?

Claude Bridge, Claude Desktop içinde proje dosyalarını okuyabilen, güvenli shell komutları çalıştırabilen ve küçük patch'ler uygulayabilen hafif bir yerel köprü sağlar.

Özellikle şu kullanım için tasarlandı:

- aynı oturumda birden fazla proje kökü arasında geçiş yapmak isteyen geliştiriciler
- Python tabanlı, `pipx` dostu bir kurulum isteyen ekipler
- sadece dosya erişimi değil, workflow, context-pack ve bounded agent loop gibi daha kontrollü geliştirme akışları isteyen kullanıcılar
- Godot, Python, JavaScript, TypeScript, Rust ve Go gibi farklı ekosistemlerde çalışan projeler

## Hızlı Başlangıç

En kısa kurulum akışı:

```bash
pipx install claude-bridge
claude-bridge install
```

Sonra Claude Desktop'u tamamen kapatıp yeniden açın ve yeni bir sohbet başlatın.

## Özellikler

- 📁 **Dosya Okuma** (`read_file`): Yerel metin dosyalarını Claude'a okutun
- 🖼️ **Çoklu Format Okuma** (`read_image`, `read_pdf`): Opsiyonel extra ile görsel metadata/base64 içerik ve PDF metni çıkarın
- 📂 **Klasör Listeleme** (`list_directory`): Proje yapısını keşfedin
- 🖥️ **Terminal Çalıştırma** (`run_shell`): Testleri ve komutları çalıştırın
- ✏️ **Akıllı Düzenleme** (`patch_file`, `preview_patch`): SEARCH/REPLACE ile sadece değişen satırları uygulayın
- 🚚 **Dosya Taşıma/Kopyalama** (`move_file`, `copy_path`): Workspace içinde onaylı rename, move ve copy işlemleri yapın
- 🔒 **Güvenli**: Her işlem öncesinde onay, tehlikeli komutlar engellenir
- 🌿 **Git Entegrasyonu**: Her değişiklik otomatik commit'lenir
- 🔌 **MCP Uyumlu**: Claude Desktop ve diğer MCP client'larla doğrudan çalışır
- 🌲 **Opsiyonel Tree-sitter**: Kuruluysa daha güçlü çok dilli sembol çıkarımı kullanır, yoksa güvenli fallback ile çalışır
- 📊 **Benchmark Hazır**: Büyük gerçek repo'larda indeksleme ve relevans sorgusunu ölçmek için dahili benchmark komutu içerir
- ✅ **Kalite Kapıları**: Tree-sitter var/yok matris testleri ve relevans için altın veri seti ile doğrulanır

## Kurulum

### Adım 1: Kurulum

```bash
pipx install claude-bridge
```

Veya repo'dan:
```bash
git clone <your-repo-url>
cd claude-bridge
pip install -e .
```

Tree-sitter destekli daha güçlü çok dilli indeksleme isterseniz opsiyonel parser paketini de kurabilirsiniz:

```bash
pip install -e .[treesitter]
```

Görsel ve PDF okuma araçlarını kullanmak isterseniz opsiyonel multi-format extra'yı kurun:

```bash
pip install -e .[multi-format]
```

`pipx` kurulumunda aynı extra'yı baştan eklemek için:

```bash
pipx install "claude-bridge[multi-format]"
```

### Adım 2: Claude Desktop'a Ekle

Önce hazır config örneğini üretin:

```bash
claude-bridge setup
```

Daha hızlı ve önerilen kurulum için Claude Desktop config dosyasını otomatik güncelleyebilirsiniz:

```bash
claude-bridge install
```

Elle kurmak isterseniz Claude Desktop > Settings > Developer > Edit Config dosyasını açın ve üretilen JSON'u ekleyin. Örnek:

```json
{
  "mcpServers": {
    "claude-bridge": {
      "command": "/absolute/path/to/python3",
      "args": ["-m", "claude_bridge.mcp_server"],
      "env": {
        "CLAUDE_BRIDGE_PROJECT_DIR": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_ALLOWED_ROOTS": "/absolute/path/to/project:/absolute/path/to/projects-parent",
        "CLAUDE_BRIDGE_AUTO_APPROVE": "0",
        "CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL": "0",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": "/absolute/path/to/repo/src"
      }
    }
  }
}
```

Claude Desktop'u tamamen kapatıp yeniden açın. Bu yapılandırma macOS sandbox nedeniyle stdout'u kirletmeden `python -m claude_bridge.mcp_server` çalıştırır, aktif proje dizinini `CLAUDE_BRIDGE_PROJECT_DIR` ile taşır ve ek çalışma alanlarını `CLAUDE_BRIDGE_ALLOWED_ROOTS` ile erişilebilir kılar. `install` komutu Claude Desktop config dosyasını otomatik bulup aynı JSON girdisini yazar.

Parser backend notu:

- Claude Bridge indeksleme sırasında önce opsiyonel Tree-sitter backend'i dener.
- Uygun parser paketi kurulu değilse mevcut regex/AST fallback backend ile çalışmaya devam eder.
- İndeks çıktısında `parser_backend` ve `parser_backends` alanları hangi yolun kullanıldığını gösterir.

Multi-format notu:

- `read_image` ve `read_pdf` core kurulumda import-time crash yaratmaz; gerekli paket yoksa structured error döner.
- `read_pdf` ilk sürümde text-only çalışır ve sayfa/pagination metadata'sı döndürür.
- `read_image` görsel metadata'sı ve base64 içerik döndürür; dosya path sınırı ve hassas dosya koruması diğer okuma araçlarıyla aynıdır.

Benchmark notu:

- Büyük repo performansını ölçmek için `claude-bridge benchmark --query "login auth" --path src` çalıştırabilirsiniz.
- Bu komut indeksleme süresini, tekrar eden relevans sorgu sürelerini ve en üst sonuçları raporlar.
- İsterseniz `--json` ile CI veya regresyon karşılaştırmalarında makine-okunur çıktı alabilirsiniz.
- İsterseniz `--baseline-file benchmarks/example_baseline.json` vererek baseline karşılaştırmasını fail/pass kapısına dönüştürebilirsiniz.
- İsterseniz `--profile-file benchmarks/profiles/django_auth.json` gibi bir profil verip query/path/baseline setini tek dosyadan yükleyebilirsiniz.

Önemli approval notu:

- MCP stdio modunda sunucu terminalden `input()` ile onay isteyemez.
- `run_shell`, `write_file`, `move_file`, `copy_path`, `patch_file`, `undo_last_patch` gibi araçların çalışması için ya MCP client'ın approval UI yönetmesi gerekir ya da güvenilir yerel kullanımda `CLAUDE_BRIDGE_AUTO_APPROVE=1` açılmalıdır.
- Claude Desktop approval UI kullanacaksanız config'i `claude-bridge setup --client-managed-approval ...` ile üretin.

İlk mesaj ipucu:

- Claude Desktop bazen MCP tool yönlendirmesini ilk mesajda geciktirebilir.
- İlk yanıtta "erişimim yok" benzeri bir cevap alırsanız daha açık bir ikinci mesaj deneyin:
  - "Bu projeyi claude-bridge ile incele"
  - "workspace_status kullan ve dosyaları oku"
  - "Bu klasörü review et ve claude-bridge tool'larını kullan"

## Paylaşım Öncesi Güvenlik

Bu projeyi GitHub veya benzeri bir yere koymadan önce şu kuralları uygulayın:

- Gerçek `claude_desktop_config.json` dosyanızı repoya koymayın; sadece placeholder içeren [claude_desktop_config.snippet.json](claude_desktop_config.snippet.json) paylaşın.
- Kendi kullanıcı adınızı, ev dizininizi ve özel proje path'lerinizi README veya örnek config içinde bırakmayın.
- `.env`, `*.local`, özel config ve kişisel log dosyalarının `.gitignore` tarafından dışlandığını kontrol edin.
- Paylaşmadan önce `rg -n "/Users/|API_KEY|SECRET|TOKEN|PASSWORD" .` ile hızlı bir sızıntı taraması yapın.

Amaç şu olmalı: repo klonlandığında herkes çalıştırabilsin, ama sizden kalan kişisel path veya gizli bilgi repo tarihine hiç girmesin.

### Adım 3: Manuel Başlatma (isteğe bağlı)

```bash
claude-bridge start --project-dir /absolute/path/to/project --allow-root /absolute/path/to/projects-parent
```

Bu komut MCP sunucuyu stdio modunda sessiz biçimde başlatır. Claude Desktop bu modda doğrudan iletişim kurar. Kurulum yönergeleri ve sistem promptu için `claude-bridge setup` kullanılır.

## Kullanım

Claude Desktop'ta normal konuşurken Claude şu tool'ları otomatik olarak kullanabilir:

- `read_file(path="src/player.py")` — dosya okuma
- `read_image(path="docs/screenshot.png")` — opsiyonel dependency ile görsel metadata ve base64 içerik okuma
- `read_pdf(path="docs/spec.pdf", page_start=1, page_end=3)` — opsiyonel dependency ile PDF metni okuma
- `list_directory(path="src/")` — klasör listeleme
- `write_file(path="notes.txt", content="...", max_lines=500)` — yeni dosya yazma veya açık overwrite; büyük içerikte patch önerisiyle warning döner
- `move_file(source="old.txt", destination="docs/old.txt")` — dosya veya klasör taşıma/yeniden adlandırma
- `copy_path(source="template.md", destination="docs/template.md")` — dosya veya klasör kopyalama
- `search_in_files(query="TODO", path="src")` — shell'e düşmeden metin arama
- `run_shell(command="pytest")` — komut çalıştırma
- `patch_file(file="src/player.py", search="old", replace="new")` — dosya düzenleme
- `preview_patch(...)` — patch uygulamadan önce diff ve risk önizleme
- `run_agent_loop_step(...)` — tek adımlık patch + validation yürütme
- `run_agent_loop_session(...)` — planlanmış birkaç adımı bounded şekilde zincirler
- `index_codebase(path=".")` — kaynak dosyalar için sembolik indeks çıkarma
- `find_relevant_files(query="login auth", path="src")` — sorguya göre en alakalı dosyaları bulma
- `claude-bridge benchmark --query "login auth" --path src` — büyük repo performansını ve sorgu kalitesini ölçme
- `workspace_status()` — aktif proje kökünü ve izinli kökleri görme
- `switch_project_root(path="/Users/me/Desktop/tertis")` — başka bir izinli klasöre geçme
- `run_workflow(mode="review", target="src/")` — slash UI olmadan workflow prompt'u üretme
- `run_workflow(mode="review", target="src/", execute=true)` — güvenli ilk keşif adımını otomatik başlatma
- `build_context_pack(target="src", goal="understand auth flow")` — hedef için framework-aware bağlam paketi çıkarma
- `suggest_validation_commands(target="src")` — proje tipine göre doğrulama komutları önerme

Üretilen örnek config varsayılan olarak fail-closed davranır: approval gerektiren araçlar ancak MCP client approval UI yönetiyorsa veya `auto_approve` açıkça etkinleştirildiyse çalışır.

### Prompt Komutları

İlk MCP prompt prototipi eklendi:

- `/review` — bir dosya veya klasör için inceleme akışı başlatır
- `/optimize` — performans ve bakım odaklı iyileştirme önerileri ister
- `/orchestrate` — büyük bir işi paralel iş akışlarına bölüp entegrasyon planı çıkarır
- `/agent_loop` — küçük ve kontrollü bir inspect-patch-validate döngüsü planlar
- `/quality` — kodu yayınlanabilir kalite standardına göre değerlendirir
- `/test` — eksik testleri ve riskli boşlukları tespit ettirir
- `/todo` — TODO/FIXME/HACK yorumlarını tarayıp önceliklendirir
- `/explain` — kodu hedeflediğiniz seviyede açıklar
- `/commit` — değişiklikleri özetleyip commit mesajı önerir

Bu prompt, Claude'a önce hangi dosyaları okuması gerektiğini ve nelere odaklanacağını söyler. Amaç doğrudan dosya değiştirmek değil, önce riskleri ve eksikleri bulmaktır.

### Workflow Tool

Claude Desktop prompt UI bu komutları göstermese bile aynı akışlara `run_workflow` aracıyla erişilebilir.

Örnekler:

- `run_workflow(mode="review", target="src/claude_bridge/server.py")`
- `run_workflow(mode="review", target="src/claude_bridge/server.py", execute=true)`
- `run_workflow(mode="optimize", target="src/", option="performance and readability")`
- `run_workflow(mode="orchestrate", target="src/", option="split by modules and define integration gates")`
- `run_workflow(mode="agent_loop", target="src/", option="fix the failing behavior with bounded iterations", max_iterations=3)`
- `run_workflow(mode="quality", target="src/", option="correctness and regression safety")`
- `run_workflow(mode="test", target="src/", option="regression tests")`
- `run_workflow(mode="todo", target=".", option="TODO, FIXME")`
- `run_workflow(mode="explain", target="src/claude_bridge/server.py", option="a junior developer", language="English")`
- `run_workflow(mode="commit", target=".", option="short imperative message")`

Desteklenen `mode` değerleri:

- `review`
- `optimize`
- `orchestrate`
- `agent_loop`
- `quality`
- `test`
- `todo`
- `explain`
- `commit`

`execute=true` verilirse araç güvenli, salt-okunur ilk keşif adımını da çalıştırır:

- dosya hedefinde `read_file`
- klasör hedefinde `list_directory`, ardından `find_relevant_files` ve birkaç güçlü aday için `read_file`
- uygun olduğunda `project.godot`, `export_presets.cfg` veya sahne dosyaları gibi tamamlayıcı runtime/config dosyalarını da dahil eder

Bu mod otomatik olarak `run_shell` veya `patch_file` çalıştırmaz.

`orchestrate` modu özellikle büyük görevlerde yararlıdır:

- işi bağımsız workstream'lere böler
- her parça için sahiplik ve risk tanımlar
- ana agent için entegrasyon ve final kalite kontrol adımı üretir

Bu, gerçek paralel alt-agent orkestrasyonu değildir; ama Claude Desktop içinde buna yakın bir çalışma düzeni kurmak için güçlü bir başlangıç sağlar.

## Test ve Stabilizasyon

Bu repo artık sadece birim testlerle değil, birkaç farklı kalite kapısıyla korunur:

- klasik davranış testleri
- Tree-sitter var/yok entegrasyon matrisi
- relevans sıralaması için altın veri seti
- büyük gerçek repo'larda tekrar çalıştırılabilir benchmark komutu
- GitHub Actions üzerinde fallback, Tree-sitter ve CLI smoke doğrulamaları

Yerelde hızlı doğrulama için:

```bash
pip install -e .[dev]
claude-bridge doctor --project-dir .
pytest
claude-bridge benchmark --project-dir . --path src --query "auth session login"
```

`doctor` komutu Python sürümünü, paketin import edilebilirliğini, dev araçlarını
(`pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`) ve opsiyonel smart /
Tree-sitter bağımlılıklarını kontrol eder. Eksik opsiyonel paketler core
kullanımı engellemez; çıktı hangi extra'nın kurulması gerektiğini gösterir.

`agent_loop` modu ise daha küçük ve kontrollü işler içindir:

- inspect -> patch -> validate -> decide döngüsü tanımlar
- iterasyon bütçesi koyar
- allowed tool ve validation sınırlarını açıkça listeler
- “sonsuz düzeltme” yerine güvenli durma koşulları üretir

`execute=true` ile birlikte ilk iterasyon için:

- okunacak dosyaları seçer
- validation komutları önerir
- küçük ve geri alınabilir ilk patch stratejisini yapılandırılmış olarak döner

Gerçek yürütme için `run_agent_loop_step(...)` kullanılabilir:

- bir patch uygular
- bir validation komutu çalıştırır
- `stop_success`, `continue` veya `stop_failure` kararı döner

Birden fazla adımı sırayla yürütmek için `run_agent_loop_session(...)` kullanılabilir:

- JSON step listesi alır
- structured `steps=[...]` parametresi veya geriye dönük `steps_json` kullanabilir
- her step için `run_agent_loop_step(...)` çağırır
- erken başarı veya başarısızlıkta durur
- ham step sonuçlarının yanında kısa bir `session_summary` da döner; bu da uzun oturumlarda context şişmesini azaltan hafif bir auto-compact katmanı sağlar
- `compact_threshold` ve `keep_recent_results` ile eski step detaylarını otomatik özetleyip sadece en güncel adımları ayrıntılı bırakabilir
- `handoff_summary` alanı, başka bir sohbete ya da modele geçerken kısa durum aktarımı yapmak için kullanılabilir

### Codebase Index Tool

`index_codebase` aracı, desteklenen kaynak dosyalarını tarayıp basit bir sembolik indeks döner.

Şunları çıkarır:

- dosya listesi
- fonksiyon adları
- sınıf adları
- import edilen modüller

İlk sürüm özellikle hızlı ve güvenli olacak şekilde sade tutuldu:

- şu anda Python, GDScript (`.gd`), JavaScript (`.js`, `.jsx`), TypeScript (`.ts`, `.tsx`), Rust (`.rs`), Go (`.go`), Java (`.java`), Kotlin (`.kt`), C# (`.cs`), Ruby (`.rb`) ve PHP (`.php`) dosyalarını işler
- `venv`, `.git`, `__pycache__`, `.pytest_cache`, `node_modules` gibi klasörleri atlar
- embedding kullanmaz

Örnek:

- `index_codebase(path=".")`
- `index_codebase(path="src")`

### Relevant Files Tool

`find_relevant_files` aracı, sembolik indeks üstünde basit bir relevans sıralaması yapar.

Şunları dikkate alır:

- dosya yolu
- fonksiyon adları
- sınıf adları
- import edilen modüller

Örnek:

- `find_relevant_files(query="login auth", path="src")`
- `find_relevant_files(query="todo parser", path="src", limit=3)`

Not:

- Araç şu anda Python, GDScript (`.gd`), JavaScript, TypeScript, Rust, Go, Java, Kotlin, C#, Ruby ve PHP kaynaklarını indeksler.
- Bu sayede hem Python MCP projelerinde, hem Godot gibi yerel oyun projelerinde, hem modern frontend/backend JS/TS projelerinde, hem de farklı backend/uygulama ekosistemlerinde işe yarar.

### Tool Yanıt Formatı

Tüm ana tool'lar (`read_file`, `list_directory`, `write_file`, `move_file`, `copy_path`, `run_shell`, `patch_file`) düz metin yerine yapılandırılmış JSON metni döner. Bu format slash komutları, workflow ve agentic loop için sabit bir temel sağlar.

Örnek başarılı yanıt:

```json
{
  "ok": true,
  "message": "Shell command completed successfully",
  "details": {
    "command": "pytest",
    "stdout": "...",
    "stderr": "",
    "exit_code": 0
  }
}
```

Örnek hatalı yanıt:

```json
{
  "ok": false,
  "code": "blocked_command",
  "message": "Command blocked for safety: contains 'sudo'",
  "details": {
    "command": "sudo apt update",
    "blocked_pattern": "sudo"
  }
}
```

Başlıca hata kodları:

- `directory_not_found`
- `directory_read_error`
- `not_a_directory`
- `not_a_file`
- `blocked_command`
- `approval_rejected`
- `command_failed`
- `command_timeout`
- `command_error`
- `empty_command`
- `file_not_found`
- `source_not_found`
- `destination_exists`
- `same_path`
- `interactive_command_unsupported`
- `search_not_found`
- `search_ambiguous`
- `python_syntax_error`
- `path_outside_project`
- `file_read_error`
- `file_write_error`

### Shell Komut Matrisi

`run_shell` aracı için pratik davranış özeti:

| Komut tipi | Örnek | Beklenen davranış |
|------------|-------|-------------------|
| Güvenli okuma | `ls`, `pytest`, `python -m pytest` | Onay sonrası çalışır |
| Güvenli teşhis | `git status`, `git diff`, `ruff check .` | Onay sonrası çalışır |
| Tehlikeli komut | `sudo ...`, `rm -rf ...`, `chmod 777 ...` | Otomatik engellenir |
| Shell pipe ile script | `curl ... \| bash` | Otomatik engellenir |
| Runtime pipe | `curl ... \| node`, `printf ... \| fish` | Otomatik engellenir |
| Inline runtime script | `node -e ...`, `ruby -e ...`, `php -r ...` | Otomatik engellenir |
| Uzun çalışan komut | uzun süren build/test | 30 saniye sonra timeout döner |
| Etkileşimli komut | `python`, `vim`, `top` | `interactive_command_unsupported` ile reddedilir |
| Boş komut | `""` | `empty_command` ile reddedilir |

Notlar:

- `run_shell` şu an TTY açmaz
- `stdin` bekleyen komutlar güvenilir çalışmaz
- `python3 -c ...` geriye dönük uyumluluk için izinli kalır; daha riskli inline runtime entrypoint'leri engellenir
- Başarısız komutlar `command_failed`, `command_timeout`, `interactive_command_unsupported` veya `empty_command` koduyla döner

## Güvenlik

- **Yerel-only**: Sunucu hiçbir zaman dış internete bağlanmaz
- **Açık kaynak**: MIT lisansı, herkes denetleyebilir
- **Onay modeli**: Sunucu `auto_approve=false` ile başlar; ama Claude Desktop kullanımında approval çoğunlukla istemci tarafından yönetilir. Yani gerçek onay davranışı MCP client'ına bağlıdır.
- **İzin sistemi**: Sadece belirlenen klasöre erişilir
- **Komut filtresi**: `rm -rf`, `sudo`, `chmod`, `| bash`, `curl | node`, `node -e` gibi riskli komutlar engellenir
- **Path traversal koruması**: `../` ile proje dışına çıkılamaz
- **Hassas dosya koruması**: `.env`, `.pem`, `.key`, `id_rsa`, `claude_desktop_config.json` gibi dosyalar doğrudan okunmaz/yazılmaz ve hata yanıtlarında resolved path/reason sızdırılmaz

## Neden İndirilsin?

Bu projenin değerli olması için sadece "çalışıyor" olması yetmez; başka araçlardan ayrışması gerekir. Claude Bridge şu alanlarda farklılaşır:

- **Claude Desktop odaklı pratik kurulum**: stdio'yu bozmayan, gerçek masaüstü entegrasyonuna göre şekillendirilmiş akış.
- **Yerel ve çok çalışma alanlı kullanım**: tek repo yerine izinli birden fazla kök arasında geçiş yapabilir.
- **Yapılandırılmış tool çıktıları**: düz metin yerine kararlı JSON döndürerek daha agentic akışlara temel sağlar.
- **Kod inceleme ve workflow katmanı**: sadece dosya açan bir bridge değil; review, explain, test ve todo akışlarını da başlatır.
- **Python dışına açılma sinyali**: GDScript gibi ikinci bir ekosistemde de fayda üretmeye başlamıştır.

Eğer projeyi yayımlayacaksanız, en güçlü konumlandırma şu olur:

- "Claude Desktop için güvenli, yerel-first, çok-projeli MCP bridge"
- "Claude Code hissini resmi ürün olmadan yaklaştıran açık kaynak yardımcı katman"

Yani değer önerisi sadece "dosya okuyor" değil; "masaüstünde gerçekten kullanılabilir, kontrollü ve geliştirilebilir bir agent köprüsü" olmalı.

## Sistem Gereksinimleri

- Python 3.8+
- Claude Desktop (veya başka bir MCP client)
- pipx (kurulum için)

## Sorun Giderme

### macOS: `Operation not permitted`

Claude Desktop sandbox içinde çalıştığı için `venv/bin/claude-bridge` gibi imzasız binary'leri doğrudan çalıştırmak başarısız olabilir. Bu yüzden config içinde `python -m claude_bridge.mcp_server` yaklaşımını kullanın ve config'i `claude-bridge setup` ile üretin.

- `command`: `/usr/bin/env`
- `args`: `["python3", "-m", "claude_bridge.mcp_server"]`

Bu yaklaşım doğrudan venv binary'sini `exec` etmek yerine Python modülünü başlatır.

### Log Dosyası Nerede?

macOS üzerinde MCP log'u genelde şu dosyada olur:

```text
~/Library/Logs/Claude/mcp-server-claude-bridge.log
```

Başarılı bir başlangıçta log içinde şunlara benzer satırlar görmelisiniz:

- `Using MCP server command: /usr/bin/env`
- `Message from client: {"method":"initialize"...}`
- `Message from client: {"method":"tools/list"...}`

### Prompt'lar Görünmüyorsa

- Claude Desktop'ı tamamen kapatıp yeniden açın
- `claude_desktop_config.json` içinde geçerli JSON olduğundan emin olun
- Log dosyasında `prompts/list` isteğinin geldiğini kontrol edin
- `PYTHONPATH` değişkeninin proje içindeki `src` klasörünü gösterdiğini doğrulayın

### Tool Çıktıları Beklediğiniz Gibi Değilse

- Tool yanıtının JSON metni olduğunu unutmayın
- Başarı için `ok: true`, hata için `ok: false` kontrol edin
- Ayrıntıları `details` alanından okuyun
- Hata nedenini anlamak için `code` alanını kullanın

## Lisans

MIT Lisansı — Detaylar için [LICENSE](LICENSE) dosyasına bakın.

## Katkıda Bulunma

Katkılar memnuniyetle karşılanır! Lütfen önce bir issue açın.

---

**Not**: Bu proje Anthropic'in resmi bir ürünü değildir. Claude.ai'yı normal kullanım şartları dahilinde kullanır.
