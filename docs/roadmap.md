# Claude Bridge — Teknik Yol Haritası

> **📌 Ürün pivotu:** 2026 Temmuz itibarıyla Claude Bridge, bir MCP geliştirici aracından
> **AI destekli güvenlik değerlendirme katmanına** dönüşmektedir. Yeni ürün vizyonu,
> gelir modeli ve stratejik yol haritası için [`docs/product-roadmap.md`](./product-roadmap.md)
> dokümanına bakın. Bu dosya, teknik implementasyon aşamalarını ve mevcut durumu belgeler.

> **Kural:** Bir özellik tamamlanmadan bir sonrakine geçilmez.
> **Ölçüt:** Her aşamanın kendi test seti olmak zorunda.

---

## Aşama 0 — Temel Stabilizasyon
**Durum:** Güvenlik modeli fail-closed hale getirildi, install akışı sadeleştirildi, hibrit parser mimarisi eklendi, çok dilli sembol çıkarımı genişletildi ve testler 185 passed seviyesine taşındı.

Tamamlanması gerekenler:
- [x] `run_shell` için onay akışı (tehlikeli komutları engelle)
- [x] Hata durumlarında Claude'a anlamlı mesaj dön (boş/crash yerine)
- [ ] macOS dışı platform testi (Linux önce, Windows sonra)
- [x] Büyük repo benchmark komutu
- [x] Tree-sitter var/yok entegrasyon matrisi
- [x] Relevans kalitesi için altın veri seti
- [x] README: kurulum, güvenlik uyarıları, kısıtlamalar
- [x] Claude Desktop log'larına yönelik kısa troubleshooting rehberi
- [x] `patch_file` için başarısız git commit durumunu kullanıcıya daha net raporla
- [x] Shell komutları için izin verilecek/engellenecek örnek komut matrisi oluştur
- [x] Uzun çalışan veya etkileşim isteyen shell komutlarında davranışı netleştir (`timeout`, TTY yok, stdin yok)
- [x] Araç çıktıları için yapılandırılmış hata formatı belirle (`code`, `message`, `details`)
- [x] Çok-kök workspace switching ve alt-klasöre geçiş desteği
- [x] Godot / GDScript gibi ikinci ekosistemlerde dosya keşfini iyileştir

**Çıktı:** Başkası kurup kullanabilmeli, çökmemeli.

**Bu aşamanın bitiş kriteri:**
- Claude Desktop'tan ilk kurulum 10 dakikanın altında tamamlanmalı
- Başarısız komutlarda kullanıcı ne yapacağını anlayabilmeli
- Aynı repo macOS ve Linux'ta aynı temel akışla çalışmalı
- Çok dilli indeksleme Tree-sitter kurulu ve kurulu değilken aynı test matrisiyle doğrulanmalı
- Relevans kalitesi en az küçük bir altın veri setiyle regresyona karşı korunmalı
- Büyük repo performansı tekrar çalıştırılabilir benchmark ile izlenebilmeli

### Kalan Başlıca Riskler

- Relevans skoru hâlâ anahtar kelime tabanlı; semantik intent ve cross-file ilişki kurma gücü sınırlı.
- Relevans skoru artık token ve field-aware olsa da hâlâ embedding veya graph tabanlı değil; derin semantik ilişki kurma gücü sınırlı.
- Büyük repo benchmark komutu eklendi, ama henüz CI içinde eşik bazlı performans kapısı yok.
- Linux ve Windows üzerinde gerçek uçtan uca Claude Desktop benzeri doğrulama eksik.
- Tree-sitter entegrasyonu opsiyonel olduğu için paket sürüm uyumsuzluklarında davranış farkı riski devam ediyor.
- İndeks cache'i süreç içi bellekte; çok büyük mono-repo senaryolarında disk cache veya incremental update gerekebilir.

---

## Aşama 1 — Slash Komutları
**Süre tahmini:** 1-2 hafta
**Teknik:** MCP `prompts` API

