#!/usr/bin/env python3
"""Open-source MISRA stand-in for ZiSE25's ECLAIR analysis.

Runs cppcheck's MISRA C:2012 addon on the application sources, using the exact
compile commands from a Zephyr build.

This is NOT ECLAIR and NOT equivalent to ZiSE25's ECLAIR MISRA C:2025 analysis:
  * cppcheck's free addon covers a subset of MISRA C:2012 rules, without rule texts;
  * sources are preprocessed with the build's own compiler first, because cppcheck's
    preprocessor cannot expand Zephyr's IS_ENABLED() macro; Rule 20.x (preprocessing)
    findings are therefore dropped;
  * findings on lines that invoke an upper-case macro are reported separately as
    "in adopted macro expansion", roughly mirroring how ZiSE25's ECLAIR configuration
    treats Zephyr macros as adopted code (Rule 17.7 findings always stay native).

Usage:
  open_misra_check.py BUILD_DIR OUT_DIR [--app-dir DIR] [--baseline misra_findings.json]
Exit status is 1 when --baseline is given and there are new native findings.
"""
import argparse
import collections
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

ap = argparse.ArgumentParser()
ap.add_argument("build_dir")
ap.add_argument("out_dir")
ap.add_argument("--app-dir", default=os.getcwd())
ap.add_argument("--baseline")
a = ap.parse_args()

app = os.path.abspath(a.app_dir)
os.makedirs(a.out_dir, exist_ok=True)
cc = json.load(open(os.path.join(a.build_dir, "compile_commands.json")))

addon = next((p for p in ("/usr/lib/x86_64-linux-gnu/cppcheck/addons/misra.py",
                          "/usr/share/cppcheck/addons/misra.py",
                          "/usr/local/share/Cppcheck/addons/misra.py") if os.path.exists(p)), None)
if not addon:
    sys.exit("cppcheck MISRA addon (misra.py) not found")

