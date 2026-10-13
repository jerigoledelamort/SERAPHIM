// SERAPHIM S02 — Tauri v2 shell (Rust)
// Minimal: loads frontend from tauri.conf.json frontendDist, no custom commands.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
}