Komutlar:
- `/review` — seçili dosyayı veya dizini incele, sorunları listele
- `/optimize` — performans ve okunabilirlik önerileri
- `/test` — mevcut kodu için test yaz
- `/explain` — kodu Türkçe veya İngilizce açıkla
- `/commit` — değişiklikleri özetle, commit mesajı öner
- `/todo` — TODO yorumlarını tara, öncelik sırala

**Ölçüt:** Claude Desktop'ta `/` yazınca komutlar görünmeli.

**Mevcut durum:**
- [x] `/review` prompt prototipi
- [x] `/optimize` prompt prototipi
- [x] `/test` prompt prototipi
- [x] `/todo` prompt prototipi
- [x] `/explain` prompt prototipi
- [x] `/commit` prompt prototipi

**Eksik kararlar:**
- Prompt'lar yalnızca şablon mu dönecek, yoksa mevcut dosya/klasör seçimine göre parametreli mi olacak?
- `/review` ve `/test` gibi komutlar doğrudan tool çağrısı mı başlatacak, yoksa sadece iyi bir başlangıç prompt'u mu üretecek?

---

## Aşama 2 — Codebase İndeksleme
**Süre tahmini:** 3-4 hafta
**Teknik:** AST parsing + embedding veya basit sembolik indeks

Ne yapar:
- Proje açıldığında dosya yapısını tarar
- Fonksiyon/sınıf/import haritası çıkarır
- "Bu bug nerede olabilir?" sorusuna Claude hangi dosyaları okuyacağını kendisi seçer
- `.gitignore` ve büyük dosyaları otomatik atlar

**Kritik sorun:** Embedding kullanılacaksa hangi model? Lokal (nomic-embed) mi, API mi? API kullanılırsa maliyet var.

**Ölçüt:** 10.000+ satır kod tabanında Claude doğru dosyayı ilk seferde bulmalı.

**Mevcut durum:**
- [x] İlk sembolik indeks prototipi (`index_codebase`)
- [x] Python `ast` ile fonksiyon/sınıf/import çıkarımı
- [x] Temel skip listesi (`.git`, `venv`, `__pycache__`, `node_modules`, cache klasörleri)
- [x] İlk sorgu aracı (`find_relevant_files`)
- [x] Workflow keşfinde indeks sonuçlarını kullanma (`run_workflow(..., execute=true)`)
- [x] `.gitignore` dosyasını gerçek anlamda yorumlama
- [x] İndeksi saklama / yeniden kullanma
- [x] İçerik düzeyi arama ve daha iyi relevans puanlaması
- [x] Policy kararlarını taşıyan maskelenmiş audit kayıtları, CLI filtreleri ve deterministic rule
  replay eklendi

**Eksik teknik kararlar:**
- İndeks ne zaman güncellenecek: başlangıçta mı, dosya değişince mi, manuel komutla mı?
- İndeks dosyası repo içinde mi tutulacak, cache dizininde mi?
- İlk sürüm embedding'siz sembolik indeks ile mi başlamalı?

---

## Aşama 3 — Agentic Loop
**Süre tahmini:** 1-2 ay
**Teknik:** Tool call → sonuç → tekrar tool call döngüsü
**Durum:** ✅ Tamamlandı

Ne yapar:
- "Şu testi geçir" denir
- Claude kodu okur, değiştirir, testi çalıştırır
- Test geçmezse hatayı okur, tekrar düzeltir
- Geçene kadar veya max iterasyona ulaşana kadar devam eder

**Güvenlik sınırları (tamamlandı):**
- [x] Maksimum iterasyon sayısı
- [x] Toplam dosya değiştirme limiti
- [x] Tek adımda çalıştırılabilecek shell komut seti
- [x] Geri alma politikası: başarısız durumda snapshot
- [x] Validation command ile her adım doğrulama
- [x] Result compaction ve session summary

---

## Aşama 4 — Multi-Model Yönlendirme
**Durum:** ✅ Tamamlandı
**Süre tahmini:** 2-3 hafta (Aşama 3 sonrası)
**Teknik:** Görev sınıflandırıcı + model seçici

