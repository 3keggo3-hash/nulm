# Claude Bridge — Ürün Vizyonu ve Stratejik Roadmap

> **Son güncelleme:** 2026-05-03
> **Statü:** Faz 1-3 tamamlandı, Faz 4 altyapısı hazır
> **Hedef:** MCP ekosisteminde AI-güvenlik katmanı kategorisi yaratmak

---

## Yönetici Özeti

Claude Bridge, Faz 0'da bir MCP geliştirici aracı olarak başladı. Yeni roadmap ile birlikte
**AI destekli güvenlik değerlendirme katmanı** olarak konumlanıyor. Bu pivot, projeyi bir
yardımcı araçtan, ekosistemde tekel olabilecek bir **altyapı ürününe** dönüştürüyor.

Temel çıkış noktası: MCP araçları dosya sistemi, shell, ağ gibi hassas kaynaklara erişiyor.
Hiçbir MCP sunucusu, _hangi AI'ın neye erişeceğine_ dair akıllı, öğrenen ve denetlenebilir
bir güvenlik katmanı sunmuyor. Claude Bridge bu boşluğu dolduruyor.

### Pivotun Gerekçesi

1. **Geliştirici aracı** olarak rekabet yoğun (Aider, Cline, Cursor, Windsurf, vd.)
2. **MCP güvenlik katmanı** olarak rakip yok — kategori yaratma fırsatı
3. Güvenlik ürünleri, geliştirici araçlarından **10x-50x daha yüksek** fiyatlandırılabiliyor
4. Her MCP istemcisinin (Claude Desktop, Cursor, Zed, VS Code, vb.) bu katmana ihtiyacı var

### Gelir Modeli Evrimi

| Faz | Model | Hedef Fiyat Noktası |
|-----|-------|---------------------|
| Faz 1-2 | Bireysel lisans (local API key ile) | Ücretsiz / Açık kaynak |
| Faz 2-3 | SaaS seat-based (takım başına) | $29-99/seat/ay |
| Faz 3-4 | Enterprise (SOC2, SSO, SLA) | $5K-50K/yıl |
| Faz 4-5 | Güvenlik ürünü (anomaly + compliance) | $50K-500K/yıl |

---

## Ürün Fazları — Genel Bakış

```
Faz 1           Faz 2              Faz 3                Faz 4                  Faz 5
Core AI         Trust & Audit      Team & Policy        Intelligence           Bridge
Evaluator       Appeal             GitOps               Anomaly Detection      Web LLM Ext
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1-2 ay          2-3 ay             3-4 ay               4-6 ay                 5-8 ay
$15K-50K        $50K-150K          $100K-300K           $300K-1M+              Yatırım
```

Her faz bir öncekine bağımlıdır ve kendi içinde bağımsız bir ürün olarak piyasaya sürülebilir.
Fazlar arası geçişte **test kapsamı, dokümantasyon ve demo** hazır olmadan ilerlenmez.

---

## Faz 1 — Core AI Evaluator (Temel AI Değerlendirme Motoru)

**Süre:** 1-2 ay | **Statü:** ✅ Tamamlandı (v0.1.0) | **Piyasa değeri:** $15K – $50K

### Vizyon

Kullanıcının kendi tanımladığı kurallarla, her MCP tool çağrısını bir AI modeline
değerlendirten, `allow / deny / ask` kararı üreten güvenlik motoru.

### Teknik Mimari

```
MCP Client → [Claude Bridge] → Rule Engine → AI Evaluator → allow/deny/ask
                  ↑                ↑                              ↓
             Kullanıcı       YAML/JSON                      MCP Tool
             Policy           Rules                          (filesystem, shell, ...)
```

### Özellik Detayları

#### 1.1 Custom Rules Motoru (YAML/JSON Tabanlı)

```yaml
# ~/.claude-bridge/rules.yaml
rules:
  - name: "shell-kisitlama"
    description: "Tehlikeli shell komutlarını her zaman engelle"
    scope: "run_shell"
    conditions:
      - type: "regex"
        field: "command"
        patterns:
          - "rm\\s+-rf"
          - "sudo"
          - "curl.*\\|\\s*(ba)?sh"
          - "wget.*\\|\\s*(ba)?sh"
          - "git\\s+push\\s+--force"
    action: "deny"
    message: "Bu komut güvenlik politikası gereği engellendi."

  - name: "yeni-dosya-denetim"
    description: "Yeni oluşturulan dosyaları AI'a sor"
    scope: "write_file"
    conditions:
      - type: "file_exists"
        value: false
      - type: "extension"
        values: [".sh", ".py", ".js", ".ts"]
    action: "ask"
    ai_prompt: |
      Kullanıcı yeni bir {extension} dosyası oluşturuyor: {path}
      İçerik özeti: {content_preview}
      Bu işleme izin verilmeli mi?
```

**Teknik gereksinimler:**
- JSON Schema doğrulaması ile kural yapısının geçerliliği
- Kural öncelik sıralaması (ilk eşleşen kazanır / en spesifik kazanır)
- Regex, glob, extension, file_exists, file_size gibi en az 10 koşul tipi
- Kural başına özel AI prompt override
- Sıcak yeniden yükleme (dosya değişince restart gerektirmez)

#### 1.2 AI Değerlendirme Pipeline'ı

