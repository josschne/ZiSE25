#!/usr/bin/env python3
"""Open-source architecture stand-in for ZiSE25's ECLAIR independence check.

Reads the component definitions and allow rules from ECLAIR/architecture.ecl, then
approximates them with the build's own preprocessor and universal-ctags:

  * which native component (APPLICATION, BUZZER, DISPLAY, LEDS, UTILS) uses which
    component (native, or a Zephyr slice such as ZEP/SENSOR or ZEP/MMIO);
  * how: "call" (functions), "expand" (macros) or "read" (variables), the entity kinds
    ZiSE25's configuration keeps under check;
  * whether architecture.ecl allows that use.

This is NOT ECLAIR. It matches identifiers in the app's source against where ctags finds
them declared; ECLAIR works on the real program model and its semantics differ. Include
edges are reported for information only. The upstream authors reported no violations
with ECLAIR on this code.

Usage:
  open_arch_check.py BUILD_DIR OUT_DIR [--app-dir DIR] [--baseline arch_uses.json]
Exit status is 1 on any use the rules do not allow, or with --baseline on any new one.
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
import shutil

CTAGS = shutil.which("ctags-universal") or shutil.which("ctags") or "ctags"
ap = argparse.ArgumentParser()
ap.add_argument("build_dir")
ap.add_argument("out_dir")
ap.add_argument("--app-dir", default=os.getcwd())
ap.add_argument("--ecl", default="ECLAIR/architecture.ecl")
ap.add_argument("--baseline")
a = ap.parse_args()
app = os.path.abspath(a.app_dir)
os.makedirs(a.out_dir, exist_ok=True)
ecl = open(os.path.join(app, a.ecl)).read()

# ---------------------------------------------------------------- read architecture.ecl
tags = collections.defaultdict(list)
for name, rx in re.findall(r'-file_tag\+=\{(\w+),\s*"(.*?)"\}', ecl):
    tags[name].append(re.compile(rx.replace("\\\\", "\\")))
comp_of_tag = {tag: comp for comp, tag in re.findall(r'component_files\+=\s*\{([\w/]+),"(\w+)"\}', ecl)}
order = [c for c, _ in re.findall(r'component_files\+=\s*\{([\w/]+),"(\w+)"\}', ecl)]
native = [c for c in order if not c.startswith("ZEP/")]
zephyr = [c for c in order if c.startswith("ZEP/")]
# Zephyr slices are matched most specific first; ZEP/KERNEL is the catch-all for kernel headers.
zephyr_priority = [c for c in zephyr if c != "ZEP/KERNEL"] + ["ZEP/KERNEL"]

allows = []
for doc, expr in re.findall(r'-doc="([^"]*)"\s*-config=B\.INDEPENDENCE,component_allows\+=\s*"([^"]*)"', ecl, re.S):
    m = re.match(r"from\((.*?)\)&&to\((.*?)\)&&action\((.*?)\)$", expr.strip())
    if m:
        allows.append({"doc": " ".join(doc.split()), "from": set(m.group(1).split("||")),
                       "to": set(m.group(2).split("||")), "actions": set(m.group(3).split("||"))})


def allowed(frm, to, action):
    if frm == to:
        return True
    return any(frm in r["from"] and to in r["to"] and action in r["actions"] for r in allows)


def component_of_file(path):
    hits = [comp_of_tag[t] for t, rxs in tags.items() if t in comp_of_tag and any(r.match(path) for r in rxs)]
    for c in native:
        if c in hits:
            return c
    for c in zephyr_priority:
        if c in hits:
            return c
    return None


def component_of_entity(name, kind, path):
    comp = component_of_file(path)
    # Entity selectors from architecture.ecl for declarations inside the kernel headers.
    if comp in ("ZEP/KERNEL", "ZEP/THREADING", "ZEP/TIMING") and re.match(r"^.*include/zephyr/kernel.*$", path):
        if re.search(r"(thread|THREAD)", name):
            return "ZEP/THREADING"
        if kind == "macro" and re.search(r"K_(M|U)?SEC", name):
            return "ZEP/TIMING"
        if kind != "macro" and re.match(r"^k_(sleep|busy_wait)", name):
            return "ZEP/TIMING"
        return "ZEP/KERNEL"
    return comp


# ---------------------------------------------------------------- headers each file really includes
cc = json.load(open(os.path.join(a.build_dir, "compile_commands.json")))
tus = [c for c in cc if os.path.abspath(c["file"]).startswith(os.path.join(app, "src") + os.sep)]
tmp = tempfile.mkdtemp()
headers = set()
direct_includes = collections.defaultdict(set)
for c in tus:
    args = c.get("arguments") or shlex.split(c["command"])
    pp, i = [], 0
    while i < len(args):
        if args[i] == "-o":
            i += 2
            continue
        if args[i] != "-c":
            pp.append(args[i])
        i += 1
    ifile = os.path.join(tmp, os.path.basename(c["file"]) + ".i")
    subprocess.run(pp + ["-E", "-H", "-o", ifile], cwd=c["directory"], capture_output=True, text=True,
                   check=True)
    current = None
    for line in open(ifile, encoding="utf-8", errors="replace"):
        m = re.match(r'^# \d+ "(.*?)"((?: \d+)*)', line)
        if not m:
            continue
        name, flags = m.group(1), m.group(2).split()
        path = name if name.startswith("<") else os.path.abspath(os.path.join(c["directory"], name))
        if "1" in flags and current and current.startswith(app + os.sep):
            direct_includes[current].add(path)   # current file includes path
        current = path
        if name.startswith("<"):
            continue
        headers.add(path)

app_files = sorted({os.path.join(app, d, f) for d in ("src", "inc")
                    for f in os.listdir(os.path.join(app, d)) if f.endswith((".c", ".h"))})
files = sorted(headers | set(app_files))

# ---------------------------------------------------------------- where everything is declared (ctags)
kinds = {"f": "function", "p": "function", "d": "macro", "v": "variable", "x": "variable"}
listfile = os.path.join(tmp, "files.txt")
open(listfile, "w").write("\n".join(files) + "\n")
ct = subprocess.run([CTAGS, "-x", "--languages=C", "--language-force=C", "--kinds-C=fpdvx",
                     "-I", "__syscall,__deprecated,__pinned_func,__boot_func,ALWAYS_INLINE,__STATIC_INLINE",
                     "--_xformat=%N\t%K\t%F", "-L", listfile], capture_output=True, text=True)
decls = collections.defaultdict(list)
for line in ct.stdout.splitlines():
    parts = line.split("\t")
    if len(parts) == 3 and parts[1][:1] in "fpdvx":
        decls[parts[0]].append((kinds[parts[1][0]], os.path.abspath(parts[2])))
    elif len(parts) == 3:
        kk = {"function": "function", "prototype": "function", "macro": "macro", "variable": "variable",
              "externvar": "variable"}.get(parts[1])
        if kk:
            decls[parts[0]].append((kk, os.path.abspath(parts[2])))


def resolve(name, user_comp):
    """Return (component, kind) for an identifier used in user_comp, or None if unchecked."""
    cands = decls.get(name, [])
    if not cands:
        return None
    # Declared in the user's own component: internal use.
    for kind, path in cands:
        if component_of_file(path) == user_comp:
            return None
    best = None
    for kind, path in cands:
        # Another component's interface is its headers; file-scope names in its .c files are not visible.
        if path.endswith(".c"):
            continue
        comp = component_of_entity(name, kind, path)
        if comp is None:
            continue
        rank = (native + zephyr_priority).index(comp)
        if best is None or rank < best[2]:
            best = (comp, kind, rank, path)
    return (best[0], best[1], best[3]) if best else None


def strip_c(text):
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)
    out = []
    for l in text.splitlines():
        s = l.lstrip()
        if s.startswith("#"):
            # Keep the body of a #define: its expansions happen in this component's code.
            m = re.match(r"#\s*define\s+\w+(\([^)]*\))?(.*)$", s)
            l = (" " * (len(l) - len(m.group(2))) + m.group(2)) if m else ""
        out.append(l)
    return "\n".join(out)


ACTION = {"function": "call", "macro": "expand", "variable": "read"}
uses = []
for f in app_files:
    comp = component_of_file(f)
    if comp is None:
        continue
    for ln, line in enumerate(strip_c(open(f, encoding="utf-8").read()).splitlines(), 1):
        for m in re.finditer(r"\b[A-Za-z_]\w*\b", line):
            r = resolve(m.group(0), comp)
            if r:
                to, kind, where = r
                uses.append({"from": comp, "to": to, "action": ACTION[kind], "name": m.group(0),
                             "at": f"{os.path.relpath(f, app)}:{ln}",
                             "declared_in": where.split("/include/", 1)[-1] if "/include/" in where
                             else os.path.relpath(where, app),
                             "allowed": allowed(comp, to, ACTION[kind])})

includes = []
for f, incs in sorted(direct_includes.items()):
    comp = component_of_file(f)
    for h in sorted(incs):
        to = component_of_file(h)
        if comp and to and to != comp:
            includes.append({"from": comp, "to": to, "file": os.path.relpath(f, app),
                             "header": h.split("/include/", 1)[-1] if "/include/" in h else os.path.relpath(h, app),
                             "allowed": allowed(comp, to, "include")})

json.dump({"uses": uses, "includes": includes}, open(os.path.join(a.out_dir, "arch_uses.json"), "w"), indent=1)

# ---------------------------------------------------------------- report
bad = [u for u in uses if not u["allowed"]]
new = []
if a.baseline and os.path.exists(a.baseline):
    base = {(u["from"], u["to"], u["action"], u["name"]) for u in json.load(open(a.baseline))["uses"]
            if not u["allowed"]}
    new = [u for u in bad if (u["from"], u["to"], u["action"], u["name"]) not in base]

matrix = collections.defaultdict(lambda: collections.defaultdict(set))
for u in uses:
    matrix[u["from"]][u["to"]].add(u["action"] + ("" if u["allowed"] else " (NOT ALLOWED)"))
targets = [c for c in native + zephyr if any(c in matrix[f] for f in matrix)]
out = ["OPEN-SOURCE STAND-IN. Not ECLAIR. Rules read from ECLAIR/architecture.ecl.",
       f"{len(allows)} allow rules, {len(native)} native components, {len(zephyr)} Zephyr slices", "",
       f"Checked uses (call, expand, read) across component boundaries: {len(uses)}",
       f"Uses the rules do not allow: {len(bad)}"]
for u in bad:
    out.append(f"  {u['at']}: {u['from']} {u['action']} {u['name']} from {u['to']} ({u['declared_in']})")
if a.baseline:
    out.append(f"New compared with baseline: {len(new)}")
    for u in new:
        out.append(f"  NEW {u['at']}: {u['from']} {u['action']} {u['name']} from {u['to']}")
out += ["", "Who uses what (from component: to component = actions)"]
for frm in native:
    if frm in matrix:
        out.append(f"  {frm}: " + "; ".join(f"{to} = {', '.join(sorted(matrix[frm][to]))}"
                                             for to in targets if to in matrix[frm]))
inc_bad = [i for i in includes if not i["allowed"]]
out += ["", f"Include edges not covered by an include rule (information only, see note): {len(inc_bad)}"]
for i in inc_bad:
    out.append(f"  {i['file']} includes {i['header']} ({i['from']} -> {i['to']})")
summary = "\n".join(out) + "\n"
open(os.path.join(a.out_dir, "arch_summary.txt"), "w").write(summary)

cells = "".join(f"<th>{html.escape(t)}</th>" for t in targets)
rows = ""
for frm in native:
    if frm not in matrix:
        continue
    tds = ""
    for to in targets:
        acts = matrix[frm].get(to, set())
        badc = any("NOT" in x for x in acts)
        tds += (f"<td class='{'bad' if badc else ('ok' if acts else '')}'>"
                f"{html.escape(', '.join(sorted(acts)))}</td>")
    rows += f"<tr><th>{html.escape(frm)}</th>{tds}</tr>"
rules = "".join(f"<li>{html.escape(r['doc'])}</li>" for r in allows)
open(os.path.join(a.out_dir, "index.html"), "w").write(
    "<!doctype html><meta charset=utf-8><title>Architecture stand-in</title><style>body{font:14px Arial;}pre{white-space:pre-wrap}body{"
    "margin:24px;color:#171717}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}table{border-"
    "collapse:collapse}.ok{background:#e8f3ea}.bad{background:#fbe3e1;font-weight:bold}</style>"
    "<h1>Architecture stand-in (not ECLAIR)</h1>"
    f"<pre>{html.escape(summary)}</pre><h2>Uses by component</h2><table><tr><th>From \\ To</th>{cells}</tr>"
    f"{rows}</table><h2>Allow rules read from architecture.ecl</h2><ul>{rules}</ul>")
print(summary)
sys.exit(1 if (new if a.baseline else bad) else 0)
