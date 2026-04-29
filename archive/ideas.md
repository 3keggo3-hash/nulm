# Proje Yol Haritası Analizi

Bu doküman, sistemin mevcut durumunu ve gelecek planlarını (1-12 ay) içeren teknik yol haritasını özetler.

| Kategori | Şu An Var (Mevcut) | Kısa Vade (1-3 Ay) | Uzun Vade (6-12 Ay) |
| :--- | :--- | :--- | :--- |
| **Dosya Keşfi** | **AST sembolik indeks** <br> *Sadece .py ve .gd* | **JS/TS/Rust/Go desteği** <br> *Treesitter entegrasyonu* | **Embedding tabanlı arama** <br> *Semantic relevance* |
| **Otomasyon** | **run_agent_loop_step** <br> *Tek adım, manuel plan* | **Test-fix döngüsü** <br> *Snapshot + rollback* | **Multi-file refactor** <br> *Cross-file agent* |
| **Platform Desteği** | **macOS only** <br> *Claude Desktop MCP* | **Linux desteği** <br> *Cross-platform test* | **VSCode extension** <br> *IDE entegrasyonu* |
| **Güvenlik** | **Komut kara listesi** <br> *Pattern matching* | **İzin profilleri** <br> *Per-proje kural seti* | **Audit log + replay** <br> *Tam değişiklik geçmişi* |

---

### Teknik Analiz ve Notlar

* **Genişleme Stratejisi:** Mevcut yapı Python ve GDScript (Godot) odaklıyken, orta vadede sistem bağımsız dillerin (Rust, Go, JS) Treesitter entegrasyonu ile desteklenmesi planlanıyor.
* **Otomasyon Seviyesi:** Manuel kontrol gerektiren ajan döngüleri yerini, hata aldığında otomatik geri dönen (rollback) ve kendi testini yapan otonom bir yapıya bırakacak.
* **Entegrasyon:** Başlangıçta bir MCP (Model Context Protocol) aracı olarak macOS özelinde çalışan sistem, nihai hedef olarak tam bir VSCode eklentisi olmayı hedefliyor.
