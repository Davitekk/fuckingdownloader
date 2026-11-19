use std::{
    io::{BufRead, BufReader},
    os::windows::{io::AsRawHandle, process::CommandExt},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::Sender,
    },
    thread,
    time::Duration,
};
use url::Url;
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
        SetInformationJobObject,
    },
};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Engine {
    Yt,
    Gallery,
    Spotify,
    Ffmpeg,
    Deno,
}

impl Engine {
    pub fn exe(self) -> &'static str {
        match self {
            Self::Yt => "yt-dlp",
            Self::Gallery => "gallery-dl",
            Self::Spotify => "spotdl",
            Self::Ffmpeg => "ffmpeg",
            Self::Deno => "deno",
        }
    }

    pub fn package(self) -> Option<&'static str> {
        match self {
            Self::Yt => Some("yt-dlp.yt-dlp"),
            Self::Gallery => Some("mikf.gallery-dl"),
            Self::Ffmpeg => Some("Gyan.FFmpeg"),
            Self::Deno => Some("DenoLand.Deno"),
            Self::Spotify => None,
        }
    }
}

pub fn executable(name: &str) -> Option<PathBuf> {
    let links = std::env::var_os("LOCALAPPDATA").map(|path| {
        PathBuf::from(path)
            .join("Microsoft/WinGet/Links")
            .join(format!("{name}.exe"))
    });
    links
        .filter(|p| p.is_file())
        .or_else(|| which::which(name).ok())
}

pub fn command(exe: impl AsRef<Path>) -> Command {
    let mut command = Command::new(exe.as_ref());
    command.creation_flags(0x08000000).stdin(Stdio::null());
    command
}

pub enum Event {
    Line(String),
    Done(Result<String, String>),
}

struct Job(HANDLE);

impl Job {
    fn new() -> std::io::Result<Self> {
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error());
        }
        let job = Self(handle);
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                std::mem::size_of_val(&info) as u32,
            )
        };
        if ok == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(job)
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

pub fn run(
    command: &mut Command,
    tx: &Sender<Event>,
    cancel: &AtomicBool,
) -> Result<ExitStatus, String> {
    if cancel.load(Ordering::Relaxed) {
        return Err("Cancelled.".into());
    }
    let job = Job::new().map_err(|e| e.to_string())?;
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    if unsafe { AssignProcessToJobObject(job.0, child.as_raw_handle().cast()) } == 0 {
        let error = std::io::Error::last_os_error();
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!("Could not monitor the process: {error}"));
    }
    let output = child.stdout.take().unwrap();
    let errors = child.stderr.take().unwrap();
    thread::scope(|scope| {
        scope.spawn(|| relay(output, tx));
        scope.spawn(|| relay(errors, tx));
        let result = loop {
            if cancel.load(Ordering::Relaxed) {
                break Err("Cancelled.".into());
            }
            match child.try_wait() {
                Ok(Some(status)) => {
                    break Ok(status);
                }
                Ok(None) => thread::sleep(Duration::from_millis(100)),
                Err(e) => break Err(e.to_string()),
            }
        };
        drop(job);
        let _ = child.wait();
        result
    })
}

