---
name: amap-resolve-locations
description: Use when the user needs place names resolved to AMap (高德地图) coordinates — 地点转坐标、解析经纬度、地名查经纬度、批量村落/文保单位/学校定位, provides lists, tables or images of 传统村落、自然村、文保单位、历史建筑、学校、公园 needing geocoding, or mentions 高德 API / AMap geocoding / POI 搜索 / GCJ-02 / WGS84 / 坐标转换 / 火星坐标. Use especially when same-name villages across counties, 自然村 vs 行政村 ambiguity, renamed or merged villages, or row-by-row CSV output could lead to wrong coordinate matches.
---

# 高德地点解析与坐标匹配

把一批地点解析为对应的高德 GCJ-02 经纬度，输出与输入逐条对应的结果表（GCJ-02 与 WGS84 两套英文坐标字段 + 转换状态）。适用于传统村落、自然村、文保单位、历史建筑、学校、公园等具有明确位置的对象。

**核心原则：AI 可以推断查询方式，但不能推断经纬度；只有确认对应地点的接口坐标才能输出。坐标转换与结果写出全部由本地脚本完成，AI 不逐条计算、抄写或审核坐标数值。**

分工：查询衔接（首选接口→校验→条件补查/逆查）与限速、预算、错误分类由 `scripts/amap_api.py` + `scripts/resolver.py` 承担；GCJ-02→WGS84 转换由 `scripts/coordinate_transform.py` 承担；结果表合并、转换、CSV/XLSX 写出与回读校验由 `scripts/output_writer.py` 承担。AI 只负责输入解析、身份消歧、沿革证据与输入不足等例外。查询变体不能直接证明身份——**违反本文件字面规则即违反其精神**。

## 1. 任务范围

- 输入：一个或多个地点，可带行政层级或补充线索；输出：与输入逐条对应的经度、纬度。
- 适用于村落、自然村、文保单位、学校、公园、古街等各类具有明确位置的对象，**不限于特定省份或名录类型**；`references/shaanxi_adcodes.json` 只是可选辅助资源（缺项查接口补齐），不是通用依赖。
- 默认不负责：传统村落资格认定、村界划分、保护范围绘制。
- 道路、河流、大范围景区等线状/面状对象：**不能擅自选一个点代表整体**，先确认用户需要入口、中心还是指定位置。
- 村落默认寻找**目标聚落的代表位置**；行政村村委会 ≠ 自然村或传统聚落的位置，不能自动替代。

## 2. 输入解析

- 支持文字名单、表格、CSV、Excel、图片和用户提供的网页内容；自动识别地点字段与行政层级，不要求固定列名。
- 内部统一整理为记录表：

  | 字段 | 说明 |
  |---|---|
  | 记录编号 | 原始输入顺序 |
  | 原始名称 | 与输入逐字一致，后续输出靠它对齐 |
  | 地点类型 | 村落/自然村/文保单位/学校/公园/其他 |
  | 省、市、县、乡镇 | 来自该行、表头、标题或上下文 |
  | 补充线索 | 旧名、别名、备注等 |

- 表头、标题、上下文中的共同地区可以应用到名单（如标题写“陕西省某县”）；**不能**仅因本次会话之前处理过陕西就默认新地点仍在陕西。
- 保留原始顺序和重复项；重复地点同样逐条输出。
- 图片文字无法辨认时标为待确认，**不猜字**。
- 缺少地区且同名歧义无法排除时：先处理其余记录，最后集中向用户询问必要信息（一次问清）。

## 3. 查询策略

按地点类型选入口，逐级补充；**找到满足第 5 节确认条件的结果立即停止**，不要求每条跑完整流程。

