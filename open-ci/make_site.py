#!/usr/bin/env python3
"""Assemble the open reproduction report site from the outputs of open_reproduction.yml.

Usage: make_site.py RESULTS_DIR SITE_DIR
RESULTS_DIR holds: twister/ (twister.json, coverage/), strictdoc/html, check_requirements.txt,
misra/, arch/, trace/, versions.txt, and optionally new_findings.txt.
"""
import html
import json
import os
import shutil
import sys
from datetime import datetime, timezone

res, site = sys.argv[1], sys.argv[2]
shutil.rmtree(site, ignore_errors=True)
os.makedirs(site)


def read(p, default=""):
    try:
        return open(os.path.join(res, p), encoding="utf-8").read()
    except OSError:
        return default


def copy(src, dst):
    s = os.path.join(res, src)
    if os.path.isdir(s):
        shutil.copytree(s, os.path.join(site, dst))
        return True
    if os.path.isfile(s):
        os.makedirs(os.path.dirname(os.path.join(site, dst)) or site, exist_ok=True)
        shutil.copy(s, os.path.join(site, dst))
        return True
    return False


tests = "no twister.json"
try:
    tj = json.load(open(os.path.join(res, "twister", "twister.json")))
    cases = [tc for ts in tj.get("testsuites", []) for tc in ts.get("testcases", [])]
    passed = sum(1 for tc in cases if tc.get("status") == "passed")
    suites = tj.get("testsuites", [])
    ok = sum(1 for s in suites if s.get("status") == "passed")
    tests = f"{passed} of {len(cases)} test cases passed, {ok} of {len(suites)} test configurations passed"
except (OSError, ValueError):
    pass
cov = ""
try:
    cs = json.load(open(os.path.join(res, "twister", "coverage_summary.json")))
    cov = (f"{cs['line_percent']}% of lines and {cs['branch_percent']}% of branches in src/ "
           f"({cs['line_covered']}/{cs['line_total']} lines, {cs['branch_covered']}/{cs['branch_total']} branches)")
    rows = "".join(f"<tr><td>{html.escape(f['filename'])}</td><td>{f['line_percent']}%</td>"
                   f"<td>{f['branch_percent']}%</td></tr>" for f in cs["files"])
    cov += ("<table><tr><th>File</th><th>Lines</th><th>Branches</th></tr>" + rows + "</table>")
except (OSError, ValueError, KeyError):
    pass

copy("twister/coverage", "coverage")
for f in ("twister.json", "twister.xml", "twister_report.xml", "twister_suite_report.xml", "testplan.json",
          "twister.log", "coverage_summary.json"):
    copy(f"twister/{f}", f"tests/{f}")
have_sd = copy("strictdoc/html", "requirements")
for d in ("misra", "arch", "trace"):
    copy(d, d)
copy("check_requirements.txt", "check_requirements.txt")
copy("versions.txt", "versions.txt")

sha = os.environ.get("GITHUB_SHA", "local")
run = os.environ.get("GITHUB_RUN_ID", "")
repo = os.environ.get("GITHUB_REPOSITORY", "")
run_url = f"https://github.com/{repo}/actions/runs/{run}" if run and repo else ""
when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
chk = read("check_requirements.txt").strip() or "No problems reported."
new = read("new_findings.txt").strip()


def block(title, body, link=None, stand_in=False):
    tag = "<span class=si>Open-source stand-in, not ECLAIR</span>" if stand_in else \
          "<span class=same>Same tool as upstream</span>"
    a = f' <a href="{link}">Open report</a>' if link else ""
    return f"<section><h2>{html.escape(title)} {tag}</h2>{body}<p>{a}</p></section>"


body = "".join([
    block("Tests (twister on native_sim)", f"<p>{html.escape(tests)}</p>", "tests/twister_report.xml"),
    block("Coverage (gcovr via twister)", f"<p>{cov}</p>", "coverage/index.html"),
    block("Requirements document (StrictDoc)", "<p>Same export the upstream workflow deployed to Pages.</p>",
          "requirements/index.html" if have_sd else None),
    block("Requirements hierarchy check (ZiSE25's check_requirements.py)", f"<pre>{html.escape(chk)}</pre>",
          "check_requirements.txt"),
    block("MISRA C (cppcheck addon, MISRA C:2012 subset)",
          f"<pre>{html.escape(read('misra/misra_summary.txt'))}</pre>", "misra/index.html", True),
    block("Architecture rules from ECLAIR/architecture.ecl",
          f"<pre>{html.escape(read('arch/arch_summary.txt'))}</pre>", "arch/index.html", True),
    block("Requirements traceability tags (@implements, @tests)",
          f"<pre>{html.escape(read('trace/trace_summary.txt'))}</pre>", "trace/index.html", True),
])
if new:
    body = block("New findings compared with the pull request base", f"<pre>{html.escape(new)}</pre>",
                 None, True) + body
open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(f"""<!doctype html>
<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ZiSE25 open reproduction</title>
<style>
body{{font:15px/1.45 Arial,sans-serif;color:#171717;margin:0;background:#fff}}
header{{background:#2D4054;color:#fff;padding:20px 24px}} header h1{{margin:0 0 4px;font-size:22px}}
main{{max-width:980px;margin:0 auto;padding:8px 24px 40px}} section{{border-bottom:1px solid #ddd;padding:10px 0}}
h2{{font-size:17px}} pre{{background:#f4f5f7;padding:10px;overflow:auto;white-space:pre-wrap;font:12.5px Consolas,monospace}}
.si{{background:#F5A623;color:#171717;font-size:12px;padding:2px 6px;border-radius:3px;margin-left:6px}}
.same{{background:#e8f3ea;color:#171717;font-size:12px;padding:2px 6px;border-radius:3px;margin-left:6px}}
table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:3px 8px;text-align:left}}
a{{color:#2D4054;font-weight:bold}}
</style>
<header><h1>ZiSE25 open reproduction</h1>
<div>Commit {html.escape(sha[:12])}, built {when}{', <a style="color:#F5A623" href="' + run_url + '">workflow run</a>' if run_url else ''}</div></header>
<main>
<p>This page reproduces the outputs of <a href="https://github.com/BUGSENG/ZiSE25">BUGSENG/ZiSE25</a>'s CI with
open-source tools, because the original workflow artifacts and logs have expired and the ECLAIR steps need an
ECLAIR license and BUGSENG's runner. Items marked <span class=same>Same tool as upstream</span> use the tools the
upstream workflows used. Items marked <span class=si>Open-source stand-in, not ECLAIR</span> approximate ECLAIR
checks with free tools; they are not equivalent to ECLAIR and are not a compliance claim. Tool versions are in
<a href="versions.txt">versions.txt</a>.</p>
{body}
</main>""")
print("site written to", site)
