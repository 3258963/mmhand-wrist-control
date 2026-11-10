"""列出 add-on 备份与当前文件的真实差异块（difflib，带上下文）。"""
import difflib

a = open(r'code\mmhand-main\mmhand_scope.py.bak-perf-20261103-174450', encoding='utf-8').read().splitlines()
b = open(r'code\mmhand-main\mmhand_scope.py', encoding='utf-8').read().splitlines()
print(f'备份 {len(a)} 行 / 当前 {len(b)} 行')
for line in difflib.unified_diff(a, b, 'bak', 'cur', n=2, lineterm=''):
    print(line)
