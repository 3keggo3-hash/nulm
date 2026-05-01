# Docs

Bu klasor, proje icin kalici ve referans niteligindeki dokumantasyonu toplar.

## Durum Siniflandirmasi

### Aktif / Kanonik

Bu belgeler mevcut urun yonu, teknik davranis veya operasyonel akis icin birincil
referans kabul edilir.

- `product-roadmap.md`
  Yeni urun vizyonu: Claude Bridge'in AI destekli MCP guvenlik degerlendirme
  katmanina pivotunu tanimlar.
- `roadmap.md`
  Teknik implementasyon asamalari ve mevcut teknik durum. Yeni urun vizyonu icin
  `product-roadmap.md` dosyasina baglanir.
- `merged-execution-plan.md`
  Uygulanabilir teknik backlog, bagimlilik sirasi ve delegasyon paketleri.
- `known-issues-and-improvements.md`
  Bilinen eksikler, riskler ve iyilestirme onerileri.
- `optional-dependencies.md`
  Opsiyonel dependency pattern'i ve doctor kontrolleri icin kanonik rehber.
- `publishing-checklist.md`
  Yayinlama ve release oncesi kontrol listesi.
- `competitive-development-plan.md`
  Rakiplerden ogrenilenleri mimariye uygun is planina donusturen uzun vadeli
  gelistirme plani.
- `competitive-analysis-template.md`
  Yeni rakip analizleri icin tekrar kullanilabilir sablon.

### Tamamlanmis / Referans

Bu belgeler ana plan degil; tamamlanmis analiz, audit veya tarihsel karar kaydi
olarak saklanir.

- `competitive-analysis-desktopcommander.md`
  DesktopCommanderMCP karsilastirmasi ve bulgulari.
- `performance-and-completion-audit.md`
  Performans, completion ve UX audit raporu. Icerigindeki uygulanabilir maddeler
  `merged-execution-plan.md` icinde is paketlerine donusturulmustur.

### Devam Eden / Gorev Takibi

Gorev yasam dongusu `docs/` altinda tutulmaz. Aktif isler ve tamamlanan kayitlar:

- `tasks/active/`
- `tasks/done/`
- `tasks/needs-review.md`

### Inceleme veya Arsiv Adayi

Bu belgeler dogrudan silinmemeli; yeni pivotla iliskileri netlestirilip gerekirse
`archive/` altina tasinmalidir.

- `strategic-roadmap.md`
  Yeni `product-roadmap.md` tarafindan buyuk olcude yeniden konumlandirildi.
  Icindeki fikirler degerli, ama kanonik urun plani olarak okunmamali.

## Klasor Kurallari

Buraya su tip belgeler girer:

- urun veya teknik dokumantasyon
- audit ve performans raporlari
- roadmap ve strateji dokumanlari
- yayinlama, operasyon veya kullanim rehberleri

Buraya gorev takibi veya gecici calisma notu koyma:

- aktif isler `tasks/active/`
- tamamlanan gorev kayitlari `tasks/done/`
- eski planlar ve artik kanonik olmayan notlar `archive/`

Not:

- `benchmarks/README.md` benchmark klasoruyle birlikte duran ozel bir kullanim
  rehberidir; benchmark materyaline yakin kalmasi gerekip gerekmedigi
  `tasks/needs-review.md` icinde izlenir.
