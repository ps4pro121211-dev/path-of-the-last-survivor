"""
Thai Dub - พากย์ไทยจากซับไตเติลในเกมแบบเรียลไทม์
==================================================
อ่านซับบนจอ (OCR) -> แปลเป็นไทย (Google Translate) -> พูดด้วยเสียงไทย (Edge TTS)

ปุ่มลัด (ค่าเริ่มต้น แก้ได้ใน config.json):
    F6  = บันทึกภาพดีบัก (ดูว่าโปรแกรมเห็นซับยังไง)
    F7  = สลับเสียงผู้ชาย / ผู้หญิง
    F8  = หยุด / เล่นต่อ
    F9  = เลือกกรอบซับใหม่
    F10 = ปิดโปรแกรม
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import difflib
import io
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from PIL import Image, ImageEnhance  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEBUG_DIR = BASE_DIR / "debug"

VOICES = ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"]  # ชาย, หญิง

DEFAULT_CONFIG = {
    # กรอบซับ [left, top, width, height] (หน่วยพิกเซลจริงของจอ) - null = ให้เลือกตอนเปิด
    "region": None,
    # ภาษาของซับในเกม
    "source_lang": "en",
    # ตัวแปล: "auto" (Google ก่อน ถ้าโดนจำกัดใช้ Microsoft), "google", "microsoft"
    "translator": "auto",
    # "windows" = Windows OCR (ไม่ต้องติดตั้งเพิ่ม), "tesseract" = Tesseract OCR
    "ocr_engine": "windows",
    "tesseract_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    # เสียงพากย์
    "voice": "th-TH-NiwatNeural",
    "rate": "+15%",          # ความเร็วเสียงพูด เช่น "+0%", "+25%"
    "volume": "+0%",
    # การอ่านซับ
    "scan_interval": 0.35,    # อ่านจอทุก ๆ กี่วินาที
    "stable_reads": 2,        # ต้องอ่านได้ข้อความเดิมกี่ครั้งติดกันถึงจะถือว่าซับขึ้นครบ
    "similarity": 0.85,       # ข้อความคล้ายกันเกินค่านี้ = ประโยคเดิม (ไม่พูดซ้ำ)
    "min_chars": 4,           # ข้อความสั้นกว่านี้ไม่อ่าน (กันอ่านขยะ)
    "upscale": 2,             # ขยายภาพก่อน OCR ช่วยให้อ่านแม่นขึ้น
    # ซับ RDR2 เป็นตัวหนังสือสีขาว: เก็บเฉพาะพิกเซลที่สว่างกว่าค่านี้ (0 = ปิด)
    "white_text_threshold": 175,
    "strip_speaker_name": True,   # ตัดชื่อคนพูดหน้าประโยค เช่น "ARTHUR: ..."
    # การเล่นเสียง
    "interrupt_on_new_line": False,  # True = ประโยคใหม่มา ตัดประโยคเก่าทิ้งทันที
    "max_queue": 2,                  # จำนวนประโยคที่รอพูดได้มากสุด (เกินนี้ทิ้งอันเก่า)
    # ปุ่มลัด
    "hotkey_debug": "f6",
    "hotkey_voice": "f7",
    "hotkey_toggle": "f8",
    "hotkey_select": "f9",
    "hotkey_quit": "f10",
}


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"[!] Cannot read config.json ({e}), using defaults")
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def set_dpi_aware() -> None:
    """ให้พิกัดเมาส์/จอตรงกันแม้ตั้ง Scale ใน Windows ไว้ 125% / 150%"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------------
