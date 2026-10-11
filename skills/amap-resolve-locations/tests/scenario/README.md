# 验收场景（无 Key 可复现）

用 mock 高德响应检验 Skill 的五条验收标准，不消耗任何接口额度，也不依赖真实高德 Key。

## 组成

| 文件 | 作用 |
|---|---|
| `input.txt` | 输入名单：4 个地点（武功县） |
| `mock_api.json` | 模拟高德响应（格式与 `scripts/amap_api.py` 一致）；**未列出的查询一律视为无结果** |
| `expected.csv` | 期望输出：新标准五列 `longitude_gcj02,latitude_gcj02,longitude_wgs84,latitude_wgs84,conversion_status`（失败行坐标留空、状态 missing） |
| `run_mock.py` | 检查器：比对 `output.csv` 与 `expected.csv` |

## 埋设的陷阱与对应验收标准

| 记录 | 陷阱 | 正确行为 | 验收标准 |
|---|---|---|---|
| 1. 凤安村（苏坊镇） | 不限范围搜索时，眉县同名“凤安村”排第一 | 用完整地址地理编码，或比较县/乡镇后选武功县苏坊镇的结果 | 同名村不跨县误配 |
| 2. 李家沟（自然村，属凤安村） | 地理编码把“李家沟”归一化为“凤安村”（名称不符）；搜索只返回“凤安村村委会” | 身份不符，两行留空 | 自然村不被行政村/村委会替代 |
| 3. 王村（未给乡镇） | 地理编码只返回 `level=乡镇` 的武功镇坐标 | 粒度不足，留空 | 乡镇中心不冒充村落 |
| 4. 营上村（武功镇） | 地理编码无结果，必须走县域搜索 | 县域搜索命中武功镇营上村，输出坐标 | 县域候选搜索路径可用 |

## 用法

1. 由执行者（AI 或人）阅读 `input.txt` 与 `mock_api.json`，按 `SKILL.md` 规则产出 `output.csv`；
2. 运行检查器：

```bash
cd tests/scenario
python run_mock.py
```

全部 `PASS` 并输出 `ALL PASS` 即通过。
