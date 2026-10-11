# amap-resolve-locations · 高德地点解析与坐标匹配

一个 [Claude Code Skill](https://www.anthropic.com/claude-code)：把地点名单（村落、自然村、文保单位、历史建筑、学校、公园、地址等）通过高德接口批量解析为坐标，用于 GIS 导入及后续地理分析。**输入不局限于陕西省或传统村落**——任何具有明确位置的名称/地址名单均可处理。

## 工作方式

- **AI 协助**：理解输入名单、判断同名/改名/撤并等疑难匹配（按 `SKILL.md` 规则消歧）；
- **脚本负责**：接口调用、限速、重试、错误分类、预算控制（`scripts/amap_api.py` + `resolver.py`）；
  坐标转换与结果表写出（`scripts/coordinate_transform.py` + `output_writer.py`，本地数值运算，不消耗 API 调用或大模型 token）。

核心承诺：**AI 可以推断查询方式，但不能推断经纬度；只有确认对应地点的接口坐标才能输出。** 无法确认的地点留空并记录原因，不用乡镇中心、村委会或 `0,0` 冒充成功结果。

## 安装（多 Agent 支持）

本 skill 的核心是**标准库 Python 脚本 + 规则文档**，可用于任何能执行本地命令的 AI Agent：
Claude Code、OpenAI Codex（原生 Skill 机制），DeepSeek、豆包、Work Buddy、Kimi、通义等
（通过通用指令注入）。**各 Agent 使用同一套脚本与规则，处理流程和效果完全一致。**

```bash
python install.py claude        # Claude Code → ~/.claude/skills/
python install.py codex         # OpenAI Codex → ~/.codex/skills/（SKILL.md 头格式兼容）
python install.py --path D:\my\skills   # 其他 Agent：装到任意目录
```

| Agent | 触发方式 |
|---|---|
| Claude Code | 原生 Skill，自动读取 SKILL.md |
| Codex | 原生 Skill（兼容本 SKILL.md 的 name/description 头） |
| DeepSeek / 豆包 / Work Buddy 等 | 把 `cross-agent.md` 全文粘贴进系统提示词/指令/知识库，并授予命令执行权限；脚本按绝对路径调用 |

安装器按白名单复制，**绝不复制凭据文件**；目标目录已存在时只更新同名文件、不删除多余内容。
详细说明见 [INSTALL.md](./INSTALL.md)。

依赖：Python 3.8+（标准库）；输出 XLSX 需要 `pip install openpyxl`（CSV 流程纯标准库，不装也能用）。

## 配置高德 Key（三选一，按优先级；本仓库不含任何 Key）

```bash
export AMAP_KEY=你的高德Web服务Key              # 方式一：环境变量
export AMAP_KEY_FILE=/path/to/private/key.txt   # 方式二：环境变量指向仓库外的私人凭据文件（推荐）
# 方式三：把 scripts/amap_key.txt.example 复制为 scripts/amap_key.txt 并填入 Key
#         （仅本地兼容，已被 .gitignore 排除，绝不提交）
```

Key 获取：高德开放平台 → 控制台 → 应用管理 → 创建应用 → 添加 Key（服务平台选「Web 服务」）。无 Key 时脚本会给出上述配置提示并安全退出。安全事项见 [SECURITY.md](./SECURITY.md)。

## 快速开始（最小示例）

```bash
# 单点地理编码（验证 Key）
python scripts/amap_api.py geocode --address "北京市"

# 批量查询：按 examples/plan.example.json 的格式准备查询计划
python scripts/amap_api.py batch --input examples/plan.example.json --output out.json

# 本地自检（无 Key、无网络）
python scripts/coordinate_transform.py --self-test
python tests/test_coordinate_transform.py
python tests/test_output_writer.py
python tests/test_security.py
cd tests/scenario && python run_mock.py
```

完整流程：解析输入 → `resolver.py` 自动解析 → AI 消歧疑难记录 → `output_writer.py` 写出结果表。用法详见 `SKILL.md`（工作流程与脚本用法）；给终端用户的提示词模板见 `prompt-template.md`。

## 支持的输入输出

- 输入：文字名单、表格、CSV、Excel（.xlsx）、.doc/.docx（需本机有 antiword/python-docx 等提取工具）、图片与网页内容（由 AI 解析）。
- 输出：XLSX 和/或 CSV，与输入逐行对应，保留原有内容列、行序与记录数量，默认另存新文件、不覆盖输入。

## 默认坐标字段

| 字段 | 含义 |
|---|---|
| `longitude_gcj02` | 高德原始经度（GCJ-02，接口原值） |
| `latitude_gcj02` | 高德原始纬度（GCJ-02） |
| `longitude_wgs84` | 本地脚本近似反算的 WGS84 经度（7 位小数） |
| `latitude_wgs84` | 本地脚本近似反算的 WGS84 纬度 |
| `conversion_status` | `converted` / `already_wgs84` / `out_of_scope_passthrough` / `missing` / `invalid` / `not_converged` / `unknown_source_crs` |

字段名只含英文字母/数字/下划线（ArcGIS 等软件可直接绘图，中文列名实测会报"无效 SQL"）。

## 坐标系与精度限制

- 高德原始坐标是 **GCJ-02**（"火星坐标"）；GCS_WGS_1984 即 WGS84 / EPSG:4326。
- WGS84 由本地脚本按公开逆向推导的 GCJ-02 公式（与 wandergis/coordtransform、googollee/eviltransform 一致，MIT License，见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)）做**残差迭代反算**（阈值 1e-7 度 / 30 次），纯本地计算，**不消耗额外 API 调用或大模型 token**。**不是高德官方逆变换**。
- 适用范围为中国大陆粗界矩形 lng∈[72.004,137.8347]、lat∈[0.8293,55.8271]（非精确国界）；范围外原值透传并标 `out_of_scope_passthrough`。
- 迭代收敛只证明公式数值闭合，**不代表实地定位达到同等精度**；转换不提高原始地点匹配精度。
- 已声明为 WGS84 的输入不重复转换（`already_wgs84`）；源坐标系未知时不猜测（`unknown_source_crs`）。

