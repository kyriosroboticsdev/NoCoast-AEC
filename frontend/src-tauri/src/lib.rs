//! Desktop shell. The UI is the Vite app; the only native job is starting and
//! stopping the Python backend so the app is one double-click.
//!
//! Environment:
//!   BIM_NO_BACKEND=1     don't spawn a backend (one is already running)
//!   BIM_BACKEND_DIR      path to the `backend` folder (default: ../../backend relative to src-tauri)
//!   BIM_PYTHON           python executable (default: `python`)

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::Manager;

struct Backend(Mutex<Option<Child>>);

fn spawn_backend() -> Option<Child> {
    if std::env::var_os("BIM_NO_BACKEND").is_some() {
        return None;
    }
    let dir = std::env::var("BIM_BACKEND_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../backend"));
    let python = std::env::var("BIM_PYTHON").unwrap_or_else(|_| "python".into());
    match Command::new(&python).arg("main.py").current_dir(&dir).spawn() {
        Ok(child) => {
            eprintln!("[backend] started {} main.py in {}", python, dir.display());
            Some(child)
        }
        Err(err) => {
            eprintln!("[backend] could not start ({err}); assuming it is already running");
            None
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(Backend(Mutex::new(spawn_backend())));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
