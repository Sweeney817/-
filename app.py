from __future__ import annotations

import ctypes
import json
import math
import os
import random
import sys
import time
import tkinter as tk
import winreg
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageOps, ImageTk

from screenshot_tool import ScreenshotController


APP_NAME = "OrangeCatDesktopPet"
DISPLAY_NAME = "橘猫桌面宠物"
TRANSPARENT = "#01fe02"
CELL_W = 192
CELL_H = 208
ATLAS_COLUMNS = 4
DEFAULT_SCALE = 0.8
MIN_SCALE = 0.45
MAX_SCALE = 1.1
TICK_MS = 16
IDLE_TICK_MS = 100

ROW_FRAMES = {
    "idle": (0, 4),
    "walk_right": (1, 4),
    "wave": (2, 4),
    "jump": (3, 4),
    "rest": (4, 4),
    "observe": (5, 4),
    "play": (6, 4),
    "drink": (7, 4),
}

FPS = {
    "idle": 1.8,
    "walk_right": 5.2,
    "walk_left": 5.2,
    "wave": 3.2,
    "jump": 3.0,
    "rest": 1.0,
    "observe": 1.6,
    "play": 3.0,
    "drink": 3.2,
}


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def settings_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def executable_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


@dataclass
class DesktopBounds:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def current(cls) -> "DesktopBounds":
        user32 = ctypes.windll.user32
        return cls(
            user32.GetSystemMetrics(76),
            user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78),
            user32.GetSystemMetrics(79),
        )


