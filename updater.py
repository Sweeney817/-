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
from tkinter import messagebox
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


def download_release(info: dict) -> Path:
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
try {
    Wait-Process -Id $PetPid -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $Download -Destination $staged -Force
    Move-Item -LiteralPath $Target -Destination $backup
    $moved = $true
    try { Move-Item -LiteralPath $staged -Destination $Target }
    catch { Move-Item -LiteralPath $backup -Destination $Target; throw }
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
            if not automatic or kind == "download":
                messagebox.showerror("软件更新", f"更新失败：{error}", parent=self.pet.root)
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
            self._start_worker("download", lambda: download_release(result))
        else:
            try:
                helper = result.parent / "install-update.ps1"
                helper.write_text(HELPER, encoding="utf-8-sig")
                subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper), str(os.getpid()), sys.executable, str(result)], creationflags=subprocess.CREATE_NO_WINDOW)
                self.pet.quit()
            except Exception as exc:
                self.busy = False
                messagebox.showerror("软件更新", f"无法启动更新程序：{exc}", parent=self.pet.root)

    def close(self):
        if self.poll_id is not None:
            self.pet.root.after_cancel(self.poll_id)
            self.poll_id = None
