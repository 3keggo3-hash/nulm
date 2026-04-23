# Claude Bridge

> Claude Pro aboneliğiniz varsa, Claude Code olmadan Claude Code deneyimi yaşayın.

Claude Bridge, Claude.ai web arayüzüne yerel dosya sistemi ve terminal erişimi kazandıran hafif bir araçtır. `pipx` ile kurulur, tek komutla çalışır, hiçbir karmaşık yapılandırma gerektirmez.

## Özellikler

- 📁 **Dosya Okuma**: `[READ: dosya.py]` ile yerel dosyaları Claude'a gösterin
- 📂 **Klasör Listeleme**: `[LIST: src/]` ile proje yapısını keşfedin
- 🖥️ **Terminal Çalıştırma**: `[SHELL: pytest]` ile testleri çalıştırın
- ✏️ **Akıllı Düzenleme**: `[PATCH: ...]` ile sadece değişen satırları uygulayın
- 🔒 **Güvenli**: Her işlem öncesinde onay, tehlikeli komutlar engellenir
- 🌿 **Git Entegrasyonu**: Her değişiklik otomatik commit'lenir

## Kurulum

### Adım 1: Kurulum

```bash
pipx install claude-bridge
```

### Adım 2: Sunucuyu Başlatın

```bash
claude-bridge start
```

Bu komut:
- Yerel sunucuyu başlatır (localhost:7337)
- Bookmarklet kodunu ekrana yazdırır
- Claude için sistem promptunu gösterir

### Adım 3: Claude.ai'yi Yapılandırın

1. **Bookmarklet**: Ekrana gelen JavaScript kodunu tarayıcınızın yer imlerine sürükleyin
2. **Sistem Promptu**: Claude.ai'daki Projects > Project Settings > Project Instructions'a gidin ve ekrana gelen promptu yapıştırın

Hepsi bu kadar! 3-5 dakika içinde çalışmaya hazırsınız.

## Kullanım

Claude.ai'da normal konuşurken:

1. Claude bir dosyayı görmek isterse `[READ: src/player.py]` yazar
2. Bookmarklet'e tıklayın, dosya içeriği Claude'a otomatik gider
3. Claude değişiklik önerirse, yine bookmarklet'e tıklayın
4. Değişiklikler otomatik uygulanır, git commit atılır

## Güvenlik

- **Yerel-only**: Sunucu hiçbir zaman dış internete bağlanmaz
- **Açık kaynak**: ~200 satır, MIT lisansı, herkes denetleyebilir
- **Onay zorunluluğu**: Hiçbir değişiklik onaysız uygulanmaz
- **İzin sistemi**: Sadece belirlenen klasöre erişilir
- **Komut filtresi**: `rm -rf`, `sudo`, `chmod` gibi komutlar engellenir

## Sistem Gereksinimleri

- Python 3.8+
- Modern bir web tarayıcısı (Chrome, Firefox, Safari, Edge)
- pipx (kurulum için)

## Lisans

MIT Lisansı — Detaylar için [LICENSE](LICENSE) dosyasına bakın.

## Katkıda Bulunma

Katkılar memnuniyetle karşılanır! Lütfen önce bir issue açın.

---

**Not**: Bu proje Anthropic'in resmi bir ürünü değildir. Claude.ai'yı normal kullanım şartları dahilinde kullanır.
