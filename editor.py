#!/usr/bin/env python3
"""
Local LaTeX writing tool for mattyding.github.io.

Usage:
    python3 editor.py          # opens at http://localhost:5757
    python3 editor.py --port 8080
    make editor

Requires:  pip3 install flask
           claude CLI (Claude Code) must be in PATH for the agent feature.
"""

import argparse
import html
import json
import os
import re
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory, stream_with_context

BLOG_DIR = Path(__file__).parent.resolve()
POSTS_DIR = BLOG_DIR / "blog" / "posts"
TEMPLATE = BLOG_DIR / "blog" / "template.html"

app = Flask(__name__)

agent_history: dict[str, list] = {}

def _build_agent_prompt(filename: str, file_content: str, history: list, user_msg: str) -> str:
    file_desc = f"Currently editing: {filename}" if filename else "No file saved yet (new post)."
    system = f"""You are a writing assistant for Matthew Ding's personal blog at mattyding.github.io.

Blog style: minimalist, monospace (JetBrains Mono), black-and-white. Understated and precise.

Post format — YAML front matter then pure LaTeX body (no \\documentclass or \\begin{{document}} needed):

    ---
    title: "Post Title"
    date: "YYYY-MM-DD"
    description: "One-liner for the blog index."
    ---

    \\section{{Introduction}}
    Content. Inline math: $E = mc^2$. Display: \\[F = ma\\].
    \\begin{{itemize}}
      \\item bullet
    \\end{{itemize}}

Available: \\section, \\subsection, itemize/enumerate, \\textbf, \\textit, \\emph, \\footnote, \\href{{url}}{{text}}.
Math: $...$ inline, \\[...\\] display, align/equation environments.

{file_desc}

Current file content:
```
{file_content}
```

When making edits, output the COMPLETE updated file wrapped in:
<write_file summary="one-line description of change">
[complete .tex content]
</write_file>

Put any explanation before or after the block, never inside it. Only emit the block when you have actual changes."""

    parts = [system]
    if history:
        parts.append("\n\nConversation so far:")
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"\n{role}: {msg['text']}")
    parts.append(f"\n\nUser: {user_msg}")
    return "".join(parts)


def _parse_agent_output(output: str):
    """Split output into (display_text, (file_content, summary) or None)."""
    m = re.search(
        r'<write_file\s+summary="([^"]*)">\n?(.*?)\n?</write_file>',
        output, re.DOTALL
    )
    if not m:
        return output.strip(), None
    summary = m.group(1)
    content = m.group(2)
    display = (output[:m.start()] + output[m.end():]).strip()
    return display, (content, summary)


_PREVIEW_LOCAL_BLOCK = """<script>
(function () {
  document.querySelectorAll('a:not([target="_blank"])').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); });
    a.style.cursor = 'not-allowed';
    a.title = 'navigation disabled in preview';
  });
})();
</script>"""


def _inject_preview_link_handler(html_str: str) -> str:
    # target="_blank" server-side: more reliable than JS inside a sandboxed iframe
    html_str = re.sub(
        r'(<a\s[^>]*href="https?://[^"]*")',
        r'\1 target="_blank" rel="noopener noreferrer"',
        html_str,
    )
    return html_str.replace("</body>", _PREVIEW_LOCAL_BLOCK + "\n</body>", 1)

_YAML_FENCE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_front_matter(content: str):
    meta = {}
    match = _YAML_FENCE.match(content)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip("\"'")
        return meta, content[match.end():]
    return meta, content


def _pandoc_to_html(content: str) -> str:
    meta, body = _parse_front_matter(content)
    with tempfile.NamedTemporaryFile(suffix=".tex", mode="w", encoding="utf-8", delete=False) as f:
        f.write(body)
        tmp_path = f.name
    try:
        cmd = [
            "pandoc", tmp_path, "-o", "-",
            "--from=latex", "--to=html5",
            f"--template={TEMPLATE}",
            "--mathjax",
            "--syntax-highlighting=monochrome",
        ]
        for key, val in meta.items():
            cmd.extend(["-M", f"{key}={val}"])
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BLOG_DIR)
        if result.returncode == 0:
            return _inject_preview_link_handler(result.stdout)
        err = html.escape(result.stderr or result.stdout)
        return f"""<!DOCTYPE html><html><head>
  <style>
    body {{ font-family: "JetBrains Mono", monospace; font-size: 13px; padding: 20px; background: #fff; }}
    .err {{ border: 2px solid #c00; background: #fff5f5; padding: 16px; }}
    .err-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #c00; margin-bottom: 10px; }}
    pre {{ white-space: pre-wrap; font-size: 0.85em; color: #900; margin: 0; }}
  </style>
</head><body>
  <div class="err">
    <div class="err-label">Compilation Error</div>
    <pre>{err}</pre>
  </div>
</body></html>"""
    finally:
        os.unlink(tmp_path)


EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Writer — mattyding.github.io</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      display: flex; flex-direction: column; height: 100vh;
      font-family: "JetBrains Mono", monospace; font-size: 13px; background: #fff;
    }

    /* ── Toolbar ── */
    #toolbar {
      display: flex; align-items: center; gap: 8px;
      padding: 5px 12px; background: #f5f5f5;
      border-bottom: 2px solid #000; flex-shrink: 0; min-height: 36px;
      position: relative;
    }
    #toolbar select {
      font-family: inherit; font-size: 12px;
      padding: 2px 6px; border: 1px solid #999; max-width: 220px;
    }
    #toolbar button {
      font-family: inherit; font-size: 11px;
      padding: 2px 10px; border: 1px solid #000;
      background: #fff; cursor: pointer;
      text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap;
    }
    #toolbar button:hover { background: #000; color: #fff; }
    #status { margin-left: auto; color: #888; font-size: 11px; white-space: nowrap; }

    /* ── File dropdown menu ── */
    #file-menu-wrap { position: relative; }
    #file-menu-btn { font-family: inherit; font-size: 11px; padding: 2px 10px;
      border: 1px solid #000; background: #fff; cursor: pointer;
      text-transform: uppercase; letter-spacing: 0.05em; }
    #file-menu-btn:hover, #file-menu-btn.open { background: #000; color: #fff; }
    #file-menu-items {
      display: none; position: absolute; top: 100%; left: 0; z-index: 100;
      background: #fff; border: 1px solid #000; min-width: 140px; margin-top: 2px;
    }
    #file-menu-items.open { display: block; }
    #file-menu-items button {
      display: block; width: 100%; text-align: left;
      font-family: inherit; font-size: 11px; padding: 5px 12px;
      border: none; border-bottom: 1px solid #eee; background: #fff;
      cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em;
    }
    #file-menu-items button:last-child { border-bottom: none; }
    #file-menu-items button:hover { background: #000; color: #fff; }

    /* ── Insert dropdown (reuses same pattern) ── */
    #insert-menu-wrap { position: relative; }
    #insert-menu-btn { font-family: inherit; font-size: 11px; padding: 2px 10px;
      border: 1px solid #000; background: #fff; cursor: pointer;
      text-transform: uppercase; letter-spacing: 0.05em; }
    #insert-menu-btn:hover, #insert-menu-btn.open { background: #000; color: #fff; }
    #insert-menu-items {
      display: none; position: absolute; top: 100%; left: 0; z-index: 100;
      background: #fff; border: 1px solid #000; min-width: 160px; margin-top: 2px;
    }
    #insert-menu-items.open { display: block; }
    #insert-menu-items button {
      display: block; width: 100%; text-align: left;
      font-family: inherit; font-size: 11px; padding: 5px 12px;
      border: none; border-bottom: 1px solid #eee; background: #fff;
      cursor: pointer; letter-spacing: 0.03em;
    }
    #insert-menu-items button:last-child { border-bottom: none; }
    #insert-menu-items button:hover { background: #000; color: #fff; }

    /* ── Main split ── */
    #main { display: flex; flex: 1; overflow: hidden; }

    /* ── Left pane ── */
    #left-pane { width: 50%; display: flex; flex-direction: column; border-right: 2px solid #000; }

    #tab-bar {
      display: flex; flex-shrink: 0;
      border-bottom: 1px solid #ccc; background: #f0f0f0;
    }
    .tab-btn {
      font-family: inherit; font-size: 11px;
      padding: 5px 16px; border: none; border-right: 1px solid #ccc;
      background: #f0f0f0; cursor: pointer;
      text-transform: uppercase; letter-spacing: 0.08em; color: #666;
    }
    .tab-btn:hover { background: #e0e0e0; color: #000; }
    .tab-btn.active { background: #fff; color: #000; border-bottom: 2px solid #fff; margin-bottom: -1px; }

    #editor-tab { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    #editor { flex: 1; }

    /* ── Agent tab ── */
    #agent-tab { flex: 1; display: none; flex-direction: column; overflow: hidden; }

    #agent-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 5px 10px; background: #f8f8f8; border-bottom: 1px solid #e0e0e0;
      flex-shrink: 0;
    }
    #agent-file-label { font-size: 11px; color: #666; }
    #agent-header button {
      font-family: inherit; font-size: 10px; text-transform: uppercase;
      letter-spacing: 0.05em; padding: 2px 8px;
      border: 1px solid #ccc; background: #fff; cursor: pointer; color: #666;
    }
    #agent-header button:hover { border-color: #000; color: #000; }

    #chat-messages {
      flex: 1; overflow-y: auto; padding: 12px 14px;
      display: flex; flex-direction: column; gap: 14px;
    }
    .msg-row { display: flex; flex-direction: column; gap: 2px; }
    .msg-label {
      font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #999;
    }
    .msg-row.user .msg-label { color: #000; }
    .msg-text { font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
    .msg-row.user .msg-text { font-weight: 600; }
    .file-pill {
      display: inline-block; margin-top: 4px;
      font-size: 10px; color: #006600; border: 1px solid #006600;
      padding: 1px 6px; letter-spacing: 0.05em;
    }
    .error-text { color: #c00; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }
    .thinking { animation: blink 1.1s infinite; }

    #chat-input-area {
      flex-shrink: 0; border-top: 1px solid #ccc; padding: 8px 10px;
      display: flex; flex-direction: column; gap: 5px;
    }
    #chat-input {
      width: 100%; font-family: inherit; font-size: 13px;
      padding: 6px 8px; border: 1px solid #ccc; resize: none;
      line-height: 1.4;
    }
    #chat-input:focus { outline: none; border-color: #000; }
    #chat-footer {
      display: flex; align-items: center; justify-content: space-between;
    }
    #chat-hint { font-size: 10px; color: #aaa; }
    #send-btn {
      font-family: inherit; font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.05em; padding: 3px 14px;
      border: 1px solid #000; background: #000; color: #fff; cursor: pointer;
    }
    #send-btn:disabled { opacity: 0.4; cursor: default; }
    #send-btn:not(:disabled):hover { background: #333; }

    /* ── Right pane (preview) ── */
    #right-pane { width: 50%; display: flex; flex-direction: column; }
    #preview-header {
      display: flex; align-items: center; gap: 8px;
      padding: 3px 10px; background: #f5f5f5;
      border-bottom: 1px solid #e0e0e0; flex-shrink: 0;
    }
    #preview-title {
      font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #aaa;
    }
    #build-btn {
      font-family: inherit; font-size: 10px; padding: 1px 8px;
      border: 1px solid #999; background: #fff; cursor: pointer;
      text-transform: uppercase; letter-spacing: 0.05em; color: #555;
    }
    #build-btn:hover { background: #000; color: #fff; border-color: #000; }
    #preview-hint { font-size: 10px; color: #bbb; }
    #preview-frame { flex: 1; border: none; width: 100%; }
  </style>
