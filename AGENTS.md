# AGENTS.md

## Proje Amaci

Bu repo, Claude Desktop ve diger MCP istemcileri icin yerel dosya sistemi, shell ve kontrollu patch akislarini sunan Python tabanli bir MCP sunucusu olan `claude-bridge` projesidir.

## Repo Yapisi

- `src/claude_bridge/`: uygulama kodu
- `tests/`: pytest testleri
- `docs/`: kalici urun, operasyon ve roadmap dokumantasyonu
- `tasks/active/`: aktif gorev dosyalari
- `tasks/done/`: tamamlanmis gorev kayitlari
- `archive/`: eski planlar, notlar, fikirler ve artik kanonik olmayan belgeler
- `benchmarks/`: benchmark profilleri, baseline dosyalari ve benchmark'a ozel materyaller

## Kodlama Kurallari

- Python 3.8+ uyumlulugunu koru.
- Mevcut mimariye uy: CLI, MCP surface, tool implementations, config/state, indexing/relevance ve workflow katmanlarini karistirma.
- Naming stiline, moduler sinirlara ve mevcut kod duzenine uy.
- 100 karakter satir limiti, Black formatlama ve Ruff uyumu korunmali.
- Yeni veya degisen production kodu icin type hint kullan; `mypy` ayarlari siki.
- Gereksiz dependency, abstraction veya buyuk refactor ekleme.

## Gorev Yapma Akisi

1. Once ilgili dosyalari bul ve kisa bir plan cikar.
2. Sadece gorev icin gerekli dosyalari oku; gereksiz tarama yapma.
3. Degisiklik yapmadan once mevcut mimariye hangi katmanda uydugunu netlestir.
4. Sadece gerekli dosyalari degistir.
5. Mumkunse ilgili testi ekle veya guncelle.
6. Degisiklikten sonra uygun dogrulamayi calistir.
7. En sonda degisen dosyalari ve nedenlerini kisaca ozetle.

Buyuk refactor, tasima veya yapisal degisiklikten once mutlaka plan cikar ve etkisini kontrol et.

## Test / Lint / Build Komutlari

- Kurulum: `pip install -e .`
- Gelistirme bagimliliklari: `pip install -e .[dev]`
- Opsiyonel Tree-sitter: `pip install -e .[treesitter]`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Tip kontrol: `mypy src`
- Benchmark: `claude-bridge benchmark --project-dir . --path src --query "auth session login"`

## Shell ve Guvenlik Kurallari

- `shell_tools.py` icindeki guvenlik modeli korunmali.
- `sudo`, destructive `git` komutlari, `rm -r`, `curl|bash`, `wget|bash` benzeri kaliplari ekleme veya gevsetme.
- Shell komutlari acik, parcali ve `subprocess.run(..., shell=False)` modeline uygun olmali.
- Path sinirlari, approval akisi ve auto-approve davranisi sessizce degistirilmemeli.
- Gizli bilgi, yerel path ve kisisel config verilerini dokumantasyona ekleme.

## Gerekmedikce Okunmamasi Gereken Yerler

- `archive/`
- `tasks/done/`
- `venv/`
- `.git/`
- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `benchmarks/baselines/` ve `benchmarks/profiles/` sadece ilgili benchmark gorevlerinde

## Dokumantasyon Kurallari

- Kalici dokumanlari `docs/` altina koy.
- Yeni gorevler `tasks/active/`, tamamlananlar `tasks/done/` altina gitmeli.
- Eski ama silinmemesi gereken notlar `archive/` altina alinmali.
- Klasor tasima veya dosya yeniden adlandirmada ic linkleri kontrol et.
- `README.md` ve `AGENTS.md` root'ta kalmali.
