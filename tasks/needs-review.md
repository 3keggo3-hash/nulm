# Needs Review

Bu dosya, otomatik tasinmayan Markdown dosyalarini ve neden manuel gozden gecirme gerektirdiklerini listeler.

## Belirsiz Dosyalar

- `benchmarks/README.md`
  Neden: kalici dokumantasyon ama benchmark klasorune yakin durmasi da anlamli.
  Oneri: yerinde kalsin veya icerigi `docs/` altina tasinirken benchmark klasorunde kisa bir pointer birakilsin.

- `.aider.chat.history.md`
  Neden: tool gecmisi ve yerel oturum kaydi; repo dokumani olmaktan cok arac artifakti.
  Oneri: gerekirse `archive/` veya gitignore disi baska bir yere alinmali; otomatik tasima yapilmadi.

- `docs/strategic-roadmap.md`
  Neden: yeni `docs/product-roadmap.md` urun pivotunu kanonik hale getirdi; bu dosya
  artik stratejik kaynak fikirler ve eski konumlandirma notlari gibi okunmali.
  Oneri: icindeki halen gecerli fikirler `product-roadmap.md` veya
  `merged-execution-plan.md` icine tasindiktan sonra `archive/` altina alinabilir.

## Devam Eden Gorev Dosyalari

- `tasks/active/security-layer-execution-plan.md`
  Durum: devam ediyor. Yeni urun pivotu fazlara bolundu; ilk uygulanacak surec
  `Policy Decision Kernel` olarak secildi ve uygulamasi tamamlandi. `Rules Engine
  MVP`, `Audit, Replay ve Masking` ve `Security Hardening ve Bugfix Gate` surecleri
  tamamlandi. Siradaki surec `Optional AI Evaluator`.

- `tasks/active/doctor-and-competitive-analysis.md`
  Durum: devam ediyor. Doctor, optional dependency dokumani ve ilk rakip analizi
  buyuk olcude tamamlanmis; minimal/full extras mock ayrimi, CI validation sirasi ve
  uygulanabilir fikirlerin yeni tasklara bolunmesi maddeleri acik.

## Tamamlanmis / Referans Kabul Edilen Markdown Dosyalari

- `docs/competitive-analysis-desktopcommander.md`
  Durum: tamamlanmis rakip analizi; referans olarak `docs/` altinda kalabilir.

- `docs/performance-and-completion-audit.md`
  Durum: tamamlanmis audit raporu; uygulanabilir maddeler
  `docs/merged-execution-plan.md` icinde is paketlerine donusturuldugu icin referans
  olarak kalabilir.