fn relay(pipe: impl std::io::Read, tx: &Sender<Event>) {
    for line in BufReader::new(pipe).split(b'\n').map_while(Result::ok) {
        let line = String::from_utf8_lossy(&line);
        // Extractor errors can include signed URLs. Keep those out of the UI log.
        let line = line
            .split_whitespace()
            .map(|word| {
                if word.contains("://") && word.contains('?') {
                    "[URL with query removed]"
                } else {
                    word
                }
            })
            .collect::<Vec<_>>()
            .join(" ");
        if tx.send(Event::Line(line)).is_err() {
            break;
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    Video,
    Audio,
    Images,
    Original,
    Cover,
}

pub fn belongs(host: &str, domain: &str) -> bool {
    host == domain
        || host
            .strip_suffix(domain)
            .is_some_and(|prefix| prefix.ends_with('.'))
}

pub fn parse_link(input: &str) -> Result<Url, String> {
    let url = Url::parse(input.trim()).map_err(|_| "Paste a valid media URL.")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("Use an HTTP or HTTPS URL without embedded credentials.".into());
    }
    Ok(url)
}

pub struct Request {
    pub url: Url,
    pub folder: PathBuf,
    pub cookies: Option<PathBuf>,
    pub mode: Mode,
    pub format: String,
    pub height: String,
    pub bitrate: String,
    pub playlist: bool,
    pub range: String,
    pub subtitles: bool,
    pub sponsorblock: bool,
    pub preview: bool,
    pub login_test: bool,
    pub forced: Option<Engine>,
}

impl Request {
    fn plan(&self) -> Vec<Engine> {
        use Engine::*;
        if self.login_test {
            return vec![Yt];
        }
        if let Some(engine) = self.forced {
            return vec![engine];
        }
        let host = self.url.host_str().unwrap_or_default();
        let path = self.url.path();
        if belongs(host, "spotify.com") {
            return vec![Spotify];
        }
        if self.mode == Mode::Images {
            return vec![Gallery];
        }
        if matches!(self.mode, Mode::Audio | Mode::Cover) {
            return vec![Yt];
        }
        let gallery_site = [
            "pin.it",
            "pinterest.com",
            "pixiv.net",
            "tumblr.com",
            "deviantart.com",
            "imgur.com",
            "flickr.com",
            "bsky.app",
            "e621.net",
        ]
        .iter()
        .any(|d| belongs(host, d));
        if (belongs(host, "instagram.com")
            && !path.starts_with("/reel/")
            && !path.starts_with("/tv/"))
            || (belongs(host, "tiktok.com") && path.starts_with("/photo/"))
            || gallery_site
        {
            if self.mode == Mode::Original || self.preview {
                return vec![Gallery, Yt];
            }
        }
        if self.mode == Mode::Original {
            vec![Yt, Gallery]
        } else {
            vec![Yt]
        }
    }

    fn tool(
        &self,
        engine: Engine,
        output: &Path,
        cookies: Option<&Path>,
    ) -> Result<Command, String> {
        let exe = executable(engine.exe())
            .ok_or_else(|| format!("{} is missing. Open Setup.", engine.exe()))?;
        let mut cmd = command(exe);
        cmd.current_dir(output);
        match engine {
            Engine::Yt => self.yt_args(&mut cmd, cookies)?,
            Engine::Gallery => {
                if !self.preview && !matches!(self.mode, Mode::Images | Mode::Original) {
                    return Err("Select Images or Original for gallery-dl.".into());
                }
                cmd.args([
                    "--config-ignore",
                    "-D",
                    ".",
                    "--no-mtime",
                    "-o",
                    if self.mode == Mode::Images {
                        "videos=false"
                    } else {
                        "videos=true"
                    },
                ]);
                if let Some(cookie) = cookies {
                    cmd.arg("--cookies").arg(cookie);
                }
                if self.preview {
                    cmd.args(["--get-urls", "--range", "1"]);
                } else if !self.range.is_empty() {
                    cmd.args(["--range", &self.range.replace(':', "-")]);
                } else if !self.playlist {
                    cmd.args(["--range", "1-50"]);
                }
            }
            Engine::Spotify => {
                if self.preview {
                    return Err("Spotify preview is unavailable. Use Download Audio.".into());
                }
                if !matches!(self.mode, Mode::Audio | Mode::Original) {
                    return Err("Select Audio or Original for Spotify links.".into());
                }
                if !self.range.is_empty() {
                    return Err("Item ranges are unavailable for Spotify links.".into());
                }
                if !self.playlist && !self.url.path().contains("/track/") {
                    return Err("Enable Playlists for Spotify albums and collections.".into());
                }
                cmd.args([
                    "download",
                    self.url.as_str(),
                    "--output",
                    "{artists} - {title}.{output-ext}",
                ]);
                let ffmpeg = executable("ffmpeg").ok_or("FFmpeg is missing. Open Setup.")?;
                cmd.arg("--ffmpeg").arg(ffmpeg);
                if self.mode == Mode::Audio {
                    let format = if self.format == "vorbis" {
                        "ogg"
                    } else {
                        self.format.as_str()
                    };
                    if !matches!(format, "mp3" | "m4a" | "opus" | "ogg" | "flac" | "wav") {
                        return Err("Unsupported Spotify audio format.".into());
                    }
                    cmd.args(["--format", format]);
                    if self.bitrate != "Best" {
                        cmd.args(["--bitrate", &format!("{}k", self.bitrate)]);
                    }
                }
                return Ok(cmd);
            }
            _ => unreachable!(),
        }
        cmd.args(["--", self.url.as_str()]);
        Ok(cmd)
    }

    fn yt_args(&self, cmd: &mut Command, cookies: Option<&Path>) -> Result<(), String> {
        cmd.args([
            "--ignore-config",
            "--newline",
            "--windows-filenames",
            "--no-mtime",
            "--encoding",
            "utf-8",
            "--socket-timeout",
            "30",
            "-o",
            "%(title).150B [%(id)s].%(ext)s",
        ]);
        if let Some(cookie) = cookies {
            cmd.arg("--cookies").arg(cookie);
        }
        if let Some(deno) = executable("deno") {
            cmd.arg("--js-runtimes")
                .arg(format!("deno:{}", deno.display()));
        }
        cmd.arg(if self.playlist && !self.login_test {
            "--yes-playlist"
        } else {
            "--no-playlist"
        });
        if self.preview || self.login_test {
            cmd.args([
                "--skip-download",
                "--playlist-end",
                "1",
                "--print",
                "%(title)s | %(duration_string)s",
            ]);
            return Ok(());
        }
        if !self.range.is_empty() {
            cmd.args(["--playlist-items", &self.range]);
        }
        if let Some(ffmpeg) = executable("ffmpeg") {
            cmd.arg("--ffmpeg-location").arg(ffmpeg);
        } else if matches!(self.mode, Mode::Audio | Mode::Video) {
            return Err("FFmpeg is missing. Open Setup.".into());
        }
        match self.mode {
            Mode::Video => {
                let height = if self.height == "Best" {
                    String::new()
                } else {
                    format!("[height<={}]", self.height)
                };
                let format = if self.format == "mp4" {
                    format!(
                        "bv*{height}[vcodec^=avc1]+ba[ext=m4a]/b{height}[ext=mp4][vcodec^=avc1]/b{height}[ext=mp4]"
                    )
                } else {
                    if self.format == "webm" {
                        format!("bv*{height}[ext=webm]+ba[ext=webm]/b{height}[ext=webm]")
                    } else {
                        format!("bv*{height}+ba/b{height}")
                    }
                };
                cmd.args([
                    "-f",
                    &format,
                    "--merge-output-format",
                    &self.format,
                    "--remux-video",
                    &self.format,
                    "--embed-metadata",
                ]);
            }
            Mode::Audio => {
                cmd.args([
                    "-x",
                    "--audio-format",
                    &self.format,
                    "--embed-metadata",
                    "--embed-thumbnail",
                ]);
                if self.bitrate != "Best" {
                    cmd.args(["--audio-quality", &format!("{}K", self.bitrate)]);
                }
            }
            Mode::Cover => {
                cmd.args(["--skip-download", "--write-thumbnail"]);
            }
            Mode::Original => {
                cmd.args(["-f", "best"]);
            }
            Mode::Images => return Err("Images require gallery-dl.".into()),
        }
        if self.subtitles && self.mode == Mode::Video {
            cmd.args(["--write-subs", "--sub-langs", "all,-live_chat"]);
        }
        if self.sponsorblock && matches!(self.mode, Mode::Video | Mode::Audio) {
            cmd.args([
                "--sponsorblock-remove",
                "sponsor,selfpromo,interaction,intro,outro,music_offtopic",
            ]);
        }
        Ok(())
    }

    pub fn execute(self, tx: &Sender<Event>, cancel: &AtomicBool) -> Result<String, String> {
        let mut failures = Vec::new();
        for engine in self.plan() {
            if cancel.load(Ordering::Relaxed) {
                return Err("Cancelled.".into());
            }
            let result = self.attempt(engine, tx, cancel);
            match result {
                Ok(message) => return Ok(message),
                Err(error) => {
                    let _ = tx.send(Event::Line(format!("{}: {error}", engine.exe())));
                    failures.push(error);
                }
            }
        }
        if cancel.load(Ordering::Relaxed) {
            return Err("Cancelled.".into());
        }
        let mut message = failures.join(" ");
        if belongs(self.url.host_str().unwrap_or_default(), "tiktok.com") {
            message.push_str(
                " Open Setup to import or refresh your TikTok cookies and test the same link.",
            );
        }
        Err(message)
    }

    fn attempt(
        &self,
        engine: Engine,
        tx: &Sender<Event>,
        cancel: &AtomicBool,
    ) -> Result<String, String> {
        let preview = self.preview || self.login_test;
        let output = if preview {
            tempfile::tempdir()
        } else {
            std::fs::create_dir_all(&self.folder).map_err(|e| e.to_string())?;
            tempfile::Builder::new()
                .prefix("Download-")
                .tempdir_in(&self.folder)
        }
        .map_err(|e| e.to_string())?;
        let cookies = self
            .cookies
            .as_ref()
            .map(|import| {
                let temp = tempfile::NamedTempFile::new()?;
                std::fs::copy(import, temp.path())?;
                Ok::<_, std::io::Error>(temp)
            })
            .transpose()
            .map_err(|e| format!("Could not prepare site cookies: {e}"))?;
        let mut cmd = self.tool(
            engine,
            output.path(),
            cookies.as_ref().map(|temp| temp.path()),
        )?;
        let _ = tx.send(Event::Line(format!("Using {}", engine.exe())));
        let status = run(&mut cmd, tx, cancel)?;
        if cancel.load(Ordering::Relaxed) {
            return Err("Cancelled.".into());
        }
        if !status.success() {
            return Err(format!(
                "{} exited with {status}. See Activity for details.",
                engine.exe()
            ));
        }
        if self.login_test {
            return Ok("TikTok accepted the request for this link.".into());
        }
        if preview {
            return Ok("Preview ready. See Activity for the extracted result.".into());
        }
        if std::fs::read_dir(output.path())
            .map_err(|e| e.to_string())?
            .next()
            .is_none()
        {
            return Err("The engine produced no files.".into());
        }
        Ok(format!("Saved to {}", output.keep().display()))
    }
}

#[cfg(test)]
#[path = "engine_tests.rs"]
mod tests;
