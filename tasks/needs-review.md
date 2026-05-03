# Needs Review

Bu dosya, otomatik tasinmayan Markdown dosyalarini ve neden manuel gozden gecirme gerektirdiklerini listeler.

## Belirsiz Dosyalar

- `benchmarks/README.md`
  Neden: kalici dokumantasyon ama benchmark klasorune yakin durmasi da anlamli.
  Oneri: yerinde kalsin veya icerigi `docs/` altina tasinirken benchmark klasorunde kisa bir pointer birakilsin.

## Devam Eden Gorev Dosyalari

- `tasks/active/security-layer-execution-plan.md`
  Durum: devam ediyor. Yeni urun pivotu fazlara bolundu; Faz 1-7 implementasyonu
  tamamlandi, execution plan statuleri guncellenmeyi bekliyor.

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

## Arşivlendi

- `.aider.chat.history.md` → `archive/`
- `docs/strategic-roadmap.md` → `archive/`