MACRO_CALL = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\s*\(")
LINE = re.compile(r"^\[(.*?):(\d+)\].*\[misra-c2012-([\d.]+)\]")
app_src = [c for c in cc if os.path.abspath(c["file"]).startswith(os.path.join(app, "src") + os.sep)]
findings, dropped_20 = [], 0
tmp = tempfile.mkdtemp()
for c in app_src:
    src = os.path.abspath(c["file"])
    args = c.get("arguments") or shlex.split(c["command"])
    pp, i = [], 0
    while i < len(args):
        if args[i] == "-o":
            i += 2
            continue
        if args[i] != "-c":
            pp.append(args[i])
        i += 1
    ifile = os.path.join(tmp, os.path.basename(src) + ".i")
    r = subprocess.run(pp + ["-E", "-o", ifile], cwd=c["directory"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"preprocessing failed for {src}:\n{r.stderr}")
    # cppcheck attributes lines correctly only with "#line N" directives, not GCC's "# N file flags" markers.
    marker = re.compile(r'^# (\d+) "(.*?)"(?: \d+)*\s*$')
    with open(ifile, encoding="utf-8", errors="replace") as fh:
        conv = [(lambda m: f'#line {m.group(1)} "{m.group(2)}"' if m else l)(marker.match(l))
                for l in fh.read().splitlines()]
    with open(ifile, "w", encoding="utf-8") as fh:
        fh.write("\n".join(conv) + "\n")
    plat = "unix32" if "-m32" in args else "unix64"
    subprocess.run(["cppcheck", "--dump", "-q", "--std=c11", f"--platform={plat}", ifile],
                   capture_output=True, text=True)
    r = subprocess.run([sys.executable, addon, ifile + ".dump"], capture_output=True, text=True)
    lines_cache = {}
    for line in (r.stdout + r.stderr).splitlines():
        m = LINE.match(line)
        if not m:
            continue
        path = os.path.abspath(m.group(1))
        if not path.startswith(app + os.sep) or "/deps/" in path or "/build" in path:
            continue
        rule = m.group(3)
        if rule.startswith("20."):
            dropped_20 += 1
            continue
        ln = int(m.group(2))
        if path not in lines_cache:
            lines_cache[path] = open(path, encoding="utf-8", errors="replace").read().splitlines()
        text = lines_cache[path][ln - 1] if 0 < ln <= len(lines_cache[path]) else ""
        # Rule 17.7 (ignored return value) is about the app's own call statement, so it stays native.
        kind = "adopted-macro" if (MACRO_CALL.search(text) and rule != "17.7") else "native"
        findings.append({"file": os.path.relpath(path, app), "line": ln, "rule": rule, "kind": kind,
                         "source": text.strip()})

# Deduplicate (a file's findings can be reported once per translation unit that includes it)
uniq = {(f["file"], f["line"], f["rule"]): f for f in findings}
findings = sorted(uniq.values(), key=lambda f: (f["file"], f["line"], f["rule"]))
json.dump(findings, open(os.path.join(a.out_dir, "misra_findings.json"), "w"), indent=1)

native = [f for f in findings if f["kind"] == "native"]
rule_key = lambda r: [int(p) for p in r.split(".")]
by_rule = collections.Counter(f["rule"] for f in native)
by_file = collections.Counter(f["file"] for f in native)

new = []
if a.baseline and os.path.exists(a.baseline):
    base = [f for f in json.load(open(a.baseline)) if f.get("kind", "native") == "native"]
    bc = collections.Counter((f["file"], f["rule"]) for f in base)
    cur = collections.Counter((f["file"], f["rule"]) for f in native)
    for k, n in sorted(cur.items()):
        if n > bc.get(k, 0):
            added = [f for f in native if (f["file"], f["rule"]) == k]
            new.append({"file": k[0], "rule": k[1], "added": n - bc.get(k, 0),
                        "candidates": [f"{f['file']}:{f['line']}" for f in added]})
    json.dump(new, open(os.path.join(a.out_dir, "misra_new_findings.json"), "w"), indent=1)

ver = subprocess.run(["cppcheck", "--version"], capture_output=True, text=True).stdout.strip()
out = []
out.append("OPEN-SOURCE STAND-IN. Not ECLAIR, not MISRA C:2025, not a compliance claim.")
out.append(f"{ver}, MISRA C:2012 addon, {len(app_src)} application translation units")
out.append("")
out.append(f"Native findings: {len(native)} across {len(by_file)} files and {len(by_rule)} rules")
out.append(f"Findings inside adopted (Zephyr) macro expansions, reported separately: "
           f"{len(findings) - len(native)}")
out.append(f"Rule 20.x findings dropped (preprocessed input): {dropped_20}")
out.append("")
for r in sorted(by_rule, key=rule_key):
    out.append(f"  Rule {r:<6} {by_rule[r]:>4}")
if a.baseline:
    out.append("")
    out.append(f"New native findings compared with baseline: {sum(n['added'] for n in new)}")
    for n in new:
        out.append(f"  NEW  Rule {n['rule']} in {n['file']} (+{n['added']})")
summary = "\n".join(out) + "\n"
open(os.path.join(a.out_dir, "misra_summary.txt"), "w").write(summary)

rows = "".join(
    f"<tr><td>{html.escape(f['file'])}:{f['line']}</td><td>{f['rule']}</td><td>{f['kind']}</td>"
    f"<td><code>{html.escape(f['source'])}</code></td></tr>" for f in findings)
open(os.path.join(a.out_dir, "index.html"), "w").write(
    "<!doctype html><meta charset=utf-8><title>MISRA stand-in</title>"
    "<style>body{font:14px Arial;margin:24px;color:#171717}td,th{border:1px solid #ccc;padding:4px 8px;"
    "text-align:left}table{border-collapse:collapse}code{font:12px Consolas,monospace}</style>"
    f"<h1>MISRA stand-in (cppcheck)</h1><pre>{html.escape(summary)}</pre>"
    "<table><tr><th>Location</th><th>Rule</th><th>Kind</th><th>Source line</th></tr>" + rows + "</table>")
print(summary)
sys.exit(1 if new else 0)
