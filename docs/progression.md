# Claude Bridge — Geliştirme İlerlemesi

Bu doküman proje geliştirme aşamalarını ve mevcut durumunu takip eder.

---

## ✅ Tamamlanan Aşamalar

### Phase 0: Planlama ve Tasarım
- [x] Proje fikri ve hedef kitlesi tanımlandı
- [x] Mimari (3 bileşen) belirlendi
- [x] Tool Protocol komutları tasarlandı
- [x] Güvenlik modeli oluşturuldu
- [x] Sürüm planı (V1/V2/V3) hazırlandı

---

## 🚧 Aktif Geliştirme

### Phase 1: V1 — Temel Sürüm

#### Bileşen 1: Yerel Sunucu (Local Bridge Server)
- [x] Python projesi yapılandırması (pyproject.toml)
- [x] ~~FastAPI sunucu (localhost:7337)~~ ➜ **MCP Server** (stdio)
- [x] CLI komutları (start, version)
- [x] MCP Tool tanımları (`read_file`, `list_directory`, `run_shell`, `patch_file`)
- [x] READ komutu implementasyonu
- [x] LIST komutu implementasyonu
- [x] SHELL komutu implementasyonu (güvenlik filtreleri ile)
- [x] PATCH komutu implementasyonu (SEARCH/REPLACE motoru)
- [x] Onay sistemi (async approval handler, test edilebilir)
- [x] Git entegrasyonu (otomatik commit, test edilebilir)
- [x] İzin sistemi (klasör erişim kısıtlaması)
- [x] Yapılandırılmış tool yanıt formatı (`ok`, `message`, `details`, `code`)
- [x] MCP prompt prototipleri (`review`, `optimize`, `test`, `todo`, `explain`, `commit`)
- [x] Workflow tool (`run_workflow`) ve güvenli `execute=true` keşif modu
- [x] Sembolik Python indeksleme prototipi (`index_codebase`)
- [x] İndeks tabanlı ilgili dosya seçimi (`find_relevant_files`)
- [x] Workflow keşfinde ilgili dosya önerilerini kullanma
- [x] Çoklu çalışma alanı kökleri ve proje kökü değiştirme (`workspace_status`, `switch_project_root`)
- [x] GDScript (`.gd`) kaynaklarını indeksleme ve relevans aramada kullanma

#### Bileşen 2: MCP Entegrasyonu
- [x] `mcp` Python SDK entegrasyonu (`FastMCP`)
- [x] Stdio transport desteği (Claude Desktop uyumlu)
- [x] Claude Desktop'ta canlı test
- [x] Claude Desktop config snippet üretimi ve env tabanlı kurulum akışı
- [x] Client-managed approval ile stdio kanalını temiz tutma

#### Bileşen 3: Sistem Promptu
- [x] Claude için sistem promptu taslağı
- [x] Tool Protocol kullanım talimatları
- [x] Örnek diyaloglar ve workflow
- [x] Sistem promptu test edildi (doğru formattalar var)

#### Dokümantasyon
- [x] README.md (kurulum ve kullanım)
- [x] README.md MCP kurulum talimatları eklendi
- [x] Güvenlik dokümantasyonu — README.md ve plan.md'de
- [x] README.md troubleshooting ve shell komut matrisi eklendi
- [x] Claude Desktop için env tabanlı güvenilir config üretimi (`claude-bridge setup`)
- [x] MCP stdio başlangıcında stdout temizliği (`claude-bridge start` sessiz akış)
- [x] Paylaşım öncesi güvenlik rehberi ve yayın checklist'i

---

## 📋 Yapılacaklar (Backlog)

### V2 — Akıllı Bağlam
- [x] Proje indeksleme ve sembol tarama
- [x] İlgili dosyaları otomatik tespit
- [ ] Kod hiyerarşisi analizi
- [ ] Daha güçlü dil desteği ve daha derin içerik arama

### V3 — Masaüstü Arayüzü
- Küçük GUI uygulaması
- Proje klasörü seçici
- Diff görünümü
- Onay butonları

### V4 — Claude Code Benzeri Davranış
- [ ] Kontrollü test-fix loop
- [ ] Maksimum iterasyon ve dosya değişim limitleri
- [ ] Her adım için snapshot / rollback politikası
- [ ] "Tek bir sabit gördüm, iş bitti" yerine çapraz dosya ve override kontrol alışkanlığı

---

## 🎯 V1 Milestone Hedefleri

| Özellik | Durum | Notlar |
|---------|-------|--------|
| pipx ile kurulum | ✅ | pyproject.toml hazır |
| CLI temel yapısı | ✅ | start/version komutları |
| Bookmarklet çalışması | ✅ | JS kodu + regex testleri geçti |
| READ komutu | ✅ | Dosya okuma + path traversal koruması |
| LIST komutu | ✅ | Klasör listeleme + güvenlik sınırı |
| SHELL komutu | ✅ | Onaylı terminal + tehlikeli komut filtreleme |
| PATCH komutu | ✅ | SEARCH/REPLACE + syntax kontrolü + line-ending normalize |
| Git entegrasyonu | ✅ | Otomatik commit + init + test edilebilir |
| Onay sistemi | ✅ | Async approval handler + mock testleri |
| Syntax kontrolü | ✅ | Python ast modülü + testleri |

**Durum Açıklamaları:**
- ✅ Tamamlandı
- 🔄 Devam ediyor
- ⏳ Başlamadı
- ❌ Engellendi

---

## 📝 Son Güncelleme

**Tarih:** 2026-04-28  
**Aktif Çalışma:** Approval akışı stdio için fail-closed güvenli hale getiriliyor; git commit bağımlılığı açık enjeksiyona taşınıyor; dokümantasyon gerçek davranışla hizalanıyor  
**Durum:** 153/153 test geçti; MCP tool seti, bounded workflow araçları, çok-kök switching ve Python/GDScript indeksleme doğrulandı  
**Sonraki Adım:** Approval modelini Claude Desktop kurulum akışında daha görünür hale getir; ardından workflow/indexing tarafında dil kapsamını Python ve GDScript dışına genişletecek mimariyi tasarla
