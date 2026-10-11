# Create-Skills

Claude Code Skills 集合。

## 已有 Skills

| Skill | 说明 |
|---|---|
| [amap-resolve-locations](skills/amap-resolve-locations/README.md) | 高德地点解析与坐标匹配：批量把地点名称/地址解析为 GCJ-02 坐标并本地近似反算 WGS84，输出双坐标结果表（CSV/XLSX），用于 GIS 导入与分析 |

## 安装

```bash
mkdir -p ~/.claude/skills
cp -r skills/<skill-name> ~/.claude/skills/
```

各 skill 的用法、依赖与 Key 配置见其目录内 README 与 SECURITY.md。本仓库不内置任何 API Key。
