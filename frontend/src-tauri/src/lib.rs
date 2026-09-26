//! Desktop shell: window, IFC file I/O, launch options, and (optionally) the Python backend.
//! Everything BIM-related lives in the web UI and the backend; this stays thin.

use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::ipc::{InvokeBody, Request, Response};
use tauri::{Manager, RunEvent};

/// Backend address; BIM_PORT (also read by backend/main.py) overrides the port.
fn backend_addr() -> String {
    format!("127.0.0.1:{}", env("BIM_PORT").unwrap_or_else(|| "8765".into()))
}

struct Backend(Mutex<Option<Child>>);

fn env(key: &str) -> Option<String> {
    std::env::var(key).ok().filter(|v| !v.is_empty())
}

fn backend_alive() -> bool {
    let Ok(addr) = backend_addr().parse::<SocketAddr>() else { return false };
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn backend_dir() -> PathBuf {
    env("BIM_BACKEND_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("backend"))
}

/// Start `python main.py` in backend/ unless something already listens on the port.
fn start_backend() -> Option<Child> {
    if env("BIM_NO_BACKEND").is_some() || backend_alive() {
        return None;
    }
    let dir = backend_dir();
    let venv = if cfg!(windows) { dir.join(".venv/Scripts/python.exe") } else { dir.join(".venv/bin/python") };
    let python = if venv.exists() { venv } else { PathBuf::from("python") };
    let mut cmd = Command::new(python);
    cmd.arg("main.py").current_dir(&dir);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    match cmd.spawn() {
        Ok(child) => {
            #[cfg(windows)]
            kill_with_app(&child);
            Some(child)
        }
        Err(e) => {
            eprintln!("[backend] failed to start in {}: {e}", dir.display());
            None
        }
    }
}

/// Put the backend in a Job Object that dies with this process. A venv's python.exe is a
/// launcher that spawns the real interpreter, so killing the direct child isn't enough —
/// and this also covers crashes and force-quits, where no exit handler runs.
#[cfg(windows)]
fn kill_with_app(child: &Child) {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    // The job handle is deliberately never closed: the OS closes it when we exit, killing the tree.
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        // The launcher's own children inherit the job when they're created.
        AssignProcessToJobObject(job, child.as_raw_handle() as _);
    }
}

#[derive(Serialize)]
struct LaunchOptions {
    backend_url: String,
    autoload: Option<String>,
    prompt: Option<String>,
    select: Option<String>,
    tab: Option<String>,
    smoke: bool,
}

/// Smoke-test hooks and config, read from the environment.
#[tauri::command]
fn launch_options() -> LaunchOptions {
    LaunchOptions {
        backend_url: env("BIM_BACKEND_URL").unwrap_or_else(|| format!("http://{}", backend_addr())),
        autoload: env("BIM_AUTOLOAD"),
        prompt: env("BIM_PROMPT"),
        select: env("BIM_SMOKE_SELECT"),
        tab: env("BIM_SMOKE_TAB"),
        smoke: env("BIM_SMOKE").is_some(),
    }
}

fn check_ifc_path(path: &Path) -> Result<(), String> {
    match path.extension().and_then(|e| e.to_str()) {
        Some(ext) if ext.eq_ignore_ascii_case("ifc") => Ok(()),
        _ => Err(format!("not an .ifc file: {}", path.display())),
    }
}

/// Read an IFC chosen in the open dialog. Returned as raw bytes (an ArrayBuffer in JS), not JSON.
#[tauri::command]
fn read_ifc(path: PathBuf) -> Result<Response, String> {
    check_ifc_path(&path)?;
    std::fs::read(&path).map(Response::new).map_err(|e| e.to_string())
}

/// Write raw bytes to the path chosen in the save dialog (passed in the `path` header).
#[tauri::command]
fn write_ifc(request: Request<'_>) -> Result<(), String> {
    let path = request
        .headers()
        .get("path")
        .and_then(|v| v.to_str().ok())
        .map(PathBuf::from)
        .ok_or("missing path header")?;
    check_ifc_path(&path)?;
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err("expected raw bytes".into());
    };
    std::fs::write(&path, bytes).map_err(|e| e.to_string())
}

/// The UI reports its state here. With BIM_SMOKE=<file> the final state is written out and
/// the app exits after BIM_SMOKE_HOLD seconds (default 3), leaving time for a screenshot.
#[tauri::command]
fn smoke_report(app: tauri::AppHandle, state: serde_json::Value) {
    println!("[smoke] {state}");
    let Some(file) = env("BIM_SMOKE") else { return };
    let _ = std::fs::write(file, state.to_string());
    if matches!(state["status"].as_str(), Some("ready" | "error")) {
        let hold = env("BIM_SMOKE_HOLD").and_then(|s| s.parse().ok()).unwrap_or(3);
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(hold));
            app.exit(0);
        });
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            *app.state::<Backend>().0.lock().unwrap() = start_backend();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![launch_options, read_ifc, write_ifc, smoke_report])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