| 查询阶段 | 使用方式 | 继续查询的条件 |
|---|---|---|
| ① 精确查询 | 完整行政层级＋原始名称（村落优先 geocode，明确 POI 优先 search） | 无结果、层级过粗、身份有疑问 |
| ② 县域候选搜索 | 县 adcode + `citylimit=true` 搜“乡镇＋地点”或地点名 | 同名、名称写法不同、地址缺失 |
| ③ 名称变体查询 | 简称、繁简体、标点、“村”等后缀变化 | 原始名称未解决 |
| ④ 沿革核查 | 查政府公告、官方名录、地方志，确认旧名/新名/隶属后再查 | 涉及更名、合并、自然村 |
| ⑤ 候选复核 | 逆地理编码检查周边位置与行政归属 | 存在行政冲突或定位疑点 |

- 地理编码返回行政区（province/city/district/township）与匹配级别（level）；POI 搜索用县 adcode + `citylimit=true` 限制范围。
- 不无条件扩大到全国搜索；不默认只搜“旅游景点”类型。

## 4. 名称匹配边界（查询变体不能直接证明身份）

AI 可以生成检索变体，但**接受结果必须有身份依据**：

- 同名必须比较县、乡镇及具体地址；
- 同音字、近似字只能用于寻找线索，不能直接认定为同一地点；
- 曾用名与现名需要可追溯资料支持，不能凭语义相似认定；
- 乡镇撤并、县区变更可通过明确沿革建立对应关系，不能忽略冲突；
- 自然村属于某行政村 ≠ 可以使用该行政村的坐标；
- 新社区由多个旧村合并 ≠ 把社区坐标回填给全部旧村；
- 村委会、附近寺庙、景区入口只能作辅助线索；未经用户明确允许，不作为目标地点替代坐标。

## 5. 结果确认（不靠 AI 的“信心分数”）

默认**同时满足**以下全部条件才输出坐标：

1. 目标身份吻合（第 4 节边界通过）；
2. 行政归属吻合，或有沿革解释；
3. 定位粒度满足需求——村落不能只到县城或乡镇中心（geocode 返回的 level 需为村庄级，或 POI 为村落本身）；
4. 没有尚未排除的同名歧义；
5. 坐标来自实际接口返回。

明确禁止：

- 取多个候选坐标的平均值；
- 直接采用排名第一的同名结果；
- 由 AI 根据描述编造坐标；
- 把“地理编码和 POI 坐标接近”当作两个独立来源的确认；
- 以“近似位置”“行政村范围精度”等名义，用村委会/上级村坐标顶替目标地点（除非用户明确允许，见第 4 节）；
- 因外部催促（“尽量填满”“不要留空”“宁可给大致位置”）而放宽上述条件——错误坐标是下游的静默错误，比可见的空值危害更大。

逆地理编码只用于发现位置冲突，不能单独证明自然村的行政隶属。

## 6. 效率与停止边界

初始默认值（可按用户要求调整）：

