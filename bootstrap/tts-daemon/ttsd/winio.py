"""Standard-handle I/O for the console-free Windows executable.

PyInstaller's windowed bootloader deliberately sets ``sys.stdin`` and friends
to ``None``. Hook hosts still pass JSON through an inherited pipe, so read and
write that pipe through Win32 directly. Source-mode tests keep normal stdio.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_BROKEN_PIPE = 109


def _std_handle(which: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel32.GetStdHandle(which)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    return kernel32, handle


def read_stdin_bytes(limit: int = 256 * 1024) -> bytes:
    stream = getattr(sys, "stdin", None)
    if stream is not None:
        try:
            return stream.buffer.read(limit)
        except (AttributeError, OSError):
            try:
                return stream.read(limit).encode("utf-8")
            except (AttributeError, OSError):
                return b""
    if os.name != "nt":
        return b""
    resolved = _std_handle(STD_INPUT_HANDLE)
    if resolved is None:
        return b""
    kernel32, handle = resolved
    kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                  wintypes.LPVOID]
    kernel32.ReadFile.restype = wintypes.BOOL
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        size = min(8192, remaining)
        buf = ctypes.create_string_buffer(size)
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None):
            if ctypes.get_last_error() == ERROR_BROKEN_PIPE:
                break
            return b"".join(chunks)
        if read.value == 0:
            break
        chunks.append(buf.raw[:read.value])
        remaining -= read.value
    return b"".join(chunks)


def write_stdout(value: str) -> None:
    data = value.encode("utf-8")
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            stream.write(value)
            stream.flush()
            return
        except OSError:
            pass
    if os.name != "nt":
        return
    resolved = _std_handle(STD_OUTPUT_HANDLE)
    if resolved is None:
        return
    kernel32, handle = resolved
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                   wintypes.LPVOID]
    kernel32.WriteFile.restype = wintypes.BOOL
    written = wintypes.DWORD()
    kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None)
