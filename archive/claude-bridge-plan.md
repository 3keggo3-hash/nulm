# Claude Bridge — Proje Planı

**Hedef:** Claude.ai Pro kullanıcılarına, ek ücret ödemeden, Claude Code'a yakın (%85–90) bir geliştirme deneyimi sunmak. Terminal kurulumu yok, karmaşık yapılandırma yok, tek komutla çalışır.

---

## 1. Temel Fikir

Claude.ai web arayüzü güçlü bir "beyin"dir ama elleri yoktur. Masaüstündeki dosyalardan haberdar değildir, terminal çalıştıramaz ve bir değişikliği uygulamak için her seferinde kodun tamamını yeniden yazmak zorunda kalır.

Claude Bridge bu sorunu şu şekilde çözer: Claude'a bir dil öğretiyoruz. Claude bu özel dili (Tool Protocol) kullandığında, masaüstünüzdeki küçük bir sunucu devreye girer ve Claude'un "görmek" ya da "yapmak" istediği şeyi gerçekten yapar. Sonucu Claude'a geri verir. Claude artık karanlıkta tahmin yapmak zorunda değildir.

Kullanıcı deneyimi şu şekilde görünür: Tarayıcıda Claude ile normal konuşursunuz. Claude bir dosyayı okumak istediğinde siz bir butona basarsınız, dosya içeriği Claude'a gider. Claude bir düzeltme yaptığında tekrar butona basarsınız, sadece değişen satırlar masaüstünüzdeki dosyaya işlenir. Kopyala-yapıştır yok, dosyayı baştan yazma yok.

---

## 2. Mimari: Üç Parça

Sistem üç bileşenden oluşur ve her biri bağımsız ve anlaşılır bir görev üstlenir.

### Bileşen 1: Yerel Sunucu (Local Bridge Server)

Bilgisayarınızda arka planda çalışan küçük bir Python programı. `pipx install claude-bridge` komutuyla kurulur, `claude-bridge start` ile başlatılır.

Bu sunucunun görevi:
- `localhost:7337` adresini dinlemek
- Bookmarklet'ten gelen komutları almak
- Tool Protocol komutlarını çalıştırmak (dosya okuma, terminal komutu, patch uygulama)
- Sonuçları geri döndürmek
- Her işlemden önce onay sormak

Sunucu hiçbir zaman dış internete bağlanmaz. Sadece `localhost` üzerinde çalışır. 200 satır, açık kaynak, herkes okuyabilir.

### Bileşen 2: Bookmarklet (Tarayıcı Köprüsü)

Claude Bridge kurulunca size tek satırlık bir JavaScript kodu verir. Bunu tarayıcınızın yer imlerine sürükleyip bırakırsınız. Artık her Claude sayfasında bir "Bridge" düğmesi görürsünüz.

Bu düğmeye bastığınızda bookmarklet şunları yapar:
- Sayfadaki Claude cevabını okur
- Tool Protocol komutlarını (`[READ:]`, `[SHELL:]`, `[PATCH:]`) tespit eder
- Bunları `localhost:7337`'deki yerel sunucuya gönderir
- Sonucu Claude'a otomatik olarak bir kullanıcı mesajı gibi yapıştırır

Tarayıcı eklentisi değildir, mağaza onayı gerektirmez, herhangi bir tarayıcıya saniyeler içinde eklenir.

### Bileşen 3: Sistem Promptu (Claude'un Beyni)

Claude'a konuşma başında verilen özel talimat metni. Claude.ai'daki "Projects" özelliğine bir kez eklenir, sonra her konuşmada otomatik aktif olur.

Bu prompt Claude'a şunları öğretir:
- Hiçbir zaman kodun tamamını yazma
- Sadece SEARCH/REPLACE blokları üret
- Bir dosyayı görmek istersen `[READ: path]` yaz
- Terminal çalıştırmak istersen `[SHELL: komut]` yaz
- Değişiklik yapmak istersen `[PATCH: ...]` bloğu üret

---

## 3. Tool Protocol — Detaylı Açıklama

Tool Protocol, Claude ile yerel sunucu arasındaki iletişim dilidir. Claude bu formatları kullandığında bookmarklet devreye girer.

### READ Komutu
Claude bir dosyanın içeriğini görmek istediğinde kullanır.

```
[READ: src/player.py]
```

Sunucu `src/player.py` dosyasını açar, içeriğini alır ve Claude'a geri gönderir. Claude artık dosyanın içeriğini bildiği için "tahmin etmek" zorunda kalmaz.