Mantık:
- Basit soru / açıklama → Haiku (hızlı, ucuz)
- Kod yazma / refactor → Sonnet
- Mimari karar / karmaşık analiz → Opus
- Kullanıcı override edebilir: `--model opus`

**Kritik sorun:** Claude Desktop şu an model seçimini kullanıcıya bırakıyor, API üzerinden otomatik yönlendirme için ayrı bir katman gerekiyor.

**Ölçüt:** Aynı kalitede çıktı için maliyet %40+ düşmeli (ölçülebilir).

**Not:** Bu aşama ancak ayrı bir API orkestrasyon katmanı varsa anlamlı. Sadece Claude Desktop içinde çalışıyorsak ertelenebilir.

---

## Aşama 5 — Git Entegrasyonu
**Süre tahmini:** 2-3 hafta
**Durum:** ✅ Tamamlandı

Ne yapar:
- [x] Her agentic loop adımından önce otomatik commit (güvenlik ağı)
- [x] `git diff` çıktısını Claude'a besle
- [x] Git status, log, branch operations
- [ ] PR açıklaması otomatik yaz
- [ ] Conflict resolution öner

**Ölçüt:** Agentic loop bir şeyi bozarsa tek komutla geri dönülebilmeli.

---

## Aşama 6 — Web Arayüzü (Opsiyonel)
**Durum:** ✅ Tamamlandı
**Süre tahmini:** 3-4 hafta
**Koşul:** Aşama 1-3 stabil olmadan başlama.

Ne yapar:
- Claude Desktop yerine tarayıcıdan kullan
- Oturum geçmişi
- Proje bazlı context yönetimi
- Takım kullanımı (çok kullanıcı)

**Kritik uyarı:** Bu noktada Claude Code ile doğrudan rekabete girilir. Anthropic ToS tekrar incelenmeli.

---

## Hiçbir Zaman Yapılmayacaklar

- API anahtarını kullanıcıdan isteyip kendi sunucunda saklama — güvenlik felaketi
- Model ağırlıklarını indirip çalıştırma — lisans ihlali
- Claude'un çıktısını başka bir servise satma — açık ToS ihlali

---

## Öncelik Matrisi

| Aşama | Zorluk | Kullanıcı Değeri | Öncelik |
|-------|--------|-----------------|---------|
| 0 — Stabilizasyon | Düşük | Yüksek | **Şimdi** |
| 1 — Slash Komutları | Düşük | Orta | **Sonra** |
| 2 — İndeksleme | Yüksek | Yüksek | 3. sıra |
| 3 — Agentic Loop | Çok Yüksek | Çok Yüksek | 4. sıra |
| 4 — Multi-Model | Orta | Orta | 5. sıra |
| 5 — Git | Orta | Yüksek | 6. sıra |
| 6 — Web Arayüzü | Yüksek | Orta | Son |

---

## Stabilizasyon Roadmap

1. 2-3 büyük gerçek repo üzerinde baseline benchmark sonucu kaydet
2. Altın relevans veri setini hata raporlarından gelen gerçek sorgularla büyütmeye devam et
3. Benchmark çıktıları için repo-bazlı daha sıkı eşikler tanımla
4. Linux smoke hattını gerçek Claude Desktop benzeri uçtan uca doğrulamaya yükselt
5. Windows hattını güvenle ekle
6. İndeks cache'i ve relevans skoru için incremental/perf iyileştirme turuna gir

### Bir Sonraki Somut İşler
- Benchmark sonuçlarını gerçek açık kaynak repo örnekleriyle belgeye dök
- Relevans veri setine Java, Ruby ve karma mono-repo vakaları ekle
- `find_relevant_files` için sorgu sonucu cache veya token bazlı ön-indeksleme dene
- Linux üzerinde ilk çapraz platform doğrulamasını yap
- CI tarafında opsiyonel Tree-sitter bağımlılığı için ayrı job ekle

---

*Bu dosya her aşama tamamlandığında güncellenir.*
