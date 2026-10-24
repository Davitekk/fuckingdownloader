"""Admin-defined engines: any CLI downloader you can install in the container,
wired to a URL regex. The URL always lands in its own argv slot, never a shell."""
import re
import shlex

from ..jobs import Ctx, EngineError

PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")


def matching(cfg: dict, url: str) -> list[dict]:
    out = []
    for e in cfg.get("custom_engines") or []:
        if not e.get("enabled", True) or not e.get("pattern") or not e.get("command"):
            continue
        try:
            if re.search(e["pattern"], url):
                out.append(e)
        except re.error:
            continue
    return out


def by_name(cfg: dict, name: str) -> dict | None:
    return next((e for e in cfg.get("custom_engines") or [] if e.get("name") == name), None)


async def download(ctx: Ctx, engine: dict):
    subs = {
        "{url}": ctx.url, "{outdir}": str(ctx.outdir), "{tmpdir}": str(ctx.tmpdir),
        "{cookies}": str(ctx.cookies or ""), "{proxy}": ctx.cfg.get("proxy") or "",
        "{mode}": ctx.opts.get("mode", "video"), "{audio_format}": ctx.opts.get("audio_format", "mp3"),
        "{quality}": str(ctx.opts.get("video_quality", "1080")),
    }
    argv = []
    for part in shlex.split(engine["command"]):
        for k, v in subs.items():
            part = part.replace(k, v)
        argv.append(part)

    def on_line(line: str):
        m = PCT_RE.findall(line)
        if m:
            ctx.set(status="running", progress=min(float(m[-1]), 100.0), message=f"{engine['name']}: downloading")

    ctx.set(message=f"Running {engine['name']}...")
    rc = await ctx.run(argv, on_line)
    if rc != 0 and not any(ctx.outdir.rglob("*.*")):
        raise EngineError(ctx.last_error(f"{engine['name']} exited with code {rc}"))
