import ctypes
import os
import re
import threading
import time

import cv2
import numpy as np
import win32gui

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_PACKAGE_DIR, "..", "..", ".."))
_SCRIPT_DIR = _PROJECT_ROOT
_RUNTIME_DIR = os.path.join(_PROJECT_ROOT, "runtime")

PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),("mouseData",ctypes.c_ulong),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]
class INPUT_UNION(ctypes.Structure):
    _fields_ = [("mi",MOUSEINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type",ctypes.c_ulong),("iu",INPUT_UNION)]

_extra = ctypes.c_ulong(0)
def _send_mouse_input(flags):
    iu = INPUT_UNION(); iu.mi = MOUSEINPUT(0,0,0,flags,0,ctypes.pointer(_extra))
    cmd = INPUT(0, iu)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))


class CaptchaWatcher:
    def __init__(self, client_id=0, log_cb=None):
        self._client_id = client_id
        self._log_cb    = log_cb   # callable(level:str, msg:str) | None
        self._reader = None
        self._lock = threading.Lock()
        self._hazir = False
        self._son_cozum = 0.0
        self._cooldown = 1.0
        self._son_basarisiz = 0.0
        self._basarisiz_cd = 0.6
        self._son_tiklama = 0.0
        self.last_status = "init"
        self.last_detail = ""
        self._last_dialog_log = 0.0
        self._enabled_tips = {"tip1": False, "tip2": False, "tip3": False, "tip4": False}
        # Captcha template — captcha_template.png varsa yükle
        self._header_tpl      = None   # gri template görüntüsü
        self._header_tpl_path = os.path.join(_SCRIPT_DIR, "templates", "captcha_template", "captcha_template.png")
        # Full-dialog modu için layout bilgileri
        self._tpl_mode         = "none"   # "none" | "header" | "full"
        self._tpl_mask         = None     # math expression bandı hariç tutan maske
        self._input_rel_cx     = None     # template içi input merkez x
        self._input_rel_cy     = None
        self._send_rel_cx      = None     # template içi Send merkez x
        self._send_rel_cy      = None
        self._expr_rel_y1      = None     # math expression bandı (template y)
        self._expr_rel_y2      = None
        # Son başarılı template eşleşmesi (dialog_roi içindeki konum)
        self._last_match_loc   = None     # (x, y)
        self._last_match_scale = 1.0
        self._load_template()
        threading.Thread(target=self._init_ocr, daemon=True).start()

    def _load_template(self):
        """captcha_template.png yükler. Yükseklik ≥ 60 px → full-dialog modu;
        aksi halde header modu. Full modunda input/Send konumlarını otomatik
        tespit edip göreli olarak saklar ve math expression bandını maskeler.
        """
        # Varsayılanlar
        self._header_tpl   = None
        self._tpl_mode     = "none"
        self._tpl_mask     = None
        self._input_rel_cx = self._input_rel_cy = None
        self._send_rel_cx  = self._send_rel_cy  = None
        self._expr_rel_y1  = self._expr_rel_y2  = None

        if not os.path.exists(self._header_tpl_path):
            return
        img = cv2.imread(self._header_tpl_path)
        if img is None:
            return

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._header_tpl = gray
        th, tw = gray.shape[:2]

        if th < 60:
            # ── Header modu (geri uyum) ──
            self._tpl_mode = "header"
            self._log("info", f"Captcha template yuklenid: {tw}x{th}px (HEADER mod)")
            return

        # ── Full-dialog modu: input kutusu + Send butonu konumlarını bul ──
        self._tpl_mode = "full"

        # Math expression bandı (yaklaşık %22-%50) — maskeleme için
        self._expr_rel_y1 = int(th * 0.22)
        self._expr_rel_y2 = int(th * 0.50)

        # Edge tabanlı dikdörtgen tespiti — koyu arka planda contour+threshold
        # başarısız oluyor çünkü tüm diyalog koyu. Canny kenarları ile input
        # ve Send kutularını aynı anda tespit edip y sıralamasıyla ayırıyoruz.
        edges = cv2.Canny(gray, 40, 130)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        cnts_e, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []  # (y_top, x, w, h)
        for cnt in cnts_e:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if cw < int(tw * 0.25) or ch < 10:
                continue
            if ch > int(th * 0.40):
                continue
            if cw > int(tw * 0.95):        # neredeyse tam genişlik → diyalog kenarlığı
                continue
            aspect = cw / max(ch, 1)
            if not (1.5 <= aspect <= 14.0):
                continue
            cx_pen = abs((x + cw / 2.0) - tw / 2.0) / max(tw / 2.0, 1.0)
            if cx_pen > 0.30:               # merkeze yakın olmalı
                continue
            # Alt yarıda olsun (instruction/math bandını eleme)
            if y + ch / 2.0 < th * 0.45:
                continue
            candidates.append((y, x, cw, ch))

        # y'ye göre aynı satırdakileri birleştir (en büyük dış dikdörtgeni al)
        candidates.sort()
        merged = []
        for y, x, cw, ch in candidates:
            placed = False
            for i, (my, mx, mw, mh) in enumerate(merged):
                if abs(y - my) <= 6 or (my <= y <= my + mh) or (y <= my <= y + ch):
                    # aynı satır → birleştirilmiş bbox
                    nx1 = min(x, mx); ny1 = min(y, my)
                    nx2 = max(x + cw, mx + mw); ny2 = max(y + ch, my + mh)
                    merged[i] = (ny1, nx1, nx2 - nx1, ny2 - ny1)
                    placed = True
                    break
            if not placed:
                merged.append((y, x, cw, ch))

        input_box = None
        send_box  = None
        if len(merged) >= 2:
            merged.sort()  # y artan
            # En alttaki Send (daha ince), onun üstü input
            send_box  = merged[-1]
            input_box = merged[-2]
            # Aspect kontrolü ile karıştırmayı önle: input genelde daha geniş & uzun
            if (send_box[2] * send_box[3]) > (input_box[2] * input_box[3]):
                input_box, send_box = send_box, input_box
        elif len(merged) == 1:
            # Tek kutu bulundu — alt yarıya göre input mı Send mi?
            only = merged[0]
            if only[0] + only[3] / 2.0 > th * 0.75:
                send_box = only
            else:
                input_box = only

        # Tuple formatı: (x, y, w, h)
        if input_box is not None:
            input_box = (input_box[1], input_box[0], input_box[2], input_box[3])
        if send_box is not None:
            send_box = (send_box[1], send_box[0], send_box[2], send_box[3])

        # Sonuçları sakla; bulunamadıysa makul varsayılanlar kullan
        if input_box is not None:
            self._input_rel_cx = input_box[0] + input_box[2] // 2
            self._input_rel_cy = input_box[1] + input_box[3] // 2
        else:
            self._input_rel_cx = tw // 2
            self._input_rel_cy = int(th * 0.60)
            self._log("warn", "Template FULL: input kutusu auto-detect basarisiz, varsayilan kullanildi")

        if send_box is not None:
            self._send_rel_cx = send_box[0] + send_box[2] // 2
            self._send_rel_cy = send_box[1] + send_box[3] // 2
        else:
            self._send_rel_cx = tw // 2
            self._send_rel_cy = int(th * 0.88)
            self._log("warn", "Template FULL: Send butonu auto-detect basarisiz, varsayilan kullanildi")

        # Maske: degisen alanlari 0 (yok say), gerisi 255.
        # Math ifadesi her captcha'da degisir; input icinde de onceki denemeden
        # kalmis cevap veya bos alan olabilir. Kenarlari sabit kaldigi icin
        # sadece ic dolguyu maskeliyoruz.
        mask = np.full((th, tw), 255, dtype=np.uint8)
        mask[self._expr_rel_y1:self._expr_rel_y2, :] = 0
        if input_box is not None:
            ix, iy, iw, ih = input_box
            pad_x = max(2, int(iw * 0.03))
            pad_y = max(2, int(ih * 0.18))
            mask[max(0, iy + pad_y):min(th, iy + ih - pad_y),
                 max(0, ix + pad_x):min(tw, ix + iw - pad_x)] = 0
        self._tpl_mask = mask

        self._log(
            "info",
            f"Template FULL mod: dialog={tw}x{th}, "
            f"input_rel=({self._input_rel_cx},{self._input_rel_cy}), "
            f"send_rel=({self._send_rel_cx},{self._send_rel_cy}), "
            f"math_band=({self._expr_rel_y1}-{self._expr_rel_y2})"
        )

    # UI'ye yalnızca bu metin parçacıklarını içeren mesajlar iletilir;
    # terminal gürültüsüz kalır ama diagnoz için kritik noktalar görünür.
    _UI_LOG_ALLOWLIST = (
        "CAPTCHA ÇÖZÜLDÜ",           # success
        "CAPTCHA ÇÖZÜLEMEDİ",        # basarisiz
        "Captcha tespit edildi",     # kontrol attempt
        "Template skor",             # match skor (fail diagnoz)
        "Template eslesmedi",
        "OCR hata",
        "yanlis captcha",
        "iptal",
        "_coz girdi",                # diagnoz: fast-path koşulları
        "FAST-PATH",                 # diagnoz: aktif/yönlendirme
        "Origins FULL",              # diagnoz: fast-path icindeki hata yolları
        "Expr",                      # diagnoz: math OCR teşhisi
        "ADIM",                      # diagnoz: tıklama/yazma adımları
        "CAPTCHA GORUNTUSU",         # cozum oncesi kontrol kaydi
    )

    def _log(self, level, msg):
        """UI'ye gürültüsüz log yayını. Success + hedeflenen diagnoz mesajları
        geçer; geri kalan hepsi konsola gider, UI terminali temiz kalır.
        """
        tag = f"[CAPTCHA-C{self._client_id}]"
        line = f"{tag} {msg}"
        try:
            print(line)          # konsolda her seviye görünür
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))
        if not self._log_cb:
            return
        allow = (level == "success" or level == "error")
        if not allow:
            for kw in self._UI_LOG_ALLOWLIST:
                if kw in msg:
                    allow = True
                    break
        if allow:
            try:
                self._log_cb(level, f"{tag} {msg}")
            except Exception:
                pass

    def _set_status(self, status, detail=""):
        with self._lock:
            self.last_status = status
            self.last_detail = detail

    def _safe_file_part(self, text, limit=32):
        cleaned = re.sub(r'[^0-9A-Za-z_+=-]+', '_', str(text or ""))
        cleaned = cleaned.strip("_") or "captcha"
        return cleaned[:limit]

    def _save_tip4_capture_before_send(self, frame, bbox, offset_x, offset_y, expr, answer, tag="tip4"):
        """Cevap yazildiktan sonra, Send oncesi captcha crop'unu kaydeder."""
        try:
            dx1, dy1, dx2, dy2 = [int(v) for v in bbox]
        except Exception:
            self._log("warn", "CAPTCHA GORUNTUSU kaydedilemedi: bbox gecersiz")
            return None

        out_dir = os.path.join(_RUNTIME_DIR, "captcha_kontrol")
        os.makedirs(out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        ms = int((time.time() % 1.0) * 1000)
        expr_part = self._safe_file_part(expr)
        ans_part = self._safe_file_part(answer, 8)
        fname = f"{tag}_C{self._client_id}_{ts}_{ms:03d}_{expr_part}_cevap_{ans_part}.png"
        path = os.path.join(out_dir, fname)

        live_capture = False
        crop = None
        width = max(1, dx2 - dx1)
        height = max(1, dy2 - dy1)
        try:
            import mss
            left = int(dx1 + offset_x)
            top = int(dy1 + offset_y)
            with mss.mss() as sct:
                shot = np.array(sct.grab({"left": left, "top": top, "width": width, "height": height}), dtype=np.uint8)
            crop = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            live_capture = True
        except Exception as exc:
            try:
                if frame is not None and frame.size:
                    fh, fw = frame.shape[:2]
                    x1 = max(0, min(dx1, fw - 1))
                    y1 = max(0, min(dy1, fh - 1))
                    x2 = max(x1 + 1, min(dx2, fw))
                    y2 = max(y1 + 1, min(dy2, fh))
                    crop = frame[y1:y2, x1:x2].copy()
                    self._log("warn", f"CAPTCHA GORUNTUSU canlı yakalama basarisiz, frame crop kaydedilecek: {exc}")
            except Exception:
                crop = None

        if crop is None or crop.size == 0:
            self._log("warn", "CAPTCHA GORUNTUSU kaydedilemedi: crop bos")
            return None
        ok = cv2.imwrite(path, crop)
        if not ok:
            self._log("warn", f"CAPTCHA GORUNTUSU kaydedilemedi: {path}")
            return None
        source = "canli" if live_capture else "frame"
        self._log("warn", f"CAPTCHA GORUNTUSU KAYDEDILDI ({source}): {path}")
        return path

    def set_enabled_tips(self, tips=None):
        tips = tips or {}
        with self._lock:
            for key in ("tip1", "tip2", "tip3", "tip4"):
                if key in tips:
                    self._enabled_tips[key] = bool(tips[key])

    def _tip_enabled(self, name):
        with self._lock:
            return bool(self._enabled_tips.get(name, False))

    def _init_ocr(self):
        try:
            import easyocr

            last_error = None
            for use_gpu in (True, False):
                try:
                    self._reader = easyocr.Reader(["tr", "en"], gpu=use_gpu, verbose=False)
                    with self._lock:
                        self._hazir = True
                    mode = "gpu" if use_gpu else "cpu"
                    self._set_status("ready", mode)
                    self._log("info", f"EasyOCR hazir ({mode.upper()})")
                    return
                except Exception as exc:
                    last_error = exc
            self._set_status("ocr_hata", str(last_error))
            self._log("error", f"OCR hatasi: {last_error}")
        except Exception as exc:
            self._set_status("ocr_hata", str(exc))
            self._log("error", f"OCR hatasi: {exc}")

    @property
    def hazir(self):
        return self._hazir

    def dialog_durumu(self, frame):
        dialog = self._dialog_bul(frame)
        if dialog is None:
            return None
        return {"bbox": dialog, "mode": "legacy"}

    def kontrol_et(self, frame, offset_x=0, offset_y=0, hwnd=None):
        if not self._hazir:
            self._set_status("not_ready", self.last_detail)
            return False
        # GÜVENLİK: Template yüklü değilse captcha tespiti TAMAMEN devre dışı —
        # aksi halde tüm koyu bölgeler captcha olarak algılanabilir.
        if self._header_tpl is None:
            self._set_status("template_yok", "captcha_template.png yuklu degil")
            return False

        now = time.time()
        if now - self._son_cozum < self._cooldown:
            self._set_status("cooldown", f"cozum_sonrasi ({self._cooldown - (now - self._son_cozum):.1f}s kaldi)")
            return False
        if now - self._son_basarisiz < self._basarisiz_cd:
            self._set_status("cooldown", f"basarisiz_sonrasi ({self._basarisiz_cd - (now - self._son_basarisiz):.1f}s kaldi)")
            return False

        dialog = self._dialog_bul(frame)
        if dialog is None:
            if time.time() - self._son_tiklama < 1.0:
                self._set_status("dialog_yok", "tiklama_sonrasi_animasyon")
                return False
            # Tip3: Bot kontrol dialog (genis, kare olmayan)
            if self._tip_enabled("tip3") and self._coz_tip3_detect(frame, offset_x, offset_y, hwnd):
                self._son_cozum = time.time()
                return True
            # Tip4: Matematik captcha (cok kucuk dialog, _dialog_bul atlayabilir)
            if self._tip_enabled("tip4") and self._coz_tip4_detect(frame, offset_x, offset_y, hwnd):
                self._son_cozum = time.time()
                return True
            self._set_status("dialog_yok")
            return False

        if time.time() - self._last_dialog_log > 1.0:
            self._log("info", f"Dialog tespit edildi: {dialog}")
            self._last_dialog_log = time.time()
        solved = self._coz(frame, dialog, offset_x, offset_y, hwnd)
        if solved:
            self._son_cozum = time.time()
            return True

        self._son_basarisiz = time.time()
        return False

    def _dialog_bul(self, frame):
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        # Full template varsa once dogrudan merkez bolgesinde ara. Kontur/renk
        # tabanli yol, oyun arka plani captcha kenarlarina benzediginde kacabiliyor.
        tpl_dialog = self._dialog_bul_template_scan(frame)
        if tpl_dialog is not None:
            self._set_status("dialog_var", f"{tpl_dialog[0]},{tpl_dialog[1]},{tpl_dialog[2]},{tpl_dialog[3]}")
            self._log("info", f"Captcha tespit edildi (template-scan) bbox={tpl_dialog}")
            return tpl_dialog

        r = 80
        y1 = max(0, cy - r)
        y2 = min(h, cy + r)
        x1 = max(0, cx - r)
        x2 = min(w, cx + r)
        center = frame[y1:y2, x1:x2]
        if center.size == 0:
            self._set_status("dialog_yok", "merkez_bos")
            return None

        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        mean_gray = float(np.mean(gray))
        # Origins'te dialog koyu ama arka plan (cöl) açık olabiliyor;
        # eşiği 80'e çektik — dialog içeriği yeterince koyu olduğunda geçer.
        if mean_gray > 80:
            self._set_status("dialog_yok", f"bright:{mean_gray:.1f}")
            return None

        # Oyun icinde captcha merkezin biraz altinda aciliyor.
        sx1 = max(0, cx - 200)
        sy1 = max(0, cy - 50)
        sx2 = min(w, cx + 200)
        sy2 = min(h, cy + 350)
        search = frame[sy1:sy2, sx1:sx2]
        if search.size == 0:
            self._set_status("dialog_yok", "arama_bos")
            return None

        gray_search = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray_search, (5, 5), 0)
        edges = cv2.Canny(blur, 45, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        area_total = search.shape[0] * search.shape[1]
        best = None
        best_score = -1.0
        scx = search.shape[1] / 2.0
        scy = search.shape[0] / 2.0

        best_rect = None
        for cnt in contours:
            x, y, ww, hh = cv2.boundingRect(cnt)
            area = ww * hh
            if area < area_total * 0.10 or area > area_total * 0.90:
                continue
            aspect = ww / max(hh, 1)
            if not (0.72 <= aspect <= 2.5):
                continue

            roi = gray_search[y:y + hh, x:x + ww]
            if roi.size == 0:
                continue

            dark_ratio = float(np.mean(roi < 95))
            if dark_ratio < 0.30:
                continue

            edge_roi = edges[y:y + hh, x:x + ww]
            edge_ratio = float(np.count_nonzero(edge_roi)) / float(area)
            if edge_ratio < 0.010 or edge_ratio > 0.140:
                continue

            center_dx = abs((x + ww / 2.0) - scx)
            center_dy = abs((y + hh / 2.0) - scy)
            center_penalty = (center_dx / max(scx, 1.0)) + (center_dy / max(scy, 1.0))
            score = (dark_ratio * 2.2) + (edge_ratio * 8.0) - center_penalty
            if score > best_score:
                best_score = score
                best_rect = (x, y, ww, hh)

        if best_rect is None:
            self._set_status("dialog_yok", "kontur_yok")
            # Merkez cok koyuysa captcha benzeri bir sey olabilir → kullaniciya bildir
            now = time.time()
            if mean_gray < 50 and (now - self._last_dialog_log > 2.5):
                self._log(
                    "warn",
                    f"Merkez koyu (gri={mean_gray:.0f}) ama kontur bulunamadi — "
                    f"captcha bbox tespiti basarisiz"
                )
                self._last_dialog_log = now
            return None

        x, y, ww, hh = best_rect
        cx_box = sx1 + x + (ww / 2.0)
        cy_box = sy1 + y + (hh / 2.0)
        # Ic koyu parcayi bulduktan sonra kutuyu captcha penceresinin tam boyutuna genislet.
        half_w = max(114, int(ww * 0.95))
        top_h = max(98, int(hh * 0.68))
        bottom_h = max(118, int(hh * 0.72))
        bx1 = max(0, int(cx_box - half_w))
        bx2 = min(w, int(cx_box + half_w))
        by1 = max(0, int(cy_box - top_h))
        by2 = min(h, int(cy_box + bottom_h))
        best = (bx1, by1, bx2, by2)

        # ── Captcha doğrulama kapısı ────────────────────────────────────
        # Tespit edilen bölge gerçekten Captcha diyalogu mu?
        dialog_roi_check = frame[by1:by2, bx1:bx2]
        if not self._is_captcha_dialog(dialog_roi_check):
            self._set_status("dialog_yok", "captcha_dogrulama_basarisiz")
            return None

        self._set_status("dialog_var", f"{best[0]},{best[1]},{best[2]},{best[3]}")
        self._log("info", f"Captcha tespit edildi — cozuluyor bbox={best}")
        return best

    def _dialog_bul_template_scan(self, frame):
        """Full template ile merkez bolgesinde dogrudan captcha bbox arar."""
        if self._tpl_mode != "full" or self._header_tpl is None:
            return None
        if frame is None or frame.size == 0:
            return None

        h, w = frame.shape[:2]
        th, tw = self._header_tpl.shape[:2]
        cx, cy = w // 2, h // 2

        rx = min(w // 2, max(420, int(tw * 2.2)))
        ry_top = min(cy, max(300, int(th * 2.0)))
        ry_bottom = min(h - cy, max(420, int(th * 3.0)))
        sx1 = max(0, cx - rx)
        sx2 = min(w, cx + rx)
        sy1 = max(0, cy - ry_top)
        sy2 = min(h, cy + ry_bottom)
        search = frame[sy1:sy2, sx1:sx2]
        if search.size == 0:
            return None

        gray_region = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        best_score = -1.0
        best = None
        scale_list = (1.0, 0.90, 1.10, 0.80, 1.20, 0.70, 1.30)
        for scale in scale_list:
            nw = max(10, int(tw * scale))
            nh = max(10, int(th * scale))
            if nw > gray_region.shape[1] or nh > gray_region.shape[0]:
                continue
            if scale == 1.0:
                tpl_s = self._header_tpl
                mask_s = self._tpl_mask
            else:
                interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                tpl_s = cv2.resize(self._header_tpl, (nw, nh), interpolation=interp)
                mask_s = cv2.resize(self._tpl_mask, (nw, nh), interpolation=cv2.INTER_NEAREST) if self._tpl_mask is not None else None

            try:
                if mask_s is not None:
                    res = cv2.matchTemplate(gray_region, tpl_s, cv2.TM_CCOEFF_NORMED, mask=mask_s)
                else:
                    res = cv2.matchTemplate(gray_region, tpl_s, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            if not np.all(np.isfinite(res)):
                res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)
            score = float(maxv)
            if score > best_score:
                ax1 = sx1 + int(maxloc[0])
                ay1 = sy1 + int(maxloc[1])
                best_score = score
                best = (ax1, ay1, ax1 + nw, ay1 + nh, scale)

        if best is None:
            return None

        # Direct scan daha genis ekranda calistigi icin esigi kontur sonrasi
        # dogrulamadan biraz yuksek tutuyoruz.
        if best_score < 0.70:
            now = time.time()
            if now - self._last_dialog_log > 2.0:
                self._log("debug", f"Template-scan eslesmedi skor={best_score:.2f}")
                self._last_dialog_log = now
            return None

        bx1, by1, bx2, by2, scale = best
        self._last_match_loc = (0, 0)
        self._last_match_scale = float(scale)
        self._log("info", f"Template-scan match scale={scale:.2f} score={best_score:.2f}")
        return (bx1, by1, bx2, by2)

    def _is_captcha_dialog(self, dialog_roi):
        """Tespit edilen bölgenin gerçek Captcha diyalogu olup olmadığını doğrular.

        İki kademe:
        1. Template dosyası varsa → cv2.matchTemplate (kesin eşleşme)
        2. Yoksa             → başlık renk profili + gövde karanlık kontrolü
        """
        if dialog_roi is None or dialog_roi.size == 0:
            return False
        dh, dw = dialog_roi.shape[:2]

        # ── Kademe 1: Template eşleşmesi ─────────────────────────────────
        if self._header_tpl is not None:
            th, tw = self._header_tpl.shape[:2]
            full_mode = (self._tpl_mode == "full")
            # Son match bilgilerini sıfırla
            self._last_match_loc   = None
            self._last_match_scale = 1.0

            if full_mode:
                # Tüm dialog_roi üzerinde maskeli match
                gray_region = cv2.cvtColor(dialog_roi, cv2.COLOR_BGR2GRAY)
                score_threshold = 0.66
            else:
                # Header modu: sadece üst bant
                strip_h = max(th + 6, int(dh * 0.35))
                header_strip = dialog_roi[0:strip_h, :]
                if header_strip.shape[0] < th or header_strip.shape[1] < tw:
                    self._log("debug", "Template eslesmedi — bolge kucuk")
                    return False
                gray_region = cv2.cvtColor(header_strip, cv2.COLOR_BGR2GRAY)
                score_threshold = 0.52

            # Tüm ölçeklerdeki en iyi skoru izle — diagnoz amaçlı
            best_score_all = -1.0
            best_scale_all = 1.0

            # Daha geniş ölçek aralığı: Origins istemcisi farklı
            # çözünürlüklerde captcha'yı %70-%130 arası boyutlarda çıkarabilir.
            scale_list = (1.0, 0.90, 1.10, 0.80, 1.20, 0.70, 1.30)
            for scale in scale_list:
                if scale != 1.0:
                    nw = max(10, int(tw * scale))
                    nh = max(10, int(th * scale))
                    if nw > gray_region.shape[1] or nh > gray_region.shape[0]:
                        continue
                    tpl_s = cv2.resize(self._header_tpl, (nw, nh))
                    mask_s = cv2.resize(self._tpl_mask, (nw, nh)) if (full_mode and self._tpl_mask is not None) else None
                else:
                    tpl_s = self._header_tpl
                    mask_s = self._tpl_mask if full_mode else None

                if gray_region.shape[0] < tpl_s.shape[0] or gray_region.shape[1] < tpl_s.shape[1]:
                    continue

                try:
                    if mask_s is not None:
                        res = cv2.matchTemplate(gray_region, tpl_s, cv2.TM_CCOEFF_NORMED, mask=mask_s)
                    else:
                        res = cv2.matchTemplate(gray_region, tpl_s, cv2.TM_CCOEFF_NORMED)
                except cv2.error:
                    continue
                # Mask kullanıldığında NaN çıkabilir — temizle
                if not np.all(np.isfinite(res)):
                    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)
                score = float(maxv)
                if score > best_score_all:
                    best_score_all = score
                    best_scale_all = scale
                if score >= score_threshold:
                    self._last_match_loc   = (int(maxloc[0]), int(maxloc[1]))
                    self._last_match_scale = float(scale)
                    if full_mode:
                        self._log(
                            "info",
                            f"Template FULL match loc=({maxloc[0]},{maxloc[1]}) "
                            f"scale={scale:.2f} score={score:.2f}"
                        )
                    else:
                        self._log("info", f"Captcha dogrulandi (template, skor={score:.2f}, scale={scale:.2f})")
                    return True

            # Throttle: 2 saniyede bir en iyi skoru bildir (spam yapmasın)
            now = time.time()
            if now - self._last_dialog_log > 2.0:
                self._log(
                    "warn",
                    f"Template eslesmedi — en iyi skor={best_score_all:.2f} "
                    f"(scale={best_scale_all:.2f}, esik={score_threshold})"
                )
                self._last_dialog_log = now
            return False

        # ── Kademe 2: Renk profili kontrolü (template dosyası yoksa) ─────
        # Başlık bandı: üst %20 — Captcha başlığı koyu kırmızı/kahverengi
        band_h = max(8, int(dh * 0.20))
        header_band = dialog_roi[0:band_h, int(dw * 0.1):int(dw * 0.9)]
        body_band   = dialog_roi[band_h:int(dh * 0.85), int(dw * 0.1):int(dw * 0.9)]

        if header_band.size == 0 or body_band.size == 0:
            return False

        # Gövde: çok koyu olmalı (siyah dialog arka planı)
        body_gray = cv2.cvtColor(body_band, cv2.COLOR_BGR2GRAY)
        body_mean = float(np.mean(body_gray))
        if body_mean > 90:
            self._log("debug", f"Govde cok parlak ({body_mean:.1f}) — yanlis tespit")
            return False

        # Başlık: gövdeden belirgin şekilde farklı bir renk içermeli
        # (kırmızı/kahverengi kanal baskınlığı veya gövdeden daha parlak)
        header_hsv = cv2.cvtColor(header_band, cv2.COLOR_BGR2HSV)
        # Kırmızı-kahverengi aralığı: H=0-20 veya 155-180, S>40, V=30-160
        mask_r1 = cv2.inRange(header_hsv, (0,  40,  30), (20,  255, 160))
        mask_r2 = cv2.inRange(header_hsv, (155, 40, 30), (180, 255, 160))
        colored = cv2.bitwise_or(mask_r1, mask_r2)
        color_ratio = float(np.count_nonzero(colored)) / float(header_band.shape[0] * header_band.shape[1])

        # Başlık gövdeden en az 15 birim daha parlak da olabilir
        header_gray = cv2.cvtColor(header_band, cv2.COLOR_BGR2GRAY)
        header_mean = float(np.mean(header_gray))
        brightness_diff = header_mean - body_mean

        ok = color_ratio >= 0.15 or brightness_diff >= 15
        if ok:
            self._log("info", f"Captcha dogrulandi (renk, ratio={color_ratio:.2f} Δbright={brightness_diff:.1f})")
        else:
            self._log("debug", f"Renk profili uyumsuz (ratio={color_ratio:.2f} Δbright={brightness_diff:.1f})")
        return ok

    def reload_template(self):
        """captcha_template.png'yi disk'ten yeniden yükler (bot çalışırken güncellemek için)."""
        self._load_template()
        return self._header_tpl is not None

    def _coz_tip3_detect(self, frame, offset_x=0, offset_y=0, hwnd=None):
        import random, re
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        # ── 1. Geniş diyaloğu bul ───────────────────────────────────────
        sx1 = max(0, cx - 450)
        sy1 = max(0, cy - 150)
        sx2 = min(w, cx + 450)
        sy2 = min(h, cy + 300)
        search = frame[sy1:sy2, sx1:sx2]
        if search.size == 0:
            return False

        gray_s = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray_s, (5, 5), 0), 35, 100)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_rect = None
        best_score = -1.0
        scx_s, scy_s = search.shape[1] / 2.0, search.shape[0] / 2.0

        for cnt in contours:
            x, y, ww, hh = cv2.boundingRect(cnt)
            if ww < 200 or hh < 60:
                continue
            aspect = ww / max(hh, 1)
            if not (1.4 <= aspect <= 6.5):
                continue
            roi = gray_s[y:y + hh, x:x + ww]
            if roi.size == 0:
                continue
            dark_ratio = float(np.mean(roi < 110))
            if dark_ratio < 0.18:
                continue
            cp = (abs((x + ww / 2.0) - scx_s) / max(scx_s, 1) +
                  abs((y + hh / 2.0) - scy_s) / max(scy_s, 1))
            score = dark_ratio * 2.0 + ww / 100.0 - cp
            if score > best_score:
                best_score = score
                best_rect = (sx1 + x, sy1 + y, ww, hh)

        if best_rect is None:
            return False

        dlg_x, dlg_y, dlg_w, dlg_h = best_rect
        dialog_roi = frame[dlg_y:dlg_y + dlg_h, dlg_x:dlg_x + dlg_w]

        # ── 2. Diyaloğu büyüt + tek OCR geçişi (konum bilgisi dahil) ───
        scale = 2.5
        try:
            with self._lock:
                if not self._reader:
                    return False
                large = cv2.resize(dialog_roi, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_CUBIC)
                ocr_results = self._reader.readtext(large, detail=1, paragraph=False)
        except Exception as e:
            self._log("warn", f"Tip3 OCR hata: {e}")
            return False

        if not ocr_results:
            return False

        all_text = " ".join(r[1] for r in ocr_results).lower()
        self._log("info", f"Tip3 tam OCR: {all_text[:160]}")

        # Doğrulama: bot kontrol / tıkla içermeli
        dogrula_keys = ["sand", "bot", "tikl", "tıkl", "kontrol", "kask", "kalkan",
                        "kilic", "kılıç", "zirah", "zırh", "tıklay", "tiklay"]
        if not any(k in all_text for k in dogrula_keys):
            return False

        # ── 3. Item satırı bölgesi ──────────────────────────────────────
        item_y1 = dlg_y + int(dlg_h * 0.40)
        item_y2 = dlg_y + int(dlg_h * 0.93)
        item_x1 = dlg_x + int(dlg_w * 0.03)
        item_x2 = dlg_x + int(dlg_w * 0.97)
        item_w  = item_x2 - item_x1
        item_h  = item_y2 - item_y1
        if item_w < 100 or item_h < 15:
            return False

        slot_px = item_w / 8.0   # her slotun piksel genişliği

        # ── 4. OCR kutularını üst (talimat) / alt (etiket) olarak ayır ──
        # Büyütülmüş koordinatları orijinale çevir: frame_y = dlg_y + box_y/scale
        talimat_parcalar = []   # diyaloğun üst %45'inde bulunan metinler
        slot_etiketler   = {i: [] for i in range(8)}  # slot → [metin, ...]

        for box, text, prob in ocr_results:
            if prob < 0.3:
                continue
            # Kutunun merkezi (orijinal frame koordinatları)
            bx_mid = dlg_x + (box[0][0] + box[2][0]) / 2.0 / scale
            by_mid = dlg_y + (box[0][1] + box[2][1]) / 2.0 / scale

            # Diyaloğun üst %45 → talimat
            if by_mid < dlg_y + dlg_h * 0.45:
                talimat_parcalar.append(text.lower())
            # Alt %45-93 arası → item satırı
            elif item_y1 <= by_mid <= item_y2:
                # Hangi slota ait?
                rel_x = bx_mid - item_x1
                slot_idx = int(rel_x / slot_px)
                slot_idx = max(0, min(7, slot_idx))
                slot_etiketler[slot_idx].append(text.lower())

        talimat_text = " ".join(talimat_parcalar)
        self._log("info", f"Tip3 talimat: '{talimat_text}'")
        for i, lbls in slot_etiketler.items():
            if lbls:
                self._log("info", f"Tip3 slot{i}: {lbls}")

        # ── 5. Hedef kelimeyi çıkar ─────────────────────────────────────
        target = self._tip3_hedef_cikar(talimat_text or all_text)
        self._log("info", f"Tip3 hedef: '{target}'")

        # ── 6. Slotlardaki etiketlerle eşleştir ────────────────────────
        best_slot  = None
        best_match = 0.0

        if target:
            for slot_idx, lbls in slot_etiketler.items():
                for lbl in lbls:
                    score = self._tip3_eslesme(target, lbl)
                    if score > best_match:
                        best_match = score
                        best_slot  = slot_idx
            if best_slot is not None:
                self._log("info", f"Tip3 eslesti: slot{best_slot} skor={best_match:.2f}")
            if best_match < 0.35:
                self._log("warn", f"Tip3 eslesme zayif ({best_match:.2f}), rastgele")
                best_slot = None

        # ── 7. Eşleşme yoksa rastgele ──────────────────────────────────
        if best_slot is None:
            best_slot = random.randint(0, 7)
            self._log("warn", f"Tip3 rastgele slot: {best_slot}")

        # ── 8. Tıkla ───────────────────────────────────────────────────
        click_x = int(item_x1 + best_slot * slot_px + slot_px / 2.0) + offset_x
        click_y = int((item_y1 + item_y2) / 2.0) + offset_y

        print(f"[CAPTCHA-C{self._client_id}] Tip3 tikla: slot={best_slot} "
              f"hedef='{target}' skor={best_match:.2f} ({click_x},{click_y})")
        self._tikla(click_x, click_y, hwnd)
        self._set_status("tiklandi", f"tip3:slot{best_slot}:{target or 'rastgele'}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — TİP 3 hedef='{target}' slot={best_slot}")
        return True

    # ── Tip3 yardımcı: hedef kelimeyi talimat metninden çıkar ──────────
    def _tip3_hedef_cikar(self, text):
        import re
        t = text.lower().strip()
        # "Kaskı tıklayın", "Kılıcı tıklayın", "Sandığa tıklayın" vb.
        # → fiilden önce gelen isim
        m = re.search(r'([a-zçğışöü]{2,15}?)(?:[ıiuü](?:n[ıiuü])?|[ay]a|e)\s+t[ıi]kla', t)
        if m:
            word = m.group(1).strip()
            stop = {'bir', 'bu', 'su', 've', 'ile', 'bot', 'kon', 'res',
                    'foto', 'lut', 'lüt', 'ras', 'gel', 'ara'}
            if word not in stop and len(word) >= 2:
                return word
        # Geri dönüş: tıkla'dan önce gelen son anlamlı kelime
        m2 = re.search(r'(\w{2,14})\s+t[ıi]kla', t)
        if m2:
            word = m2.group(1).strip()
            if len(word) >= 2:
                return word
        return None

    # ── Tip3 yardımcı: Türkçe son ek duyarsız bulanık eşleşme ─────────
    def _tip3_eslesme(self, target, seen):
        import re
        def normalize(s):
            s = s.lower().strip()
            s = re.sub(r'[^a-zçğışöü]', '', s)
            # Türkçe yalın hale getir (belirtme eki vb.)
            for suf in ('yını', 'yine', 'yını', 'nını', 'nine', 'nına', 'nına',
                        'yı', 'yi', 'yu', 'yü', 'nı', 'ni', 'nu', 'nü',
                        'ya', 'ye', 'na', 'ne', 'ğa', 'ğe',
                        'ı', 'i', 'u', 'ü', 'a', 'e'):
                if s.endswith(suf) and len(s) > len(suf) + 1:
                    s = s[:-len(suf)]
                    break
            return s

        t = normalize(target)
        s = normalize(seen)
        if not t or not s:
            return 0.0
        if t == s:
            return 1.0
        if len(t) >= 3 and (t in s or s in t):
            return 0.85
        # Karakter örtüşme oranı
        if len(t) >= 3 and len(s) >= 3:
            common = sum(a == b for a, b in zip(t, s))
            ratio = common / max(len(t), len(s))
            if ratio >= 0.55:
                return ratio
        return 0.0

    def _coz(self, frame, bbox, offset_x, offset_y, hwnd=None):
        dx1, dy1, dx2, dy2 = bbox
        dialog = frame[dy1:dy2, dx1:dx2]
        if dialog.size == 0:
            self._set_status("dialog_bos")
            return False

        # ── FAST-PATH: FULL template match başarılı → Origins math captcha ──
        self._log(
            "warn",
            f"_coz girdi: mode={self._tpl_mode} match_loc={self._last_match_loc} "
            f"tip4={self._tip_enabled('tip4')}"
        )
        if (self._tpl_mode == "full"
                and self._last_match_loc is not None
                and self._tip_enabled("tip4")):
            self._log("warn", "FAST-PATH: Origins math cozumune gidiliyor")
            return self._coz_origins_math(frame, bbox, "", offset_x, offset_y, hwnd)

        with self._lock:
            if not self._reader:
                self._set_status("reader_yok")
                return False
            large = cv2.resize(dialog, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            results = self._reader.readtext(large, detail=1, paragraph=False)

        if not results:
            self._set_status("ocr_yok")
            return False

        all_text = " ".join([item[1] for item in results]).lower()
        self._log("info", f"OCR: {all_text}")

        # Origins matematik captcha — "Insert the result of the sum below"
        if self._tip_enabled("tip4") and any(k in all_text for k in ["insert", "sum", "result of", "below", "captcha"]):
            if re.search(r'\d\s*\+\s*\d', all_text):
                self._set_status("tip4_origins", all_text[:120])
                return self._coz_origins_math(frame, bbox, all_text, offset_x, offset_y, hwnd)

        if self._tip_enabled("tip2") and any(key in all_text for key in ["butunlug", "bozan", "farkl", "kareleri", "fotograf", "foto"]):
            self._set_status("tip2", all_text[:120])
            return self._coz_tip2(frame, bbox, results, offset_x, offset_y, hwnd)

        if self._tip_enabled("tip1") and any(key in all_text for key in ["ara", "resm", "sec", "seç"]):
            self._set_status("tip1", all_text[:120])
            return self._coz_tip1(frame, bbox, results, all_text, offset_x, offset_y, hwnd)

        # Tip4: Matematik captcha — "2+3", "5x2", "10-3" vb.
        if re.search(r'\d\s*[+\-xX×÷:]\s*\d', all_text) or \
           re.search(r'\d+\s*=\s*\?', all_text):
            self._set_status("tip4", all_text[:120])
            return self._coz_tip4(frame, bbox, all_text, offset_x, offset_y, hwnd) if self._tip_enabled("tip4") else False

        self._set_status("tip_yok", all_text[:120])
        return False

    def _coz_tip1(self, frame, bbox, results, all_text, offset_x, offset_y, hwnd=None):
        dx1, dy1, dx2, dy2 = bbox
        target = self._extract_target(all_text)

        if not target:
            self._set_status("hedef_yok", all_text[:120])
            return False

        best_box = None
        best_score = 0.0
        for box, text, _prob in results:
            normalized = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ]", "", text.strip()).lower()
            if len(normalized) < 1 or len(normalized) > 6:
                continue
            score = self._eslesme(target, normalized)
            if score > best_score:
                best_score = score
                best_box = box

        if best_box is None or best_score < 0.5:
            fallback = self._coz_tip1_grid(frame[dy1:dy2, dx1:dx2], dx1, dy1, target, offset_x, offset_y, hwnd)
            if fallback:
                self._set_status("tiklandi", f"tip1-grid:{target}")
                self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — TİP 1 (grid) hedef='{target}'")
                return True
            self._set_status("eslesme_yok", f"{target}:{best_score:.2f}")
            return False

        top_left, bottom_right = best_box[0], best_box[2]
        hx = int((top_left[0] + bottom_right[0]) / 2.0 / 2.0)
        hy = int((top_left[1] + bottom_right[1]) / 2.0 / 2.0)
        abs_x = dx1 + hx + offset_x
        abs_y = dy1 + hy + offset_y
        self._tikla(abs_x, abs_y, hwnd)
        self._set_status("tiklandi", f"tip1:{target}:{best_score:.2f}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — TİP 1 hedef='{target}' skor={best_score:.2f}")
        return True

    def _coz_tip1_grid(self, dialog, dx1, dy1, target, offset_x, offset_y, hwnd=None):
        if dialog.size == 0:
            return False

        dh, dw = dialog.shape[:2]
        gx1 = int(dw * 0.10)
        gx2 = int(dw * 0.90)
        gy1 = int(dh * 0.12)
        gy2 = int(dh * 0.58)
        grid = dialog[gy1:gy2, gx1:gx2]
        gh, gw = grid.shape[:2]
        if gh < 40 or gw < 60:
            return False

        cell_w = gw // 3
        cell_h = gh // 2
        best = None
        best_score = 0.0
        best_text = ""

        for row in range(2):
            for col in range(3):
                cx1 = col * cell_w + 4
                cx2 = (col + 1) * cell_w - 4
                cy1 = row * cell_h + 4
                cy2 = (row + 1) * cell_h - 4
                cell = grid[cy1:cy2, cx1:cx2]
                if cell.size == 0:
                    continue

                for seen in self._ocr_cell_candidates(cell):
                    score = self._eslesme(target, seen)
                    if score > best_score:
                        best_score = score
                        best = (
                            dx1 + gx1 + cx1 + (cx2 - cx1) // 2 + offset_x,
                            dy1 + gy1 + cy1 + (cy2 - cy1) // 2 + offset_y,
                        )
                        best_text = seen

        if best is None or best_score < 0.45:
            return False

        self._log("info", f"Tip1 grid tikla: ({best[0]}, {best[1]}) skor={best_score:.2f} metin={best_text}")
        self._tikla(best[0], best[1], hwnd)
        time.sleep(0.5)
        return True

    def _ocr_cell_candidates(self, cell):
        gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        variants = [big, cv2.GaussianBlur(big, (3, 3), 0)]
        _, thr1 = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, thr2 = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.extend([thr1, thr2])

        texts = set()
        with self._lock:
            if not self._reader:
                return []
            for img in variants:
                try:
                    out = self._reader.readtext(
                        img,
                        detail=0,
                        paragraph=False,
                        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
                    )
                except TypeError:
                    out = self._reader.readtext(img, detail=0, paragraph=False)
                except Exception:
                    continue
                for item in out or []:
                    normalized = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ]", "", str(item).strip()).lower()
                    if 1 <= len(normalized) <= 6:
                        texts.add(normalized)
        return list(texts)

    def _coz_tip2(self, frame, bbox, results, offset_x, offset_y, hwnd=None):
        dx1, dy1, dx2, dy2 = bbox
        dialog = frame[dy1:dy2, dx1:dx2]
        dh, dw = dialog.shape[:2]

        approve_pos = None
        text_bottom_y = 0
        remain_top_y = dh

        for box, text, _prob in results:
            text_l = text.strip().lower()
            top_left, bottom_right = box[0], box[2]
            oy_mid = int((top_left[1] + bottom_right[1]) / 2.0 / 2.0)
            ox_mid = int((top_left[0] + bottom_right[0]) / 2.0 / 2.0)

            if "onayla" in text_l or "onay" in text_l:
                approve_pos = (ox_mid, oy_mid)

            if any(key in text_l for key in ["seçin", "secin", "bozan", "farkl"]):
                bottom = int(bottom_right[1] / 2.0)
                if bottom > text_bottom_y:
                    text_bottom_y = bottom

            if "kalan" in text_l or "deneme" in text_l or "hakk" in text_l:
                top = int(top_left[1] / 2.0)
                if top < remain_top_y:
                    remain_top_y = top

        grid_y1 = text_bottom_y + 5 if text_bottom_y > 0 else int(dh * 0.14)
        grid_y2 = remain_top_y - 5 if remain_top_y < dh else int(dh * 0.74)
        grid_x1 = int(dw * 0.10)
        grid_x2 = int(dw * 0.90)

        grid = dialog[grid_y1:grid_y2, grid_x1:grid_x2]
        gh, gw = grid.shape[:2]
        if gh < 50 or gw < 50:
            self._set_status("grid_yok", f"{gw}x{gh}")
            return False

        cell_w = gw // 3
        cell_h = gh // 3
        cells = []
        for row in range(3):
            for col in range(3):
                cy1 = row * cell_h + 3
                cy2 = (row + 1) * cell_h - 3
                cx1 = col * cell_w + 3
                cx2 = (col + 1) * cell_w - 3
                cell = grid[cy1:cy2, cx1:cx2]
                if cell.shape[0] < 10 or cell.shape[1] < 10:
                    continue

                hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [30, 30], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

                cells.append(
                    {
                        "row": row,
                        "col": col,
                        "hist": hist,
                        "cx": grid_x1 + cx1 + (cx2 - cx1) // 2,
                        "cy": grid_y1 + cy1 + (cy2 - cy1) // 2,
                        "bright": float(np.mean(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY))),
                    }
                )

        n = len(cells)
        if n < 4:
            self._set_status("grid_az", str(n))
            return False

        similarity = [0.0] * n
        for i in range(n):
            for j in range(n):
                if i != j:
                    similarity[i] += cv2.compareHist(cells[i]["hist"], cells[j]["hist"], cv2.HISTCMP_CORREL)
            similarity[i] /= (n - 1)

        avg = float(np.mean(similarity))
        threshold = avg - 0.15
        different = [cells[i] for i in range(n) if similarity[i] < threshold]

        if not different:
            order = sorted(range(n), key=lambda idx: similarity[idx])
            if similarity[order[0]] < similarity[order[-1]] * 0.7:
                for idx in order[:3]:
                    if similarity[idx] < avg:
                        different.append(cells[idx])

        if not different:
            self._set_status("farkli_yok")
            return False

        for cell in different:
            ax = dx1 + cell["cx"] + offset_x
            ay = dy1 + cell["cy"] + offset_y
            self._tikla(ax, ay, hwnd)
            time.sleep(0.3)

        time.sleep(0.5)
        if approve_pos:
            ox = dx1 + approve_pos[0] + offset_x
            oy = dy1 + approve_pos[1] + offset_y
        else:
            ox = dx1 + dw // 2 + offset_x
            oy = dy1 + int(dh * 0.86) + offset_y
        self._tikla(ox, oy, hwnd)
        self._set_status("tiklandi", f"tip2:{len(different)}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — TİP 2 ({len(different)} farklı kare)")
        return True

    def _eslesme(self, target, seen):
        t = target.lower()
        s = seen.lower()
        if t == s:
            return 1.0
        if len(t) >= 2 and len(s) == 1:
            return 0.0
        if t in s or s in t:
            return 0.8
        if len(t) == len(s):
            diff = sum(c1 != c2 for c1, c2 in zip(t, s))
            return max(0.0, 1.0 - (diff / len(t)))
        return 0.0

    def _extract_target(self, all_text):
        text = all_text.lower()
        patterns = [
            r"ara[sş][ıi]ndan\s+([a-z0-9çğıöşü]{1,6})\s*resm",
            r"([a-z0-9çğıöşü]{1,6})\s*resmin[ıi]\s*se[çc]",
            r"ara[sş][ıi]ndan\s+([a-z0-9çğıöşü]{1,6})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = re.sub(r"[^a-z0-9çğıöşü]", "", match.group(1).strip(), flags=re.IGNORECASE)
                if 1 <= len(candidate) <= 4:
                    return candidate

        idx = text.find("resimler aras")
        if idx != -1:
            left = text[:idx]
            tokens = re.findall(r"[a-z0-9çğıöşü]{2,4}", left, re.IGNORECASE)
            for candidate in reversed(tokens[-4:]):
                if candidate not in {"sn", "btn", "bot"}:
                    return candidate
        return None

    # ════════════════════════════════════════════════════════════════
    #  TİP4 — Matematik Captcha  ("2+3=?", "5x2=?", "10-3=?" vb.)
    # ════════════════════════════════════════════════════════════════

    def _coz_tip4(self, frame, bbox, all_text, offset_x, offset_y, hwnd=None, input_bbox=None, parsed_expr=None):
        return self._coz_tip4_v2(frame, bbox, all_text, offset_x, offset_y, hwnd, input_bbox=input_bbox, parsed_expr=parsed_expr)
        """Diyalog bbox'ı biliniyor — matematik ifadesini çöz, input alanına yaz."""
        dx1, dy1, dx2, dy2 = bbox
        dw, dh = dx2 - dx1, dy2 - dy1

        answer = self._tip4_hesapla(all_text)
        if answer is None:
            self._set_status("tip4_hesap_yok", all_text[:80])
            return False

        self._log("info", f"Tip4 ifade='{all_text[:60]}' cevap={answer}")

        # Input alanı: diyaloğun alt %55-85 bandında yatay dikdörtgen ara
        dialog_roi = frame[dy1:dy2, dx1:dx2]
        input_cx, input_cy = self._tip4_input_bul(dialog_roi, dx1, dy1, dw, dh)
        abs_ix = input_cx + offset_x
        abs_iy = input_cy + offset_y

        # Input alanına tıkla, cevabı yaz, Enter bas
        self._tikla(abs_ix, abs_iy, hwnd)
        time.sleep(0.25)
        self._yaz(str(answer), hwnd)
        time.sleep(0.15)
        self._enter_bas(hwnd)

        self._set_status("tiklandi", f"tip4:{answer}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — sonuç={answer}")
        return True

    def _coz_tip4_detect(self, frame, offset_x=0, offset_y=0, hwnd=None):
        return self._coz_tip4_detect_v2(frame, offset_x=offset_x, offset_y=offset_y, hwnd=hwnd)
        """_dialog_bul küçük diyaloğu kaçırdığında bağımsız arama yapar."""
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        # Merkez etrafında daha geniş ama ölçek kısıtlı arama
        sx1 = max(0, cx - 350); sy1 = max(0, cy - 200)
        sx2 = min(w, cx + 350); sy2 = min(h, cy + 250)
        search = frame[sy1:sy2, sx1:sx2]
        if search.size == 0:
            return False

        gray_s = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        edges  = cv2.Canny(cv2.GaussianBlur(gray_s, (5, 5), 0), 40, 110)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        scx_s, scy_s = search.shape[1] / 2.0, search.shape[0] / 2.0
        for cnt in contours:
            x, y, ww, hh = cv2.boundingRect(cnt)
            # Küçük dikdörtgen: 60-400px genişlik, 40-250px yükseklik
            if not (60 <= ww <= 400 and 40 <= hh <= 250):
                continue
            aspect = ww / max(hh, 1)
            if not (0.6 <= aspect <= 5.0):
                continue
            roi = gray_s[y:y + hh, x:x + ww]
            if roi.size == 0:
                continue
            dark_ratio = float(np.mean(roi < 120))
            if dark_ratio < 0.15:
                continue
            cp = (abs((x + ww / 2.0) - scx_s) / max(scx_s, 1) +
                  abs((y + hh / 2.0) - scy_s) / max(scy_s, 1))
            candidates.append((dark_ratio - cp * 0.5, sx1 + x, sy1 + y, ww, hh))

        candidates.sort(reverse=True)

        for _, bx, by, bw, bh in candidates[:5]:
            dlg_roi = frame[by:by + bh, bx:bx + bw]
            if dlg_roi.size == 0:
                continue
            try:
                with self._lock:
                    if not self._reader:
                        return False
                    large = cv2.resize(dlg_roi, None, fx=2.5, fy=2.5,
                                       interpolation=cv2.INTER_CUBIC)
                    results = self._reader.readtext(large, detail=0, paragraph=False)
                ocr_text = " ".join(results).lower()
            except Exception:
                continue

            if not re.search(r'(?<!\d)\d\s*\+\s*\d(?!\d)', ocr_text):
                continue

            self._log("info", f"Tip4-detect OCR: '{ocr_text[:80]}'")
            bbox = (bx, by, bx + bw, by + bh)
            return self._coz_tip4(frame, bbox, ocr_text, offset_x, offset_y, hwnd)

        return False

    def _tip4_hesapla(self, text):
        return self._tip4_hesapla_v2(text)
        """OCR metninden matematik ifadesini çıkarıp hesaplar."""
        import re
        t = (text.lower()
             .replace('×', '*').replace('x', '*').replace('X', '*')
             .replace('÷', '/').replace(':', '/').replace('−', '-')
             .replace('о', '0').replace('O', '0').replace('o', '0')  # OCR 0/O karışıklığı
             .replace('l', '1').replace('I', '1'))                    # OCR 1/l/I karışıklığı

        # Tip4 yalnizca tek haneli toplama: a+b
        m = re.search(r'(?<!\d)(\d)\s*\+\s*(\d)(?!\d)', t)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        return a + b

    def _tip4_input_bul(self, dialog_roi, dx1, dy1, dw, dh):
        return self._tip4_input_bul_v2(dialog_roi, dx1, dy1, dw, dh)
        """Diyalog içinde input kutusunun merkezini döner (frame koordinatları)."""
        # Alt %50-90 bandında en geniş açık dikdörtgeni ara
        y_start = int(dh * 0.50)
        band = dialog_roi[y_start:int(dh * 0.90), int(dw * 0.05):int(dw * 0.95)]
        bx_off = int(dw * 0.05)

        best = None
        if band.size > 0:
            gray_b = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
            # Input kutuları genellikle çevreleyen koyu arka plana göre daha açık
            _, bright = cv2.threshold(gray_b, 85, 255, cv2.THRESH_BINARY)
            cnts, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in cnts:
                x, y, w, h = cv2.boundingRect(cnt)
                if w < 25 or h < 8:
                    continue
                aspect = w / max(h, 1)
                if not (1.5 <= aspect <= 12.0):
                    continue
                if best is None or w * h > best[2] * best[3]:
                    best = (x, y, w, h)

        if best:
            ix = dx1 + bx_off + best[0] + best[2] // 2
            iy = dy1 + y_start + best[1] + best[3] // 2
        else:
            # Fallback: diyaloğun alt %70 merkezi
            ix = dx1 + dw // 2
            iy = dy1 + int(dh * 0.72)
        return ix, iy

    def _coz_tip4_v2(self, frame, bbox, all_text, offset_x, offset_y, hwnd=None, input_bbox=None, parsed_expr=None):
        """Matematik ifadesini cozer, input alanina yazar."""
        dx1, dy1, dx2, dy2 = bbox
        dialog_roi = frame[dy1:dy2, dx1:dx2]
        if dialog_roi.size == 0:
            self._set_status("tip4_dialog_bos")
            return False

        parsed = parsed_expr or self._tip4_parse_expression(all_text)
        if not parsed:
            self._set_status("tip4_ifade_yok", str(all_text)[:80])
            return False

        answer = self._tip4_hesapla_v2(parsed)
        if answer is None:
            self._set_status("tip4_hesap_yok", parsed.get("expr", "")[:80])
            return False

        if input_bbox is None:
            input_bbox = self._tip4_input_bul_v2(dialog_roi, dx1, dy1, dx2 - dx1, dy2 - dy1)
        if input_bbox is None:
            self._set_status("tip4_input_yok", parsed.get("expr", "")[:80])
            return False

        ix1, iy1, ix2, iy2 = input_bbox
        abs_ix = int((ix1 + ix2) / 2) + offset_x
        abs_iy = int((iy1 + iy2) / 2) + offset_y

        self._log("info", f"Tip4 ifade='{parsed['expr']}' cevap={answer} input=({ix1},{iy1},{ix2},{iy2})")

        self._tikla(abs_ix, abs_iy, hwnd)
        time.sleep(0.25)
        self._yaz(str(answer), hwnd)
        time.sleep(0.15)
        self._save_tip4_capture_before_send(frame, bbox, offset_x, offset_y, parsed["expr"], answer, tag="tip4")
        self._enter_bas(hwnd)

        self._set_status("tiklandi", f"tip4:{parsed['expr']}={answer}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — '{parsed['expr']}' = {answer}")
        return True

    def _tip4_panel_bul_v2(self, frame):
        """Merkez cevresinde Tip4 icin muhtemel panel bbox'larini dondurur."""
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        sx1 = max(0, cx - min(360, w // 3))
        sy1 = max(0, cy - min(220, h // 3))
        sx2 = min(w, cx + min(360, w // 3))
        sy2 = min(h, cy + min(260, h // 3))
        search = frame[sy1:sy2, sx1:sx2]
        if search.size == 0:
            return []

        gray_s = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray_s, (5, 5), 0)
        edges = cv2.Canny(blur, 35, 105)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        scx_s, scy_s = search.shape[1] / 2.0, search.shape[0] / 2.0
        for cnt in contours:
            x, y, ww, hh = cv2.boundingRect(cnt)
            if not (80 <= ww <= 340 and 55 <= hh <= 220):
                continue
            aspect = ww / max(hh, 1)
            if not (1.1 <= aspect <= 4.6):
                continue
            roi = gray_s[y:y + hh, x:x + ww]
            if roi.size == 0:
                continue
            dark_ratio = float(np.mean(roi < 125))
            if dark_ratio < 0.18:
                continue
            cx_pen = abs((x + ww / 2.0) - scx_s) / max(scx_s, 1.0)
            cy_pen = abs((y + hh / 2.0) - scy_s) / max(scy_s, 1.0)
            score = dark_ratio * 2.0 - (cx_pen + cy_pen) * 0.8 + min(ww * hh / 25000.0, 1.0) * 0.3
            candidates.append((score, (sx1 + x, sy1 + y, sx1 + x + ww, sy1 + y + hh)))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [bbox for _, bbox in candidates[:8]]

    def _tip4_expression_roi_v2(self, dialog_roi, input_bbox_abs, dx1, dy1):
        """Input kutusunun ustunden matematik metni ROI'si cikarir."""
        ih1 = input_bbox_abs[1] - dy1
        ix1 = input_bbox_abs[0] - dx1
        ix2 = input_bbox_abs[2] - dx1
        dh, dw = dialog_roi.shape[:2]

        expr_y1 = max(0, int(dh * 0.08))
        expr_y2 = max(expr_y1 + 12, ih1 - max(6, int(dh * 0.06)))
        pad_x = max(6, int((ix2 - ix1) * 0.18))
        expr_x1 = max(0, ix1 - pad_x)
        expr_x2 = min(dw, ix2 + pad_x)
        if expr_y2 - expr_y1 < 12 or expr_x2 - expr_x1 < 24:
            return None
        return dialog_roi[expr_y1:expr_y2, expr_x1:expr_x2]

    def _tip4_expression_ocr_v2(self, expr_roi):
        """Expression ROI uzerinde birden fazla OCR varyanti dener."""
        if expr_roi is None or expr_roi.size == 0:
            return []
        with self._lock:
            if not self._reader:
                return []

        gray = cv2.cvtColor(expr_roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, thr_inv = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        sharp = cv2.addWeighted(big, 1.5, cv2.GaussianBlur(big, (0, 0), 2.0), -0.5, 0)
        variants = [big, thr, thr_inv, sharp]

        texts = []
        for var in variants:
            try:
                out = self._reader.readtext(
                    var,
                    detail=0,
                    paragraph=False,
                    allowlist="0123456789+="
                )
            except TypeError:
                out = self._reader.readtext(var, detail=0, paragraph=False)
            except Exception:
                continue
            for item in out or []:
                txt = str(item).strip()
                if txt:
                    texts.append(txt)
        return texts

    def _tip4_normalize_text_v2(self, text):
        """OCR metnini matematiksel ifadeye normalize eder.

        Farkli captcha sorularinda cikan OCR okuma hatalarini duzeltiyor:
          harf/rakam karisikligi, operatör unicode varyantlari, gürültü karakterleri.
        """
        t = str(text or "").strip()
        # ── Operatör varyantlari ────────────────────────────────────────────
        t = (t.replace("Ã—", "").replace("×", "").replace("✕", "")
               .replace("x", "").replace("X", "")
               .replace("Ã·", "").replace("÷", "")
               .replace("âˆ'", "").replace("—", "").replace("–", "")
               .replace("±", "+"))
        # ── Boşluk/gürültü temizle ──────────────────────────────────────────
        t = t.replace(" ", "").replace("=", "").replace("?", "")
        # ── Rakam/harf karişikliği (OCR sık yapar) ──────────────────────────
        # Önce operatör olarak yorumlanmayacak pozisyonlardaki harfleri düzelt.
        # Bu dönüşümler [^0-9+\-*/] temizlenmeden ÖNCE yapılmalı.
        char_map = {
            "O": "0", "o": "0", "Q": "0", "D": "0",
            "I": "1", "l": "1", "|": "1", "i": "1",
            "Z": "2", "z": "2",
            "S": "5", "s": "5",
            "G": "6", "b": "6",
            "T": "7",
            "B": "8",
            "g": "9", "q": "9",
        }
        result = []
        for ch in t:
            if ch in "0123456789+":
                result.append(ch)
            elif ch in char_map:
                result.append(char_map[ch])
            # diğer karakterler düşer
        t = "".join(result)
        return t

    def _tip4_parse_expression(self, ocr_candidates):
        """OCR sonucundan a+b bicimindeki tek haneli toplama ifadesini cikarir.

        - Yalnizca tek haneli toplama kabul edilir: 0-9 + 0-9.
        - Cift haneli veya farkli operatorlu OCR sonuclari gecersiz sayilir.
        - Her captcha farkli soru gosterdiginden OCR her seferinde taze okunur;
          bu fonksiyon yalnizca parse + dogrulama yapar, hibir sey cachlemez.
        - Birden fazla aday varsa en temiz (kisa, gürültüsüz) eslesmeyi alir.
        """
        if isinstance(ocr_candidates, str):
            candidates = [ocr_candidates]
        else:
            candidates = list(ocr_candidates or [])
        best = None
        for raw in candidates:
            # Once ham OCR metninde ara. "Insert the result..." gibi aciklama
            # metinlerini normalize edince harf->rakam duzeltmeleri sahte
            # sayilar uretebiliyor; ham metindeki ayrik "a + b" en guvenli sinyal.
            raw_text = str(raw or "")
            raw_scan = (raw_text.replace("×", "*").replace("x", "*").replace("X", "*")
                                .replace("÷", "/").replace(":", "/")
                                .replace("−", "-").replace("–", "-").replace("—", "-"))
            raw_matches = list(re.finditer(r'(?<!\d)(\d)\s*(\+)\s*(\d)(?!\d)', raw_scan))
            for m in raw_matches:
                a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
                score = 40 - len(m.group(0).replace(" ", ""))
                # Metnin sonundaki ifade genelde asil captcha satiri olur; OCR
                # gurultusu basta toplandiginda dogru adayi one alir.
                score += m.start() / max(len(raw_scan), 1)
                current = {"a": a, "op": op, "b": b,
                           "expr": f"{a}{op}{b}", "raw": raw_text, "score": score}
                if best is None or current["score"] > best["score"]:
                    best = current
            if raw_matches:
                continue

            normalized = self._tip4_normalize_text_v2(raw)
            if not normalized or normalized.isdigit():
                continue
            # Origins Tip4 yalnizca tek haneli TOPLAMA gosterir.
            # ab+cd gibi cift haneli veya operatoru farkli okumalar reddedilir.
            m = re.search(r'(?<!\d)(\d)\s*(\+)\s*(\d)(?!\d)', normalized)
            if not m:
                continue
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            # Skor: daha kisa normalize = daha az gürültü = daha iyi
            score = 20 - len(normalized)
            if raw != normalized:
                score -= 0.5
            current = {"a": a, "op": op, "b": b,
                       "expr": f"{a}{op}{b}", "raw": str(raw), "score": score}
            if best is None or current["score"] > best["score"]:
                best = current
        return best

    def _tip4_gecerli_aday_mi_v2(self, parsed_expr, input_bbox_abs, panel_bbox):
        if not parsed_expr or input_bbox_abs is None or panel_bbox is None:
            return False
        if parsed_expr.get("op") != "+":
            return False
        ix1, iy1, ix2, iy2 = input_bbox_abs
        px1, py1, px2, py2 = panel_bbox
        if ix2 <= ix1 or iy2 <= iy1:
            return False
        if not (px1 <= ix1 < ix2 <= px2 and py1 <= iy1 < iy2 <= py2):
            return False
        if parsed_expr["expr"].isdigit():
            return False
        return True

    def _coz_tip4_detect_v2(self, frame, offset_x=0, offset_y=0, hwnd=None):
        """Kucuk matematik captcha panelini bagimsiz olarak arar ve cozer."""
        for bbox in self._tip4_panel_bul_v2(frame):
            bx1, by1, bx2, by2 = bbox
            dlg_roi = frame[by1:by2, bx1:bx2]
            if dlg_roi.size == 0:
                continue
            try:
                dialog_ok = self._is_captcha_dialog(dlg_roi)
            except Exception:
                dialog_ok = False

            # Once tam OCR yap — Origins tipi mi kontrol et
            try:
                with self._lock:
                    if not self._reader:
                        return False
                    large_full = cv2.resize(dlg_roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    full_results = self._reader.readtext(large_full, detail=0, paragraph=False)
                full_text = " ".join(full_results).lower()
            except Exception:
                full_text = ""

            anchor_ok = bool(
                full_text
                and any(k in full_text for k in ["captcha", "insert", "sum", "result of", "below"])
                and any(k in full_text for k in ["send", "gonder", "gönder", "tamam", "ok"])
            )

            if full_text and any(k in full_text for k in ["insert", "sum", "result of", "below", "send"]):
                parsed = self._tip4_parse_expression(full_text)
                if parsed:
                    answer = self._tip4_hesapla_v2(parsed)
                    if answer is not None:
                        self._log("info", f"Tip4-detect Origins: '{parsed['expr']}={answer}'")
                        return self._coz_origins_math(frame, bbox, full_text, offset_x, offset_y, hwnd)

            if not dialog_ok and not anchor_ok:
                self._set_status("tip4_panel_yanlis", full_text[:80] if full_text else "anchor_yok")
                now = time.time()
                if now - self._last_dialog_log > 2.0:
                    self._log(
                        "warn",
                        f"Tip4 panel dogrulanmadi, atlandi bbox={bbox} "
                        f"ocr='{full_text[:80] if full_text else ''}'"
                    )
                    self._last_dialog_log = now
                continue

            input_bbox = self._tip4_input_bul_v2(dlg_roi, bx1, by1, bx2 - bx1, by2 - by1)
            if input_bbox is None:
                continue

            expr_roi = self._tip4_expression_roi_v2(dlg_roi, input_bbox, bx1, by1)
            if expr_roi is None:
                continue

            ocr_candidates = self._tip4_expression_ocr_v2(expr_roi)
            parsed = self._tip4_parse_expression(ocr_candidates)
            if not self._tip4_gecerli_aday_mi_v2(parsed, input_bbox, bbox):
                continue

            answer = self._tip4_hesapla_v2(parsed)
            if answer is None:
                continue

            self._log("info", f"Tip4-detect OCR: adaylar={ocr_candidates[:4]} secilen='{parsed['expr']}'")
            return self._coz_tip4_v2(
                frame, bbox, parsed["expr"], offset_x, offset_y, hwnd,
                input_bbox=input_bbox, parsed_expr=parsed
            )
        return False

    def _tip4_hesapla_v2(self, text):
        """Yalnizca tek haneli a+b ifadesini kabul eder; duz sayiyi reddeder."""
        parsed = text if isinstance(text, dict) else self._tip4_parse_expression(text)
        if not parsed:
            return None
        a, op, b = parsed["a"], parsed["op"], parsed["b"]
        if op != "+":
            return None
        if not (0 <= int(a) <= 9 and 0 <= int(b) <= 9):
            return None
        return int(a) + int(b)

    def _tip4_input_bul_v2(self, dialog_roi, dx1, dy1, dw, dh):
        """Diyalog icindeki koyu yatay input kutusunun bbox'ini dondurur."""
        if dialog_roi is None or dialog_roi.size == 0 or dw <= 0 or dh <= 0:
            return None

        y_start = int(dh * 0.42)
        y_end = int(dh * 0.92)
        x_start = int(dw * 0.05)
        x_end = int(dw * 0.95)
        band = dialog_roi[y_start:y_end, x_start:x_end]
        if band.size == 0:
            return None

        gray_b = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray_b, (5, 5), 0)
        thr_val = int(max(30, min(90, np.percentile(blur, 28) + 8)))
        _, dark = cv2.threshold(blur, thr_val, 255, cv2.THRESH_BINARY_INV)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel, iterations=2)
        cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best = None
        best_score = -1e9
        band_cx = band.shape[1] / 2.0
        for cnt in cnts:
            x, y, w, h = cv2.boundingRect(cnt)
            if w < max(30, int(dw * 0.18)) or h < max(10, int(dh * 0.08)):
                continue
            aspect = w / max(h, 1)
            if not (2.0 <= aspect <= 14.0):
                continue
            roi = blur[y:y + h, x:x + w]
            if roi.size == 0:
                continue
            mean_v = float(np.mean(roi))
            if mean_v > 105:
                continue
            fill_ratio = float(np.count_nonzero(dark[y:y + h, x:x + w])) / float(max(w * h, 1))
            if fill_ratio < 0.55:
                continue
            center_penalty = abs((x + w / 2.0) - band_cx) / max(band_cx, 1.0)
            darkness = (110.0 - mean_v) / 110.0
            score = darkness * 3.0 + fill_ratio * 2.0 + min(w / max(dw, 1), 1.0) * 1.5 - center_penalty * 1.4
            if score > best_score:
                best_score = score
                best = (dx1 + x_start + x, dy1 + y_start + y, dx1 + x_start + x + w, dy1 + y_start + y + h)
        return best

    def _coz_origins_math(self, frame, bbox, all_text, offset_x, offset_y, hwnd=None):
        """Origins matematik captcha — 4 fazli pipeline.

        Modul 1 — Akiz: dialog zaten bbox olarak geldi.
        Modul 2 — OCR: tek yuksek-kalite gecis; Send (alt anchor) + expression birlikte.
        Modul 3 — Hesap: a op b → tam sayi sonuc.
        Modul 4 — Uygula: input tikla → yaz → Send tikla.
        """
        import random as _rnd
        dx1, dy1, dx2, dy2 = bbox
        dw, dh = dx2 - dx1, dy2 - dy1
        dialog_roi = frame[dy1:dy2, dx1:dx2]
        if dialog_roi.size == 0:
            self._set_status("origins_dialog_bos")
            return False

        # ════════════════════════════════════════════════════════════════
        # FULL TEMPLATE FAST-PATH
        # Template FULL modunda input + Send konumları template'den gelir,
        # OCR anchor aramalarına gerek yoktur. Sadece math bandında OCR yapılır.
        # GÜVENLİK: match loc her zaman güncel bbox üzerinde YENİDEN doğrulanır
        # (stale koordinata tıklama riskini sıfırlamak için).
        # ════════════════════════════════════════════════════════════════
        if (self._tpl_mode == "full"
                and self._input_rel_cx is not None
                and self._send_rel_cx is not None):
            # Match'i taze yap — önceki _last_match_loc bu bbox'a ait olmayabilir
            self._last_match_loc = None
            if not self._is_captcha_dialog(dialog_roi):
                self._log("warn", "Origins FULL: template match yenilendi ama basarisiz — iptal")
                return False
            if self._last_match_loc is None:
                self._log("warn", "Origins FULL: match loc None — iptal")
                return False
            mx, my = self._last_match_loc
            msc    = self._last_match_scale
            # Template koordinatlarını dialog_roi'ye -> absolute ekrana çevir
            input_rx = int(self._input_rel_cx * msc)
            input_ry = int(self._input_rel_cy * msc)
            send_rx  = int(self._send_rel_cx  * msc)
            send_ry  = int(self._send_rel_cy  * msc)

            input_abs_full = (dx1 + mx + input_rx + offset_x,
                              dy1 + my + input_ry + offset_y)
            send_abs_full  = (dx1 + mx + send_rx  + offset_x,
                              dy1 + my + send_ry  + offset_y)

            # Güvenlik: hesaplanan koordinatlar bbox içinde mi?
            tpl_h_s = int(self._header_tpl.shape[0] * msc)
            tpl_w_s = int(self._header_tpl.shape[1] * msc)
            if (mx < 0 or my < 0
                or mx + tpl_w_s > dw or my + tpl_h_s > dh):
                self._log("warn", f"Origins FULL: match loc bbox disinda ({mx},{my}) tpl={tpl_w_s}x{tpl_h_s} bbox={dw}x{dh} — iptal")
                return False

            # Math bandı (template koordinatları + scale + match konumu)
            ey1 = max(0, my + int(self._expr_rel_y1 * msc))
            ey2 = min(dh, my + int(self._expr_rel_y2 * msc))
            if ey2 <= ey1:
                ey1, ey2 = int(dh * 0.22), int(dh * 0.50)
            focus_x1 = max(0, mx + int(tpl_w_s * 0.22))
            focus_x2 = min(dw, mx + int(tpl_w_s * 0.78))
            focus_y1 = max(0, my + int(tpl_h_s * 0.32))
            focus_y2 = min(dh, my + int(tpl_h_s * 0.56))
            self._log(
                "warn",
                f"FAST-PATH aktif: match_loc=({mx},{my}) scale={msc:.2f} "
                f"input_abs=({input_abs_full[0]},{input_abs_full[1]}) "
                f"send_abs=({send_abs_full[0]},{send_abs_full[1]}) "
                f"math_band y={focus_y1}-{focus_y2} x={focus_x1}-{focus_x2}"
            )

            parsed = self._origins_expr_ocr_direct_band(dialog_roi, focus_y1, focus_y2, focus_x1, focus_x2)
            if not parsed:
                parsed = self._origins_expr_ocr_direct_band(dialog_roi, ey1, ey2)
            if not parsed and all_text:
                parsed = self._tip4_parse_expression(all_text)
            if not parsed:
                self._set_status("origins_ifade_yok", all_text[:80])
                self._log(
                    "warn",
                    f"CAPTCHA ÇÖZÜLEMEDİ — matematik ifadesi okunamadı "
                    f"(band y={ey1}-{ey2}, bbox={dw}x{dh})"
                )
                return False

            answer = self._tip4_hesapla_v2(parsed)
            if answer is None:
                self._set_status("origins_hesap_yok", parsed.get("expr", ""))
                self._log("warn", f"CAPTCHA ÇÖZÜLEMEDİ — hesap yok: '{parsed.get('expr','')}'")
                return False
            self._log("info", f"Origins: '{parsed['expr']}' = {answer}")

            # ── Input tıkla → yaz → Send tıkla ──
            # Input TEK click (çift click focus'u kaybettirebilir).
            # Zamanlamalar uzun: oyun penceresi focus + input field activation
            # için yeterli zaman bırakılır.
            self._log("warn", f"ADIM 1: input tikla ({input_abs_full[0]},{input_abs_full[1]})")
            self._tikla(input_abs_full[0], input_abs_full[1], hwnd, single=True)
            time.sleep(0.30)   # focus için yeterli süre

            # İkinci emin olma tıklaması (bazı clientlarda ilk click sadece focus, ikincisi cursor)
            self._log("warn", "ADIM 2: input tekrar tikla (focus garanti)")
            self._tikla(input_abs_full[0], input_abs_full[1], hwnd, single=True)
            time.sleep(0.25)

            self._log("warn", f"ADIM 3: yaz '{answer}'")
            self._yaz(str(answer), hwnd)
            time.sleep(0.35)   # yazma tamamlandıktan sonra Send'e geçmeden önce
            self._save_tip4_capture_before_send(
                frame, bbox, offset_x, offset_y, parsed["expr"], answer, tag="origins_full"
            )

            self._log("warn", f"ADIM 4: Send tikla ({send_abs_full[0]},{send_abs_full[1]})")
            self._tikla(send_abs_full[0], send_abs_full[1], hwnd, single=True)

            self._set_status("tiklandi", f"origins-full:{parsed['expr']}={answer}")
            self._log(
                "success",
                f"✔ CAPTCHA ÇÖZÜLDÜ — '{parsed['expr']}' = {answer} | "
                f"Input ({input_abs_full[0]},{input_abs_full[1]}) → Send ({send_abs_full[0]},{send_abs_full[1]})"
            )
            return True

        # ════════════════════════════════════════════════════════════════
        # MODUL 2 — Tek OCR gecisi (3x) → Top-Anchor + Send + ifade
        # (Header modu / template olmayan senaryolar için geri uyum yolu)
        # Her iki anchor da bulunmazsa yanlış tespit kabul edilir.
        # ════════════════════════════════════════════════════════════════
        SCALE = 3.0
        send_abs            = None   # (abs_x, abs_y) — Send butonunun ekran koordinati
        send_rel_y          = None   # dialog_roi icindeki y (input arama icin)
        captcha_title_found = False  # Top-Anchor: "Captcha" başlık metni
        parsed              = None   # {'a','op','b','expr',...}

        try:
            with self._lock:
                if not self._reader:
                    return False
                large = cv2.resize(dialog_roi, None, fx=SCALE, fy=SCALE,
                                   interpolation=cv2.INTER_CUBIC)
                ocr_res = self._reader.readtext(large, detail=1, paragraph=False)

            # OCR kutularini gez: Captcha baslik + Send + expression bul
            expr_candidates = []
            for box, text, prob in ocr_res:
                if prob < 0.12:   # baslik icin daha dusuk esik (stilize font)
                    continue
                tl  = text.strip()
                tll = tl.lower()

                # Kutunun dialog-roi icindeki y konumu (scale'siz)
                box_y_top = box[0][1] / SCALE   # kutunun ust kenari

                # ── Top-Anchor: "Captcha" baslik (dialog ust %30'u) ─────
                if "captcha" in tll and box_y_top < dh * 0.30:
                    captcha_title_found = True
                    self._log("info", f"Origins: Captcha baslik bulundu y={box_y_top:.0f}")

                # ── Bottom-Anchor: Send butonu ──────────────────────────
                if any(k in tll for k in ("send", "gönder", "gonder", "tamam", "ok")):
                    bx_c = int((box[0][0] + box[2][0]) / 2.0 / SCALE)
                    by_c = int((box[0][1] + box[2][1]) / 2.0 / SCALE)
                    send_abs   = (dx1 + bx_c + offset_x,
                                  dy1 + by_c + offset_y)
                    send_rel_y = by_c
                    self._log("info", f"Origins: Send=({send_abs[0]},{send_abs[1]})")

                # ── Expression toplama: sayi/operator iceren kutular ────
                expr_candidates.append(tl)

            # Tum OCR metninden ifadeyi cikar
            combined = " ".join(expr_candidates)
            parsed = self._tip4_parse_expression(combined)

        except Exception as e:
            self._log("warn", f"Origins OCR hata: {e}")

        # ── Anchor dogrulamasi — iki anchor da zorunlu ───────────────────
        if not captcha_title_found:
            self._set_status("origins_baslik_yok", "'Captcha' baslik tespit edilemedi")
            self._log("warn", "Origins: 'Captcha' baslik bulunamadi — yanlis captcha tespiti, atlanıyor")
            return False

        if not send_abs:
            self._set_status("origins_send_yok", "Send butonu tespit edilemedi — yanlis captcha")
            self._log("warn", "Origins: Send butonu bulunamadi — yanlis captcha tespiti, atlanıyor")
            return False

        self._log("info", f"Origins: Her iki anchor dogrulandi (Captcha baslik + Send)")

        # Fallback 1 — all_text (caller tarafindan zaten OCR edilmis)
        if not parsed:
            parsed = self._tip4_parse_expression(all_text)

        # Fallback 2 — expression bandina ozel binarize+OCR
        if not parsed:
            parsed = self._origins_expr_ocr_direct(dialog_roi, dw, dh)

        if not parsed:
            self._set_status("origins_ifade_yok", all_text[:80])
            return False

        # ════════════════════════════════════════════════════════════════
        # MODUL 3 — Hesapla
        # ════════════════════════════════════════════════════════════════
        answer = self._tip4_hesapla_v2(parsed)
        if answer is None:
            self._set_status("origins_hesap_yok", parsed.get("expr", ""))
            return False
        self._log("info", f"Origins: '{parsed['expr']}' = {answer}")

        # ════════════════════════════════════════════════════════════════
        # MODUL 4 — Input kutusu bul (Send'i alt anchor olarak kullan)
        # ════════════════════════════════════════════════════════════════
        input_abs = self._origins_find_input(
            dialog_roi, dx1, dy1, dw, dh, offset_x, offset_y, send_rel_y
        )

        # 4.1 — Input kutusuna tikla (Focus & Activate)
        self._tikla(input_abs[0], input_abs[1], hwnd)
        time.sleep(_rnd.uniform(0.06, 0.14))

        # 4.2 — Cevabi yaz (Data Entry)
        self._yaz(str(answer), hwnd)
        time.sleep(_rnd.uniform(0.18, 0.28))
        self._save_tip4_capture_before_send(
            frame, bbox, offset_x, offset_y, parsed["expr"], answer, tag="origins"
        )

        # 4.3 — Send butonu tıkla (Submit)  [send_abs zaten doğrulandı, None olamaz]
        self._tikla(send_abs[0], send_abs[1], hwnd)
        self._set_status("tiklandi", f"origins:{parsed['expr']}={answer}")
        self._log("success", f"✔ CAPTCHA ÇÖZÜLDÜ — '{parsed['expr']}' = {answer} | Send ({send_abs[0]},{send_abs[1]})")
        return True

    # ── Yardimci: ozel y bandinda expression OCR (full template icin) ──
    def _origins_expr_ocr_direct_band(self, dialog_roi, ey1, ey2, ex1=None, ex2=None):
        """Math ifade bandında çok katmanlı OCR.

        Origins captcha'sında rakamlar gri arka planda daha açık renkle (gri
        100-130 civarı) çıkıyor. Sabit parlak eşikler (155+) boş görüntü
        üretiyordu; bu nedenle hem BINARY hem BINARY_INV'i hem de adaptive
        threshold'u deniyoruz. İlk başarılı parse döner.
        """
        dh, dw = dialog_roi.shape[:2]
        if ex1 is None:
            ex1 = int(dw * 0.04)
        if ex2 is None:
            ex2 = int(dw * 0.96)
        ex1 = max(0, min(int(ex1), dw - 1))
        ex2 = max(ex1 + 1, min(int(ex2), dw))
        ey1 = max(0, min(ey1, dh - 1))
        ey2 = max(ey1 + 1, min(ey2, dh))
        band = dialog_roi[ey1:ey2, ex1:ex2]
        if band.size == 0:
            return None
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)

        # Teşhis: band piksel dağılımı
        self._log(
            "warn",
            f"Expr band gray: min={int(gray.min())} max={int(gray.max())} "
            f"mean={float(gray.mean()):.1f} median={int(np.median(gray))} shape={gray.shape}"
        )

        # Varyantlar: farklı eşikler + inversiyon + adaptive + raw
        variants = []
        for t in (60, 80, 100, 120, 140, 160):
            _, b = cv2.threshold(gray, t, 255, cv2.THRESH_BINARY)
            variants.append((f"bin{t}", b))
            _, bi = cv2.threshold(gray, t, 255, cv2.THRESH_BINARY_INV)
            variants.append((f"inv{t}", bi))
        # Otsu (otomatik eşik)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("otsu", otsu))
        _, otsu_i = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.append(("otsui", otsu_i))
        # Adaptive
        adapt = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                       cv2.THRESH_BINARY, 15, 5)
        variants.append(("adapt", adapt))
        adapt_i = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                         cv2.THRESH_BINARY_INV, 15, 5)
        variants.append(("adapti", adapt_i))
        # Raw gray (bazen en iyisi)
        variants.append(("raw", gray))

        tried_texts = []
        for name, img in variants:
            try:
                large = cv2.resize(img, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
                large_bgr = cv2.cvtColor(large, cv2.COLOR_GRAY2BGR) if len(large.shape) == 2 else large
                with self._lock:
                    if not self._reader:
                        return None
                    # allowlist: sadece rakamlar ve + karakteri — daha kesin OCR
                    results = self._reader.readtext(
                        large_bgr, detail=0, paragraph=False,
                        allowlist='0123456789+ '
                    )
                candidates = " ".join(results).strip()
                tried_texts.append(f"{name}:'{candidates}'")
                parsed = self._tip4_parse_expression(candidates)
                if parsed:
                    self._log("warn", f"Expr-OCR BASARI ({name}): '{candidates}' -> {parsed['expr']}")
                    return parsed
            except Exception as e:
                tried_texts.append(f"{name}:ERR({e})")

        # Hiçbiri parse edemedi — tüm sonuçları göster
        self._log("warn", f"Expr-OCR TUM DENEMELER BASARISIZ: {' | '.join(tried_texts[:12])}")
        return None

    # ── Yardimci: expression bandini binarize edip ozel OCR ile oku ─────────
    def _origins_expr_ocr_direct(self, dialog_roi, dw, dh):
        """Dialog ortasindaki expression bandina coklu esik + 4x OCR uygular.

        Her captcha farkli matematik sorusu gosterebilir; farkli dialog
        parlakliklarina karsi robustluk icin 3 farkli binarization esigi
        denenir (155, 120, 185). Ilk basarili parse dondurilur.
        """
        # Expression yaklasik diyalogun %22-65 araliginda bulunur
        ey1 = max(0, int(dh * 0.22))
        ey2 = min(dh, int(dh * 0.65))
        ex1 = max(0, int(dw * 0.04))
        ex2 = min(dw, int(dw * 0.96))
        band = dialog_roi[ey1:ey2, ex1:ex2]
        if band.size == 0:
            return None

        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)

        # Farkli dialog parlakliklarina karsi 3 esik dene
        for thresh in (155, 120, 185):
            _, binary = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)

            # 4x scale → daha iyi OCR dogrulugu (rakamlar iri, net okunur)
            large = cv2.resize(binary, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
            large_bgr = cv2.cvtColor(large, cv2.COLOR_GRAY2BGR)

            try:
                with self._lock:
                    if not self._reader:
                        return None
                    results = self._reader.readtext(
                        large_bgr, detail=0, paragraph=False,
                        allowlist='0123456789+ '
                    )
                candidates = " ".join(results)
                parsed = self._tip4_parse_expression(candidates)
                if parsed:
                    self._log("info", f"Origins expr-OCR (esik={thresh}): '{candidates[:60]}' -> {parsed['expr']}")
                    return parsed
                else:
                    self._log("debug", f"Origins expr-OCR (esik={thresh}): parse basarisiz — '{candidates[:60]}'")
            except Exception as e:
                self._log("warn", f"Origins expr-OCR hata (esik={thresh}): {e}")

        self._log("warn", "Origins expr-OCR: tum esikler basarisiz, ifade okunamadi")
        return None

    # ── Yardimci: Send'i alt anchor alarak input kutusunu bul ───────────────
    def _origins_find_input(self, dialog_roi, dx1, dy1, dw, dh,
                            offset_x, offset_y, send_rel_y=None):
        """Siyah input kutusunu kontur tespiti ile bulur.

        send_rel_y: Send butonunun dialog_roi icindeki y koordinati.
        Biliniyorsa arama bandin ustu Send'in hemen altina kadar kisaltilir.
        """
        # Arama bandi: Send'in yukari kismi veya sabit yuzde
        if send_rel_y is not None:
            band_y2 = max(10, int(send_rel_y - dh * 0.02))
            band_y1 = max(0, band_y2 - int(dh * 0.40))
        else:
            band_y1 = int(dh * 0.40)
            band_y2 = int(dh * 0.88)

        band_x1 = int(dw * 0.05)
        band_x2 = int(dw * 0.95)
        band = dialog_roi[band_y1:band_y2, band_x1:band_x2]

        if band.size > 0:
            gray_b = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)

            # Input kutusu cok koyu (siyah, ~0-50)
            _, dark = cv2.threshold(gray_b, 50, 255, cv2.THRESH_BINARY_INV)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
            dark   = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel, iterations=2)
            cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            best       = None
            best_score = -1.0
            bw_center  = band.shape[1] / 2.0

            for cnt in cnts:
                x, y, cw, ch = cv2.boundingRect(cnt)
                if cw < max(25, int(dw * 0.22)) or ch < 7:
                    continue
                aspect = cw / max(ch, 1)
                if not (2.5 <= aspect <= 20.0):
                    continue
                roi_g  = gray_b[y:y+ch, x:x+cw]
                if roi_g.size == 0:
                    continue
                mean_v = float(np.mean(roi_g))
                if mean_v > 85:
                    continue
                cx_pen = abs((x + cw / 2.0) - bw_center) / max(bw_center, 1.0)
                # Genis + koyu + merkezi = yuksek skor
                score = (85.0 - mean_v) / 85.0 * 2.0 \
                      + min(cw / max(dw, 1), 1.0) \
                      - cx_pen * 0.7
                if score > best_score:
                    best_score = score
                    best = (dx1 + band_x1 + x + cw // 2,
                            dy1 + band_y1 + y + ch // 2)

            if best:
                pos = (best[0] + offset_x, best[1] + offset_y)
                self._log("info", f"Origins: Input=({pos[0]},{pos[1]}) skor={best_score:.2f}")
                return pos

        # Fallback: Send'in biraz usunden veya sabit %63
        if send_rel_y is not None:
            fx = dx1 + dw // 2 + offset_x
            fy = dy1 + max(0, int(send_rel_y - dh * 0.10)) + offset_y
        else:
            fx = dx1 + dw // 2 + offset_x
            fy = dy1 + int(dh * 0.63) + offset_y
        self._log("warn", f"Origins: Input fallback ({fx},{fy})")
        return (fx, fy)

    def _yaz(self, text, hwnd=None):
        """Metni SendInput klavye olaylarıyla yazar (rakam + eksi için).

        Yazmadan önce oyun penceresine focus zorlar (keys global gönderildiği
        için focus yanlış pencereye geçmişse cevap kaybolur).
        """
        VK_MAP = {
            '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
            '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
            '-': 0xBD,  # VK_OEM_MINUS
        }
        # Focus garanti
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, 9)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.08)
            except Exception:
                pass
        for ch in str(text):
            vk = VK_MAP.get(ch)
            if vk is None:
                continue
            # MapVirtualKey ile scan code (bazı clientlar scan code bekler)
            scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
            ctypes.windll.user32.keybd_event(vk, scan, 0, 0)            # KEYDOWN
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(vk, scan, 0x0002, 0)       # KEYUP
            time.sleep(0.08)

    def _enter_bas(self, hwnd=None):
        """Enter tuşuna basar."""
        VK_RETURN = 0x0D
        ctypes.windll.user32.keybd_event(VK_RETURN, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_RETURN, 0, 0x0002, 0)

    def _tikla(self, x, y, hwnd=None, single=False):
        """Tıklama — varsayılan çift, single=True ise tek click.
        Input alanları single kullanmalı (çift click focus kaybettirebilir).
        """
        self._son_tiklama = time.time()
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.05)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)
            except:
                pass
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.08)
        _send_mouse_input(0x0002)   # LMB DOWN
        time.sleep(0.05)
        _send_mouse_input(0x0004)   # LMB UP
        if not single:
            time.sleep(0.15)
            _send_mouse_input(0x0002)
            time.sleep(0.05)
            _send_mouse_input(0x0004)
