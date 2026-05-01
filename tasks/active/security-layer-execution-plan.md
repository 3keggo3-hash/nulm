# Active Task: Security Layer Execution Plan

## Amac

Claude Bridge'in yeni urun pivotunu uygulanabilir is paketlerine bolmek:

- buyuk plani fazlara ve sureclere ayirmak
- ilk sureci hemen baslatilabilir hale getirmek
- ilk surecin icindeki isleri zorluk, bagimlilik ve dosya sahipligine gore ayirmak
- farkli araclara kodlatilabilecek paketleri net sinirlarla tanimlamak
- paketler bittiginde entegrasyon ve dogrulama akisini belirlemek

Bu planin odagi, Claude Bridge'i "MCP tool helper" cizgisinden
"secure MCP execution / policy decision layer" cizgisine tasimaktir.

## Ust Fazlar

### Faz 0 - Dokuman ve Yonu Sabitleme

Durum: Basladi.

Amac:

- `product-roadmap.md` dosyasini urun vizyonu icin kanonik kabul etmek.
- `roadmap.md` dosyasini teknik implementasyon ve mevcut durum kaydi olarak tutmak.
- Eski strateji ve rakip analizlerini aktif plan, referans ve arsiv adayi olarak ayirmak.
- Ilk uygulama surecinin kapsam disina cikan isleri ertelemek.

Cikis:

- Dokuman envanteri guncel.
- Faz 1 icin kodlatilabilir paket listesi hazir.

### Faz 1 - Policy Decision Kernel

Durum: Tamamlandi.

Amac:

- Her riskli MCP tool cagrisi icin standart `allow / deny / ask` karar modeli olusturmak.
- Mevcut shell, path, approval ve audit guardrail'lerini tek karar modeline baglamak.
- AI evaluator gelmeden once deterministik ve test edilebilir guvenlik cekirdegi kurmak.

Neden once bu?

- AI evaluator, audit, appeal, role policy ve anomaly detection bu karar modeline baglanacak.
- Karar modeli olmadan her feature kendi formatini uretir ve ileride birlestirme maliyeti artar.

### Faz 2 - Rules Engine MVP

Amac:

- YAML/JSON tabanli kullanici kurallarini yuklemek, dogrulamak ve tool cagrilarina uygulamak.
- Kural eslesmesini hizli, test edilebilir ve fail-closed yapmak.

Bagimlilik:

- Faz 1 karar modeli.

### Faz 3 - Audit, Replay ve Masking

Amac:

- Her policy kararini kaydetmek.
- Hassas parametreleri maskelenmis sekilde loglamak.
- Gecmis kararlarin deterministic replay ile tekrar degerlendirilmesini saglamak.

Bagimlilik:

- Faz 1 karar modeli.
- Faz 2 rule sonucu metadata'si.

### Faz 4 - Optional AI Evaluator

Amac:

- Deterministik kurallar kesin karar vermediginde AI'dan guvenlik degerlendirmesi almak.
- AI cevabini strict JSON parse etmek, timeout ve bozuk cevapta fail-closed davranmak.

Bagimlilik:

- Faz 1 karar modeli.
- Faz 3 audit kaydi.

### Faz 5 - Appeal ve User Override

Amac:

- `deny` veya `ask` kararlarina kullanici gerekcesiyle itiraz akisi eklemek.
- Appeal sonucunu audit zincirine eklemek.
- Kalici kural onerisi uretmek ama otomatik politika yazmamak.

Bagimlilik:

- Faz 3 audit/replay.
- Faz 4 AI evaluator, opsiyonel.

### Faz 6 - Team Policy ve GitOps

Amac:

- Role based policy, `policy validate`, `policy diff`, `policy simulate` ve CI uyumlu policy
  kontrolleri eklemek.

Bagimlilik:

- Faz 2 rules engine.
- Faz 3 audit.

### Faz 7 - Intelligence ve Anomaly Detection

Amac:

- Audit verisinden davranis baseline'i ve anomaly score uretmek.
- Ilk surumde ML yerine deterministic anomaly kurallariyla baslamak.

Bagimlilik:

- Faz 3 audit verisi.
- Faz 6 role/policy bilgisi, opsiyonel.

### Faz 8 - Browser Extension / Web LLM Bridge

Amac:

- Local policy decision layer'i Claude Desktop disindaki web LLM akislari icin de kullanmak.

Bagimlilik:

- Stabil local daemon API.
- Stabil decision API.
- Audit ve policy altyapisi.

## Surec 1 - Policy Decision Kernel

Bu surec ilk baslanacak is grubudur. Paketler mumkun oldugunca farkli dosyalara ayrildi.
Amac, farkli araclarla paralel calisildiginda merge riskini dusurmektir.

Durum: Tamamlandi. `guard_policy.py` karar modeli, response helper'lari, shell/file
decision adapter'lari, MCP response entegrasyonu ve E2E policy decision testleri eklendi.

### Surec 1 Kabul Kriterleri

- Her policy karari ayni typed veri modeliyle temsil edilir.
- `allow`, `deny`, `ask` disinda karar uretilemez.
- Risk seviyesi ve karar kaynagi structured olarak doner.
- Shell/path/approval tarafindaki mevcut guvenlik davranisi gevsetilmez.
- Mevcut testler gecmeye devam eder.
- Yeni karar modeli icin unit test eklenir.

### Paket 1A - Kolay: Karar Modeli Tipleri

Zorluk: Kolay
Tahmini sure: 30-60 dk
Sahiplik: yeni veya dusuk cakismali model dosyasi

Ilgili dosyalar:

- `src/claude_bridge/guard_policy.py`
- `tests/test_guard_policy.py`

Kapsam:

- `DecisionAction`: `allow`, `deny`, `ask`
- `DecisionSource`: `default`, `builtin_guard`, `rule`, `approval`, `ai`
- `RiskLevel`: `low`, `medium`, `high`, `critical`
- `PolicyDecision` dataclass veya TypedDict
- `ToolRequestContext` dataclass veya TypedDict
- JSON serializable helper: `to_dict()`

Kapsam disi:

- YAML rule parsing
- AI provider
- Audit yazimi
- Existing tool wrapper refactor

Kabul kriterleri:

