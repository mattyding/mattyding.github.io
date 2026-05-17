#!/usr/bin/env python3
"""Generate blog/index.html from post metadata.

Run via `make blog` or directly: python3 blog/build.py

Both .tex and .md posts use YAML front matter at the top:
    ---
    title: "Post Title"
    date: "YYYY-MM-DD"
    description: "Optional one-liner."
    ---
"""

import html
import os
import re

POSTS_DIR = os.path.join(os.path.dirname(__file__), "posts")
OUTPUT = os.path.join(os.path.dirname(__file__), "index.html")


def parse_front_matter(filepath):
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    meta = {}
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip("\"'")
    return meta


posts = []
for fname in sorted(os.listdir(POSTS_DIR)):
    if fname.endswith(".tex"):
        slug = fname[:-4]
    elif fname.endswith(".md"):
        slug = fname[:-3]
    else:
        continue
    meta = parse_front_matter(os.path.join(POSTS_DIR, fname))
    posts.append(
        {
            "slug": slug,
            "title": meta.get("title", slug),
            "date": meta.get("date", ""),
            "description": meta.get("description", ""),
        }
    )

posts.sort(key=lambda p: p["date"], reverse=True)

if posts:
    content = """  <table>
    <thead>
      <tr>
        <th>Post</th>
      </tr>
    </thead>
    <tbody>
""" + "\n".join(
        f'      <tr>'
        f'<td><a href="/blog/posts/{p["slug"]}.html">{html.escape(p["title"])}</a>'
        + (f'<br><span class="post-index-desc">{html.escape(p["description"])}</span>' if p["description"] else "")
        + f"</td></tr>"
        for p in posts
    ) + """
    </tbody>
  </table>"""
else:
    content = """  <div class="empty-blog">
    <p>this space intentionally left blank.</p>
  </div>"""

page = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes" />
  <title>blog | matthew ding</title>
  <link rel="stylesheet" href="/styles/reset.css" />
  <link rel="stylesheet" href="/styles/style.css" />
  <link rel="stylesheet" href="/styles/blog.css" />
  <link rel="icon" href="/assets/favicon.ico" type="image/x-icon">
</head>
<body>
  <nav class="post-nav">
    <a href="/">← home</a>
  </nav>
  <h1>Blog</h1>
{content}
</body>
</html>"""

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(page + "\n")

print(f"Generated {OUTPUT} with {len(posts)} post(s).")
