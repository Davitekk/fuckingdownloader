#![windows_subsystem = "windows"]

mod engine;

use eframe::egui::{self, Color32, RichText};
use engine::{Engine, Event, Mode, Request};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, Sender},
    },
};

const TOOLS: [Engine; 5] = [
    Engine::Yt,
    Engine::Ffmpeg,
    Engine::Deno,
    Engine::Gallery,
    Engine::Spotify,
];
const SITES: &[&str] = &[
    "tiktok.com",
    "youtube.com",
    "instagram.com",
    "reddit.com",
    "x.com",
];
const ACCENT: Color32 = Color32::from_rgb(112, 181, 255);

#[derive(Serialize, Deserialize)]
struct Settings {
    folder: PathBuf,
}

struct Task {
    events: Receiver<Event>,
    cancel: Arc<AtomicBool>,
}

impl Drop for Task {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
    }
}

struct App {
    data: PathBuf,
    settings: Settings,
    task: Option<Task>,
    tools: Vec<bool>,
    activity: VecDeque<String>,
    status: String,
    failed: bool,
    setup: bool,
    link: String,
    cookie_site: usize,
    mode: Mode,
    container: String,
    audio: String,
    height: String,
    bitrate: String,
    playlist: bool,
    range: String,
    subtitles: bool,
    sponsorblock: bool,
    forced: Option<Engine>,
}

fn main() -> eframe::Result {
    let data = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir)
        .join("FuckinDownloader");
    let home = std::env::var_os("USERPROFILE")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    let settings = std::fs::read(data.join("settings.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(Settings {
            folder: home.join("Downloads").join("FuckinDownloader"),
        });
    let tools: Vec<_> = TOOLS
        .iter()
        .map(|tool| engine::executable(tool.exe()).is_some())
        .collect();
    let setup = !tools[..3].iter().all(|&ready| ready);
    eframe::run_native(
        "FuckinDownloader",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_inner_size([820.0, 720.0])
                .with_min_inner_size([550.0, 460.0]),
            ..Default::default()
        },
        Box::new(move |cc| {
            let mut visuals = egui::Visuals::dark();
            visuals.panel_fill = Color32::from_rgb(19, 23, 31);
            visuals.selection.bg_fill = Color32::from_rgb(38, 78, 122);
            cc.egui_ctx.set_visuals(visuals);
            Ok(Box::new(App {
                data,
                settings,
                tools,
                setup,
                task: None,
                activity: VecDeque::new(),
                status: String::new(),
                failed: false,
                link: String::new(),
                cookie_site: 0,
                mode: Mode::Video,
                container: "mp4".into(),
                audio: "mp3".into(),
                height: "1080".into(),
                bitrate: "192".into(),
                playlist: false,
                range: String::new(),
                subtitles: false,
                sponsorblock: false,
                forced: None,
            }))
        }),
    )
}

impl App {
    fn refresh_tools(&mut self) {
        self.tools = TOOLS
            .iter()
            .map(|tool| engine::executable(tool.exe()).is_some())
            .collect();
    }

    fn message(&mut self, result: Result<String, String>) {
        self.failed = result.is_err();
        self.status = result.unwrap_or_else(|e| e);
    }

