# Active Task — Doctor Command and Competitive Analysis Foundation

## Amac

Claude Bridge icin ilk stabilizasyon sprintini baslatmak:

- ortam kaynakli test/mypy sorunlarini `claude-bridge doctor` ile gorunur yapmak
- dev setup ve validation akisini netlestirmek
- rakip kod incelemeleri icin tekrar edilebilir analiz formati olusturmak

## Kapsam

### 1. Doctor komutu

- [x] CLI yuzeyini belirle: `claude-bridge doctor`
- [x] `claude_bridge` import edilebiliyor mu kontrol et
- [x] Python version ve executable bilgisini raporla
- [x] Toolchain kontrolu: `pytest`, `ruff`, `black`, `mypy`
- [x] Dev plugin kontrolu: `pytest_asyncio`
- [x] Smart extra kontrolu: `tiktoken`, `charset_normalizer`
- [x] Tree-sitter extra kontrolu: `tree_sitter_language_pack`
- [x] Ciktiyi insan-okunur ve test edilebilir yap
- [x] Eksik dependency icin net kurulum onerisi ver

### 2. Testler

- [x] Doctor core logic icin unit test ekle
- [x] CLI smoke testi ekle veya mevcut CLI testlerine dahil et
- [ ] Minimal ortam ve full extras davranisini mock ile ayir

### 3. Dokumantasyon

- [x] README dev setup bolumunu genislet
- [x] Optional dependency pattern'ini dokumante et
- [ ] CI icin onerilen validation sirasi yaz

### 4. Competitive analysis

- [x] Kalici plan dokumani ekle: `docs/competitive-development-plan.md`
- [x] Rakip inceleme sablonu ekle: `docs/competitive-analysis-template.md`
- [x] Ilk rakip repo sec
- [x] Rakipteki shell/file/search/patch akisini incele
- [x] Claude Bridge karsiligini kod referanslariyla esle
- [ ] Uygulanabilir fikirleri yeni tasklara bol

## Mimari Sinirlar

- Doctor komutu CLI/config katmaninda kalmali; MCP tool davranisini sessizce
  degistirmemeli.
- Optional dependency kontrolleri import yan etkisi yaratmamali.
- Shell guvenlik modeli gevsetilmemeli.
- Rakip kodundan dogrudan kopya alinmamali; yalnizca tasarim fikirleri
  uyarlanabilir.

## Dogrulama

- `ruff check .`
- `mypy src`
- `pytest`

## Notlar

Bu task tamamlandiginda `tasks/done/` altina tasinmali ve ilgili roadmap
dokumanlari guncellenmelidir.