# Screen capture & region selection
# ----------------------------------------------------------------------------
def grab(sct, region) -> Image.Image:
    left, top, width, height = region
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def select_region(sct):
    """แสดงภาพหน้าจอ แล้วให้ผู้ใช้ลากกรอบรอบบริเวณซับ"""
    import tkinter as tk
    from PIL import ImageTk

    mon = sct.monitors[1]  # จอหลัก
    full = grab(sct, (mon["left"], mon["top"], mon["width"], mon["height"]))
    dim = ImageEnhance.Brightness(full).enhance(0.55)

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(cursor="crosshair")
    canvas = tk.Canvas(root, highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)
    photo = ImageTk.PhotoImage(dim)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    canvas.create_text(
        mon["width"] // 2, 40,
        text="Drag a box around the SUBTITLE area (tall enough for 2 lines)   |   Esc = cancel",
        fill="yellow", font=("Tahoma", 20, "bold"),
    )

    state = {"start": None, "rect": None, "result": None}

    def on_press(e):
        state["start"] = (e.x, e.y)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff66", width=3)

    def on_drag(e):
        if state["start"]:
            x0, y0 = state["start"]
            canvas.coords(state["rect"], x0, y0, e.x, e.y)

    def on_release(e):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = e.x, e.y
        left, top = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w > 20 and h > 10:
            state["result"] = [mon["left"] + left, mon["top"] + top, w, h]
            root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    root.mainloop()
    return state["result"]


# ----------------------------------------------------------------------------
# OCR
# ----------------------------------------------------------------------------
def preprocess(img: Image.Image, cfg: dict) -> Image.Image:
    g = img.convert("L")
    s = int(cfg.get("upscale", 1) or 1)
    if s > 1:
        g = g.resize((g.width * s, g.height * s), Image.LANCZOS)
    t = int(cfg.get("white_text_threshold", 0) or 0)
    if t > 0:
        # ตัวหนังสือสว่าง -> ดำ, พื้นหลัง -> ขาว (OCR อ่านง่ายที่สุด)
        g = g.point(lambda p: 0 if p >= t else 255)
    return g.convert("RGB")


class OcrEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lang = cfg["source_lang"]
        self.engine = cfg.get("ocr_engine", "windows")
        self.loop = asyncio.new_event_loop()
        if self.engine == "windows":
            try:
                import winocr  # noqa: F401
                self._winocr = winocr
                self.read(Image.new("RGB", (64, 32), "white"))  # ทดสอบว่าใช้ได้จริง
            except Exception as e:  # noqa: BLE001
                print(f"[!] Windows OCR not available: {e}")
                print("    -> Make sure English language is installed in Windows (see README)")
                print("    -> Trying Tesseract instead...")
                self.engine = "tesseract"
        if self.engine == "tesseract":
            import pytesseract
            path = cfg.get("tesseract_path")
            if path and Path(path).exists():
                pytesseract.pytesseract.tesseract_cmd = path
            self._tess = pytesseract
            self._tess_lang = {"en": "eng", "ja": "jpn", "zh": "chi_sim", "ko": "kor"}.get(self.lang, "eng")
            self._tess.get_tesseract_version()  # ถ้าไม่มี Tesseract จะ error ตรงนี้
        print(f"[i] OCR: {self.engine}")

    def read(self, img: Image.Image) -> str:
        if self.engine == "windows":
            r = self.loop.run_until_complete(self._winocr.recognize_pil(img, self.lang))
            lines = getattr(r, "lines", None)
            if lines is not None:
                return " ".join(line.text for line in lines)
            return getattr(r, "text", "") or ""
        return self._tess.image_to_string(img, lang=self._tess_lang, config="--psm 6")


_SPEAKER_RE = re.compile(r"^\s*[A-Z][A-Za-z.'\- ]{1,24}:\s+")


