"""Check and install published Windows releases without blocking the UI."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from version import APP_VERSION

API = "https://api.github.com/repos/Sweeney817/-/releases/latest"
EXE_NAME = "OrangeCatDesktopPet.exe"
HASH_NAME = EXE_NAME + ".sha256"
MAX_DOWNLOAD = 1024 * 1024 * 1024
HEADERS = {"User-Agent": "OrangeCatDesktopPet-updater", "Accept": "application/vnd.github+json"}


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("版本号格式不正确")
    return tuple(map(int, match.groups()))


def read_url(url: str, limit: int) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=25) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("服务器响应过大")
    return data


def release_info() -> dict | None:
    release = json.loads(read_url(API, 2 * 1024 * 1024))
    if release.get("draft") or release.get("prerelease"):
        return None
    tag = release.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(APP_VERSION):
        return None
    assets = {a.get("name"): a for a in release.get("assets", [])}
    for name in (EXE_NAME, HASH_NAME):
        asset = assets.get(name, {})
        url = asset.get("browser_download_url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith("/Sweeney817/-/releases/download/"):
            raise ValueError(f"更新版本缺少有效的 {name}")
    size = assets[EXE_NAME].get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_DOWNLOAD:
        raise ValueError("更新文件大小无效")
    return {"version": tag, "exe": assets[EXE_NAME]["browser_download_url"],
            "hash": assets[HASH_NAME]["browser_download_url"], "size": size}


def download_release(info: dict, progress=None) -> Path:
    checksum = read_url(info["hash"], 4096).decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?OrangeCatDesktopPet\.exe)?", checksum)
    if not match:
        raise ValueError("更新校验文件格式不正确")
    expected = match.group(1).lower()
    folder = Path(tempfile.mkdtemp(prefix="orange-cat-update-"))
    path = folder / EXE_NAME
    try:
        digest = hashlib.sha256()
        total = 0
        with urlopen(Request(info["exe"], headers=HEADERS), timeout=60) as response, path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > info["size"] or total > MAX_DOWNLOAD:
                    raise ValueError("更新文件超过预期大小")
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    progress(total, info["size"])
        if total != info["size"] or digest.hexdigest() != expected:
            raise ValueError("更新文件大小或 SHA256 校验不匹配")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise


# The separate installer waits for the running pet to exit. Paths are passed as
# process arguments rather than interpolated into this script.
HELPER = r'''param([int]$PetPid, [string]$Target, [string]$Download)
$ErrorActionPreference = 'Stop'
$suffix = Split-Path -Leaf (Split-Path -Parent $Download)
$backup = "$Target.$suffix.backup"
$staged = "$Target.$suffix.new"
$moved = $false
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = '橘猫桌面宠物更新'
$form.Size = New-Object System.Drawing.Size(420, 140)
$form.StartPosition = 'CenterScreen'
$form.ControlBox = $false
$form.TopMost = $true
$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(18, 16)
$label.Size = New-Object System.Drawing.Size(370, 24)
$label.Text = '正在等待桌宠退出…'
$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = New-Object System.Drawing.Point(18, 48)
$bar.Size = New-Object System.Drawing.Size(370, 24)
$form.Controls.Add($label)
$form.Controls.Add($bar)
$form.Show()
[System.Windows.Forms.Application]::DoEvents()
try {
    Wait-Process -Id $PetPid -ErrorAction SilentlyContinue
    $label.Text = '正在复制更新文件… 0%'
    $inputStream = [System.IO.File]::OpenRead($Download)
    try {
        $outputStream = [System.IO.File]::Create($staged)
        try {
            $buffer = New-Object byte[] (1024 * 1024)
            $total = $inputStream.Length
            $copied = 0
            while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $outputStream.Write($buffer, 0, $count)
                $copied += $count
                $bar.Value = [Math]::Min(100, [int][Math]::Floor(100 * $copied / $total))
                $label.Text = "正在复制更新文件… $($bar.Value)%"
                [System.Windows.Forms.Application]::DoEvents()
            }
        } finally { $outputStream.Dispose() }
    } finally { $inputStream.Dispose() }
    $label.Text = '正在替换程序，请稍候…'
    $bar.Style = 'Marquee'
    [System.Windows.Forms.Application]::DoEvents()
    # PyInstaller's one-file launcher may still hold the EXE briefly after
    # the Python child exits. Retry while Windows releases the file handle.
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try { Move-Item -LiteralPath $Target -Destination $backup -ErrorAction Stop; break }
        catch { if ($attempt -eq 19) { throw }; [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 500 }
    }
    $moved = $true
    try { Move-Item -LiteralPath $staged -Destination $Target }
    catch { Move-Item -LiteralPath $backup -Destination $Target; throw }
    $label.Text = '更新完成，正在启动桌宠…'
    [System.Windows.Forms.Application]::DoEvents()
    Start-Process -FilePath $Target
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
} catch {
    if ($moved -and (Test-Path -LiteralPath $backup)) {
        if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue }
        Move-Item -LiteralPath $backup -Destination $Target -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $Target) { Start-Process -FilePath $Target -ErrorAction SilentlyContinue }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("更新失败，已尝试恢复原程序。请检查程序目录的写入权限。", '橘猫桌面宠物') | Out-Null
} finally {
    $form.Close()
    $form.Dispose()
    Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Split-Path -Parent $Download) -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
'''


class UpdateController:
    def __init__(self, pet):
        self.pet = pet
        self.results = queue.Queue()
        self.busy = False
        self.poll_id = None
        self.progress_window = None

    def check(self, automatic=False):
        if self.busy:
            if not automatic:
                messagebox.showinfo("软件更新", "正在检查或下载更新，请稍候。", parent=self.pet.root)
            return
        if not getattr(sys, "frozen", False):
            if not automatic:
                messagebox.showinfo("软件更新", "在线更新仅适用于打包后的 EXE。", parent=self.pet.root)
            return
        self.busy = True
        self._start_worker("check", release_info, automatic)

    def _start_worker(self, kind, function, automatic=False):
        def run():
            try:
                self.results.put((kind, function(), None, automatic))
            except Exception as exc:
                self.results.put((kind, None, str(exc), automatic))
        threading.Thread(target=run, daemon=True).start()
        self.poll_id = self.pet.root.after(100, self._poll)

    def _poll(self):
        self.poll_id = None
        try:
            kind, result, error, automatic = self.results.get_nowait()
        except queue.Empty:
            self.poll_id = self.pet.root.after(100, self._poll)
            return
        if error:
            self.busy = False
            self._close_progress()
            if not automatic or kind == "download":
                messagebox.showerror("软件更新", f"更新失败：{error}", parent=self.pet.root)
            return
        if kind == "progress":
            if self.progress_window:
                done, total = result
                percent = min(100, int(done * 100 / total))
                self.progress_bar["value"] = percent
                self.progress_label.configure(text="下载完成，正在校验…" if done == total else f"正在下载更新… {percent}%")
            self.poll_id = self.pet.root.after(1, self._poll)
            return
        if kind == "check":
            if not result:
                self.busy = False
                if not automatic:
                    messagebox.showinfo("软件更新", f"当前已是最新版本（{APP_VERSION}）。", parent=self.pet.root)
                return
            if not messagebox.askyesno("软件更新", f"发现新版本 {result['version']}（当前 {APP_VERSION}）。\n下载并安装更新？桌宠将重启。", parent=self.pet.root):
                self.busy = False
                return
            self._show_progress()
            self._start_worker("download", lambda: download_release(result, lambda done, total: self.results.put(("progress", (done, total), None, False))))
        else:
            try:
                self.progress_label.configure(text="校验完成，正在启动安装程序…")
                self.pet.root.update_idletasks()
                helper = result.parent / "install-update.ps1"
                helper.write_text(HELPER, encoding="utf-8-sig")
                subprocess.Popen(["powershell.exe", "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper), str(os.getpid()), sys.executable, str(result)], creationflags=subprocess.CREATE_NO_WINDOW)
                self.pet.quit()
            except Exception as exc:
                self.busy = False
                self._close_progress()
                messagebox.showerror("软件更新", f"无法启动更新程序：{exc}", parent=self.pet.root)

    def _show_progress(self):
        self.progress_window = tk.Toplevel(self.pet.root)
        self.progress_window.title("软件更新")
        self.progress_window.resizable(False, False)
        self.progress_window.attributes("-topmost", True)
        self.progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        self.progress_label = ttk.Label(self.progress_window, text="正在准备下载…")
        self.progress_label.pack(padx=20, pady=(16, 8))
        self.progress_bar = ttk.Progressbar(self.progress_window, length=300, maximum=100)
        self.progress_bar.pack(padx=20, pady=(0, 18))

    def _close_progress(self):
        if self.progress_window is not None:
            self.progress_window.destroy()
            self.progress_window = None

    def close(self):
        if self.poll_id is not None:
            self.pet.root.after_cancel(self.poll_id)
            self.poll_id = None
        self._close_progress()
