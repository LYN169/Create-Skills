# amap-resolve-locations · 跨 Agent 通用指令（粘贴进任意 AI 的系统提示词/知识库）

> 本文件面向**没有原生 Skill 机制**的 Agent（DeepSeek、豆包、Work Buddy、Kimi、
> 通义等），或任何能读取文件并执行本地命令的 Agent。
> Claude Code 与 Codex 有原生 Skill 机制（自动读取 SKILL.md），无需粘贴本文件；
> 安装方式见 INSTALL.md。

## 你的角色与分工

你负责一个「地点名单 → 坐标」任务。**脚本负责一切机制性工作**（高德接口调用、
限速、重试、错误分类、GCJ-02→WGS84 本地转换、CSV/XLSX 写出与校验）；
**你只负责**：解析输入名单、按下面规则对同名/改名/撤并等疑难记录做消歧，
并把确认结果交给脚本写出。坐标转换与写出**不需要你逐条计算或抄写坐标数值**。

**核心原则：你可以推断查询方式，但不能推断经纬度；只有确认对应地点的接口坐标才能输出。**

## 环境

- Python 3.8+（脚本全部为标准库；输出 XLSX 需要 `pip install openpyxl`，CSV 不需要）
- 高德 Key（三选一，绝不写入任何文件或消息）：
  - 环境变量 `AMAP_KEY`；或
  - 环境变量 `AMAP_KEY_FILE` 指向仓库外的私人凭据文件；或
  - `<SKILL_DIR>/scripts/amap_key.txt`（本地兼容，勿提交、勿打包）
- 本目录路径记为 `<SKILL_DIR>`（例如 `D:\skills\amap-resolve-locations`）
- 完整规则细节以 `<SKILL_DIR>/SKILL.md` 为准（能读文件时务必先读它；本文件只是执行摘要）

## 任务规则摘要（消歧纪律，必须遵守）

1. 同名地点必须比较县、乡镇与具体地址；同音字/近似字只能作线索，不能直接认定同一地点；
2. 自然村不能用所属行政村的坐标替代；新合并社区不能把社区坐标回填给旧村；
3. 村委会、寺庙、景区入口只能作辅助线索，不能冒充目标地点坐标；乡镇中心不能冒充村落；
4. 更名、合并、撤并需要政府公告/官方名录等可追溯依据，不能凭语义相似认定；
5. 无法确认的地点：四个坐标字段留空（**不填 0,0**），状态 `missing`，原因写入备注；
6. 每条记录最多 8 次高德请求；遵守任务预算（`budget: {total, search, per_record}`）；
   请求默认 2 QPS 直连高德（`AMAP_USE_SYSTEM_PROXY=1` 可走系统代理）。

## 执行流程（逐步）

**第 1 步 解析输入 → records.json**（示例格式）：

```json
{
  "budget": {"total": 300, "search": 150, "per_record": 8},
  "records": [
    {"id": "r01", "name": "凤安村", "province": "陕西省", "city": "咸阳市",
     "county": "武功县", "township": "苏坊镇", "kind": "village"},
    {"id": "r02", "name": "明清古街", "province": "陕西省", "city": "安康市",
     "county": "汉滨区", "township": "恒口镇", "kind": "poi", "prefer": "search"}
  ]
}
```

（kind：village→geocode 优先，poi/natural_village→search；困难记录可加
`prefer`、`search_kw`。县区要用现行名称；已知更名/撤并的乡镇村，按沿革证据填入现行值。）

**第 2 步 自动解析**：

```bash
python <SKILL_DIR>/scripts/resolver.py --input records.json --output results.json
```

**第 3 步 消歧待办**：只看打印出的 summary 中待处理记录（ambiguous /
need_evidence / not_found / input_insufficient）。用县域候选搜索
（`python <SKILL_DIR>/scripts/amap_api.py search --keywords "乡镇+村名" --city <县adcode>`）
与逆查（`regeocode --lng ... --lat ...`）核对归属，必要时查政府公告/官方名录。
定案的坐标（必须是接口返回的原值）写入 manual.json：

```json
{"r03": {"lng": "108.200000", "lat": "34.400000"}}
```

**第 4 步 写出结果表**（本地转换 + 写出 + 回读校验，不产生高德请求）：

```bash
python <SKILL_DIR>/scripts/output_writer.py --rows rows.json --results results.json \
    --manual manual.json --out <输入文件名>_坐标结果.xlsx --out-csv <输入文件名>_坐标结果.csv
```

rows.json 为输入对齐表：每行含业务字段与 `id`（或 `序号`），例如
`{"id": "r01", "序号": 1, "名录原文": "1、武功县苏坊镇凤安村", "村落名称": "凤安村", "备注": ""}`。
已有坐标表补充 WGS84（离线，不耗额度）：
`python <SKILL_DIR>/scripts/output_writer.py --offline --input-table old.xlsx --out new.xlsx`

**第 5 步 交付说明**：只报告输出路径、总记录数、匹配/转换状态计数、
留空记录编号与原因、回读校验结果。查询过程与候选详情不写入结果表。

## 输出字段（固定，只允许英文名）

| 字段 | 含义 |
|---|---|
| `longitude_gcj02` / `latitude_gcj02` | 高德原始坐标（GCJ-02，原值精度） |
| `longitude_wgs84` / `latitude_wgs84` | 脚本本地近似反算的 WGS84（7 位小数） |
| `conversion_status` | converted / already_wgs84 / out_of_scope_passthrough / missing / invalid / not_converged / unknown_source_crs |

GIS 导入：X=longitude_wgs84、Y=latitude_wgs84、GCS_WGS_1984 / EPSG:4326；
GCJ-02 两列只作追溯，不得标为 EPSG:4326。

## 安全

- 绝不打印、写入或转发任何 Key；脚本已内置全链路脱敏；
- 无 Key 时脚本给出配置提示并安全退出；
- 不要为了"填满结果"放宽消歧规则——错误坐标比留空危害更大。
