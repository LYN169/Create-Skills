# Create-Skills

Claude Code Skills 集合（多数 skill 亦适配其他 AI Agent，见各 skill 的 INSTALL.md）。

## 已有 Skills

| Skill | 说明 |
|---|---|
| [amap-resolve-locations](skills/amap-resolve-locations/README.md) | 高德地点解析与坐标匹配：批量把地点名称/地址解析为 GCJ-02 坐标并本地近似反算 WGS84，输出双坐标结果表（CSV/XLSX），用于 GIS 导入与分析；支持 Claude Code、Codex、DeepSeek、豆包、Work Buddy 等多 Agent |

## 安装

各 skill 自带多 Agent 安装器：

```bash
python skills/<skill-name>/install.py claude        # Claude Code
python skills/<skill-name>/install.py codex         # OpenAI Codex
python skills/<skill-name>/install.py --path <目录>  # 其他 Agent（见 INSTALL.md）
```

各 skill 的用法、依赖与 Key 配置见其目录内 README、INSTALL.md 与 SECURITY.md。本仓库不内置任何 API Key。
