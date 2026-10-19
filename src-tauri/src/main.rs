// 叙事驾驶舱 · Tauri v2 桌面外壳
//
// 设计：把现有 Python sidecar（dist/rpg-sidecar.exe）当资源打进安装包；
// 启动时挑一个空闲端口拉起 sidecar（无控制台窗口），窗口先显示本地 loading 页，
// 端口就绪后导航到 http://127.0.0.1:<port>/；退出（甚至崩溃）时按进程树回收 sidecar。
//
// 为什么不把前端静态资源直接塞进 WebView：整套 API（FastAPI）必须和 UI 同源，
// 直接复用已经打包并测试过的 P4 sidecar；桌面壳只负责“进程 + 窗口 + 生命周期”，
// 这样桌面版和 exe/浏览器版是完全同一份 UI 与后端，不存在两套实现。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

/// 托管 sidecar 子进程与 Job Object，退出时统一回收整棵进程树。
struct Sidecar {
    inner: Mutex<Option<SidecarInner>>,
}

struct SidecarInner {
    child: Child,
    /// Windows Job Object 句柄；进程退出时关闭它 → 系统连坐回收 sidecar 树。
    job: Option<isize>,
}

impl Drop for SidecarInner {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        #[cfg(windows)]
        {
            if let Some(job) = self.job.take() {
                job_object::close(job);
            }
        }
    }
}

/// Job Object：PyInstaller onefile 的 rpg-sidecar.exe 只是个引导进程，
/// 真正跑 uvicorn 的是它再 fork 出来的子进程；只 kill 直接子进程会留下孤儿
/// 占住端口，所以把引导进程放进 KILL_ON_JOB_CLOSE 的 Job，桌面壳退出/崩溃时
/// 由内核把整棵进程树带走。
#[cfg(windows)]
mod job_object {
    use std::ffi::c_void;
    use std::mem::size_of;
    use std::ptr;

    type Handle = isize;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;

    #[repr(C)]
    struct BasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    struct ExtendedLimitInformation {
        basic: BasicLimitInformation,
        io: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    unsafe extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(job: Handle, class: i32, info: *mut c_void, len: u32) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
    }

    pub fn assign(process: Handle) -> Option<Handle> {
        unsafe {
            let job = CreateJobObjectW(ptr::null_mut(), ptr::null());
            if job == 0 {
                return None;
            }
            let mut info: ExtendedLimitInformation = std::mem::zeroed();
            info.basic.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                &mut info as *mut _ as *mut c_void,
                size_of::<ExtendedLimitInformation>() as u32,
            );
            if ok == 0 {
                CloseHandle(job);
                return None;
            }
            if AssignProcessToJobObject(job, process) == 0 {
                CloseHandle(job);
                return None;
            }
            Some(job)
        }
    }

    pub fn close(job: Handle) {
        unsafe {
            CloseHandle(job);
        }
    }
}

/// 让操作系统分配一个空闲端口：绑 0 → 读端口 → 释放。
fn pick_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

