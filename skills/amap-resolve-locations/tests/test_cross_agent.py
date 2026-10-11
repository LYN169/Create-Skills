#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_cross_agent.py — 多 Agent 安装适配层测试（无网络、无 Key）

运行：cd <skill根目录> && python tests/test_cross_agent.py
覆盖：
  1. SKILL.md frontmatter 兼容 Claude Code 与 Codex（name/description 齐全）
  2. cross-agent.md 自足（含 resolver/output_writer 命令、五字段、消歧纪律、安全）
  3. install.py 白名单：不含凭据/缓存类文件；复制到临时目录后凭据文件零拷贝
  4. 安装器对 claude/codex/--path 三种目标解析正确
  5. 核心脚本清单不因适配层改变（既定流程文件一个不少）
"""
import json
import os
import re
import shutil
import sys
import tempfile

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_ROOT)
import install as installer  # noqa: E402

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def read(rel):
    with open(os.path.join(SKILL_ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ---- 1. SKILL.md frontmatter 兼容 ----
skill = read("SKILL.md")
m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check("SKILL.md 有 frontmatter", m is not None)
fm = m.group(1) if m else ""
check("frontmatter 含 name", re.search(r"^name:\s*\S+", fm, re.M) is not None)
check("frontmatter 含 description", re.search(r"^description:\s*\S+", fm, re.M) is not None)

# ---- 2. cross-agent.md 自足性 ----
ca = read("cross-agent.md")
for kw in ("resolver.py", "output_writer.py", "manual.json", "records.json",
           "longitude_gcj02", "latitude_gcj02", "longitude_wgs84",
           "latitude_wgs84", "conversion_status", "不填 0,0",
           "不能推断经纬度", "AMAP_KEY"):
    check(f"cross-agent.md 含关键内容 {kw}", kw in ca)

# ---- 3. install.py 白名单与凭据排除 ----
wl = installer.WHITELIST
check("白名单不含凭据/缓存文件",
      all(b not in wl for b in ("amap_key.txt", ".env", "__pycache__",
                                "scripts/amap_key.txt"))
      and "scripts/amap_key.txt.example" in wl)
check("白名单含核心脚本与规则文档",
      all(r in wl for r in ("SKILL.md", "scripts/amap_api.py",
                            "scripts/resolver.py", "scripts/output_writer.py",
                            "scripts/coordinate_transform.py", "cross-agent.md",
                            "INSTALL.md", "SECURITY.md")))
tmp = tempfile.mkdtemp(prefix="amap_inst_")
try:
    # 在临时源目录种一个假凭据文件，验证安装器绝不复制
    fake_src = os.path.join(tmp, "src")
    os.makedirs(fake_src)
    for rel in wl:
        p = os.path.join(fake_src, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")
    with open(os.path.join(fake_src, "scripts", "amap_key.txt"), "w", encoding="utf-8") as f:
        f.write("FAKE_KEY_SHOULD_NOT_COPY")
    with open(os.path.join(fake_src, ".env"), "w", encoding="utf-8") as f:
        f.write("FAKE_ENV")
    os.makedirs(os.path.join(fake_src, "__pycache__"))
    dst = os.path.join(tmp, "dst")
    n = installer.copy_skill(fake_src, dst)
    check("白名单复制数量一致", n == len(wl), f"{n}/{len(wl)}")
    check("假凭据文件未被复制", not os.path.exists(os.path.join(dst, "scripts", "amap_key.txt")))
    check(".env 未被复制", not os.path.exists(os.path.join(dst, ".env")))
    check("__pycache__ 未被复制", not os.path.exists(os.path.join(dst, "__pycache__")))
    # 覆盖更新：目标已存在时只更新同名文件、不删除多余内容
    extra = os.path.join(dst, "user_extra.txt")
    with open(extra, "w", encoding="utf-8") as f:
        f.write("user data")
    installer.copy_skill(fake_src, dst)
    check("更新安装不删除目标已有内容", os.path.exists(extra))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- 4. 目标解析 ----
class _A:
    def __init__(self, target=None, path=None, target_dir=None):
        self.target, self.path, self.target_dir = target, path, target_dir

home = os.path.expanduser("~")
d, kind = installer.resolve_target(_A(target="claude"))
check("claude 目标解析", d == os.path.join(home, ".claude", "skills", "amap-resolve-locations")
      and kind == "claude", d)
d, kind = installer.resolve_target(_A(target="codex"))
check("codex 目标解析", d == os.path.join(home, ".codex", "skills", "amap-resolve-locations")
      and kind == "codex", d)
d, kind = installer.resolve_target(_A(path=r"D:\my\skills"))
check("--path 目标解析", d == r"D:\my\skills" and kind == "path")

# ---- 5. 核心脚本与规则文件不因适配层缺失 ----
required = ["scripts/amap_api.py", "scripts/resolver.py",
            "scripts/coordinate_transform.py", "scripts/output_writer.py",
            "SKILL.md", "references/coordinate_systems.md"]
check("核心流程文件齐全", all(os.path.isfile(os.path.join(SKILL_ROOT, r))
                              for r in required))

# ---- 报告 ----
failed = 0
for name, ok, detail in CHECKS:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" — {detail}"))
    if not ok:
        failed += 1
print("ALL PASS" if failed == 0 else f"HAS {failed} FAILURE(S)")
sys.exit(0 if failed == 0 else 1)