- Invalid action/source/risk state uretilemez veya validate edilir.
- Decision helper'lari Python 3.8 uyumlu olur.
- Unit testler action, source, risk ve serialization davranisini kapsar.

Test plani:

- `pytest tests/test_guard_policy.py`
- `ruff check src/claude_bridge/guard_policy.py tests/test_guard_policy.py`
- `mypy src`

### Paket 1B - Kolay/Orta: Policy JSON Response Helpers

Zorluk: Kolay-Orta
Tahmini sure: 45-90 dk
Sahiplik: response helper alani

Ilgili dosyalar:

- `src/claude_bridge/tool_utils.py`
- `src/claude_bridge/guard_policy.py`
- `tests/test_security.py` veya yeni helper testi

Kapsam:

- Policy decision sonucunu mevcut structured response formatina ekleyen helper.
- Response icinde standart alanlar:
  - `decision.action`
  - `decision.source`
  - `decision.risk_level`
  - `decision.reason`
  - `decision.risk_reasons`
- Mevcut `code`, `message`, `details` formatini bozmadan ekleme.

Kapsam disi:

- Tool davranisini degistirmek.
- Audit formatini degistirmek.

Kabul kriterleri:

- Eski response formatini bekleyen testler bozulmaz.
- Policy alanlari `details` icinde geriye uyumlu sekilde yer alir.

Test plani:

- Helper unit testleri.
- `pytest tests/test_security.py`

### Paket 1C - Orta: Shell Guard Decision Adapter

Zorluk: Orta
Tahmini sure: 1-2 saat
Sahiplik: shell guvenlik katmani

Ilgili dosyalar:

- `src/claude_bridge/shell_tools.py`
- `src/claude_bridge/guard_policy.py`
- `tests/test_security.py`

Kapsam:

- Mevcut `blocked_command_reason`, risk analizi ve approval davranisini policy decision
  modeline map etmek.
- Tehlikeli komutlar icin `deny`.
- Approval gereken ama deterministik engellenmeyen komutlar icin `ask`.
- Guvenli diagnostik komutlar icin `allow` veya mevcut approval modeline uyumlu karar.
- Risk nedenlerini structured liste olarak donmek.

Kapsam disi:

- Yeni command blocklist eklemek.
- Shell execution modelini degistirmek.
- Network policy.

Kabul kriterleri:

- Mevcut shell security testleri ayni veya daha siki davranisla gecer.
- Karar modeli response/audit tarafinda kullanilabilir metadata uretir.

Test plani:

- `pytest tests/test_security.py`
- `pytest tests/test_protocol.py -k shell`
- `ruff check src/claude_bridge/shell_tools.py`

### Paket 1D - Orta: Path ve File Operation Decision Adapter

Zorluk: Orta
Tahmini sure: 1-2 saat
Sahiplik: file/path guardrail alani

Ilgili dosyalar:

- `src/claude_bridge/tool_utils.py`
- `src/claude_bridge/file_tools.py`
- `src/claude_bridge/guard_policy.py`
- `tests/test_protocol.py`
- `tests/test_security.py`

Kapsam:

- Workspace disi path, sensitive path ve destructive file operation sinyallerini policy
  decision modeline map etmek.
- `read_file`, `write_file`, `patch_file`, `move_file`, `copy_path` gibi file tool'larin
  karar metadata'sini kullanabilmesine hazirlik yapmak.
- Mevcut path boundary davranisini korumak.

Kapsam disi:

- Yeni file tool eklemek.
- Rule engine condition'lari.
- Full response refactor.

Kabul kriterleri:

- Path disina cikma denemeleri fail-closed kalir.
- Sensitive path nedenleri structured risk reason olarak temsil edilir.
- File tool testleri bozulmaz.

Test plani:

- `pytest tests/test_security.py`
- `pytest tests/test_protocol.py -k file`

### Paket 1E - Orta/Zor: Server Integration Slice

Zorluk: Orta-Zor
Tahmini sure: 2-4 saat
Sahiplik: MCP tool wrapper entegrasyonu

Ilgili dosyalar:

- `src/claude_bridge/server.py`
- `src/claude_bridge/meta_tool_server.py`
- `src/claude_bridge/guard_policy.py`
- `tests/test_protocol.py`

Kapsam:

- Policy decision metadata'sini MCP tool response'larinda gorunur hale getirmek.
- En az 3 tool ile ilk entegrasyon:
  - `run_shell`
  - `write_file` veya `patch_file`
  - `workspace_status` gibi read-only bir meta tool, sadece default allow gostermek icin
- Response formatinda geriye uyumlulugu korumak.

Kapsam disi:

- Tum tool'lari tek PR'da tasimak.
- Rule engine.
- AI evaluator.

Kabul kriterleri:

- Entegre edilen tool'lar policy decision metadata'si dondurur.
- Entegre edilmeyen tool'lar eski davranisla calismaya devam eder.
- MCP protocol testleri gecer.

Test plani:

- `pytest tests/test_protocol.py`
- `pytest tests/test_security.py`

### Paket 1F - Zor: End-to-End Policy Decision Tests

Zorluk: Zor
Tahmini sure: 2-4 saat
Sahiplik: test ve fixture entegrasyonu

Ilgili dosyalar:

- `tests/test_policy_decisions.py`
- `tests/test_protocol.py`
- `tests/test_security.py`

Kapsam:

- Uctan uca karar senaryolari:
  - safe read-only operation
  - blocked shell command
  - approval-required shell command
  - sensitive path attempt
  - path outside workspace
- Response payload'larinda decision alanlarini assert etmek.
- Regression fixture'lariyla karar formatini sabitlemek.

Kapsam disi:

- AI karar fixture'lari.
- YAML policy fixture'lari.

Kabul kriterleri:

- E2E testler karar action/source/risk alanlarini dogrular.
- Existing tests ile cakisan fixture state'i temizlenir.

Test plani:

- `pytest tests/test_policy_decisions.py`
- `pytest tests/test_security.py`
- `pytest tests/test_protocol.py`
- `ruff check .`
- `mypy src`

## Surec 1 Birlestirme Sirasi