def clean_text(raw: str, cfg: dict) -> str:
    t = raw.replace("\n", " ")
    t = re.sub(r"[|_~`^<>{}\[\]\\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if cfg.get("strip_speaker_name", True):
        t = _SPEAKER_RE.sub("", t)
    if len(t) < int(cfg.get("min_chars", 4)):
        return ""
    # กันขยะ: ต้องเป็นตัวอักษรอย่างน้อยครึ่งหนึ่ง และมีคำที่ยาวเกิน 1 ตัวอักษร
    letters = sum(c.isalpha() for c in t)
    if letters < len(t.replace(" ", "")) * 0.6:
        return ""
    if cfg.get("source_lang") == "en":
        # ต้องมีคำภาษาอังกฤษจริง ๆ อย่างน้อย 1 คำ (3 ตัวอักษรขึ้นไป)
        if not re.search(r"[A-Za-z]{3,}", t):
            return ""
        words = t.split()
        good = sum(1 for w in words if re.fullmatch(r"[A-Za-z'’\-]+[.,!?;:\"]*", w))
        if good < max(1, len(words) * 0.7):
            return ""
    return t


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ----------------------------------------------------------------------------
# Translator: Google (ฟรี) -> ถ้าโดนจำกัดจะสลับไป Microsoft (ฟรี) อัตโนมัติ
# ----------------------------------------------------------------------------
class RateLimited(Exception):
    pass


class Translator:
    MIN_GAP = 0.6  # วินาที ระหว่างคำขอแต่ละครั้ง กันโดนบล็อก

    def __init__(self, cfg: dict):
        import requests

        self.src = cfg["source_lang"]
        self.order = {
            "google": ["google", "microsoft"],
            "microsoft": ["microsoft", "google"],
        }.get(cfg.get("translator", "auto"), ["google", "microsoft"])
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        self.cache: dict[str, str] = {}
        self.blocked_until = {"google": 0.0, "microsoft": 0.0}
        self.last_call = 0.0
        self.ms_token = ""
        self.ms_token_time = 0.0
        self.last_error_print = 0.0

    def _google(self, text: str) -> str:
        r = self.http.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": self.src, "tl": "th", "dt": "t", "q": text},
            timeout=6,
        )
        if r.status_code == 429:
            raise RateLimited("Google 429")
        r.raise_for_status()
        data = r.json()
        return "".join(seg[0] for seg in data[0] if seg and seg[0])

    def _microsoft(self, text: str) -> str:
        if not self.ms_token or time.time() - self.ms_token_time > 480:
            t = self.http.get("https://edge.microsoft.com/translate/auth", timeout=6)
            t.raise_for_status()
            self.ms_token, self.ms_token_time = t.text.strip(), time.time()
        r = self.http.post(
            "https://api-edge.cognitive.microsofttranslator.com/translate",
            params={"from": self.src, "to": "th", "api-version": "3.0"},
            headers={"Authorization": f"Bearer {self.ms_token}"},
            json=[{"Text": text}],
            timeout=6,
        )
        if r.status_code == 429:
            raise RateLimited("Microsoft 429")
        if r.status_code == 401:
            self.ms_token = ""
        r.raise_for_status()
        return r.json()[0]["translations"][0]["text"]

    def translate(self, text: str) -> str | None:
        if text in self.cache:
            return self.cache[text]
        wait = self.MIN_GAP - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        errors = []
        for name in self.order:
            if time.monotonic() < self.blocked_until[name]:
                continue
            self.last_call = time.monotonic()
            try:
                th = (self._google if name == "google" else self._microsoft)(text)
                if th:
                    self.cache[text] = th
                    return th
            except RateLimited:
                self.blocked_until[name] = time.monotonic() + 60
                print(f"[i] {name} is busy (too many requests) - switching for 60s")
            except Exception as e:  # noqa: BLE001
                self.blocked_until[name] = time.monotonic() + 5
                errors.append(f"{name}: {e}")
        if errors and time.monotonic() - self.last_error_print > 10:
            self.last_error_print = time.monotonic()
            print("[!] Translation failed: " + " | ".join(errors)[:300])
        return None


