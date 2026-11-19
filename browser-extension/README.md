# FuckinDownloader browser extension

An MIT-licensed Chromium extension bundled with the Windows installer. The export runs in the browser after you click **Save TikTok cookies.txt** and grant access to TikTok. The extension has no backend or network requests. It only exports TikTok cookies from the active browser profile to a local file. Treat that file as account credentials.

## Load in Brave, Chrome, or Edge

1. Open FuckinDownloader → **Setup → Site login → Open extension folder**. For a source checkout, use this directory.
2. Open `brave://extensions`, `chrome://extensions`, or `edge://extensions` in the browser you use for TikTok.
3. Turn on **Developer mode**, click **Load unpacked**, then select the extension folder containing `manifest.json`.
4. Sign in to TikTok in the same browser profile. Open the extension from the toolbar, click **Save TikTok cookies.txt**, and approve access when prompted.
5. Select **tiktok.com** in the app's Setup tab, click **Import cookies.txt**, and select the saved file. Delete the export when finished.

Run the format tests with `node --test browser-extension/cookies.test.mjs` from the repository root. The repository's MIT license applies to this extension.
