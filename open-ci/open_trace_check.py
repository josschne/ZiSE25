#!/usr/bin/env python3
"""Open-source requirements-traceability stand-in for ZiSE25's ECLAIR REQMAN analysis.

Reads the software requirements (SRS-*) from temp_alert.sdoc with ZiSE25's own
read_sdoc.py, then checks the Doxygen tags ZiSE25 uses:
  * "@implements SRS-xx" in src/ and inc/
  * "@tests SRS-xx" in tests/
and reports, in the spirit of MISRA C Directive 3.1:
  * software requirements with no implementation or no test;
  * tags that name a requirement that does not exist;
  * functions in src/ whose comment block names no requirement.

This is NOT ECLAIR. Function detection uses universal-ctags and the comment block
directly above each function definition.

Usage: open_trace_check.py OUT_DIR [--app-dir DIR] [--sdoc temp_alert.sdoc]
Exit status is 1 when a software requirement is unimplemented or untested, or a tag is dangling.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import shutil

CTAGS = shutil.which("ctags-universal") or shutil.which("ctags") or "ctags"
ap = argparse.ArgumentParser()
ap.add_argument("out_dir")
ap.add_argument("--app-dir", default=os.getcwd())
ap.add_argument("--sdoc", default="temp_alert.sdoc")
a = ap.parse_args()
app = os.path.abspath(a.app_dir)
os.makedirs(a.out_dir, exist_ok=True)
sys.path.insert(0, os.path.join(app, "scripts"))
from read_sdoc import extract_requirements_from_file  # noqa: E402  (ZiSE25's own reader)

reqs = extract_requirements_from_file(os.path.join(app, a.sdoc))
srs = sorted(u for u in reqs if u.startswith("SRS-"))
TAG = re.compile(r"@(implements|tests)\s+((?:SRS|LLR|HLR)-[\w-]+)")


def scan(dirs, exts=(".c", ".h")):
    for d in dirs:
        for root, _, files in os.walk(os.path.join(app, d)):
            for f in sorted(files):
                if f.endswith(exts):
                    p = os.path.join(root, f)
                    for n, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                        for m in TAG.finditer(line):
                            yield m.group(1), m.group(2), f"{os.path.relpath(p, app)}:{n}"


impl, tests, dangling = {}, {}, []
for kind, uid, where in list(scan(["src", "inc"])) + list(scan(["tests"])):
    (impl if kind == "implements" else tests).setdefault(uid, []).append(where)
    if uid not in reqs:
        dangling.append({"tag": kind, "uid": uid, "at": where})

# Functions without a requirement tag in their comment block.
untagged = []
srcs = [os.path.join(app, "src", f) for f in sorted(os.listdir(os.path.join(app, "src"))) if f.endswith(".c")]
ct = subprocess.run([CTAGS, "-x", "--kinds-C=f", "--_xformat=%N\t%n\t%F", *srcs], capture_output=True, text=True)
for line in ct.stdout.splitlines():
    name, ln, path = line.split("\t")
    lines = open(path, encoding="utf-8").read().splitlines()
    i, block = int(ln) - 2, []
    while i >= 0 and (lines[i].strip() == "" or lines[i].strip().startswith(("*", "/*", "//", "*/"))
                      or lines[i].strip().endswith("*/")):
        block.append(lines[i])
        if lines[i].strip().startswith("/*"):
            break
        i -= 1
    if not any("@implements" in b for b in block):
        untagged.append({"function": name, "at": f"{os.path.relpath(path, app)}:{ln}"})

rows = []
for u in srs:
    rows.append({"srs": u, "component": reqs[u].component, "parents": sorted(reqs[u].parents),
                 "implemented_at": impl.get(u, []), "tested_at": tests.get(u, [])})
unimpl = [r["srs"] for r in rows if not r["implemented_at"]]
untested = [r["srs"] for r in rows if not r["tested_at"]]
json.dump({"requirements": rows, "dangling": dangling, "untagged_functions": untagged},
          open(os.path.join(a.out_dir, "trace.json"), "w"), indent=1)

out = ["OPEN-SOURCE STAND-IN. Not ECLAIR. Tags checked: @implements (src, inc) and @tests (tests).", "",
       f"Requirements in {a.sdoc}: {len(reqs)} total, {len(srs)} software (SRS)",
       f"SRS with no @implements: {len(unimpl)}  {' '.join(unimpl)}",
       f"SRS with no @tests: {len(untested)}  {' '.join(untested)}",
       f"Tags naming a requirement that does not exist: {len(dangling)}"]
out += [f"  {d['at']}: @{d['tag']} {d['uid']}" for d in dangling]
out.append(f"Functions in src/ with no @implements in their comment block: {len(untagged)}")
out += [f"  {u['at']}: {u['function']}()" for u in untagged]
out += ["", "SRS          implemented at                     tested at"]
for r in rows:
    out.append(f"{r['srs']:<12} {', '.join(r['implemented_at']) or '-':<34} {', '.join(r['tested_at']) or '-'}")
summary = "\n".join(out) + "\n"
open(os.path.join(a.out_dir, "trace_summary.txt"), "w").write(summary)

trs = "".join(
    f"<tr class='{'' if r['implemented_at'] and r['tested_at'] else 'gap'}'><td>{r['srs']}</td>"
    f"<td>{html.escape(', '.join(r['parents']))}</td><td>{html.escape(r['component'] or '')}</td>"
    f"<td>{html.escape(', '.join(r['implemented_at']) or 'none')}</td>"
    f"<td>{html.escape(', '.join(r['tested_at']) or 'none')}</td></tr>" for r in rows)
open(os.path.join(a.out_dir, "index.html"), "w").write(
    "<!doctype html><meta charset=utf-8><title>Traceability stand-in</title><style>body{font:14px Arial;"
    "margin:24px;color:#171717}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}table{border-"
    "collapse:collapse}.gap{background:#fbe3e1}</style><h1>Traceability stand-in (not ECLAIR)</h1>"
    f"<pre>{html.escape(summary)}</pre><table><tr><th>SRS</th><th>Parents</th><th>Component</th>"
    f"<th>Implemented at</th><th>Tested at</th></tr>{trs}</table>")
print(summary)
sys.exit(1 if (unimpl or untested or dangling) else 0)
