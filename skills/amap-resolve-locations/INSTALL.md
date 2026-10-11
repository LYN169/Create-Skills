# INSTALL.md · 多 Agent 安装适配

本 skill 的核心是一套**标准库 Python 脚本**（任何能执行本地命令的 Agent 均可调用）
加一份**规则文档**（SKILL.md）。不同 Agent 的"技能机制"不同，安装方式分两类。

## 安装方式总览

| Agent | 安装 | 触发方式 |
|---|---|---|
| Claude Code | `python install.py claude`（或手动复制到 `~/.claude/skills/`） | 原生 Skill 机制，自动读取 SKILL.md |
| OpenAI Codex | `python install.py codex`（或手动复制到 `~/.codex/skills/`） | 原生 Skill 机制（Codex 兼容本 SKILL.md 的 name/description 头） |
| DeepSeek / 豆包 / Work Buddy / Kimi / 通义等 | `python install.py --path <任意目录>` | 把 `cross-agent.md` 全文粘贴进该 Agent 的系统提示词/指令/知识库，并授予其本地命令执行权限 |

通用前置：Python 3.8+；XLSX 输出需 `pip install openpyxl`（CSV 不需要）。
高德 Key 三选一：环境变量 `AMAP_KEY`；`AMAP_KEY_FILE` 指向仓库外凭据文件；或
`scripts/amap_key.txt`（本地兼容，勿提交）。**任何安装方式都不会复制凭据文件。**

## 一、Claude Code

```bash
python install.py claude
# 等价于：把整个目录复制到 ~/.claude/skills/amap-resolve-locations/
```

重启会话后，用户给出地点名单时自动触发（关键词：地点转坐标/解析经纬度/GCJ-02 等）。

## 二、OpenAI Codex

```bash
python install.py codex
# 等价于：把整个目录复制到 ~/.codex/skills/amap-resolve-locations/
```

Codex 的 Skill 格式与 Claude Code 相同（SKILL.md 的 `name`/`description` frontmatter 兼容），
规则与脚本执行方式完全一致。

## 三、无原生 Skill 机制的 Agent（DeepSeek、豆包、Work Buddy 等）

三步：

1. **安装文件**：`python install.py --path D:\my\skills`（目录任意，例如放到团队共享盘）；
2. **注入指令**：把本目录 `cross-agent.md` 的全文粘贴进该 Agent 的**系统提示词 / 自定义指令 /
   知识库**（豆包：指令中心或智能体人设；DeepSeek：系统提示词或项目指令文件）；
3. **授予执行权**：确保该 Agent 能执行本地命令（shell/Python）。脚本路径要写绝对路径，
   并在 Agent 所在环境里配置 `AMAP_KEY`（或 `AMAP_KEY_FILE`）。

说明：`cross-agent.md` 是面向通用 Agent 的**自足执行摘要**（含消歧纪律、records 格式、
五条命令、输出字段与安全要求）；Agent 若能读取文件，还应让它先读 `SKILL.md` 获取完整规则。
核心查询/转换/写出流程对所有 Agent 完全一致，不存在"降级版本"。

## install.py 行为保证

- 按**白名单**复制（脚本、文档、测试、示例），绝不复制：`amap_key.txt`、`.env*`、
  `__pycache__`、`.git`、日志、缓存、临时文件；
- 目标是已存在的目录时**只更新同名文件、不删除任何多余内容**；
- 复制完成后打印该 Agent 的下一步配置提示（Key 配置 / cross-agent.md 粘贴步骤）。
