# PHANTOM Bot

> Windows üzerinde çalışan, PyWebView arayüzlü, YOLO tabanlı çift istemci otomasyon projesi.
> Hedef algılama, HP takibi, hedef kuyruğu, otomatik loot, mesaj koruması, CAPTCHA modülleri,
> canlı debug görüntüsü ve ayrıntılı log sistemi tek arayüzde toplanır.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey)
![UI](https://img.shields.io/badge/UI-PyWebView%20%2B%20HTML%2FCSS-2f855a)
![Vision](https://img.shields.io/badge/Vision-Ultralytics%20YOLO-orange)
![Input](https://img.shields.io/badge/Input-SendInput%20%2F%20Interception-805ad5)

---

## İçindekiler

- [Kısa Özet](#kısa-özet)
- [Ekran Görüntüleri](#ekran-görüntüleri)
- [En İşe Yarayan Özellikler](#en-işe-yarayan-özellikler)
- [Özellikler](#özellikler)
- [Kurulum](#kurulum)
- [Başlatma](#başlatma)
- [İlk Kullanım Akışı](#ilk-kullanım-akışı)
- [Arayüz Rehberi](#arayüz-rehberi)
- [Interception ve Girdi Sistemi](#interception-ve-girdi-sistemi)
- [CAPTCHA ve Mesaj Koruması](#captcha-ve-mesaj-koruması)
- [Model ve Şablon Dosyaları](#model-ve-şablon-dosyaları)
- [Dosya Yapısı](#dosya-yapısı)
- [Ayarlar ve Loglar](#ayarlar-ve-loglar)
- [Sorun Giderme](#sorun-giderme)
- [Güvenlik ve Antivirüs](#güvenlik-ve-antivirüs)
- [Geliştirici Notları](#geliştirici-notları)
- [Sorumluluk Notu](#sorumluluk-notu)

---

## Kısa Özet

PHANTOM Bot, iki ayrı oyun istemcisini aynı panelden yönetmek için tasarlanmış bir otomasyon aracıdır. Her client için ayrı model, pencere, HP paneli ve canlı debug görüntüsü tutulur. Bot, ekrandaki hedefleri YOLO modeli ile algılar, HP durumuna göre savaş akışını takip eder, hedef öldüğünde loot toplar ve istatistikleri arayüzde gösterir.

Projenin hedefi, başka bir Windows bilgisayarda da minimum manuel işlemle çalışmaktır. Bu yüzden kurulum akışı `.venv` tabanlıdır; sistem Python ortamını kirletmez, eksik Python sürümünü indirir, gerekli paketleri kurar ve sonunda gerçek import testi yapar.

---

## Ekran Görüntüleri

| İstemci Paneli | Ayarlar ve İzleme |
| --- | --- |
| ![PHANTOM istemci paneli](docs/screenshots/ui_preview_1.png) | ![PHANTOM ayarlar paneli](docs/screenshots/ui_preview_2.png) |

---

## En İşe Yarayan Özellikler

| Özellik | Neden önemli? | Ne zaman kullanılmalı? |
| --- | --- | --- |
| Hedef Kuyruğu | Bir hedefte HP varken sıradaki hedefi hazırlayarak bekleme süresini azaltır. | Yoğun hedef bulunan alanlarda en verimli moddur. |
| HP Panel Seçimi | Botun savaşta mı, aramada mı olduğunu anlamasının ana sinyalidir. | İlk kurulumdan sonra her client için mutlaka seçilmelidir. |
| Canlı Debug Görüntüsü | Modelin ne gördüğünü, HP kutusunu ve hedef merkezini anında gösterir. | Yanlış tıklama, model görmeme veya HP algılama sorunlarında ilk bakılacak yerdir. |
| Interception / SendInput Katmanı | Girdi gönderimini otomatik olarak uygun yöntemle yapar. | Interception kullanılabiliyorsa daha düşük seviyeli input yolu devreye girer; yoksa SendInput ile çalışmaya devam eder. |
| Mesaj Koruması | Mesaj penceresi veya bildirim algılanınca farm akışını durdurup cevap göndermeye çalışır. | Uzun süreli kullanımda beklenmeyen mesaj pencereleri için faydalıdır. |
| Kurulum BAT Akışı | Python, sanal ortam, Torch, WebView2 ve paket kontrollerini tek dosyada toplar. | Projeyi başka PC’ye taşırken en kritik yardımcıdır. |
| Log Sistemi | Kurulum ve çalışma zamanı olaylarını dosyaya yazar. | Kullanıcı destek verirken “bende çalışmıyor” durumunu somut hataya çevirir. |

---

## Özellikler

### Çift Client Yönetimi

- `Client 1` ve `Client 2` ayrı ayrı açılıp kapatılabilir.
- Her client için ayrı oyun penceresi seçilir.
- Her client için model dosyası seçilebilir.
- Her client için HP panel alanı ayrı kaydedilir.
- Canlı görüntü ve debug aç/kapat kontrolü client bazlıdır.
- Ayarlar üstteki `C1 ON/OFF` ve `C2 ON/OFF` düğmeleriyle hızlıca değiştirilebilir.

### YOLO Tabanlı Hedef Algılama

- Ultralytics YOLO modeli ile oyun ekranındaki hedefler algılanır.
- Kararlı hedef filtresi, hedefin iki karede benzer konumda kalmasını bekler.
- Merkez yakınındaki hedefleri filtrelemek için `ignore_radius` kullanılır.
- `conf_esik` sabit olarak `0.50` uygulanır.
- Model inference GPU varsa CUDA üzerinde, yoksa CPU üzerinde çalışır.

### HP Takibi

- Kullanıcı her client için HP bar bölgesini seçer.
- Seçilen HP alanı template olarak `templates/hp_templates/` altında saklanır.
- Bot savaş durumunu HP görünürlüğüne göre takip eder.
- HP kaybolduğunda hedefin öldüğü kabul edilir ve kill istatistiği artar.

### Hedef Kuyruğu

Hedef Kuyruğu, özellikle seri hedef kesme akışında en yararlı otomasyon modlarından biridir.

- İlk hedefe tıklandıktan sonra HP görünürken sıradaki hedef hazırlanır.
- HP kaybolunca kill sayacı artar ve bot tekrar hedef aramaya döner.
- Hedef kuyruğu açıkken bot taze frame kontrolü yapar; eski görüntüye göre tıklamayı engeller.
- Hedefler blacklist mantığıyla tekrar tekrar aynı noktaya basmayacak şekilde filtrelenir.

### Otomatik Loot

- Hedef öldükten sonra `Z` tuşu ile loot toplama tetiklenir.
- Loot burst davranışı kısa aralıklarla birden fazla basış yapabilir.
- Oto Loot ayarı `Ayarlar > Otomasyon` bölümünden açılıp kapatılır.

### Anti-Stuck / Kurtarma

- Arama, savaş ve kuyruk durumlarında takılma belirtileri izlenir.
- Belirli süre hedef bulunmazsa veya savaş uzarsa kurtarma manevrası uygulanır.
- Geri ve yan hareket kombinasyonları ile karakterin sıkıştığı yerden çıkması hedeflenir.
- Varsayılan sabitler:
  - Savaş uzarsa kontrol: `15.0s`
  - Hareketsizlik kontrolü: `10.0s`
  - Kurtarma cooldown: `3.0s`

### Mesaj Koruması

- Mesaj bildirimi veya mesaj penceresi algılanırsa farm akışı global olarak duraklatılır.
- Bot kısa cevaplardan birini seçerek yanıt göndermeye çalışır.
- Yanıt sonrası ilgili client için farm kısa süre duraklatılır.
- Kendi gönderdiği mesajları tekrar gelen mesaj sanmamak için basit benzerlik ve geçmiş kontrolü kullanılır.

### CAPTCHA Modülleri

CAPTCHA varsayılan olarak kapalı gelir. Gerektiğinde `Ayarlar > Güvenlik > Captcha Tipi` menüsünden açılır.

- `Kapalı`: CAPTCHA solver tamamen devre dışı.
- `Origins Çözümleyici`: Origins matematik CAPTCHA akışına odaklanır.
- `Helios Algoritması`: Görsel seçim / hedef kelime benzeri tipler için kullanılır.
- `Merlis Motoru`: Bütünlüğü bozan veya farklı kare mantığındaki tipler için kullanılır.

CAPTCHA sistemi EasyOCR kullanır. OCR ilk açılışta model dosyalarını indirebileceği için ilk kullanımda hazır olması biraz zaman alabilir.

### Loglar ve İstatistik

- Arayüzde `Loglar` sekmesi vardır.
- Loglar temizlenebilir veya panoya kopyalanabilir.
- Kurulum logları `runtime/logs/kurulum_*.log` dosyalarına yazılır.
- Çalışma logları `runtime/logs/events_*.jsonl` dosyalarına yazılır.
- Client bazlı toplam kill ve süre bilgisi `Ayarlar` sekmesinde görüntülenir.

---

## Kurulum

### Önerilen Yöntem

Projeyi yeni bir Windows bilgisayara taşıdıktan sonra yalnızca şu dosyayı çalıştırın:

```bat
kurulum.bat
```

Kurulum scripti şunları yapar:

1. Python 3.11 var mı kontrol eder.
2. Python 3.11 yoksa resmi Python 3.11.9 kurulum dosyasını indirir.
3. Proje içinde `.venv` sanal ortamı oluşturur.
4. `pip`, `setuptools` ve `wheel` paketlerini günceller.
5. NVIDIA GPU varsa CUDA destekli Torch kurmayı dener.
6. CUDA Torch kurulamazsa CPU Torch’a otomatik düşer.
7. Proje bağımlılıklarını kurar:
   - `torch`, `torchvision`, `torchaudio`
   - `ultralytics`
   - `opencv-python`
   - `numpy`
   - `mss`
   - `keyboard`
   - `pywin32`
   - `pywebview`
   - `easyocr`
8. Microsoft WebView2 Runtime kurulumunu dener.
9. Son adımda gerçek import testi yapar.

Kurulum sırasında hata olursa terminalde kısa hata görünür. Ayrıntılı hata logu şurada tutulur:

```text
runtime/logs/kurulum_YYYYMMDD_HHMMSS.log
```

### Gereksinimler

| Bileşen | Gereksinim |
| --- | --- |
| İşletim sistemi | Windows 10 veya Windows 11, 64-bit |
| Python | Kurulum scripti Python 3.11.9 kurabilir |
| İnternet | İlk kurulumda Python, Torch, EasyOCR ve paketler için gerekli |
| GPU | Opsiyonel; NVIDIA GPU varsa CUDA Torch denenir |
| WebView2 | Kurulum scripti kurmayı dener; çoğu Windows 10/11 sistemde zaten yüklüdür |
| Yetki | Bot başlatıcı yönetici izni ister |

### Neden `.venv` Kullanılıyor?

`.venv`, bağımlılıkları proje içine izole eder. Böylece başka bir PC’de sistem Python’u farklı olsa bile bot kendi ortamından çalışır. Bu yaklaşım özellikle Torch, EasyOCR ve pywin32 gibi Windows’ta hassas bağımlılıklar için daha kararlıdır.

---

## Başlatma

Kurulumdan sonra botu başlatmak için:

```bat
PHANTOM.bat
```

`PHANTOM.bat` şu davranışlara sahiptir:

- Yönetici izni ister.
- `.venv` yoksa `kurulum.bat /auto` çalıştırır.
- Kurulum başarılıysa `metin_bot_webview.py` dosyasını `.venv` içindeki Python ile başlatır.
- Uygulama hata ile kapanırsa terminal penceresini açık bırakır.

Kısayol:

| Tuş | İşlev |
| --- | --- |
| `F5` | Botu başlatır veya durdurur |

---

## İlk Kullanım Akışı

1. `kurulum.bat` dosyasını çalıştırın.
2. Kurulum bittikten sonra `PHANTOM.bat` dosyasını açın.
3. `İstemciler` sekmesinde `Client 1` için model seçin.
4. `Pencere` listesinden oyun penceresini seçin.
5. `HP Panel` düğmesiyle HP bar alanını ekrandan seçin.
6. Gerekirse aynı işlemleri `Client 2` için de yapın.
7. `Ayarlar` sekmesinden Oto Loot, Hedef Kuyruğu, Kurtarma ve CAPTCHA durumunu ayarlayın.
8. Debug görüntüsünde hedef ve HP kutularının doğru göründüğünü kontrol edin.
9. `Başlat` düğmesine veya `F5` tuşuna basın.

---

## Arayüz Rehberi

### İstemciler Sekmesi

| Alan | Açıklama |
| --- | --- |
| Model | Client için kullanılacak `.pt` YOLO modelini seçer. |
| Pencere | Otomasyon yapılacak oyun penceresini seçer. |
| HP Panel | HP bar bölgesini seçmek için ekran üzerinden ROI seçimi açar. |
| Canlı Görüntü | Debug feed üzerinde model çıktısını, merkez çizgisini ve HP alanını gösterir. |
| Debug | Görüntü encode ve arayüz feed maliyetini açar/kapatır. |
| C1/C2 ON-OFF | Client’ın aktif olup olmayacağını belirler. |

### Ayarlar Sekmesi

| Alan | Açıklama |
| --- | --- |
| Captcha Tipi | CAPTCHA solver modunu seçer. Varsayılan: `Kapalı`. |
| Mesaj Koruması | Mesaj algılama ve otomatik cevap sistemini açar/kapatır. |
| Kurtarma | Takılma ve hareketsizlik kurtarma manevralarını açar/kapatır. |
| Oto Loot | Hedef öldüğünde loot toplama basışlarını açar/kapatır. |
| Hedef Kuyruğu | Seri hedef akışı için sıradaki hedefi hazırlayan modu açar/kapatır. |
| Toplam Kill | Client bazlı kill sayacını gösterir. |
| Süre | Botun açık kaldığı süreyi gösterir. |

### Loglar Sekmesi

| Alan | Açıklama |
| --- | --- |
| Temizle | Arayüzde görünen logları temizler; dosyadaki logları silmez. |
| Kopyala | Görünen logları panoya kopyalar. |

---

## Interception ve Girdi Sistemi

PHANTOM, Windows girdi katmanında iki seviye kullanır:

1. **Interception**: Düşük seviyeli mouse/klavye sürücüsü. Sistemde yüklüyse aktif olur.
2. **SendInput**: Windows API varsayılan yöntemi. Interception yoksa otomatik devreye girer.

Bu tasarım sayesinde Interception kurulu olmayan bilgisayarlarda bot hata vermeden SendInput ile çalışmaya devam eder.

### Interception Kurulumu (Önerilir)

Interception, daha kararlı ve düşük seviyeli girdi sağlar. Kurulum tek seferliktir:

1. **Kurulum dosyasını çalıştırın:**
   ```text
   lib/interception/install-interception.exe
   ```
   Bu dosya Interception sürücüsünü sisteme yükler. **Yönetici izni gerekir.**

2. **Bilgisayarı yeniden başlatın.**
   Sürücünün aktif olması için restart şarttır.

3. **Botu başlatın.**
   Açılış loglarında `Interception hazir` görürseniz kurulum başarılıdır.

> **Not:** `install-interception.exe` yalnızca Windows sürücü katmanına bir filter driver yükler; arka planda çalışan bir uygulama değildir. Kaldırmak isterseniz aynı `.exe`'yi tekrar çalıştırabilirsiniz.

### İlgili Dosyalar

| Dosya | Açıklama |
| --- | --- |
| `interception.dll` | **(Kök dizin)** Botun çalışma zamanında doğrudan yüklediği `x64` kütüphane. |
| `lib/interception/install-interception.exe` | Sürücüyü sisteme yükleyen resmi komut satırı kurulum aracı. |
| `lib/interception/x64/interception.dll` | 64-bit kütüphane (kökteki ile aynı). |
| `lib/interception/x86/interception.dll` | 32-bit kütüphane (nadir durumlar için). |
| `lib/interception/interception.h` | C/C++ header dosyası. |
| `lib/interception/LICENSE.txt` | LGPL 3.0 lisansı. |

### Hangi DLL Kullanılıyor?

Bot çalıştığında önce proje **kökündeki** `interception.dll`'yi dener. Bu dosya `x64` sürümüdür ve modern Windows 10/11 sistemler için uygundur.

Eğer çok nadir de olsa 32-bit (x86) bir sistemde çalıştırırsanız, `lib/interception/x86/interception.dll` dosyasını proje köküne `interception.dll` adıyla kopyalayabilirsiniz.

> **Önemli:** `.gitignore` dosyası, kök dizindeki `interception.dll` ve `lib/interception/` altındaki kütüphane dosyaları için istisna tanımlıdır. Projeyi Git veya ZIP ile başka PC'ye taşırken bu dosyaların da gittiğinden emin olun.

### Interception Hazır Değilse Ne Olur?

Bot otomatik olarak SendInput moduna düşer. Bu durumda:

- Mouse hareketi Windows `SetCursorPos` ve `SendInput` ile yapılır.
- Klavye basışları `keyboard` paketi üzerinden gönderilir.
- Arayüzde ve loglarda `Interception bulunamadi` / `Tiklama modu: SendInput` benzeri kayıtlar görülebilir.

---

## CAPTCHA ve Mesaj Koruması

CAPTCHA sistemi `src/phantom/captcha/solver.py` içinde yer alır ve `CaptchaWatcher` sınıfı ile çalışır.

### CAPTCHA Dosyaları

| Dosya | Amaç |
| --- | --- |
| `templates/captcha_template/captcha_template.png` | CAPTCHA dialog doğrulama ve template scan için kullanılır. |
| `templates/captcha_keypad/captcha_keypad.png` | Sayısal keypad / görsel doğrulama akışlarında referans olarak kullanılır. |
| `runtime/captcha_kontrol/` | Çözüm öncesi veya teşhis amaçlı CAPTCHA görüntülerinin kaydedildiği klasördür. |

### CAPTCHA Tipleri

| Arayüz seçeneği | Teknik karşılık | Açıklama |
| --- | --- | --- |
| Kapalı | `captcha=false`, tüm tipler `false` | Solver devre dışı. Varsayılan ve en güvenli başlangıç modudur. |
| Origins Çözümleyici | `captcha_tip4=true` | Matematik / toplam sonucu isteyen Origins tipi dialoglar için kullanılır. |
| Helios Algoritması | `captcha_tip1=true` | Görsel veya hedef kelime seçimi mantığındaki tipler için kullanılır. |
| Merlis Motoru | `captcha_tip2=true` | Farklı kare veya bütünlüğü bozan kare seçimi mantığındaki tipler için kullanılır. |

### Mesaj Koruması Nasıl Çalışır?

- Mesaj bildirimi veya açık mesaj penceresi aranır.
- Sarı mesaj satırları OCR ile okunabilir.
- Kısa ve bağlama göre seçilen cevaplar gönderilir.
- Mesaj cevaplandıktan sonra farm kısa süre duraklatılır.
- CAPTCHA aktifse mesaj işlemi CAPTCHA bekleme durumuna saygı gösterir.

---

## Model ve Şablon Dosyaları

### Hazır Modeller

| Dosya | Açıklama |
| --- | --- |
| `models/Büyülü_metni.pt` | Büyülü metin modeli. |
| `models/Guatama_metni.pt` | Guatama metni modeli. |
| `models/Gölge_metni.pt` | Gölge metni modeli. |
| `models/Kızıl_metni.pt` | Kızıl metin modeli. |

Model seçimi client bazlı yapılır. Yanlış model seçilirse hedef algılama performansı doğrudan düşer. En iyi sonuç için bulunduğunuz harita ve hedef tipine uygun modeli seçin.

### Şablonlar

| Klasör | Açıklama |
| --- | --- |
| `templates/hp_templates/` | Client HP template dosyaları burada oluşur. |
| `templates/message_templates/` | Mesaj / GM bildirimi benzeri template dosyaları. |
| `templates/captcha_template/` | CAPTCHA dialog doğrulama template’i. |
| `templates/captcha_keypad/` | CAPTCHA keypad template’i. |

---

## Dosya Yapısı

```text
PHANTOM_BOT/
├─ PHANTOM.bat
├─ kurulum.bat
├─ metin_bot_webview.py
├─ captcha_solver.py
├─ interception.dll
├─ index.html
├─ config_phantom.json
├─ lib/
│  └─ interception/
│     ├─ install-interception.exe
│     ├─ interception.h
│     ├─ x64/
│     │  └─ interception.dll
│     ├─ x86/
│     │  └─ interception.dll
│     └─ LICENSE.txt
├─ models/
│  ├─ Büyülü_metni.pt
│  ├─ Guatama_metni.pt
│  ├─ Gölge_metni.pt
│  └─ Kızıl_metni.pt
├─ templates/
│  ├─ captcha_keypad/
│  ├─ captcha_template/
│  ├─ hp_templates/
│  └─ message_templates/
├─ runtime/
│  ├─ logs/
│  ├─ evidence/
│  └─ captcha_kontrol/
├─ src/
│  └─ phantom/
│     ├─ app/
│     ├─ captcha/
│     ├─ automation/
│     ├─ core/
│     ├─ input/
│     └─ vision/
└─ docs/
   └─ screenshots/
```

### Ana Dosyalar

| Dosya / Klasör | Rol |
| --- | --- |
| `PHANTOM.bat` | Yönetici yetkisi ister, `.venv` yoksa kurulum yapar, botu başlatır. |
| `kurulum.bat` | Tek tık kurulum dosyasıdır. Python, `.venv`, paketler ve WebView2 kontrolünü yapar. |
| `metin_bot_webview.py` | Eski giriş noktasını koruyan launcher dosyasıdır. |
| `index.html` | PyWebView içinde çalışan arayüzdür. |
| `interception.dll` | Çalışma zamanında yüklenen Interception kütüphanesi (`x64`). |
| `lib/interception/` | Interception sürücü kurulum aracı, `x86`/`x64` kütüphaneleri ve lisans dosyası. |
| `src/phantom/app/main.py` | Ana uygulama, state, thread’ler, API ve otomasyon akışı. |
| `src/phantom/captcha/solver.py` | CAPTCHA ve OCR çözüm motoru. |
| `config_phantom.json` | Kullanıcı ayarlarını tutar. |

---

## Ayarlar ve Loglar

### `config_phantom.json`

Bu dosya kullanıcıya özel ayarları tutar:

- Client aktif/pasif durumu
- Pencere seçimi
- Model yolu
- HP region bilgisi
- CAPTCHA seçenekleri
- Mesaj koruması
- Oto Loot
- Hedef kuyruğu
- Kurtarma seçenekleri

Bu dosya `.gitignore` içindedir. Her kullanıcı kendi bilgisayarında kendi pencere ID’lerine ve HP alanlarına sahip olmalıdır.

### `runtime/logs/`

| Dosya tipi | Açıklama |
| --- | --- |
| `kurulum_*.log` | Kurulum sırasında çalışan komutlar ve hata detayları. |
| `events_*.jsonl` | Bot çalışma zamanı olayları. |

Log dosyaları destek ve hata ayıklama için ilk bakılacak yerdir.

### `runtime/evidence/`

Bazı olaylarda ekran görüntüsü veya kanıt amaçlı capture dosyaları kaydedilebilir.

### `runtime/captcha_kontrol/`

CAPTCHA çözüm denemelerinde kaydedilen teşhis görüntülerini içerir.

---

## Güvenlik ve Antivirüs

Bu proje açık kaynaklıdır. Aşağıdaki hash değerleri ile indirdiğiniz dosyaların bütünlüğünü doğrulayabilirsiniz.

### SHA256 Hash Değerleri

| Dosya | SHA256 |
| --- | --- |
| `PHANTOM.bat` | `42B45798DBD01651B1287F6D4921E0DD7C809C5624DAE17BF98D2F90066B9C6D` |
| `kurulum.bat` | `451D51C1E13D83018ADD73E1E0B765AC9DDE710C067606055CB222FB793CEF9A` |
| `interception.dll` (kök) | `AB88164C11B1B48488772D4C3BFAA4509D5B0AE9DBC5A691DC4F96F0260443C8` |
| `lib/interception/install-interception.exe` | `E137863A79DA797F08E7A137280FF2A123809044A888FD75CE9C973198915ABE` |
| `lib/interception/x64/interception.dll` | `AB88164C11B1B48488772D4C3BFAA4509D5B0AE9DBC5A691DC4F96F0260443C8` |
| `lib/interception/x86/interception.dll` | `9E1DEF27B804DF9BA97FD07F9DE835C70660AE568C00950102F70034E293A684` |

> Hash kontrolü Windows'ta şu komutla yapılabilir: `Get-FileHash -Path <dosya> -Algorithm SHA256`

### VirusTotal Taraması

Dosyaların antivirüs motorları tarafından taranmış hâllerini görmek için:

1. [virustotal.com](https://www.virustotal.com/gui/home/upload) adresine gidin.
2. Yukarıdaki dosyalardan birini yükleyin.
3. Tarama raporunu inceleyin.

**Yaygın Durum:** `install-interception.exe` ve `interception.dll` gibi düşük seviyeli girdi (input) sürücüleri içeren dosyalar, bazı antivirüsler tarafından **davranışsal analiz** (`HackTool`, `Suspicious`, `PUA`) ile işaretlenebilir. Bu, dosyanın gerçekten zararlı olduğu anlamına gelmez; yalnızca sistemin girdi katmanına müdahale edebilecek bir araç olduğunu gösterir.

Proje kaynak kodları açıktır. Şüphe duyarsanız `src/` klasörünü inceleyebilir ve kodu kendiniz derleyebilirsiniz.

---

## Sorun Giderme

### `PHANTOM.bat` açılıyor ama uygulama gelmiyor

1. `runtime/logs/` klasöründeki son log dosyasını kontrol edin.
2. `.venv\Scripts\python.exe` dosyasının oluştuğunu doğrulayın.
3. `kurulum.bat` dosyasını tekrar çalıştırın.
4. WebView2 Runtime kurulumunun tamamlandığından emin olun.

### Kurulum Torch aşamasında uzun sürüyor

Torch büyük bir pakettir. CUDA sürümü indiriliyorsa dosya boyutu daha yüksek olabilir. Bu aşama internet hızına göre uzun sürebilir.

### CUDA kurulumu başarısız oldu

Kurulum scripti CUDA Torch başarısız olursa CPU Torch’a düşer. Bot yine çalışır, ancak model inference daha yavaş olabilir. NVIDIA sürücüsünü güncellemek performans için faydalı olabilir.

### Pencere listesinde oyun görünmüyor

- Oyunun açık olduğundan emin olun.
- Arayüzde pencere yenile düğmesine basın.
- Oyunu minimize etmeyin.
- `PHANTOM.bat` yönetici izniyle çalışmalıdır.

### Debug görüntüsü `NO_SIGNAL` gösteriyor

- Botun başlatıldığından emin olun.
- Client aktif olmalı (`C1 ON` veya `C2 ON`).
- Pencere doğru seçilmiş olmalı.
- Seçilen pencere minimize durumda olmamalı.
- Debug toggle açık olmalı.

### HP algılanmıyor

- HP paneli yeniden seçin.
- HP bar seçimini mümkün olduğunca dar ve sabit alana yapın.
- Farklı çözünürlük veya UI ölçeği kullanıyorsanız HP template’i yeniden oluşturun.
- Debug görüntüsünde HP kutusunun doğru yerde olduğundan emin olun.

### Bot hedefe tıklamıyor

- Doğru YOLO modelini seçin.
- Debug görüntüsünde hedef kutularının çıkıp çıkmadığını kontrol edin.
- Hedef Kuyruğu kapalıysa hedefin kararlı algılanması birkaç kare sürebilir.
- Pencere focus sorunu varsa botu yönetici olarak çalıştırın.

### Interception çalışmıyor

Bu kritik bir hata değildir. Bot otomatik SendInput moduna geçer. Loglarda `Interception bulunamadi` ve `Tiklama modu: SendInput` benzeri kayıtlar görülebilir.

### EasyOCR hazır değil uyarısı

İlk çalıştırmada OCR modelleri hazırlanırken bekleme olabilir. İnternet bağlantısı ve `.venv` kurulumunun tamamlandığını kontrol edin.

### CAPTCHA yanlış algılanıyor

- CAPTCHA tipini ihtiyacınız yoksa `Kapalı` bırakın.
- Doğru CAPTCHA tipi seçildiğinden emin olun.
- `templates/captcha_template/captcha_template.png` dosyasının yerinde olduğundan emin olun.
- `runtime/captcha_kontrol/` klasöründeki kayıtları kontrol edin.

---

## Geliştirici Notları

### Python Kontrolü

Kurulum scripti Python 3.11’i hedefler. Bunun nedeni Torch, EasyOCR, pywin32 ve WebView bağımlılıklarında sürüm uyumluluğunu daha öngörülebilir tutmaktır.

### Sanal Ortamı Temizlemek

Bağımlılıkları sıfırdan kurmak için `.venv` klasörünü silip `kurulum.bat` dosyasını tekrar çalıştırabilirsiniz.

```bat
rmdir /s /q .venv
kurulum.bat
```

### Kod Sağlık Kontrolü

Python sözdizimi kontrolü için:

```bat
.venv\Scripts\python.exe -m compileall -q src captcha_solver.py metin_bot_webview.py
```

### Ana Thread’ler

| Thread / Katman | Görev |
| --- | --- |
| VisionThread | Ekran yakalama, model inference, HP ve template kontrolleri. |
| ActionThread | Durum makinesi, hedef seçimi, tıklama, loot ve kurtarma davranışı. |
| CaptchaWatcher | CAPTCHA dialog algılama, OCR ve çözüm aksiyonları. |
| PyWebView API | Arayüz ile Python state’i arasında köprü. |

### Durum Akışı

Botun temel durumları şunlardır:

```text
ARANIYOR -> DOGRULAMA -> SAVASIYOR -> ARANIYOR
```

Hedef kuyruğu açıkken akış `KUYRUK` durumunu da kullanır. CAPTCHA veya mesaj sırasında global pause devreye girer:

```text
CAPTCHA / CAPTCHA BEKLE
MESAJ / MESAJ BEKLE
```

---

## Sorumluluk Notu

Bu proje otomasyon, görüntü işleme ve Windows input yönetimi üzerine teknik bir çalışmadır. Kullanıldığı ortamın kurallarını, hizmet şartlarını ve hesap güvenliği risklerini değerlendirmek kullanıcının sorumluluğundadır. Proje sahibi veya geliştirici, kullanım sonucunda oluşabilecek hesap kısıtlaması, veri kaybı, sistem hatası veya üçüncü taraf yaptırımlarından sorumlu değildir.
