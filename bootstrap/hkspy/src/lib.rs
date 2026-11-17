// hkspy: names the process that owns a Windows global hotkey.
//
// Windows has no API that says who registered a hotkey (RegisterHotKey only
// fails with ERROR_HOTKEY_ALREADY_REGISTERED). But the owner receives the
// hotkey as a WM_HOTKEY message, and a global WH_GETMESSAGE hook runs inside
// every GUI thread that retrieves a message. So: install this DLL's hook_proc
// with SetWindowsHookExW(WH_GETMESSAGE, ..., 0), press the chord, and the hook
// writes one line naming the receiving process.
//
// Configured through a named shared-memory block the loader creates
// (CONFIG_NAME). Without it the hook does nothing at all, so a copy of this DLL
// left loaded in some process after the loader unhooks is inert.
//
// Layout of the block (little-endian):
//   0..4   magic  0x5950_534B ("KSPY")
//   4..8   flags  bit 0: swallow - turn the WM_HOTKEY into WM_NULL so the
//                 owner never acts on the probe press
//   8..    UTF-16 log path, NUL-terminated, at most 1024 units
//
// Log line (tab-separated, UTF-8):
//   pid  tid  hwnd  hotkey-id  modifiers  vk  window-class  window-title  exe
#![allow(non_snake_case)]
#![allow(clippy::missing_safety_doc)]

use std::io::Write;

const WM_HOTKEY: u32 = 0x0312;
const WM_NULL: u32 = 0x0000;
const PM_REMOVE: usize = 0x0001;
const FILE_MAP_READ: u32 = 0x0004;
const MAGIC: u32 = 0x5950_534B;
const CONFIG_NAME: &str = "Local\\hkspy-config";
const CONFIG_BYTES: usize = 8 + 2 * 1025;

#[repr(C)]
struct MSG {
    hwnd: isize,
    message: u32,
    wParam: usize,
    lParam: isize,
    time: u32,
    pt: [i32; 2],
}

#[link(name = "user32")]
extern "system" {
    fn CallNextHookEx(hook: isize, code: i32, w: usize, l: isize) -> isize;
    fn GetClassNameW(hwnd: isize, buf: *mut u16, n: i32) -> i32;
    fn GetWindowTextW(hwnd: isize, buf: *mut u16, n: i32) -> i32;
}

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentProcessId() -> u32;
    fn GetCurrentThreadId() -> u32;
    fn GetModuleFileNameW(module: isize, buf: *mut u16, n: u32) -> u32;
    fn OpenFileMappingW(access: u32, inherit: i32, name: *const u16) -> isize;
    fn MapViewOfFile(map: isize, access: u32, hi: u32, lo: u32, bytes: usize) -> *const u8;
    fn UnmapViewOfFile(view: *const u8) -> i32;
    fn CloseHandle(h: isize) -> i32;
}

struct Config {
    swallow: bool,
    log: String,
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}

fn read_config() -> Option<Config> {
    unsafe {
        let name = wide(CONFIG_NAME);
        let map = OpenFileMappingW(FILE_MAP_READ, 0, name.as_ptr());
        if map == 0 {
            return None;
        }
        let view = MapViewOfFile(map, FILE_MAP_READ, 0, 0, CONFIG_BYTES);
        if view.is_null() {
            CloseHandle(map);
            return None;
        }
        let bytes = std::slice::from_raw_parts(view, CONFIG_BYTES);
        let magic = u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        let flags = u32::from_le_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]);
        let units: Vec<u16> = bytes[8..]
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .take_while(|&u| u != 0)
            .collect();
        UnmapViewOfFile(view);
        CloseHandle(map);
        if magic != MAGIC || units.is_empty() {
            return None;
        }
        Some(Config { swallow: flags & 1 != 0, log: String::from_utf16_lossy(&units) })
    }
}

fn text(f: unsafe extern "system" fn(isize, *mut u16, i32) -> i32, hwnd: isize) -> String {
    if hwnd == 0 {
        return String::new();
    }
    let mut buf = [0u16; 256];
    let n = unsafe { f(hwnd, buf.as_mut_ptr(), buf.len() as i32) }.max(0) as usize;
    String::from_utf16_lossy(&buf[..n]).replace(['\t', '\r', '\n'], " ")
}

fn exe_path() -> String {
    let mut buf = [0u16; 1024];
    let n = unsafe { GetModuleFileNameW(0, buf.as_mut_ptr(), buf.len() as u32) } as usize;
    String::from_utf16_lossy(&buf[..n])
}

#[no_mangle]
pub unsafe extern "system" fn hook_proc(code: i32, w: usize, l: isize) -> isize {
    if code >= 0 && l != 0 && w == PM_REMOVE {
        let msg = &mut *(l as *mut MSG);
        if msg.message == WM_HOTKEY {
            if let Some(cfg) = read_config() {
                let mods = (msg.lParam as usize) & 0xffff;
                let vk = ((msg.lParam as usize) >> 16) & 0xffff;
                let line = format!(
                    "{}\t{}\t{:#x}\t{}\t{}\t{}\t{}\t{}\t{}\n",
                    GetCurrentProcessId(),
                    GetCurrentThreadId(),
                    msg.hwnd,
                    msg.wParam,
                    mods,
                    vk,
                    text(GetClassNameW, msg.hwnd),
                    text(GetWindowTextW, msg.hwnd),
                    exe_path()
                );
                if let Ok(mut f) =
                    std::fs::OpenOptions::new().create(true).append(true).open(&cfg.log)
                {
                    let _ = f.write_all(line.as_bytes());
                }
                if cfg.swallow {
                    msg.message = WM_NULL;
                }
            }
        }
    }
    CallNextHookEx(0, code, w, l)
}
