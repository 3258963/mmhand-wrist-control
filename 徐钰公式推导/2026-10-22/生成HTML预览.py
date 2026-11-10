# -*- coding: utf-8 -*-
"""把 Markdown 报告转成带学术样式的 HTML（MathJax 渲染公式）。

要点：先把 $$...$$ 与 $...$ 抽出来做占位符，避免 Markdown 解析下划线、星号时破坏公式。
"""
import re
import markdown

SRC = "腕部_动态R矩阵_完整报告.md"
CSS = "学术样式.css"
OUT = "腕部_动态R矩阵_完整报告.html"

md_text = open(SRC, encoding="utf-8").read()

maths = []


def stash(m):
    maths.append(m.group(0))
    return "@@MATH%d@@" % (len(maths) - 1)


# 先抽块级，再抽行内
text = re.sub(r"\$\$.+?\$\$", stash, md_text, flags=re.S)
text = re.sub(r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", stash, text, flags=re.S)

md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"])
body = md.convert(text)

body = re.sub(r"@@MATH(\d+)@@", lambda m: maths[int(m.group(1))], body)
body = re.sub(r"\n{3,}", "\n\n", body)

css = open(CSS, encoding="utf-8").read()

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>绳驱二轴腕部动态 R 矩阵解算</title>
<style>
{css}
</style>
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['$','$']], displayMath: [['$$','$$']], processEscapes: true }},
  svg: {{ fontCache: 'global' }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }}
}};
</script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
</head>
<body>
{body}
</body>
</html>
"""
open(OUT, "w", encoding="utf-8").write(html)
print("written", OUT, len(html), "math blocks:", len(maths))