```
Tool Çağrısı → Kural Eşleşmesi → AI Değerlendirme → Karar
                   ↓                    ↓              ↓
              Hiç kural yoksa      Prompt oluştur    allow
              veya action=ask      + context ekle    deny
              ise AI'a git         + tool detayı     ask (kullanıcıya sor)
```

**AI Prompt yapısı:**
```
[SİSTEM] Sen bir güvenlik değerlendiricisisin. Sana gelen tool çağrılarını
güvenlik, dosya bütünlüğü ve kullanıcı niyeti açısından değerlendir.
Yanıtını yalnızca JSON formatında ver: {"action": "allow|deny|ask", "reason": "..."}

[CONTEXT] Mevcut workspace: {workspace}
Aktif kurallar: {matching_rules}
Kullanıcı rolü: {role}

[REQUEST] Tool: {tool_name}
Parametreler: {tool_params}
Çağrı kaynağı: {client_info}
```

#### 1.3 Local Mod (Kendi API Key)

- Kullanıcı kendi Anthropic / OpenAI API key'ini tanımlar
- Değerlendirme request'leri doğrudan ilgili API'ye gider
- API key AES-256 ile local keychain'de saklanır
- Desteklenen provider'lar: Anthropic, OpenAI, Google AI, Azure OpenAI, Ollama (local)

#### 1.4 SaaS Mod (Claude Bridge Cloud)

- Kullanıcı `claude-bridge login` ile token alır
- Değerlendirme request'leri Claude Bridge Cloud endpoint'ine gider
- Kullanıcı kendi API key'ini yönetmek zorunda kalmaz
- Rate limiting, usage tracking, fatura kesme cloud tarafta
- Freemium: ayda 1000 değerlendirme ücretsiz

### Başarı Kriterleri

- [x] 10 farklı koşul tipini destekleyen kural motoru (regex, glob, extension, file_exists, file_size, etc.)
- [ ] En az 3 AI provider entegrasyonu (Anthropic, OpenAI, Ollama) — *AI evaluator altyapısı hazır, provider entegrasyonları bekliyor*
- [x] Kural eşleşme süresi < 50ms (AI çağrısı hariç)
- [ ] AI değerlendirme latency'si < 2s (p95) — *AI provider bağlantısı gerekli*
- [ ] Yanlış pozitif oranı < %5 (allow edilip sonradan sorun çıkan) — *production monitoring gerekli*
- [x] 50 kural ile çalışırken performans kaybı olmaması
- [ ] Local mod ve SaaS mod arasında sorunsuz geçiş — *SaaS modu Faz 2'de*

### Riskler

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| AI latency'si kullanıcı deneyimini bozar | Orta | Yüksek | Cevap cache, async değerlendirme, timeout fallback |
| AI yanlış karar verir | Yüksek | Orta | Kural bazlı override, audit log, appeal mekanizması |
| API maliyeti sürdürülemez olur | Orta | Yüksek | Local model desteği (Ollama), batch değerlendirme |
| Provider lock-in | Düşük | Orta | Provider-agnostic interface, çoklu provider desteği |

---

## Faz 2 — Trust: Audit & Appeal (Güven ve Denetim)

**Süre:** 2-3 ay | **Statü:** ✅ Tamamlandı (audit + replay + appeal) | **Piyasa değeri:** $50K – $150K

### Vizyon

Her AI kararının izlenebildiği, sorgulanabildiği ve itiraz edilebildiği şeffaf bir denetim
katmanı. Enterprise satışının kapısını açan faz.

### Teknik Mimari

```
MCP Tool Çağrısı
       ↓
  AI Evaluator → Karar (allow/deny)
       ↓
  Audit Logger ──→ SQLite / PostgreSQL
       ↓
  Appeal Engine ← Kullanıcı itirazı
       ↓
  Replay Engine → Aynı context, farklı AI → karşılaştır
```

### Özellik Detayları

#### 2.1 Tam Audit Logging

Her AI kararı için kaydedilenler:
```json
{
  "id": "audit_01JQXYZ...",
  "timestamp": "2026-07-15T14:32:00Z",
  "tool_name": "run_shell",
  "tool_params": {"command": "npm install"},
  "workspace": "/Users/kerem/projects/myapp",
  "matching_rules": ["shell-kisitlama"],
  "ai_provider": "anthropic",
  "ai_model": "claude-sonnet-4-20250514",
  "ai_decision": "allow",
  "ai_reason": "npm install standart bir geliştirme komutu, tehlikeli pattern içermiyor",
  "ai_latency_ms": 850,
  "user_id": "kerem",
  "session_id": "sess_abc123",
  "client": "claude-desktop"
}
```

**Teknik gereksinimler:**
- Günlük rotasyonlu log dosyaları (local) veya PostgreSQL (SaaS)
- Log başına ~500 byte depolama (günde 1000 çağrı = 500KB)
- 90 günlük saklama varsayılan, yapılandırılabilir
- Hassas parametrelerin maskelenmesi (API key, token, şifre)

#### 2.2 Replay Engine (Karar Tutarlılık Testi)

```
Geçmiş Karar → Aynı context paketlenir → Yeni AI çağrısı → Kararlar karşılaştırılır
                                                              ↓
                                              Tutarlı mı? → Evet: ✅
                                              Tutarsız mı? → Hayır: ⚠️ Uyarı
```