1. Paket 1A merge edilir.
2. Paket 1B, 1A uzerine merge edilir.
3. Paket 1C ve 1D paralel gelirse once cakisma kontrolu yapilir; ikisi de 1A/1B'ye
   baglidir.
4. Paket 1E, 1C ve 1D bittikten sonra yapilir.
5. Paket 1F en son calisir ve surecin kalite kapisi olur.

## Surec 1 Paralel Kodlatma Onerisi

### Kolay araca verilecekler

- Paket 1A
- Paket 1B

Bu paketler yeni model/helper yazdigi icin dusuk risklidir.

### Orta zorluktaki araca verilecekler

- Paket 1C
- Paket 1D

Bu paketler mevcut guvenlik davranisina dokundugu icin dikkatli test ister.

### Zor araca verilecekler

- Paket 1E
- Paket 1F

Bu paketler entegrasyon ve test kapisi oldugu icin repo genelini daha iyi bilen araca
verilmelidir.

## Surec 1 Disinda Birakilanlar

- YAML/JSON rule parser
- Hot reload
- AI provider entegrasyonlari
- SaaS login/token akisi
- Appeal mekanizmasi
- Role based policy
- Anomaly detection
- Browser extension
- Docker/sandbox isolation
- Network allowlist policy

Bu isler sonraki sureclere aittir. Surec 1'in gorevi sadece karar cekirdegini kurmaktir.

## Surec 2 - Rules Engine MVP

Bu surec, Surec 1'de kurulan `PolicyDecision` cekirdeginin ustune kullanici
tanimli YAML/JSON kurallari ekler. Amac, ilk surumde guvenli ve deterministik
bir kural motoru kurmaktir; AI evaluator, audit replay ve team policy bu surecin
disindadir.

Durum: Tamamlandi. Paket 2A-2D rule model, loader, matching ve tool entegrasyonu
katmanlari uzerine Paket 2E CLI validate/simulate ve Paket 2F E2E regression ile
kisa rule writing guide eklendi.

### Surec 2 Kabul Kriterleri

- Kullanici kurallari JSON ve mumkunse YAML dosyasindan yuklenebilir.
- Gecersiz kural dosyasi server'i crash ettirmez; validation hatalari structured raporlanir.
- En az su condition tipleri desteklenir:
  - `tool`
  - `field_equals`
  - `field_contains`
  - `regex`
  - `glob`
  - `extension`
  - `file_exists`
  - `file_size`
  - `sensitive_path`
  - `content_contains`
- Rule action sadece `allow`, `deny`, `ask` olabilir.
- Rule eslesmesi `PolicyDecision(source=rule)` uretir.
- Mevcut built-in guardrail'ler gevsetilmez; hard deny davranisi rule allow ile bypass
  edilemez.
- `claude-bridge policy validate` ve `claude-bridge policy simulate` CLI akislari vardir.
- Surec sonunda `ruff check .`, `mypy src`, `pytest` temizdir.

### Paket 2A - Kolay: Rule Model ve Validation

Zorluk: Kolay
Tahmini sure: 1-2 saat
Sahiplik: rule model dosyasi

Ilgili dosyalar:

- `src/claude_bridge/guard_policy.py` veya yeni `src/claude_bridge/rules_engine.py`
- `tests/test_rules_engine.py`

Kapsam:

- `RuleAction`, `ConditionType`, `RuleCondition`, `GuardRule`, `RuleSet` typed modelleri.
- JSON-compatible `from_dict()` / `to_dict()` helper'lari.
- Validation hatalarini structured liste olarak donduren helper:
  - rule name bos olamaz
  - action sadece `allow`, `deny`, `ask`
  - condition type desteklenen listeden olmali
  - regex condition compile edilebilir olmali
  - file_size condition numeric limit kullanmali
- Python 3.8 uyumlulugu.

Kapsam disi:

- Dosyadan policy yukleme.
- Condition matching.
- CLI.
- Tool entegrasyonu.

Kabul kriterleri:

- Gecerli rule dict'i modele donusur.
- Gecersiz rule dict'i crash yerine validation error uretir.
- Testler her condition type icin en az bir validation senaryosu kapsar.

Test plani:

- `pytest tests/test_rules_engine.py -k validation`
- `ruff check src/claude_bridge/guard_policy.py tests/test_rules_engine.py`
- `mypy src`

### Paket 2B - Kolay/Orta: Policy Loader ve Backward Compatibility

Zorluk: Kolay-Orta
Tahmini sure: 1-2 saat
Sahiplik: policy loading

Ilgili dosyalar:

- `src/claude_bridge/guard_policy.py` veya `src/claude_bridge/rules_engine.py`
- `tests/test_rules_engine.py`
- `tests/test_security.py`

Kapsam:

- Policy dosyasi arama sirasi:
  - `CLAUDE_BRIDGE_GUARD_POLICY` env override
  - proje ici `.claude-bridge-guard.json`
  - ileride `.claude-bridge/rules.yaml` icin hazir genisletilebilir tasarim
- JSON dosyasindan yeni `rules: [...]` formatini yukleme.
- Mevcut basit formatin geriye uyumlu kalmasi:
  - `blocked_shell_patterns`
  - `sensitive_path_patterns`
  - `secret_patterns`
- YAML icin opsiyonel destek:
  - PyYAML yoksa import-time crash olmamali
  - YAML dosyasi verilirse ama PyYAML yoksa structured validation error dondurulmeli
- Basit mtime cache veya yeniden okuma stratejisi; testlerde stale cache kalmamali.

Kapsam disi:

- Condition matching.
- CLI.
- Hot reload watcher.

Kabul kriterleri:

- Eski custom guard policy testleri gecmeye devam eder.
- Yeni `rules` listesi yuklenir ve validation sonucu alinabilir.
- Bozuk JSON/YAML dosyasi fail-closed validation error verir ama server crash olmaz.

Test plani:

- `pytest tests/test_rules_engine.py -k loader`
- `pytest tests/test_security.py -k custom_guard_policy`

### Paket 2C - Orta: Condition Matching Engine

Zorluk: Orta
Tahmini sure: 2-4 saat
Sahiplik: matching engine

Ilgili dosyalar:

- `src/claude_bridge/guard_policy.py` veya `src/claude_bridge/rules_engine.py`
- `tests/test_rules_engine.py`