</head>
<body>

<div id="toolbar">
  <select id="file-select" title="Open post">
    <option value="">— new post —</option>
  </select>
  <div id="file-menu-wrap">
    <button id="file-menu-btn" onclick="toggleFileMenu()">File ▾</button>
    <div id="file-menu-items">
      <button onclick="newPost(); closeFileMenu()">New Post</button>
      <button onclick="savePost(); closeFileMenu()">Save  ⌘S</button>
    </div>
  </div>
  <div id="insert-menu-wrap">
    <button id="insert-menu-btn" onclick="toggleInsertMenu()">Insert ▾</button>
    <div id="insert-menu-items">
      <button onclick="insertSnippet('\\href{https://}{text}', -7)">Link  \href{}{}</button>
    </div>
  </div>
  <span id="status">Loading editor…</span>
</div>

<div id="main">
  <div id="left-pane">
    <div id="tab-bar">
      <button class="tab-btn active" onclick="switchTab('editor', event)">Edit</button>
      <button class="tab-btn" onclick="switchTab('agent', event)">Agent</button>
    </div>

    <div id="editor-tab">
      <div id="editor"></div>
    </div>

    <div id="agent-tab">
      <div id="agent-header">
        <span id="agent-file-label">No file open</span>
        <button onclick="clearAgent()">Clear session</button>
      </div>
      <div id="chat-messages"></div>
      <div id="chat-input-area">
        <textarea id="chat-input" rows="3" placeholder="Ask Claude to help edit your post…  (Enter to send, Shift+Enter for newline)"></textarea>
        <div id="chat-footer">
          <span id="chat-hint">Enter ↵ send · Shift+Enter newline</span>
          <button id="send-btn" onclick="sendMessage()">Send</button>
        </div>
      </div>
    </div>
  </div>

  <div id="right-pane">
    <div id="preview-header">
      <span id="preview-title">Preview</span>
      <button id="build-btn" onclick="updatePreview()">Build</button>
      <span id="preview-hint">(⌘↵)</span>
    </div>
    <iframe id="preview-frame" sandbox="allow-scripts allow-same-origin allow-popups"></iframe>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs/loader.js"></script>
