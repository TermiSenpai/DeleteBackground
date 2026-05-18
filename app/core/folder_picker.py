"""Native folder-picker dialogs for the local UI.

The picker is called from the FastAPI ``/api/folder/pick`` endpoint and runs
in the same process as the server. The Windows implementation talks directly
to ``SHBrowseForFolderW`` via :mod:`ctypes` — no subprocess, no PowerShell,
no .NET. That matters in the PyInstaller EXE bundle, where spawning a hidden
``powershell.exe`` to host a WinForms dialog turned out to be fragile (the
dialog frequently opened behind the browser, or never surfaced at all under
``CREATE_NO_WINDOW``).

On non-Windows hosts we keep the existing approach of launching a tiny
tkinter subprocess; that path is exercised only by local development on
macOS / Linux and is not bundled into a frozen executable.
"""

from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import sys
from ctypes import wintypes
from typing import Optional

logger = logging.getLogger(__name__)


_TK_PICKER_SCRIPT: str = r"""
import json
import sys

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:  # pragma: no cover - only on broken installs.
    print(json.dumps({"path": "", "error": "tkinter unavailable: " + str(exc)}))
    raise SystemExit(0)

initial = sys.argv[1] if len(sys.argv) > 1 else ""
title = sys.argv[2] if len(sys.argv) > 2 else "Choose folder"

root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except tk.TclError:
    pass

selected = filedialog.askdirectory(
    initialdir=initial or None,
    title=title,
    mustexist=True,
)
root.destroy()
print(json.dumps({"path": selected or ""}))
"""


if sys.platform == "win32":
    _shell32 = ctypes.windll.shell32
    _ole32 = ctypes.windll.ole32
    _user32 = ctypes.windll.user32

    _MAX_PATH = 260

    # SHBrowseForFolderW BROWSEINFO flags.
    _BIF_RETURNONLYFSDIRS = 0x00000001
    _BIF_EDITBOX = 0x00000010
    _BIF_NEWDIALOGSTYLE = 0x00000040
    _BIF_USENEWUI = _BIF_NEWDIALOGSTYLE | _BIF_EDITBOX

    # BFFM callback messages.
    _BFFM_INITIALIZED = 1
    _BFFM_SETSELECTIONW = 0x467

    # CoInitializeEx flags. SHBrowseForFolder requires an STA thread when
    # used with the new (Vista+) dialog style.
    _COINIT_APARTMENTTHREADED = 0x2
    _COINIT_DISABLE_OLE1DDE = 0x4

    # SetWindowPos flags used to surface the dialog above the browser.
    _HWND_TOPMOST = -1
    _HWND_NOTOPMOST = -2
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_SHOWWINDOW = 0x0040
    _SWP_NOACTIVATE = 0x0010

    class _BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", ctypes.c_wchar_p),
            ("lpszTitle", ctypes.c_wchar_p),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    _BFFCALLBACK = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.LPARAM,
        wintypes.LPARAM,
    )

    _shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW)]
    _shell32.SHBrowseForFolderW.restype = ctypes.c_void_p

    _shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    _shell32.SHGetPathFromIDListW.restype = wintypes.BOOL

    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    _ole32.CoTaskMemFree.restype = None

    _ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _ole32.CoInitializeEx.restype = ctypes.c_long

    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None

    _user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.SendMessageW.restype = wintypes.LPARAM

    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL

    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL

    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL

    def _pick_folder_windows(initial_dir: str, title: str) -> str:
        """Open the Windows folder-picker dialog and return the selected path.

        Returns an empty string when the user cancels. Raises :class:`OSError`
        on unrecoverable Win32 errors.
        """
        hr = _ole32.CoInitializeEx(
            None, _COINIT_APARTMENTTHREADED | _COINIT_DISABLE_OLE1DDE
        )
        # S_OK=0 and S_FALSE=1 (already initialised on this thread) are both
        # fine; only a negative HRESULT indicates a real failure.
        if hr < 0:
            raise OSError(f"CoInitializeEx failed: 0x{hr & 0xFFFFFFFF:08X}")

        # The callback needs to keep the initial-path buffer alive for as long
        # as the dialog is open; the closure captures both refs here.
        initial_ref: Optional[ctypes.c_wchar_p] = (
            ctypes.c_wchar_p(initial_dir) if initial_dir else None
        )

        def _callback(hwnd, u_msg, l_param, lp_data):  # noqa: ANN001
            if u_msg == _BFFM_INITIALIZED:
                # The browser was the foreground window when the user clicked
                # "Choose folder", so the dialog inherits the wrong z-order.
                # Force it above everything else, then drop the topmost bit so
                # the user can still alt-tab to other windows normally.
                try:
                    _user32.SetWindowPos(
                        hwnd,
                        _HWND_TOPMOST,
                        0, 0, 0, 0,
                        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
                    )
                    _user32.SetWindowPos(
                        hwnd,
                        _HWND_NOTOPMOST,
                        0, 0, 0, 0,
                        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
                    )
                    _user32.BringWindowToTop(hwnd)
                    _user32.SetForegroundWindow(hwnd)
                except OSError:  # pragma: no cover - defensive only
                    logger.debug("Could not surface folder dialog window.")

                if initial_ref is not None:
                    addr = ctypes.cast(initial_ref, ctypes.c_void_p).value or 0
                    _user32.SendMessageW(
                        hwnd, _BFFM_SETSELECTIONW, 1, addr
                    )
            return 0

        callback_ref = _BFFCALLBACK(_callback)

        try:
            bi = _BROWSEINFOW()
            bi.hwndOwner = None
            bi.pidlRoot = None
            bi.pszDisplayName = None
            bi.lpszTitle = title or "Choose folder"
            bi.ulFlags = _BIF_RETURNONLYFSDIRS | _BIF_USENEWUI
            bi.lpfn = ctypes.cast(callback_ref, ctypes.c_void_p)
            bi.lParam = 0
            bi.iImage = 0

            pidl = _shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(_MAX_PATH * 2)
                if not _shell32.SHGetPathFromIDListW(pidl, buf):
                    return ""
                return buf.value
            finally:
                _ole32.CoTaskMemFree(pidl)
        finally:
            _ole32.CoUninitialize()


def _pick_folder_tk(initial_dir: str, title: str) -> str:
    """Open a tkinter dialog in a child interpreter (non-Windows hosts).

    We deliberately spawn a subprocess so the dialog's own Tk runtime cannot
    deadlock against the FastAPI server's event loop.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            _TK_PICKER_SCRIPT,
            initial_dir or "",
            title or "Choose folder",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(
            message or f"Folder picker exited with code {result.returncode}."
        )

    raw = result.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OSError(f"Folder picker returned invalid output: {raw!r}") from exc
    if payload.get("error"):
        raise OSError(str(payload["error"]))
    return str(payload.get("path", "") or "")


def pick_folder(initial_dir: str, title: str) -> str:
    """Open the host's native folder-picker dialog.

    Returns the selected absolute path, or an empty string when the user
    cancels. Raises :class:`OSError` on unrecoverable platform errors.
    """
    if sys.platform == "win32":
        return _pick_folder_windows(initial_dir, title)
    return _pick_folder_tk(initial_dir, title)