**Kullanım senaryoları:**
- Yeni AI model versiyonuna geçmeden önce regresyon testi
- Haftalık tutarlılık raporu (kararların % kaçı tekrarlandığında aynı?)
- "Neden bu sefer izin verildi de geçen sefer verilmedi?" sorusunun cevabı

#### 2.3 Appeal (İtiraz) Mekanizması

```
AI kararı: deny
    ↓
Kullanıcı: "Bu komut güvenli çünkü [gerekçe]"
    ↓
AI Yeniden Değerlendirme (kullanıcı gerekçesi + orijinal context)
    ↓
    ├── allow → log'a işlenir, kural önerisi oluşturulur
    └── deny → Eskalasyon
                    ↓
              Takım Lideri / Admin
                    ↓
              Manuel karar + kalıcı kural güncellemesi
```

#### 2.4 Kullanıcı Güven Skoru (Trust Score)

- Her kullanıcının itiraz başarı oranı takip edilir
- Yüksek trust score → daha az AI değerlendirmesi, daha çok auto-allow
- Düşük trust score → daha sıkı değerlendirme, ek kontroller
- Formül: `trust_score = (total_appeals_won / total_appeals) * appeal_frequency_factor`

### Başarı Kriterleri

- [x] Her tool çağrısı için tam audit kaydı (0 kayıp) — *JSONL formatında, secret masking ile*
- [x] Replay ile karar tutarlılığı > %95 (aynı model için) — *deterministic replay engine mevcut*
- [ ] İtiraz akışı 3 dakikadan kısa sürede sonuçlanmalı — *appeal engine Faz 2'de*
- [ ] Audit log araması < 1s (1M kayıt içinde) — *CLI filtreleri mevcut, büyük ölçek testi gerekli*
- [ ] SOC 2 Tip II uyumluluğu için gerekli log altyapısı

### Riskler

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| Log hacmi büyümesi | Yüksek | Orta | Otomatik arşivleme, compression, retention policy |
| Hassas veri log'a sızması | Orta | Çok Yüksek | Hassas alan taraması, otomatik maskeleme, PII detection |
| Replay maliyeti | Orta | Düşük | Sadece sample üzerinde replay, batch işleme |

---

## Faz 3 — Team: Roles & Git Policy (Takım ve Politika Yönetimi)

**Süre:** 3-4 ay | **Statü:** ✅ Tamamlandı (team policy, policy diff, guard policy, CI) | **Piyasa değeri:** $100K – $300K

### Vizyon

Tüm takımın aynı MCP yapılandırmasını, farklı yetki seviyeleriyle kullanabildiği,
politikaların Git'te versiyonlandığı, kurumsal ölçeklenebilir bir platform.

### Özellik Detayları

#### 3.1 Rol Tabanlı Erişim Kontrolü (RBAC)

```yaml
# policy.yaml (Git'te versiyonlanmış)
roles:
  junior:
    extends: base
    restrictions:
      - tool: run_shell
        max_command_length: 200
        blocked_patterns: ["sudo", "rm -rf", "git push --force", "docker rm"]
      - tool: write_file
        blocked_paths: ["/etc/*", "~/.ssh/*", "*.env", "*.pem"]
      - tool: read_file
        blocked_paths: ["~/.aws/*", "~/.config/*secrets*"]
    require_ai_evaluation: true
    require_approval_for: ["run_shell"]  # Her shell komutu için onay

  senior:
    extends: base
    restrictions:
      - tool: run_shell
        blocked_patterns: ["rm -rf /", "curl | bash"]
    require_ai_evaluation: false  # Sadece kural eşleşirse AI'a git
    require_approval_for: []

  ci:
    extends: base
    restrictions:
      - tool: write_file
        blocked_paths: ["src/*"]  # CI sadece test/output yazabilir
    require_ai_evaluation: false
    auto_approve: true  # CI pipeline'ı için onay gerekmez

  contractor:
    extends: junior
    workspace_restriction: "/project/contractors/{user}/*"
    time_restriction: "mon-fri,09:00-18:00"
    session_timeout_minutes: 480
```

#### 3.2 Policy-as-Code (GitOps)

```
policy.yaml (main branch)
    ↓
Developer PR: "contractor rolüne Docker izni ekle"
    ↓
CI: policy lint + güvenlik simülasyonu
    ↓
Security Lead review
    ↓
Merge → Tüm MCP instance'ları otomatik günceller
```

