# -*- coding: utf-8 -*-
"""Build a MathJax HTML preview for the focused LaTeX-style note."""
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "飞书_动态R矩阵_原理与实现.md"
OUT = ROOT / "飞书_动态R矩阵_原理与实现.html"

text = SRC.read_text(encoding="utf-8-sig")

math_store = []


def stash(m):
    math_store.append(m.group(0))
    return f"@@MATH{len(math_store) - 1}@@"


pattern = re.compile(r"\$\$.*?\$\$|\$(?!\$).*?(?<!\\)\$", re.S)
protected = pattern.sub(stash, text)

md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                       extension_configs={"toc": {"toc_depth": "2-3"}})
body = md.convert(protected)

for i, s in enumerate(math_store):
    if s.startswith("$$"):
        body = body.replace(f"@@MATH{i}@@", f'<div class="math-display">{s}</div>')
    else:
        body = body.replace(f"@@MATH{i}@@", f'<span class="math-inline">{s}</span>')

body = re.sub(r"<p>\s*(<div class=\"math-display\">.*?</div>)\s*</p>", r"\1", body, flags=re.S)

toc = getattr(md, "toc", "")
toc = toc.replace('<div class="toc">', '<div class="toc-inner">', 1)
m = re.search(r"<h2\b", body)
if toc and m:
    body = (body[:m.start()]
            + f'<nav class="toc"><div class="toc-title">目录</div>{toc}</nav>\n'
            + body[m.start():])

CSS = """
:root { --ink:#1f2328; --muted:#57606a; --blue:#2F5597; --line:#d0d7de; --bg:#f6f8fa; }
* { box-sizing: border-box; }
body {
  margin: 0 auto; max-width: 980px; padding: 32px 40px 80px;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 15px; line-height: 1.8; color: var(--ink); background: #fff;
}
h1 { font-size: 30px; line-height: 1.35; margin: 8px 0 18px; color: #12355b; letter-spacing: .5px; }
h2 { font-size: 22px; margin: 38px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--line); color: #12355b; }
h3 { font-size: 17.5px; margin: 26px 0 8px; color: #1f3f66; }
p { margin: 9px 0; }
blockquote {
  margin: 14px 0; padding: 10px 16px; background: var(--bg);
  border-left: 4px solid var(--blue); color: #243b53; border-radius: 0 6px 6px 0;
}
blockquote p { margin: 5px 0; }
table { border-collapse: collapse; width: 100%; margin: 14px 0 18px; font-size: 13px; }
th, td { border: 1px solid var(--line); padding: 5px 8px; vertical-align: middle; }
th { background: #eef3f9; font-weight: 600; }
tr:nth-child(even) td { background: #fbfcfe; }
code { font-family: Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; font-size: 12.8px; background: #f2f4f7; padding: 1px 4px; border-radius: 4px; }
pre {
  background: #f7f9fc; border: 1px solid var(--line); border-left: 4px solid var(--blue);
  padding: 12px 14px; border-radius: 6px; overflow-x: auto; line-height: 1.7;
  font-size: 13.2px; margin: 10px 0 14px;
}
pre code { background: transparent; padding: 0; font-size: inherit; }
img { max-width: 100%; height: auto; display: block; margin: 16px auto 6px; border: 1px solid #e5e7eb; border-radius: 6px; }
em { color: var(--muted); }
hr { border: 0; border-top: 1px solid var(--line); margin: 28px 0; }
.toc { background: #fbfcfe; border: 1px solid var(--line); border-radius: 8px; padding: 14px 20px; margin: 18px 0 26px; }
.toc-title { font-weight: 700; color: #12355b; margin-bottom: 6px; }
.toc ul { margin: 4px 0; padding-left: 20px; }
.toc li { margin: 2px 0; }
.toc a { color: #245b9e; text-decoration: none; }
.math-inline { white-space: nowrap; }
.math-display { overflow-x: auto; overflow-y: hidden; margin: 10px 0; text-align: center; }
.print-btn {
  position: fixed; right: 22px; bottom: 22px; padding: 9px 14px; border: 0; border-radius: 8px;
  background: var(--blue); color: #fff; font-size: 14px; cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,.18);
}
@media print {
  body { max-width: none; padding: 0; font-size: 10.5pt; line-height: 1.7; }
  h1 { font-size: 22pt; } h2 { font-size: 15pt; page-break-after: avoid; } h3 { font-size: 12.5pt; page-break-after: avoid; }
  table { font-size: 8.6pt; } th, td { padding: 3px 4px; }
  pre { white-space: pre-wrap; }
  table, img, blockquote, pre { page-break-inside: avoid; }
  .print-btn { display: none; }
  a { color: inherit; text-decoration: none; }
  @page { size: A4; margin: 16mm 14mm 16mm 14mm; }
}
"""

HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>绳驱二轴腕部：为什么要做动态 R，以及怎么做</title>
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['$','$']], displayMath: [['$$','$$']], processEscapes: true }},
  svg: {{ fontCache: 'global' }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }}
}};
</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>{CSS}</style>
</head>
<body>
{body}
<button class="print-btn" onclick="window.print()">打印 / 导出 PDF</button>
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8")
print("wrote", OUT, len(HTML))