Kapsam:

- `ToolRequestContext` ve tool params uzerinden condition matching.
- Desteklenecek condition tipleri:
  - `tool`: tool adi eslesmesi
  - `field_equals`: params alan degeri eslesmesi
  - `field_contains`: params alaninda substring
  - `regex`: params alaninda regex
  - `glob`: path/command gibi alanlarda glob
  - `extension`: path/file extension
  - `file_exists`: path var/yok
  - `file_size`: byte limiti
  - `sensitive_path`: mevcut `sensitive_path_reason`
  - `content_contains`: content preview icinde substring
- Ilk eslesen rule kazanir veya explicit priority alanina gore siralanir; secilen
  strateji testlerde belgelenir.
- Eslesen rule `PolicyDecision(source=rule)` uretir ve metadata icinde rule name/id tasir.

Kapsam disi:

- Built-in hard deny onceligi entegrasyonu.
- CLI simulate.
- AI prompt override.

Kabul kriterleri:

- Her condition type icin positive ve negative test vardir.
- Missing field condition false doner, crash olmaz.
- Regex hatalari validation'da yakalanir; runtime'da patlamaz.

Test plani:

- `pytest tests/test_rules_engine.py -k match`
- `ruff check src/claude_bridge/guard_policy.py tests/test_rules_engine.py`

### Paket 2D - Orta/Zor: Built-in Guard Priority ve Tool Entegrasyonu

Zorluk: Orta-Zor
Tahmini sure: 2-4 saat
Sahiplik: shell/file decision path entegrasyonu

Ilgili dosyalar:

- `src/claude_bridge/shell_tools.py`
- `src/claude_bridge/file_tools.py`
- `src/claude_bridge/tool_utils.py`
- `src/claude_bridge/guard_policy.py`
- `tests/test_security.py`
- `tests/test_policy_decisions.py`
- `tests/test_rules_engine.py`

Kapsam:

- Rule evaluation'i shell ve file operation karar akisi icine baglamak.
- Built-in hard deny onceligi:
  - blocked shell pattern
  - workspace disi path
  - sensitive path hard block
  - secret pattern hard block
  Bu durumlar rule `allow` ile bypass edilemez.
- Rule `deny` ve `ask`, built-in allow/default kararlarindan once uygulanabilir.
- Rule `allow`, yalnizca built-in hard deny olmayan durumda approval akisini yumusatabilir;
  bu davranis net testlenmeli veya ilk MVP'de allow sadece metadata olarak tutulup approval
  bypass etmemeli. Secilen strateji dokumante edilmeli.
- Response `details.decision.metadata` icinde rule bilgisi gorunur.

Kapsam disi:

- Tum MCP tool'larina entegrasyon.
- Audit replay.
- AI evaluator.

Kabul kriterleri:

- Rule deny shell/file cagrilarini engeller.
- Rule ask approval-required response uretir.
- Built-in hard deny rule allow ile gecilemez.
- Mevcut security ve protocol testleri gecmeye devam eder.

Test plani:

- `pytest tests/test_rules_engine.py`
- `pytest tests/test_security.py`
- `pytest tests/test_policy_decisions.py`

### Paket 2E - Zor: CLI Policy Validate ve Simulate

Zorluk: Zor
Tahmini sure: 3-5 saat
Sahiplik: CLI ve simulation UX

Ilgili dosyalar:

- `src/claude_bridge/cli.py`
- `src/claude_bridge/guard_policy.py` veya `src/claude_bridge/rules_engine.py`
- `tests/test_cli.py`
- `tests/test_rules_engine.py`

Kapsam:

- `claude-bridge policy validate --path <policy-file>`
  - validation errors
  - warning count
  - rule count
  - non-zero exit on invalid policy
- `claude-bridge policy simulate --path <policy-file> --tool run_shell --param command="npm test"`
  - tool context olusturur
  - rules engine'i calistirir
  - JSON veya human-readable karar ciktisi verir
- Param parsing basit ve guvenli olmali:
  - repeated `--param key=value`
  - JSON object opsiyonu sonradan eklenebilir, ilk MVP'de sart degil
- CLI komutlari shell veya file operation calistirmamali; sadece policy degerlendirmeli.

Kapsam disi:

- Policy diff.
- Team roles.
- SaaS/cloud policy.

Kabul kriterleri:

- Valid policy exit code 0.
- Invalid policy exit code non-zero.
- Simulate karar action/source/risk/rule metadata basar.
- Testlerde Typer runner ile validate ve simulate kapsanir.

Test plani:

- `pytest tests/test_cli.py -k policy`
- `pytest tests/test_rules_engine.py`
- `ruff check src/claude_bridge/cli.py`

### Paket 2F - Zor: E2E Rules Regression ve Dokumantasyon

Zorluk: Zor
Tahmini sure: 2-4 saat
Sahiplik: entegrasyon testi ve docs

Ilgili dosyalar:

- `tests/test_rules_engine.py`
- `tests/test_policy_decisions.py`
- `docs/roadmap.md`
- `docs/product-roadmap.md` veya `README.md` icindeki ilgili guvenlik bolumu
- `tasks/active/security-layer-execution-plan.md`

Kapsam:

- E2E fixture ile proje policy dosyasi yazip tool cagrisi sonucu rule decision assert etmek.
- En az su senaryolar:
  - custom rule deny: `run_shell` command regex
  - custom rule ask: `write_file` yeni `.sh` dosyasi
  - custom rule allow: safe validation command, built-in deny olmayan durumda
  - built-in hard deny wins over custom allow
  - invalid policy reports validation errors
- Kisa rule writing guide veya README bolumu.
- Surec 2 checkbox'larini uygulama sonunda guncellemek.

Kapsam disi:

- Full marketplace/policy package dokumantasyonu.
- AI evaluator prompt guide.

Kabul kriterleri:

- E2E tests stable ve izole.
- Dokumanlar yeni policy dosyasi formatini gosterir.
- Surec sonunda tam suite temizdir.

Test plani:

- `pytest tests/test_rules_engine.py`
- `pytest tests/test_policy_decisions.py`
- `pytest tests/test_cli.py -k policy`
- `ruff check .`
- `mypy src`
- `pytest`

## Surec 2 Birlestirme Sirasi

