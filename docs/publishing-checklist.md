# Publishing Checklist

Bu dosya, projeyi herkese açık paylaşmadan önce hızlı son kontrol içindir.

## Güvenlik

- Gerçek `claude_desktop_config.json` repoda yok.
- Sadece placeholder kullanan `claude_desktop_config.snippet.json` repoda var.
- Kişisel path, kullanıcı adı veya ev dizini referansları temizlendi.
- `.env`, `*.local`, log ve özel config dosyaları ignore ediliyor.
- `rg -n "/Users/|API_KEY|SECRET|TOKEN|PASSWORD" .` taraması temiz.

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
