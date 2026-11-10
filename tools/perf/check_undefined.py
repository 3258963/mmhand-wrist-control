"""AST 静态检查（v2）：抓「名字用了但没定义」和「私有 self 属性读了但从没写过」。

v1 误报太多（闭包外层变量、Qt 继承方法），v2：
  - 按作用域递归分析：内层函数能看到外层函数的绑定；
  - 函数内 import / def / class / 推导式 / with / except 都算绑定；
  - self 属性只看下划线开头的私有名（Qt 方法不会以下划线开头）；
  - 类里定义过的方法名、类属性名都算已定义。

用法： .venv\\Scripts\\python.exe tools\\perf\\check_undefined.py [文件...]
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}


def _bind_target(node, bound: set[str]) -> None:
    if isinstance(node, ast.Name):
        bound.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            _bind_target(e, bound)
    elif isinstance(node, ast.Starred):
        _bind_target(node.value, bound)


def local_bindings(node) -> set[str]:
    """函数体里直接绑定的名字（不含更内层函数体）。"""
    bound: set[str] = set()
    for stmt in node.body:
        for n in ast.walk(stmt):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                bound.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    bound.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ExceptHandler) and n.name:
                bound.add(n.name)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                bound.update(n.names)
    return bound


def arg_names(args) -> set[str]:
    out = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
    if args.vararg:
        out.add(args.vararg.arg)
    if args.kwarg:
        out.add(args.kwarg.arg)
    return out


def loads_in(node) -> dict[str, int]:
    """node 内部读取的 Name（不下潜进嵌套函数/lambda/类：它们有自己的作用域）。"""
    out: dict[str, int] = {}
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) \
                and n is not node:
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out[n.id] = out.get(n.id, 0) + 1
        stack.extend(ast.iter_child_nodes(n))
    return out

class Checker:
    def __init__(self, path: Path, module_names: set[str], class_attrs: set[str],
                 class_methods: set[str], self_writes: set[str]):
        self.path = path
        self.module_names = module_names
        self.class_attrs = class_attrs
        self.class_methods = class_methods
        self.self_writes = self_writes
        self.problems: list[str] = []

    def visit_function(self, fn, enclosing: set[str], label: str = "") -> None:
        args = arg_names(fn.args)
        inner = local_bindings(fn)
        bound = enclosing | args | inner
        # 默认参数在**外层**求值，按外层作用域查
        for d in list(fn.args.defaults) + [d for d in fn.args.kw_defaults if d]:
            self._check_names_in(d, enclosing, f"{label}{fn.name}() 默认参数")
        # 注释里不要看 Return 等
        body_loads: dict[str, int] = {}
        for stmt in fn.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for k, v in loads_in(stmt).items():
                body_loads[k] = body_loads.get(k, 0) + v
        free = set(body_loads) - bound - self.module_names - BUILTINS
        qn = f"{label}{fn.name}()"
        for name in sorted(free):
            self.problems.append(
                f"{self.path.name}:{fn.lineno} {qn} 读取了从未定义的名字 '{name}'"
                f"（运行到即 NameError）")
        # self.X 私有属性读
        read_attrs = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) \
                    and isinstance(n.value, ast.Name) and n.value.id == "self" \
                    and n.attr.startswith("_"):
                read_attrs.add(n.attr)
        for attr in sorted(read_attrs - self.self_writes - self.class_attrs - self.class_methods):
            self.problems.append(
                f"{self.path.name}:{fn.lineno} {qn} 读取 self.{attr}，"
                f"但全文件没有 self.{attr} = ... 赋值（可能拼错/漏初始化）")
        # 递归进内层函数（带上本层绑定）
        for n in ast.walk(fn):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn:
                self.visit_function(n, bound, label=f"{label}{fn.name}>")
            elif isinstance(n, ast.Lambda):
                seen = {a.arg for a in list(n.args.posonlyargs) + list(n.args.args)
                        + list(n.args.kwonlyargs)}
                loads = loads_in(n.body)
                for name in sorted(set(loads) - seen - bound - self.module_names - BUILTINS):
                    self.problems.append(
                        f"{self.path.name}:{n.lineno} {qn} 的 lambda 读取未定义名字 '{name}'")

    def _check_names_in(self, node, bound: set[str], where: str) -> None:
        for name in sorted(set(loads_in(node)) - bound - self.module_names - BUILTINS):
            self.problems.append(
                f"{self.path.name}:{getattr(node, 'lineno', '?')} {where} 读取未定义名字 '{name}'")


def check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(src, filename=str(path))

    module_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                module_names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    module_names.add(n.id)

    class_attrs: set[str] = set()
    class_methods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_methods.add(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_methods.add(sub.name)
                else:
                    for n in ast.walk(sub):
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                            class_attrs.add(n.id)

    self_writes: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) \
                and isinstance(n.value, ast.Name) and n.value.id == "self":
            self_writes.add(n.attr)

    checker = Checker(path, module_names, class_attrs, class_methods, self_writes)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            checker.visit_function(node, module_names)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    checker.visit_function(sub, module_names, label=f"{node.name}.")
    return checker.problems


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]] or [
        Path("code/mmhand-main/mmhand_scope.py")]
    total = 0
    for p in targets:
        if not p.exists():
            print(f"跳过（不存在）：{p}")
            continue
        probs = check_file(p)
        total += len(probs)
        print(f"\n=== {p} ===")
        for line in probs:
            print("  " + line)
        if not probs:
            print("  未发现未定义名/未赋值私有属性")
    print(f"\n合计 {total} 处")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))