<script>
let editor = null;
let currentFile = null;
let agentStreaming = false;
let isDirty = false;

function makeNewTemplate() {
  return [
    '---',
    'title: "New Post"',
    'date: "' + new Date().toISOString().slice(0, 10) + '"',
    'description: ""',
    '---',
    '',
    '% fill in here',
    '',
  ].join('\n');
}

require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' } });
require(['vs/editor/editor.main'], function () {
  editor = monaco.editor.create(document.getElementById('editor'), {
    value: makeNewTemplate(),
    language: 'latex',
    theme: 'vs',
    fontSize: 14,
    wordWrap: 'on',
    minimap: { enabled: false },
    lineNumbers: 'on',
    automaticLayout: true,
    scrollBeyondLastLine: false,
    fontFamily: '"JetBrains Mono", "Courier New", monospace',
  });

  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, savePost);
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, updatePreview);

  editor.onDidChangeModelContent(() => {
    isDirty = true;
    setStatus('Modified •');
  });

  loadFileList(null);
  updatePreview();
  setStatus('Ready');
});

function confirmDiscard() {
  if (!isDirty) return true;
  return confirm('You have unsaved changes. Discard them?');
}

window.addEventListener('beforeunload', (e) => {
  if (isDirty) { e.preventDefault(); e.returnValue = ''; }
});

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

function setAgentFileLabel() {
  document.getElementById('agent-file-label').textContent =
    currentFile ? 'Context: ' + currentFile : 'Context: (unsaved post)';
}

function toggleFileMenu() {
  const items = document.getElementById('file-menu-items');
  const btn = document.getElementById('file-menu-btn');
  const open = items.classList.toggle('open');
  btn.classList.toggle('open', open);
}

function closeFileMenu() {
  document.getElementById('file-menu-items').classList.remove('open');
  document.getElementById('file-menu-btn').classList.remove('open');
}

function toggleInsertMenu() {
  const items = document.getElementById('insert-menu-items');
  const btn = document.getElementById('insert-menu-btn');
  const open = items.classList.toggle('open');
  btn.classList.toggle('open', open);
}

function closeInsertMenu() {
  document.getElementById('insert-menu-items').classList.remove('open');
  document.getElementById('insert-menu-btn').classList.remove('open');
}

function insertSnippet(text, cursorOffset) {
  if (!editor) return;
  const sel = editor.getSelection();
  editor.executeEdits('insert', [{ range: sel, text, forceMoveMarkers: true }]);
  if (cursorOffset < 0) {
    const pos = editor.getPosition();
    editor.setPosition({ lineNumber: pos.lineNumber, column: Math.max(1, pos.column + cursorOffset) });
  }
  editor.focus();
}

document.addEventListener('click', function (e) {
  if (!document.getElementById('file-menu-wrap').contains(e.target)) closeFileMenu();
  if (!document.getElementById('insert-menu-wrap').contains(e.target)) closeInsertMenu();
});

