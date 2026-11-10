"""Extract the inline JS from the visualization fragment and write it to _check.js (via Write-safe route: print to stdout)."""
import re, sys
src = open(r"E:\ZCODE_DOCUMENT\.zcode\v2\visualizations\805793b12beeba9e08d355a5230551fa69c7b9f78f25d8e92f1798ee903a37cd\wrist-model-review.html", encoding="utf-8").read()
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
sys.stdout.write(scripts[-1])
