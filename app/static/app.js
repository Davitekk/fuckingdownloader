(() => {
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem("fdl:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("fdl:" + k, JSON.stringify(v)); } catch {} },
  };

  let cfg = {};
  let mode = "video";
  let analyzeSeq = 0;
  let lastInfo = null;
  const saved = new Set();
  const hints = {}; // title/thumbnail from the preview, shown until the job reports its own
  const jobsEl = $("#jobs");

  const fields = ["video_quality", "video_container", "video_codec", "audio_format", "audio_quality", "engine"];
  const checks = ["subtitles", "sponsorblock", "autosave"];

  function headers() {
    const h = { "Content-Type": "application/json" };
    const k = store.get("key", "");
    if (k) h["X-Access-Key"] = k;
    return h;
  }

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { ...headers(), ...(opts.headers || {}) } });
    let data = null;
    try { data = await r.json(); } catch {}
    if (!r.ok) {
      if (r.status === 401 && cfg.access_key_required) $("#keybox").classList.remove("hidden");
      if (r.status === 503) setFull(true);
      throw new Error((data && (data.error || data.detail)) || `HTTP ${r.status}`);
    }
    return data;
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtBytes = (b) => {
    if (!b && b !== 0) return "";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(b >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
  };
  const fmtTime = (s) => {
    if (s == null || isNaN(s)) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`;
  };

  function setMode(m) {
    mode = m;
    document.querySelectorAll(".mode").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    $("#videoOpts").classList.toggle("hidden", m !== "video");
    $("#audioOpts").classList.toggle("hidden", m !== "audio");
    store.set("mode", m);
  }

  function options() {
    const o = { mode, playlist: $("#playlist").checked, playlist_items: $("#playlist_items").value.trim() };
    fields.forEach((f) => (o[f] = $("#" + f).value));
    checks.forEach((c) => (o[c] = $("#" + c).checked));
    delete o.autosave;
    return o;
  }

  function savePrefs() {
    const p = {};
    fields.forEach((f) => (p[f] = $("#" + f).value));
    checks.forEach((c) => (p[c] = $("#" + c).checked));
    store.set("prefs", p);
  }

  function loadPrefs() {
    const d = cfg.defaults || {};
    const p = store.get("prefs", {});
    fields.forEach((f) => { const v = p[f] ?? d[f]; if (v != null) $("#" + f).value = v; });
    checks.forEach((c) => { if (p[c] != null) $("#" + c).checked = p[c]; });
    setMode(store.get("mode", d.mode || "video"));
  }

  // --- analyze / preview --------------------------------------------------
  function looksLikeUrl(s) { return /^https?:\/\/\S+\.\S+/i.test(s.trim()); }

  async function analyze() {
    const url = $("#url").value.trim();
    const pv = $("#preview");
    lastInfo = null;
    if (!looksLikeUrl(url)) { pv.innerHTML = ""; return; }
    const seq = ++analyzeSeq;
    pv.innerHTML = `<div class="preview"><div class="sub"><span class="spinner"></span>&nbsp; Looking at that link...</div></div>`;
    try {
      const info = await api("/api/analyze", { method: "POST", body: JSON.stringify({ url, mode }) });
      if (seq !== analyzeSeq) return;
      lastInfo = info;
      renderPreview(info);
    } catch (e) {
      if (seq !== analyzeSeq) return;
      pv.innerHTML = `<div class="preview"><div class="meta"><div class="sub">Couldn't preview it, but you can still try downloading.</div><div class="err">${esc(e.message)}</div></div></div>`;
    }
  }

  function renderPreview(i) {
    const badges = [];
    if (i.engine) badges.push(`<span class="badge acc">${esc(i.engine)}</span>`);
    if (i.extractor) badges.push(`<span class="badge">${esc(i.extractor)}</span>`);
    if (i.duration) badges.push(`<span class="badge">${fmtTime(i.duration)}</span>`);
    if (i.heights && i.heights.length) badges.push(`<span class="badge">up to ${i.heights[0]}p</span>`);
    if (i.is_playlist) badges.push(`<span class="badge acc">${i.count ?? "?"}${i.count_capped ? "+" : ""} items</span>`);
    const entries = (i.entries || []).slice(0, 200).map((e) => `<li>${esc(e.title)}${e.duration ? ` <span class="sub">${fmtTime(e.duration)}</span>` : ""}</li>`).join("");
    $("#preview").innerHTML = `
      <div class="preview">
        ${i.thumbnail ? `<img src="${esc(i.thumbnail)}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : ""}
        <div class="meta">
          <h3>${esc(i.title || "Untitled")}</h3>
          ${i.uploader ? `<div class="sub">${esc(i.uploader)}</div>` : ""}
          <div class="badges">${badges.join("")}</div>
          ${i.is_playlist ? `<details ${entries ? "" : "class='hidden'"}><summary>Show items</summary><ol class="entries">${entries}</ol></details>` : ""}
        </div>
      </div>`;
    if (i.is_playlist) $("#playlist").checked = true;
    if (i.is_playlist === false && !i.is_gallery) $("#playlist").checked = false;
    if (i.audio_only && mode === "video") setMode("audio");
    if (i.is_gallery && (mode === "video" || mode === "audio")) setMode("image");
    if (i.has_video === false && mode === "video") setMode("audio");
  }

  let debounce;
  $("#url").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(analyze, 450); });
  $("#paste").addEventListener("click", async () => {
    try { $("#url").value = (await navigator.clipboard.readText()).trim(); analyze(); }
    catch { $("#url").focus(); }
  });
  document.querySelectorAll(".mode").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  [...fields, ...checks].forEach((f) => $("#" + f).addEventListener("change", savePrefs));

  // --- submit -------------------------------------------------------------
  $("#form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("#formErr");
    err.classList.add("hidden");
    const url = $("#url").value.trim();
    if (!url) return;
    const btn = $("#go");
    btn.disabled = true;
    try {
      const job = await api("/api/jobs", { method: "POST", body: JSON.stringify({ url, options: options() }) });
      if (lastInfo) hints[job.id] = { t: lastInfo.title, th: lastInfo.thumbnail };
      prevStatus[job.id] = job.status;
      $("#url").value = "";
      $("#preview").innerHTML = "";
      lastInfo = null;
      poll();
    } catch (e) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    } finally {
      btn.disabled = !$("#fullBanner").classList.contains("hidden");
    }
  });

  // --- jobs ---------------------------------------------------------------
  // The server only returns jobs made from this browser (fdl_owner cookie).
  let jobList = [];
  const prevStatus = {};
  const deadlines = {}; // job id -> local-clock expiry time, immune to server/client clock skew
  const inUse = {}; // job id -> someone is downloading it right now, so it won't be deleted yet
  const openDetails = new Set();
  let pollTimer = null;

  function autoSave(job) {
    if (saved.has(job.id) || !$("#autosave").checked) return;
    saved.add(job.id);
    const a = document.createElement("a");
    a.href = `/api/jobs/${job.id}/file`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function expiryText(id) {
    const left = (deadlines[id] - Date.now()) / 1000;
    if (left > 0) return `Deletes in ${fmtTime(left)}`;
    return inUse[id] ? "Deletes when the download finishes" : "Expired";
  }

  function tickExpiry() {
    document.querySelectorAll("[data-exp]").forEach((el) => {
      const id = el.dataset.exp;
      if (!deadlines[id]) return;
      el.textContent = expiryText(id);
      el.classList.toggle("soon", deadlines[id] - Date.now() < 60000);
    });
  }
  setInterval(tickExpiry, 1000);

  function render() {
    const list = jobList;
    if (!list.length) { jobsEl.innerHTML = `<div class="empty">Nothing yet. Paste something above.</div>`; return; }
    jobsEl.querySelectorAll("details[data-id]").forEach((d) => (d.open ? openDetails.add(d.dataset.id) : openDetails.delete(d.dataset.id)));
    jobsEl.innerHTML = list.map((j) => {
      const title = j.title || hints[j.id]?.t || j.url;
      const thumb = j.thumbnail || hints[j.id]?.th;
      const active = ["queued", "running", "processing"].includes(j.status);
      const indet = active && (j.progress == null || j.status === "processing" || j.status === "queued");
      const pct = j.status === "done" ? 100 : (j.progress || 0);
      const bits = [];
      if (j.status === "running" && j.progress != null) bits.push(`${pct.toFixed(1)}%`);
      if (j.downloaded && j.total && j.status === "running") bits.push(`${fmtBytes(j.downloaded)} / ${fmtBytes(j.total)}`);
      if (j.speed) bits.push(`${fmtBytes(j.speed)}/s`);
      if (j.eta) bits.push(`ETA ${fmtTime(j.eta)}`);
      if (j.status === "done" && deadlines[j.id]) bits.push(`<span class="expiry" data-exp="${j.id}">${expiryText(j.id)}</span>`);
      const size = (j.files || []).reduce((a, f) => a + (f.size || 0), 0);
      let actions = "";
      if (j.status === "done") {
        actions += `<a class="btn primary small" href="/api/jobs/${j.id}/file" download>Save${j.has_archive ? ` zip (${j.files.length} files)` : ""} · ${fmtBytes(size)}</a>`;
      }
      if (active) actions += `<button class="btn small danger" data-cancel="${j.id}">Cancel</button>`;
      if (j.status === "error") actions += `<button class="btn small" data-retry="${j.id}">Retry</button>`;
      actions += `<button class="btn small" data-remove="${j.id}">${j.status === "done" ? "Delete now" : "Remove"}</button>`;
      const files = j.status === "done" && j.files.length > 1
        ? `<details data-id="${j.id}" ${openDetails.has(j.id) ? "open" : ""}><summary>${j.files.length} files</summary><ul class="files">${j.files.map((f, i) => `<li><a href="/api/jobs/${j.id}/files/${i}" download>${esc(f.path)}</a> <span class="sub">${fmtBytes(f.size)}</span></li>`).join("")}</ul></details>`
        : "";
      return `
        <div class="box job ${j.status}">
          ${thumb ? `<img class="thumb" src="${esc(thumb)}" referrerpolicy="no-referrer" alt="" onerror="this.style.visibility='hidden'">` : `<div class="thumb"></div>`}
          <div class="body">
            <div class="title" title="${esc(title)}">${esc(title)}</div>
            <div class="bar ${indet ? "indet" : ""}"><i style="width:${pct}%"></i></div>
            <div class="status">
              <span>${esc(j.status === "error" ? "Failed" : j.message)}${j.engine ? ` · ${esc(j.engine)}` : ""}</span>
              <span>${bits.join(" · ")}</span>
            </div>
            ${j.status === "error" ? `<div class="err">${esc(j.error)}</div>` : ""}
            ${files}
            <div class="actions">${actions}</div>
          </div>
        </div>`;
    }).join("");
    tickExpiry();
  }

  jobsEl.addEventListener("click", async (ev) => {
    const t = ev.target.closest("[data-cancel],[data-remove],[data-retry]");
    if (!t) return;
    try {
      if (t.dataset.cancel) {
        await api(`/api/jobs/${t.dataset.cancel}/cancel`, { method: "POST" });
      } else if (t.dataset.remove) {
        await api(`/api/jobs/${t.dataset.remove}`, { method: "DELETE" });
      } else if (t.dataset.retry) {
        const j = jobList.find((x) => x.id === t.dataset.retry);
        if (j) { $("#url").value = j.url; analyze(); window.scrollTo({ top: 0, behavior: "smooth" }); }
        return;
      }
    } catch {}
    poll();
  });

  $("#clearDone").addEventListener("click", async () => {
    try { await api("/api/jobs/clear", { method: "POST" }); } catch {}
    poll();
  });

  async function poll() {
    clearTimeout(pollTimer);
    try {
      const list = await api("/api/jobs");
      list.forEach((j) => {
        if (j.status === "done" && prevStatus[j.id] && prevStatus[j.id] !== "done") autoSave(j);
        prevStatus[j.id] = j.status;
        if (j.expires_in != null) deadlines[j.id] = Date.now() + j.expires_in * 1000;
        inUse[j.id] = j.in_use;
      });
      jobList = list;
      render();
    } catch {}
    const busy = jobList.some((j) => ["queued", "running", "processing"].includes(j.status));
    pollTimer = setTimeout(poll, busy ? 1000 : 8000);
  }

  // --- storage quota ------------------------------------------------------
  let fullTimer = null;
  function setFull(full) {
    $("#fullBanner").classList.toggle("hidden", !full);
    $("#go").disabled = full;
    clearTimeout(fullTimer);
    fullTimer = setTimeout(checkFull, full ? 15000 : 60000);
  }
  async function checkFull() {
    try { setFull(!!(await (await fetch("/api/config")).json()).storage_full); } catch { setFull(true); }
  }

  // --- themes -------------------------------------------------------------
  function setTheme(t, persist) {
    document.documentElement.dataset.theme = t;
    document.querySelectorAll(".theme-dot").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
    if (persist) store.set("theme", t);
  }
  document.querySelectorAll(".theme-dot").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.theme, true)));

  // --- access key ---------------------------------------------------------
  $("#saveKey").addEventListener("click", () => {
    store.set("key", $("#key").value);
    $("#keybox").classList.add("hidden");
    analyze();
  });

  // --- boot ---------------------------------------------------------------
  (async () => {
    try { cfg = await (await fetch("/api/config")).json(); } catch {}
    setTheme(store.get("theme", null) || cfg.default_theme || "blue", false);
    setFull(!!cfg.storage_full);
    if (cfg.title) {
      document.title = cfg.title;
      const t = cfg.title;
      const cut = t.toLowerCase().indexOf("downloader");
      $("#logo").innerHTML = cut > 0 ? `${esc(t.slice(0, cut))}<span>${esc(t.slice(cut))}</span>` : esc(t);
    }
    if (cfg.tagline) $("#tagline").innerHTML = `<b>${esc(cfg.tagline)}</b> No ads. No subscriptions. No waiting.`;
    if (cfg.public_enabled === false && !cfg.is_admin) {
      $("#app").classList.add("hidden");
      $("#closed").classList.remove("hidden");
      return;
    }
    if (cfg.access_key_required && !cfg.is_admin && !store.get("key", "")) $("#keybox").classList.remove("hidden");
    (cfg.custom_engines || []).forEach((n) => {
      const o = document.createElement("option");
      o.value = n; o.textContent = `Custom: ${n}`;
      $("#engine").appendChild(o);
    });
    loadPrefs();
    const shared = new URLSearchParams(location.search).get("url");
    if (shared) { $("#url").value = shared; analyze(); }
    poll();
  })();
})();