1. Paket 2A merge edilir.
2. Paket 2B, 2A uzerine merge edilir.
3. Paket 2C, 2A/2B uzerine gelir.
4. Paket 2D, 2C bittikten sonra yapilir.
5. Paket 2E, 2A-2C sonrasinda paralel baslayabilir ama finalde 2D ile uyumlanir.
6. Paket 2F en son kalite kapisi olur.

## Surec 2 Paralel Kodlatma Onerisi

### Kolay araca verilecekler

- Paket 2A
- Paket 2B

Model, validation ve loader isleri dusuk riskli ama format kararlarini netlestirir.

### Orta zorluktaki araca verilecekler

- Paket 2C
- Paket 2D

Condition matching ve tool entegrasyonu mevcut guvenlik davranisina dokunur; bu nedenle
test odakli calisilmalidir.

### Zor araca verilecekler

- Paket 2E
- Paket 2F

CLI simulate, E2E regression ve dokumantasyon isleri entegrasyon bilgisini gerektirir.

## Surec 3 - Audit, Replay ve Masking

Bu surec, mevcut JSONL audit altyapisini policy decision odakli hale getirir. Amac,
her tool cagrisi ve policy kararinin hassas veri sizdirmeden kaydedilmesi, filtrelenmesi
ve deterministic olarak tekrar degerlendirilmesidir.

Durum: Tamamlandi. Audit record schema, masking, query/filtering, deterministic replay,
CLI audit filtreleri, replay komutu, E2E regresyon testleri ve dokumantasyon eklendi.

### Surec 3 Kabul Kriterleri

- Audit kayitlari policy decision metadata'sini standart alanlarda tasir.
- Audit kayitlarinda hassas parametreler ve sonuc detaylari maskelenir.
- Masking hem parametre adlarina hem icerik pattern'lerine gore calisir.
- Her audit kaydi replay icin yeterli context ozetini tasir.
- Replay, eski kaydi mevcut rule engine ile tekrar degerlendirip karar degisti mi raporlar.
- CLI veya MCP meta tool uzerinden audit filtreleme ve replay calistirilabilir.
- Tam suite sonunda `ruff check .`, `mypy src`, `pytest` temizdir.

### Paket 3A - Kolay: Audit Decision Extraction ve Record Schema

Zorluk: Kolay
Tahmini sure: 1-2 saat
Sahiplik: audit record schema

Ilgili dosyalar:

- `src/claude_bridge/audit.py`
- `tests/test_audit.py` veya mevcut audit/protocol testleri

Kapsam:

- Tool result payload'undan policy decision'i standart sekilde cikaran helper:
  - once `details.decision`
  - yoksa top-level `decision`
  - yoksa `None`
- Audit record icine standart alanlar eklemek:
  - `decision_action`
  - `decision_source`
  - `decision_risk_level`
  - `decision_reason`
  - `decision_risk_reasons`
  - `decision_metadata`
- Mevcut record formatini geriye uyumlu tutmak; eski summary testleri bozulmamalidir.

Kapsam disi:

- Masking/redaction.
- Replay.
- CLI filtreleme.

Kabul kriterleri:

- Decision bulunan tool result'lari audit record'da normalize edilir.
- Decision olmayan tool result'lari eski davranisla loglanir.
- JSONL record hala parse edilebilir ve eski summary akisi calisir.

Test plani:

- `pytest tests/test_protocol.py -k audit`
- `pytest tests/test_audit.py -k decision` varsa
- `ruff check src/claude_bridge/audit.py`

### Paket 3B - Kolay/Orta: Redaction ve Masking Helpers

Zorluk: Kolay-Orta
Tahmini sure: 1-2 saat
Sahiplik: masking utility

Ilgili dosyalar:

- `src/claude_bridge/audit.py`
- `src/claude_bridge/tool_utils.py` gerekirse
- `tests/test_audit.py` veya `tests/test_security.py`

Kapsam:

- Hassas key isimlerini maskele:
  - `api_key`, `apikey`, `token`, `secret`, `password`, `authorization`, `cookie`
  - case-insensitive ve nested dict/list destekli
- Hassas icerik pattern'lerini maskele:
  - mevcut `_SECRET_PATTERNS` veya ortak helper ile uyumlu
  - `.env` benzeri content preview'larda secret degerlerini loglama
- Masked value formati deterministik olmali:
  - `{"redacted": true, "reason": "...", "sha256": "...", "length": N}`
- Path ve command gibi faydali debug bilgisini tamamen silme; sadece secret degerleri maskelenmeli.

Kapsam disi:

- PII detection.
- Full content scanning beyond audit summary limits.
- Encryption.

Kabul kriterleri:

- Nested secret parametreleri audit record'a acik sekilde yazilmaz.
- Hash sayesinde replay/debug icin ayni degerin ayni olup olmadigi anlasilabilir.
- Mevcut custom secret pattern testleri bozulmaz.

Test plani:

- `pytest tests/test_security.py -k secret`
- `pytest tests/test_protocol.py -k audit`
- `ruff check src/claude_bridge/audit.py`

### Paket 3C - Orta: Audit Query ve Filtering

Zorluk: Orta
Tahmini sure: 2-3 saat
Sahiplik: audit read/query katmani

Ilgili dosyalar:

- `src/claude_bridge/audit.py`
- `src/claude_bridge/meta_tool_server.py`
- `tests/test_protocol.py`

Kapsam:

- Audit kayitlarini filtreleyen helper:
  - `tool_name`
  - `ok`
  - `decision_action`
  - `decision_source`
  - `decision_risk_level`
  - `since` veya basit `limit`
- `get_recent_tool_calls` veya yeni meta helper'in bu filtreleri kullanabilmesi.
- Activity summary icinde policy decision sayilari:
  - allow/deny/ask count
  - high/critical risk count
  - rule decision count

Kapsam disi:

- SQL/SQLite.
- Cross-session global search.
- Replay.

Kabul kriterleri:

- Filtreler JSONL kayitlar uzerinde deterministik calisir.
- Mevcut `get_recent_tool_calls` geriye uyumlu kalir.
- Summary policy kararlarini gorunur kilar.

Test plani:

- `pytest tests/test_protocol.py -k audit`
- `pytest tests/test_cli.py -k audit`

### Paket 3D - Orta/Zor: Replay Engine

Zorluk: Orta-Zor
Tahmini sure: 3-5 saat
Sahiplik: replay engine

Ilgili dosyalar:

- `src/claude_bridge/audit.py`
- `src/claude_bridge/guard_policy.py`
- `src/claude_bridge/rules_engine.py`
- yeni `src/claude_bridge/replay.py` dusunulebilir
- `tests/test_replay.py` veya `tests/test_audit.py`

Kapsam:

- Audit record'dan replay context olusturmak:
  - tool name
  - masked params
  - project/workspace bilgisi varsa
  - onceki decision snapshot
- Mevcut rule engine ile yeniden evaluate etmek.
- Replay sonucu:
  - `original_decision`
  - `replayed_decision`
  - `changed: true/false`
  - `change_reason`
  - validation errors varsa metadata
- Masked params ile replay'in sinirlarini dokumante etmek; secret degeri gerekiyorsa
  condition false donmeli, crash olmamali.

Kapsam disi:

- AI evaluator replay.
- Full filesystem snapshot replay.
- Git snapshot.

Kabul kriterleri:

- Ayni policy ile replay stable sonuc verir.
- Policy degisince karar farki raporlanir.
- Masked/verisi eksik alanlarda replay fail-open yapmaz; deterministic `ask` veya no-match
  davranisi belgelenir.

Test plani:

- `pytest tests/test_replay.py`
- `pytest tests/test_rules_engine.py`
- `mypy src`

### Paket 3E - Zor: CLI Audit Replay ve Filtering

Zorluk: Zor
Tahmini sure: 3-5 saat
Sahiplik: CLI UX ve entegrasyon

Ilgili dosyalar:

- `src/claude_bridge/cli.py`
- `src/claude_bridge/audit.py`
- `src/claude_bridge/replay.py` varsa
- `tests/test_cli.py`

Kapsam:

- `claude-bridge audit --last` mevcut davranisini koru.
- Yeni opsiyonel filtreler:
  - `--tool`
  - `--decision allow|deny|ask`
  - `--risk low|medium|high|critical`
  - `--source default|builtin_guard|rule|approval|ai`
- Replay komutu veya audit alt modu:
  - `claude-bridge audit replay --record-id <id>`
  - veya Typer yapisina daha uygunsa `claude-bridge replay --record-id <id>`
- Replay ciktisi human-readable ve test edilebilir olmali.
- CLI hicbir tool execution yapmamali; sadece audit record'u yeniden degerlendirmeli.

Kapsam disi:

- Interactive selection UI.
- SaaS audit backend.
- PostgreSQL/SQLite.

Kabul kriterleri:

- Audit filtreleri beklenen kayitlari basar.
- Replay komutu karar degisimini gosterir.
- Invalid record id non-zero exit verir.

Test plani:

- `pytest tests/test_cli.py -k audit`
- `pytest tests/test_replay.py`
- `ruff check src/claude_bridge/cli.py src/claude_bridge/audit.py`

### Paket 3F - Zor: E2E Audit Regression ve Docs

Zorluk: Zor
Tahmini sure: 2-4 saat
Sahiplik: E2E test ve dokumantasyon

Ilgili dosyalar:

- `tests/test_audit.py` veya `tests/test_protocol.py`
- `tests/test_replay.py`
- `README.md`
- `docs/roadmap.md`
- `tasks/active/security-layer-execution-plan.md`

Kapsam:

- E2E senaryolar:
  - rule deny tool call audit'e decision alanlariyla yazilir
  - secret parametre audit'te masked kalir
  - audit filtreleme deny/high/rule kayitlarini bulur
  - replay same-policy stable sonucu verir
  - replay changed-policy fark raporlar
- README veya docs icinde:
  - audit kaydinda ne saklanir / ne saklanmaz
  - masking garantileri ve sinirlari
  - replay'in deterministic rule engine ile sinirli oldugu
- Surec 3 checkbox'larini uygulama sonunda guncellemek.

Kapsam disi:

- SOC2 seviyesinde retention/compliance dokumani.
- Appeal flow.
- AI replay.

Kabul kriterleri:

- E2E testler izole audit dir kullanir.
- Dokumanlar kullaniciya secret'larin loglanmadigini ve replay sinirlarini aciklar.
- Surec sonunda tam suite temizdir.

Test plani:

- `pytest tests/test_audit.py tests/test_replay.py`
- `pytest tests/test_protocol.py -k audit`
- `pytest tests/test_cli.py -k audit`
- `ruff check .`
- `mypy src`
- `pytest`

## Surec 3 Birlestirme Sirasi

1. Paket 3A merge edilir.
2. Paket 3B, 3A uzerine gelir.
3. Paket 3C, 3A/3B sonrasinda gelir.
4. Paket 3D, 3A/3B ve Surec 2 rule engine uzerine gelir.
5. Paket 3E, 3C ve 3D sonrasinda uygulanir.
6. Paket 3F en son kalite kapisi olur.

## Surec 3 Paralel Kodlatma Onerisi

### Kolay araca verilecekler

- Paket 3A
- Paket 3B

Audit schema ve masking helper'lari dusuk riskli ama guvenlik acisindan dikkat ister.

### Orta zorluktaki araca verilecekler

- Paket 3C
- Paket 3D

Query/filtering ve replay engine mevcut audit/rules altyapisini birlestirir.

### Zor araca verilecekler

- Paket 3E
- Paket 3F

CLI, E2E regression ve dokumantasyon entegrasyon bilgisi gerektirir.

## Surec 3.5 - Security Hardening ve Bugfix Gate

Bu surec, Surec 4 AI Evaluator'a gecmeden once uygulanmasi gereken zorunlu
guvenlik ve saglamlik kapisidir. Yeni AI katmani eklenmeden once mevcut shell,
file/path, policy, audit ve workflow yuzeylerindeki kritik aciklar kapatilmalidir.

Durum: Planlandi.

### Surec 3.5 Kabul Kriterleri