class OrangeCatPet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(DISPLAY_NAME)
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANSPARENT)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        self.settings = self._load_settings()
        saved_scale = float(self.settings.get("scale", DEFAULT_SCALE))
        self.scale = saved_scale if MIN_SCALE <= saved_scale <= MAX_SCALE else DEFAULT_SCALE
        self._update_window_size()

        self.canvas = tk.Canvas(
            self.root,
            width=self.window_w,
            height=self.window_h,
            bg=TRANSPARENT,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack()

        self.frames = self._load_frames()
        self.image_item = self.canvas.create_image(
            self.window_w // 2,
            self.window_h - 4,
            image=self.frames["idle"][0],
            anchor="s",
        )
        self.current_frame_key: tuple[str, int] | None = ("idle", 0)
        self.last_window_position: tuple[int, int] | None = None
        self._create_water_bowl()

        self.bounds = DesktopBounds.current()
        default_x = self.bounds.left + self.bounds.width - self.window_w - 72
        default_y = self.bounds.top + self.bounds.height - self.window_h - 54
        self.x = float(self.settings.get("x", default_x))
        self.base_y = float(self.settings.get("y", default_y))
        self._clamp_position()

        self.state = "idle"
        self.state_started = time.perf_counter()
        self.state_duration = 3.0
        self.last_tick = self.state_started
        self.energy = 0.82
        self.thirst = 0.18
        self.play_streak = 0
        self.paused = False
        self.dragging = False
        self.drag_pointer = (0, 0)
        self.drag_origin = (0.0, 0.0)
        self.topmost_var = tk.BooleanVar(value=self.settings.get("topmost", True))
        self.autostart_var = tk.BooleanVar(value=self._autostart_enabled())
        self._build_menu()
        self._bind_controls()
        self.screenshot_tool = ScreenshotController(self)

        self.root.geometry(f"{self.window_w}x{self.window_h}")
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.attributes("-topmost", self.topmost_var.get())
        client_hwnd = self.root.winfo_id()
        self.hwnd = ctypes.windll.user32.GetParent(client_hwnd) or client_hwnd
        self._set_window_position(self.x, self.base_y)
        self._enter_state("idle", 2.4)
        self.root.after(TICK_MS, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def _load_frames(self) -> dict[str, list[ImageTk.PhotoImage]]:
        with Image.open(resource_path("spritesheet.png")) as source:
            atlas = source.convert("RGBA")
        expected = (CELL_W * ATLAS_COLUMNS, CELL_H * len(ROW_FRAMES))
        if atlas.size != expected:
            raise ValueError(f"动画图集尺寸错误：应为 {expected[0]}x{expected[1]}")

        target = (round(CELL_W * self.scale), round(CELL_H * self.scale))
        loaded: dict[str, list[ImageTk.PhotoImage]] = {}
        alpha_lut = [0] * 72 + [255] * 184
        for state, (row, count) in ROW_FRAMES.items():
            state_frames = []
            left_frames = []
            for column in range(count):
                box = (
                    column * CELL_W,
                    row * CELL_H,
                    (column + 1) * CELL_W,
                    (row + 1) * CELL_H,
                )
                frame = atlas.crop(box)
                frame = frame.resize(target, Image.Resampling.LANCZOS)
                # Windows color-key transparency blends semi-transparent edges with
                # the key color. A binary alpha edge prevents the visible green rim.
                alpha = frame.getchannel("A").point(alpha_lut)
                frame.putalpha(alpha)
                state_frames.append(ImageTk.PhotoImage(frame))
                if state == "walk_right":
                    left_frames.append(ImageTk.PhotoImage(ImageOps.mirror(frame)))
            loaded[state] = state_frames
            if left_frames:
                loaded["walk_left"] = left_frames
        return loaded

    def _create_water_bowl(self) -> None:
        self.canvas.create_oval(0, 0, 1, 1, fill="#4c6473", outline="#26343d", width=2, tags=("bowl", "bowl_outer"))
        self.canvas.create_oval(0, 0, 1, 1, fill="#8fd3e7", outline="#d7f5fb", width=2, tags=("bowl", "bowl_water"))
        self.canvas.create_arc(0, 0, 1, 1, start=8, extent=164, style="arc", outline="#ffffff", width=1, tags=("bowl", "bowl_glint"))
        self._position_water_bowl()
        self.canvas.itemconfigure("bowl", state="hidden")

    def _position_water_bowl(self) -> None:
        center_x = self.window_w / 2 + 72 * self.scale
        bottom = self.window_h - 6
        self.canvas.coords("bowl_outer", center_x - 23*self.scale, bottom - 9*self.scale, center_x + 23*self.scale, bottom)
        self.canvas.coords("bowl_water", center_x - 21*self.scale, bottom - 13*self.scale, center_x + 21*self.scale, bottom - 5*self.scale)
        self.canvas.coords("bowl_glint", center_x - 16*self.scale, bottom - 12*self.scale, center_x + 16*self.scale, bottom - 7*self.scale)

    def _update_window_size(self) -> None:
        self.window_w = round(CELL_W * self.scale + 44)
        self.window_h = round(CELL_H * self.scale + 28)

    def _load_settings(self) -> dict:
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            for key in ("scale", "x", "y"):
                value = data.get(key)
                if key in data and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    data.pop(key, None)
            if not isinstance(data.get("topmost", True), bool):
                data.pop("topmost", None)
            return data
        except (OSError, ValueError, OverflowError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "x": round(self.x),
            "y": round(self.base_y),
            "scale": round(self.scale, 2),
            "topmost": self.topmost_var.get(),
        }
        try:
            settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="截图（F1）", command=self.start_screenshot)
        self.menu.add_separator()
        self.menu.add_command(label="暂停活动", command=self.toggle_pause)
        self.menu.add_command(label="陪它玩一下", command=lambda: self._interact("play", 5.0))
        self.menu.add_command(label="给它喝水", command=lambda: self._interact("drink", 6.0))
        self.menu.add_command(label="让它休息", command=lambda: self._interact("rest", 10.0))
        self.menu.add_command(label="和它打招呼", command=lambda: self._interact("wave", 3.6))
        size_menu = tk.Menu(self.menu, tearoff=False)
        size_menu.add_command(label="迷你", command=lambda: self._set_scale(0.5))
        size_menu.add_command(label="很小", command=lambda: self._set_scale(0.65))
        size_menu.add_command(label="较小", command=lambda: self._set_scale(0.8))
        size_menu.add_command(label="小", command=lambda: self._set_scale(1.0))
        self.menu.add_cascade(label="显示大小", menu=size_menu)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="保持在最前面", variable=self.topmost_var, command=self._toggle_topmost)
        self.menu.add_checkbutton(label="开机自动出现", variable=self.autostart_var, command=self._toggle_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

    def _bind_controls(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Double-Button-1>", lambda _event: self._interact("wave", 3.6))
        self.canvas.bind("<MouseWheel>", self._mousewheel_scale)

    def _mousewheel_scale(self, event: tk.Event) -> None:
        step = 0.1 if event.delta > 0 else -0.1
        self._set_scale(self.scale + step)

    def _set_scale(self, scale: float) -> None:
        new_scale = round(min(MAX_SCALE, max(MIN_SCALE, scale)), 2)
        if new_scale == self.scale:
            return
        self.scale = new_scale
        self._update_window_size()
        self.frames = self._load_frames()
        self.current_frame_key = None
        self.canvas.configure(width=self.window_w, height=self.window_h)
        self.canvas.coords(self.image_item, self.window_w // 2, self.window_h - 4)
        self._position_water_bowl()
        self._clamp_position()
        self.root.geometry(f"{self.window_w}x{self.window_h}")
        self.root.update_idletasks()
        self.last_window_position = None
        self._set_window_position(self.x, self.base_y)
        self._update_frame(time.perf_counter() - self.state_started, forced_state="idle" if self.paused else None)
        self._save_settings()

    def _show_menu(self, event: tk.Event) -> None:
        self.menu.entryconfigure(2, label="继续活动" if self.paused else "暂停活动")
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_screenshot(self) -> None:
        self.screenshot_tool.start_capture()

    def _drag_start(self, event: tk.Event) -> None:
        self.dragging = True
        self.drag_started = time.perf_counter()
        self.drag_pointer = (event.x_root, event.y_root)
        self.drag_origin = (self.x, self.base_y)

    def _drag_move(self, event: tk.Event) -> None:
        dx = event.x_root - self.drag_pointer[0]
        dy = event.y_root - self.drag_pointer[1]
        self.x = self.drag_origin[0] + dx
        self.base_y = self.drag_origin[1] + dy
        self._clamp_position()
        self._set_window_position(self.x, self.base_y)

    def _drag_end(self, _event: tk.Event) -> None:
        if self.dragging:
            self.state_started += time.perf_counter() - self.drag_started
        self.dragging = False
        self._save_settings()

    def _clamp_position(self) -> None:
        right = self.bounds.left + self.bounds.width - self.window_w
        bottom = self.bounds.top + self.bounds.height - self.window_h - 32
        self.x = min(max(self.x, self.bounds.left), right)
        self.base_y = min(max(self.base_y, self.bounds.top), bottom)

    def _set_window_position(self, x: float, y: float) -> None:
        target = (round(x), round(y))
        if self.last_window_position == target:
            return
        if not hasattr(self, "hwnd"):
            self.root.geometry(f"{self.window_w}x{self.window_h}{target[0]:+d}{target[1]:+d}")
            self.last_window_position = target
            return
        ctypes.windll.user32.SetWindowPos(
            self.hwnd,
            0,
            target[0],
            target[1],
            0,
            0,
            0x0001 | 0x0004 | 0x0010,
        )
        self.last_window_position = target

    def _enter_state(self, state: str, duration: float | None = None) -> None:
        now = time.perf_counter()
        self.state = state
        self.state_started = now
        if duration is None:
            ranges = {
                "idle": (2.8, 6.5),
                "walk_right": (5.5, 11.0),
                "walk_left": (5.5, 11.0),
                "wave": (2.5, 4.2),
                "jump": (1.25, 1.55),
                "rest": (8.0, 17.0),
                "observe": (3.0, 6.2),
                "play": (4.2, 7.2),
                "drink": (5.5, 8.5),
            }
            low, high = ranges[state]
            duration = random.uniform(low, high)
        self.state_duration = duration
        self.canvas.itemconfigure("bowl", state="normal" if state == "drink" else "hidden")
        if state == "play":
            self.play_streak += 1
        elif state not in {"jump", "wave"}:
            self.play_streak = max(0, self.play_streak - 1)

    def _choose_next_state(self) -> None:
        if self.thirst >= 0.76 or (self.play_streak >= 2 and self.thirst >= 0.46):
            self._enter_state("drink")
            return
        if self.energy <= 0.24:
            self._enter_state("rest")
            return

        choices = ["walk", "idle", "observe", "play", "jump", "wave"]
        weights = [30, 22, 14, 16, 9, 9]
        if self.state.startswith("walk"):
            weights = [16, 30, 18, 15, 11, 10]
        action = random.choices(choices, weights=weights, k=1)[0]
        current_action = "walk" if self.state.startswith("walk") else self.state
        if action == current_action:
            alternatives = [(choice, weight) for choice, weight in zip(choices, weights) if choice != current_action]
            action = random.choices(
                [choice for choice, _weight in alternatives],
                weights=[weight for _choice, weight in alternatives],
                k=1,
            )[0]
        if action == "walk":
            center = self.bounds.left + self.bounds.width / 2
            if self.x < self.bounds.left + 36:
                direction = "walk_right"
            elif self.x > self.bounds.left + self.bounds.width - self.window_w - 36:
                direction = "walk_left"
            else:
                toward_center = random.random() < 0.62
                direction = "walk_right" if (self.x < center) == toward_center else "walk_left"
            self._enter_state(direction)
        else:
            self._enter_state(action)

    def _tick(self) -> None:
        now = time.perf_counter()
        # Limit catch-up after sleep or a blocked UI, while allowing the slower
        # stationary timer to account for the full interval between ticks.
        dt = min(now - self.last_tick, 0.25)
        self.last_tick = now

        if not self.paused and not self.dragging:
            elapsed = now - self.state_started
            self._update_needs(dt)
            if elapsed >= self.state_duration:
                self._choose_next_state()
                elapsed = 0.0
            self._update_position(dt, elapsed)
            self._update_frame(elapsed)
        elif self.paused:
            elapsed = now - self.state_started
            self._update_frame(elapsed, forced_state="idle")

        moving = not self.paused and not self.dragging and self.state in {
            "walk_left", "walk_right", "jump", "play"
        }
        self.root.after(TICK_MS if moving else IDLE_TICK_MS, self._tick)

    def _update_needs(self, dt: float) -> None:
        self.thirst = min(1.0, self.thirst + dt * 0.0048)
        if self.state.startswith("walk"):
            self.energy = max(0.0, self.energy - dt * 0.008)
            self.thirst = min(1.0, self.thirst + dt * 0.006)
        elif self.state in {"play", "jump"}:
            self.energy = max(0.0, self.energy - dt * 0.021)
            self.thirst = min(1.0, self.thirst + dt * 0.016)
        elif self.state == "rest":
            self.energy = min(1.0, self.energy + dt * 0.045)
        elif self.state == "drink":
            self.thirst = max(0.04, self.thirst - dt * 0.15)
            self.energy = min(1.0, self.energy + dt * 0.008)
        else:
            self.energy = min(1.0, self.energy + dt * 0.004)

    def _update_position(self, dt: float, elapsed: float) -> None:
        if self.state == "walk_right":
            self.x += 82.0 * dt
        elif self.state == "walk_left":
            self.x -= 82.0 * dt

        left = self.bounds.left
        right = self.bounds.left + self.bounds.width - self.window_w
        if self.x <= left and self.state == "walk_left":
            self.x = left
            self._enter_state("walk_right")
        elif self.x >= right and self.state == "walk_right":
            self.x = right
            self._enter_state("walk_left")

        offset_y = 0.0
        if self.state == "jump":
            progress = min(elapsed / max(self.state_duration, 0.01), 1.0)
            offset_y = -74.0 * math.sin(math.pi * progress)
        elif self.state == "play":
            offset_y = -2.0 * max(0.0, math.sin(elapsed * math.pi * 2.0))
        self._set_window_position(self.x, self.base_y + offset_y)

    def _update_frame(self, elapsed: float, forced_state: str | None = None) -> None:
        state = forced_state or self.state
        frames = self.frames[state]
        if state == "jump":
            progress = min(max(elapsed / max(self.state_duration, 0.01), 0.0), 1.0)
            index = min(int(progress * len(frames)), len(frames) - 1)
        else:
            index = int(elapsed * FPS[state]) % len(frames)
        frame_key = (state, index)
        if self.current_frame_key == frame_key:
            return
        self.canvas.itemconfigure(self.image_item, image=frames[index])
        self.current_frame_key = frame_key

    def _interact(self, state: str, duration: float) -> None:
        # Explicit interactions resume activity so their action is visible.
        self.paused = False
        self._enter_state(state, duration)
        if self.dragging:
            self.drag_started = self.state_started
        self._update_frame(0)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.state_started = time.perf_counter()
        if self.paused:
            self.canvas.itemconfigure("bowl", state="hidden")
            self._set_window_position(self.x, self.base_y)
            self._update_frame(0, forced_state="idle")
        else:
            self._enter_state("idle", 1.8)

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self.topmost_var.get())
        self._save_settings()

    def _autostart_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False

    def _toggle_autostart(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if self.autostart_var.get():
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, executable_command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            self.autostart_var.set(not self.autostart_var.get())
            messagebox.showerror(DISPLAY_NAME, f"无法修改开机启动设置：{exc}")

    def quit(self) -> None:
        self._save_settings()
        self.screenshot_tool.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def acquire_single_instance() -> object:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}-Singleton")
    if not handle or kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "橘猫已经在桌面上了。", DISPLAY_NAME, 0x40)
        raise SystemExit(0)
    return handle


if __name__ == "__main__":
    mutex = acquire_single_instance()
    try:
        OrangeCatPet().run()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}", DISPLAY_NAME, 0x10)
        raise
