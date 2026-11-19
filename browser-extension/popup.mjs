import { netscapeCookies } from "./cookies.mjs";

const button = document.querySelector("#export");
const status = document.querySelector("#status");

button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    const granted = await chrome.permissions.request({ origins: ["https://*.tiktok.com/*"] });
    if (!granted) {
      status.textContent = "TikTok access is required for this export.";
      return;
    }
    const cookies = await chrome.cookies.getAll({ domain: "tiktok.com" });
    const text = netscapeCookies(cookies);
    if (!text) {
      status.textContent = "No exportable TikTok cookies found. Sign in and try again.";
      return;
    }
    const blob = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    try {
      await chrome.downloads.download({
        url: blob,
        filename: "tiktok-cookies.txt",
        saveAs: true,
      });
      status.textContent = "Import the saved file from FuckinDownloader → Setup.";
    } finally {
      URL.revokeObjectURL(blob);
    }
  } catch {
    status.textContent = "The export did not finish. Open the extension and try again.";
  } finally {
    button.disabled = false;
  }
});
