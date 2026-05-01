# Claude Bridge — Competitive Development Plan

Bu dokuman, Claude Bridge'i hem daha saglam bir yerel MCP katmani yapmak hem de
rakip projelerden sistematik sekilde ogrenerek urun yonunu guclendirmek icin
uygulanabilir uzun vadeli plani tanimlar.

## Hedef

Claude Bridge'in konumu:

- guvenli yerel dosya ve shell erisimi
- aciklanabilir kod kesfi ve relevance
- kontrollu patch ve validation akisi
- MCP istemcileri icin tekrar kullanilabilir workflow katmani

Uzun vadeli basari olcutu:

- yeni gelistirici tek komutla ortam sagligini gorebilmeli
- CI ve yerel dogrulama ayni kalite kapilarini kosmali
- buyuk repolarda dogru dosya secimi olculebilir sekilde iyilesmeli
- shell, patch ve workflow islemleri audit edilebilir olmali
- rakiplerden gelen fikirler kopyalanmadan, proje mimarisine uygun ozgun
  tasarimlara donusmeli

## Calisma Hatlari

### Hat 1 — Stabilizasyon ve Developer Experience

Amac, "kod mu bozuk, ortam mi bozuk?" sorusunu hizla cevaplamak.

Yapilacaklar:

- `claude-bridge doctor` komutu
- editable install ve dev extras kontrolu
- `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy` toolchain kontrolu
- opsiyonel `smart` ve `treesitter` dependency raporu
- README icinde net dev setup ve validation akisi
- CI icin minimal ve full extras profilleri

Basari olcutleri:

- `claude-bridge doctor` eksik kurulumu net aksiyonla raporlar
- `mypy src`, `ruff check .`, `pytest` ayni dokumante ortamda temiz calisir
- opsiyonel dependency eksikligi false-negative uretmez

### Hat 2 — Optional Dependency ve Typing Guardrails

Amac, opsiyonel ozelliklerin runtime fallback ve static typing tarafinda ayni
kalitede davranmasini saglamak.

Yapilacaklar:

- opsiyonel importlar icin tek pattern belirlemek
- `tiktoken`, `charset_normalizer`, Tree-sitter ve benzeri importlari bu pattern'e
  uydurmak
- availability raporlarini merkezi hale getirmek
- mypy override'larini dar kapsamli ve bilincli tutmak

Basari olcutleri:

- core kurulumda mypy import hatasi yok
- full extras kurulumda ayni API davranisi korunur
- yeni opsiyonel dependency eklemek icin dokumante pattern vardir

### Hat 3 — Security, Audit ve Trust Layer

Amac, Claude Bridge'i sadece arac degil guvenilir yurutme katmani yapmak.

Yapilacaklar:

- tool call audit logging
- shell risk skoru ve risk nedenleri
- approval policy presetleri
- path boundary ve destructive command testlerini genisletmek
- patch oncesi/sonrasi structured summary
- dry-run veya simulation modu

Basari olcutleri:

- kullanici son oturumda hangi tool'un ne yaptigini gorebilir
- tehlikeli shell kaliplari fail-closed davranir
- audit kaydi gizli bilgi sizdirmadan yararli debugging bilgisi tasir

### Hat 4 — Indexing, Relevance ve Code Intelligence

Amac, buyuk repolarda dogru dosyalari daha az okuma ile bulmak.

Yapilacaklar:

- disk cache ve incremental index
- cache invalidation stratejisi
- relevance sonucuna `selection_reason` eklemek
- Tree-sitter sembollerini skora daha acik sekilde katmak
- golden relevance datasetini buyutmek
- opsiyonel semantic/graph relevance prototipi

Basari olcutleri:

- benchmark ve golden dataset ile relevance regresyonu yakalanir
- kullanici her secilen dosyanin neden secildigini gorebilir
- buyuk repo taramasinda tekrar calistirma maliyeti belirgin azalir

