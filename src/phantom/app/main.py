"""PHANTOM v6 â€” Metin2 AI Bot (Tam Yeniden YapÄ±landÄ±rma)"""
import os
import time
import json
import copy
import random
import base64
import ctypes
import threading
import re
import difflib
import unicodedata
from collections import deque

import cv2
import mss
import keyboard
import numpy as np
import win32gui
import win32api
import webview
import tkinter as tk
from tkinter import filedialog

import torch
from ultralytics import YOLO

# SHIFT+SOL TIK iÃ§in lock (recursive loop Ã¶nlemek iÃ§in)
sol_tik_lock = threading.Lock()

try:
    from ..captcha.solver import CaptchaWatcher
    CAPTCHA_OK = True
except ImportError:
    CAPTCHA_OK = False

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, "..", "..", ".."))
SCRIPT_DIR = PROJECT_ROOT
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config_phantom.json")
HTML_FILE = os.path.join(PROJECT_ROOT, "index.html")
HP_TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates", "hp_templates")
MESSAGE_TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates", "message_templates")
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
EVIDENCE_DIR = os.path.join(RUNTIME_DIR, "evidence")
HP_TEMPLATE_SCALES = [1.0, 0.75, 0.50, 0.25]
HP_TEMPLATE_MIN_SCORE = 0.70
MESSAGE_TEMPLATE_SCALES = [1.0, 0.90, 0.80, 1.10]
MESSAGE_TEMPLATE_MIN_SCORE = 0.68
MESSAGE_REPLY_TEXTS = [
    "selam",
    "efendim",
    "buyur",
    "nasıl yardımcı olayım",
    "bir sorun mu var",
    "buradayım sorun mu var",
    "yardımcı olayım mı",
    "dinliyorum",
]
MESSAGE_ACTION_COOLDOWN = 6.0
MESSAGE_SELF_NAME_PREFIXES = ("vespa",)
MESSAGE_SELF_ECHO_SECONDS = 3.0
MESSAGE_SELF_ECHO_SIMILARITY = 0.74
MESSAGE_OCR_MIN_CONF = 0.20
MESSAGE_FARM_PAUSE_SECONDS = 300.0
LOOT_BURST_TAPS = 6
LOOT_TAP_INTERVAL = 0.08
LOOT_POST_KILL_DELAY = 0.12
HEDEF_KUYRUK_BATCH_CLICK_GAP = 0.10
HEDEF_KUYRUK_HP_CLICK_DELAY = 0.0
HEDEF_KUYRUK_NO_HP_RESET_SN = 2.0
HEDEF_KUYRUK_INITIAL_RETRY_SN = 1.5
HEDEF_KUYRUK_FRAME_MAX_AGE = 1.20
DEFAULT_TARGET_FRAME_MAX_AGE = 0.80
TARGET_STABLE_RADIUS = 8
TARGET_STABLE_MAX_FRAME_GAP = 0.20
GLOBAL_PAUSE_WARN_AFTER = 20.0
GLOBAL_PAUSE_WARN_EVERY = 15.0
WINDOW_ISSUE_LOG_INTERVAL = 8.0
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_RETENTION_DAYS = 7
EVIDENCE_RETENTION_DAYS = 14
TERMINAL_HIDDEN_INFO_PREFIXES = (
    "[LOOT]",
    "Client 1 captcha status:",
    "Client 2 captcha status:",
)
FIXED_CONF_ESIK = 0.50
FIXED_DOGRULAMA_SN = 1.50
FIXED_HP_BEKLEME_SN = 0.0
FIXED_ANTI_STUCK_SN = 15.0
FIXED_ANTI_HAREKETSIZ_SN = 10.0
FIXED_ANTI_KURTARMA_BEKLEME_SN = 3.0
ANTI_SUCUK_BACK_HOLD_SN = 1.8
ANTI_SUCUK_BACK_HOLD_REPEAT_SN = 2.35
ANTI_SUCUK_SIDE_HOLD_MIN_SN = 0.50
ANTI_SUCUK_SIDE_HOLD_MAX_SN = 0.90
ANTI_SUCUK_SIDE_HOLD_REPEAT_MIN_SN = 0.80
ANTI_SUCUK_SIDE_HOLD_REPEAT_MAX_SN = 1.25
ANTI_SUCUK_REPEAT_WINDOW_SN = 20.0
os.makedirs(HP_TEMPLATE_DIR, exist_ok=True)
os.makedirs(MESSAGE_TEMPLATE_DIR, exist_ok=True)
os.makedirs(RUNTIME_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

_log_file_lock = threading.Lock()

def _cleanup_runtime_dir(path, max_age_days, keep_suffixes=None):
    keep_suffixes = tuple(keep_suffixes or ())
    try:
        cutoff = time.time() - (float(max_age_days) * 86400.0)
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                continue
            if keep_suffixes and not name.lower().endswith(keep_suffixes):
                continue
            try:
                if os.path.getmtime(full) < cutoff:
                    os.remove(full)
            except Exception:
                pass
    except Exception:
        pass

def _rotated_log_path():
    path = os.path.join(LOG_DIR, f"events_{time.strftime('%Y%m%d')}.jsonl")
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_LOG_FILE_BYTES:
            idx = 1
            while True:
                rotated = os.path.join(LOG_DIR, f"events_{time.strftime('%Y%m%d')}_{idx}.jsonl")
                if not os.path.exists(rotated):
                    os.replace(path, rotated)
                    break
                idx += 1
    except Exception:
        pass
    return path

def _safe_file_part(text, limit=48):
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-", "+", "=") else "_" for ch in str(text or ""))
    cleaned = cleaned.strip("_") or "event"
    return cleaned[:limit]

def _should_show_terminal_log(level, message):
    lvl = str(level or "").lower()
    msg = str(message or "")
    if "[KUYRUK]" in msg and lvl not in ("error", "critical", "kritik"):
        return False
    if lvl == "debug":
        return False
    if lvl in ("error", "critical", "kritik", "warn", "warning"):
        return True
    if any(msg.startswith(prefix) for prefix in TERMINAL_HIDDEN_INFO_PREFIXES):
        return False
    return True

def log_event(state, level, message):
    entry = {"ts": time.strftime("%H:%M:%S"), "level": level, "message": message}
    if _should_show_terminal_log(level, message):
        with state.lk:
            state.logs.append(entry)
    try:
        line = dict(entry)
        line["date"] = time.strftime("%Y-%m-%d")
        path = _rotated_log_path()
        with _log_file_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass

def save_evidence_capture(event, client_label, image=None, hwnd=None, bbox=None, meta=None, state=None):
    """Kritik olaylar icin PNG + JSON kanit kaydi olusturur."""
    crop = None
    source = "none"
    if image is not None and getattr(image, "size", 0):
        try:
            if bbox:
                x1, y1, x2, y2 = [int(v) for v in bbox]
                h, w = image.shape[:2]
                x1 = max(0, min(x1, w - 1)); y1 = max(0, min(y1, h - 1))
                x2 = max(x1 + 1, min(x2, w)); y2 = max(y1 + 1, min(y2, h))
                crop = image[y1:y2, x1:x2].copy()
                source = "frame_crop"
            else:
                crop = image.copy()
                source = "frame"
        except Exception:
            crop = None
    if (crop is None or crop.size == 0) and hwnd:
        try:
            r = win32gui.GetWindowRect(hwnd)
            if r[0] >= -32000 and r[2] > r[0] and r[3] > r[1]:
                with mss.mss() as sct:
                    shot = np.array(sct.grab({
                        "left": int(r[0]), "top": int(r[1]),
                        "width": int(r[2] - r[0]), "height": int(r[3] - r[1])
                    }), dtype=np.uint8)
                crop = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
                source = "live_window"
        except Exception:
            crop = None
    if crop is None or crop.size == 0:
        if state:
            log_event(state, "warn", f"[KANIT] {event} goruntusu kaydedilemedi ({client_label})")
        return None

    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = int((time.time() % 1.0) * 1000)
    event_part = _safe_file_part(event, 24)
    client_part = _safe_file_part(client_label, 28)
    base = f"{event_part}_{client_part}_{ts}_{ms:03d}"
    img_path = os.path.join(EVIDENCE_DIR, base + ".png")
    json_path = os.path.join(EVIDENCE_DIR, base + ".json")
    if not cv2.imwrite(img_path, crop):
        if state:
            log_event(state, "warn", f"[KANIT] {event} goruntusu yazilamadi: {img_path}")
        return None
    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "client": client_label,
        "source": source,
        "image": img_path,
        "meta": meta or {},
    }
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if state:
        log_event(state, "info", f"[KANIT] {event} kaydedildi: {img_path}")
    return img_path

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SendInput YapÄ±larÄ± (DonanÄ±msal TÄ±klama â€” Anti-Cheat Bypass)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),("mouseData",ctypes.c_ulong),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]
class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi",MOUSEINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type",ctypes.c_ulong),("iu",INPUT_UNION)]

_extra = ctypes.c_ulong(0)
def _send_mouse(flags):
    iu = INPUT_UNION(); iu.mi = MOUSEINPUT(0,0,0,flags,0,ctypes.pointer(_extra))
    cmd = INPUT(0, iu)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))

def _sol_tik_sendinput(x, y):
    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x-bx, y-by)
    if dist >= 10:
        steps = max(10, min(int(dist/20), 55))
        for i in range(steps):
            t = 1-(1-i/steps)**2
            ctypes.windll.user32.SetCursorPos(int(bx+(x-bx)*t), int(by+(y-by)*t))
            time.sleep(random.uniform(0.002, 0.005))
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _send_mouse(0x0002)  # LEFTDOWN
    time.sleep(random.uniform(0.06, 0.10))
    _send_mouse(0x0004)  # LEFTUP

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Interception Kernel Driver â€” Ã–ncelikli GiriÅŸ
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class _IMouseStroke(ctypes.Structure):
    _fields_ = [
        ("state",       ctypes.c_ushort),
        ("flags",       ctypes.c_ushort),
        ("rolling",     ctypes.c_short),
        ("x",           ctypes.c_int),
        ("y",           ctypes.c_int),
        ("information", ctypes.c_uint),
    ]

class _IKeyStroke(ctypes.Structure):
    """Interception klavye stroke yapÄ±sÄ± (InterceptionKeyStroke)."""
    _fields_ = [
        ("code",        ctypes.c_ushort),   # PS/2 scan kodu
        ("state",       ctypes.c_ushort),   # 0=down 1=up 2=e0_down 3=e0_up
        ("information", ctypes.c_ulong),
    ]

# Interception klavye state sabitleri
_IKDOWN = 0x00   # key down
_IKUP   = 0x01   # key up

# PS/2 scan kodlarÄ± (Interception set-1)
_SC = {
    'ctrl':  0x1D,   # Left Ctrl
    'g':     0x22,
    'v':     0x2F,
    'enter': 0x1C,
    '1':     0x02,
    '2':     0x03,
    's':     0x1F,
    'a':     0x1E,
    'd':     0x20,
    'z':     0x2C,
    'space': 0x39,   # Space bar
}

_IMDN  = 0x0001   # LEFT_BUTTON_DOWN
_IMUP  = 0x0002   # LEFT_BUTTON_UP
_IMRDN = 0x0004   # RIGHT_BUTTON_DOWN
_IMRUP = 0x0008   # RIGHT_BUTTON_UP
_IMABS = 0x0001   # MOVE_ABSOLUTE
_IMVD  = 0x0002   # VIRTUAL_DESKTOP (Ã§ok monitÃ¶r desteÄŸi)

_ilib = None
_icx  = None
_idev = 11        # Interception mouse device (11-20)
_ikdev = None     # Interception keyboard device (1-10)
INTERCEPTION_OK = False

def _interception_init():
    global _ilib, _icx, _idev, _ikdev, INTERCEPTION_OK
    for path in [os.path.join(SCRIPT_DIR, "interception.dll"), "interception.dll"]:
        try:
            lib = ctypes.WinDLL(path)
            lib.interception_create_context.restype  = ctypes.c_void_p
            lib.interception_create_context.argtypes = []
            lib.interception_destroy_context.restype  = None
            lib.interception_destroy_context.argtypes = [ctypes.c_void_p]
            lib.interception_send.restype  = ctypes.c_int
            lib.interception_send.argtypes = [
                ctypes.c_void_p, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_uint,   # void* â€” hem mouse hem klavye stroke geÃ§er
            ]
            lib.interception_is_invalid.restype  = ctypes.c_int
            lib.interception_is_invalid.argtypes = [ctypes.c_int]
            ctx = lib.interception_create_context()
            if not ctx:
                continue
            # Mouse device bul (11-20)
            found_mouse = 11
            for dev in range(11, 21):
                if lib.interception_is_invalid(dev) == 0:
                    found_mouse = dev
                    break
            # Klavye device bul (1-10)
            found_kb = None
            for dev in range(1, 11):
                if lib.interception_is_invalid(dev) == 0:
                    found_kb = dev
                    break
            _ilib, _icx, _idev, _ikdev = lib, ctx, found_mouse, found_kb
            INTERCEPTION_OK = True
            return True
        except Exception:
            pass
    return False

_interception_init()

def _ik_send(scancode, state):
    """Interception Ã¼zerinden tek bir klavye olayÄ± gÃ¶nder."""
    if not _ilib or not _icx or _ikdev is None:
        return False
    try:
        s = _IKeyStroke(code=scancode, state=state, information=0)
        _ilib.interception_send(_icx, _ikdev, ctypes.byref(s), 1)
        return True
    except Exception:
        return False

def _ik_tap(scancode, delay=0.05):
    """Bir tuÅŸa basÄ±p bÄ±rak (Interception Ã¼zerinden)."""
    _ik_send(scancode, _IKDOWN)
    time.sleep(delay)
    _ik_send(scancode, _IKUP)

def _ik_ctrl_tap(key_scancode, delay=0.05):
    """Ctrl+<tuÅŸ> kombinasyonu (Interception Ã¼zerinden)."""
    _ik_send(_SC['ctrl'], _IKDOWN)
    time.sleep(0.03)
    _ik_send(key_scancode, _IKDOWN)
    time.sleep(delay)
    _ik_send(key_scancode, _IKUP)
    time.sleep(0.03)
    _ik_send(_SC['ctrl'], _IKUP)

def _sol_tik_interception(x, y):
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)

    def _move(px, py):
        nx = int(px * 65535 / max(sw - 1, 1))
        ny = int(py * 65535 / max(sh - 1, 1))
        s = _IMouseStroke(state=0, flags=_IMABS | _IMVD, rolling=0, x=nx, y=ny, information=0)
        _ilib.interception_send(_icx, _idev, ctypes.byref(s), 1)

    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x - bx, y - by)
    if dist >= 10:
        steps = max(10, min(int(dist / 20), 55))
        for i in range(steps):
            t = 1 - (1 - i / steps) ** 2
            _move(int(bx + (x - bx) * t), int(by + (y - by) * t))
            time.sleep(random.uniform(0.002, 0.005))
    _move(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _ilib.interception_send(_icx, _idev, ctypes.byref(
        _IMouseStroke(state=_IMDN, flags=0, rolling=0, x=0, y=0, information=0)), 1)
    time.sleep(random.uniform(0.06, 0.10))
    _ilib.interception_send(_icx, _idev, ctypes.byref(
        _IMouseStroke(state=_IMUP, flags=0, rolling=0, x=0, y=0, information=0)), 1)

def _sag_tik_sendinput(x, y):
    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x-bx, y-by)
    if dist >= 10:
        steps = max(10, min(int(dist/20), 55))
        for i in range(steps):
            t = 1-(1-i/steps)**2
            ctypes.windll.user32.SetCursorPos(int(bx+(x-bx)*t), int(by+(y-by)*t))
            time.sleep(random.uniform(0.002, 0.005))
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _send_mouse(0x0008)  # RIGHTDOWN
    time.sleep(random.uniform(0.06, 0.10))
    _send_mouse(0x0010)  # RIGHTUP