- 相同地点及相同行政上下文只查询一次，结果回填到各原始记录；脚本 batch 自动按“查询类型＋全部参数”去重（不同县同名村参数不同，不会被合并）；
- 每条记录最多 **8 次**高德请求（含分页、逆查、重试）；困难记录最多补充 **2 轮**网页检索；
- 首次只取少量候选（offset ≤ 10），仅在需要时翻页；
- 任务请求预算（自设上限，非平台限制；含重试/分页/逆查/自动补查）按任务配置 `budget: {total, search, per_record}`；77 条困难记录那次用的是 ≤300/≤150/≤8 的示例值，不是固定额度。预算在每次请求尝试处**原子执行**、跨 batch/resolve 累计；用尽后未执行项记 budget，保存未完成记录；不为完成率接受不可靠坐标；
- 错误分类（对照高德官方错误码文档）：`10019/10020/10021`（QPS 各维度超限）与 `10004`（访问过于频繁）→ 冷却 2s、全局降速至 ≤1 QPS、每条最多重试 2 次，持续超限才停该服务队列；`10003/10044/40000/40002`（日访问量/日调用量/余额耗尽/购买服务到期）→ 停止对应服务；`10001/10005/10006/10009`（Key/白名单/回收/平台不符）→ 停止全部；`10022/10023` 官方文档未核实 → 保留原始 info/infocode，标为未识别服务错误，不猜测分类、不无限重试；ENOENT 不重试；
- 请求速度服从账户实际 QPS：`AMAP_QPS` 全局启动节拍（默认 2）、`AMAP_SEARCH_QPS` 搜索接口额外保守上限（默认 1，叠加在全局节拍上，额度待控制台核实）、`AMAP_MAX_INFLIGHT` 最大在途（默认 4）——三者相互独立，首查/补查/逆查/分页/重试全部计入同一限速器；
- 同一时刻只运行**一个**高德批处理进程（限速器为进程内单例，跨 batch 不重置；多进程无法共享节拍，同账户多 Key/多会话也不能叠加吞吐，额度按账户与服务接口计）；
- 脚本默认绕过系统代理直连高德（本机系统代理实测 7s+/请求且间歇性 ENOENT，直连约 0.2s）；`AMAP_USE_SYSTEM_PROXY=1` 可恢复走系统代理；
- 县 adcode 优先查 `references/shaanxi_adcodes.json`（来源与日期已标注，不是永久常量；缺项不影响其他地区）；表中没有的县才 geocode 县名取码；
- 达到预算仍不能确认：坐标留空，归入待处理记录，继续完成其他地点。
- 坐标转换与结果写出**不产生任何高德请求**：转换是本地数值运算，写出只读写本地文件；已确认地点不因增加 WGS84 列而重新查询。对已经完成的坐标表，用 `output_writer.py --offline` 离线补充两套坐标，无需再次消耗 Key 额度。

内部状态区分（resolver 输出）：`confirmed / ambiguous / need_evidence / not_found / input_insufficient / interface_error / budget`——不把所有失败都解释成“高德没有这个地点”。

## 7. 坐标规范

- 高德接口原始坐标按 **GCJ-02** 管理，经度在前、纬度在后；GCS_WGS_1984 即 **WGS84 / EPSG:4326**。
- 结果表同时输出两套坐标（第 8 节），转换由 `scripts/coordinate_transform.py` 本地完成；**不能**仅通过改字段名、定义投影或修改 CRS 标签完成转换。
- 转换算法：公开逆向推导的 GCJ-02 正向公式（与 wandergis/coordtransform、googollee/eviltransform 一致，MIT License）+ 残差迭代反算（初值=输入 GCJ-02，代入正向公式求残差并修正，默认经纬度最大绝对残差 ≤1e-7 度、最多 30 次）。**不是高德官方逆变换**；算法来源、许可证与限制见 `references/coordinate_systems.md`。
- 适用范围：矩形粗界 lng∈[72.004,137.8347]、lat∈[0.8293,55.8271]（**不是精确国界**）；范围外不施加偏移、原值透传，状态标 `out_of_scope_passthrough`，不标为正常转换成功。
- 源坐标系必须明确（`--source-crs gcj02` 默认 / `wgs84`）：已声明为 WGS84 的数据不执行 GCJ-02 反算（`already_wgs84`）；坐标系未知时**不得凭数值范围猜测**（`unknown_source_crs`）。
- 迭代阈值只衡量所选公式的数值收敛，**不能证明真实地面定位达到同等精度**；地理编码代表点误差不会因转换而消失。
- 经纬度取接口原值（保留原始精度），先校验数值完整性（拒绝 NaN、Infinity、单边缺失、非数值、超出 lng∈[-180,180]/lat∈[-90,90]）再转换；更多小数位不代表更准确。

## 8. 输出规范

结果表由 `scripts/output_writer.py` 生成。skill 新增字段**固定**为以下五个（新增字段名只允许匹配 `^[A-Za-z][A-Za-z0-9_]*$`——不含中文、括号、空格、连字符；CSV/XLSX 固定使用，未来 SHP 另行处理字段长度限制）：