- Kritik guvenlik bulgulari icin regression test vardir.
- Built-in guardrail'ler kullanici policy `allow` ile bypass edilemez.
- Path/symlink kontrolleri realpath hedefini de dogrular.
- LLM-controlled validation command'lar shell injection'a acik degildir.
- CLI JSON output'lari double-serialized degildir.
- ReDoS riskli kullanici regex'leri validation'da reddedilir veya guvenli timeout/limit ile
  ele alinir.
- Tam suite sonunda `ruff check .`, `mypy src`, `pytest` temizdir.

### Paket 3.5A - Kolay: CLI, Boolean Parsing ve Low-Risk Logic Fixes

Zorluk: Kolay
Tahmini sure: 1-2 saat
Sahiplik: dusuk cakismali mantik duzeltmeleri

Ilgili dosyalar:

- `src/claude_bridge/cli.py`
- `src/claude_bridge/rules_engine.py`
- `src/claude_bridge/config.py`
- `src/claude_bridge/tool_utils.py`
- `tests/test_cli.py`
- `tests/test_rules_engine.py`
- `tests/test_security.py`

Kapsam:

- `console.print_json(json.dumps(...))` double JSON serialization bug'larini duzelt.
- `rules_engine.py` icinde bool condition parsing'i string `"false"`, `"no"`, `"0"` icin
  dogru false degerine cevir.
- `shell_timeout` icin 0/negatif degerleri reddeden bounds check ekle.
- `safe_read_text` non-UTF-8 dosyalarda structured error/fallback dondursun; raw
  `UnicodeDecodeError` firlatmasin.
- Bu degisiklikler icin odakli test ekle.

Kapsam disi:

- Shell security parser refactor.
- Symlink traversal.
- Replay/audit performans iyilestirmeleri.

Test plani:

- `pytest tests/test_cli.py -k json`
- `pytest tests/test_rules_engine.py -k bool`
- `pytest tests/test_security.py -k timeout`
- `ruff check src/claude_bridge/cli.py src/claude_bridge/rules_engine.py src/claude_bridge/config.py src/claude_bridge/tool_utils.py`
- `mypy src`

### Paket 3.5B - Kolay/Orta: Git ve Error Handling Fixes

Zorluk: Kolay-Orta
Tahmini sure: 2-3 saat
Sahiplik: git/error handling

Ilgili dosyalar:

- `src/claude_bridge/git_ops.py`
- `src/claude_bridge/file_tools.py`
- `src/claude_bridge/workflow_tools.py`
- `src/claude_bridge/indexing.py`
- `src/claude_bridge/insights.py`
- `tests/test_git.py`
- `tests/test_protocol.py`
- `tests/test_indexing_cache.py` veya yeni ilgili test

Kapsam:

- `git_commit` repo yoksa sessiz `git init` yapmasin; explicit error dondursun.
- Git subprocess `TimeoutExpired` yakalansin.
- Relative path `".."` kontrolu `some..file` gibi mesru isimleri yanlis engellemesin.
- `file_tools.py` commit sonucu `commit` key'ini guvenli kontrol etsin.
- Disk cache `json.loads` hatalari yakalansin; bozuk cache crash ettirmesin.
- `ast.parse` icin `ValueError` yakalansin.
- Tempfile cleanup `finally` ile garanti edilsin.

Kapsam disi:

- Symlink traversal.
- Workflow validation command injection.
- Performance refactor.

Test plani:

- `pytest tests/test_git.py`
- `pytest tests/test_protocol.py -k 'commit or cache or ast'`
- `ruff check src/claude_bridge/git_ops.py src/claude_bridge/file_tools.py src/claude_bridge/workflow_tools.py src/claude_bridge/indexing.py src/claude_bridge/insights.py`
- `mypy src`

### Paket 3.5C - Orta: Shell Guard Hardening

Zorluk: Orta
Tahmini sure: 3-5 saat
Sahiplik: shell command analysis

Ilgili dosyalar:

- `src/claude_bridge/shell_tools.py`
- `src/claude_bridge/shell_tool_server.py`
- `tests/test_security.py`
- `tests/test_protocol.py`

Kapsam:

- Fork bomb varyantlarini yakala:
  - `:(){ :|:& };:`
  - `f(){ f|f& };f`
  - whitespace ve fonksiyon adi varyasyonlari
- `/dev` redirect kontrollerini genislet:
  - `>/dev/...`
  - `1>/dev/...`
  - `2>/dev/...`
  - `&>/dev/...`
- Curl/wget pipe kontrolunu token-level false positive uretmeyecek sekilde duzelt:
  - `curl -o python3 ...` gibi dosya adi false positive olmamali
  - pipe/operator akisi gercekten shell/interpreter'a gidiyorsa block edilmeli
- `env -i python3` gibi env flag'lerini dogru atla.
- `env python3 -m pytest` risk seviyesi low olmali.
- `git -C /path reset --hard` destructive git check tarafindan yakalanmali.
- Low risk shell analizinde `requires_confirmation` metadata'si yanlis true olmamali.
- Dead code `_DESTRUCTIVE_GIT_SUBCOMMANDS` ya kullanilsin ya kaldirilsin.

Kapsam disi:

- Long-running process refactor.
- Network allowlist policy.

Test plani:

- `pytest tests/test_security.py -k shell`
- `pytest tests/test_protocol.py -k shell`
- `ruff check src/claude_bridge/shell_tools.py src/claude_bridge/shell_tool_server.py`
- `mypy src`

### Paket 3.5D - Orta/Zor: File Path, Symlink ve Directory Listing Hardening

Zorluk: Orta-Zor
Tahmini sure: 3-5 saat
Sahiplik: file/path security

Ilgili dosyalar:

- `src/claude_bridge/file_tools.py`
- `src/claude_bridge/tool_utils.py`
- `tests/test_security.py`
- `tests/test_protocol.py`

Kapsam:

- Symlink traversal fix:
  - workspace icindeki symlink hedefi allowed roots disindaysa write/move/copy/read/patch
    izin vermemeli.
- Path validation hem lexical path'i hem resolved target'i kontrol etmeli.
- `list_directory` symlink'leri sessiz takip edip dis dosya bilgisi sizdirmemeli.
  Symlink entry icin guvenli metadata dondur veya blocked/symlink olarak isaretle.
