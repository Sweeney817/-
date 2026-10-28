from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import json
import math
import queue
import threading
import tkinter as tk
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageGrab, ImageTk


VK_F1 = 0x70
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class F1Hotkey:
    """Own F1 while the pet is running without depending on another app."""

    def __init__(self, requests: queue.SimpleQueue[str]) -> None:
        self.requests = requests
        self.thread_id = 0
        self.hook = None
        self.callback = None
        self.thread = threading.Thread(target=self._run, name="PetScreenshotHotkey", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        registered = bool(user32.RegisterHotKey(None, 1, 0, VK_F1))
        message = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY and message.wParam == 1:
                self.requests.put("capture")
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if registered:
            user32.UnregisterHotKey(None, 1)

    def close(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def copy_image_to_clipboard(image: Image.Image) -> None:
    output = io.BytesIO()
    image.convert("RGB").save(output, "BMP")
    dib = output.getvalue()[14:]
    output.close()

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint32, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    global_mem = kernel32.GlobalAlloc(0x0002, len(dib))
    if not global_mem:
        raise OSError("无法分配剪贴板内存")
    locked = kernel32.GlobalLock(global_mem)
    ctypes.memmove(locked, dib, len(dib))
    kernel32.GlobalUnlock(global_mem)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(global_mem)
        raise OSError("无法打开剪贴板")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(8, global_mem):
            raise OSError("无法写入剪贴板")
        global_mem = None
    finally:
        user32.CloseClipboard()
        if global_mem:
            kernel32.GlobalFree(global_mem)


class AnnotationEditor:
    def __init__(self, owner: tk.Misc, image: Image.Image, on_apply) -> None:
        self.on_apply = on_apply
        self.image = image.convert("RGBA")
        self.history: list[Image.Image] = []
        self.tool = tk.StringVar(value="pen")
        self.color = "#ff3b30"
        self.start = None
        self.last = None
        self.preview = None

        self.window = tk.Toplevel(owner)
        self.window.title("截图标注")
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#202124")
        toolbar = tk.Frame(self.window, bg="#202124")
        toolbar.pack(fill="x")
        tools = (("画笔", "pen"), ("箭头", "arrow"), ("矩形", "rect"), ("马赛克", "mosaic"), ("文字", "text"))
        for label, value in tools:
            tk.Radiobutton(
                toolbar,
                text=label,
                value=value,
                variable=self.tool,
                indicatoron=False,
                bg="#303134",
                fg="white",
                selectcolor="#1677ff",
                activebackground="#4a4b4e",
                activeforeground="white",
                bd=0,
                padx=11,
                pady=7,
            ).pack(side="left", padx=(4, 0), pady=5)
        tk.Button(toolbar, text="颜色", command=self._choose_color, **self._button_style()).pack(side="left", padx=4, pady=5)
        tk.Button(toolbar, text="撤销", command=self.undo, **self._button_style()).pack(side="left", padx=4, pady=5)
        tk.Button(toolbar, text="完成", command=self.apply, bg="#1677ff", fg="white", bd=0, padx=14, pady=7).pack(side="right", padx=5, pady=5)
        tk.Button(toolbar, text="取消", command=self.close, **self._button_style()).pack(side="right", padx=4, pady=5)

        max_w = max(320, self.window.winfo_screenwidth() - 160)
        max_h = max(240, self.window.winfo_screenheight() - 190)
        self.display_scale = min(1.0, max_w / self.image.width, max_h / self.image.height)
        self.canvas_w = max(1, round(self.image.width * self.display_scale))
        self.canvas_h = max(1, round(self.image.height * self.display_scale))
        self.canvas = tk.Canvas(self.window, width=self.canvas_w, height=self.canvas_h, bd=0, highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.window.bind("<Escape>", lambda _event: self.close())
        self._refresh()

    @staticmethod
    def _button_style() -> dict:
        return {"bg": "#303134", "fg": "white", "activebackground": "#4a4b4e", "activeforeground": "white", "bd": 0, "padx": 11, "pady": 7}

    def _choose_color(self) -> None:
        chosen = colorchooser.askcolor(self.color, parent=self.window, title="标注颜色")[1]
        if chosen:
            self.color = chosen

    def _point(self, event: tk.Event) -> tuple[int, int]:
        return (round(event.x / self.display_scale), round(event.y / self.display_scale))

    def _save_history(self) -> None:
        self.history.append(self.image.copy())
        if len(self.history) > 20:
            self.history.pop(0)

    def _press(self, event: tk.Event) -> None:
        self.start = self._point(event)
        self.last = self.start
        if self.tool.get() in {"pen", "mosaic", "text"}:
            self._save_history()
        if self.tool.get() == "text":
            text = simpledialog.askstring("添加文字", "请输入标注文字：", parent=self.window)
            if text:
                draw = ImageDraw.Draw(self.image)
                font_size = max(18, round(22 / max(self.display_scale, 0.2)))
                try:
                    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", font_size)
                except OSError:
                    font = ImageFont.load_default()
                draw.text(self.start, text, fill=self.color, font=font, stroke_width=1, stroke_fill="white")
                self._refresh()

    def _move(self, event: tk.Event) -> None:
        if self.start is None:
            return
        point = self._point(event)
        if self.tool.get() == "pen":
            draw = ImageDraw.Draw(self.image)
            draw.line((self.last, point), fill=self.color, width=max(3, round(4 / self.display_scale)), joint="curve")
            self.last = point
            self._refresh()
        elif self.tool.get() in {"arrow", "rect", "mosaic"}:
            self._show_preview(point)

    def _show_preview(self, point: tuple[int, int]) -> None:
        if self.preview is not None:
            self.canvas.delete(self.preview)
        x1, y1 = (round(v * self.display_scale) for v in self.start)
        x2, y2 = (round(v * self.display_scale) for v in point)
        if self.tool.get() == "arrow":
            self.preview = self.canvas.create_line(x1, y1, x2, y2, fill=self.color, width=3, arrow="last")
        else:
            self.preview = self.canvas.create_rectangle(x1, y1, x2, y2, outline=self.color, width=3)

    def _release(self, event: tk.Event) -> None:
        if self.start is None:
            return
        end = self._point(event)
        tool = self.tool.get()
        if tool in {"arrow", "rect"}:
            self._save_history()
            draw = ImageDraw.Draw(self.image)
            width = max(3, round(4 / self.display_scale))
            if tool == "rect":
                x1, x2 = sorted((self.start[0], end[0]))
                y1, y2 = sorted((self.start[1], end[1]))
                draw.rectangle((x1, y1, x2, y2), outline=self.color, width=width)
            else:
                self._draw_arrow(draw, self.start, end, width)
        elif tool == "mosaic":
            self._apply_mosaic(self.start, end)
        if self.preview is not None:
            self.canvas.delete(self.preview)
            self.preview = None
        self.start = None
        self.last = None
        self._refresh()

    def _draw_arrow(self, draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], width: int) -> None:
        draw.line((start, end), fill=self.color, width=width)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        length = max(14, width * 4)
        left = (end[0] - length * math.cos(angle - 0.55), end[1] - length * math.sin(angle - 0.55))
        right = (end[0] - length * math.cos(angle + 0.55), end[1] - length * math.sin(angle + 0.55))
        draw.polygon((end, left, right), fill=self.color)

    def _apply_mosaic(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        x1, x2 = sorted((min(self.image.width, max(0, start[0])), min(self.image.width, max(0, end[0]))))
        y1, y2 = sorted((min(self.image.height, max(0, start[1])), min(self.image.height, max(0, end[1]))))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        region = self.image.crop((x1, y1, x2, y2))
        small = region.resize((max(1, region.width // 12), max(1, region.height // 12)), Image.Resampling.BILINEAR)
        self.image.paste(small.resize(region.size, Image.Resampling.NEAREST), (x1, y1))

    def _refresh(self) -> None:
        shown = self.image.resize((self.canvas_w, self.canvas_h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(shown)
        if hasattr(self, "image_item"):
            self.canvas.itemconfigure(self.image_item, image=self.photo)
        else:
            self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
            self.canvas.tag_lower(self.image_item)

    def undo(self) -> None:
        if self.history:
            self.image = self.history.pop()
            self._refresh()

    def apply(self) -> None:
        self.on_apply(self.image)
        self.close()

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()


class PinnedImage:
    def __init__(self, controller, image: Image.Image, x: int, y: int, on_close) -> None:
        self.controller = controller
        self.on_close = on_close
        self.image = image.convert("RGBA")
        self.scale = 1.0
        self.opacity = 1.0
        self.window = tk.Toplevel(controller.owner.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.label = tk.Label(self.window, bd=1, relief="solid", bg="#222222")
        self.label.pack()
        self.window.geometry(f"+{x}+{y}")
        self.drag_origin = (0, 0)
        self._build_menu()
        self._refresh()
        self.window.bind("<ButtonPress-1>", self._drag_start)
        self.window.bind("<B1-Motion>", self._drag_move)
        self.window.bind("<Double-Button-1>", lambda _event: self.annotate())
        self.window.bind("<Button-3>", self._show_menu)
        self.window.bind("<MouseWheel>", self._mousewheel)
        self.window.bind("<Escape>", lambda _event: self.close())

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.window, tearoff=False)
        self.menu.add_command(label="标注（双击）", command=self.annotate)
        self.menu.add_command(label="复制", command=lambda: copy_image_to_clipboard(self.image))
        self.menu.add_command(label="保存", command=self.save)
        self.menu.add_command(label="英译中", command=lambda: self.controller.translate_image(self.image))
        self.menu.add_separator()
        self.menu.add_command(label="放大", command=lambda: self.set_scale(self.scale + 0.15))
        self.menu.add_command(label="缩小", command=lambda: self.set_scale(self.scale - 0.15))
        self.menu.add_command(label="原始大小", command=lambda: self.set_scale(1.0))
        opacity_menu = tk.Menu(self.menu, tearoff=False)
        for label, value in (("100%", 1.0), ("80%", 0.8), ("60%", 0.6), ("40%", 0.4), ("20%", 0.2)):
            opacity_menu.add_command(label=label, command=lambda amount=value: self.set_opacity(amount))
        self.menu.add_cascade(label="透明度", menu=opacity_menu)
        self.menu.add_separator()
        self.menu.add_command(label="关闭贴图", command=self.close)

    def _show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def _mousewheel(self, event: tk.Event) -> None:
        self.set_scale(self.scale + (0.1 if event.delta > 0 else -0.1))

    def set_scale(self, scale: float) -> None:
        self.scale = round(min(4.0, max(0.25, scale)), 2)
        self._refresh()

    def set_opacity(self, opacity: float) -> None:
        self.opacity = opacity
        self.window.attributes("-alpha", opacity)

    def _refresh(self) -> None:
        size = (max(1, round(self.image.width * self.scale)), max(1, round(self.image.height * self.scale)))
        shown = self.image.resize(size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(shown)
        self.label.configure(image=self.photo)
        self.window.update_idletasks()
        self.window.geometry(f"{size[0]}x{size[1]}+{self.window.winfo_x()}+{self.window.winfo_y()}")

    def annotate(self) -> None:
        AnnotationEditor(self.window, self.image, self._apply_annotation)

    def _apply_annotation(self, image: Image.Image) -> None:
        self.image = image
        self._refresh()

    def save(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.window,
            title="保存贴图",
            initialdir=str(Path.home() / "Desktop"),
            defaultextension=".png",
            filetypes=(("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg;*.jpeg")),
        )
        if destination:
            image = self.image.convert("RGB") if Path(destination).suffix.lower() in {".jpg", ".jpeg"} else self.image
            image.save(destination, quality=96)

    def _drag_start(self, event: tk.Event) -> None:
        self.drag_origin = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        self.window.geometry(f"+{event.x_root - self.drag_origin[0]}+{event.y_root - self.drag_origin[1]}")

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()
        self.on_close(self)


class TranslationWindow:
    def __init__(self, owner: tk.Misc, original: str, translated: str) -> None:
        self.window = tk.Toplevel(owner)
        self.window.title("截图英译中")
        self.window.attributes("-topmost", True)
        self.window.geometry("680x520")
        self.window.minsize(480, 360)
        self.window.configure(bg="#f5f6f8")

        header = tk.Frame(self.window, bg="#f5f6f8")
        header.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(header, text="英文原文", bg="#f5f6f8", fg="#202124", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Button(header, text="复制中文", command=lambda: self._copy(translated), bg="#1677ff", fg="white", bd=0, padx=12, pady=5).pack(side="right")

        original_box = tk.Text(self.window, height=9, wrap="word", font=("Microsoft YaHei UI", 10), bd=1, relief="solid")
        original_box.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        original_box.insert("1.0", original)
        original_box.configure(state="disabled")
        tk.Label(self.window, text="中文翻译", bg="#f5f6f8", fg="#202124", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=14, pady=(0, 4))
        translated_box = tk.Text(self.window, height=9, wrap="word", font=("Microsoft YaHei UI", 11), bd=1, relief="solid")
        translated_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        translated_box.insert("1.0", translated)

    def _copy(self, text: str) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update()


def translate_english_to_chinese(text: str) -> str:
    chunks = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= 3000:
            chunks.append(remaining)
            break
        split_at = max(remaining.rfind("\n", 0, 3000), remaining.rfind(". ", 0, 3000))
        if split_at < 800:
            split_at = 3000
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    translated_parts = []
    for chunk in chunks:
        query = urllib.parse.urlencode(
            {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": chunk}
        )
        request = urllib.request.Request(
            "https://translate.googleapis.com/translate_a/single?" + query,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        translated_parts.append("".join(item[0] for item in payload[0] if item and item[0]))
    return "\n".join(translated_parts)


class ScreenshotOverlay:
    def __init__(self, owner, screenshot: Image.Image, left: int, top: int, on_finish) -> None:
        self.owner = owner
        self.screenshot = screenshot
        self.left = left
        self.top = top
        self.on_finish = on_finish
        self.start = None
        self.selection = None
        self.crop_photo = None

        self.window = tk.Toplevel(owner.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="black")
        self.canvas = tk.Canvas(
            self.window,
            width=screenshot.width,
            height=screenshot.height,
            bd=0,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        dimmed = ImageEnhance.Brightness(screenshot).enhance(0.48)
        self.background_photo = ImageTk.PhotoImage(dimmed)
        self.canvas.create_image(0, 0, image=self.background_photo, anchor="nw")
        self.canvas.bind("<ButtonPress-1>", self._start_selection)
        self.canvas.bind("<B1-Motion>", self._move_selection)
        self.canvas.bind("<ButtonRelease-1>", self._finish_selection)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.geometry(f"{screenshot.width}x{screenshot.height}+0+0")
        self.window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id()) or self.window.winfo_id()
        ctypes.windll.user32.SetWindowPos(
            hwnd, -1, left, top, screenshot.width, screenshot.height, 0x0040
        )
        self.window.focus_force()

    def _start_selection(self, event: tk.Event) -> None:
        self.start = (event.x, event.y)
        self.selection = None
        self._remove_selection_items()

    def _move_selection(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x1, y1, x2, y2 = self._normalized_box(self.start[0], self.start[1], event.x, event.y)
        self._draw_selection(x1, y1, x2, y2)

    def _finish_selection(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x1, y1, x2, y2 = self._normalized_box(self.start[0], self.start[1], event.x, event.y)
        if x2 - x1 < 4 or y2 - y1 < 4:
            self.cancel()
            return
        self.selection = (x1, y1, x2, y2)
        self._draw_selection(x1, y1, x2, y2)
        self._show_toolbar(x1, y1, x2, y2)

    def _normalized_box(self, x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
        return (
            max(0, min(x1, x2)),
            max(0, min(y1, y2)),
            min(self.screenshot.width, max(x1, x2)),
            min(self.screenshot.height, max(y1, y2)),
        )

    def _remove_selection_items(self) -> None:
        self.canvas.delete("selection")
        if hasattr(self, "toolbar") and self.toolbar.winfo_exists():
            self.toolbar.destroy()
        if hasattr(self, "translation_panel") and self.translation_panel.winfo_exists():
            self.translation_panel.destroy()

    def _draw_selection(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.canvas.delete("selection")
        crop = self.screenshot.crop((x1, y1, x2, y2))
        self.crop_photo = ImageTk.PhotoImage(crop)
        self.canvas.create_image(x1, y1, image=self.crop_photo, anchor="nw", tags="selection")
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#20a8ff", width=2, tags="selection")
        self.canvas.create_text(
            x1 + 5,
            max(10, y1 - 9),
            text=f"{x2 - x1} x {y2 - y1}",
            fill="white",
            anchor="w",
            font=("Microsoft YaHei UI", 9),
            tags="selection",
        )

    def _show_toolbar(self, x1: int, y1: int, x2: int, y2: int) -> None:
        if hasattr(self, "toolbar") and self.toolbar.winfo_exists():
            self.toolbar.destroy()
        self.toolbar = tk.Frame(self.window, bg="#202124", bd=1, relief="solid")
        actions = [
            ("复制", self.copy),
            ("保存", self.save),
            ("贴图", self.pin),
            ("英译中", self.translate),
            ("取消", self.cancel),
        ]
        for label, command in actions:
            tk.Button(
                self.toolbar,
                text=label,
                command=command,
                bg="#202124",
                fg="white",
                activebackground="#3c4043",
                activeforeground="white",
                bd=0,
                padx=12,
                pady=6,
                font=("Microsoft YaHei UI", 9),
            ).pack(side="left")
        self.toolbar_status = tk.Label(
            self.toolbar,
            text="",
            bg="#202124",
            fg="#ffd166",
            font=("Microsoft YaHei UI", 9),
        )
        self.toolbar_status.pack(side="left", padx=(4, 8))
        self.toolbar.update_idletasks()
        toolbar_x = min(max(0, x2 - self.toolbar.winfo_reqwidth()), self.screenshot.width - self.toolbar.winfo_reqwidth())
        toolbar_y = y2 + 6
        if toolbar_y + self.toolbar.winfo_reqheight() > self.screenshot.height:
            toolbar_y = max(0, y1 - self.toolbar.winfo_reqheight() - 6)
        self.toolbar.place(x=toolbar_x, y=toolbar_y)

    def _crop(self) -> Image.Image:
        if self.selection is None:
            raise ValueError("尚未选择截图区域")
        return self.screenshot.crop(self.selection)

    def copy(self) -> None:
        copy_image_to_clipboard(self._crop())
        self.close()

    def save(self) -> None:
        self.window.withdraw()
        destination = filedialog.asksaveasfilename(
            parent=self.owner.root,
            title="保存截图",
            initialdir=str(Path.home() / "Desktop"),
            defaultextension=".png",
            filetypes=(("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg;*.jpeg")),
        )
        if destination:
            image = self._crop()
            if Path(destination).suffix.lower() in {".jpg", ".jpeg"}:
                image = image.convert("RGB")
            image.save(destination, quality=96)
            self.close()
        else:
            self.window.deiconify()
            self.window.attributes("-topmost", True)

    def pin(self) -> None:
        x1, y1, _x2, _y2 = self.selection
        self.owner.screenshot_tool.create_pin(self._crop(), self.left + x1, self.top + y1)
        self.close()

    def translate(self) -> None:
        if hasattr(self, "toolbar_status"):
            self.toolbar_status.configure(text="识别翻译中...")
        self.owner.screenshot_tool.translate_image(self._crop(), self._translation_finished)

    def _translation_finished(self, status: str, original: str, translated: str) -> None:
        if not self.window.winfo_exists():
            return
        if hasattr(self, "toolbar_status"):
            self.toolbar_status.configure(text="")
        if status != "ok":
            messagebox.showerror("截图英译中", translated, parent=self.window)
            return
        if hasattr(self, "translation_panel") and self.translation_panel.winfo_exists():
            self.translation_panel.destroy()
        self.translation_panel = tk.Frame(self.window, bg="#f5f6f8", bd=1, relief="solid", width=430, height=330)
        self.translation_panel.pack_propagate(False)
        header = tk.Frame(self.translation_panel, bg="#f5f6f8")
        header.pack(fill="x", padx=10, pady=(9, 5))
        tk.Label(header, text="截图英译中", bg="#f5f6f8", fg="#202124", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Button(header, text="关闭", command=self.translation_panel.destroy, bg="#e5e7eb", fg="#202124", bd=0, padx=9, pady=3).pack(side="right")
        tk.Button(header, text="复制中文", command=lambda: self._copy_text(translated), bg="#1677ff", fg="white", bd=0, padx=10, pady=3).pack(side="right", padx=(0, 6))
        tk.Label(self.translation_panel, text="英文原文", bg="#f5f6f8", fg="#5f6368").pack(anchor="w", padx=10)
        original_box = tk.Text(self.translation_panel, height=5, wrap="word", font=("Microsoft YaHei UI", 9), bd=1, relief="solid")
        original_box.pack(fill="both", expand=True, padx=10, pady=(3, 7))
        original_box.insert("1.0", original)
        original_box.configure(state="disabled")
        tk.Label(self.translation_panel, text="中文翻译", bg="#f5f6f8", fg="#5f6368").pack(anchor="w", padx=10)
        translated_box = tk.Text(self.translation_panel, height=6, wrap="word", font=("Microsoft YaHei UI", 10), bd=1, relief="solid")
        translated_box.pack(fill="both", expand=True, padx=10, pady=(3, 10))
        translated_box.insert("1.0", translated)

        x1, y1, x2, _y2 = self.selection
        panel_w, panel_h = 430, 330
        panel_x = x2 + 8 if x2 + panel_w + 8 <= self.screenshot.width else max(8, x1 - panel_w - 8)
        panel_y = min(max(8, y1), max(8, self.screenshot.height - panel_h - 8))
        self.translation_panel.place(x=panel_x, y=panel_y)

    def _copy_text(self, text: str) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update()

    def cancel(self) -> None:
        self.close()

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()
        self.on_finish()


class ScreenshotController:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.requests: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.results: queue.SimpleQueue[tuple[str, str, str, object]] = queue.SimpleQueue()
        self.hotkey = F1Hotkey(self.requests)
        self.overlay = None
        self.pins: list[PinnedImage] = []
        self.poll_job = owner.root.after(80, self._poll_requests)

    def _poll_requests(self) -> None:
        try:
            while self.requests.get_nowait() == "capture":
                self.start_capture()
        except queue.Empty:
            pass
        try:
            while True:
                status, original, translated, callback = self.results.get_nowait()
                if callback is not None:
                    callback(status, original, translated)
                elif status == "ok":
                    TranslationWindow(self.owner.root, original, translated)
                else:
                    messagebox.showerror("截图英译中", translated, parent=self.owner.root)
        except queue.Empty:
            pass
        self.poll_job = self.owner.root.after(80, self._poll_requests)

    def start_capture(self) -> None:
        if self.overlay is not None:
            return
        self.owner.root.withdraw()
        self.owner.root.update_idletasks()
        self.owner.root.after(260, self._capture_desktop)

    def _capture_desktop(self) -> None:
        bounds = self.owner.bounds
        screenshot = ImageGrab.grab(
            bbox=(bounds.left, bounds.top, bounds.left + bounds.width, bounds.top + bounds.height),
            all_screens=True,
        ).convert("RGB")
        self.overlay = ScreenshotOverlay(
            self.owner,
            screenshot,
            bounds.left,
            bounds.top,
            self._capture_finished,
        )

    def _capture_finished(self) -> None:
        self.overlay = None
        self.owner.root.deiconify()
        self.owner.root.attributes("-topmost", self.owner.topmost_var.get())
        self.owner._set_window_position(self.owner.x, self.owner.base_y)

    def create_pin(self, image: Image.Image, x: int, y: int) -> None:
        pin = PinnedImage(self, image, x, y, self._remove_pin)
        self.pins.append(pin)

    def translate_image(self, image: Image.Image, callback=None) -> None:
        threading.Thread(
            target=self._translate_worker,
            args=(image.copy(), callback),
            name="PetScreenshotTranslation",
            daemon=True,
        ).start()

    def _translate_worker(self, image: Image.Image, callback) -> None:
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR()
            result, _elapsed = engine(np.asarray(image.convert("RGB")))
            lines = [item[1].strip() for item in (result or []) if len(item) >= 3 and item[1].strip() and item[2] >= 0.45]
            original = "\n".join(lines)
            if not original:
                raise ValueError("没有识别到清晰的英文文字，请重新框选文字区域。")
            translated = translate_english_to_chinese(original)
            if not translated:
                raise ValueError("翻译服务没有返回内容。")
            self.results.put(("ok", original, translated, callback))
        except Exception as exc:
            self.results.put(("error", "", f"英译中失败：{exc}", callback))

    def _remove_pin(self, pin: PinnedImage) -> None:
        if pin in self.pins:
            self.pins.remove(pin)

    def close(self) -> None:
        if self.poll_job:
            self.owner.root.after_cancel(self.poll_job)
        self.hotkey.close()
        if self.overlay is not None:
            self.overlay.window.destroy()
            self.overlay = None
        for pin in list(self.pins):
            pin.close()