| 字段 | 含义 |
|---|---|
| `longitude_gcj02` | 高德原始经度（接口原值，保留原始精度） |
| `latitude_gcj02` | 高德原始纬度 |
| `longitude_wgs84` | 本地转换后的 WGS84 经度（默认 7 位小数；小数位数不代表定位精度） |
| `latitude_wgs84` | 本地转换后的 WGS84 纬度 |
| `conversion_status` | `converted` / `already_wgs84` / `out_of_scope_passthrough` / `missing` / `invalid` / `not_converged` / `unknown_source_crs` |

规则：

- 默认输出位置与命名（用户未另行指定时）：与输入文件**同目录**、文件名 `<输入文件名>_坐标结果.xlsx`，并同时输出同名 `.csv` 副本（UTF-8 BOM）；**另存新文件，不覆盖输入源文件**。
- 按输入顺序逐条对应，**不删除失败行、不改变行数与行序**；匹配失败或仍有歧义的地点，**不得**把候选点、乡镇中心或 `0,0` 写入四个坐标字段——原行保留、四列留空、`conversion_status=missing`，原因写入现有匹配状态/说明字段。
- 地点已确认、GCJ-02 有效但转换失败（`not_converged`）：保留 GCJ-02 原始坐标，WGS84 两列留空。
- 用户原有业务字段、内容、行序与记录数量保持完整；旧版 X(经度)/Y(纬度) 等坐标列在新结果文件中迁移为 `longitude_gcj02`/`latitude_gcj02`，不残留中文坐标列。
- 字段冲突（用户表已有同名列）时报错，不悄悄覆盖无关数据。
- XLSX 坐标单元格写**数值**（不写带单位字符串）；CSV 用规范 csv 写出、十进制度数、小数点用点号，默认 UTF-8 BOM（可配编码）。
- 写出后由程序重新读取核对：记录数、行序、字段名、坐标数值与缺失，防止遗漏或错位。
- **GIS 导入**：导入 WGS84 时 X 选 `longitude_wgs84`、Y 选 `latitude_wgs84`，输入坐标系选 GCS_WGS_1984 / EPSG:4326。GCJ-02 两列只用于原始结果追溯或高德场景，**不能**直接标为 EPSG:4326；**不得**混选两套坐标的经纬度。需要距离/面积分析时再按研究区域选择合适的投影坐标系。
- 交付说明只简要报告：输出路径、总记录数、匹配状态计数、转换状态计数、回读验证结果与少量异常摘要；查询过程与候选详情不塞入最终坐标表；转换与写出过程中成功记录不逐行回传。

## 9. 工具、Key 与数据使用边界

- Key 读取优先级：环境变量 `AMAP_KEY` → 环境变量 `AMAP_KEY_FILE` 指向的私人凭据文件（仓库之外）→ 脚本同目录 `amap_key.txt`（本地兼容，已 gitignore）。无 Key 时给出简短配置提示并安全退出。
- Key 绝不写入 Skill 正文、最终文件、结果表、可见日志或聊天消息；不建议把 Key 放在命令行参数或完整请求 URL 中。所有错误消息、网络异常与调试输出由 `redact()` 统一脱敏（凭据值及其 URL 编码/base64 形式、key=/sig=/authorization= 等通用模式）。
- 保存、导出和离线使用结果须遵守高德服务条款；持有 Key ≠ 获得所有数据使用授权。
- 不新增长期地点数据库；任务数据与 Key 不打包进发布的 skill。

## 工作流程

