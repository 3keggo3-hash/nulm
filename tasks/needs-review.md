# Needs Review

Bu dosya, otomatik tasinmayan Markdown dosyalarini ve neden manuel gozden gecirme gerektirdiklerini listeler.

## Belirsiz Dosyalar

- `benchmarks/README.md`
  Neden: kalici dokumantasyon ama benchmark klasorune yakin durmasi da anlamli.
  Oneri: yerinde kalsin veya icerigi `docs/` altina tasinirken benchmark klasorunde kisa bir pointer birakilsin.

- `.aider.chat.history.md`
  Neden: tool gecmisi ve yerel oturum kaydi; repo dokumani olmaktan cok arac artifakti.
  Oneri: gerekirse `archive/` veya gitignore disi baska bir yere alinmali; otomatik tasima yapilmadi.