- `entry.stat()` tek entry icin hata verirse tum directory listing crash etmemeli.
- Fallback search path'indeki `relative_to()` ValueError yakalanmali.

Kapsam disi:

- Full virtual filesystem.
- Docker/sandbox isolation.

Test plani:

- `pytest tests/test_security.py -k 'symlink or path'`
- `pytest tests/test_protocol.py -k 'list_directory or patch or write_file or move_file or copy_path'`
- `ruff check src/claude_bridge/file_tools.py src/claude_bridge/tool_utils.py`
- `mypy src`

### Paket 3.5E - Zor: Policy Regex ReDoS ve Workflow Validation Command Safety

Zorluk: Zor
Tahmini sure: 4-6 saat
Sahiplik: policy validation + workflow execution safety

Ilgili dosyalar:

- `src/claude_bridge/guard_policy.py`
- `src/claude_bridge/rules_engine.py`
- `src/claude_bridge/workflow_tools.py`
- `tests/test_rules_engine.py`
- `tests/test_security.py`
- `tests/test_protocol.py`

Kapsam:

- Kullanici supplied regex icin ReDoS mitigation:
  - nested quantifier gibi riskli pattern'leri validation'da reddet veya safe-regex
    heuristic uygula.
  - `((a+)+b)` benzeri pattern regression testi.
- Runtime regex matching bug'larini sessizce yutma; validation'da yakalanmayan beklenmedik
  hata structured warning/error olarak gorunur olmali.
- `workflow_tools.py` icindeki LLM-controlled `validation_command` dogrudan shell'e
  verilmesin:
  - sadece `suggest_validation_commands` veya allowlisted validation prefix'leri kabul edilsin
  - command parse `shell=False` modeline uyumlu kalsin
  - injection operatorleri reddedilsin
- Bozuk workflow disk cache JSON crash ettirmesin.

Kapsam disi:

- AI evaluator.
- Full policy marketplace validation.

Test plani:

- `pytest tests/test_rules_engine.py -k regex`
- `pytest tests/test_security.py -k workflow`
- `pytest tests/test_protocol.py -k workflow`
- `ruff check src/claude_bridge/guard_policy.py src/claude_bridge/rules_engine.py src/claude_bridge/workflow_tools.py`
- `mypy src`

### Paket 3.5F - Zor: Performance, Thread Safety ve Final Regression

Zorluk: Zor
Tahmini sure: 4-8 saat
Sahiplik: repo geneli regression/perf

Ilgili dosyalar:

- `src/claude_bridge/audit.py`
- `src/claude_bridge/indexing.py`
- `src/claude_bridge/insights.py`
- `src/claude_bridge/shell_tools.py`
- ilgili test dosyalari

Kapsam:

- `find_audit_record` ve `latest_session_id` icin kabul edilebilir cache/index stratejisi veya
  bounded scan ekle.
- `_is_local_module` icin O(n^2) tree walk yerine once hesaplanan module index/cache kullan.
- `get_cached_index` mutable cache referansi dondurmesin; defensive copy veya immutable view
  kullansin.
- `reset_process_sessions` lock/race window'unu daralt.
- `indexing.py` cift stat ve fallback symbol extraction performansini gozden gecir.
- Kod kalitesi cleanup:
  - shell output limit sabitlerini netlestir
  - import side effect `reset_audit_session()` icin gerekce yoksa kaldir veya lazy yap

Kapsam disi:

- Buyuk mimari refactor.
- SQLite audit backend.

Test plani:

- `pytest tests/test_indexing_cache.py tests/test_relevance.py tests/test_protocol.py -k process`
- `pytest tests/test_audit.py tests/test_replay.py`
- `ruff check .`
- `mypy src`
- `pytest`

## Surec 3.5 Birlestirme Sirasi

1. Paket 3.5A ve 3.5B dusuk riskli olarak once gelebilir.
2. Paket 3.5C ve 3.5D paralel calisabilir ama `tests/test_security.py` cakismalari
   merge oncesi dikkatle cozulmelidir.
3. Paket 3.5E, 3.5C'den sonra gelmelidir; workflow command safety shell parser kararlarini
   kullanabilir.
4. Paket 3.5F en son performans/thread safety ve tam regression kapisi olarak calisir.

## Surec 3.5 Paralel Kodlatma Onerisi

### Kolay araca verilecekler

- Paket 3.5A
- Paket 3.5B

### Orta zorluktaki araca verilecekler

- Paket 3.5C
- Paket 3.5D

### Zor araca verilecekler

- Paket 3.5E
- Paket 3.5F

Bu surec bitmeden Surec 4 AI Evaluator'a gecilmemelidir.

## Genel Dogrulama

Her paket sonunda mumkun olan en dar test calistirilir. Surec sonunda tam dogrulama:

```bash
ruff check .
mypy src
pytest
```

## Son Durum

- [x] Buyuk plan fazlara bolundu.
- [x] Ilk surec secildi: Policy Decision Kernel.
- [x] Ilk surec zorluk ve sahiplik bazli paketlere ayrildi.
- [x] Paket 1A uygulandi.
- [x] Paket 1B uygulandi.
- [x] Paket 1C uygulandi.
- [x] Paket 1D uygulandi.
- [x] Paket 1E uygulandi.
- [x] Paket 1F uygulandi.
- [x] Surec 2 - Rules Engine MVP tamamlandi.
- [x] Paket 2A rule model ve validation uygulandi.
- [x] Paket 2B policy loader ve backward compatibility uygulandi.
- [x] Paket 2C condition matching engine uygulandi.
- [x] Paket 2D built-in guard priority ve tool entegrasyonu uygulandi.
- [x] Paket 2E CLI policy validate/simulate uygulandi.
- [x] Paket 2F E2E rules regression ve dokumantasyon uygulandi.
- [x] Surec 3 - Audit, Replay ve Masking tamamlandi.
- [x] Paket 3A audit decision extraction ve record schema uygulandi.
- [x] Paket 3B redaction ve masking helper'lari uygulandi.
- [x] Paket 3C audit query ve filtering uygulandi.
- [x] Paket 3D deterministic replay engine uygulandi.
- [x] Paket 3E CLI audit replay ve filtering uygulandi.
- [x] Paket 3F E2E audit regression ve dokumantasyon uygulandi.