1. **解析输入** → 按第 2 节生成记录表（记录编号、原始名称、地点类型 kind: village/poi/natural_village/unknown、省市县乡镇、补充线索）。同名歧义无法排除的记录先集中问用户。
2. **确认 Key** → `python scripts/amap_api.py geocode --address "北京市"`；报 invalid_key 时提示用户配置后继续。
3. **生成 records 输入** → 每条记录带 `id/name/province/city/county/township/kind`；AI 可为困难记录指定 `prefer`（geocode/search）与 `search_kw`；任务级 `budget` 按本次任务规模配置（示例 300/150/8，不是固定值）。
4. **执行自动解析** → `python scripts/resolver.py --input records.json --output results.json`。脚本按第 3 节规则完成：首选接口 → 校验 → 条件补查/逆查（不做全量双查、不做前 N 条无差别逆查），返回状态与候选；`--detail <id>` 可按记录查看完整详情（调试用）。
5. **处理待办** → 只看 summary 中的 `pending_records`（ambiguous/need_evidence/not_found/input_insufficient），按第 4、5 节对候选做身份消歧、沿革核查（网页证据）、必要时再定向补查，遵守第 6 节预算。多轮处理只回传新增或改变的疑难项。
6. **输出** → AI 定案记录（人工消歧确认的坐标）写入 `manual.json`（`{"r03": {"lng": "…", "lat": "…"}}`，坐标须为接口返回的原值），然后运行：
   `python scripts/output_writer.py --rows rows.json --results results.json --out result.xlsx [--out-csv result.csv] [--manual manual.json] [--source-crs gcj02|wgs84]`
   脚本本地完成：合并已确认坐标 → GCJ-02→WGS84 转换 → 写出五字段 → 回读核对，并打印紧凑摘要（路径、总数、匹配/转换状态计数、验证结果、异常前若干条）。成功记录不逐行回传，AI 不得逐条抄写或重算坐标。已有坐标表补充 WGS84 用 `--offline` 模式（见脚本用法），不消耗 Key 额度。

## 验收自检（交付前逐项确认）

- [ ] 同名村没有跨县误配（比较了县、乡镇、地址）
- [ ] 自然村没有被上级行政村坐标替代
- [ ] 更名/合并有沿革依据，不是语义相似认定
- [ ] 乡镇中心没有冒充村落（level 与粒度已核对）
- [ ] geocode 村庄级确认且名录带乡镇时，乡镇字段缺失的已逆查核实（回显链不可靠）
- [ ] 失败行为空行保留，没有删除、没有 `0,0`、没有错位
- [ ] 最终坐标表未混入未经确认的候选坐标
- [ ] 请求消耗、错误与预算统计已核对（resolver summary 的 usage/status_counts）
- [ ] 输出字段为英文名 `longitude_gcj02/latitude_gcj02/longitude_wgs84/latitude_wgs84/conversion_status`，无中文坐标列残留
- [ ] 未确认记录四列留空且 `conversion_status=missing`；转换失败保留 GCJ-02、WGS84 留空
- [ ] 源坐标系已明确（gcj02 默认 / wgs84），无重复转换、无凭范围猜坐标系
- [ ] 回读校验通过（记录数、行序、字段名、坐标数值与缺失），未覆盖输入源文件

## 脚本用法