## GIS 导入

导入 WGS84：**X 选 `longitude_wgs84`，Y 选 `latitude_wgs84`，输入坐标系选 GCS_WGS_1984 / EPSG:4326**。
`longitude_gcj02`/`latitude_gcj02` 两列只用于原始结果追溯或高德场景，**不能直接标为 EPSG:4326**；两套坐标的经纬度不要混选。需要距离/面积分析时，再按研究区域选择合适的投影坐标系。

## 定位与覆盖边界

- 接口返回的是**地点代表点**（村落聚落/POI 点），不能代替村界、测绘成果、地籍位置或精确建筑轮廓。
- 同名地点必须用县、乡镇等行政区上下文区分；自然村、旧地名、已更名或撤并地点可能无法确认——此时坐标留空并记录原因，绝不硬填。
- 实际覆盖取决于高德接口数据：中国大陆地名数据较全，**不能承诺可靠解析所有全球地点**（港澳台与境外覆盖弱，且 GCJ-02 偏移不适用）。
- API 额度、计费与 QPS 取决于**你自己的高德账户**（免费/付费档位由高德控制台决定）。脚本默认限速：全局 2 QPS（`AMAP_QPS`，本机账户实测 3 QPS 封顶，取 2 留余量）、搜索接口额外 1 QPS（`AMAP_SEARCH_QPS`）、最大在途 4（`AMAP_MAX_INFLIGHT`）；额度紧张时请自行调低，**不要把这些默认值当成平台通用标准**。
- 默认**绕过系统代理直连高德**（`AMAP_USE_SYSTEM_PROXY=1` 恢复系统代理）。应用层绕过系统代理不保证绕过 VPN 等网络层路由。

## 隐私与数据

本仓库**不内置任何 Key、不提供共享 Key、不维护无限扩张的地点数据库**；示例数据均为无隐私的合成数据。保存、导出和离线使用结果须遵守[高德服务条款](https://lbs.amap.com/pages/terms/)。

## License

本 skill 代码以 [MIT](./LICENSE) 发布；坐标公式为公开逆向推导实现，第三方来源与署名见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。