### LIST Komutu
Claude proje klasörünün yapısını görmek istediğinde kullanır.

```
[LIST: src/]
```

Sunucu o klasördeki dosya ve klasörlerin listesini döndürür. Claude böylece projenin haritasını çıkarır.

### SHELL Komutu
Claude bir terminal komutu çalıştırmak istediğinde kullanır.

```
[SHELL: python -m pytest tests/]
```

Sunucu bu komutu çalıştırır. Çıktıyı (başarı mesajı veya hata stack trace'i) Claude'a geri gönderir. Claude hatayı okur ve düzeltir. Bu tam olarak "Feedback Loop" — Claude Code'u Code yapan şey.

### PATCH Komutu
Claude bir değişiklik yapmak istediğinde kullanır. Dosyayı baştan yazmaz, sadece değişen kısmı belirtir.

```
[PATCH]
FILE: src/player.py
SEARCH:
def update():
    pass
REPLACE:
def update():
    self.velocity += self.gravity
    self.position += self.velocity
[/PATCH]
```

Sunucu dosyayı açar, SEARCH metnini bulur, REPLACE metniyle değiştirir. Eğer SEARCH metni bulunamazsa hata verir ve değişikliği uygulamaz. Her başarılı PATCH işleminden önce otomatik `git commit` atılır.

---

## 4. SEARCH/REPLACE Motoru — Teknik Detaylar

Bu motorun doğru çalışması projenin kalbidir. Yanlış çalışırsa dosyalar bozulur, kullanıcı güveni kaybolur. Bu yüzden şu önlemleri alıyoruz:

**Satır sonu normalizasyonu:** Windows `\r\n`, Mac/Linux `\n` kullanır. Aradaki fark bulma işlemini başarısız kılar. Motor her dosyayı ve her SEARCH metnini okurken satır sonlarını normalize eder, sonra geri dönüştürür.

**Benzersizlik kontrolü:** SEARCH metni dosyada birden fazla yerde geçiyorsa motor değişikliği redder ve kullanıcıya "Bu metin dosyada 3 farklı yerde bulunuyor, hangisini değiştireceğimi bilemem" der. Claude'dan daha spesifik bir SEARCH metni vermesi istenir.

**Syntax kontrolü:** Python dosyaları için değişiklik uygulandıktan sonra Python'un `ast` modülüyle syntax kontrolü yapılır. Syntax hatası varsa değişiklik geri alınır ve hata Claude'a bildirilir. Diğer diller için temel parantez/tırnak dengeleme kontrolü yapılır.

**Onay ekranı:** Her PATCH işleminden önce terminalde şu görünür:

```
⚠️  src/player.py — 3 satır değişecek
    - Satır 12: "def update():"  →  değişmiyor
    - Satır 13:     "pass"  →  SİLİNİYOR
    - Satır 13+:               →  2 satır ekleniyor

Onaylıyor musunuz? (y/n/diff)
```

`diff` yazılırsa tam fark gösterilir. `n` yazılırsa hiçbir şey değişmez.

---

## 5. Git Entegrasyonu

`.bak` dosyaları düzensizlik yaratır ve yönetimi zorlaşır. Git zaten bu iş için var.

Her başarılı PATCH işleminden sonra sunucu otomatik olarak şu komutu çalıştırır:

```
git add -A
git commit -m "bridge: player.py — update() fonksiyonu güncellendi"
```

Commit mesajı Claude'un değişiklik açıklamasından otomatik oluşturulur.

Kullanıcı `/undo` yazarsa Claude bu komutu `[SHELL: git revert HEAD --no-edit]` formatında çalıştırır ve son değişiklik geri alınır. Proje bozulma korkusu ortadan kalkar.

Proje klasöründe git yoksa sunucu otomatik `git init` yapar ve ilk commit'i atar.

---

## 6. Kurulum Deneyimi

Kullanıcının yapacağı şey üç adımdır:

**Adım 1:** Terminale tek komut yazılır.
```
pipx install claude-bridge
```

**Adım 2:** Sunucu başlatılır.
```
claude-bridge start
```
Sunucu tarayıcıya eklenecek bookmarklet kodunu ve Claude'a yapıştırılacak sistem promptunu ekrana yazar.

**Adım 3:** Bookmarklet yer imlerine sürüklenir. Sistem promptu Claude Projects'e yapıştırılır.

Bitti. Toplam süre: 3–5 dakika. Python dışında hiçbir bağımlılık yok. `pipx` sayesinde sistem Python'una dokunulmaz, izole bir ortamda çalışır.

---

## 7. Güvenlik Mimarisi

Güvenlik şüphesi projeyi öldürebilir. Bu yüzden şeffaflık birinci önceliktir.

**Yerel-only çalışma:** Sunucu hiçbir zaman `localhost:7337` dışına veri göndermez. Anthropic API'ye, analitiğe, hiçbir sunucuya bağlantı yoktur. Sadece Claude.ai sayfasındaki bookmarklet ile konuşur.

**Açık kaynak:** Tüm kod GitHub'da, MIT lisansıyla. 200 satır. Bir yazılımcı 5 dakikada okuyup "zararlı bir şey yok" diyebilir.

**İzin sistemi:** Sunucu ilk çalıştığında hangi klasöre erişebileceğini sorar. Sadece o klasör ve alt klasörlerine erişir. Sistem dosyalarına, ev dizinine veya başka yerlere dokunamaz.

**Onay zorunluluğu:** Hiçbir değişiklik onaysız uygulanmaz. İsterse "tüm oturumda otomatik onayla" modu aktif edilebilir ama varsayılan her seferinde sormaktır.

**SHELL kısıtlaması:** Terminal komutları için ikinci bir onay ekranı çıkar ve komut sarı renkte gösterilir. Tehlikeli komutlar (`rm -rf`, `sudo`, `chmod`) kara listeye alınmıştır, çalıştırılmaz.

---

## 8. Claude Code ile Karşılaştırma

| Özellik | Claude Code | Claude Bridge |
|---|---|---|
| Dosya okuma | ✅ Otomatik | ✅ Bookmarklet ile |
| Incremental edit | ✅ | ✅ SEARCH/REPLACE |
| Terminal çalıştırma | ✅ Otomatik | ✅ Onaylı |
| Feedback loop | ✅ | ✅ |
| Git entegrasyonu | ✅ | ✅ |
| Çoklu dosya edit | ✅ | ✅ |
| Otonom agent döngüsü | ✅ | ⚠️ Yarı-otonom |
| Kendi kendine ilerleme | ✅ | ❌ |
| Fiyat | Max plan (~$100/ay) | Pro plan ($20/ay) |
| Kurulum | Terminal gerekli | 3 adım |

Otonom agent döngüsü şimdilik eksik — Claude her adımda sizden onay bekler. Bu bir kısıtlama değil, güvenlik tercihidir. İleride "otonom mod" opsiyonel olarak eklenebilir.

---

## 9. Sürüm Planı

**V1 — Temel (İlk Çalışan Sürüm)**

Kapsam: Bookmarklet, localhost sunucu, Tool Protocol (READ/LIST/SHELL/PATCH), SEARCH/REPLACE motoru, onay sistemi, git entegrasyonu, syntax kontrolü, sistem promptu.

Hedef: "Çalışıyor mu?" sorusunu cevaplamak. Karmaşıklık eklemek yok.

**V2 — Akıllı Bağlam**

Büyük projelerde tüm dosyaları Claude'a göndermek kota harcar. V2'de proje indeksleme gelir: Claude "zıplama mekaniği" üzerine çalışırken sistem otomatik olarak sadece ilgili dosyaları (`Player.gd`, `Gravity.gd`) bağlama ekler.

**V3 — Arayüz (Opsiyonel)**

Küçük bir masaüstü penceresi: Proje klasörü seçici, aktif dosyalar listesi, son değişikliklerin diff görünümü, onay düğmesi. Terminal kullanmak istemeyenler için.

---

## 10. Proje İsmi ve Konumlandırma

İsim önerisi: **Claude Bridge** — işlevini (köprü) açıkça anlatır, telif hakkı sorunu yaratmaz, kolay hatırlanır. GitHub slug: `claude-bridge`.

README'nin ilk satırı şöyle olmalı:

> "Claude Pro aboneliğiniz varsa, Claude Code olmadan Claude Code deneyimi yaşayın."

Bu cümle projeyi bir cümlede anlatır ve doğru kitleyi çeker: Claude Code'u pahalı bulan veya erişimini kaybeden Pro kullanıcıları.

Proje Anthropic'in hiçbir kuralını ihlal etmez: Claude API'ye doğrudan bağlanmıyor, web scraping yapmıyor, kullanıcı web arayüzünü normal kullanıyor. Araç sadece kullanıcının tarayıcısında üretilen metni alıp yerel dosyalara uygular — bu tamamen meşru bir kullanımdır.