```bash
# Key 配置（三选一，按优先级；Key 永不写入任何交付文件）
export AMAP_KEY=你的高德Web服务Key              # 方式一：环境变量
export AMAP_KEY_FILE=/path/to/private/key.txt   # 方式二：环境变量指向仓库外的私人凭据文件
# 或把 Key 写入 scripts/amap_key.txt            # 方式三：本地文件（已 gitignore，勿提交）

python scripts/amap_api.py geocode --address "陕西省咸阳市武功县苏坊镇凤安村" --city "咸阳市"
python scripts/amap_api.py search --keywords "苏坊镇凤安村" --city 610431 --page 1 --offset 10
python scripts/amap_api.py regeocode --lng 108.1326 --lat 34.3364
python scripts/amap_api.py batch --input plan.json --output results.json
python scripts/resolver.py --input records.json --output results.json          # 记录级自动解析
python scripts/resolver.py --input records.json --output r.json --detail r05   # 按记录查详情（调试）

# 结果写出（本地转换 + CSV/XLSX + 回读校验；不产生高德请求）
python scripts/output_writer.py --rows rows.json --results results.json --out result.xlsx \
    [--out-csv result.csv] [--manual manual.json] [--source-crs gcj02|wgs84]
# 离线补列：旧坐标表（X(经度)/Y(纬度) 或已有 gcj02 英文列）→ 新表，不消耗 Key 额度
python scripts/output_writer.py --offline --input-table old.xlsx --out new.xlsx \
    [--lng-col "X(经度)" --lat-col "Y(纬度)"] [--source-crs gcj02]

# 坐标转换调试/自检（纯本地，无网络）
python scripts/coordinate_transform.py --lng 108.1326 --lat 34.3364 [--source-crs gcj02]
python scripts/coordinate_transform.py --self-test

# 本地测试（无需 Key、无网络）
python tests/test_coordinate_transform.py
python tests/test_output_writer.py
cd tests/scenario && python run_mock.py
```

`rows.json`（输出对齐表）每行含业务字段与 `id`（或 `序号`，用作与 results.json 对齐的键）；`manual.json` 为 AI 定案补录 `{"id": {"lng": "…", "lat": "…"}}`（坐标必须是接口返回的原值）。`output_writer.py` 摘要只含：输出路径、总记录数、匹配状态计数、转换状态计数、回读验证结果与未确认记录编号（截断）。

resolver 输入格式（首选接口由 kind 决定：village→geocode，poi/natural_village→search；AI 可用 prefer 覆盖）：

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

resolver 摘要（发送给 AI 的默认内容，完整结果在输出文件中）：输入数/确认数/待处理数、本次与累计请求数（区分搜索与其他）、状态与错误统计、输出文件位置、待 AI 处理记录（编号/原始地点/行政上下文/候选摘要/未确认原因）。候选摘要只含必要字段（名称、行政区、地址、类型/级别、候选 ID、坐标、冲突原因），默认截断 3 条并注明候选总数——**不因截断声称只有一个候选**。confirmed 记录不重复回传；`--detail` 调试输出不含 Key。

batch 输入格式（`query_id` 建议用“记录编号-查询序号”，便于回填；可带 `budget` 预算与 `_record_key` 单条计数键）：

```json
{
  "budget": {"total": 300, "search": 150, "per_record": 8},
  "queries": [
    {"query_id": "r01-a", "type": "geocode", "address": "陕西省咸阳市武功县苏坊镇凤安村", "city": "咸阳市", "_record_key": "r01"},
    {"query_id": "r02-a", "type": "search", "keywords": "苏坊镇凤安村", "city": "610431", "citylimit": true, "page": 1, "offset": 10, "_record_key": "r02"},
    {"query_id": "r03-a", "type": "regeocode", "lng": "108.1326", "lat": "34.3364", "_record_key": "r03"}
  ]
}
```

返回结构说明：每个结果含 `location`（接口原值）与 `coord_error`（数值/范围校验，None 为通过）；`geocode` 含 `level`（省/市/区县/乡镇/村庄/门牌号等匹配级别）、`adcode`、`township` 等行政字段；`search` 含 `pname/cityname/adname`。错误分类：`invalid_key`（停全部）/ `daily_limit`（停对应服务）/ `qps_limit`（降速有限重试后停队列）/ `local_error`（ENOENT，不重试）/ `network`（退避重试后仍失败）/ `error` / `budget` / `dedup`。batch 返回额外含 `usage`（本次进程累计消耗）与 `budget` 字段。

## 提示词模板

给终端用户（同事等）提供任务时，直接引用 `prompt-template.md`：用户照抄一句基础提示词 + 给出输入文件路径即可，其余由本文件规则默认执行（五字段英文坐标表、XLSX/CSV 各一份、另存不覆盖输入）；固定行为与结果用法写在该文件"使用须知"中，不要求用户粘贴。