function switchTab(name, e) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('editor-tab').style.display = name === 'editor' ? 'flex' : 'none';
  document.getElementById('agent-tab').style.display  = name === 'agent'  ? 'flex' : 'none';
  e.currentTarget.classList.add('active');
  if (name === 'agent') {
    setAgentFileLabel();
    document.getElementById('chat-input').focus();
  } else if (editor) {
    editor.focus();
    editor.layout();
  }
}

async function loadFileList(selectName) {
  const res = await fetch('/api/list');
  const files = await res.json();
  const sel = document.getElementById('file-select');
  sel.innerHTML = '<option value="">— new post —</option>';
  files.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f;
    sel.appendChild(opt);
  });
  if (selectName) sel.value = selectName;
}

document.getElementById('file-select').addEventListener('change', function () {
  if (this.value) openFile(this.value);
  else newPost();
});

async function openFile(name) {
  if (!confirmDiscard()) { document.getElementById('file-select').value = currentFile || ''; return; }
  const res = await fetch('/api/open?name=' + encodeURIComponent(name));
  if (!res.ok) { setStatus('Error opening ' + name); return; }
  const data = await res.json();
  if (editor) editor.setValue(data.content);
  currentFile = name;
  isDirty = false;
  setAgentFileLabel();
  updatePreview();
  setStatus('Opened: ' + name);
}

function newPost() {
  if (!confirmDiscard()) { document.getElementById('file-select').value = currentFile || ''; return; }
  if (editor) editor.setValue(makeNewTemplate());
  currentFile = null;
  isDirty = false;
  document.getElementById('file-select').value = '';
  setAgentFileLabel();
  updatePreview();
  setStatus('New post');
}

function savePost() {
  if (currentFile) {
    doSave(currentFile);
  } else {
    let name = prompt('Save as:', 'my-post.tex');
    if (name === null) return;           // cancelled
    name = name.trim();
    if (!name) return;
    if (!name.endsWith('.tex')) name += '.tex';
    const exists = Array.from(document.getElementById('file-select').options)
      .some(opt => opt.value === name);
    if (exists && !confirm(name + ' already exists. Overwrite?')) return;
    doSave(name);
  }
}

async function doSave(name) {
  setStatus('Saving…');
  const res = await fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content: editor ? editor.getValue() : '' }),
  });
  const data = await res.json();
  if (data.ok) {
    currentFile = name;
    isDirty = false;
    setAgentFileLabel();
    await loadFileList(name);
    updatePreview();
    setStatus('Saved: ' + name);
  } else {
    setStatus('Save error: ' + data.error);
  }
}

async function updatePreview() {
  if (!editor) return;
  const content = editor.getValue();
  const res = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  document.getElementById('preview-frame').srcdoc = data.html;
  if (currentFile) {
    const m = content.match(/^---[\s\S]*?\ntitle:\s*"?([^"\n]+)"?/m);
    if (m) {
      const title = m[1].trim();
      const label = title.length > 34 ? title.slice(0, 32) + '…' : title;
      const opt = Array.from(document.getElementById('file-select').options)
        .find(o => o.value === currentFile);
      if (opt) opt.textContent = label;
    }
  }
}

function appendMsg(role, text) {
  const container = document.getElementById('chat-messages');
  const row = document.createElement('div');
  row.className = 'msg-row ' + role;
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'You' : 'Claude';
  const body = document.createElement('div');
  body.className = 'msg-text';
  body.textContent = text;
  row.appendChild(label);
  row.appendChild(body);
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return body;
}

function appendFilePill(summary, parentRow) {
  const pill = document.createElement('div');
  pill.className = 'file-pill';
  pill.textContent = '✓ ' + summary;
  parentRow.parentElement.appendChild(pill);
  const msgs = document.getElementById('chat-messages');
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendMessage() {
  if (agentStreaming) return;
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  appendMsg('user', msg);
  const claudeBody = appendMsg('claude', '…');
  claudeBody.classList.add('thinking');

  agentStreaming = true;
  document.getElementById('send-btn').disabled = true;

  try {
    const res = await fetch('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        filename: currentFile || '',
        content: editor ? editor.getValue() : '',
      }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

        if (evt.type === 'text') {
          claudeBody.classList.remove('thinking');
          claudeBody.textContent = evt.text || '(no response)';
          const chatEl = document.getElementById('chat-messages');
          chatEl.scrollTop = chatEl.scrollHeight;

        } else if (evt.type === 'file_updated') {
          if (editor) {
            editor.setValue(evt.content);
            isDirty = false;
            updatePreview();
          }
          appendFilePill(evt.summary || 'File updated', claudeBody);

        } else if (evt.type === 'error') {
          claudeBody.classList.remove('thinking');
          claudeBody.textContent = '⚠ ' + evt.text;
          claudeBody.classList.add('error-text');
        }
      }
    }
  } catch (err) {
    claudeBody.classList.remove('thinking');
    claudeBody.textContent = '⚠ Network error: ' + err.message;
    claudeBody.classList.add('error-text');
  }

  agentStreaming = false;
  document.getElementById('send-btn').disabled = false;
  input.focus();
}