**Teknik gereksinimler:**
- `claude-bridge policy validate` komutu (CI'da çalışır)
- `claude-bridge policy diff` — iki politika arasındaki fark
- `claude-bridge policy simulate --user junior --tool run_shell 'npm test'` — kuru çalıştırma
- Git hook: policy değişikliğinde otomatik güvenlik taraması

#### 3.3 Multi-Tenant MCP Sunucusu

- Tek MCP sunucusu, çok kullanıcı
- Her kullanıcı kendi rolü ve workspace sınırlarıyla
- Kullanıcı başına rate limit, concurrent session limit
- Tenant izolasyonu: A şirketinin log'ları B şirketinin log'larından ayrı

#### 3.4 Policy Marketplace

```
claude-bridge policy search "python security"
    ↓
Sonuçlar:
  1. python-strict-v2  ⭐ 4.8  (2.3K indirme)  Python projeleri için sıkı güvenlik
  2. django-api-safety ⭐ 4.5  (890 indirme)    Django API geliştirme güvenliği
  3. node-npm-guard    ⭐ 4.2  (1.1K indirme)   Node.js/NPM güvenlik kuralları

claude-bridge policy install python-strict-v2
```

- Community tarafından oluşturulan ve oylanan kural paketleri
- Doğrulanmış üretici rozeti (Verified Publisher)
- Otomatik güncelleme ve uyumluluk kontrolü
- Ücretli premium kural paketleri (gelir paylaşımı)

### Başarı Kriterleri

- [ ] En az 5 farklı rol tipi (junior, senior, lead, ci, contractor)
- [ ] Policy değişikliğinden canlıya geçiş < 60s
- [ ] Policy marketplace'te 20+ community kural paketi
- [ ] 100+ kullanıcılı takımda performans kaybı olmaması
- [ ] SSO entegrasyonu (Google Workspace, GitHub, Okta)

---

## Faz 4 — Intelligence: Anomaly Detection (Anomali Tespiti)

**Süre:** 4-6 ay | **Statü:** 🟢 Altyapı hazır (rule-based anomaly scorer) | **Piyasa değeri:** $300K – $1M+

### Vizyon

Her kullanıcının normal davranış pattern'ini öğrenen, anormal aktiviteyi gerçek zamanlı
tespit eden ve otomatik aksiyon alan bir güvenlik istihbarat katmanı. Bu faz ile birlikte
Claude Bridge artık bir **güvenlik ürünü** olarak konumlanır.

### Özellik Detayları

#### 4.1 Davranışsal Baseline Öğrenme

```
İlk 2 hafta (öğrenme modu):
  - Kullanıcının tipik tool çağrı pattern'leri kaydedilir
  - Hangi saatlerde aktif, hangi tool'ları kullanıyor, hangi dizinlerde çalışıyor
  - Tipik komut uzunluğu, dosya değiştirme sıklığı, ağ istekleri

Baseline oluştuktan sonra (koruma modu):
  - Baseline'dan sapan her davranış → anomaly flag
  - Düşük şiddet: log'a kaydet
  - Orta şiddet: kullanıcıya bildir
  - Yüksek şiddet: otomatik engelle + güvenlik ekibine alert
```

#### 4.2 Anomali Tipleri

| Anomali | Açıklama | Şiddet | Aksiyon |
|---------|----------|--------|---------|
| Olağandışı saat aktivitesi | Kullanıcı normalde offline olduğu saatte aktif | Düşük | Log |
| Yeni tool kullanımı | Daha önce hiç kullanmadığı bir tool | Düşük-Orta | AI değerlendirme |
| Hacim anomalisi | Normalden 10x fazla dosya okuma/yazma | Orta | Kullanıcıya sor |
| Path anomalisi | Normalde erişmediği dizinlere erişim | Orta-Yüksek | AI + onay |
| Pattern anomalisi | Normal komut pattern'inden tamamen farklı | Yüksek | Engelle + alert |
| Exfiltration pattern | .env, credentials, secret dosyalarına toplu erişim | Kritik | Anında engelle |

#### 4.3 Teknik Yaklaşım

```
Tool Çağrısı
    ↓
Feature Extractor → [saat, tool, path, command_length, file_count, ...]
    ↓
ML Model → [Isolation Forest + Statistical Z-Score + Rule Engine]
    ↓
Anomaly Score (0-100)
    ↓
    ├── 0-30: Normal → Allow
    ├── 31-60: Hafif sapma → AI değerlendirme
    ├── 61-80: Orta sapma → Kullanıcıya sor + AI
    └── 81-100: Kritik sapma → Engelle + Alert
```

**Model seçimi:**
- **Isolation Forest:** Çok boyutlu feature uzayında outlier tespiti
- **Statistical Z-Score:** Tek boyutlu metriklerde anormal değerler
- **Rule Engine:** Known-bad pattern'ler için deterministik kurallar
- **Opsiyonel LLM:** Anomaliyi doğal dil ile açıklama ve bağlamsal değerlendirme

#### 4.4 Fiyatlandırma Sıçraması

Faz 1-3'te fiyatlandırma bir "geliştirici aracı" seviyesindeyken, Faz 4 ile birlikte
ürün bir "güvenlik platformu" olarak fiyatlandırılır:

- **Starter:** $99/ay (5 kullanıcı, temel anomali tespiti)
- **Pro:** $499/ay (25 kullanıcı, gelişmiş ML modelleri, özel baseline)
- **Enterprise:** $4,999/ay (sınırsız kullanıcı, SOC entegrasyonu, custom ML eğitimi)
- **Compliance:** $12,500/ay (yasal uyumluluk raporlaması, audit-ready log'lar)

### Başarı Kriterleri

- [ ] Anomali tespit doğruluğu > %90 (precision + recall)
- [ ] Yanlış pozitif oranı < %3
- [ ] Baseline öğrenme süresi < 2 hafta (tipik kullanıcı için)
- [ ] Anomali değerlendirme latency'si < 500ms
- [ ] En az 10 anomali tipi tespit edebilme

---

## Faz 5 — Bridge: Web LLM Extension (Tarayıcı Uzantısı)

**Süre:** 5-8 ay | **Statü:** ⚪ Konsept | **Piyasa değeri:** Yatırım seviyesi

### Vizyon

Dünyada ilk: Hangi web tabanlı LLM'i kullanırsanız kullanın (ChatGPT, Claude.ai, Gemini,
DeepSeek, vb.), o LLM'in MCP tool çağrıları sizin **local MCP sunucunuzdan** geçer ve
sizin güvenlik kurallarınıza tabi olur. Kategori yaratıcı bir ürün.

### Teknik Mimari

```
Browser Tab: chatgpt.com
       ↓
ChatGPT "read_file /Users/kerem/projeler/myapp/.env" istiyor
       ↓
Browser Extension (Chrome/Firefox)
       ↓
WebSocket → Local MCP Server (Claude Bridge)
       ↓
AI Evaluator → Rule Engine → allow/deny/ask
       ↓
    ├── allow → Dosya okunur, içerik ChatGPT'ye döner
    └── deny  → ChatGPT'ye "Bu dosyaya erişim izniniz yok" döner
```

### Özellik Detayları

#### 5.1 Tarayıcı Uzantısı

- **Chrome Extension** (Manifest V3) ve **Firefox Add-on**
- ChatGPT, Claude.ai, Gemini, DeepSeek, Mistral, Copilot web'i otomatik tanır
- Web LLM sayfasına inject edilen ince bir katman
- Tool call isteklerini yakalar → local MCP'ye yönlendirir
- Sonucu LLM'e şeffaf şekilde döndürür

#### 5.2 Protokol

```
Web LLM → Tool Call Request (JSON)
    ↓
Extension yakalar → WebSocket → claude-bridge daemon
    ↓
Güvenlik katmanı (Faz 1-4'teki tüm özellikler)
    ↓
Tool execution → Sonuç → WebSocket → Extension → Web LLM
```

#### 5.3 Kullanıcı Deneyimi

```
┌─────────────────────────────────────────────┐
│ chatgpt.com                         🔒 Bridge │
├─────────────────────────────────────────────┤
│                                             │
│  ChatGPT: Dosya sisteminizdeki            │
│  .env dosyasını okuyabilir miyim?         │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ ⚡ Claude Bridge                    │   │
│  │ ChatGPT şu dosyayı okumak istiyor:  │   │
│  │ /Users/kerem/projects/myapp/.env    │   │
│  │                                     │   │
│  │ Risk: Orta — ortam değişkenleri     │   │
│  │         içerebilir                  │   │
│  │                                     │   │
│  │ [İzin Ver] [Reddet] [Her Zaman İzin Ver │
│  │                     Bu Dizin İçin]      │
│  └─────────────────────────────────────┘   │
│                                             │
└─────────────────────────────────────────────┘
```

#### 5.4 Benzersiz Değer Teklifi

- **Hiçbir AI şirketi bunu sunmuyor:** Her AI kendi güvenlik modelini dayatıyor
- **Kullanıcı kontrolü:** Dosya erişimi her zaman sizin kurallarınızla
- **AI bağımsız:** Hangi AI'ı kullanırsanız kullanın, aynı güvenlik katmanı
- **Gelecek kanıtı:** Yeni AI'lar çıktıkça extension otomatik tanır

### Başarı Kriterleri

- [ ] Chrome Web Store ve Firefox Add-ons'ta yayında
- [ ] En az 5 web LLM platformu desteği
- [ ] Tool call interception gecikmesi < 300ms
- [ ] 10K+ haftalık aktif kullanıcı
- [ ] Herhangi bir güvenlik ihlali olmadan 6 ay çalışma

---

## Teknik Mimari — Bütünsel Bakış

```
┌──────────────────────────────────────────────────────────────────┐
│                    CLAUDE BRIDGE PLATFORM                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ MCP Interface │  │ WebSocket API │  │ Browser Extension    │  │
│  │ (Claude Desk, │  │ (Faz 5)       │  │ (Faz 5)             │  │
│  │  Cursor, VS..)│  │               │  │                      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │               │
│         └─────────────────┼──────────────────────┘               │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │  RULE ENGINE │  Faz 1                        │
│                    │  YAML/JSON   │                               │
│                    └──────┬──────┘                                │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │ AI EVALUATOR│  Faz 1                        │
│                    │ Multi-      │                               │
│                    │ Provider    │                               │
│                    └──────┬──────┘                                │
│                           │                                       │
│              ┌────────────┼────────────┐                         │
│              │            │            │                          │
│       ┌──────▼─────┐ ┌───▼────┐ ┌────▼──────┐                    │
│       │ AUDIT LOG   │ │ APPEAL │ │ ANOMALY   │  Faz 2,4          │
│       │ (Faz 2)    │ │ (Faz 2)│ │ DETECTION │                    │
│       └────────────┘ └────────┘ │ (Faz 4)   │                    │
│                                 └───────────┘                    │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │ ROLE & POLICY│  Faz 3                        │
│                    │ GitOps       │                               │
│                    └──────┬──────┘                                │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │ MCP TOOLS    │                               │
│                    │ file, shell, │                               │
│                    │ patch, idx.. │                               │
│                    └─────────────┘                                │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Fazlar Arası Bağımlılıklar

```
Faz 1 ──────→ Faz 2 ──────→ Faz 3 ──────→ Faz 4
  │              │              │              │
  │              │              │              │
  └──────────────┴──────────────┴──────────────┴──→ Faz 5
                                                  (Faz 1 yeterli,
                                                   tam güç için
                                                   Faz 4 gerekli)
```

- **Faz 2**, Faz 1'in AI evaluator'ına bağımlı (log'lanacak karar lazım)
- **Faz 3**, Faz 2'nin audit log'una bağımlı (rol bazlı log görünümü)
- **Faz 4**, Faz 2'nin audit log'undan beslenir (baseline için geçmiş veri)
- **Faz 5**, minimum Faz 1 ile çalışır, tam güvenlik için Faz 4 gerekir

---

## Go-to-Market Stratejisi

### Faz 1 Sonu — Bireysel Geliştiricilere Açılış

- **Kanal:** GitHub, Hacker News, Reddit (r/programming, r/MachineLearning)
- **Mesaj:** "Kendi MCP güvenlik kurallarınızı yazın, AI karar versin"
- **Metrik:** 500 GitHub star, 100 aktif kullanıcı
- **Fiyat:** Açık kaynak (MIT), SaaS opsiyonel

### Faz 2-3 Arası — Takım ve Startup'lara Genişleme

- **Kanal:** Product Hunt, YC communities, tech meetup'lar
- **Mesaj:** "Takımınızın AI kullanımını denetleyin, itiraz edin, güvende kalın"
- **Metrik:** 50 takım, $10K MRR
- **Fiyat:** $29-99/seat/ay

### Faz 4 — Enterprise ve Güvenlik Pazarı

- **Kanal:** Direct sales, güvenlik konferansları (Black Hat, RSAC)
- **Mesaj:** "AI destekli MCP güvenlik platformu — anomaly detection ile"
- **Metrik:** 10 enterprise müşteri, $500K ARR
- **Fiyat:** $50K-500K/yıl

### Faz 5 — Kategori Liderliği

- **Kanal:** TechCrunch, VentureBeat, AI güvenlik zirveleri
- **Mesaj:** "Hangi AI'ı kullanırsanız kullanın, güvenlik sizin kontrolünüzde"
- **Metrik:** 100K+ kullanıcı, Series A hazır
- **Fiyat:** Freemium + enterprise, yatırım ile ölçeklenme

---

## Risk ve Azaltma Matrisi

| Risk | Faz | Olasılık | Etki | Azaltma |
|------|-----|----------|------|---------|
| AI latency'si UX'i bozar | 1 | Orta | Yüksek | Cache, async, timeout fallback |
| Yanlış AI kararı | 1 | Yüksek | Orta | Appeal (Faz 2), kural override |
| API maliyeti sürdürülemez | 1 | Orta | Yüksek | Ollama/local model desteği |
| Hassas veri log'a sızması | 2 | Orta | Kritik | PII tarama, otomatik maskeleme |
| Policy marketplace'te zararlı kural | 3 | Orta | Yüksek | İnceleme süreci, verified badge |
| ML model false positive fazlalığı | 4 | Yüksek | Orta | Aşamalı rollout, kullanıcı feedback loop |
| Browser extension güvenlik açığı | 5 | Orta | Kritik | Kapsamlı güvenlik denetimi, bug bounty |
| Anthropic/Google ToS ihlali riski | 5 | Düşük | Kritik | Hukuki inceleme, ToS uyumlu tasarım |
| Rakip kopyalaması | Tümü | Yüksek | Orta | Hızlı iterate, community moat, patent? |

---

## Başarı Metrikleri (OKR Formatı)

### Objective 1: Kategori yarat ve lider ol
- **KR1:** GitHub'da MCP security kategorisinde #1 ol (Faz 2 sonu)
- **KR2:** 100+ kurumsal müşteri (Faz 4 sonu)
- **KR3:** 1M+ tool çağrısı değerlendirilmiş (Faz 2 sonu)

### Objective 2: Sürdürülebilir gelir modeli kur
- **KR1:** Faz 3'te $10K MRR
- **KR2:** Faz 4'te $500K ARR
- **KR3:** Faz 5'te Series A için $2M ARR pipeline

### Objective 3: Açık kaynak topluluğu inşa et
- **KR1:** 1,000 GitHub star (Faz 2 sonu)
- **KR2:** 50+ community kural paketi (Faz 3 sonu)
- **KR3:** 10+ aktif contributor (Faz 3 sonu)

---

## Teknik Borç ve Kalite Taahhütleri

Her fazın sonunda aşağıdakiler tamamlanmış olmalıdır:

- [ ] Test coverage > %80 (unit + integration)
- [ ] Dokümantasyon güncel (README, API docs, rule writing guide)
- [ ] Benchmark sonuçları kaydedilmiş (performans regresyonu yok)
- [ ] Güvenlik denetimi (her majör sürüm öncesi)
- [ ] `mypy` strict mod hatasız
- [ ] `ruff check` ve `black` uyumlu

---

## Ek — Mevcut Teknik Roadmap ile İlişki

Bu ürün roadmap'i, `docs/roadmap.md`'deki teknik aşamaları **kapsar ve yeniden
konumlandırır:**

| Teknik Aşama (eski) | Ürün Fazı (yeni) | Açıklama |
|---------------------|------------------|----------|
| Aşama 0 — Stabilizasyon | Faz 1 altyapısı | Güvenlik modeli zaten fail-closed, bunun üzerine AI katmanı inşa ediliyor |
| Aşama 1 — Slash Komutları | Ertelendi | Ürün pivotu nedeniyle daha düşük öncelik |
| Aşama 2 — İndeksleme | Faz 1-4 altyapısı | Codebase anlama, AI evaluator'ın daha iyi karar vermesi için kullanılacak |
| Aşama 3 — Agentic Loop | Faz 4 ile entegre | Self-healing loop'lar anomaly detection ile güvenli hale gelecek |
| Aşama 4 — Multi-Model | Faz 1'in çekirdeği | Multi-provider AI evaluator zaten Faz 1'de |
| Aşama 5 — Git Entegrasyonu | Faz 3'ün temeli | Policy-as-code = Git entegrasyonu |
| Aşama 6 — Web Arayüzü | Faz 5'e evrildi | Web arayüzü yerine browser extension + local daemon |

---

*Bu doküman her faz tamamlandığında güncellenir. Faz başlangıcında detaylı implementasyon
planı `tasks/active/` altında oluşturulur.*

---

## Ek B — Orijinal Kaynak (claudey_roadmap.html)

Bu roadmap'in çıkış noktası olan orijinal HTML taslağı:

```claudey code/claudey_roadmap.html
<style>
  .rm-wrap { padding: 16px 0 8px; font-family: var(--font-sans); }
  .rm-phase { display: flex; gap: 16px; margin-bottom: 8px; }
  .rm-left { display: flex; flex-direction: column; align-items: center; width: 28px; flex-shrink: 0; }
  .rm-dot { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 500; flex-shrink: 0; z-index: 1; }
  .rm-line { width: 2px; flex: 1; min-height: 12px; }
  .rm-card { flex: 1; border-radius: var(--border-radius-lg); border: 1px solid var(--color-border-tertiary); padding: 14px 16px 12px; margin-bottom: 8px; cursor: pointer; transition: border-color 0.15s; }
  .rm-card:hover { border-color: var(--color-border-secondary); }
  .rm-header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
  .rm-title { font-size: 14px; font-weight: 500; color: var(--color-text-primary); }
  .rm-duration { font-size: 11px; color: var(--color-text-tertiary); }
  .rm-badge { font-size: 10px; font-weight: 500; padding: 2px 7px; border-radius: 99px; margin-left: auto; }
  .rm-features { display: flex; flex-direction: column; gap: 5px; }
  .rm-feat { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: var(--color-text-secondary); line-height: 1.4; }
  .rm-feat-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
  .rm-divider { font-size: 11px; font-weight: 500; color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: 0.06em; padding: 12px 0 6px; }
  .rm-value { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--color-border-tertiary); }
  .rm-value-label { font-size: 11px; color: var(--color-text-tertiary); }
  .rm-value-num { font-size: 12px; font-weight: 500; }

  .p1-dot { background: #EEEDFE; color: #3C3489; }
  .p1-line { background: #CECBF6; }
  .p1-card { background: transparent; }
  .p1-feat-dot { background: #7F77DD; }
  .p1-badge { background: #EEEDFE; color: #3C3489; }
  .p1-val { color: #534AB7; }

  .p2-dot { background: #E1F5EE; color: #085041; }
  .p2-line { background: #9FE1CB; }
  .p2-feat-dot { background: #1D9E75; }
  .p2-badge { background: #E1F5EE; color: #085041; }
  .p2-val { color: #0F6E56; }

  .p3-dot { background: #FAEEDA; color: #633806; }
  .p3-line { background: #FAC775; }
  .p3-feat-dot { background: #BA7517; }
  .p3-badge { background: #FAEEDA; color: #633806; }
  .p3-val { color: #854F0B; }

  .p4-dot { background: #FAECE7; color: #4A1B0C; }
  .p4-line { background: #F5C4B3; }
  .p4-feat-dot { background: #D85A30; }
  .p4-badge { background: #FAECE7; color: #4A1B0C; }
  .p4-val { color: #993C1D; }

  .p5-dot { background: #E6F1FB; color: #042C53; }
  .p5-line { background: #B5D4F4; }
  .p5-feat-dot { background: #378ADD; }
  .p5-badge { background: #E6F1FB; color: #042C53; }
  .p5-val { color: #185FA5; }

  @media (prefers-color-scheme: dark) {
    .p1-dot { background: #26215C; color: #AFA9EC; }
    .p1-line { background: #3C3489; }
    .p1-badge { background: #26215C; color: #AFA9EC; }
    .p2-dot { background: #04342C; color: #5DCAA5; }
    .p2-line { background: #085041; }
    .p2-badge { background: #04342C; color: #5DCAA5; }
    .p3-dot { background: #412402; color: #EF9F27; }
    .p3-line { background: #633806; }
    .p3-badge { background: #412402; color: #EF9F27; }
    .p4-dot { background: #4A1B0C; color: #F0997B; }
    .p4-line { background: #712B13; }
    .p4-badge { background: #4A1B0C; color: #F0997B; }
    .p5-dot { background: #042C53; color: #85B7EB; }
    .p5-line { background: #0C447C; }
    .p5-badge { background: #042C53; color: #85B7EB; }
  }
</style>

<div class="rm-wrap">

  <div class="rm-phase">
    <div class="rm-left">
      <div class="rm-dot p1-dot">1</div>
      <div class="rm-line p1-line"></div>
    </div>
    <div class="rm-card p1-card">
      <div class="rm-header">
        <span class="rm-title">Core — AI Evaluation</span>
        <span class="rm-duration">1–2 ay</span>
        <span class="rm-badge p1-badge">şimdi başla</span>
      </div>
      <div class="rm-features">
        <div class="rm-feat"><div class="rm-feat-dot p1-feat-dot"></div><span>Kullanıcı tanımlı custom rules motoru (YAML/JSON tabanlı)</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p1-feat-dot"></div><span>Kural eşleşince API'daki AI'a isteği gönder → allow / deny / ask</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p1-feat-dot"></div><span>Local mod: kendi API key'i (Anthropic, OpenAI, vs.)</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p1-feat-dot"></div><span>SaaS mod: kendi endpoint'in üzerinden token ile bağlanma</span></div>
      </div>
      <div class="rm-value">
        <span class="rm-value-label">Potansiyel piyasa değeri</span>
        <span class="rm-value-num p1-val">$15K – $50K</span>
      </div>
    </div>
  </div>

  <div class="rm-phase">
    <div class="rm-left">
      <div class="rm-dot p2-dot">2</div>
      <div class="rm-line p2-line"></div>
    </div>
    <div class="rm-card">
      <div class="rm-header">
        <span class="rm-title">Trust — Audit & Appeal</span>
        <span class="rm-duration">2–3 ay</span>
        <span class="rm-badge p2-badge">enterprise kapısı</span>
      </div>
      <div class="rm-features">
        <div class="rm-feat"><div class="rm-feat-dot p2-feat-dot"></div><span>Her AI kararı loglanıyor: ne istendi, neden izin verildi/reddedildi</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p2-feat-dot"></div><span>Replay: aynı context tekrar gönderiliyor, karar tutarlı mı test ediliyor</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p2-feat-dot"></div><span>AI reddettiyse kullanıcı gerekçe yazıyor, AI yeniden değerlendiriyor</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p2-feat-dot"></div><span>Eskalasyon: itiraz yine reddedildiyse takım liderine gidiyor</span></div>
      </div>
      <div class="rm-value">
        <span class="rm-value-label">Potansiyel piyasa değeri</span>
        <span class="rm-value-num p2-val">$50K – $150K</span>
      </div>
    </div>
  </div>

  <div class="rm-phase">
    <div class="rm-left">
      <div class="rm-dot p3-dot">3</div>
      <div class="rm-line p3-line"></div>
    </div>
    <div class="rm-card">
      <div class="rm-header">
        <span class="rm-title">Team — Roles & Git Policy</span>
        <span class="rm-duration">3–4 ay</span>
        <span class="rm-badge p3-badge">seat-based gelir</span>
      </div>
      <div class="rm-features">
        <div class="rm-feat"><div class="rm-feat-dot p3-feat-dot"></div><span>junior / senior / CI / contractor rolleri, her rol için farklı kural seti</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p3-feat-dot"></div><span>policy.yaml Git'te yaşıyor — kural değişikliği = PR açmak demek</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p3-feat-dot"></div><span>Takım genelinde aynı MCP, farklı izinlerle çalışıyor</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p3-feat-dot"></div><span>Policy marketplace: kullanıcılar kendi kurallarını paylaşıyor</span></div>
      </div>
      <div class="rm-value">
        <span class="rm-value-label">Potansiyel piyasa değeri</span>
        <span class="rm-value-num p3-val">$100K – $300K</span>
      </div>
    </div>
  </div>

  <div class="rm-phase">
    <div class="rm-left">
      <div class="rm-dot p4-dot">4</div>
      <div class="rm-line p4-line"></div>
    </div>
    <div class="rm-card">
      <div class="rm-header">
        <span class="rm-title">Intelligence — Anomaly Detection</span>
        <span class="rm-duration">4–6 ay</span>
        <span class="rm-badge p4-badge">güvenlik ürünü</span>
      </div>
      <div class="rm-features">
        <div class="rm-feat"><div class="rm-feat-dot p4-feat-dot"></div><span>Her kullanıcının normal davranış paterni öğreniliyor</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p4-feat-dot"></div><span>Pattern dışı işlem tespit edildiğinde uyarı + otomatik kısıtlama</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p4-feat-dot"></div><span>Fiyatlandırma 10x artıyor — artık güvenlik aracısın</span></div>
      </div>
      <div class="rm-value">
        <span class="rm-value-label">Potansiyel piyasa değeri</span>
        <span class="rm-value-num p4-val">$300K – $1M+</span>
      </div>
    </div>
  </div>

  <div class="rm-phase">
    <div class="rm-left">
      <div class="rm-dot p5-dot">5</div>
    </div>
    <div class="rm-card">
      <div class="rm-header">
        <span class="rm-title">Bridge — Web LLM Extension</span>
        <span class="rm-duration">5–8 ay</span>
        <span class="rm-badge p5-badge">kategori yaratıcı</span>
      </div>
      <div class="rm-features">
        <div class="rm-feat"><div class="rm-feat-dot p5-feat-dot"></div><span>Chrome/Firefox extension: ChatGPT, Claude.ai, Gemini'yi yakalar</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p5-feat-dot"></div><span>Web LLM'in tool call isteği → local MCP'ye yönlendirilir → güvenlik katmanından geçer</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p5-feat-dot"></div><span>Hangi AI kullanırsan kullan, dosya erişimi senin kurallarınla</span></div>
        <div class="rm-feat"><div class="rm-feat-dot p5-feat-dot"></div><span>Dünyada bunu yapan başka araç yok</span></div>
      </div>
      <div class="rm-value">
        <span class="rm-value-label">Potansiyel piyasa değeri</span>
        <span class="rm-value-num p5-val">yatırım konuşulabilir seviye</span>
      </div>
    </div>
  </div>

</div>
```
