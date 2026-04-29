# Benchmarking

Claude Bridge artık indeksleme ve relevans regresyonlarını ölçmek için tekrar çalıştırılabilir bir benchmark komutu içerir.

## Hızlı kullanım

```bash
claude-bridge benchmark --project-dir . --path src --query "auth session login"
```

Makine-okunur çıktı için:

```bash
claude-bridge benchmark --project-dir . --path src --query "auth session login" --json
```

Profil dosyasıyla çalıştırmak için:

```bash
claude-bridge benchmark --project-dir /path/to/repo --profile-file benchmarks/profiles/django_auth.json
```

## Baseline karşılaştırması

Bir baseline dosyası verirseniz komut süre, minimum dosya sayısı ve beklenen üst sıraları kontrol eder:

```bash
claude-bridge benchmark \
  --project-dir . \
  --path src \
  --query "login auth session" \
  --baseline-file benchmarks/example_baseline.json
```

Profil kullanıyorsanız `baseline_file` profil içinden de otomatik alınabilir.

## Ne ölçülüyor?

- ilk indeksleme süresi
- tekrar edilen relevans sorgusu süreleri
- kullanılan parser backend'leri
- üst sıralı sonuçlar

## Pratik öneri

- Aynı benchmark'ı birkaç büyük repoda düzenli çalıştırın.
- Tree-sitter kurulu ve kurulu değil varyantlarını ayrı izleyin.
- Gerçek bug raporlarından gelen sorguları altın veri setine ekleyin.
- `benchmarks/profiles/` altındaki açık kaynak repo profillerini yerel clone'larınızla doldurup baseline'ları gerçek ölçümlerle güncelleyin.
