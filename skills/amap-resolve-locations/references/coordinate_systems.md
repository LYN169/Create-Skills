# 坐标系与 GCJ-02→WGS84 转换（已实现，随结果表输出）

实现：`scripts/coordinate_transform.py`（转换）、`scripts/output_writer.py`（结果表写出）。
结果表固定输出五个英文字段：`longitude_gcj02`、`latitude_gcj02`、`longitude_wgs84`、`latitude_wgs84`、`conversion_status`。

## 1. 坐标系

- 高德接口返回 **GCJ-02**（国测局坐标，即"火星坐标"），经度在前、纬度在后，单位十进制度。
- **GCS_WGS_1984 即 WGS84，EPSG:4326**。
- 两套坐标不能互换标注：GCJ-02 相对 WGS84 在中国大陆有约几十至几百米的系统性偏移；**不能**仅通过改字段名、定义投影或修改 CRS 标签完成转换。

## 2. 转换算法与来源

- 正向公式（WGS84→GCJ-02）：公开**逆向推导**的 GCJ-02 偏移公式，参数 a=6378245.0、ee=0.00669342162296594323，与开源项目 [wandergis/coordtransform](https://github.com/wandergis/coordtransform)（MIT License）和 [googollee/eviltransform](https://github.com/googollee/eviltransform)（MIT License）的实现一致。本 skill 按数学公式独立实现，未复制上述项目源码；两者的 MIT License 允许使用、复制与再发布（保留版权声明）。
- 逆向（GCJ-02→WGS84）：**残差迭代反算**——以输入 GCJ-02 为初值，将估计的 WGS84 代入正向公式，计算与输入 GCJ-02 的经纬度残差并修正估计值，直至收敛。默认：经纬度最大绝对残差 ≤1e-7 度、最多 30 次迭代；内部保留完整浮点精度，写出时才按 7 位小数格式化。
- **本实现不是高德官方逆变换**，不是测量级精度；同公式不同实现的一步近似（如 coordtransform 的 `2x−forward(x)`）与迭代解的差异约为 5e-7 度（厘米级），迭代解的正向回代残差更小。

### 精度声明

- 迭代阈值只衡量所选公式的**数值收敛**（回代闭合），不能证明真实地面定位达到同等精度；
- 地理编码代表点误差（POI 点与目标聚落中心/入口的差异）、地点匹配误差不会因转换而消失；
- 更多小数位不代表更准确——WGS84 默认写 7 位小数仅为数值格式。

## 3. 适用范围与范围外策略

- 适用范围：矩形粗界 lng∈[72.004,137.8347]、lat∈[0.8293,55.8271]（中国内地粗界）。**该矩形不是精确国界**：不含港澳台等无偏移区域，个别边境点可能误判。
- 范围外默认**不施加偏移、原值透传**，`conversion_status=out_of_scope_passthrough`；不得标记成正常转换成功（converted）。

## 4. 源坐标系参数与状态

- `--source-crs gcj02`（默认，高德接口原值）→ 执行反算。
- `--source-crs wgs84` → 已声明为 WGS84，**不执行 GCJ-02 反算**，原值放入 WGS84 列，GCJ-02 两列留空，状态 `already_wgs84`；防止重复转换。
- 输入坐标系未知 → **不得凭数值范围猜测**，四列留空，状态 `unknown_source_crs`。
- 其余状态：`converted`（正常收敛）、`missing`（无已确认坐标）、`invalid`（NaN/Infinity/非数值/单边缺失/超出 lng∈[-180,180]·lat∈[-90,90]）、`not_converged`（反算未收敛；保留 GCJ-02 原值、WGS84 留空）、`out_of_scope_passthrough`。

## 5. 验证方式

- 独立参考样例（测试中已固化，来源注明）：
  - wandergis/coordtransform README 公开示例：wgs84(116.404, 39.915) → gcj02(116.41024449916938, 39.91640428150164)；
  - mapchaxun.cn 对照页（https://www.mapchaxun.cn/wgs84-gcj02）：wgs84(116.391275, 39.907201) → gcj02(116.397516, 39.908602)。
- 中国大陆多点（北京/上海/西安/成都/广州/哈尔滨/拉萨/乌鲁木齐）正向回代残差 ≤1e-7 度。
- **回代通过本身不能证明真实位置精度**；如需更高位置可信度，用独立、坐标体系已知的控制点（公开 WGS84 记录或实测点）核验。
- 误差来源分开讨论：地点匹配误差（消歧规则控制）、POI 代表点误差（定位粒度）、坐标转换误差（公式残差，米级以内）。

## 6. GIS 导入流程（ArcGIS / QGIS）

1. 坐标数值转换已由脚本完成（`longitude_wgs84`/`latitude_wgs84`）；
2. 导入 WGS84：**X 选 `longitude_wgs84`，Y 选 `latitude_wgs84`，输入坐标系选 GCS_WGS_1984 / EPSG:4326**；
3. `longitude_gcj02`/`latitude_gcj02` 两列仅用于原始结果追溯或高德场景，**不能直接标为 EPSG:4326**；不得混选两套坐标的经纬度；
4. 需要米制距离、面积或缓冲区分析时，再按研究区域选择合适投影坐标系（如 UTM 分带、CGCS2000 高斯投影等）。

## 7. 输出与离线

- 结果表默认另存新文件，不覆盖输入；XLSX 坐标单元格为数值；CSV 默认 UTF-8 BOM。
- 已有坐标表补充 WGS84：`python scripts/output_writer.py --offline --input-table old.xlsx --out new.xlsx`，旧 X(经度)/Y(纬度) 列迁移为英文名，全程本地执行、不产生高德请求、不消耗额度。
- 写出后程序回读核对记录数、行序、字段名与坐标数值。
