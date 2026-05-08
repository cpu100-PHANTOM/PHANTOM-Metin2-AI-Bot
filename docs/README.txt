PHANTOM - Metin2 AI Bot
Kurulum ve Kullanım Rehberi

═══════════════════════════════════════════════════════════════
HAKKINDA
═══════════════════════════════════════════════════════════════

PHANTOM, Metin2 oyunu için hazırlanmış yapay zeka destekli bir bottur.
YOLO tabanlı görüntü işleme, otomatik hedef tıklama, HP takibi 
ve CAPTCHA çözme özellikleri vardır.

Sadece Windows'ta çalışır. Mac veya Linux desteği yoktur.


═══════════════════════════════════════════════════════════════
KURULUM
═══════════════════════════════════════════════════════════════

1) Python İndir
   https://www.python.org/downloads/
   
   Python 3.10, 3.11 veya 3.12 64-bit sürümünü indir.
   Kurulumda "Add Python to PATH" işaretli olsun.

2) Kütüphaneleri Kur
   İki yöntemden birini kullan:

   a) Otomatik (Önerilen):
      Dosya klasöründe "kurulum.bat" çift tıkla

   b) Manuel:
      cmd veya PowerShell'de şu komutu çalıştır:
      pip install opencv-python numpy mss keyboard ultralytics torch pywin32 pyglet easyocr

   İlk kurulum 5-15 dakika sürebilir, özellikle torch ve easyocr biraz bekletir.


═══════════════════════════════════════════════════════════════
KULLANIM
═══════════════════════════════════════════════════════════════

1) Botu Aç
   "PHANTOM.bat" dosyasına çift tıkla
   (Yönetici yetkisi isteyebilir)

2) İlk Ayarlar
   - Model dosyası seç (.pt uzantılı YOLO modeli)
   - Oyun penceresini seç
   - HP panel bölgesini fare ile çizerek seç
   - İstersen skill, loot ve CAPTCHA ayarlarını yap

3) Çalıştır
   "BASLAT" butonuna veya F5 tuşuna bas

4) Klavye Kısayolları
   F5           → Botu başlat/durdur
   SHIFT+LİK   → Manuel tıklama


═══════════════════════════════════════════════════════════════
AYARLAR
═══════════════════════════════════════════════════════════════

conf_esik      → Model güven eşiği (0.60 önerilir)
hp_bekleme_sn  → HP yokken bekleme süresi
dogrulama_sn   → Hedef tıklama sonrası bekleme
oto_loot      → Otomatik loot (Z tuşu)
anti_stuck   → Takılma önleyici
captcha      → CAPTCHA çözme
eco_mode     → CPU modu (düşük performans)
cember_yaricap → Hedef dairesi yarıçapı


═══════════════════════════════════════════════════════════════
SORUNLAR VE ÇÖZÜMLER
═══════════════════════════════════════════════════════════════

Python bulunamıyor:
   → Python kurulu mu kontrol et
   → PATH ayarını kontrol et
   → Bilgisayarı yeniden başlat

Kütüphane hatası:
   → pip güncelle: pip install --upgrade pip
   → Internet bağlantısını kontrol et
   → kurulum.bat tekrar çalıştır

Bot çalışmıyor:
   → Model dosyası seçildi mi?
   → Pencere doğru seçildi mi?
   → HP bölgesi işaretlendi mi?

HP algılamıyor:
   → HP panelini yeniden seç
   → Daha temiz bir alan seç

CAPTCHA çözülmüyor:
   → Internet var mı kontrol et
   → easyocr yüklü mü bak


═══════════════════════════════════════════════════════════════
DOSYALAR
═══════════════════════════════════════════════════════════════

Proje klasöründe olması gerekenler:
   metin_bot_webview.py   → Ana bot dosyası
   captcha_solver.py      → CAPTCHA modülü
   PHANTOM.bat          → Çalıştırıcı
   kurulum.bat          → Kütüphane kurucu
   index.html          → Arayüz dosyası

Otomatik oluşanlar:
   config_phantom.json   → Ayarlar (ilk açılışta oluşur)
   templates/          → HP şablonları (seçim yapınca oluşur)


═══════════════════════════════════════════════════════
HIZLI BAŞLANGIÇ
═══════════════════════════════════════════════════════

Adımlar:
1. Python 3.10-3.11 kur
2. kurulum.bat çalıştır
3. Metin2 oyununu başlat
4. PHANTOM.bat aç
5. Model seç
6. Pencere seç
7. HP seç
8. F5 baslat

Bu kadar.


═══════════════════════════════════════════════════════════════
İLETİŞİM
═══════════════════════════════════════════════════════════════

Herhangi bir sorunda kodu inceleyebilir veya kendi başına
ayarlamalar yapabilirsin.

İyi oyunlar!