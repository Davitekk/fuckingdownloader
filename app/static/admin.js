(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtBytes = (b) => {
    if (b == null) return "";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(i ? 1 : 0)} ${u[i]}`;
  };
  let cfg = {};

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-FDL": "1", ...(opts.headers || {}) } });
    if (r.status === 401) { location.reload(); throw new Error("logged out"); }
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${r.status}`);
    return data;
  }

  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.style.background = bad ? "var(--bad)" : "";
    t.classList.remove("hidden");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.add("hidden"), 2600);
  }

  const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  function setPath(o, p, v) {
    const ks = p.split("."); let cur = o;
    ks.slice(0, -1).forEach((k) => (cur = cur[k] = cur[k] || {}));
    cur[ks.at(-1)] = v;
  }

  // --- tabs ---------------------------------------------------------------
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("on", x === t));
    $$(".panel").forEach((p) => p.classList.toggle("on", p.id === "p-" + t.dataset.tab));
    if (t.dataset.tab === "jobs") loadJobs();
    if (t.dataset.tab === "system") loadSystem();
    try { localStorage.setItem("fdl:admintab", t.dataset.tab); } catch {}
  }));

  $("#logout").action = location.pathname.replace(/\/$/, "") + "/logout";

  // --- settings -----------------------------------------------------------
  function fill() {
    $$("[data-k]").forEach((el) => {
      const v = getPath(cfg, el.dataset.k);
      if (el.type === "checkbox") el.checked = !!v;
      else el.value = v ?? "";
    });
    renderCookies();
    renderEngines();
  }

  function collect() {
    const out = {};
    $$("[data-k]").forEach((el) => {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "number") v = Number(v);
      setPath(out, el.dataset.k, v);
    });
    out.cookies = {};
    $$("[data-cookie]").forEach((t) => (out.cookies[t.dataset.cookie] = t.value));
    out.custom_engines = $$(".engine-row").map((r) => ({
      name: r.querySelector("[name=name]").value.trim(),
      pattern: r.querySelector("[name=pattern]").value.trim(),
      command: r.querySelector("[name=command]").value.trim(),
      enabled: r.querySelector("[name=enabled]").checked,
    }));
    return out;
  }

  function renderCookies() {
    const slots = cfg.cookie_slots || {};
    $("#cookieSlots").innerHTML = Object.entries(slots).map(([k, label]) => `
      <div class="box cookie-slot">
        <div class="head">
          <b>${esc(label)}</b>
          <div class="row" style="margin:0">
            <span class="badge ${cfg.cookie_counts?.[k] ? "acc" : ""}" data-count="${k}">${cfg.cookie_counts?.[k] || 0} cookies</span>
            <label class="btn small">Upload<input type="file" accept=".txt,.json,text/plain,application/json" data-upload="${k}" hidden></label>
            <button class="btn small danger" data-clear="${k}">Clear</button>
          </div>
        </div>
        <textarea data-cookie="${k}" spellcheck="false" placeholder="# Netscape HTTP Cookie File&#10;.example.com&#9;TRUE&#9;/&#9;TRUE&#9;1999999999&#9;name&#9;value"></textarea>
      </div>`).join("");
    $$("[data-cookie]").forEach((t) => (t.value = cfg.cookies?.[t.dataset.cookie] || ""));
  }

  $("#cookieSlots").addEventListener("change", async (ev) => {
    const inp = ev.target.closest("[data-upload]");
    if (!inp || !inp.files[0]) return;
    $(`[data-cookie="${inp.dataset.upload}"]`).value = await inp.files[0].text();
    toast("Loaded. Don't forget to save.");
  });
  $("#cookieSlots").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-clear]");
    if (b) $(`[data-cookie="${b.dataset.clear}"]`).value = "";
  });

  function engineRow(e = {}) {
    const d = document.createElement("div");
    d.className = "engine-row";
    d.innerHTML = `
      <input class="input" name="name" placeholder="name" value="${esc(e.name)}">
      <input class="input" name="pattern" placeholder="URL regex, e.g. example\\.com/watch" value="${esc(e.pattern)}">
      <input class="input" name="command" placeholder="mytool --out {outdir} {url}" value="${esc(e.command)}" style="font-family:var(--mono)">
      <label class="check"><input type="checkbox" name="enabled" ${e.enabled === false ? "" : "checked"}> on</label>
      <button class="btn small danger" type="button">✕</button>`;
    d.querySelector("button").onclick = () => d.remove();
    return d;
  }
  function renderEngines() {
    const box = $("#customEngines");
    box.innerHTML = "";
    (cfg.custom_engines || []).forEach((e) => box.appendChild(engineRow(e)));
  }
  $("#addEngine").onclick = () => $("#customEngines").appendChild(engineRow());

  async function load() {
    cfg = await api("/api/admin/settings");
    fill();
  }

  $("#save").onclick = async () => {
    try {
      const r = await api("/api/admin/settings", { method: "PUT", body: JSON.stringify(collect()) });
      Object.entries(r.cookie_counts || {}).forEach(([k, n]) => {
        const b = $(`[data-count="${k}"]`);
        if (b) { b.textContent = `${n} cookies`; b.classList.toggle("acc", n > 0); }
      });
      toast("Saved.");
    } catch (e) { toast(e.message, true); }
  };
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); $("#save").click(); }
  });

  // --- jobs ---------------------------------------------------------------
  async function loadJobs() {
    const jobs = await api("/api/admin/jobs");
    const t = $("#jobTable");
    if (!jobs.length) { t.innerHTML = `<tr><td class="sub">No downloads.</td></tr>`; return; }
    t.innerHTML = `<tr><th>When</th><th>What</th><th>Status</th><th>IP</th><th>Size</th><th></th></tr>` + jobs.map((j) => {
      const size = j.files.reduce((a, f) => a + f.size, 0);
      return `<tr>
        <td class="sub">${new Date(j.created * 1000).toLocaleString()}</td>
        <td style="max-width:420px">
          <div style="overflow-wrap:anywhere"><b>${esc(j.title || "")}</b></div>
          <div class="sub" style="overflow-wrap:anywhere">${esc(j.url)}</div>
          <div class="sub">${esc(j.opts.mode)} · ${esc(j.engine || "")}</div>
          ${j.error ? `<div class="err">${esc(j.error)}</div>` : ""}
          <details><summary>log</summary><pre class="log">${esc(j.log.join("\n"))}</pre></details>
        </td>
        <td>${esc(j.status)}${j.progress != null && j.status === "running" ? ` ${j.progress.toFixed(0)}%` : ""}</td>
        <td class="sub">${esc(j.ip)}</td>
        <td class="sub">${size ? fmtBytes(size) : ""}</td>
        <td><div class="actions" style="margin:0">
          ${j.status === "done" ? `<a class="btn small" href="/api/jobs/${j.id}/file">Get</a>` : ""}
          ${["queued", "running", "processing"].includes(j.status) ? `<button class="btn small" data-jcancel="${j.id}">Cancel</button>` : ""}
          <button class="btn small danger" data-jdel="${j.id}">Delete</button>
        </div></td></tr>`;
    }).join("");
  }
  $("#jobTable").addEventListener("click", async (ev) => {
    const c = ev.target.closest("[data-jcancel]"), d = ev.target.closest("[data-jdel]");
    try {
      if (c) await api(`/api/admin/jobs/${c.dataset.jcancel}/cancel`, { method: "POST" });
      if (d) await api(`/api/admin/jobs/${d.dataset.jdel}`, { method: "DELETE" });
      if (c || d) loadJobs();
    } catch (e) { toast(e.message, true); }
  });
  $("#refreshJobs").onclick = loadJobs;
  $("#clearJobs").onclick = async () => {
    const r = await api("/api/admin/jobs/clear", { method: "POST" });
    toast(`Deleted ${r.removed}.`);
    loadJobs();
  };

  // --- system -------------------------------------------------------------
  async function loadSystem() {
    const s = await api("/api/admin/system");
    $("#versions").innerHTML = [["FuckinDownloader", s.app], ["Python", s.python], ...Object.entries(s.versions)]
      .map(([k, v]) => `<b>${esc(k)}</b><span>${esc(v)}</span>`).join("");
    $("#disk").innerHTML = `
      <b>Downloads</b><span>${fmtBytes(s.disk.downloads)}${s.disk.quota ? ` of ${fmtBytes(s.disk.quota)} quota${s.disk.full ? " (FULL, new downloads paused)" : ""}` : " (no quota)"}</span>
      <b>Free</b><span>${fmtBytes(s.disk.free)} of ${fmtBytes(s.disk.total)}</span>
      <b>Jobs</b><span>${Object.entries(s.jobs).map(([k, v]) => `${v} ${k}`).join(", ")}</span>
      <b>Admin path</b><span>${esc(s.admin_path)}</span>`;
  }
  $("#update").onclick = async () => {
    const b = $("#update"), log = $("#updateLog");
    b.disabled = true;
    b.textContent = "Updating... (can take a minute)";
    log.classList.remove("hidden");
    log.textContent = "Running pip...";
    try {
      const r = await api("/api/admin/update", { method: "POST", body: JSON.stringify({ nightly: $("#nightly").checked }) });
      log.textContent = r.log;
      toast("Updated.");
      loadSystem();
    } catch (e) { log.textContent = e.message; toast(e.message, true); }
    b.disabled = false;
    b.textContent = "Update yt-dlp, gallery-dl & spotdl";
  };

  load().then(() => {
    let tab = "general";
    try { tab = localStorage.getItem("fdl:admintab") || tab; } catch {}
    $(`.tab[data-tab="${tab}"]`)?.click();
  }).catch((e) => toast(e.message, true));
})();
