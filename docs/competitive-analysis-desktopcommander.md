# Competitive Analysis — DesktopCommanderMCP

## Proje

- Ad: DesktopCommanderMCP
- Repo / kaynak: <https://github.com/wonderwhy-er/DesktopCommanderMCP>
- Incelenen ref: `main`, 2026-05-01 tarihinde public GitHub uzerinden
- Odak alani: shell/process, search, edit, audit/onboarding ve guvenlik modeli

## Kisa Ozet

DesktopCommanderMCP, Claude ve diger MCP istemcileri icin dosya sistemi, terminal
ve uzun calisan process yonetimi saglayan TypeScript tabanli bir MCP server.
README yuzeyinde one cikan farklar: interactive process control, output streaming,
process session management, audit logging, Docker isolation, Office/PDF/DOCX
destegi ve onboarding/feedback akislari.

Claude Bridge ayni problem alaninda daha kontrollu Python/MCP katmani sunuyor:
path boundary, approval presetleri, structured audit, relevance/indexing ve
workflow orchestration daha proje merkezli. DesktopCommanderMCP ise genis tool
yelpazesi, process session ergonomisi ve onboarding polish tarafinda daha ileri.

## Karsilastirma Tablosu

| Alan | Claude Bridge | DesktopCommanderMCP | Fark | Alinabilecek fikir |
|---|---|---|---|---|
| Shell execution | `run_shell`, `start_process`, approval ve risk analizi | `TerminalManager` ile shell secimi, login shell flagleri, timeout, session map | Rakip shell/process lifecycle'i daha urunlesmis | Process output pagination ve shell-specific spawn config'i iyilestir |
| Approval / policy | Approval presetleri ve fail-closed akis | Config icinde blocked commands ve allowed directories | Biz approval tarafinda daha acik; rakip config runtime degisimi sunuyor | Runtime config UI/doctor entegrasyonu dusunulebilir |
| File search | `find_relevant_files`, ripgrep tabanli arama, relevance scoring | `SearchManager` ile async search session, ripgrep JSON, pagination, Office search | Biz relevance tarafinda daha zeki; rakip streaming/pagination tarafinda guclu | Search session pagination ve incomplete search raporu ekle |
| Patch/edit akisi | `preview_patch`, `patch_file`, risk summary, fuzzy suggestions | `edit_block`, multi-file/file rewrite yonlendirmeleri | Biz controlled patch ve git snapshot tarafinda daha guclu | Multi-occurrence edit UX'i ve edit history gorunurlugu incelenebilir |
| Indexing/relevance | AST/Tree-sitter index, golden relevance dataset | README ve kodda daha cok search odakli | Biz code intelligence tarafinda ayrisiyoruz | Bu ayrimi urun mesajinda one cikar |
| Audit/logging | JSONL audit, result hash, summarized params/results | README comprehensive audit logging; `toolHistory`, usage stats ve telemetry | Biz privacy-friendly local audit icin iyi temele sahibiz | Audit rotation, session summary ve user-visible history UX'i guclendir |
| CLI onboarding | `setup`, `install`, `doctor`, lightweight onboarding hints | npx setup, Docker install, welcome onboarding, feedback prompts | Rakip ilk 5 dakika deneyiminde daha polish | Doctor sonrasi next-step onerileri ve guided setup ekle |
| Test/CI stratejisi | pytest/mypy/ruff/black, benchmark/golden dataset | Bu ilk turda derin incelenmedi | Eksik karsilastirma | Ayrica test/CI turu ac |

## Mimari Notlar

- DesktopCommanderMCP process yonetimini `TerminalManager` sinifinda topluyor:
  aktif ve tamamlanmis session mapleri, process input, output buffer, pagination
  ve terminate fonksiyonlari ayni lifecycle icinde.
- Search tarafinda `SearchManager`, ripgrep process'ini session olarak baslatiyor,
  ilk chunk'i bekleyip sonucu parca parca okutuyor ve permission kaynakli eksik
  aramalari `wasIncomplete` gibi alanlarla gorunur kiliyor.