async function clearAgent() {
  await fetch('/api/agent/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: currentFile || '' }),
  });
  document.getElementById('chat-messages').innerHTML = '';
}

document.getElementById('chat-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(EDITOR_HTML)


@app.route("/styles/<path:filename>")
def serve_styles(filename):
    return send_from_directory(BLOG_DIR / "styles", filename)


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(BLOG_DIR / "assets", filename)


@app.route("/blog/<path:filename>")
def serve_blog(filename):
    return send_from_directory(BLOG_DIR / "blog", filename)


@app.route("/api/list")
def api_list():
    if not POSTS_DIR.exists():
        return jsonify([])
    files = sorted(f.name for f in POSTS_DIR.iterdir() if f.suffix == ".tex")
    return jsonify(files)


@app.route("/api/open")
def api_open():
    name = request.args.get("name", "").strip()
    path = POSTS_DIR / name
    if not path.exists() or path.suffix != ".tex":
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": path.read_text(encoding="utf-8")})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    content = data.get("content", "")
    if not name or not name.endswith(".tex"):
        return jsonify({"ok": False, "error": "Filename must end with .tex"})
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    (POSTS_DIR / name).write_text(content, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/preview", methods=["POST"])
def api_preview():
    content = request.get_json(force=True).get("content", "")
    return jsonify({"html": _pandoc_to_html(content)})


@app.route("/api/build", methods=["POST"])
def api_build():
    result = subprocess.run(["make", "blog"], capture_output=True, text=True, cwd=BLOG_DIR)
    if result.returncode == 0:
        posts = len(list(POSTS_DIR.glob("*.tex"))) if POSTS_DIR.exists() else 0
        return jsonify({"ok": True, "posts": posts})
    return jsonify({"ok": False, "error": result.stderr or result.stdout})


@app.route("/api/agent/chat", methods=["POST"])
def api_agent_chat():
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    filename = data.get("filename", "")
    file_content = data.get("content", "")

    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    key = filename or "__new__"

    def generate():
        history = agent_history.get(key, [])
        prompt = _build_agent_prompt(filename, file_content, history, user_msg)

        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True, timeout=120, cwd=BLOG_DIR,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except FileNotFoundError:
            yield f"data: {json.dumps({'type': 'error', 'text': 'claude command not found — is Claude Code installed and in PATH?'})}\n\n"
            return
        except subprocess.TimeoutExpired:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Timed out after 120 seconds'})}\n\n"
            return

        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip() or "claude exited with an error"
            yield f"data: {json.dumps({'type': 'error', 'text': err})}\n\n"
            return

        display_text, file_update = _parse_agent_output(result.stdout)

        yield f"data: {json.dumps({'type': 'text', 'text': display_text})}\n\n"

        if file_update:
            new_content, summary = file_update
            if filename:
                try:
                    (POSTS_DIR / filename).write_text(new_content, encoding="utf-8")
                except Exception as e:
                    summary = f"Save error: {e}"
            yield f"data: {json.dumps({'type': 'file_updated', 'content': new_content, 'summary': summary})}\n\n"

        agent_history[key] = history + [
            {"role": "user", "text": user_msg},
            {"role": "assistant", "text": display_text},
        ]
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.route("/api/agent/clear", methods=["POST"])
def api_agent_clear():
    data = request.get_json(force=True)
    key = data.get("filename", "") or "__new__"
    agent_history.pop(key, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LaTeX blog writer")
    parser.add_argument("--port", type=int, default=5757)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}"
    print(f"\n  Writer → {url}")
    print(f"  Ctrl+C to quit\n")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(port=args.port, debug=False, use_reloader=False)