# ----------------------------------------------------------------------------
# Translate -> TTS -> play  (ทำงานใน thread แยก เพื่อไม่ให้การอ่านจอสะดุด)
# ----------------------------------------------------------------------------
class DubPipeline:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.translator = Translator(cfg)
        self.text_q: queue.Queue = queue.Queue()
        self.audio_q: queue.Queue = queue.Queue()
        self.generation = 0  # เพิ่มทุกครั้งที่สั่งตัดเสียง เพื่อทิ้งงานเก่า
        self.stop_event = threading.Event()
        self.mixer_ok = False
        try:
            import pygame

            pygame.mixer.init()
            self.pygame = pygame
            self.mixer_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[!] Cannot open audio device: {e}")
        threading.Thread(target=self._synth_worker, daemon=True).start()
        threading.Thread(target=self._play_worker, daemon=True).start()

    # --- public ---
    def submit(self, text: str) -> None:
        if self.cfg.get("interrupt_on_new_line"):
            self.interrupt()
        else:
            max_q = int(self.cfg.get("max_queue", 2))
            while self.text_q.qsize() + self.audio_q.qsize() >= max_q:
                try:
                    self.text_q.get_nowait()
                except queue.Empty:
                    try:
                        self.audio_q.get_nowait()
                    except queue.Empty:
                        break
        self.text_q.put((self.generation, text))

    def interrupt(self) -> None:
        self.generation += 1
        for q in (self.text_q, self.audio_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        if self.mixer_ok:
            self.pygame.mixer.music.stop()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.interrupt()
        self.text_q.put(None)
        self.audio_q.put(None)

    async def synth(self, text: str) -> bytes:
        import edge_tts

        com = edge_tts.Communicate(
            text, self.cfg["voice"], rate=self.cfg.get("rate", "+0%"), volume=self.cfg.get("volume", "+0%")
        )
        buf = bytearray()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    # --- workers ---
    def _synth_worker(self) -> None:
        loop = asyncio.new_event_loop()
        while not self.stop_event.is_set():
            item = self.text_q.get()
            if item is None:
                break
            gen, text = item
            th = self.translator.translate(text)
            if not th or gen != self.generation:
                continue
            try:
                audio = loop.run_until_complete(self.synth(th))
            except Exception as e:  # noqa: BLE001
                print(f"[!] Text-to-speech failed: {e}")
                continue
            if audio and gen == self.generation:
                self.audio_q.put((gen, audio))

    def _play_worker(self) -> None:
        while not self.stop_event.is_set():
            item = self.audio_q.get()
            if item is None:
                break
            gen, audio = item
            if gen != self.generation or not self.mixer_ok:
                continue
            music = self.pygame.mixer.music
            try:
                music.load(io.BytesIO(audio), "mp3")
                music.play()
                while music.get_busy() and gen == self.generation and not self.stop_event.is_set():
                    time.sleep(0.05)
            except Exception as e:  # noqa: BLE001
                print(f"[!] Audio playback failed: {e}")


# ----------------------------------------------------------------------------
# Subtitle watcher (ตัดสินว่าเมื่อไหร่คือ "ซับใหม่")
# ----------------------------------------------------------------------------
class SubtitleTracker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.candidate = ""
        self.count = 0
        self.last_spoken = ""
        self.empty_since: float | None = None

    def feed(self, text: str) -> str | None:
        """รับข้อความที่ OCR อ่านได้ คืนค่าข้อความที่ควรพากย์ (หรือ None)"""
        now = time.monotonic()
        if not text:
            self.candidate, self.count = "", 0
            if self.empty_since is None:
                self.empty_since = now
            elif now - self.empty_since > 1.5:
                self.last_spoken = ""  # ซับหายไปนานแล้ว ประโยคเดิมกลับมาก็พูดใหม่ได้
            return None
        self.empty_since = None

        thr = float(self.cfg.get("similarity", 0.85))
        if similar(text, self.candidate) >= thr:
            self.count += 1
            # เก็บข้อความที่ยาวกว่า (มักอ่านครบกว่า)
            if len(text) > len(self.candidate):
                self.candidate = text
        else:
            self.candidate, self.count = text, 1

        if self.count == int(self.cfg.get("stable_reads", 2)):
            if similar(self.candidate, self.last_spoken) < thr:
                self.last_spoken = self.candidate
                return self.candidate
        return None


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="พากย์ไทยจากซับไตเติลในเกม")
    ap.add_argument("--select", action="store_true", help="เลือกกรอบซับใหม่ตอนเปิด")
    ap.add_argument("--female", action="store_true", help="ใช้เสียงผู้หญิง")
    ap.add_argument("--male", action="store_true", help="ใช้เสียงผู้ชาย")
    args = ap.parse_args()

    import mss

    cfg = load_config()
    if args.female:
        cfg["voice"] = VOICES[1]
    if args.male:
        cfg["voice"] = VOICES[0]
    set_dpi_aware()

    print("=" * 60)
    print("  Thai Dub - Thai voice-over from game subtitles")
    print("=" * 60)

    sct = mss.mss()
    if args.select or not cfg.get("region"):
        print("[i] Select subtitle area: drag a box around the subtitles")
        region = select_region(sct)
        if not region:
            print("[!] No area selected, exiting")
            return
        cfg["region"] = region
        save_config(cfg)
    print(f"[i] Subtitle area: {cfg['region']}")

    ocr = OcrEngine(cfg)
    dub = DubPipeline(cfg)
    tracker = SubtitleTracker(cfg)

    flags = {"paused": False, "quit": False, "select": False, "debug": False}

    def toggle_pause():
        flags["paused"] = not flags["paused"]
        if flags["paused"]:
            dub.interrupt()
        print("[i] PAUSED" if flags["paused"] else "[i] RESUMED")

    def toggle_voice():
        cfg["voice"] = VOICES[1] if cfg["voice"] == VOICES[0] else VOICES[0]
        save_config(cfg)
        print(f"[i] Voice: {'FEMALE' if cfg['voice'] == VOICES[1] else 'MALE'}")

    try:
        import keyboard

        keyboard.add_hotkey(cfg["hotkey_toggle"], toggle_pause)
        keyboard.add_hotkey(cfg["hotkey_voice"], toggle_voice)
        keyboard.add_hotkey(cfg["hotkey_select"], lambda: flags.__setitem__("select", True))
        keyboard.add_hotkey(cfg["hotkey_debug"], lambda: flags.__setitem__("debug", True))
        keyboard.add_hotkey(cfg["hotkey_quit"], lambda: flags.__setitem__("quit", True))
        print(
            f"[i] ปุ่มลัด: {cfg['hotkey_toggle'].upper()}=pause/resume  "
            f"{cfg['hotkey_voice'].upper()}=switch voice  {cfg['hotkey_select'].upper()}=reselect area  "
            f"{cfg['hotkey_debug'].upper()}=debug image  {cfg['hotkey_quit'].upper()}=quit"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[!] Hotkeys unavailable ({e}) - press Ctrl+C here to quit")

    print(f"[i] Voice: {cfg['voice']}   Waiting for subtitles...\n")

    interval = float(cfg.get("scan_interval", 0.35))
    try:
        while not flags["quit"]:
            t0 = time.monotonic()

            if flags["select"]:
                flags["select"] = False
                dub.interrupt()
                region = select_region(sct)
                if region:
                    cfg["region"] = region
                    save_config(cfg)
                    print(f"[i] New subtitle area: {region}")

            if flags["paused"]:
                time.sleep(0.2)
                continue

            raw_img = grab(sct, cfg["region"])
            img = preprocess(raw_img, cfg)
            try:
                raw = ocr.read(img)
            except Exception as e:  # noqa: BLE001
                print(f"[!] OCR error: {e}")
                raw = ""
            text = clean_text(raw, cfg)

            if flags["debug"]:
                flags["debug"] = False
                DEBUG_DIR.mkdir(exist_ok=True)
                stamp = time.strftime("%H%M%S")
                raw_img.save(DEBUG_DIR / f"{stamp}_capture.png")
                img.save(DEBUG_DIR / f"{stamp}_processed.png")
                print(f"[debug] Images saved to {DEBUG_DIR}")
                print(f"[debug] OCR raw: {raw!r}")
                print(f"[debug] Cleaned: {text!r}\n")

            line = tracker.feed(text)
            if line:
                print(f"  EN: {line}")
                dub.submit(line)

            time.sleep(max(0.0, interval - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        dub.shutdown()
        print("[i] Bye")


if __name__ == "__main__":
    main()