    fn collect(&mut self) {
        let Some(task) = &self.task else {
            return;
        };
        loop {
            match task.events.try_recv() {
                Ok(Event::Line(line)) => {
                    if self.activity.len() == 300 {
                        self.activity.pop_front();
                    }
                    self.activity.push_back(line);
                }
                Ok(Event::Done(result)) => {
                    self.task = None;
                    self.refresh_tools();
                    self.message(result);
                    break;
                }
                Err(mpsc::TryRecvError::Empty) => break,
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.task = None;
                    self.message(Err("The worker stopped unexpectedly.".into()));
                    break;
                }
            }
        }
    }

    fn start(
        &mut self,
        ctx: &egui::Context,
        label: &str,
        work: impl FnOnce(&Sender<Event>, &AtomicBool) -> Result<String, String> + Send + 'static,
    ) {
        let (tx, events) = mpsc::channel();
        let cancel = Arc::new(AtomicBool::new(false));
        let worker_cancel = Arc::clone(&cancel);
        let ctx = ctx.clone();
        self.activity.clear();
        self.message(Ok(label.into()));
        self.task = Some(Task { events, cancel });
        std::thread::spawn(move || {
            let result = work(&tx, &worker_cancel);
            let _ = tx.send(Event::Done(result));
            ctx.request_repaint();
        });
    }

    fn submit(
        &mut self,
        ctx: &egui::Context,
        preview: bool,
        login_test: bool,
    ) -> Result<(), String> {
        let url = engine::parse_link(&self.link)?;
        let host = url.host_str().unwrap_or_default();
        if login_test && !engine::belongs(host, "tiktok.com") {
            return Err("Paste a TikTok video link in Download first.".into());
        }
        let cookies = SITES
            .iter()
            .find(|domain| engine::belongs(host, domain))
            .map(|domain| self.data.join("cookies").join(format!("{domain}.txt")))
            .filter(|path| path.is_file());
        if login_test && cookies.is_none() {
            return Err("Import TikTok cookies before running the check.".into());
        }
        let request = Request {
            url,
            folder: self.settings.folder.clone(),
            cookies,
            mode: self.mode,
            format: if self.mode == Mode::Audio {
                self.audio.clone()
            } else {
                self.container.clone()
            },
            height: self.height.clone(),
            bitrate: self.bitrate.clone(),
            playlist: self.playlist,
            range: if self.playlist {
                self.range.trim().into()
            } else {
                String::new()
            },
            subtitles: self.subtitles,
            sponsorblock: self.sponsorblock,
            preview,
            login_test,
            forced: self.forced,
        };
        self.start(
            ctx,
            if login_test {
                "Checking TikTok link…"
            } else if preview {
                "Extracting preview…"
            } else {
                "Downloading…"
            },
            move |tx, cancel| request.execute(tx, cancel),
        );
        Ok(())
    }

    fn update_tool(&mut self, ctx: &egui::Context, tool: Engine, action: &'static str) {
        let Some(id) = tool.package() else {
            return;
        };
        self.start(
            ctx,
            &format!("Running WinGet for {}…", tool.exe()),
            move |tx, cancel| {
                let exe = engine::executable("winget").ok_or(
                    "WinGet is unavailable. Install or update App Installer from Microsoft Store.",
                )?;
                let status = engine::run(
                    engine::command(exe).args([
                        action,
                        "--id",
                        id,
                        "--exact",
                        "--source",
                        "winget",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                        "--disable-interactivity",
                    ]),
                    tx,
                    cancel,
                )?;
                if status.success()
                    || (action == "upgrade" && status.code() == Some(0x8A15002B_u32 as i32))
                {
                    Ok(format!(
                        "WinGet finished for {}. Check the engine status in Setup.",
                        tool.exe()
                    ))
                } else {
                    Err(format!(
                        "WinGet exited with {status}. See Activity for details."
                    ))
                }
            },
        );
    }

    fn cookie_path(&self) -> PathBuf {
        self.data
            .join("cookies")
            .join(format!("{}.txt", SITES[self.cookie_site]))
    }

    fn import_cookies(&self, source: &Path) -> Result<String, String> {
        let file = std::fs::File::open(source).map_err(|e| e.to_string())?;
        if file.metadata().map_err(|e| e.to_string())?.len() > 4 * 1024 * 1024 {
            return Err("Choose a Netscape cookies.txt file under 4 MB.".into());
        }
        let contents = std::fs::read_to_string(source).map_err(|e| e.to_string())?;
        let domain = SITES[self.cookie_site];
        let rows = contents
            .lines()
            .filter(|line| {
                let row = line.strip_prefix("#HttpOnly_").unwrap_or(line);
                !row.starts_with('#')
                    && row.split('\t').count() == 7
                    && row.split('\t').next().is_some_and(|host| {
                        engine::belongs(&host.trim_start_matches('.').to_ascii_lowercase(), domain)
                    })
            })
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return Err(format!(
                "The file has no Netscape cookie rows for {domain}."
            ));
        }
        let contents = format!("# Netscape HTTP Cookie File\n{}\n", rows.join("\n"));
        write_local(&self.cookie_path(), contents.as_bytes())?;
        Ok(format!("Imported cookies for {domain}."))
    }

    fn download_ui(&mut self, ui: &mut egui::Ui) {
        ui.heading("Download");
        ui.label("Media link");
        ui.add(
            egui::TextEdit::singleline(&mut self.link)
                .hint_text("https://…")
                .desired_width(f32::INFINITY),
        );
        ui.add_space(9.0);
        ui.horizontal_wrapped(|ui| {
            for (mode, label) in [
                (Mode::Video, "Video"),
                (Mode::Audio, "Audio"),
                (Mode::Images, "Images"),
                (Mode::Original, "Original"),
                (Mode::Cover, "Cover only"),
            ] {
                ui.selectable_value(&mut self.mode, mode, label);
            }
        });
        ui.horizontal_wrapped(|ui| {
            match self.mode {
                Mode::Video => {
                    select(
                        ui,
                        "Container",
                        &mut self.container,
                        &["mp4", "mkv", "webm"],
                    );
                    select(
                        ui,
                        "Max height",
                        &mut self.height,
                        &[
                            "Best", "4320", "2160", "1440", "1080", "720", "480", "360", "240",
                            "144",
                        ],
                    );
                }
                Mode::Audio => {
                    select(
                        ui,
                        "Format",
                        &mut self.audio,
                        &["mp3", "m4a", "opus", "vorbis", "flac", "wav"],
                    );
                    select(
                        ui,
                        "Bitrate",
                        &mut self.bitrate,
                        &["Best", "320", "256", "192", "128", "96"],
                    );
                }
                _ => {}
            }
            egui::ComboBox::from_label("Engine")
                .selected_text(self.forced.map_or("Automatic", Engine::exe))
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.forced, None, "Automatic");
                    for tool in [Engine::Yt, Engine::Gallery, Engine::Spotify] {
                        ui.selectable_value(&mut self.forced, Some(tool), tool.exe());
                    }
                });
        });
        ui.horizontal_wrapped(|ui| {
            ui.checkbox(&mut self.playlist, "Playlists");
            if self.playlist {
                ui.add(
                    egui::TextEdit::singleline(&mut self.range)
                        .hint_text("Item ranges, e.g. 1:10,15")
                        .desired_width(165.0),
                );
            }
            if self.mode == Mode::Video {
                ui.checkbox(&mut self.subtitles, "Subtitles");
            }
            if matches!(self.mode, Mode::Video | Mode::Audio) {
                ui.checkbox(&mut self.sponsorblock, "SponsorBlock");
            }
        });
        ui.add_space(10.0);
        ui.horizontal_wrapped(|ui| {
            if ui.button("Choose folder").clicked() {
                if let Some(folder) = rfd::FileDialog::new()
                    .set_directory(&self.settings.folder)
                    .pick_folder()
                {
                    let settings = Settings { folder };
                    let result = serde_json::to_vec_pretty(&settings)
                        .map_err(|e| e.to_string())
                        .and_then(|bytes| write_local(&self.data.join("settings.json"), &bytes));
                    if result.is_ok() {
                        self.settings = settings;
                    }
                    self.message(result.map(|_| "Download folder saved.".into()));
                }
            }
            if ui.button("Open folder").clicked() {
                let path = &self.settings.folder;
                let result = std::fs::create_dir_all(path).and_then(|()| {
                    engine::command("explorer.exe")
                        .arg(path)
                        .spawn()
                        .map(|_| ())
                });
                if let Err(e) = result {
                    self.message(Err(e.to_string()));
                }
            }
            ui.label(self.settings.folder.display().to_string());
        });
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            ui.add_enabled_ui(self.task.is_none(), |ui| {
                for (label, preview) in [("Download", false), ("Preview", true)] {
                    let button = egui::Button::new(label);
                    let button = if preview {
                        button
                    } else {
                        button.fill(Color32::from_rgb(36, 80, 128))
                    };
                    if ui.add(button).clicked() {
                        if let Err(e) = self.submit(ui.ctx(), preview, false) {
                            self.message(Err(e));
                        }
                    }
                }
            });
        });
    }

    fn setup_ui(&mut self, ui: &mut egui::Ui) {
        ui.heading("Setup");
        ui.label("Install the engines you need. Use Update when a site stops working.");
        ui.add_enabled_ui(self.task.is_none(), |ui| {
            egui::Grid::new("engines").spacing([18.0, 7.0]).show(ui, |ui| {
                for (index, tool) in TOOLS.into_iter().enumerate() {
                    ui.strong(tool.exe());
                    ui.label(match tool {
                        Engine::Yt => "Video and audio",
                        Engine::Gallery => "Galleries and slideshows",
                        Engine::Ffmpeg => "Merging and conversion",
                        Engine::Deno => "YouTube JavaScript runtime",
                        Engine::Spotify => "Spotify link matching",
                    });
                    ui.label(if self.tools[index] { "Found" } else { "Missing" });
                    if tool.package().is_some() {
                        let (label, action) = if self.tools[index] { ("Update", "upgrade") } else { ("Install", "install") };
                        if ui.button(label).clicked() { self.update_tool(ui.ctx(), tool, action); }
                    } else {
                        ui.hyperlink_to("Setup guide", "https://spotdl.readthedocs.io/en/latest/installation/");
                    }
                    ui.end_row();
                }
            });
            if ui.button("Check again").clicked() { self.refresh_tools(); }
            ui.separator();
            ui.heading("Site login");
            ui.label("Use the bundled TikTok exporter with Brave, Chrome, or Edge.");
            if ui.button("Open extension folder").clicked() {
                match extension_folder() {
                    Ok(folder) => {
                        ui.ctx().copy_text(folder.display().to_string());
                        let result = engine::command("explorer.exe").arg(&folder).spawn()
                            .map(|_| "Folder path copied. In your browser, select it with Load unpacked.".into())
                            .map_err(|e| e.to_string());
                        self.message(result);
                    }
                    Err(error) => self.message(Err(error)),
                }
            }
            ui.small("Open brave://extensions, chrome://extensions, or edge://extensions. Turn on Developer mode, choose Load unpacked, and paste the copied folder path.");
            ui.label("For TikTok, sign in in your browser, export a Netscape cookies.txt for TikTok, and import it here. Stay signed in. If downloads fail later, update yt-dlp and refresh the export.");
            ui.label("Cookie files contain account credentials. The app stores matching site rows under your Windows profile.");
            ui.horizontal_wrapped(|ui| {
                egui::ComboBox::from_label("Site").selected_text(SITES[self.cookie_site]).show_ui(ui, |ui| {
                    for (i, site) in SITES.iter().enumerate() { ui.selectable_value(&mut self.cookie_site, i, *site); }
                });
                if ui.button("Import cookies.txt").clicked() {
                    if let Some(file) = rfd::FileDialog::new().add_filter("Cookies", &["txt"]).pick_file() {
                        let result = self.import_cookies(&file);
                        self.message(result);
                    }
                }
                let path = self.cookie_path();
                if path.is_file() {
                    ui.label("Imported");
                    if ui.button("Remove").clicked() {
                        self.message(std::fs::remove_file(path).map(|()| "Cookies removed.".into()).map_err(|e| e.to_string()));
                    }
                }
            });
            if ui.button("Check TikTok link").clicked() {
                if let Err(e) = self.submit(ui.ctx(), false, true) { self.message(Err(e)); }
            }
            ui.small("The check uses the link in Download. A successful public link check does not establish account access.");
        });
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        self.collect();
        if self.task.is_some() {
            ctx.request_repaint_after(std::time::Duration::from_millis(120));
        }
        egui::CentralPanel::default().show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(8.0);
                ui.label(
                    RichText::new("FuckinDownloader")
                        .size(28.0)
                        .strong()
                        .color(ACCENT),
                );
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.setup, false, "Download");
                    ui.selectable_value(&mut self.setup, true, "Setup");
                });
                ui.separator();
                if self.setup {
                    self.setup_ui(ui);
                } else {
                    self.download_ui(ui);
                }
                ui.separator();
                ui.horizontal(|ui| {
                    ui.heading("Activity");
                    if let Some(task) = &self.task {
                        ui.spinner();
                        if ui.button("Cancel").clicked() {
                            task.cancel.store(true, Ordering::Relaxed);
                        }
                    }
                });
                if !self.status.is_empty() {
                    ui.colored_label(
                        if self.failed {
                            Color32::LIGHT_RED
                        } else {
                            ACCENT
                        },
                        &self.status,
                    );
                }
                if !self.activity.is_empty() {
                    egui::ScrollArea::vertical()
                        .id_salt("activity")
                        .max_height(175.0)
                        .stick_to_bottom(true)
                        .show(ui, |ui| {
                            for line in &self.activity {
                                ui.add(egui::Label::new(RichText::new(line).monospace()).wrap());
                            }
                        });
                }
            });
        });
    }
}

fn extension_folder() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let folder = exe
        .ancestors()
        .skip(1)
        .map(|path| path.join("browser-extension"))
        .find(|path| path.join("manifest.json").is_file());
    folder.ok_or_else(|| "Extension files are missing. Reinstall the Windows app or use browser-extension from the source checkout.".into())
}

fn select(ui: &mut egui::Ui, label: &str, selected: &mut String, choices: &[&str]) {
    egui::ComboBox::from_label(label)
        .selected_text(selected.as_str())
        .show_ui(ui, |ui| {
            for &choice in choices {
                ui.selectable_value(selected, choice.into(), choice);
            }
        });
}

fn write_local(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let folder = path.parent().ok_or("Invalid settings path.")?;
    std::fs::create_dir_all(folder).map_err(|e| e.to_string())?;
    let mut temp = tempfile::NamedTempFile::new_in(folder).map_err(|e| e.to_string())?;
    temp.write_all(bytes).map_err(|e| e.to_string())?;
    temp.persist(path).map_err(|e| e.to_string())?;
    Ok(())
}