def _sag_tik_interception(x, y):
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)

    def _move(px, py):
        nx = int(px * 65535 / max(sw - 1, 1))
        ny = int(py * 65535 / max(sh - 1, 1))
        s = _IMouseStroke(state=0, flags=_IMABS | _IMVD, rolling=0, x=nx, y=ny, information=0)
        _ilib.interception_send(_icx, _idev, ctypes.byref(s), 1)

    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x - bx, y - by)
    if dist >= 10:
        steps = max(10, min(int(dist / 20), 55))
        for i in range(steps):
            t = 1 - (1 - i / steps) ** 2
            _move(int(bx + (x - bx) * t), int(by + (y - by) * t))
            time.sleep(random.uniform(0.002, 0.005))
    _move(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _ilib.interception_send(_icx, _idev, ctypes.byref(
        _IMouseStroke(state=_IMRDN, flags=0, rolling=0, x=0, y=0, information=0)), 1)
    time.sleep(random.uniform(0.06, 0.10))
    _ilib.interception_send(_icx, _idev, ctypes.byref(
        _IMouseStroke(state=_IMRUP, flags=0, rolling=0, x=0, y=0, information=0)), 1)

_sag_tik_lock = threading.Lock()

def sag_tik_hw(x, y, hwnd=None):
    """SaÄŸ tÄ±k â€” Interception driver yÃ¼klÃ¼yse kernel-level, yoksa SendInput."""
    if not _sag_tik_lock.acquire(blocking=False):
        return
    try:
        if INTERCEPTION_OK and not _force_sendinput:
            _sag_tik_interception(x, y)
        else:
            _sag_tik_sendinput(x, y)
    finally:
        _sag_tik_lock.release()

_force_sendinput = False  # TÄ±klama modu otomatik: Interception varsa kullanÄ±lÄ±r, yoksa SendInput.

def sol_tik_hw(x, y, hwnd=None):
    """Interception driver yÃ¼klÃ¼yse kernel-level tÄ±klama yapar, yoksa SendInput kullanÄ±r."""
    if not sol_tik_lock.acquire(blocking=False):
        return
    try:
        if INTERCEPTION_OK and not _force_sendinput:
            _sol_tik_interception(x, y)
        else:
            _sol_tik_sendinput(x, y)
    finally:
        sol_tik_lock.release()

def sol_tik_hw_shift_callback():
    """SHIFT+LeftClick iÃ§in callback."""
    x, y = win32api.GetCursorPos()
    sol_tik_hw(x, y)

_shift_tik_lock = threading.Lock()

def shift_sol_tik_hw(x, y, hwnd=None):
    """Shift+Sol tÄ±k."""
    if not _shift_tik_lock.acquire(blocking=False):
        return
    try:
        keyboard.press('shift')
        try:
            if INTERCEPTION_OK and not _force_sendinput:
                _sol_tik_interception(x, y)
            else:
                _sol_tik_sendinput(x, y)
        finally:
            keyboard.release('shift')
    finally:
        _shift_tik_lock.release()

def shift_sag_tik_hw(x, y, hwnd=None):
    """Shift+SaÄŸ tÄ±k."""
    if not _shift_tik_lock.acquire(blocking=False):
        return
    try:
        keyboard.press('shift')
        try:
            if INTERCEPTION_OK and not _force_sendinput:
                _sag_tik_interception(x, y)
            else:
                _sag_tik_sendinput(x, y)
        finally:
            keyboard.release('shift')
    finally:
        _shift_tik_lock.release()

def _tiklama_yap(cfg, x, y, hwnd=None):
    """Config'deki tiklama_turu'na gÃ¶re doÄŸru tÄ±klama fonksiyonunu Ã§aÄŸÄ±rÄ±r."""
    turu = cfg.g("tiklama_turu") or "default"
    if turu == "right":
        sag_tik_hw(x, y, hwnd)
    elif turu == "shift_left":
        shift_sol_tik_hw(x, y, hwnd)
    elif turu == "shift_right":
        shift_sag_tik_hw(x, y, hwnd)
    else:  # default / left â€” sol tÄ±k (mevcut davranÄ±ÅŸ)
        sol_tik_hw(x, y, hwnd)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Pencere YardÄ±mcÄ±larÄ±
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def pencereleri_getir():
    lst = ["Yok","TÃ¼m Ekran"]
    def cb(h,r):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and t != "Program Manager": r.append(f"{t} (ID: {h})")
    win32gui.EnumWindows(cb, lst); return lst

def hwnd_al(val):
    if not val or val in ("Yok","TÃ¼m Ekran"): return None
    try: return int(val.split("(ID: ")[1].replace(")",""))
    except: return None

def pencere_odakla(hwnd):
    if not hwnd:
        return
    try:
        # Minimize ise geri aÃ§
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.05)
        # Foreground lock sÃ¼resini 0 yap (baÅŸka pencereye geÃ§iÅŸi zorla)
        ctypes.windll.user32.SystemParametersInfoW(0x2001, 0, None, 0)  # SPI_SETFOREGROUNDLOCKTIMEOUT
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
    except Exception:
        pass

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Config (per-client ayÄ±rÄ±mlÄ±)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _clipboard_set_text(text):
    """Unicode metni Windows panosuna koyar."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040

    data = ctypes.create_unicode_buffer(str(text) + "\0")
    size = ctypes.sizeof(data)

    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
    if not hmem:
        return False
    locked = kernel32.GlobalLock(hmem)
    if not locked:
        kernel32.GlobalFree(hmem)
        return False
    ctypes.memmove(locked, ctypes.addressof(data), size)
    kernel32.GlobalUnlock(hmem)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(hmem)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        hmem = None
        return True
    finally:
        user32.CloseClipboard()
        if hmem:
            kernel32.GlobalFree(hmem)

def _normalize_outgoing_text(text):
    replacements = {
        "Ä±": "ı",
        "Ä°": "İ",
        "Ã§": "ç",
        "Ã‡": "Ç",
        "Ã¶": "ö",
        "Ã–": "Ö",
        "Ã¼": "ü",
        "Ãœ": "Ü",
        "ÄŸ": "ğ",
        "Äž": "Ğ",
        "ÅŸ": "ş",
        "Åž": "Ş",
    }
    value = str(text or "")
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value

def _paste_text_and_enter(text, hwnd=None):
    text = _normalize_outgoing_text(text)
    if hwnd:
        pencere_odakla(hwnd)
    if not _clipboard_set_text(text):
        return False
    time.sleep(0.08)
    if _ikdev is not None and INTERCEPTION_OK and not _force_sendinput:
        _ik_ctrl_tap(_SC['v'], delay=0.05)
        time.sleep(0.10)
        _ik_tap(_SC['enter'], delay=0.04)
    else:
        keyboard.send('ctrl+v')
        time.sleep(0.10)
        keyboard.send('enter')
    return True

def _client_varsayilan():
    return {
        "aktif":True,"pencere":"Yok","conf_esik":FIXED_CONF_ESIK,"oto_loot":True,
        "hp_region":[0.02,0.07,0.30,0.70],"hp_bekleme_sn":FIXED_HP_BEKLEME_SN,"hp_stuck_timeout":20,
        "ignore_radius":35,"captcha":False,"debug_on":True,"message_captcha":True,
        "loot_taps":LOOT_BURST_TAPS,"loot_interval":LOOT_TAP_INTERVAL,"loot_delay":LOOT_POST_KILL_DELAY,
        "captcha_tip1":False,"captcha_tip2":False,"captcha_tip3":False,"captcha_tip4":False,
        "cember_yaricap":200,
        "cember_aktif":True,
    }

VARSAYILAN = {
    "model_yolu":"",
    "eco_mode":False,
    "conf_esik":FIXED_CONF_ESIK,
    "dogrulama_sn":FIXED_DOGRULAMA_SN,
    "hp_bekleme_sn":FIXED_HP_BEKLEME_SN,
    "oto_loot":True,
    "loot_taps":LOOT_BURST_TAPS,
    "loot_interval":LOOT_TAP_INTERVAL,
    "loot_delay":LOOT_POST_KILL_DELAY,
    "captcha":False,
    "message_captcha":True,
    "captcha_tip1":False,
    "captcha_tip2":False,
    "captcha_tip3":False,
    "captcha_tip4":False,
    "cember_yaricap":200,
    "cember_aktif":True,
    "mesafe_kontrol_aktif":True,
    "anti_sucuk":False,
    "anti_aranma_aktif":False,
    "anti_aranma_sn":0,
    "anti_stuck_sn":FIXED_ANTI_STUCK_SN,
    "anti_hareketsiz_sn":FIXED_ANTI_HAREKETSIZ_SN,
    "anti_kurtarma_bekleme_sn":FIXED_ANTI_KURTARMA_BEKLEME_SN,
    "hedef_kuyruk_aktif":False,
    "hedef_kuyruk_sayisi":"default",
    "c1":_client_varsayilan(),
    "c2":_client_varsayilan(),
}

class Cfg:
    def __init__(self):
        self.d = copy.deepcopy(VARSAYILAN)
        self.lk = threading.Lock()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE,"r",encoding="utf-8") as f:
                    saved = json.load(f)
                    if "hedef_kuyruk_aktif" not in saved:
                        legacy_queue = str(saved.get("hedef_kuyruk_sayisi", "default")).lower()
                        self.d["hedef_kuyruk_aktif"] = legacy_queue in {"aktif", "true", "1", "on", "2", "3", "4", "5"}
                    for k in saved:
                        if k in self.d and isinstance(self.d[k], dict) and isinstance(saved[k], dict):
                            self.d[k].update(saved[k])
                        else:
                            self.d[k] = saved[k]
            except: pass
        self._force_fixed_values()

    def _force_fixed_values(self):
        self.d["conf_esik"] = FIXED_CONF_ESIK
        self.d["dogrulama_sn"] = FIXED_DOGRULAMA_SN
        self.d["hp_bekleme_sn"] = FIXED_HP_BEKLEME_SN
        anti_on = bool(self.d.get("anti_sucuk", False))
        self.d["anti_aranma_aktif"] = False
        self.d["anti_aranma_sn"] = 0
        self.d["anti_stuck_sn"] = FIXED_ANTI_STUCK_SN
        self.d["anti_hareketsiz_sn"] = FIXED_ANTI_HAREKETSIZ_SN
        self.d["anti_kurtarma_bekleme_sn"] = FIXED_ANTI_KURTARMA_BEKLEME_SN
        for key in ("c1", "c2"):
            self.d.setdefault(key, _client_varsayilan())
            self.d[key]["conf_esik"] = FIXED_CONF_ESIK
            self.d[key]["dogrulama_sn"] = FIXED_DOGRULAMA_SN
            self.d[key]["hp_bekleme_sn"] = FIXED_HP_BEKLEME_SN
            self.d[key]["anti_sucuk"] = anti_on
            self.d[key]["anti_aranma_aktif"] = False
            self.d[key]["anti_aranma_sn"] = 0
            self.d[key]["anti_stuck_sn"] = FIXED_ANTI_STUCK_SN
            self.d[key]["anti_hareketsiz_sn"] = FIXED_ANTI_HAREKETSIZ_SN
            self.d[key]["anti_kurtarma_bekleme_sn"] = FIXED_ANTI_KURTARMA_BEKLEME_SN

    def save(self):
        with self.lk:
            self._force_fixed_values()
            with open(CONFIG_FILE,"w",encoding="utf-8") as f:
                json.dump(self.d, f, indent=2, ensure_ascii=False)

    def g(self, *keys):
        with self.lk:
            o = self.d
            for k in keys:
                if not isinstance(o, dict):
                    return None
                o = o.get(k)
                if o is None:
                    return None
            return o

    def s(self, val, *keys):
        with self.lk:
            o = self.d
            for k in keys[:-1]: o = o.setdefault(k, {})
            o[keys[-1]] = val
        self.save()

    def client(self, idx):
        """c1 veya c2 dict dÃ¶ndÃ¼r"""
        k = f"c{idx}"
        with self.lk:
            self._force_fixed_values()
            return dict(self.d.get(k, _client_varsayilan()))

    def update_client(self, idx, data):
        k = f"c{idx}"
        with self.lk:
            if k not in self.d: self.d[k] = _client_varsayilan()
            self.d[k].update(data)
            self._force_fixed_values()
        self.save()

    def update_global(self, data):
        shared = {"conf_esik", "dogrulama_sn", "hp_bekleme_sn", "oto_loot", "loot_taps", "loot_interval", "loot_delay", "captcha", "message_captcha", "captcha_tip1", "captcha_tip2", "captcha_tip3", "captcha_tip4", "anti_sucuk", "anti_aranma_aktif", "anti_aranma_sn", "anti_stuck_sn", "anti_hareketsiz_sn", "anti_kurtarma_bekleme_sn", "hedef_kuyruk_aktif", "hedef_kuyruk_sayisi"}
        data = dict(data or {})
        if "hedef_kuyruk_sayisi" in data and "hedef_kuyruk_aktif" not in data:
            legacy_queue = str(data.get("hedef_kuyruk_sayisi", "default")).lower()
            data["hedef_kuyruk_aktif"] = legacy_queue in {"aktif", "true", "1", "on", "2", "3", "4", "5"}
        with self.lk:
            for key, value in data.items():
                self.d[key] = value
                if key in shared:
                    self.d.setdefault("c1", _client_varsayilan())[key] = value
                    self.d.setdefault("c2", _client_varsayilan())[key] = value
            self._force_fixed_values()
        self.save()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PaylaÅŸÄ±lan Durum
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class State:
    def __init__(self):
        self.lk = threading.Lock()
        self.aktif = False
        self.started_at = 0.0
        self.wdata = {}
        self.frame_b64 = {}
        self.cihaz = "cpu"
        self.durum = {}
        self.captcha_block = {}
        self.captcha_cd = {}
        self.captcha_state = {}
        self.captcha_global_active = False
        self.captcha_global_owner = None
        self.captcha_global_since = 0.0
        self.message_global_active = False
        self.message_global_owner = None
        self.message_global_since = 0.0
        self.global_pause_active = False
        self.global_pause_kind = ""
        self.global_pause_owner = None
        self.global_pause_reason = ""
        self.global_pause_since = 0.0
        self.logs = deque(maxlen=500)
        self.target_memory = {}  # w â†’ {"positions": [(x,y),...], "consecutive_found": int, "confirmed": bool, "last_confirmed_pos": (x,y)}
        self.kill_counts = {}  # c1/c2 -> int; eski pencere anahtarlari fallback olarak desteklenir
        self.scene_changed_t = {}  # pk â†’ son ekran hareketi zamanÄ± (koordinat bazlÄ± hareketsiz tespiti)
        self.message_farm_pause_until = {}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Aksiyon Thread
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class ActionThread(threading.Thread):
    def __init__(self, cfg, state):
        super().__init__(daemon=True)
        self.cfg, self.st = cfg, state
        self._stop_event = threading.Event()
        self.dur = {}
        self.dogr_t = {}
        self.dogr_n = {}
        self._hp_onceki_durum = {}
        self._son_tiklama_t = {}
        self._hp_ignore_until = {}
        self._hp_kayip_t = {}
        self._loot_last_t = {}
        self._loot_log_t = {}
        self._loot_running = {}
        self._son_tiklama_zamani = {}
        self._son_hedef = {}
        self._hedef_blacklist = {}
        self._hedef_kuyruk = {}
        self._hedef_kuyruk_click_t = {}
        self._hedef_kuyruk_stable_log_t = {}
        self._hedef_kuyruk_fresh_log_t = {}
        self._queue_prev_targets = {}
        self._default_fresh_log_t = {}
        self._queue_model_cache = {}
        self._araniyor_baslat_t = {}
        self._hareketsiz_baslat_t = {}
        self._son_manevra_t = {}
        self._takilma_baslat_t = {}
        self._s_basmis = {}
        self._hareketsiz_basmis = {}   # per-window: manevra sÄ±rasÄ±nda re-entry engelle
        self._son_hareket_t = {}       # per-window: son gerÃ§ek hareket zamanÄ±
        self._anti_sucuk_diag_t = {}
        self._ad_basmis = False

    def stop(self):
        self._stop_event.set()

    def _init(self, w):
        if w not in self.dur:
            self.dur[w]="ARANIYOR"
            self.dogr_t[w]=0; self.dogr_n[w]=0

    def _kill_count_key(self, client_idx=None):
        try:
            ci = int(client_idx)
        except (TypeError, ValueError):
            return None
        return f"c{ci}" if ci in (1, 2) else None

    def _record_kill(self, w, client_idx=None):
        key = self._kill_count_key(client_idx) or w
        if not key:
            return
        with self.st.lk:
            self.st.kill_counts[key] = self.st.kill_counts.get(key, 0) + 1

    def _input_blocked(self, w=None):
        with self.st.lk:
            if self._stop_event.is_set() or not self.st.aktif:
                return True
            if self.st.global_pause_active or self.st.captcha_global_active or self.st.message_global_active:
                return True
        return False

    def _anti_sucuk_log_throttled(self, w, reason, message, now=None, interval=3.0):
        now = now or time.time()
        key = (w, reason)
        last = float(self._anti_sucuk_diag_t.get(key, 0) or 0)
        if now - last >= interval:
            self._anti_sucuk_diag_t[key] = now
            log_event(self.st, "debug", message)

    def _anti_sucuk_state_allowed(self, state, hp_var):
        if state in ("DOGRULAMA", "CAPTCHA", "CAPTCHA BEKLE", "MESAJ", "MESAJ BEKLE"):
            return False
        if hp_var:
            return state in ("SAVASIYOR", "KUYRUK")
        return state in ("ARANIYOR", "KUYRUK", "SAVASIYOR")

    def _hedef_kuyruk_aktif(self):
        raw = self.cfg.g("hedef_kuyruk_aktif")
        if raw is not None:
            if isinstance(raw, str):
                return raw.strip().lower() in {"aktif", "true", "1", "on", "yes"}
            return bool(raw)
        legacy = str(self.cfg.g("hedef_kuyruk_sayisi") or "default").lower()
        return legacy in {"aktif", "true", "1", "on", "2", "3", "4", "5"}

    def _queue_state_key(self, w, client_idx=None):
        if client_idx:
            return f"C{client_idx}:{w}"
        return str(w)

    def _hp_bitis_gecikmesi(self, cc):
        return FIXED_HP_BEKLEME_SN

    def _clear_target_click_cooldown(self, w, cc, now=None):
        now = time.time() if now is None else now
        self._son_tiklama_t[w] = now - self._hp_bitis_gecikmesi(cc)

    def _clear_hedef_kuyruk(self, w, client_idx=None):
        keys = [self._queue_state_key(w, client_idx)] if client_idx else [str(w)]
        if client_idx is None:
            suffix = f":{w}"
            keys.extend(k for k in list(self._hedef_kuyruk.keys()) if str(k).endswith(suffix))
            keys.extend(k for k in list(self._hedef_kuyruk_click_t.keys()) if str(k).endswith(suffix))
        for key in set(keys):
            self._hedef_kuyruk.pop(key, None)
            self._hedef_kuyruk_click_t.pop(key, None)
        self._queue_prev_targets.pop((w, "fresh"), None)

    def _hedef_kuyruk_merkez_yaricap(self, cc):
        try:
            base = float((cc or {}).get("ignore_radius", 35) or 35)
            return max(90.0, base * 2.5)
        except Exception:
            return 90.0

    def _target_xy(self, target):
        if isinstance(target, dict):
            return float(target.get("x", target.get("cx", 0))), float(target.get("y", target.get("cy", 0)))
        return float(target[0]), float(target[1])

    def _queue_target_xy(self, target):
        if isinstance(target, dict) and target.get("box"):
            b1, b2, b3, b4 = target["box"]
            w_box = max(1, int(b3) - int(b1))
            h_box = max(1, int(b4) - int(b2))
            x = int((int(b1) + int(b3)) / 2)
            y = int(int(b2) + h_box * 0.56)
            return float(max(int(b1) + 3, min(int(b3) - 3, x))), float(max(int(b2) + 3, min(int(b4) - 3, y)))
        return self._target_xy(target)

    def _target_center_xy(self, target):
        if isinstance(target, dict):
            return float(target.get("cx", target.get("x", 0))), float(target.get("cy", target.get("y", 0)))
        return float(target[0]), float(target[1])

    def _filter_stable_queue_targets(self, key, targets, now=None):
        now = time.time() if now is None else now
        prev = self._queue_prev_targets.get(key) or {}
        prev_ts = float(prev.get("ts", 0.0) or 0.0)
        prev_centers = prev.get("centers") or []
        frame_gap_ok = bool(prev_centers) and (now - prev_ts) <= TARGET_STABLE_MAX_FRAME_GAP
        stable = []
        for target in targets or []:
            cx, cy = self._target_center_xy(target)
            dist = min((np.hypot(cx - px, cy - py) for px, py in prev_centers), default=999999.0)
            stable_click = frame_gap_ok and dist <= TARGET_STABLE_RADIUS
            if isinstance(target, dict):
                target["stable_click"] = bool(stable_click)
                target["stable_distance"] = float(dist if dist < 999999.0 else 0.0)
            if stable_click:
                stable.append(target)
        self._queue_prev_targets[key] = {
            "ts": now,
            "centers": [self._target_center_xy(target) for target in targets or []],
        }
        return stable

    def _refresh_hedef_kuyruk_target(self, target, live_targets, ecx, ecy, exclude_center_radius=0, blacklist=None):
        if not target or not live_targets:
            return None
        old_cx, old_cy = self._target_center_xy(target)
        blacklist = blacklist or []
        adaylar = []
        for cand in live_targets:
            cx, cy = self._target_center_xy(cand)
            if exclude_center_radius and np.hypot(cx - ecx, cy - ecy) <= exclude_center_radius:
                continue
            if any(np.hypot(cx - bx, cy - by) < 35 for bx, by in blacklist):
                continue
            dist = float(np.hypot(cx - old_cx, cy - old_cy))
            if dist <= 110:
                adaylar.append((dist, cand))
        if not adaylar:
            return None
        adaylar.sort(key=lambda item: item[0])
        return adaylar[0][1]

    def _valid_hedef_kuyruk_target(self, target):
        if not isinstance(target, dict) or not target.get("box"):
            return False
        try:
            b1, b2, b3, b4 = target["box"]
            w_box = int(b3) - int(b1)
            h_box = int(b4) - int(b2)
            area = w_box * h_box
            ar = w_box / h_box if h_box > 0 else 999
            conf = float(target.get("conf", 0.0) or 0.0)
            return 200 < area < 25000 and 0.3 < ar < 2.5 and conf >= 0.45
        except Exception:
            return False

    def _select_hedef_kuyruk_targets(self, gecerli, ecx, ecy, count, exclude_center_radius=0, blacklist=None):
        if not gecerli or count <= 0:
            return []
        blacklist = blacklist or []
        aday_havuzu = [m for m in gecerli if self._valid_hedef_kuyruk_target(m)]
        sirali = sorted(aday_havuzu, key=lambda m: np.hypot(self._target_center_xy(m)[0] - ecx, self._target_center_xy(m)[1] - ecy))
        secilen = []
        for m in sirali:
            cx, cy = self._target_center_xy(m)
            x, y = self._target_xy(m)
            if exclude_center_radius and np.hypot(cx - ecx, cy - ecy) <= exclude_center_radius:
                continue
            if any(np.hypot(cx - bx, cy - by) < 35 for bx, by in blacklist):
                continue
            if any(np.hypot(cx - self._target_center_xy(s)[0], cy - self._target_center_xy(s)[1]) < 30 for s in secilen):
                continue
            secilen.append(m)
            if len(secilen) >= count:
                break
        return secilen

    def _fresh_hedef_kuyruk_targets(self, w, hwnd, cc):
        if not hwnd or self._input_blocked(w):
            return None
        model_path = (cc or {}).get("model_yolu") or self.cfg.g("model_yolu")
        if not model_path or not os.path.exists(model_path):
            return None
        try:
            model = self._queue_model_cache.get(model_path)
            if model is None:
                model = YOLO(model_path)
                dummy_size = 640
                model(np.zeros((dummy_size, dummy_size, 3), dtype=np.uint8), verbose=False)
                self._queue_model_cache[model_path] = model
            r = win32gui.GetWindowRect(hwnd)
            if r[0] < -32000:
                return None
            mon = {"top": r[1], "left": r[0], "width": r[2] - r[0], "height": r[3] - r[1]}
            if mon["width"] <= 0 or mon["height"] <= 0:
                return None
            with mss.mss() as sct:
                img = cv2.cvtColor(np.array(sct.grab(mon), dtype=np.uint8), cv2.COLOR_BGRA2BGR)
            conf = FIXED_CONF_ESIK
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            res = model(img, stream=True, verbose=False, conf=conf, half=(dev == "cuda"), imgsz=640, iou=0.45)
            hedefler = []
            frame_ts = time.time()
            for rr in res:
                if not rr.boxes:
                    continue
                bxs = rr.boxes.xyxy.cpu().numpy().astype(int)
                cfs = rr.boxes.conf.cpu().numpy()
                for i, (b1, b2, b3, b4) in enumerate(bxs):
                    w_box = int(b3) - int(b1)
                    h_box = int(b4) - int(b2)
                    area = w_box * h_box
                    ar = w_box / h_box if h_box > 0 else 999
                    if not (200 < area < 25000 and 0.3 < ar < 2.5):
                        continue
                    hedefler.append({
                        "x": int((b1 + b3) / 2),
                        "y": int(b2 + (h_box * 0.56)),
                        "cx": int((b1 + b3) / 2),
                        "cy": int((b2 + b4) / 2),
                        "box": (int(b1), int(b2), int(b3), int(b4)),
                        "conf": float(cfs[i]),
                    })
            stable_hedefler = self._filter_stable_queue_targets((w, "fresh"), hedefler, frame_ts)
            return {
                "targets": stable_hedefler,
                "ecx": mon["width"] // 2,
                "ecy": mon["height"] // 2,
                "ox": r[0],
                "oy": r[1],
                "ts": frame_ts,
            }
        except Exception as e:
            last = self._hedef_kuyruk_fresh_log_t.get((w, "fresh_infer"), 0)
            now = time.time()
            if now - last > 3.0:
                self._hedef_kuyruk_fresh_log_t[(w, "fresh_infer")] = now
                log_event(self.st, "warn", f"[KUYRUK] anlik hedef yenileme basarisiz: {e} ({w})")
            return None

    def _hedef_kuyruk_frame_fresh(self, w, data_ts, now=None, max_age=1.50):
        now = now or time.time()
        if not data_ts:
            return False
        fresh = (now - float(data_ts)) <= max_age
        if not fresh:
            last = self._hedef_kuyruk_fresh_log_t.get(w, 0)
            if now - last > 1.5:
                self._hedef_kuyruk_fresh_log_t[w] = now
                log_event(self.st, "info", f"[KUYRUK] goruntu gecikti, tiklama yok: {now - float(data_ts):.2f}s ({w})")
        return fresh

    def _default_frame_fresh(self, w, data_ts, now=None):
        now = now or time.time()
        if not data_ts:
            return False
        age = now - float(data_ts)
        fresh = age <= DEFAULT_TARGET_FRAME_MAX_AGE
        if not fresh:
            last = self._default_fresh_log_t.get(w, 0)
            if now - last > 2.0:
                self._default_fresh_log_t[w] = now
                log_event(self.st, "warn", f"[HEDEF] goruntu gecikti, tiklama atlandi: {age:.2f}s ({w})")
        return fresh

    def _ensure_hedef_kuyruk_state(self, w, hp_var=False, client_idx=None):
        qkey = self._queue_state_key(w, client_idx)
        q = self._hedef_kuyruk.get(qkey)
        if not q or "hp_visible_lock" not in q:
            q = {
                "client_idx": client_idx,
                "hp_was_visible": False,
                "initial_clicked": False,
                "batch_blacklist": [],
                "last_initial_click_t": 0.0,
                "no_target_since": 0.0,
                "no_hp_since": 0.0,
                "hp_visible_lock": False,
                "pending_click_at": 0.0,
                "pending_blacklist": [],
                "last_hp_click_t": 0.0,
            }
            self._hedef_kuyruk[qkey] = q
        return q

    def _click_hedef_kuyruk_target(self, w, target, hwnd, ox, oy, now, data_ts=0, min_gap=HEDEF_KUYRUK_BATCH_CLICK_GAP, client_idx=None):
        if not target or self._input_blocked(w):
            return False
        if not self._hedef_kuyruk_frame_fresh(w, data_ts, now, max_age=HEDEF_KUYRUK_FRAME_MAX_AGE):
            return False
        qkey = self._queue_state_key(w, client_idx)
        if now - self._hedef_kuyruk_click_t.get(qkey, 0) < min_gap:
            return False
        pencere_odakla(hwnd)
        if self._input_blocked(w):
            return False
        x, y = self._queue_target_xy(target)
        _tiklama_yap(self.cfg, x + ox, y + oy, hwnd)
        click_now = time.time()
        self._hedef_kuyruk_click_t[qkey] = click_now
        self._son_tiklama_t[w] = click_now
        self._son_hareket_t[w] = click_now
        self._son_tiklama_zamani[w] = click_now
        self._takilma_baslat_t[w] = click_now
        self._son_hedef[w] = (float(x), float(y))
        return True

    def _click_hedef_kuyruk_batch(self, w, targets, hwnd, ox, oy, now, data_ts=0):
        if not targets or self._input_blocked(w):
            return 0
        if not self._hedef_kuyruk_frame_fresh(w, data_ts, now, max_age=HEDEF_KUYRUK_FRAME_MAX_AGE):
            return 0
        pencere_odakla(hwnd)
        if self._input_blocked(w):
            return 0
        clicked = 0
        for target in targets:
            if self._input_blocked(w):
                break
            if not self._valid_hedef_kuyruk_target(target):
                continue
            x, y = self._queue_target_xy(target)
            _tiklama_yap(self.cfg, x + ox, y + oy, hwnd)
            clicked += 1
            click_now = time.time()
            self._hedef_kuyruk_click_t[w] = click_now
            self._son_tiklama_t[w] = click_now
            self._son_hareket_t[w] = click_now
            self._son_tiklama_zamani[w] = click_now
            self._takilma_baslat_t[w] = click_now
            self._son_hedef[w] = (float(x), float(y))
        return clicked

    def _handle_hedef_kuyruk(self, w, hp_var, cc, hwnd, now, mrk, gecerli, hedefler, ecx, ecy, ox, oy, active_windows=None, data_ts=0, client_idx=None):
        if not self._hedef_kuyruk_aktif():
            self._clear_hedef_kuyruk(w, client_idx)
            self.dur[w] = "ARANIYOR"
            return

        q = self._ensure_hedef_kuyruk_state(w, hp_var, client_idx)
        center_radius = self._hedef_kuyruk_merkez_yaricap(cc)

        if not hp_var:
            if q.get("hp_was_visible"):
                log_event(self.st, "info", f"Mob oldu: {w}")
                self._record_kill(w, q.get("client_idx") or client_idx)
                if cc.get("oto_loot", True):
                    self._loot_burst_async(w, hwnd, cc, "mob oldu")
            q["hp_was_visible"] = False
            q["hp_visible_lock"] = False
            q["pending_click_at"] = 0.0
            q["pending_blacklist"] = []
            if not q.get("no_hp_since"):
                q["no_hp_since"] = now
            if q.get("initial_clicked") and now - float(q.get("no_hp_since", now) or now) >= HEDEF_KUYRUK_NO_HP_RESET_SN:
                q["initial_clicked"] = False
                q["batch_blacklist"] = []
            if not q.get("initial_clicked"):
                fresh = self._fresh_hedef_kuyruk_targets(w, hwnd, cc)
                if not fresh:
                    if not q.get("no_target_since"):
                        q["no_target_since"] = now
                    elif (
                        bool(self.cfg.g("anti_sucuk"))
                        and self._anti_sucuk_state_allowed("KUYRUK", hp_var)
                        and now - float(q.get("no_target_since", now) or now) >= FIXED_ANTI_HAREKETSIZ_SN
                    ):
                        if self._anti_sucuk_araniyor_manevra(w, hwnd, now):
                            q["no_target_since"] = time.time()
                    self.dur[w] = "KUYRUK"
                    return
                q["no_target_since"] = 0.0
                ilk = self._select_hedef_kuyruk_targets(
                    fresh["targets"], fresh["ecx"], fresh["ecy"], 1, blacklist=q.get("batch_blacklist") or []
                )
                if ilk and self._click_hedef_kuyruk_target(
                    w, ilk[0], hwnd, fresh["ox"], fresh["oy"], now, data_ts=fresh["ts"], min_gap=HEDEF_KUYRUK_BATCH_CLICK_GAP, client_idx=client_idx
                ):
                    q["initial_clicked"] = True
                    q["last_initial_click_t"] = time.time()
                    q["batch_blacklist"] = [self._target_center_xy(ilk[0])]
                    q["no_hp_since"] = now
            self.dur[w] = "KUYRUK"
            return

        q["hp_was_visible"] = True
        q["no_hp_since"] = 0.0
        if not q.get("hp_visible_lock"):
            q["hp_visible_lock"] = True
            q["pending_click_at"] = now + HEDEF_KUYRUK_HP_CLICK_DELAY
            q["pending_blacklist"] = []

        pending_at = float(q.get("pending_click_at", 0.0) or 0.0)
        if pending_at <= 0 or now < pending_at:
            self.dur[w] = "KUYRUK"
            return

        fresh = self._fresh_hedef_kuyruk_targets(w, hwnd, cc)
        if not fresh:
            self.dur[w] = "KUYRUK"
            return
        adaylar = self._select_hedef_kuyruk_targets(
            fresh["targets"], fresh["ecx"], fresh["ecy"], 1, exclude_center_radius=center_radius,
            blacklist=(q.get("batch_blacklist") or []) + (q.get("pending_blacklist") or [])
        )
        if not adaylar:
            self.dur[w] = "KUYRUK"
            return

        if self._click_hedef_kuyruk_target(
            w, adaylar[0], hwnd, fresh["ox"], fresh["oy"], now, data_ts=fresh["ts"], min_gap=HEDEF_KUYRUK_BATCH_CLICK_GAP, client_idx=client_idx
        ):
            q["last_hp_click_t"] = time.time()
            q["pending_click_at"] = 0.0
            q["pending_blacklist"] = [self._target_center_xy(adaylar[0])]
            q["batch_blacklist"] = [self._target_center_xy(adaylar[0])]
        self.dur[w] = "KUYRUK"

    def _loot_tap(self):
        if _ikdev is not None and INTERCEPTION_OK and not _force_sendinput:
            _ik_tap(_SC['z'], delay=0.025)
        else:
            keyboard.press('z')
            time.sleep(0.025)
            keyboard.release('z')

    def _loot_burst(self, w, hwnd, cc, reason="loot", taps=None, delay=None, set_status=True):
        if not cc.get("oto_loot", True) or self._input_blocked(w):
            return False
        now = time.time()
        min_gap = 0.25
        if now - self._loot_last_t.get(w, 0) < min_gap:
            return False

        try:
            tap_count = int(taps if taps is not None else cc.get("loot_taps", LOOT_BURST_TAPS))
        except Exception:
            tap_count = LOOT_BURST_TAPS
        tap_count = max(1, min(tap_count, 12))

        try:
            interval = float(cc.get("loot_interval", LOOT_TAP_INTERVAL) or LOOT_TAP_INTERVAL)
        except Exception:
            interval = LOOT_TAP_INTERVAL
        interval = max(0.03, min(interval, 0.25))

        try:
            start_delay = float(delay if delay is not None else cc.get("loot_delay", LOOT_POST_KILL_DELAY))
        except Exception:
            start_delay = LOOT_POST_KILL_DELAY
        start_delay = max(0.0, min(start_delay, 0.6))

        if hwnd:
            pencere_odakla(hwnd)
        if start_delay and self._stop_event.wait(start_delay):
            return False

        if set_status:
            with self.st.lk:
                self.st.durum[w] = "LOOT"
        for _ in range(tap_count):
            if self._input_blocked(w):
                return False
            self._loot_tap()
            if self._stop_event.wait(interval):
                return False

        self._loot_last_t[w] = time.time()
        last_log = self._loot_log_t.get(w, 0)
        if time.time() - last_log > 2.0:
            log_event(self.st, "info", f"[LOOT] {reason}: Z x{tap_count} ({w})")
            self._loot_log_t[w] = time.time()
        return True

    def _loot_burst_async(self, w, hwnd, cc, reason="loot", taps=None, delay=None):
        if not cc.get("oto_loot", True) or self._input_blocked(w):
            return False
        if self._loot_running.get(w, False):
            return False

        self._loot_running[w] = True
        cc_copy = dict(cc or {})

        def _run():
            try:
                self._loot_burst(w, hwnd, cc_copy, reason, taps=taps, delay=delay, set_status=False)
            finally:
                self._loot_running[w] = False

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _handle_araniyor(self, w, gecerli, hp_var, ecx, ecy, hwnd, cc, ox, oy, hedefler=None, data_ts=0, client_idx=None):
        import numpy as np
        now = time.time()

        if self._hedef_kuyruk_aktif():
            self._handle_hedef_kuyruk(w, hp_var, cc, hwnd, now, gecerli, gecerli, hedefler or [], ecx, ecy, ox, oy, data_ts=data_ts, client_idx=client_idx)
            return
        self._clear_hedef_kuyruk(w, client_idx)

        if hp_var:
            self.dur[w] = "SAVASIYOR"
            # Timer sadece ilk kez (0 ise) set edilir â€” salÄ±nÄ±mda reset'lenmez
            if not self._son_tiklama_zamani.get(w):
                self._son_tiklama_zamani[w] = time.time()
            self._araniyor_baslat_t.pop(w, None)
            return

        if not gecerli:
            anti_sucuk = bool(self.cfg.g("anti_sucuk"))
            if anti_sucuk and self._anti_sucuk_state_allowed("ARANIYOR", hp_var):
                baslangic = float(self._araniyor_baslat_t.get(w, 0) or 0)
                if not baslangic:
                    self._araniyor_baslat_t[w] = now
                elif now - baslangic >= FIXED_ANTI_HAREKETSIZ_SN:
                    if self._anti_sucuk_araniyor_manevra(w, hwnd, now):
                        self._araniyor_baslat_t[w] = time.time()
            else:
                self._araniyor_baslat_t.pop(w, None)
            return

        if now - self._son_tiklama_t.get(w, 0) < self._hp_bitis_gecikmesi(cc):
            return

        self._araniyor_baslat_t.pop(w, None)
        h = gecerli[np.argmin([np.hypot(m[0]-ecx, m[1]-ecy) for m in gecerli])]
        self._kilitli_hedef = getattr(self, '_kilitli_hedef', {})
        self._kilitli_hedef[w] = (float(h[0]), float(h[1]))

        pencere_odakla(hwnd)
        _tiklama_yap(self.cfg, h[0]+ox, h[1]+oy, hwnd)
        if cc.get("oto_loot", True):
            self._loot_burst(w, hwnd, cc, "hedef sonrasi", taps=1, delay=0.0, set_status=False)
        self._son_tiklama_t[w] = now
        self._son_hareket_t[w] = now  # hareketsiz timer sÄ±fÄ±rla
        self.dur[w] = "DOGRULAMA"
        self.dogr_t[w] = time.time()
        self.dogr_n[w] = 0
        self._son_tiklama_zamani[w] = time.time()
        self._takilma_baslat_t[w] = time.time()
        self._son_hedef[w] = (float(h[0]), float(h[1]))
    def _handle_dogrulama(self, w, hp_var, cc):
        now = time.time()
        bekleme_suresi = FIXED_DOGRULAMA_SN
        
        if now - self.dogr_t[w] > bekleme_suresi:
            # Timeout doldu
            if hp_var:
                # HP bar var â†’ SAVASIYOR
                self.dur[w] = "SAVASIYOR"
                self.dogr_n[w] = 0
            else:
                # HP bar yok â†’ ARANIYOR (yeni hedef ara)
                self.dogr_n[w] = self.dogr_n.get(w,0)+1
                if self.dogr_n[w] >= 3:
                    self.dogr_n[w]=0
                self._clear_target_click_cooldown(w, cc, now)
                self.dur[w] = "ARANIYOR"
        else:
            # Timeout dolmadÄ±, bekle
            pass

    def _handle_savasiyor(self, w, hp_var, cc, hwnd, now, gecerli, ecx, ecy, ox, oy, client_idx=None):
        import numpy as np
        anti_sucuk = bool(self.cfg.g("anti_sucuk"))
        stuck_sn = FIXED_ANTI_STUCK_SN

        # TAKILMA: durum SAVASIYOR'da ne kadar kaldÄ±ÄŸÄ±nÄ± Ã¶lÃ§ â€” hp_var'dan baÄŸÄ±msÄ±z
        if not self._takilma_baslat_t.get(w):
            self._takilma_baslat_t[w] = now

        if anti_sucuk and stuck_sn > 0:
            takilma_t = self._takilma_baslat_t[w]
            if now - takilma_t > stuck_sn:
                if not self._anti_sucuk_cooldown_ready(w, now, "savas_uzarsa"):
                    self._anti_sucuk_log_throttled(w, "savas_uzarsa_cooldown", f"Anti-sucuk SAVAS atlandi: cooldown ({w})", now)
                    return
                log_event(self.st, "warn", f"Takilma ({now - takilma_t:.1f}s/{stuck_sn}s): {w}")
                kilitli = getattr(self, '_kilitli_hedef', {}).get(w)
                bl = self._hedef_blacklist.setdefault(w, [])
                if kilitli and not any(np.hypot(kilitli[0]-b[0], kilitli[1]-b[1]) < 30 for b in bl):
                    bl.append((int(kilitli[0]), int(kilitli[1])))
                if gecerli:
                    filtreli = [m for m in gecerli if not any(np.hypot(m[0]-b[0], m[1]-b[1]) < 30 for b in bl)]
                    if not filtreli:
                        bl.clear()
                        filtreli = gecerli
                    h = filtreli[np.argmin([np.hypot(m[0]-ecx, m[1]-ecy) for m in filtreli])]
                    pencere_odakla(hwnd)
                    _tiklama_yap(self.cfg, h[0]+ox, h[1]+oy, hwnd)
                    self._mark_anti_sucuk_manevra(w, now, "savas_uzarsa")
                    self._takilma_baslat_t[w] = now
                    self._son_hareket_t[w] = now      # hareketsiz timer sÄ±fÄ±rla
                    self._son_tiklama_t[w] = now      # ARANIYOR'a geÃ§ilirse anÄ±nda tekrar tÄ±klamasÄ±n
                    self._hp_onceki_durum.pop(w, None)  # yeni hedef â€” eski HP durumu geÃ§ersiz
                    self._hp_kayip_t.pop(w, None)       # HP kayÄ±p zamanlayÄ±cÄ±sÄ±nÄ± sÄ±fÄ±rla
                    log_event(self.st, "info", f"Yeni hedef tiklandi (takilma): {w}")
                else:
                    self._takilma_baslat_t.pop(w, None)
                    self.dur[w] = "ARANIYOR"
                    log_event(self.st, "warn", f"Takilma: baska hedef yok, ARANIYOR'a geciliyor: {w}")
                return

        if hp_var:
            self._hp_onceki_durum[w] = True
            self._hp_kayip_t.pop(w, None)
            self._araniyor_baslat_t.pop(w, None)
            self._hareketsiz_baslat_t.pop(w, None)
            return

        else:
            onceki_hp = self._hp_onceki_durum.get(w, None)
            hp_bekleme_sn = self._hp_bitis_gecikmesi(cc)

            if onceki_hp is True and hp_bekleme_sn > 0:
                if w not in self._hp_kayip_t:
                    self._hp_kayip_t[w] = now
                    return

                if now - self._hp_kayip_t[w] < hp_bekleme_sn:
                    return

            self._hp_kayip_t.pop(w, None)
            self._hp_onceki_durum.pop(w, None)

            if onceki_hp is True:
                log_event(self.st, "info", f"Mob oldu: {w}")
                self._clear_target_click_cooldown(w, cc, now)
                self._son_tiklama_zamani[w] = now
                self._takilma_baslat_t.pop(w, None)
                self._record_kill(w, client_idx)
                if cc.get("oto_loot", True):
                    self._loot_burst_async(w, hwnd, cc, "mob oldu")
            else:
                self._son_tiklama_t[w] = now

            self.dur[w] = "ARANIYOR"
            with self.st.lk:
                if w in self.st.target_memory:
                    self.st.target_memory[w] = {"positions": [], "consecutive_found": 0,
                                                 "confirmed": False, "last_confirmed_pos": None, "misses": 0}

    def _anti_sucuk_cooldown_ready(self, w, now=None, kind="genel"):
        now = now or time.time()
        bekleme = FIXED_ANTI_KURTARMA_BEKLEME_SN
        son = float(self._son_manevra_t.get((w, kind), 0) or 0)
        return bekleme <= 0 or now - son >= bekleme

    def _mark_anti_sucuk_manevra(self, w, when=None, kind="genel"):
        t = when or time.time()
        self._son_manevra_t[(w, kind)] = t
        self._son_hareket_t[w] = t

    def _anti_sucuk_manevra_sureleri(self, w, kind, now=None):
        now = now or time.time()
        son = float(self._son_manevra_t.get((w, kind), 0) or 0)
        tekrar = son > 0 and now - son <= ANTI_SUCUK_REPEAT_WINDOW_SN
        if tekrar:
            return (
                ANTI_SUCUK_BACK_HOLD_REPEAT_SN,
                ANTI_SUCUK_SIDE_HOLD_REPEAT_MIN_SN,
                ANTI_SUCUK_SIDE_HOLD_REPEAT_MAX_SN,
            )
        return (
            ANTI_SUCUK_BACK_HOLD_SN,
            ANTI_SUCUK_SIDE_HOLD_MIN_SN,
            ANTI_SUCUK_SIDE_HOLD_MAX_SN,
        )

    def _anti_sucuk_araniyor_manevra(self, w, hwnd, now):
        if not self._anti_sucuk_cooldown_ready(w, now, "hedef_yoksa"):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_cooldown", f"Anti-sucuk ARANIYOR atlandi: cooldown ({w})", now)
            return False
        if self._s_basmis.get(w, False):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_reentry", f"Anti-sucuk ARANIYOR atlandi: manevra devam ediyor ({w})", now)
            return False
        if self._input_blocked(w):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_input", f"Anti-sucuk ARANIYOR atlandi: input bloklu ({w})", now)
            return False
        self._s_basmis[w] = True
        tus = None
        try:
            pencere_odakla(hwnd)
            back_hold, side_min, side_max = self._anti_sucuk_manevra_sureleri(w, "hedef_yoksa", now)
            keyboard.press('s')
            log_event(self.st, "info", f"Anti-sucuk ARANIYOR: S basili ({w})")
            if self._stop_event.wait(back_hold):
                return False
            keyboard.release('s')
            tus = random.choice(['a', 'd'])
            time.sleep(random.uniform(0.05, 0.20))
            keyboard.press(tus)
            time.sleep(random.uniform(side_min, side_max))
            keyboard.release(tus)
            t = time.time()
            self._araniyor_baslat_t[w] = t
            self._mark_anti_sucuk_manevra(w, t, "hedef_yoksa")
            log_event(self.st, "info", f"Anti-sucuk ARANIYOR: S+{tus.upper()} yapildi ({w})")
            return True
        finally:
            try:
                keyboard.release('s')
                if tus:
                    keyboard.release(tus)
            except Exception:
                pass
            self._s_basmis[w] = False

    def _anti_sucuk_hareketsiz_manevra(self, w, hwnd, now, state="", hp_var=False):
        if not self._anti_sucuk_cooldown_ready(w, now, "hareket_takilirsa"):
            self._anti_sucuk_log_throttled(w, "hareket_takilirsa_cooldown", f"Anti-sucuk HAREKETSIZ atlandi: cooldown ({w})", now)
            return False
        # Re-entry korumasÄ± (manevra zaten devam ediyorsa atla)
        if self._hareketsiz_basmis.get(w, False):
            self._anti_sucuk_log_throttled(w, "hareket_takilirsa_reentry", f"Anti-sucuk HAREKETSIZ atlandi: manevra devam ediyor ({w})", now)
            return False
        if self._input_blocked(w):
            self._anti_sucuk_log_throttled(w, "hareket_takilirsa_input", f"Anti-sucuk HAREKETSIZ atlandi: input bloklu ({w})", now)
            return False
        self._hareketsiz_basmis[w] = True
        tus = None
        try:
            pencere_odakla(hwnd)
            back_hold, side_min, side_max = self._anti_sucuk_manevra_sureleri(w, "hareket_takilirsa", now)
            keyboard.press('s')
            ctx = ""
            if hp_var and state == "SAVASIYOR":
                ctx = " SAVAS/HP"
            elif hp_var and state == "KUYRUK":
                ctx = " KUYRUK/HP"
            log_event(self.st, "info", f"Anti-sucuk HAREKETSIZ{ctx}: S basili ({w})")
            time.sleep(back_hold)
            keyboard.release('s')
            tus = random.choice(['a', 'd'])
            time.sleep(random.uniform(0.05, 0.20))
            keyboard.press(tus)
            time.sleep(random.uniform(side_min, side_max))
            keyboard.release(tus)
            t = time.time()
            self._mark_anti_sucuk_manevra(w, t, "hareket_takilirsa")
            log_event(self.st, "info", f"Anti-sucuk HAREKETSIZ{ctx}: S+{tus.upper()} yapildi ({w})")
            return True
        finally:
            try:
                keyboard.release('s')
                if tus:
                    keyboard.release(tus)
            except Exception:
                pass
            self._hareketsiz_basmis[w] = False

    def run(self):
        while not self._stop_event.is_set():
            if self._stop_event.wait(0.02):
                break
            with self.st.lk:
                aktif = self.st.aktif
                wd = dict(self.st.wdata)
                captcha_cd = dict(self.st.captcha_cd)
                captcha_global_active = self.st.captcha_global_active
                captcha_global_owner = self.st.captcha_global_owner
                message_global_active = self.st.message_global_active
                message_global_owner = self.st.message_global_owner

            if not aktif:
                self.dur.clear(); self.dogr_t.clear(); self.dogr_n.clear()
                self._hp_onceki_durum.clear(); self._son_tiklama_t.clear()
                self._hp_ignore_until.clear(); self._hp_kayip_t.clear()
                self._hedef_kuyruk.clear()
                continue

            if message_global_active or captcha_global_active:
                self._hedef_kuyruk.clear()

            ordered_wd = []
            seen_w = set()
            for ci in (1, 2):
                cw = self.cfg.client(ci).get("pencere", "Yok")
                if cw in wd and cw not in seen_w:
                    ordered_wd.append((cw, wd[cw]))
                    seen_w.add(cw)
            for item in wd.items():
                if item[0] not in seen_w:
                    ordered_wd.append(item)
                    seen_w.add(item[0])
            active_windows = [item[0] for item in ordered_wd]

            for w, data in ordered_wd:
                data_ts = float(data.get("ts", 0) or 0)
                publish_ts = float(data.get("publish_ts", data_ts) or 0)
                data_age = time.time() - (publish_ts or data_ts) if (publish_ts or data_ts) else 999.0
                if data_ts and time.time() - data_ts > 2.0:
                    if w in self._hedef_kuyruk:
                        self._clear_hedef_kuyruk(w)
                        log_event(self.st, "warn", f"[KUYRUK] client goruntusu guncel degil, kuyruk temizlendi ({w})")
                    continue
                if captcha_global_active:
                    self._clear_hedef_kuyruk(w)
                    with self.st.lk:
                        self.st.durum[w] = "CAPTCHA" if w == captcha_global_owner else "CAPTCHA BEKLE"
                        self.st.captcha_block[w] = True
                        self.st.captcha_state[w] = True
                    continue
                if message_global_active:
                    self._clear_hedef_kuyruk(w)
                    with self.st.lk:
                        self.st.durum[w] = "MESAJ" if w == message_global_owner else "MESAJ BEKLE"
                        self.st.captcha_block[w] = True
                        self.st.captcha_state[w] = True
                    continue
                if time.time() < captcha_cd.get(w, 0):
                    self._clear_hedef_kuyruk(w)
                    with self.st.lk:
                        self.st.durum[w] = "CAPTCHA"
                        self.st.captcha_block[w] = True
                        self.st.captcha_state[w] = True
                    continue
                with self.st.lk:
                    if self.st.captcha_block.get(w, False):
                        if time.time() >= self.st.captcha_cd.get(w, 0):
                            self.st.captcha_block[w] = False
                            self.st.captcha_state[w] = False

                now = time.time()
                self._init(w)
                mrk = data.get("merkezler",[])
                hedefler = data.get("hedefler", [])
                hp_var = data.get("hp_var",False)
                ecx,ecy = data.get("ekran_merkez",(0,0))
                ox,oy = data.get("offset",(0,0))
                hwnd = data.get("hwnd")
                cc = data.get("client_cfg",{})
                client_idx = data.get("client_idx")
                ign = cc.get("ignore_radius",35)

                gecerli = [m for m in mrk if np.hypot(m[0]-ecx,m[1]-ecy) > ign]

                with self.st.lk:
                    self.st.durum[w] = self.dur.get(w,"?")

                state = self.dur[w]

                # â”€â”€ GLOBAL HAREKETSÄ°Z KONTROLÃœ (koordinat bazlÄ±) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # EkranÄ±n merkez bÃ¶lgesi X sn boyunca sabit kaldÄ±ysa S+AD yap.
                # Durum, hp_var veya mob varlÄ±ÄŸÄ±ndan tamamen baÄŸÄ±msÄ±z Ã§alÄ±ÅŸÄ±r.
                anti_sucuk_g = bool(self.cfg.g("anti_sucuk"))
                hareketsiz_sn_g = FIXED_ANTI_HAREKETSIZ_SN
                son_hareket_t = float(self._son_hareket_t.get(w, 0) or 0)
                hareket_komutu_yakin = son_hareket_t > 0 and now - son_hareket_t >= 2.0
                hareket_durum_uygun = self._anti_sucuk_state_allowed(state, hp_var)
                hareket_kontrol_aktif = (
                    anti_sucuk_g
                    and hareketsiz_sn_g > 0
                    and hareket_komutu_yakin
                    and hareket_durum_uygun
                )
                if hareket_kontrol_aktif:
                    with self.st.lk:
                        son_sahne = self.st.scene_changed_t.get(w, 0)
                    if son_sahne == 0:
                        # Ä°lk kez â€” sadece baÅŸlangÄ±Ã§ zamanÄ± kaydet, hareket etme
                        with self.st.lk:
                            self.st.scene_changed_t[w] = now
                    elif now - son_sahne > hareketsiz_sn_g:
                        if self._anti_sucuk_hareketsiz_manevra(w, hwnd, now, state, hp_var):
                            # Manevra bitti â€” scene_changed_t'yi gÃ¼ncelle ki tekrar tetiklenmesin
                            with self.st.lk:
                                self.st.scene_changed_t[w] = time.time()
                    else:
                        self._anti_sucuk_log_throttled(w, "scene_moved", f"Anti-sucuk HAREKETSIZ bekliyor: sahne hareketli ({now - son_sahne:.1f}s/{hareketsiz_sn_g}s, {state}, hp={hp_var})", now, interval=5.0)
                else:
                    if anti_sucuk_g and hareket_komutu_yakin and not hareket_durum_uygun:
                        self._anti_sucuk_log_throttled(w, "korumali_durum", f"Anti-sucuk HAREKETSIZ atlandi: durum uygun degil ({state}, hp={hp_var}, {w})", now, interval=5.0)
                    with self.st.lk:
                        self.st.scene_changed_t[w] = now
                # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                try:
                    hedef_kuyruk_aktif = self._hedef_kuyruk_aktif()
                    if not hedef_kuyruk_aktif and (state == "KUYRUK" or self._queue_state_key(w, client_idx) in self._hedef_kuyruk):
                        self._clear_hedef_kuyruk(w, client_idx)
                        self.dur[w] = "ARANIYOR"
                        state = "ARANIYOR"
                    action_ts = publish_ts or data_ts
                    if hedef_kuyruk_aktif and state in ("ARANIYOR", "KUYRUK") and data_age > HEDEF_KUYRUK_FRAME_MAX_AGE:
                        self._hedef_kuyruk_frame_fresh(w, action_ts, now)
                        continue
                    if state == "ARANIYOR":
                        if not hedef_kuyruk_aktif:
                            if not hp_var and not self._default_frame_fresh(w, action_ts, now):
                                continue
                            self._handle_araniyor(w, gecerli, hp_var, ecx, ecy, hwnd, cc, ox, oy, hedefler, action_ts, client_idx=client_idx)
                        else:
                            self._handle_hedef_kuyruk(w, hp_var, cc, hwnd, now, mrk, gecerli, hedefler, ecx, ecy, ox, oy, active_windows, action_ts, client_idx=client_idx)
                    elif state == "KUYRUK":
                        self._handle_hedef_kuyruk(w, hp_var, cc, hwnd, now, mrk, gecerli, hedefler, ecx, ecy, ox, oy, active_windows, action_ts, client_idx=client_idx)
                    elif state == "DOGRULAMA":
                        self._handle_dogrulama(w, hp_var, cc)
                    elif state == "SAVASIYOR":
                        self._handle_savasiyor(w, hp_var, cc, hwnd, now, gecerli, ecx, ecy, ox, oy, client_idx=client_idx)
                except Exception as e:
                    log_event(self.st, "error", f"ActionThread hatasi ({state}): {e}")
                    self.dur[w] = "ARANIYOR"  # gÃ¼venli sÄ±fÄ±rlama

class VisionThread(threading.Thread):
    def __init__(self, cfg, state):
        super().__init__(daemon=True)
        self.cfg, self.st = cfg, state
        self._stop_event = threading.Event()
        self.captcha_w = {1: None, 2: None}
        self.model_cache = {}
        self._captcha_last_log = {}
        self._last_debug_encode = {}
        self._message_last_action = {}
        self._message_last_reply = {}
        self._message_sent_buffer = {}
        self._message_last_ocr = {}
        self._message_last_handled_incoming = {}
        self._message_handled_signatures = {}
        self._message_pending_signature = {}
        self._message_baseline_pending = {}
        self._message_window_answered = {}
        self._message_seen_since = {}
        self._message_open_allowed = {}
        self._message_global_reply_buffer = deque(maxlen=10)
        self._duplicate_window_warn_t = {}
        self._window_issue_last_log = {}
        self._global_pause_last_warn = 0.0
        self._debug_encode_interval = 0.30
        self._hp_frame_counter = {}
        self._started_at = time.time()
        self._hp_templates = {}  # ci â†’ {"gray": template_gray, "edges": template_edges, "w": w, "h": h}
        self._hp_template_cache = {}  # (ci, scale_key) â†’ scaled variant
        self._message_templates = []
        self._message_template_cache = {}
        self._message_notify_last_debug = 0.0
        self._message_notify_best_template_score = 0.0
        self._message_notify_color_candidates = 0
        self._prev_det = {}  # pk â†’ [(cx,cy),...] Ã¶nceki karedeki ham tespitler (ardÄ±ÅŸÄ±k kare doÄŸrulamasÄ± iÃ§in)
        self._prev_target_centers = {}  # pk -> {"ts": float, "centers": [(cx,cy),...]} iki kare hareket filtresi
        self._prev_scene_roi = {}  # pk â†’ son frame'in merkez ROI'si (hareketsiz tespiti iÃ§in)
        self._load_hp_templates()
        self._load_message_templates()
        if CAPTCHA_OK:
            def _mk_cb(st):
                return lambda lvl, msg: log_event(st, lvl, msg)
            self.captcha_w[1] = CaptchaWatcher(client_id=1, log_cb=_mk_cb(self.st))
            self.captcha_w[2] = CaptchaWatcher(client_id=2, log_cb=_mk_cb(self.st))
            log_event(self.st, "info", "Captcha solver yukleniyor")
        else:
            self.captcha_w[1] = None
            self.captcha_w[2] = None
            log_event(self.st, "warn", "captcha_solver.py yuklenemedi")

    def stop(self):
        self._stop_event.set()

    def _load_message_templates(self):
        self._message_templates = []
        self._message_template_cache = {}
        try:
            files = [f for f in os.listdir(MESSAGE_TEMPLATE_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
        except Exception:
            files = []
        for name in sorted(files):
            path = os.path.join(MESSAGE_TEMPLATE_DIR, name)
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                log_event(self.st, "warn", f"Mesaj template okunamadi: {name}")
                continue
            h, w = img.shape[:2]
            if h < 8 or w < 8:
                log_event(self.st, "warn", f"Mesaj template cok kucuk: {name} ({w}x{h})")
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            self._message_templates.append({"name": name, "gray": gray, "edges": edges, "w": w, "h": h})
            log_event(self.st, "info", f"Mesaj template yuklendi: {name} ({w}x{h})")
        if not self._message_templates:
            log_event(self.st, "info", "Mesaj template yok; siki renk filtresi kullanilacak")

    def _get_scaled_message_template(self, tpl, scale):
        key = (tpl.get("name", ""), int(round(scale * 1000)))
        cached = self._message_template_cache.get(key)
        if cached is not None:
            return cached
        if abs(scale - 1.0) < 0.001:
            result = {"gray": tpl["gray"], "edges": tpl["edges"], "w": tpl["w"], "h": tpl["h"], "name": tpl.get("name", "")}
        else:
            tw = max(8, int(round(tpl["w"] * scale)))
            th = max(8, int(round(tpl["h"] * scale)))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            gray = cv2.resize(tpl["gray"], (tw, th), interpolation=interp)
            edges = cv2.resize(tpl["edges"], (tw, th), interpolation=interp)
            result = {"gray": gray, "edges": edges, "w": tw, "h": th, "name": tpl.get("name", "")}
        self._message_template_cache[key] = result
        return result

    def _load_hp_templates(self):
        for ci in [1, 2]:
            tpl_path = os.path.join(HP_TEMPLATE_DIR, f"client_{ci}.png")
            if os.path.exists(tpl_path):
                img = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
                if img is not None and img.size > 0:
                    h, w = img.shape[:2]
                    if h >= 4 and w >= 12:
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        edges = cv2.Canny(gray, 50, 150)
                        self._hp_templates[ci] = {"gray": gray, "edges": edges, "w": w, "h": h}
                        log_event(self.st, "info", f"Client {ci} HP template yuklendi: {w}x{h}")
                    else:
                        log_event(self.st, "warn", f"Client {ci} HP template cok kucuk: {w}x{h}")
                else:
                    log_event(self.st, "warn", f"Client {ci} HP template okunamadi")
            else:
                log_event(self.st, "info", f"Client {ci} HP template yok (once HP bar secin)")

    def _get_scaled_template(self, ci, scale):
        scale_key = int(round(scale * 1000))
        cache_key = (ci, scale_key)
        cached = self._hp_template_cache.get(cache_key)
        if cached is not None:
            return cached
        tpl = self._hp_templates.get(ci)
        if tpl is None:
            return None
        if abs(scale - 1.0) < 0.001:
            result = {"gray": tpl["gray"], "edges": tpl["edges"], "w": tpl["w"], "h": tpl["h"]}
        else:
            tw = max(12, int(round(tpl["w"] * scale)))
            th = max(4, int(round(tpl["h"] * scale)))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            gray = cv2.resize(tpl["gray"], (tw, th), interpolation=interp)
            edges = cv2.Canny(gray, 50, 150)
            result = {"gray": gray, "edges": edges, "w": tw, "h": th}
        self._hp_template_cache[cache_key] = result
        return result

    def _match_hp_template(self, roi, ci):
        tpl = self._hp_templates.get(ci)
        if tpl is None or roi is None or roi.size == 0:
            return {"matched": False, "score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
        roi_h, roi_w = roi.shape[:2]
        if roi_h < 4 or roi_w < 12:
            return {"matched": False, "score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
        best = {"matched": False, "score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_edges = cv2.Canny(roi_gray, 50, 150)
        
        for scale in HP_TEMPLATE_SCALES:
            variant = self._get_scaled_template(ci, scale)
            if variant is None:
                continue
            th, tw = variant["h"], variant["w"]
            if th > roi_h or tw > roi_w or th < 4 or tw < 12:
                continue
            roi_resized = cv2.resize(roi_gray, (tw, th), interpolation=cv2.INTER_AREA)
            score_gray = float(cv2.matchTemplate(roi_resized, variant["gray"], cv2.TM_CCOEFF_NORMED)[0][0])
            
            roi_edges_resized = cv2.resize(roi_edges, (tw, th), interpolation=cv2.INTER_AREA)
            score_edges = float(cv2.matchTemplate(roi_edges_resized, variant["edges"], cv2.TM_CCOEFF_NORMED)[0][0])
            
            score = max(score_gray, score_edges)
            if score > best["score"]:
                best = {"matched": score >= HP_TEMPLATE_MIN_SCORE, "score": score, "x": 0, "y": 0, "w": tw, "h": th}
        return best

    def _unload_ocr(self):
        for ci in [1, 2]:
            cw = self.captcha_w.get(ci)
            if cw:
                with cw._lock:
                    cw._reader = None
                    cw._hazir = False
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _active_client_pks(self):
        keys = []
        for ci in [1, 2]:
            cc = self.cfg.client(ci)
            if not cc.get("aktif", True):
                continue
            pk = cc.get("pencere", "Yok")
            if pk != "Yok":
                keys.append(pk)
        return keys

    def _set_global_pause_state(self, kind, owner_pk, owner_ci=None, reason=""):
        now = time.time()
        with self.st.lk:
            prev_active = self.st.global_pause_active
            prev_kind = self.st.global_pause_kind
            prev_owner = self.st.global_pause_owner
            self.st.global_pause_active = True
            self.st.global_pause_kind = kind
            self.st.global_pause_owner = owner_pk
            self.st.global_pause_reason = reason or kind
            if not self.st.global_pause_since or prev_kind != kind or prev_owner != owner_pk:
                self.st.global_pause_since = now
        if not prev_active or prev_kind != kind or prev_owner != owner_pk:
            label = f"Client {owner_ci}" if owner_ci else owner_pk
            log_event(self.st, "warn", f"[PAUSE] {kind} aktif: owner={label} reason={reason or kind}")

    def _clear_global_pause_state(self, kind=None, reason=""):
        with self.st.lk:
            if kind and self.st.global_pause_kind != kind:
                return False
            was_active = self.st.global_pause_active
            old_kind = self.st.global_pause_kind
            self.st.global_pause_active = False
            self.st.global_pause_kind = ""
            self.st.global_pause_owner = None
            self.st.global_pause_reason = ""
            self.st.global_pause_since = 0.0
        if was_active:
            suffix = f": {reason}" if reason else ""
            log_event(self.st, "info", f"[PAUSE] {old_kind} temizlendi{suffix}")
        return was_active

    def _log_window_issue(self, ci, pk, issue, message):
        key = (ci, pk, issue)
        now = time.time()
        if now - self._window_issue_last_log.get(key, 0) >= WINDOW_ISSUE_LOG_INTERVAL:
            log_event(self.st, "warn", message)
            self._window_issue_last_log[key] = now

    def _watch_global_pause(self):
        with self.st.lk:
            active = self.st.global_pause_active
            since = self.st.global_pause_since
            kind = self.st.global_pause_kind
            owner = self.st.global_pause_owner
            reason = self.st.global_pause_reason
        if not active or not since:
            return
        now = time.time()
        elapsed = now - since
        if elapsed >= GLOBAL_PAUSE_WARN_AFTER and now - self._global_pause_last_warn >= GLOBAL_PAUSE_WARN_EVERY:
            log_event(self.st, "warn", f"[PAUSE] {kind} {elapsed:.0f}s devam ediyor owner={owner} reason={reason}")
            self._global_pause_last_warn = now

    def _set_global_captcha(self, owner_pk, owner_ci=None, reason="CAPTCHA"):
        self._set_global_pause_state("CAPTCHA", owner_pk, owner_ci, reason)
        active_keys = self._active_client_pks()
        now = time.time()
        should_log = False
        with self.st.lk:
            prev_active = self.st.captcha_global_active
            prev_owner = self.st.captcha_global_owner
            self.st.captcha_global_active = True
            self.st.captcha_global_owner = owner_pk
            if not self.st.captcha_global_since:
                self.st.captcha_global_since = now
            for pk in active_keys:
                self.st.captcha_block[pk] = True
                self.st.captcha_state[pk] = True
                self.st.durum[pk] = "CAPTCHA" if pk == owner_pk else "CAPTCHA BEKLE"
            should_log = (not prev_active) or (prev_owner != owner_pk)
        if should_log:
            label = f"Client {owner_ci}" if owner_ci else owner_pk
            log_event(self.st, "warn", f"{label} captcha global blok aktif: {reason}")

    def _clear_global_captcha(self, reason=""):
        active_keys = self._active_client_pks()
        now = time.time()
        with self.st.lk:
            was_active = self.st.captcha_global_active
            self.st.captcha_global_active = False
            self.st.captcha_global_owner = None
            self.st.captcha_global_since = 0.0
            message_active = self.st.message_global_active
            message_owner = self.st.message_global_owner
            message_since = self.st.message_global_since
            for pk in active_keys:
                if message_active:
                    self.st.captcha_block[pk] = True
                    self.st.captcha_state[pk] = True
                    self.st.durum[pk] = "MESAJ" if pk == message_owner else "MESAJ BEKLE"
                elif now >= self.st.captcha_cd.get(pk, 0):
                    self.st.captcha_block[pk] = False
                    self.st.captcha_state[pk] = False
                    if self.st.durum.get(pk) in ("CAPTCHA", "CAPTCHA BEKLE", "CAPTCHA OCR"):
                        self.st.durum[pk] = "BEKLIYOR"
            if message_active:
                self.st.global_pause_active = True
                self.st.global_pause_kind = "MESAJ"
                self.st.global_pause_owner = message_owner
                self.st.global_pause_reason = "captcha temizlendi, mesaj bekliyor"
                self.st.global_pause_since = message_since or now
        if was_active:
            suffix = f": {reason}" if reason else ""
            log_event(self.st, "info", f"Captcha global blok temizlendi{suffix}")
        if not message_active:
            self._clear_global_pause_state("CAPTCHA", reason)

    def _message_captcha_enabled(self, cc):
        if "message_captcha" in cc:
            return bool(cc.get("message_captcha"))
        global_value = self.cfg.g("message_captcha")
        return True if global_value is None else bool(global_value)

    def _message_key(self, ci, pk):
        return f"{int(ci)}::{pk}"

    def _warn_duplicate_client_windows(self):
        pairs = []
        for ci in (1, 2):
            cc = self.cfg.client(ci)
            if not cc.get("aktif", True):
                continue
            pk = cc.get("pencere", "Yok")
            if pk != "Yok":
                pairs.append((ci, pk))
        seen = {}
        now = time.time()
        for ci, pk in pairs:
            if pk not in seen:
                seen[pk] = ci
                continue
            key = pk
            if now - self._duplicate_window_warn_t.get(key, 0) >= 15.0:
                log_event(self.st, "error", f"Client {seen[pk]} ve Client {ci} ayni pencereye bagli: {pk}")
                self._duplicate_window_warn_t[key] = now

    def _set_global_message(self, owner_pk, owner_ci=None, reason="MESAJ"):
        self._set_global_pause_state("MESAJ", owner_pk, owner_ci, reason)
        active_keys = self._active_client_pks()
        now = time.time()
        should_log = False
        with self.st.lk:
            prev_active = self.st.message_global_active
            prev_owner = self.st.message_global_owner
            self.st.message_global_active = True
            self.st.message_global_owner = owner_pk
            if not self.st.message_global_since:
                self.st.message_global_since = now
            for pk in active_keys:
                self.st.captcha_block[pk] = True
                self.st.captcha_state[pk] = True
                self.st.durum[pk] = "MESAJ" if pk == owner_pk else "MESAJ BEKLE"
            should_log = (not prev_active) or (prev_owner != owner_pk)
        if should_log:
            label = f"Client {owner_ci}" if owner_ci else owner_pk
            log_event(self.st, "warn", f"{label} [MESAJ] global blok aktif: {reason}")

    def _clear_global_message(self, reason=""):
        active_keys = self._active_client_pks()
        now = time.time()
        with self.st.lk:
            was_active = self.st.message_global_active
            self.st.message_global_active = False
            self.st.message_global_owner = None
            self.st.message_global_since = 0.0
            captcha_active = self.st.captcha_global_active
            captcha_owner = self.st.captcha_global_owner
            captcha_since = self.st.captcha_global_since
            for pk in active_keys:
                if captcha_active:
                    self.st.captcha_block[pk] = True
                    self.st.captcha_state[pk] = True
                    self.st.durum[pk] = "CAPTCHA" if pk == captcha_owner else "CAPTCHA BEKLE"
                elif now < self.st.captcha_cd.get(pk, 0):
                    self.st.captcha_block[pk] = True
                    self.st.captcha_state[pk] = True
                    self.st.durum[pk] = "CAPTCHA"
                else:
                    self.st.captcha_block[pk] = False
                    self.st.captcha_state[pk] = False
                    if self.st.durum.get(pk) in ("MESAJ", "MESAJ BEKLE"):
                        self.st.durum[pk] = "BEKLIYOR"
            if captcha_active:
                self.st.global_pause_active = True
                self.st.global_pause_kind = "CAPTCHA"
                self.st.global_pause_owner = captcha_owner
                self.st.global_pause_reason = "mesaj temizlendi, captcha bekliyor"
                self.st.global_pause_since = captcha_since or now
        if was_active:
            suffix = f": {reason}" if reason else ""
            log_event(self.st, "info", f"[MESAJ] global blok temizlendi{suffix}")
        if not captcha_active:
            self._clear_global_pause_state("MESAJ", reason)

    def _detect_message_notification(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return None
        x1, y1 = int(w * 0.86), int(h * 0.18)
        x2, y2 = w, int(h * 0.55)
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        template_hit = self._detect_message_notification_template(roi, x1, y1)
        if template_hit:
            return template_hit
        color_hit = self._detect_message_notification_color(roi, x1, y1, w)
        if color_hit:
            return color_hit
        now = time.time()
        if now - self._message_notify_last_debug > 3.0:
            log_event(
                self.st,
                "debug",
                "Mesaj bildirimi yok: "
                f"roi=({x1},{y1},{x2},{y2}) "
                f"template={self._message_notify_best_template_score:.2f} "
                f"renk_aday={self._message_notify_color_candidates}",
            )
            self._message_notify_last_debug = now
        return None

    def _detect_message_notification_template(self, roi, ox=0, oy=0):
        if not self._message_templates:
            self._message_notify_best_template_score = 0.0
            return None
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_edges = cv2.Canny(roi_gray, 50, 150)
        rh, rw = roi_gray.shape[:2]
        best = None
        best_score = 0.0
        for tpl in self._message_templates:
            for scale in MESSAGE_TEMPLATE_SCALES:
                variant = self._get_scaled_message_template(tpl, scale)
                tw, th = int(variant["w"]), int(variant["h"])
                if tw > rw or th > rh:
                    continue
                score_gray = cv2.matchTemplate(roi_gray, variant["gray"], cv2.TM_CCOEFF_NORMED)
                _, max_gray, _, loc_gray = cv2.minMaxLoc(score_gray)
                score_edges = cv2.matchTemplate(roi_edges, variant["edges"], cv2.TM_CCOEFF_NORMED)
                _, max_edges, _, loc_edges = cv2.minMaxLoc(score_edges)
                if max_edges > max_gray:
                    score, loc = float(max_edges), loc_edges
                else:
                    score, loc = float(max_gray), loc_gray
                best_score = max(best_score, float(score))
                if score < MESSAGE_TEMPLATE_MIN_SCORE:
                    continue
                x, y = int(loc[0]), int(loc[1])
                cx, cy = ox + x + tw // 2, oy + y + th // 2
                if best is None or score > best["score"]:
                    best = {
                        "x": int(cx), "y": int(cy), "area": int(tw * th), "score": float(score),
                        "template": variant.get("name", ""), "mode": "template",
                    }
        self._message_notify_best_template_score = best_score
        return best

    def _detect_message_notification_color(self, roi, ox=0, oy=0, full_w=0):
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([16, 70, 110]), np.array([48, 255, 255]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 7), np.uint8))
        mask = cv2.dilate(mask, np.ones((3, 5), np.uint8), iterations=1)
        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if area < 70 or area > 2500:
                continue
            if ww < 8 or hh < 10 or ww > 90 or hh > 90:
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.08 or fill > 1.0:
                continue
            abs_x = int(x) + ox
            if full_w and abs_x < int(full_w * 0.86):
                continue
            cx = float(cents[i][0]) + ox
            cy = float(cents[i][1]) + oy
            right_bias = (float(cx) / float(max(full_w, 1))) * 220.0 if full_w else 0.0
            score = float(area) + float(hh * 12) + float(ww * 2) + right_bias
            candidates.append({"x": int(cx), "y": int(cy), "area": int(area), "score": score, "mode": "color"})
        self._message_notify_color_candidates = len(candidates)
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.get("score", 0))

    def _detect_message_window(self, img):
        if img is None or img.size == 0:
            return False
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return False
        x1, y1, x2, y2 = int(w * 0.04), int(h * 0.10), int(w * 0.26), int(h * 0.34)
        roi = img[y1:y2, x1:x2]
        ix1, iy1, ix2, iy2 = int(w * 0.045), int(h * 0.255), int(w * 0.235), int(h * 0.31)
        input_roi = img[iy1:iy2, ix1:ix2]
        if roi.size == 0 or input_roi.size == 0:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        input_gray = cv2.cvtColor(input_roi, cv2.COLOR_BGR2GRAY)
        dark_ratio = float(np.mean(gray < 65))
        input_dark = float(np.mean(input_gray < 55))
        if dark_ratio > 0.55 and input_dark > 0.45:
            return True
        return self._detect_message_input_focus_point(img) is not None

    def _detect_message_send_button(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        if h < 180 or w < 300:
            return None
        search_w = int(w * (0.92 if w < 800 else 0.68))
        search_h = int(h * (0.88 if h < 650 else 0.50))
        roi = img[:max(1, search_h), :max(1, search_w)]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        red1 = cv2.inRange(hsv, np.array([0, 80, 70]), np.array([18, 255, 255]))
        red2 = cv2.inRange(hsv, np.array([165, 80, 70]), np.array([180, 255, 255]))
        mask = cv2.bitwise_or(red1, red2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        min_x = int(w * (0.20 if w < 800 else 0.24))
        max_x = int(w * (0.90 if w < 800 else 0.60))
        min_y = int(h * 0.18)
        max_y = int(h * (0.86 if h < 650 else 0.42))
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if ww < 36 or ww > 95 or hh < 22 or hh > 58:
                continue
            if x < min_x or x > max_x or y < min_y or y > max_y:
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.25 or fill > 0.92:
                continue
            score = float(area) + float(ww * 6) + float(hh * 4)
            candidates.append((score, int(x), int(y), int(ww), int(hh)))
        if not candidates:
            return None
        _score, x, y, ww, hh = max(candidates, key=lambda item: item[0])
        return x, y, ww, hh

    def _detect_message_input_focus_point(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        button = self._detect_message_send_button(img)
        if button:
            x, y, ww, hh = button
            click_x = int(max(8, x - (w * 0.29)))
            click_y = int(y + (hh * 0.50))
            return click_x, click_y, "button"

        search_w = int(w * (0.92 if w < 800 else 0.68))
        search_h = int(h * (0.88 if h < 650 else 0.50))
        roi = img[:max(1, search_h), :max(1, search_w)]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        dark = cv2.inRange(gray, 0, 85)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((7, 23), np.uint8))
        n, _labels, stats, _cents = cv2.connectedComponentsWithStats(dark, 8)
        candidates = []
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if ww < max(90, int(w * 0.20)) or ww > int(w * 0.68):
                continue
            if hh < max(18, int(h * 0.035)) or hh > int(h * 0.16):
                continue
            if x > int(w * 0.28):
                continue
            if y < int(h * 0.18) or y > int(h * (0.86 if h < 650 else 0.46)):
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.25:
                continue
            candidates.append((int(y), int(area), int(x), int(ww), int(hh)))
        if not candidates:
            return None
        y, _area, x, ww, hh = max(candidates, key=lambda item: (item[0], item[1]))
        click_x = int(x + min(max(22, ww * 0.10), ww * 0.35))
        click_y = int(y + (hh * 0.50))
        return click_x, click_y, "input"

    def _message_chat_roi(self, img):
        if img is None or img.size == 0:
            return None, (0, 0)
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return None, (0, 0)
        x1, y1 = int(w * 0.04), int(h * 0.17)
        x2, y2 = int(w * 0.90), int(h * 0.79)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None, (0, 0)
        roi = img[y1:y2, x1:x2]
        return roi, (x1, y1)

    def _message_yellow_line_bands(self, yellow):
        if yellow is None or yellow.size == 0:
            return []
        expanded = cv2.dilate(yellow, np.ones((2, 5), np.uint8), iterations=1)
        row_counts = np.count_nonzero(expanded, axis=1)
        rows = np.where(row_counts >= 3)[0]
        if len(rows) == 0:
            return []
        bands = []
        start = prev = int(rows[0])
        for raw_y in rows[1:]:
            y = int(raw_y)
            if y - prev <= 3:
                prev = y
                continue
            if prev - start >= 4:
                bands.append((start, prev))
            start = prev = y
        if prev - start >= 4:
            bands.append((start, prev))
        return bands

    def _message_line_signature(self, text, y_center):
        clean = self._clean_message_text(text).lower()
        times = re.findall(r"\[(\d{1,2}:\d{2})\]", clean)
        clean = re.sub(r"\[\d{1,2}:\d{2}\]", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return {
            "text": clean,
            "time": times[-1] if times else "",
            "y": int(round(float(y_center) / 14.0) * 14),
        }

    def _message_signature_seen(self, pk, sig):
        if not sig or not sig.get("text"):
            return True
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        sig_text = sig.get("text", "")
        sig_time = sig.get("time", "")
        for old in seen:
            old_text = old.get("text", "") if isinstance(old, dict) else str(old)
            old_time = old.get("time", "") if isinstance(old, dict) else ""
            old_y = int(old.get("y", 0) or 0) if isinstance(old, dict) else 0
            sim = self._message_text_similarity(sig_text, old_text)
            if sig_time and old_time and sig_time != old_time:
                continue
            if sim >= 0.96:
                return True
            if abs(int(sig.get("y", 0)) - old_y) <= 18 and sim >= 0.90:
                return True
        return False

    def _message_content_text(self, text):
        clean = self._clean_message_text(text)
        clean = re.sub(r"\[\d{1,2}:\d{2}\]", " ", clean)
        clean = re.sub(r"^\s*\[[^\]]+\]\s*", " ", clean)
        clean = re.sub(r"^\s*[A-Za-z0-9_ğüşöçıİĞÜŞÖÇ\[\]\-]+(?:\s*\(Lv\.?\s*\d+\))?\s*[:;]\s*", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" :;.-")
        return clean

    def _is_system_message_line(self, text):
        low = self._clean_message_text(text).lower()
        normalized = _normalize_outgoing_text(low)
        ascii_norm = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
        system_phrases = (
            "bağlı değil", "bagli degil", "baqli deyil", "bağli degil",
            "offline", "not connected", "disconnected", "çevrimdışı", "cevrimdisi",
            "connected değil", "bagli deil",
        )
        if any(p in normalized for p in system_phrases) or any(p in ascii_norm for p in ("bagli degil", "bagli deil", "cevrimdisi")):
            return True
        return bool(re.search(r"\bba[ğgq]l[ıi]\b.{0,12}\bde[ğgq]il\b", normalized) or re.search(r"\bbagli\b.{0,12}\bdegil\b", ascii_norm))

    def _is_valid_incoming_message_line(self, text):
        clean = self._clean_message_text(text)
        if not clean:
            return False, "bos"
        if self._is_system_message_line(clean):
            return False, "sistem satiri"
        content = self._message_content_text(clean)
        if not content:
            return False, "icerik yok"
        low = content.lower()
        if len(low) < 2 and "?" not in low:
            return False, "cok kisa"
        if not re.search(r"[a-zA-Z0-9ğüşöçıİĞÜŞÖÇ]", low) and "?" not in low:
            return False, "anlamsiz"
        if re.fullmatch(r"\?+", low.strip()):
            return True, ""
        if re.fullmatch(r"[\[\]\(\)\-_:;.,!?\s]+", low):
            return False, "anlamsiz"
        return True, ""

    def _read_yellow_message_lines(self, ci, pk, img, include_seen=False):
        cw = self._message_ocr_reader(ci)
        if not cw:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: OCR hazir degil")
            return []
        roi, _ = self._message_chat_roi(img)
        if roi is None or roi.size == 0:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: ROI yok")
            return []
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, np.array([12, 55, 95]), np.array([45, 255, 255]))
        yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        if int(cv2.countNonZero(yellow)) < 18:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: sari satir yok")
            return []
        bands = self._message_yellow_line_bands(yellow)
        if not bands:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: sari band yok")
            return []
        candidates = []
        pad_x, pad_y = 6, 4
        for y1, y2 in sorted(bands, key=lambda b: b[1], reverse=True):
            band_mask = yellow[max(0, y1 - pad_y):min(yellow.shape[0], y2 + pad_y + 1), :]
            ys, xs = np.where(band_mask > 0)
            if len(xs) < 18:
                continue
            x1 = max(0, int(xs.min()) - pad_x)
            x2 = min(yellow.shape[1], int(xs.max()) + pad_x)
            cy_abs = (float(y1) + float(y2)) / 2.0
            crop_mask = yellow[max(0, y1 - pad_y):min(yellow.shape[0], y2 + pad_y + 1), x1:x2]
            if crop_mask.size == 0:
                continue
            crop = np.zeros_like(crop_mask)
            crop[crop_mask > 0] = 255
            large = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            try:
                with cw._lock:
                    reader = cw._reader
                    if not reader:
                        return []
                    results = reader.readtext(large, detail=1, paragraph=False)
            except Exception:
                continue
            pieces = []
            total_conf = 0.0
            for item in results or []:
                try:
                    text, conf = item[1], float(item[2])
                except Exception:
                    continue
                clean = self._clean_message_text(text)
                if not clean or conf < MESSAGE_OCR_MIN_CONF:
                    continue
                pieces.append(clean)
                total_conf += conf
            text = self._clean_message_text(" ".join(pieces))
            if not text:
                continue
            valid, reason = self._is_valid_incoming_message_line(text)
            if not valid:
                log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: {reason} {text}")
                continue
            sig = self._message_line_signature(text, cy_abs)
            if not include_seen and self._message_signature_seen(pk, sig):
                log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: tekrar satir {text}")
                continue
            candidates.append({"text": text, "sig": sig, "y": cy_abs, "conf": total_conf / max(len(pieces), 1)})
        return candidates

    def _prime_message_yellow_baseline(self, ci, pk, img):
        lines = self._read_yellow_message_lines(ci, pk, img, include_seen=True)
        if not lines:
            return False
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        for line in lines:
            sig = line.get("sig")
            if sig and not self._message_signature_seen(pk, sig):
                seen.append(sig)
        log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] baseline sari satir: {len(lines)}")
        return True

    def _mark_visible_yellow_messages_handled(self, ci, pk, img):
        lines = self._read_yellow_message_lines(ci, pk, img, include_seen=True)
        if not lines:
            return
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        added = 0
        for line in lines:
            sig = line.get("sig")
            if sig and not self._message_signature_seen(pk, sig):
                seen.append(sig)
                added += 1
        if added:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] gorunen sari satir islendi: {added}")

    def _message_ocr_reader(self, ci):
        cw = self.captcha_w.get(ci)
        if not cw or not getattr(cw, "hazir", False):
            return None
        return cw

    def _capture_window_image(self, hwnd):
        if not hwnd:
            return None
        try:
            r = win32gui.GetWindowRect(hwnd)
            if r[0] < -32000 or r[2] <= r[0] or r[3] <= r[1]:
                return None
            with mss.mss() as sct:
                shot = np.array(sct.grab({
                    "left": int(r[0]),
                    "top": int(r[1]),
                    "width": int(r[2] - r[0]),
                    "height": int(r[3] - r[1])
                }), dtype=np.uint8)
            return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def _clean_message_text(self, text):
        text = _normalize_outgoing_text(str(text or ""))
        text = text.replace("\n", " ").replace("\r", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _message_text_similarity(self, a, b):
        aa = self._clean_message_text(a).lower()
        bb = self._clean_message_text(b).lower()
        if not aa or not bb:
            return 0.0
        return difflib.SequenceMatcher(None, aa, bb).ratio()

    def _is_self_message_text(self, pk, text):
        clean = self._clean_message_text(text)
        low = clean.lower()
        if any(low.startswith(prefix) for prefix in MESSAGE_SELF_NAME_PREFIXES):
            return True
        now = time.time()
        buf = list(self._message_sent_buffer.get(pk, []))
        for item in buf:
            sent_text = item.get("text", "") if isinstance(item, dict) else str(item)
            sent_ts = float(item.get("ts", 0) or 0) if isinstance(item, dict) else 0.0
            if sent_ts and now - sent_ts > max(30.0, MESSAGE_SELF_ECHO_SECONDS):
                continue
            if self._message_text_similarity(clean, sent_text) >= MESSAGE_SELF_ECHO_SIMILARITY:
                return True
        return False

    def _extract_incoming_message_text(self, ci, pk, img):
        candidates = self._read_yellow_message_lines(ci, pk, img, include_seen=False)
        if not candidates:
            return None
        selected = sorted(candidates, key=lambda item: item["y"], reverse=True)[0]
        text = selected["text"]
        self._message_pending_signature[pk] = selected["sig"]
        self._message_last_ocr[pk] = {"text": text, "ts": time.time(), "sig": selected["sig"]}
        log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] yeni sari satir: {text}")
        return text

    def _message_language(self, text):
        low = self._clean_message_text(text).lower()
        tr_chars = set("çğıöşü")
        tr_words = ("selam", "sa", "teşekkür", "tesekkur", "yardım", "yardim", "mı", "mi", "nasıl", "nasil", "kanka", "abi")
        en_words = ("hello", "hi", "thanks", "thank", "help", "how", "you", "what", "ok", "yes", "no")
        tr_score = sum(1 for ch in low if ch in tr_chars) + sum(1 for w in tr_words if w in low)
        en_score = sum(1 for w in en_words if re.search(rf"\b{re.escape(w)}\b", low))
        if en_score > tr_score:
            return "en"
        if tr_score > 0:
            return "tr"
        return "unknown"

    def _choose_contextual_message_reply(self, pk, incoming_text=None):
        text = self._clean_message_text(incoming_text)
        if not text:
            return self._choose_message_reply(pk)
        low = text.lower()
        lang = self._message_language(text)
        if any(w in low for w in ("bot", "auto", "macro", "otomatik")):
            replies = ["no, I am here", "I am here", "no bot"] if lang == "en" else ["buradayım", "hayır buradayım", "burdayım"]
        elif any(w in low for w in ("thank", "thanks", "ty", "teşekkür", "tesekkur", "sağol", "sagol")):
            replies = ["you're welcome", "no problem", "ok, no problem"] if lang == "en" else ["rica ederim", "sorun değil", "tamam sorun yok"]
        elif any(re.search(rf"\b{re.escape(w)}\b", low) for w in ("hello", "hi", "hey", "selam", "merhaba", "sa")):
            replies = ["hello, how can I help", "hi, I am here", "hello"] if lang == "en" else ["selam, nasıl yardımcı olayım", "selam buradayım", "merhaba"]
        elif any(w in low for w in ("help", "how can", "yardım", "yardim", "soru")) or "?" in low:
            replies = ["how can I help", "what do you need", "tell me"] if lang == "en" else ["nasıl yardımcı olayım", "ne lazım", "söyle"]
        elif lang == "en":
            replies = ["ok", "one sec", "I am here", "yes"]
        elif lang == "tr":
            replies = ["tamam", "buradayım", "dinliyorum", "evet"]
        else:
            replies = ["ok", "one sec", "I'm here", "yes"]
        return self._pick_message_reply(pk, replies)

    def _pick_message_reply(self, pk, replies):
        replies = [str(r).strip() for r in (replies or []) if str(r).strip()]
        if not replies:
            replies = ["ok"]
        last_local = self._message_last_reply.get(pk)
        global_recent = set(self._message_global_reply_buffer)
        choices = [r for r in replies if r != last_local and r not in global_recent]
        if not choices:
            choices = [r for r in replies if r != last_local]
        if not choices:
            choices = replies
        reply = random.choice(choices)
        self._message_last_reply[pk] = reply
        self._message_global_reply_buffer.append(reply)
        return reply

    def _choose_message_reply(self, pk):
        replies = [r for r in MESSAGE_REPLY_TEXTS if str(r).strip()]
        if not replies:
            return "selam"
        return self._pick_message_reply(pk, replies)

    def _focus_message_input(self, img, ox, oy, hwnd):
        if img is None or img.size == 0:
            return False
        h, w = img.shape[:2]
        if hwnd:
            pencere_odakla(hwnd)
        focus = self._detect_message_input_focus_point(img)
        if focus:
            fx, fy, mode = focus
            input_x = ox + int(fx)
            input_y = oy + int(fy)
            log_event(self.st, "debug", f"[MESAJ] input odak noktasi: {mode} ({int(fx)},{int(fy)})")
        else:
            input_x = ox + int(w * 0.145)
            input_y = oy + int(h * 0.323)
            log_event(self.st, "debug", "[MESAJ] input odak fallback")
        sol_tik_hw(input_x, input_y, hwnd)
        time.sleep(0.18)
        return True

    def _send_message_reply(self, img, ox, oy, hwnd, notification=None, reply_text=None):
        h, w = img.shape[:2]
        if hwnd:
            pencere_odakla(hwnd)
        if notification:
            sol_tik_hw(ox + notification["x"], oy + notification["y"], hwnd)
            time.sleep(0.45)
        else:
            self._focus_message_input(img, ox, oy, hwnd)
        return _paste_text_and_enter(reply_text or self._choose_message_reply(hwnd or ""), hwnd)

    def _set_message_farm_pause(self, ci, pk, seconds=MESSAGE_FARM_PAUSE_SECONDS):
        until = time.time() + float(seconds)
        with self.st.lk:
            self.st.message_farm_pause_until[pk] = until
        log_event(self.st, "warn", f"Client {ci} [MESAJ] farm 5 dk duraklatildi")

    def _message_farm_pause_remaining(self, pk, now=None):
        now = now or time.time()
        with self.st.lk:
            until = float(self.st.message_farm_pause_until.get(pk, 0) or 0)
            if until <= now:
                if pk in self.st.message_farm_pause_until:
                    self.st.message_farm_pause_until.pop(pk, None)
                return 0.0
            return until - now

    def _handle_message_request(self, ci, pk, img, ox, oy, hwnd, cc):
        mk = self._message_key(ci, pk)
        if not self._message_captcha_enabled(cc):
            return False
        if time.time() - self._started_at < 1.0:
            self._message_seen_since.pop(mk, None)
            return False
        window_open = self._detect_message_window(img)
        notification = None if window_open else self._detect_message_notification(img)
        if not window_open:
            self._message_window_answered[mk] = False
            if not notification:
                self._message_open_allowed[mk] = False
        if notification:
            first_seen = self._message_seen_since.get(mk)
            now_seen = time.time()
            if first_seen is None:
                self._message_seen_since[mk] = now_seen
                return True
            if now_seen - first_seen < 0.75:
                return True
        else:
            self._message_seen_since.pop(mk, None)
        answered_open = bool(window_open and self._message_window_answered.get(mk, False))
        if not notification and (not window_open or (not self._message_open_allowed.get(mk, False) and not answered_open)):
            return False
        pre_incoming_text = None
        if answered_open and not notification:
            baseline_since = float(self._message_baseline_pending.get(mk, 0) or 0)
            if baseline_since:
                if self._prime_message_yellow_baseline(ci, mk, img):
                    self._message_baseline_pending.pop(mk, None)
                    return False
                if time.time() - baseline_since < 2.0:
                    return False
                self._message_baseline_pending.pop(mk, None)
                return False
            pre_incoming_text = self._extract_incoming_message_text(ci, mk, img)
            if not pre_incoming_text:
                return False
        now = time.time()
        if now - self._message_last_action.get(mk, 0) < MESSAGE_ACTION_COOLDOWN:
            return True

        reason = "bildirim" if notification else "pencere acik"
        self._set_global_message(pk, ci, reason)
        ok = False
        try:
            if notification:
                incoming_text = None
                reply_text = self._choose_message_reply(mk)
                ok = self._send_message_reply(img, ox, oy, hwnd, notification, reply_text)
            else:
                incoming_text = pre_incoming_text or self._extract_incoming_message_text(ci, mk, img)
                reply_text = self._choose_contextual_message_reply(mk, incoming_text)
                ok = self._send_message_reply(img, ox, oy, hwnd, None, reply_text)
            self._message_last_action[mk] = time.time()
            if notification:
                self._message_open_allowed[mk] = True
            if ok:
                buf = self._message_sent_buffer.setdefault(mk, deque(maxlen=5))
                buf.append({"text": reply_text, "ts": time.time()})
                if incoming_text:
                    self._message_last_handled_incoming[mk] = incoming_text
                    pending_sig = self._message_pending_signature.pop(mk, None)
                    if pending_sig:
                        self._message_handled_signatures.setdefault(mk, deque(maxlen=24)).append(pending_sig)
                    self._mark_visible_yellow_messages_handled(ci, mk, img)
                self._message_window_answered[mk] = True
                self._message_seen_since.pop(mk, None)
                self._message_open_allowed[mk] = True
                if notification:
                    fresh_img = self._capture_window_image(hwnd)
                    if fresh_img is not None and fresh_img.size:
                        self._mark_visible_yellow_messages_handled(ci, mk, fresh_img)
                    else:
                        self._message_baseline_pending[mk] = time.time()
                self._set_message_farm_pause(ci, pk)
                log_event(self.st, "warn", f"Client {ci} [MESAJ] yanit gonderildi")
            else:
                log_event(self.st, "warn", f"Client {ci} [MESAJ] yazi gonderilemedi")
        finally:
            time.sleep(0.25)
            self._clear_global_message("yanitlandi" if ok else "deneme bitti")
        return True

    def run(self):
        try:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            with self.st.lk: self.st.cihaz = dev
            log_event(self.st, "info", f"Vision cihazi: {dev}")
        except:
            return

        _sct = mss.mss()

        while not self._stop_event.is_set():
            loop_start = time.time()

            with self.st.lk:
                aktif = self.st.aktif

            if not aktif:
                with self.st.lk:
                    self.st.captcha_global_active = False
                    self.st.captcha_global_owner = None
                    self.st.captcha_global_since = 0.0
                    self.st.message_global_active = False
                    self.st.message_global_owner = None
                    self.st.message_global_since = 0.0
                    self.st.global_pause_active = False
                    self.st.global_pause_kind = ""
                    self.st.global_pause_owner = None
                    self.st.global_pause_reason = ""
                    self.st.global_pause_since = 0.0
                    self.st.message_farm_pause_until.clear()
                    for pk in list(self.st.captcha_block.keys()):
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                if self._stop_event.wait(0.1):
                    break
                continue

            with self.st.lk:
                global_active = self.st.captcha_global_active
                global_owner = self.st.captcha_global_owner
                message_active = self.st.message_global_active
                message_owner = self.st.message_global_owner
            active_client_pks = self._active_client_pks()
            if global_active and global_owner and global_owner not in active_client_pks:
                self._clear_global_captcha("owner inactive")
            if message_active and message_owner and message_owner not in active_client_pks:
                self._clear_global_message("owner inactive")
            self._watch_global_pause()

            guncel = {}
            with self.st.lk:
                b64_frames = dict(self.st.frame_b64)
            active_keys = set()
            self._warn_duplicate_client_windows()

            for ci in [1,2]:
                cc = self.cfg.client(ci)
                if not cc.get("aktif", True):
                    continue
                pk = cc.get("pencere","Yok")
                if pk == "Yok": continue
                active_keys.add(pk)

                hwnd = hwnd_al(pk)
                mon = _sct.monitors[1]; ox,oy = 0,0
                if hwnd:
                    try: r = win32gui.GetWindowRect(hwnd)
                    except:
                        self._log_window_issue(ci, pk, "getrect", f"Client {ci} GetWindowRect basarisiz: {pk}")
                        with self.st.lk:
                            self.st.durum[pk] = "PENCERE HATA"
                        continue
                    if r[0] < -32000:
                        self._log_window_issue(ci, pk, "minimized", f"Client {ci} pencere minimize: {pk}")
                        with self.st.lk:
                            self.st.durum[pk] = "PENCERE MINIMIZE"
                        continue
                    ox,oy = r[0],r[1]
                    mon = {"top":r[1],"left":r[0],"width":r[2]-r[0],"height":r[3]-r[1]}
                else:
                    self._log_window_issue(ci, pk, "hwnd", f"Client {ci} hwnd bulunamadi: {pk}")
                    with self.st.lk:
                        self.st.durum[pk] = "PENCERE YOK"

                ecx, ecy = mon["width"]//2, mon["height"]//2
                hp_region = cc.get("hp_region", [0.02, 0.07, 0.30, 0.70])
                y1h = int(hp_region[0] * mon["height"])
                y2h = int(hp_region[1] * mon["height"])
                x1h = int(hp_region[2] * mon["width"])
                x2h = int(hp_region[3] * mon["width"])
                try: img = cv2.cvtColor(np.array(_sct.grab(mon),dtype=np.uint8), cv2.COLOR_BGRA2BGR)
                except:
                    self._log_window_issue(ci, pk, "capture", f"Client {ci} ekran capture basarisiz")
                    with self.st.lk:
                        self.st.durum[pk] = "CAPTURE HATA"
                    continue

                # â”€â”€ KOORDÄ°NAT BAZLI HAREKETSÄ°Z TESPÄ°TÄ° â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # Merkez %40'lÄ±k bÃ¶lgeyi 32x32'ye indirge, Ã¶nceki frame ile karÅŸÄ±laÅŸtÄ±r
                try:
                    fh, fw = img.shape[:2]
                    _y1 = fh * 3 // 10; _y2 = fh * 7 // 10
                    _x1 = fw * 3 // 10; _x2 = fw * 7 // 10
                    roi_small = cv2.resize(
                        cv2.cvtColor(img[_y1:_y2, _x1:_x2], cv2.COLOR_BGR2GRAY),
                        (32, 32), interpolation=cv2.INTER_AREA
                    ).astype(np.float32)
                    prev_roi = self._prev_scene_roi.get(pk)
                    if prev_roi is None:
                        scene_moved = True
                    else:
                        diff = float(np.mean(np.abs(roi_small - prev_roi)))
                        scene_moved = diff > 6.0   # kucuk HP/mob animasyonlari sayaci resetlemesin
                    self._prev_scene_roi[pk] = roi_small
                    if scene_moved:
                        with self.st.lk:
                            self.st.scene_changed_t[pk] = time.time()
                except Exception:
                    pass
                # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                # â”€â”€ CAPTCHA â”€â”€
                # Global captcha baska client'ta aktif olsa bile bu client'in
                # frame'i okunur. Fiziksel mesaj cevabi yine asagidaki global
                # captcha kapisindan gecmeden yapilmaz.
                captcha_waiting_for_ocr = False
                cw = self.captcha_w.get(ci)
                enabled_tips = {
                    "tip1": bool(cc.get("captcha_tip1", False)),
                    "tip2": bool(cc.get("captcha_tip2", False)),
                    "tip3": bool(cc.get("captcha_tip3", False)),
                    "tip4": bool(cc.get("captcha_tip4", False)),
                }
                base_captcha_enabled = bool(cc.get("captcha", True))
                captcha_enabled = base_captcha_enabled or any(enabled_tips.values())
                if not base_captcha_enabled and any(enabled_tips.values()):
                    warn_key = (ci, "captcha_tip_without_master")
                    last_warn = self._captcha_last_log.get(warn_key, 0)
                    if time.time() - last_warn > 10:
                        active_tips = ",".join(k for k, v in enabled_tips.items() if v)
                        log_event(self.st, "warn", f"Client {ci} {active_tips} acik ama ana captcha kapaliydi, captcha solver aktif edildi")
                        self._captcha_last_log[warn_key] = time.time()
                if not captcha_enabled:
                    with self.st.lk:
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        is_global_owner = self.st.captcha_global_owner == pk
                    if is_global_owner:
                        self._clear_global_captcha("owner captcha kapali")
                elif cw and captcha_enabled:
                    try:
                        cw.set_enabled_tips(enabled_tips)
                    except Exception:
                        pass
                    status = getattr(cw, "last_status", "")
                    if not cw.hazir:
                        with self.st.lk:
                            self.st.durum[pk] = "CAPTCHA OCR"
                        last = self._captcha_last_log.get((ci, "not_ready"), 0)
                        if time.time() - last > 10:
                            detail = getattr(cw, "last_detail", "") or "ocr hazir degil"
                            log_event(self.st, "warn", f"Client {ci} captcha OCR hazir degil: {detail}")
                            self._captcha_last_log[(ci, "not_ready")] = time.time()
                        captcha_waiting_for_ocr = True
                    else:
                        captcha_bulundu = cw.kontrol_et(img, ox, oy, hwnd)
                        status = getattr(cw, "last_status", "")
                        detail = getattr(cw, "last_detail", "")
                        # Her loop'ta status log'la (throttled)
                        if status != "dialog_yok":
                            log_key = (ci, "status_check")
                            last_log = self._captcha_last_log.get(log_key, 0)
                            if time.time() - last_log > 5:
                                log_event(self.st, "info", f"Client {ci} captcha status: {status}{(' - ' + detail) if detail else ''}")
                                self._captcha_last_log[log_key] = time.time()
                        if status in ("hedef_yok", "eslesme_yok", "ocr_yok", "ocr_hata", "tip_yok", "grid_yok", "grid_az", "farkli_yok"):
                            key = (ci, status, detail)
                            last = self._captcha_last_log.get(key, 0)
                            if time.time() - last > 3:
                                log_event(self.st, "warn", f"Client {ci} captcha cozulmedi: {status}{(' - ' + detail) if detail else ''}")
                                self._captcha_last_log[key] = time.time()
                        if captcha_bulundu:
                            log_event(self.st, "warn", f"Client {ci} captcha bulundu â€” tiklandi")
                            with self.st.lk:
                                self.st.captcha_cd[pk] = time.time() + 1.5
                            self._set_global_captcha(pk, ci, f"cozuldu:{status}")
                            if cc.get("debug_on", True):
                                now = time.time()
                                if now - self._last_debug_encode.get(pk, 0) >= self._debug_encode_interval:
                                    try:
                                        small = cv2.resize(img, (640,360)) if img.shape[1] > 700 else img
                                        _,buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
                                        b64_frames[pk] = base64.b64encode(buf.tobytes()).decode()
                                        self._last_debug_encode[pk] = now
                                    except:
                                        pass
                            continue
                    if status == "dialog_yok":
                        with self.st.lk:
                            if time.time() >= self.st.captcha_cd.get(pk, 0):
                                self.st.captcha_block[pk] = False
                                self.st.captcha_state[pk] = False
                                is_global_owner = self.st.captcha_global_owner == pk
                            else:
                                is_global_owner = False
                        if is_global_owner:
                            self._clear_global_captcha("owner dialog_yok")
                    else:
                        self._set_global_captcha(pk, ci, status or "captcha kontrol")
                        continue

                # Captcha her zaman mesajdan once gelir. Aktif captcha varken mesaj
                # icin click/paste yapma; captcha temizlenince ayni pencere tekrar taranir.
                with self.st.lk:
                    captcha_global_active = self.st.captcha_global_active
                    captcha_global_owner = self.st.captcha_global_owner
                if captcha_global_active:
                    with self.st.lk:
                        self.st.captcha_block[pk] = True
                        self.st.captcha_state[pk] = True
                        self.st.durum[pk] = "CAPTCHA" if pk == captcha_global_owner else "CAPTCHA BEKLE"
                    continue

                with self.st.lk:
                    message_global_active = self.st.message_global_active
                    message_global_owner = self.st.message_global_owner
                if message_global_active and pk != message_global_owner:
                    with self.st.lk:
                        self.st.captcha_block[pk] = True
                        self.st.captcha_state[pk] = True
                        self.st.durum[pk] = "MESAJ BEKLE"
                    continue

                if self._handle_message_request(ci, pk, img, ox, oy, hwnd, cc):
                    continue

                if captcha_waiting_for_ocr:
                    continue

                farm_pause_remaining = self._message_farm_pause_remaining(pk)
                if farm_pause_remaining > 0:
                    with self.st.lk:
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        self.st.durum[pk] = "FARM BEKLEME"
                    continue

                # Model inference parametreleri
                model_path = cc.get("model_yolu") or self.cfg.g("model_yolu")
                if not model_path or not os.path.exists(model_path):
                    continue
                model = self.model_cache.get(model_path)
                if model is None:
                    try:
                        model = YOLO(model_path)
                        dummy_size = 640
                        model(np.zeros((dummy_size,dummy_size,3),dtype=np.uint8), verbose=False)
                        self.model_cache[model_path] = model
                    except:
                        continue

                conf = FIXED_CONF_ESIK
                imgsz = 640
                half = (dev == "cuda")
                
                res = model(img, stream=True, verbose=False, conf=conf, half=half, imgsz=imgsz, iou=0.45)
                mrk, kut, hedefler = [], [], []
                stable_mrk = []
                tum_ham_pos = []  # Bu karedeki TÃœM ham tespitler (ardÄ±ÅŸÄ±k doÄŸrulama iÃ§in saklanÄ±r)
                frame_ts = time.time()
                prev_target = self._prev_target_centers.get(pk) or {}
                prev_target_ts = float(prev_target.get("ts", 0.0) or 0.0)
                prev_target_centers = prev_target.get("centers") or []
                stable_frame_gap = bool(prev_target_centers) and (frame_ts - prev_target_ts) <= TARGET_STABLE_MAX_FRAME_GAP

                for rr in res:
                    if not rr.boxes: continue
                    bxs = rr.boxes.xyxy.cpu().numpy().astype(int)
                    cfs = rr.boxes.conf.cpu().numpy()
                    for i,(b1,b2,b3,b4) in enumerate(bxs):
                        w_box = b3 - b1
                        h_box = b4 - b2
                        a = w_box * h_box
                        cx, cy = (b1+b3)//2, (b2+b4)//2

                        # 1) Alan filtresi â€” devasa veya Ã§ok minik kutularÄ± at
                        if not (200 < a < 25000):
                            continue

                        # 2) Aspect ratio filtresi â€” Ã§ok ince (UI Ã§ubuklarÄ±) veya aÅŸÄ±rÄ± basÄ±k at
                        ar = w_box / h_box if h_box > 0 else 999
                        if not (0.3 < ar < 2.5):
                            continue

                        stable_dist = min((np.hypot(cx - px, cy - py) for px, py in prev_target_centers), default=999999.0)
                        stable_click = stable_frame_gap and stable_dist <= TARGET_STABLE_RADIUS
                        click_x = int((b1 + b3) / 2)
                        click_y = int(b2 + (h_box * 0.56))

                        # TÃ¼m tespitleri debug iÃ§in gÃ¶ster, kuyruk yalnÄ±zca doÄŸrulanmÄ±ÅŸ hedefe tÄ±klar.
                        tum_ham_pos.append((cx, cy))
                        mrk.append((cx, cy))
                        kut.append((b1,b2,b3,b4,float(cfs[i])))
                        if stable_click:
                            stable_mrk.append((cx, cy))
                            hedefler.append({
                                "x": click_x, "y": click_y,
                                "cx": int(cx), "cy": int(cy),
                                "box": (int(b1), int(b2), int(b3), int(b4)),
                                "conf": float(cfs[i]),
                                "stable_click": True,
                                "stable_distance": float(stable_dist),
                            })

                # Sonraki kare iÃ§in ham tespitleri sakla
                # Miss durumunda bellekteki pozisyonu da ekle â†’ mob yeniden gÃ¶rÃ¼nÃ¼nce anÄ±nda doÄŸrulanÄ±r
                with self.st.lk:
                    tm_now = self.st.target_memory.get(pk, {})
                    mem_pos = tm_now.get("last_confirmed_pos")
                if not tum_ham_pos and mem_pos:
                    self._prev_det[pk] = [mem_pos]
                else:
                    self._prev_det[pk] = tum_ham_pos
                self._prev_target_centers[pk] = {"ts": frame_ts, "centers": list(tum_ham_pos)}

                # Tiklama adaylari yalnizca iki karede sabit kalan hedef merkezlerinden gelir.
                temiz = list(stable_mrk)

                # Model memory gÃ¼ncelle (temporal smoothing - takip sistemi)
                MISS_TOLERANS = 8  # ~0.27s @ 30fps â€” kaÃ§ kare kaÃ§Ä±rÄ±lÄ±rsa takip silinsin
                with self.st.lk:
                    if pk not in self.st.target_memory:
                        self.st.target_memory[pk] = {
                            "positions": [],
                            "consecutive_found": 0,
                            "confirmed": False,
                            "last_confirmed_pos": None,
                            "misses": 0
                        }

                    tm = self.st.target_memory[pk]
                    if temiz:
                        # Yeni konumu ekle (en yakÄ±n hedefi al)
                        closest = min(temiz, key=lambda p: np.hypot(p[0]-ecx, p[1]-ecy))
                        tm["positions"].append(closest)
                        if len(tm["positions"]) > 5:
                            tm["positions"].pop(0)
                        tm["consecutive_found"] += 1
                        tm["confirmed"] = True
                        tm["misses"] = 0
                        avg_x = int(sum(p[0] for p in tm["positions"]) / len(tm["positions"]))
                        avg_y = int(sum(p[1] for p in tm["positions"]) / len(tm["positions"]))
                        tm["last_confirmed_pos"] = (avg_x, avg_y)
                    else:
                        # YOLO kaÃ§Ä±rdÄ± â€” tolerans dahilinde belleÄŸi koru
                        tm["misses"] = tm.get("misses", 0) + 1
                        if tm["misses"] >= MISS_TOLERANS:
                            # Mob gerÃ§ekten gitti, takibi temizle
                            tm["positions"] = []
                            tm["consecutive_found"] = 0
                            tm["confirmed"] = False
                            tm["last_confirmed_pos"] = None
                            tm["misses"] = 0

                    # Tolerans dahilinde miss varsa bellekteki pozisyonu hedef olarak kullan
                    if not temiz and not mrk and tm.get("last_confirmed_pos") and tm["misses"] < MISS_TOLERANS:
                        temiz = [tm["last_confirmed_pos"]]

                roi = img[y1h:y2h, x1h:x2h]
                hp_result = self._match_hp_template(roi, ci)
                self._hp_last_result = getattr(self, '_hp_last_result', {})
                self._hp_last_result[pk] = hp_result
                self._hp_score_hist = getattr(self, '_hp_score_hist', {})
                self._hp_score_hist.pop(pk, None)
                hp_px = int(hp_result["score"] * 10000)  # score -> px format (UI uyumu)

                # HP tespiti anlik template esigini kullanir. Ortalama/cache burada gecikme
                # urettigi icin HP kaybolunca debug cercevesi hemen kirmiziya donmeli.
                hp_var = bool(hp_result.get("matched", False))

                guncel[pk] = {"merkezler":temiz,"live_merkezler":list(mrk),"hedefler":hedefler,"hp_var":hp_var,"hp_piksel":hp_px,
                              "ekran_merkez":(ecx,ecy),"offset":(ox,oy),
                              "hwnd":hwnd,"client_cfg":cc, "client_idx": ci,
                              "ts": time.time()}

                # Debug frame
                if cc.get("debug_on", True):
                    now = time.time()
                    last_encode = self._last_debug_encode.get(pk, 0)
                    if now - last_encode >= self._debug_encode_interval:
                        vis = img.copy()
                        
                        # Mevcut algÄ±lanan modeller (yeÅŸil)
                        for b1,b2,b3,b4,cf in kut:
                            cv2.rectangle(vis,(b1,b2),(b3,b4),(0,255,0),2)
                            cv2.drawMarker(vis,((b1+b3)//2,(b2+b4)//2),(0,255,255),cv2.MARKER_CROSS,14,1)
                            cv2.putText(vis,f"{cf:.0%}",(b1,b2-6),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,255,0),1)
                        
                        # Bellekte onaylÄ± hedef varsa her zaman gÃ¶ster (YOLO kaÃ§Ä±rsa da)
                        tm = self.st.target_memory.get(pk, {})
                        if tm.get("last_confirmed_pos"):
                            lx, ly = tm["last_confirmed_pos"]
                            is_memory = not bool(kut)  # YOLO kaÃ§Ä±rdÄ±, bellekten gÃ¶steriliyor
                            if is_memory:
                                cv2.rectangle(vis,(lx-20,ly-20),(lx+20,ly+20), (0, 180, 255), 2)
                                cv2.putText(vis,"MEM",(lx-18,ly-22),cv2.FONT_HERSHEY_SIMPLEX,0.35,(0,180,255),1)
                        
                        cv2.circle(vis,(ecx,ecy),cc.get("ignore_radius",35),(75,0,130),2)
                        hclr = (0,255,0) if hp_var else (0,0,255)
                        cv2.rectangle(vis,(x1h,y1h),(x2h,y2h),hclr,2)
                        cv2.putText(vis,f"HP:{hp_px}",(x1h,y1h-6),cv2.FONT_HERSHEY_SIMPLEX,0.4,hclr,1)

                        # KÃ¼Ã§Ã¼lt + JPEG encode (dÃ¼ÅŸÃ¼k kalite â€” hÄ±z iÃ§in)
                        try:
                            small = cv2.resize(vis, (640,360)) if img.shape[1] > 700 else vis
                            _,buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
                            b64_frames[pk] = base64.b64encode(buf.tobytes()).decode()
                            self._last_debug_encode[pk] = now
                        except: pass

            # State gÃ¼ncelle (tek lock, hÄ±zlÄ±)
            with self.st.lk:
                publish_ts = time.time()
                for item in guncel.values():
                    item["publish_ts"] = publish_ts
                self.st.wdata = guncel
                # Inaktif client'larÄ±n frame'lerini temizle
                stale_keys = [pk for pk in self.st.frame_b64 if pk not in active_keys]
                for pk in stale_keys:
                    del self.st.frame_b64[pk]
                self.st.frame_b64.update(b64_frames)
                now = time.time()
                for pk in active_keys:
                    if self.st.message_global_active:
                        self.st.captcha_block[pk] = True
                        self.st.captcha_state[pk] = True
                        self.st.durum[pk] = "MESAJ" if pk == self.st.message_global_owner else "MESAJ BEKLE"
                        continue
                    if self.st.captcha_global_active:
                        self.st.captcha_block[pk] = True
                        self.st.captcha_state[pk] = True
                        self.st.durum[pk] = "CAPTCHA" if pk == self.st.captcha_global_owner else "CAPTCHA BEKLE"
                        continue
                    if pk not in guncel and now >= self.st.captcha_cd.get(pk, 0):
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        if self.st.durum.get(pk) == "CAPTCHA":
                            self.st.durum[pk] = "BEKLIYOR"

            # FPS limiti â€” Normal: ~20fps
            elapsed = time.time() - loop_start
            time.sleep(max(0, 0.050 - elapsed))  # 20 FPS

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PyWebView API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class API:
    def __init__(self, cfg, state):
        self.cfg, self.st = cfg, state
        self._vt = None; self._at = None
        self._toggle_lock = threading.Lock()
        self._toggle_busy_log_t = 0.0
    def get_config(self):
        result = dict(self.cfg.d)
        result['interception_ok'] = INTERCEPTION_OK
        return result
    def get_client(self, idx): return self.cfg.client(idx)
    def save_client(self, idx, data): self.cfg.update_client(idx, data); return True
    def save_global(self, data):
        global _force_sendinput
        self.cfg.update_global(data or {})
        _force_sendinput = False
        return {"ok": True}
    def set_model(self, path): self.cfg.s(path, "model_yolu"); return True
    def get_windows(self): return pencereleri_getir()

    def select_model(self, idx=None):
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
        p=filedialog.askopenfilename(filetypes=[("YOLO","*.pt")]); root.destroy()
        if p:
            if idx in (1, 2):
                self.cfg.update_client(idx, {"model_yolu": p})
            else:
                self.cfg.s(p,"model_yolu")
            if self._vt is not None and hasattr(self._vt, "model_cache"):
                self._vt.model_cache.clear()
            return {"ok": True, "path": p}
        return {"ok": False, "path": ""}

    def select_hp_bar(self, client_idx):
        threading.Thread(target=self._hp_sec, args=(client_idx,), daemon=True).start()
        return True

    def _hp_sec(self, ci):
        cc = self.cfg.client(ci)
        hwnd = hwnd_al(cc.get("pencere","Yok"))
        with mss.mss() as sct:
            m = sct.monitors[1]
            if hwnd:
                try:
                    r = win32gui.GetWindowRect(hwnd)
                    if r[0]>=-32000: m={"top":r[1],"left":r[0],"width":r[2]-r[0],"height":r[3]-r[1]}
                except: pass
            img = cv2.cvtColor(np.array(sct.grab(m),dtype=np.uint8), cv2.COLOR_BGRA2BGR)
            cv2.namedWindow("HP Bar Sec", cv2.WINDOW_NORMAL)
            cv2.setWindowProperty("HP Bar Sec", cv2.WND_PROP_TOPMOST, 1)
            roi = cv2.selectROI("HP Bar Sec", img, showCrosshair=True, fromCenter=False)
            cv2.destroyWindow("HP Bar Sec")
            if roi[2]>0 and roi[3]>0:
                h,w = img.shape[:2]
                # HP region config kaydet
                self.cfg.update_client(ci, {
                    "hp_region":[roi[1]/h,(roi[1]+roi[3])/h,roi[0]/w,(roi[0]+roi[2])/w],
                    "hp_region_custom": True
                })
                # Template image kaydet
                roi_img = img[roi[1]:roi[1]+roi[3], roi[0]:roi[0]+roi[2]]
                tpl_path = os.path.join(HP_TEMPLATE_DIR, f"client_{ci}.png")
                cv2.imwrite(tpl_path, roi_img)
                log_event(self.st, "info", f"Client {ci} HP template kaydedildi: {roi[2]}x{roi[3]}")
                # VisionThread'e template'i yeniden yÃ¼kle
                if self._vt is not None:
                    self._vt._hp_template_cache.clear()
                    self._vt._load_hp_templates()

    def get_status(self):
        with self.st.lk:
            aktif = self.st.aktif
            started_at = self.st.started_at
            cihaz = self.st.cihaz
            durum = dict(self.st.durum)
            wdata = dict(self.st.wdata)
            b64 = dict(self.st.frame_b64)  # zaten base64, encoding yok
            logs = list(self.st.logs)
            captcha_state = dict(self.st.captcha_state)
            now_status = time.time()
            global_pause = {
                "active": self.st.global_pause_active,
                "kind": self.st.global_pause_kind,
                "owner": self.st.global_pause_owner,
                "reason": self.st.global_pause_reason,
                "since": self.st.global_pause_since,
                "elapsed": round(now_status - self.st.global_pause_since, 1) if self.st.global_pause_active and self.st.global_pause_since else 0.0,
            }

        with self.st.lk:
            kill_counts = dict(self.st.kill_counts)
        result = {"aktif":aktif, "started_at":started_at, "cihaz":cihaz, "vision_fps": 0.0, "logs": logs, "global_pause": global_pause, "checklist": {"clients": {}}, "clients":{}}
        for ci in [1, 2]:
            cc = self.cfg.client(ci)
            pk = cc.get("pencere", "Yok")
            client_kill_key = f"c{ci}"
            kill_count = kill_counts.get(client_kill_key)
            if kill_count is None:
                kill_count = kill_counts.get(pk, 0)
            client_aktif = cc.get("aktif", True)
            hp_ready = bool(cc.get("hp_region_custom")) or bool(cc.get("hp_region"))
            window_ready = client_aktif and pk != "Yok"
            model_ready = bool(cc.get("model_yolu") or self.cfg.g("model_yolu"))
            
            result["checklist"]["clients"][str(ci)] = {
                "window_ready": window_ready,
                "model_ready": model_ready,
                "hp_ready": hp_ready
            }
            
            live_seen = pk in wdata or pk in b64
            
            # Daha dÃ¼zenli bir return objesi
            cd = {
                "durum": "PASIF" if not client_aktif else (durum.get(pk, "BEKLIYOR") if live_seen else "BEKLIYOR"),
                "hp_var": False,
                "hedef": 0,
                "frame": "",
                "aktif": client_aktif,
                "window": pk,
                "hp_px": 0,
                "captcha": (captcha_state.get(pk, False) if live_seen else False),
                "hp_template": hp_ready,
                "hp_template_score": 1.0 if hp_ready else 0.0,
                "kill_count": kill_count
            }
            if not client_aktif:
                result["clients"][str(ci)] = cd
                continue
            if pk in wdata:
                d = wdata[pk]
                cd["hp_var"] = d.get("hp_var",False)
                cd["hedef"] = len(d.get("merkezler",[]))
                cd["hp_px"] = d.get("hp_piksel",0)
            if pk in b64 and aktif:
                cd["frame"] = b64[pk]  # pre-encoded, anÄ±nda dÃ¶ner
            result["clients"][str(ci)] = cd
        return result

    def toggle_bot(self):
        self._toggle(source="UI")
        with self.st.lk:
            return {"aktif": self.st.aktif}

    def reset_kills(self):
        with self.st.lk:
            self.st.kill_counts.clear()
        return {"ok": True}

    def _toggle(self, source="UI"):
        if not self._toggle_lock.acquire(blocking=False):
            now = time.time()
            if now - self._toggle_busy_log_t >= 1.0:
                self._toggle_busy_log_t = now
                log_event(self.st, "warn", f"Toggle meÅŸgul, {source} isteÄŸi atlandÄ±")
            return False
        try:
            return self._toggle_locked(source)
        finally:
            self._toggle_lock.release()

    def _toggle_locked(self, source="UI"):
        with self.st.lk:
            was_active = self.st.aktif
            self.st.aktif = not self.st.aktif
            a = self.st.aktif
            self.st.started_at = time.time() if a else 0.0
        log_event(self.st, "info", f"{'Bot baslatildi' if a else 'Bot durduruldu'} ({source})")
        if not was_active and a:
            with self.st.lk:
                self.st.wdata.clear()
                self.st.frame_b64.clear()
                self.st.target_memory.clear()
                self.st.captcha_block.clear()
                self.st.captcha_state.clear()
                self.st.captcha_cd.clear()
                self.st.durum.clear()
                self.st.message_global_active = False
                self.st.message_global_owner = None
                self.st.message_global_since = 0.0
                self.st.captcha_global_active = False
                self.st.captcha_global_owner = None
                self.st.captcha_global_since = 0.0
                self.st.global_pause_active = False
                self.st.global_pause_kind = ""
                self.st.global_pause_owner = None
                self.st.global_pause_reason = ""
                self.st.global_pause_since = 0.0
                self.st.message_farm_pause_until.clear()
            if INTERCEPTION_OK:
                kb_info = f"klavye cihaz {_ikdev}" if _ikdev is not None else "klavye cihaz YOK"
                log_event(self.st, "info", f"Giris: Interception kernel driver (mouse {_idev}, {kb_info})")
                log_event(self.st, "info", "Tiklama modu: Interception")
            else:
                log_event(self.st, "info", "Giris: SendInput (Interception bulunamadi)")
                log_event(self.st, "info", "Tiklama modu: SendInput")
            self._vt   = VisionThread(self.cfg, self.st)
            self._at   = ActionThread(self.cfg, self.st)
            self._vt.start(); self._at.start()
        elif was_active and not a:
            for th in (self._at, self._vt):
                if th:
                    th.stop()
            if self._vt:
                self._vt._unload_ocr()
            for th in (self._at, self._vt):
                if th:
                    th.join(timeout=1.5)
            self._vt   = None
            self._at   = None
        return True

def main():
    _cleanup_runtime_dir(LOG_DIR, LOG_RETENTION_DAYS, keep_suffixes=(".jsonl",))
    _cleanup_runtime_dir(EVIDENCE_DIR, EVIDENCE_RETENTION_DAYS, keep_suffixes=(".png", ".json"))
    cfg = Cfg(); state = State(); api = API(cfg, state)
    # F5 hotkey - key-up olayÄ±na baÄŸlÄ± kalmadan debounce ile Ã§alÄ±ÅŸÄ±r.
    _f5_last_t = 0.0
    _f5_lock = threading.Lock()
    def _trigger_f5_toggle(source):
        nonlocal _f5_last_t
        now = time.time()
        with _f5_lock:
            if now - _f5_last_t < 0.35:
                return
            _f5_last_t = now
        log_event(state, "info", f"F5 algilandi ({source})")
        threading.Thread(target=api._toggle, kwargs={"source": "F5"}, daemon=True).start()

    def _on_f5(event):
        if event.name != 'f5' or event.event_type != 'down':
            return
        _trigger_f5_toggle("hook")
    keyboard.hook(_on_f5)

    def _f5_poll_loop():
        was_down = False
        while True:
            try:
                down = bool(win32api.GetAsyncKeyState(0x74) & 0x8000)
                if down and not was_down:
                    _trigger_f5_toggle("poll")
                was_down = down
                time.sleep(0.025)
            except Exception as e:
                log_event(state, "warn", f"F5 poll hata: {e}")
                time.sleep(1.0)
    threading.Thread(target=_f5_poll_loop, daemon=True).start()
    # SHIFT+SOL TIK iÃ§in hotkey (normal tÄ±klamayÄ± engelle, bot tÄ±klamasÄ±nÄ± kullan)
    keyboard.add_hotkey('shift+left', sol_tik_hw_shift_callback, suppress=True)
    window = webview.create_window(title="PHANTOM", url=HTML_FILE, js_api=api,
                                    width=760, height=500, resizable=False)
    webview.start(debug=False)

if __name__ == '__main__':
    main()


