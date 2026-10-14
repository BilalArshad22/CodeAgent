#!/usr/bin/env bash
# Record a real CodeAgent run and turn it into a narrated demo video.
#   video/make_video.sh            -> video/out/CodeAgent-demo.mp4 (+ .srt subtitles, .txt script)
# Uses the provider/model/key saved in the app (DeepSeek V4 Pro for the submission video).
# VOICE=Samantha RATE=178 override the narration voice and speed.
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DIR="${RUN_DIR:-$HOME/Downloads/Task1/demo-run-$(date +%Y%m%d-%H%M%S)}"
SETTINGS="${XDG_CONFIG_HOME:-$HOME/.config}/CodeAgent/settings.json"
BACKUP="$(mktemp)"
cp "$SETTINGS" "$BACKUP"
trap 'cp "$BACKUP" "$SETTINGS"; rm -f "$BACKUP"' EXIT    # always restore the user's settings

python3 - "$SETTINGS" "$RUN_DIR" "$PWD/src/codeagent/samples" <<'PY'
import json, sys
path, run_dir, samples = sys.argv[1:]
s = json.load(open(path))
s["output_dir"] = run_dir
s["input_files"] = [f"{samples}/Architecture_Documentation.md", f"{samples}/Architecture_View.md"]
json.dump(s, open(path, "w"), indent=2)
print(f"provider={s['provider']} model={s['model']} output={run_dir}")
PY

(cd desktop && npx vite build >/dev/null)
node video/record.mjs video/raw
python3 video/build.py --raw video/raw --project "$RUN_DIR" --out video/out/CodeAgent-demo.mp4