/// 找到 sidecar 可执行文件：打包后是资源目录，开发时回落到仓库 dist/。
fn find_sidecar(app: &tauri::App) -> Option<PathBuf> {
    if let Ok(res) = app.path().resource_dir() {
        for candidate in [
            res.join("rpg-sidecar.exe"),
            res.join("resources").join("rpg-sidecar.exe"),
        ] {
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidates = [
        manifest.join("..").join("dist").join("rpg-sidecar.exe"),
        manifest.join("..").join("..").join("dist").join("rpg-sidecar.exe"),
    ];
    for candidate in candidates {
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        let candidate = cwd.join("dist").join("rpg-sidecar.exe");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// 拉起 sidecar，返回端口、子进程与（Windows）Job 句柄。
fn spawn_sidecar(exe: &PathBuf) -> std::io::Result<(u16, Child, Option<isize>)> {
    let port = pick_port()?;
    let mut cmd = Command::new(exe);
    cmd.env("RPG_PORT", port.to_string());
    cmd.env("RPG_HOST", "127.0.0.1");
    // 桌面壳不要控制台窗口闪一下。
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let child = cmd.spawn()?;
    #[cfg(windows)]
    let job = {
        use std::os::windows::io::AsRawHandle;
        job_object::assign(child.as_raw_handle() as isize)
    };
    #[cfg(not(windows))]
    let job: Option<isize> = None;
    Ok((port, child, job))
}

/// 等 sidecar 端口可连接（最多 40 秒）。
fn wait_ready(port: u16) -> bool {
    let deadline = Instant::now() + Duration::from_secs(40);
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

/// 在 loading 页里直接渲染错误说明（不依赖第二个静态页，避免导航到 tauri:// 的坑）。
fn show_error<R: tauri::Runtime>(window: &WebviewWindow<R>, title: &str, detail: &str) {
    let html = format!(
        "<html><head><meta charset=\"utf-8\"><style>\
         html,body{{height:100%;margin:0;background:#0d1117;color:#e6edf3;font:15px/1.8 'Segoe UI',system-ui,sans-serif}}\
         body{{display:flex;align-items:center;justify-content:center}}\
         .box{{max-width:640px;padding:32px}}h1{{font-size:20px;color:#f87171;margin:0 0 12px}}\
         p{{color:#c9d1d9;margin:0 0 10px}}.muted{{color:#8b949e;font-size:13px}}\
         code{{background:#161b22;border:1px solid #30363d;border-radius:4px;padding:1px 5px;font-size:13px}}\
         </style></head><body><div class=\"box\"><h1>{title}</h1><p>{detail}</p>\
         <p class=\"muted\">常见原因：杀毒软件拦截了打包后的 sidecar；端口被占用；\
         <code>dist\\rpg-sidecar.exe</code> 不存在（重新运行 <code>scripts\\package.ps1</code>）。\
         也可以在安装目录直接运行 <code>rpg-sidecar.exe</code> 查看具体错误。</p></div></body></html>"
    );
    // JS 字符串转义（内容是我们自己拼的固定文案 + 一条错误信息）。
    let escaped = html.replace('\\', "\\\\").replace('\'', "\\'").replace('\n', "\\n");
    let js = format!("document.open();document.write('{escaped}');document.close();");
    if let Err(err) = window.eval(&js) {
        eprintln!("[cockpit] 错误页渲染失败: {err}");
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // 先开窗口显示本地 loading 页：sidecar 冷启动需要几百毫秒到几秒。
            let window = WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::App("desktop-loading.html".into()),
            )
            .title("叙事驾驶舱")
            .inner_size(1440.0, 900.0)
            .min_inner_size(1080.0, 700.0)
            .build()?;

            let Some(exe) = find_sidecar(app) else {
                eprintln!("[cockpit] 找不到 rpg-sidecar.exe");
                show_error(&window, "找不到 rpg-sidecar.exe", "桌面外壳没有找到内置的 Python sidecar。");
                return Ok(());
            };
            eprintln!("[cockpit] sidecar: {}", exe.display());

            let (port, child, job) = match spawn_sidecar(&exe) {
                Ok(triple) => triple,
                Err(err) => {
                    eprintln!("[cockpit] 启动 sidecar 失败: {err}");
                    show_error(&window, "无法启动本地引擎", &format!("进程启动失败：{err}"));
                    return Ok(());
                }
            };
            #[cfg(windows)]
            if job.is_none() {
                eprintln!("[cockpit] 警告：没能把 sidecar 放进 Job Object，退出时可能留下孤儿进程");
            }
            app.manage(Sidecar {
                inner: Mutex::new(Some(SidecarInner { child, job })),
            });

            // 后台等端口，就绪后回主线程导航，避免卡住 setup。
            let handle = app.handle().clone();
            let window = window.clone();
            std::thread::spawn(move || {
                let target = if wait_ready(port) {
                    format!("http://127.0.0.1:{port}/").parse().ok()
                } else {
                    eprintln!("[cockpit] sidecar 端口 {port} 等待超时");
                    None
                };
                let _ = handle.run_on_main_thread(move || match target {
                    Some(url) => {
                        if let Err(err) = window.navigate(url) {
                            eprintln!("[cockpit] 导航失败: {err}");
                            show_error(&window, "无法打开驾驶舱", "本地引擎已启动，但窗口导航失败。");
                        }
                    }
                    None => show_error(
                        &window,
                        "本地引擎启动超时",
                        "40 秒内没有连上本地 API 端口，可能是杀软拦截或端口被占用。",
                    ),
                });
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building 叙事驾驶舱")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<Sidecar>() {
                    if let Ok(mut guard) = state.inner.lock() {
                        if let Some(mut track) = guard.take() {
                            // onefile 引导进程的孙进程才是真正的 uvicorn，按树杀。
                            #[cfg(windows)]
                            {
                                use std::os::windows::process::CommandExt;
                                const CREATE_NO_WINDOW: u32 = 0x0800_0000;
                                let _ = Command::new("taskkill")
                                    .args(["/PID", &track.child.id().to_string(), "/T", "/F"])
                                    .creation_flags(CREATE_NO_WINDOW)
                                    .status();
                            }
                            let _ = track.child.kill();
                            let _ = track.child.wait();
                            // Drop: 关 Job 句柄兜底（KILL_ON_JOB_CLOSE 会连坐整棵树）。
                        }
                    }
                }
            }
        });
}
