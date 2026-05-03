# Publishing Checklist

Bu dosya, projeyi herkese açık paylaşmadan önce hızlı son kontrol içindir.

## Güvenlik

- Gerçek `claude_desktop_config.json` repoda yok.
- Sadece placeholder kullanan `claude_desktop_config.snippet.json` repoda var.
- Kişisel path, kullanıcı adı veya ev dizini referansları temizlendi.
- `.env`, `*.local`, log ve özel config dosyaları ignore ediliyor.
- `rg -n "/Users/|API_KEY|SECRET|TOKEN|PASSWORD" .` taraması temiz.

## Policy / Audit / Replay

- `claude-bridge policy validate --path .claude-bridge-guard.json` basinca hata yok.
- `claude-bridge policy simulate --path .claude-bridge-guard.json --tool run_shell --param "command=ls"` calisiyor.
- `claude-bridge audit --last` son session'in kayitlarini gosteriyor.
- `claude-bridge replay --record-id <id>` mevcut bir kaydi yeniden degerlendiriyor.
- Audit kayitlari JSONL formatinda ve redaction uygulaniyor.
- Policy degisikliklerinde `claude-bridge policy diff` ile fark gorunuyor.

## Kurulum Deneyimi

- README ilk 2 dakikada kurulumu anlatıyor.
- `claude-bridge install ...` akışı README'de görünür.
- `pipx install claude-bridge` akışı açık.
- Repo'dan kurulum akışı açık.
- Örnek config kopyalanabilir ve anlaşılır.

## Değer Önerisi

- README içinde proje neden var sorusunun cevabı net.
- Rakip veya benzer araçlardan hangi noktalarda ayrıştığı belirtilmiş.
- Çok-kök workspace switching, workflow tool ve structured JSON outputs gibi ayırt edici özellikler görünür.

## Yayın Öncesi Son Kontrol

- Testler geçiyor.
- README ile gerçek davranış çelişmiyor.
- Placeholder URL'ler, örnek kullanıcı adları ve sahte repo adresleri temizlenmiş.
