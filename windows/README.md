# FuckinDownloader for Windows

A Rust desktop companion to the upstream self-hosted downloader. It runs on Windows 10 and 11 (x64) and saves media straight to a local folder.

## Install

Run **FuckinDownloader-Setup-x64.exe**. The per-user installer adds a Start menu shortcut and an uninstall entry in Settings → Apps → Installed apps. The installer is unsigned. Only run a copy from a source you trust.

On first launch, open **Setup** and install **yt-dlp**, **FFmpeg**, and **Deno**. Install **gallery-dl** for galleries and TikTok photo posts. Setup uses Windows Package Manager (WinGet), which comes with [App Installer](https://apps.microsoft.com/detail/9nblggh4nns1). If a tool installed outside WinGet has just added itself to PATH, relaunch from Start. Tools installed with another package manager should be updated through that package manager.

For Spotify, put [spotDL](https://spotdl.readthedocs.io/en/latest/installation/) on PATH, then relaunch. Select Audio or Original. Enable Playlists for Spotify collections. spotDL matches audio from other sources. Availability and API limits may vary.

## TikTok setup

The installer bundles an [open-source browser extension](../browser-extension/README.md) for Brave, Chrome, and Edge. Use **Setup → Site login → Open extension folder** to start. The browser requires a one-time **Load unpacked** step.

1. Try the link with the latest yt-dlp. Select **Images** and install gallery-dl for a photo post.
2. If TikTok requires a login, sign in to TikTok in your browser. Export only TikTok cookies in **Netscape cookies.txt** format using the bundled browser extension. Stay signed in after exporting.
3. Under **Setup → Site login**, select **tiktok.com** and import the file. The app keeps only cookie rows for that site. Delete the export when you are finished with it.
4. Paste the TikTok video link in **Download**, return to **Setup**, and click **Check TikTok link**. Use Activity for extractor errors. A public URL can succeed without proving the session is authenticated.
5. If downloads fail later, update yt-dlp or gallery-dl and import a fresh session. Changes on the sites and expired sessions may require maintenance.

Imported cookies are credentials stored as local text files under the current user's `%LOCALAPPDATA%\FuckinDownloader\cookies`. Remove them from Setup when you no longer need them. Never attach cookie files to issues, screenshots, or pull requests. Uninstall preserves downloaded files and profile settings.

## Desktop feature coverage

The app supports video, audio, image, original, and cover-only downloads, basic previews, quality and container selection, playlist ranges where the engine supports them, subtitles, SponsorBlock, progress output, and cancellation. Downloads are placed in a new folder per job. Automatic engine selection routes supported links to yt-dlp, gallery-dl, or spotDL according to URL and mode. Preview for yt-dlp shows a title and duration. Gallery preview asks for one media URL.

The existing Python web app remains available separately. Desktop parity gaps include the built-in music matcher and page sniffer, custom engines, automatic ZIPs, detailed thumbnail and playlist previews, and the server administration features.

## Build and contribute

Install stable Rust with the x64 MSVC toolchain, Visual Studio C++ Build Tools with the Windows SDK, and Inno Setup 6. From the repo root:

```powershell
cd windows
cargo fmt --check
cargo test --locked
cargo build --locked --release
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer.iss
```

The installer goes to `windows/dist/FuckinDownloader-Setup-x64.exe` and the portable executable goes to `windows/target/release/fuckindownloader.exe`. The Windows desktop GitHub Actions workflow builds and uploads the installer artifact. Source contributions can be submitted by pushing the branch to your fork and opening a pull request against the upstream repository. Include tested Windows versions, any tested engines, and sanitized reproduction steps for bugs.