- Config manager disk uzerinde persistent config tutuyor; `blockedCommands`,
  `allowedDirectories`, `defaultShell`, telemetry ve line limitleri runtime
  tarafinda merkezi.
- Server katmani tool registration'i tek buyuk listede topluyor; handler dispatch
  switch/case ile ilerliyor. Claude Bridge'te bunun karsiligi Python fonksiyonlari
  ve registration wrapper'lariyla daha moduler.
- Onboarding ve feedback, tool basari/failure istatistiklerine baglanmis. Bu iyi
  bir urun sinyali ama Claude Bridge icin daha sakin ve local-first uygulanmali.

## Claude Bridge'e Uyarlama

Uygulanabilir fikirler:

- [ ] Process output pagination
  - Tip: ozellik / altyapi
  - Etkilenecek dosyalar: `src/claude_bridge/shell_tools.py`,
    `src/claude_bridge/server.py`, `tests/test_protocol.py`
  - Risk: Orta; process session API'si genisler
  - Ilk uygulanabilir adim: `read_process_output(session_id, offset, limit)`
    benzeri line-based output paging ekle

- [ ] Search session modeli
  - Tip: ozellik
  - Etkilenecek dosyalar: `src/claude_bridge/file_tools.py`,
    `src/claude_bridge/indexing.py`, `src/claude_bridge/server.py`
  - Risk: Orta; mevcut sync search davranisiyla uyum korunmali
  - Ilk uygulanabilir adim: Buyuk aramalarda `search_id`, `has_more`,
    `was_incomplete` alanlariyla incremental okuma tasarla

- [ ] Doctor next-step onerileri
  - Tip: UX / dokuman
  - Etkilenecek dosyalar: `src/claude_bridge/doctor.py`,
    `src/claude_bridge/cli.py`, `README.md`
  - Risk: Dusuk
  - Ilk uygulanabilir adim: Eksik dev/smart/treesitter durumuna gore en fazla uc
    komutluk "Recommended next steps" bolumu ekle

- [ ] Audit history UX
  - Tip: ozellik / UX
  - Etkilenecek dosyalar: `src/claude_bridge/audit.py`,
    `src/claude_bridge/cli.py`, `src/claude_bridge/server.py`
  - Risk: Dusuk-Orta; log boyutu ve privacy sinirlari korunmali
  - Ilk uygulanabilir adim: Audit log rotation ve `claude-bridge audit --json`
    ciktisi tasarla

Ertelenecek fikirler:

- [ ] Docker isolation
  - Erteleme nedeni: Yuksek etki ama packaging, mount policy ve platform
    davranisi ayri tasarim ister.

- [ ] Office/PDF/DOCX native editing
  - Erteleme nedeni: Claude Bridge'in cekirdek farklilasmasi code workflow ve
    trusted execution; document feature seti simdilik ana hatta degil.

Alinmayacak fikirler:

- [ ] Telemetry opt-out default'u
  - Neden uygun degil: Claude Bridge local-first ve trust-layer konumlandirmasinda
    varsayilan olarak local audit yeterli; dis telemetry ayri acik izin gerektirir.

## Sonuc

En yuksek etkili 3 ders:

1. Long-running process ve output pagination, gelistirici deneyiminde net fark
   yaratiyor.
2. Search sadece "sonuc bulma" degil, session ve incremental okuma deneyimi olarak
   urunlestirilebilir.
3. Onboarding ve doctor next-step onerileri, teknik gucu kullanilabilir hale
   getiriyor.

Bir sonraki task:

- `doctor` raporuna recommended next steps ekle.
- Sonra `start_process` / `read_process_output` icin line-based pagination tasarla.

Roadmap'e eklenecek not:

- Relevance v2 yalniz scoring degil, buyuk arama ve process output icin
  pagination/session UX'i de kapsamali.

## Kaynaklar

- DesktopCommanderMCP README: <https://github.com/wonderwhy-er/DesktopCommanderMCP>
- `terminal-manager.ts`: <https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/terminal-manager.ts>
- `search-manager.ts`: <https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/search-manager.ts>
- `config-manager.ts`: <https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/config-manager.ts>
- `server.ts`: <https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/server.ts>
