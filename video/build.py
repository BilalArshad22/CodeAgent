#!/usr/bin/env python3
"""Turn a recording (record.mjs) of a real run into a narrated demo video.

    python3 video/build.py --raw video/raw --project <run output dir> --out video/out/CodeAgent-demo.mp4

Every number in the narration (turns, files, gate rejections, tests) is read from the
run itself: .codeagent/run_result.json, the transcript, check_project and `npm test`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FPS = 30
BG = (11, 10, 10)
ACCENT = (255, 92, 28)
TEXT = (238, 235, 229)
DIM = (150, 146, 139)
GREEN = (118, 204, 146)
AMBER = (240, 180, 90)
FONT_UI = "/System/Library/Fonts/SFNS.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"


# --------------------------------------------------------------------------- utils
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffmpeg(*args: str) -> None:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


def font(size: int, weight: str = "Regular", mono: bool = False) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT_MONO if mono else FONT_UI, size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError, AttributeError):
        pass
    return f


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# --------------------------------------------------------------------------- cards
def backdrop(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    glow = Image.new("RGB", (w // 8, h // 8), BG)
    d = ImageDraw.Draw(glow)
    d.ellipse((w // 8 * 0.45, -h // 8 * 0.35, w // 8 * 1.25, h // 8 * 0.55), fill=(70, 26, 8))
    d.ellipse((-w // 8 * 0.3, h // 8 * 0.6, w // 8 * 0.35, h // 8 * 1.3), fill=(38, 16, 8))
    glow = glow.filter(ImageFilter.GaussianBlur(14)).resize((w, h), Image.BICUBIC)
    return Image.blend(img, glow, 0.9)


def draw_logo(d: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """Orange disc with a drawn 8-spoke asterisk (the system font has no ✻ glyph)."""
    import math
    d.ellipse((x, y, x + s, y + s), fill=ACCENT)
    cx, cy, r, wd = x + s / 2, y + s / 2, s * 0.28, max(3, int(s * 0.075))
    for k in range(4):
        a = math.pi / 4 * k
        dx, dy = r * math.cos(a), r * math.sin(a)
        d.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=(255, 255, 255), width=wd)
    d.ellipse((cx - wd, cy - wd, cx + wd, cy + wd), fill=(255, 255, 255))


def title_card(path: Path, w: int, h: int, kicker: str, title: str, subtitle: str, footer: str = "") -> None:
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)
    cx = w // 2
    draw_logo(d, cx - 48, int(h * 0.27), 96)
    d.text((cx, h * 0.27 + 150), kicker.upper(), font=font(26, "Semibold"), fill=ACCENT, anchor="mm")
    d.text((cx, h * 0.27 + 230), title, font=font(92, "Bold"), fill=TEXT, anchor="mm")
    y = h * 0.27 + 330
    for line in subtitle.split("\n"):
        d.text((cx, y), line, font=font(38), fill=DIM, anchor="mm")
        y += 56
    if footer:
        d.text((cx, h - 90), footer, font=font(26), fill=DIM, anchor="mm")
    img.save(path)


def results_card(path: Path, w: int, h: int, res: dict) -> None:
    img = backdrop(w, h)
    d = ImageDraw.Draw(img)
    m = 110
    d.text((m, 95), "GENERATED PROJECT", font=font(26, "Semibold"), fill=ACCENT)
    d.text((m, 135), res["headline"], font=font(64, "Bold"), fill=TEXT)

    def panel(x0, y0, x1, y1, heading):
        d.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=(22, 20, 19), outline=(52, 48, 45), width=2)
        d.text((x0 + 40, y0 + 34), heading, font=font(24, "Semibold"), fill=DIM)

    top, bottom, mid = 290, h - 100, w // 2 + 10
    panel(m, top, mid - 25, bottom, "FILES")
    mono = font(27, mono=True)
    y = top + 90
    for line in res["tree"][:22]:
        d.text((m + 40, y), line, font=mono, fill=TEXT if not line.startswith("…") else DIM)
        y += 38

    panel(mid + 25, top, w - m, bottom, "VERIFICATION")
    y = top + 95
    for label, value, ok in res["checks"]:
        d.text((mid + 65, y), "✓" if ok else "!", font=font(34, "Bold"), fill=GREEN if ok else AMBER)
        d.text((mid + 115, y), label, font=font(32, "Semibold"), fill=TEXT)
        y += 46
        for vl in value.split("\n"):
            d.text((mid + 115, y), vl, font=font(26, mono=True), fill=DIM)
            y += 36
        y += 26
    img.save(path)


# ----------------------------------------------------------------- run results
def project_tree(project: Path) -> list[str]:
    skip = {"node_modules", ".codeagent", ".git"}
    files = sorted(p.relative_to(project).as_posix() for p in project.rglob("*")
                   if p.is_file() and not skip.intersection(p.relative_to(project).parts))
    lines = [f for f in files[:21]]
    if len(files) > 21:
        lines.append(f"… and {len(files) - 21} more")
    return lines


def npm_tests(project: Path) -> dict | None:
    pkg = project / "package.json"
    if not pkg.exists() or not shutil.which("npm"):
        return None
    try:
        if not json.loads(pkg.read_text()).get("scripts", {}).get("test"):
            return None
    except ValueError:
        return None
    try:
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=project, capture_output=True,
                       text=True, timeout=600)
        proc = subprocess.run(["npm", "test"], cwd=project, capture_output=True, text=True, timeout=600,
                              env={**os.environ, "CI": "1"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": "npm test timed out"}
    out = proc.stdout + proc.stderr
    passed = failed = None
    if m := re.search(r"Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(\d+) passed, (\d+) total", out):   # jest
        failed, passed = int(m.group(1) or 0), int(m.group(2))
    elif m := re.search(r"# pass (\d+)\s+# fail (\d+)", out):                                             # node:test
        passed, failed = int(m.group(1)), int(m.group(2))
    elif m := re.search(r"(\d+) passing", out):                                                          # mocha
        passed, failed = int(m.group(1)), int((re.search(r"(\d+) failing", out) or [0, 0])[1])
    total = (passed or 0) + (failed or 0)
    summary = f"{passed}/{total} tests pass" if passed is not None else ("npm test passed" if proc.returncode == 0
                                                                       else "npm test failed")
    return {"ok": proc.returncode == 0, "passed": passed, "total": total, "summary": summary}


def collect(project: Path, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text())
    from codeagent.tools import Workspace, collect_project_issues

    meta = project / ".codeagent"
    result = json.loads((meta / "run_result.json").read_text())
    transcript = [json.loads(l) for l in (meta / "transcript.jsonl").read_text().splitlines() if l.strip()]
    rejections = sum(1 for m in transcript if m.get("role") == "tool" and "finish` rejected" in m.get("content", ""))
    spec = json.loads((meta / "spec.json").read_text())
    from codeagent.preprocess import compact_spec
    blocking, _, stats = collect_project_issues(Workspace(project, spec=compact_spec(spec)))
    tree, n_files = project_tree(project), len(project_tree_files(project))   # before npm install
    tests = npm_tests(project)
    data = {
        "turns": result["turns"], "elapsed_s": result["elapsed_s"], "success": result["success"],
        "stop_reason": result["stop_reason"], "files": n_files,
        "usage": result["usage"], "rejections": rejections, "blocking": blocking,
        "coverage": stats.get("coverage", []), "tests": tests, "tree": tree,
        "spec_issues": len(spec.get("spec_issues", [])), "diagrams": spec["meta"]["diagram_count"],
    }
    cache.write_text(json.dumps(data, indent=1))
    return data


def project_tree_files(project: Path) -> list[Path]:
    skip = {"node_modules", ".codeagent", ".git"}
    return [p for p in project.rglob("*") if p.is_file() and not skip.intersection(p.relative_to(project).parts)]


# ------------------------------------------------------------------- narration
def provider_line(provider: str, model: str) -> str:
    if provider == "deepseek":
        return f"This run uses DeepSeek V4 Pro through the official DeepSeek API."
    return (f"For this recording we use {model.replace('-', ' ')} as a low-cost test model; "
            "the submission build runs on DeepSeek V4 Pro.")


def scenes(res: dict, marks: dict, provider: str, model: str) -> list[dict]:
    """Each scene: narration text + either a card or a [from_mark, to_mark] range of the recording."""
    S: list[dict] = []
    S.append({"card": "intro", "say":
              "This is Code Agent: a simplified, Claude Code style coding agent. "
              "It reads an architecture specification and builds a complete software project on its own."})
    S.append({"range": ("idle", "start"), "say":
              "The desktop app has four controls: the model provider and A P I key, the input specification "
              "files, an output folder, and a button to start. " + provider_line(provider, model)})
    S.append({"range": ("start", "plan"), "say":
              f"First, the inputs are preprocessed into structured JSON. The architecture document and all "
              f"{res['diagrams']} PlantUML diagrams become classes, use cases, a state machine and scenarios. "
              f"{res['spec_issues']} inconsistencies between the documents are flagged for the agent to resolve."})
    # Writing must come visibly after the plan; older recordings could mark both at once.
    if "writing" not in marks or marks["writing"] - marks.get("plan", 0) < 3:
        marks["writing"] = marks.get("plan", marks["start"]) + 8
    if "writing" in marks:
        S.append({"range": ("plan", "writing"), "say":
                  "Like Claude Code, the agent begins by writing a plan. Every task is tracked live, "
                  "with exactly one in progress at a time."})
    gate_mark = "rejected" if "rejected" in marks else "done"
    S.append({"range": ("writing" if "writing" in marks else "plan", gate_mark), "say":
              "Then it works in a tool loop. The model reads the spec and writes files through sandboxed tools "
              "that can only touch the output folder, and each step appears in the transcript as it happens."})
    gate = ("It checks syntax, imports and the required deliverables, and whether every class, use case and "
            "state transition in the spec is implemented and tested.")
    if res["rejections"]:
        times = "once" if res["rejections"] == 1 else f"{res['rejections']} times"
        tail = (" After that, the project passed." if not res["blocking"] else
                " Some gaps remained, and the run reports them instead of claiming success.")
        S.append({"range": ("rejected", "done"), "say":
                  f"Before it can finish, the agent must pass a quality gate. {gate} Here the gate rejected "
                  f"the work {times}, and the agent went back to fill the gaps.{tail}"})
    else:
        result = (" This run passed it on the first attempt." if not res["blocking"] else
                  " Some gaps remained, and the run reports them instead of claiming success.")
        S[-1]["say"] += f" Before finishing, the agent must pass a quality gate. {gate}{result}"
    minutes = res["elapsed_s"] / 60
    S.append({"range": ("done", "recap_start"), "say":
              f"The run finished in {res['turns']} turns and about {max(1, round(minutes))} "
              f"minute{'s' if round(minutes) > 1 else ''}, writing {res['files']} files."})
    S.append({"range": ("recap_start", "recap_end"), "say":
              "Here is the full transcript of the run, from the plan to the final check."})
    t = res.get("tests")
    test_line = (f"Its own test suite runs, and {t['summary'].replace('/', ' of ')}." if t and t.get("passed") is not None
                 else "")
    S.append({"card": "results", "say":
              "The output includes source code, a package manifest, a Dockerfile, a README, tests, and the "
              f"artifacts named in the spec. {test_line}"})
    S.append({"card": "outro", "say":
              "Code Agent ships as a single Windows executable: an Electron interface with a bundled Python "
              "backend, so no Python or Node installation is needed. Thanks for watching."})
    return S


# ------------------------------------------------------------------------ build
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path(__file__).parent / "raw")
    ap.add_argument("--project", type=Path, required=True, help="output folder of the recorded run")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out" / "CodeAgent-demo.mp4")
    ap.add_argument("--voice", default=os.environ.get("VOICE", "Samantha"))
    ap.add_argument("--rate", type=int, default=int(os.environ.get("RATE", "178")))
    ap.add_argument("--width", type=int, default=1920)
    args = ap.parse_args()
    # ffmpeg's concat demuxer resolves relative entries against the list file, so use absolute paths
    args.raw, args.project, args.out = args.raw.resolve(), args.project.resolve(), args.out.resolve()

    rec = json.loads((args.raw / "recording.json").read_text())
    frames, vp = rec["frames"], rec["viewport"]
    t0 = frames[0]["t"]
    marks = {k: v - t0 for k, v in rec["marks"].items() if isinstance(v, (int, float))}
    W = args.width
    H = int(round(W * vp["height"] / vp["width"] / 2) * 2)
    work = args.out.parent / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    settings = json.loads((Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
                           / "CodeAgent" / "settings.json").read_text())
    provider, model = settings.get("provider", "deepseek"), settings.get("model", "deepseek-v4-pro")
    print("collecting run results (npm install + npm test)…")
    res = collect(args.project, args.raw / "results.json")

    # Cards
    t = res.get("tests") or {}
    checks = [
        ("Agent run", f"{res['turns']} turns · {res['elapsed_s']:.0f}s · stop: {res['stop_reason']}",
         res["success"]),
        ("Quality gate", f"{len(res['blocking'])} blocking issue(s) left\n"
                         f"finish rejected {res['rejections']} time{'' if res['rejections'] == 1 else 's'}",
         not res["blocking"]),
        ("Spec coverage", compact_coverage(res["coverage"]) or "n/a", not res["blocking"]),
        ("npm test", t.get("summary", "not run"), bool(t.get("ok"))),
    ]
    res_for_card = {**res, "headline": f"{res['files']} files, written by the agent", "checks": checks}
    title_card(work / "intro.png", W, H, "Simplified Claude Code-style agent", "CodeAgent",
               "Architecture spec in. Complete project out.",
               footer=f"Recorded run · {model}")
    results_card(work / "results.png", W, H, res_for_card)
    title_card(work / "outro.png", W, H, "Windows desktop app", "One double-click .exe",
               "Electron UI  ·  bundled Python backend  ·  no runtime to install\n"
               "Preprocess  →  plan  →  tool loop  →  quality gate  →  project")

    # Master recording at constant frame rate
    lst = work / "frames.txt"
    with open(lst, "w") as fh:
        for i, f in enumerate(frames):
            nxt = frames[i + 1]["t"] if i + 1 < len(frames) else rec["marks"]["end"]
            fh.write(f"file '{(args.raw / 'frames' / f['file']).as_posix()}'\nduration {max(0.001, nxt - f['t']):.4f}\n")
        fh.write(f"file '{(args.raw / 'frames' / frames[-1]['file']).as_posix()}'\n")
    master = work / "master.mp4"
    print("encoding master recording…")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-fps_mode", "cfr", "-r", str(FPS),
           "-vf", f"scale={W}:{H}:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
           str(master))

    # Scenes
    clips, srt, clock = [], [], 0.0
    for i, sc in enumerate(scenes(res, marks, provider, model)):
        if "range" in sc and sc["range"][0] not in marks:
            print(f"scene {i + 1}: skipped (no '{sc['range'][0]}' mark in this recording)")
            continue
        aiff, wav = work / f"s{i}.aiff", work / f"s{i}.wav"
        run(["say", "-v", args.voice, "-r", str(args.rate), "-o", str(aiff), sc["say"]])
        ffmpeg("-i", str(aiff), "-ar", "48000", "-ac", "2", "-af", "apad=pad_dur=0.7", str(wav))
        T = duration(wav)
        clip = work / f"s{i}.mp4"
        common = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-r", str(FPS), "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{T:.3f}"]
        if "card" in sc:
            fade = f"fade=t=in:st=0:d=0.5,fade=t=out:st={T - 0.5:.3f}:d=0.5" if sc["card"] != "results" else \
                f"fade=t=in:st=0:d=0.4"
            ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(work / f"{sc['card']}.png"), "-i", str(wav),
                   "-vf", f"scale={W}:{H},{fade}", *common, str(clip))
        else:
            if sc["range"][0] not in marks:
                print(f"scene {i + 1}: skipped (no '{sc['range'][0]}' mark in this recording)")
                continue
            a, b = (marks[sc["range"][0]], marks.get(sc["range"][1], marks["end"]))
            src = max(0.1, b - a)
            if src > T:
                speed = src / T
                vf = f"setpts=PTS*{T / src:.6f}"
                if speed >= 1.5:
                    badge = work / f"badge{i}.png"
                    speed_badge(badge, f"{speed:.0f}× speed")
                    filt = f"[0:v]{vf}[v];[v][2:v]overlay=W-w-40:H-h-40[out]"
                    ffmpeg("-ss", f"{a:.3f}", "-t", f"{src:.3f}", "-i", str(master), "-i", str(wav),
                           "-i", str(badge), "-filter_complex", filt, "-map", "[out]", "-map", "1:a",
                           *common, str(clip))
                    clips.append(clip)
                    srt.append((clock, clock + T, sc["say"]))
                    clock += T
                    continue
            else:
                vf = f"tpad=stop_mode=clone:stop_duration={T - src + 0.1:.3f}"
            ffmpeg("-ss", f"{a:.3f}", "-t", f"{src:.3f}", "-i", str(master), "-i", str(wav),
                   "-map", "0:v", "-map", "1:a", "-vf", vf, *common, str(clip))
        clips.append(clip)
        srt.append((clock, clock + T, sc["say"]))
        clock += T
        print(f"scene {i + 1}: {T:.1f}s")

    concat = work / "clips.txt"
    concat.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(args.out))
    args.out.with_suffix(".srt").write_text("".join(
        f"{n}\n{srt_time(s)} --> {srt_time(e)}\n{text}\n\n" for n, (s, e, text) in enumerate(srt, 1)))
    args.out.with_suffix(".txt").write_text("\n\n".join(text for _, _, text in srt) + "\n")
    print(f"done: {args.out} ({clock:.0f}s)")


def compact_coverage(lines: list[str]) -> str:
    """'states 3/3, transitions implemented 0/3, tested 1/3' -> 'transitions 0/3 built · 1/3 tested'"""
    out = []
    for line in lines:
        line = re.sub(r"^states \d+/\d+, ", "", line)
        line = re.sub(r"(transitions|use cases) implemented (\d+/\d+), tested (\d+/\d+)", r"\1 \2 built · \3 tested", line)
        out.append(line.replace(", ", " · "))
    if len(out) >= 2 and out[-1].startswith("test cases") and out[-2].startswith("scenario"):
        out[-2:] = [f"{out[-2]} · {out[-1]}"]
    return "\n".join(out)


def speed_badge(path: Path, label: str) -> None:
    f = font(30, "Semibold")
    w = int(f.getlength(label)) + 76
    img = Image.new("RGBA", (w, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, 63), radius=32, fill=(20, 18, 17, 225), outline=(*ACCENT, 255), width=2)
    d.text((40, 32), "»", font=font(34, "Bold"), fill=ACCENT, anchor="mm")
    d.text((62, 32), label, font=f, fill=TEXT, anchor="lm")
    img.save(path)


if __name__ == "__main__":
    main()
