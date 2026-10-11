#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py — 多 Agent 安装器（白名单复制，绝不复制凭据）

用法（在本目录下运行）：
    python install.py claude              # 安装到 ~/.claude/skills/（Claude Code）
    python install.py codex               # 安装到 ~/.codex/skills/（OpenAI Codex）
    python install.py --path D:\\my\\skills  # 安装到任意目录（DeepSeek/豆包/Work Buddy 等）

行为保证：
    - 按白名单复制（脚本/文档/测试/示例），不复制 amap_key.txt、.env*、__pycache__、
      .git、日志、缓存、临时文件；
    - 目标目录已存在时只覆盖同名文件，不删除任何多余内容；
    - 复制后打印该 Agent 的 Key 配置与使用提示（不含任何凭据值）。
"""
import argparse
import os
import shutil
import sys

# 白名单（相对本目录）；凭据/缓存/日志类文件一律排除
WHITELIST = [
    "SKILL.md",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "INSTALL.md",
    "cross-agent.md",
    "prompt-template.md",
    "LICENSE",
    "install.py",
    "scripts/amap_api.py",
    "scripts/resolver.py",
    "scripts/coordinate_transform.py",
    "scripts/output_writer.py",
    "scripts/amap_key.txt.example",
    "references/coordinate_systems.md",
    "references/shaanxi_adcodes.json",
    "examples/plan.example.json",
    "tests/test_coordinate_transform.py",
    "tests/test_output_writer.py",
    "tests/test_security.py",
    "tests/scenario/input.txt",
    "tests/scenario/mock_api.json",
    "tests/scenario/expected.csv",
    "tests/scenario/run_mock.py",
    "tests/scenario/README.md",
]

# 目标目录名（各 Agent 的技能目录约定）
SKILL_DIR_NAME = "amap-resolve-locations"

USAGE_HINTS = {
    "claude": (
        "下一步（Claude Code）：\n"
        "  1) 配置 Key：setx AMAP_KEY \"你的Key\"  或  setx AMAP_KEY_FILE \"私人凭据文件路径\"\n"
        "  2) 重启会话；用户给出地点名单（如“请把下面文件中的地点名单解析为坐标”）即自动触发\n"
        "  3) 可复制 prompt-template.md 中的两行提示词给终端用户，只需改输入文件路径"
    ),
    "codex": (
        "下一步（OpenAI Codex）：\n"
        "  1) 配置 Key：环境变量 AMAP_KEY 或 AMAP_KEY_FILE（指向仓库外凭据文件）\n"
        "  2) Codex 兼容本 SKILL.md 的 name/description 头，按 Skill 方式触发\n"
        "  3) 规则与脚本执行方式与 Claude Code 完全一致"
    ),
    "path": (
        "下一步（DeepSeek / 豆包 / Work Buddy 等无原生 Skill 机制的 Agent）：\n"
        "  1) 把本目录 cross-agent.md 全文粘贴进该 Agent 的系统提示词/指令/知识库\n"
        "  2) 授予该 Agent 本地命令执行权限，脚本用绝对路径调用\n"
        "  3) 在 Agent 所在环境配置 Key：AMAP_KEY 或 AMAP_KEY_FILE\n"
        "  4) 若 Agent 能读文件，让它先读 SKILL.md 获取完整规则"
    ),
}


def copy_skill(src, dst):
    """白名单复制；返回复制文件数。绝不复制白名单之外的文件（含凭据）。"""
    n = 0
    for rel in WHITELIST:
        s = os.path.join(src, rel)
        if not os.path.isfile(s):
            print(f"跳过缺失文件: {rel}")
            continue
        d = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
    return n


def resolve_target(args):
    if args.path:
        return args.path, "path"
    home = os.path.expanduser("~")
    if args.target == "claude":
        return os.path.join(home, ".claude", "skills", SKILL_DIR_NAME), "claude"
    if args.target == "codex":
        return os.path.join(home, ".codex", "skills", SKILL_DIR_NAME), "codex"
    raise SystemExit("需要 --path 目录，或 --target claude/codex")


def main(argv=None):
    ap = argparse.ArgumentParser(description="多 Agent 安装器（白名单复制，不复制凭据）")
    ap.add_argument("--target", choices=["claude", "codex"],
                    help="安装到该 Agent 的技能目录")
    ap.add_argument("--path", default=None,
                    help="安装到任意目录（用于无原生 Skill 机制的 Agent）")
    ap.add_argument("--target-dir", nargs="?", default=None,
                    help="位置参数：claude / codex / 目录路径")
    args = ap.parse_args(argv)
    if args.target is None and args.path is None and args.target_dir is not None:
        if args.target_dir in ("claude", "codex"):
            args.target = args.target_dir
        else:
            args.path = args.target_dir

    dst, kind = resolve_target(args)
    src = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(src) == os.path.abspath(dst):
        print("源目录与目标目录相同，无需安装。")
        print(USAGE_HINTS[kind])
        return 0

    n = copy_skill(src, dst)
    print(f"已复制 {n} 个文件到: {dst}")
    print(USAGE_HINTS[kind])
    return 0


if __name__ == "__main__":
    sys.exit(main())