### Hat 5 — Workflow ve Agent Loop Urunlestirme

Amac, inspect -> plan -> patch -> validate -> summarize akisini kontrollu urun
davranisina cevirmek.

Yapilacaklar:

- agent loop icin dosya degisiklik limiti
- validation command allowlist
- patch risk summary
- iteration budget
- basarisiz validation icin next-step onerisi
- gorev sonunda structured completion summary

Basari olcutleri:

- basit failing test isleri insan mudahalesi olmadan guvenli sinirlarla cozulur
- her iteration ne okudu, ne degistirdi, ne calistirdi bilgisini dondurur
- sonsuz dongu ve genis refactor riski sinirlanir

### Hat 6 — Competitive Analysis

Amac, rakiplerin cozumlerini mimari fikir olarak incelemek ve proje uygunluguna
gore ozgun islere cevirmek.

Inceleme sorulari:

- Ayni problemi biz hangi modulde cozuyoruz?
- Rakip hangi abstraction veya veri modelini kullanmis?
- Guvenlik varsayimlari neler?
- Bizim mevcut mimariye uyarlarsak hangi dosyalar etkilenir?
- Alinacak fikir ozellik mi, altyapi mi, test stratejisi mi?

Oncelikli karsilastirma alanlari:

- shell execution ve approval modeli
- file search, fuzzy matching ve patch guvenilirligi
- long-running process yonetimi
- audit logging
- onboarding ve doctor/setup komutlari
- indexing, relevance ve symbol extraction
- workflow orchestration

Basari olcutleri:

- her rakip incelemesi standart bir tabloyla biter
- "kopyala" yerine "uyarlanabilir fikir" ve "uygulama plani" cikar
- secilen fikirler task dosyalarina veya roadmap'e baglanir

## Fazlar

### Faz 1 — Bootstrap ve Doctor

Kapsam:

- `claude-bridge doctor`
- dev setup dokumani
- optional dependency raporu
- ilk competitive analysis template

Cikti:

- ortam kaynakli test/mypy sorunlari tek komutla aciklanir
- rakip incelemeleri tekrar edilebilir formata kavusur

### Faz 2 — Trust Layer

Kapsam:

- audit logging
- approval presetleri
- shell/security test matrisi
- dry-run tasarimi

Cikti:

- kullanici yapilan islemleri denetleyebilir
- riskli islemler daha acik ve olculebilir hale gelir

### Faz 3 — Relevance Engine v2

Kapsam:

- disk cache
- incremental update
- selection reason
- golden dataset genisletme
- benchmark threshold tasarimi

Cikti:

- buyuk repo deneyimi hizlanir
- dosya secimleri daha aciklanabilir olur

### Faz 4 — Workflow Productization

Kapsam:

- agent loop guardrail'leri
- validation orchestration
- structured run artifacts
- patch risk summary

Cikti:

- Claude Bridge daha guvenli ve tekrarlanabilir bir coding workflow katmani olur

### Faz 5 — Advanced Competitive Features

Kapsam:

- fuzzy patch matching
- long-running process stratejisi
- semantic/graph relevance prototipi
- cross-platform smoke suite

Cikti:

- rakiplerle karsilastirmada sadece eslesen degil ayrisan ozellikler olusur

## Ilk Sprint

1. `claude-bridge doctor` tasarimini netlestir.
2. CLI komutu ve testlerini ekle.
3. README dev setup ve validation bolumunu guclendir.
4. Optional dependency import pattern'ini dokumante et.
5. Competitive analysis template'i kullanarak ilk rakip incelemesini yap.

## Bakim Kurali

- Bu dokuman stratejik ve kalici plandir.
- Aktif uygulama isleri `tasks/active/` altinda takip edilir.
- Tamamlanan isler `tasks/done/` altina tasinir.
- Rakip inceleme notlari kalici deger tasiyorsa `docs/` altina, geciciyse
  `tasks/active/` icindeki ilgili task dosyasina yazilir.
