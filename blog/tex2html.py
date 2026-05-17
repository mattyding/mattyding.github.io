#!/usr/bin/env python3
"""
Convert a .tex post to HTML.

.tex posts use YAML front matter (like markdown posts), then raw LaTeX body:

    ---
    title: "Post Title"
    date: "YYYY-MM-DD"
    description: "Optional index description."
    ---

    \\section{Introduction}
    Content here. Math: $E = mc^2$.

Usage (from repo root):
    python3 blog/tex2html.py blog/posts/foo.tex blog/posts/foo.html
"""

import os
import re
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO_ROOT, "blog", "template.html")

YAML_FENCE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text):
    meta = {}
    match = YAML_FENCE.match(text)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip("\"'")
    return meta, match.end() if match else 0


def tex_to_html(src_path, out_path):
    content = open(src_path, encoding="utf-8").read()
    meta, body_start = parse_front_matter(content)
    body = content[body_start:]

    with tempfile.NamedTemporaryFile(
        suffix=".tex", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(body)
        tmp = f.name

    cmd = [
        "pandoc", tmp, "-o", out_path,
        "--from=latex",
        "--to=html5",
        f"--template={TEMPLATE}",
        "--mathjax",
        "--syntax-highlighting=monochrome",
    ]
    for key, val in meta.items():
        cmd.extend(["-M", f"{key}={val}"])

    try:
        subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    finally:
        os.unlink(tmp)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <src.tex> <out.html>", file=sys.stderr)
        sys.exit(1)
    tex_to_html(sys.argv[1], sys.argv[2])
