#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_output_writer.py — 结果表写出与离线补列本地测试（无网络、无高德请求）

运行：cd <skill根目录> && python tests/test_output_writer.py
覆盖：
  1. 主流程合并：confirmed 输出坐标；失败/歧义行四列留空 + missing
  2. manual（AI 定案）补录生效
  3. 新增字段名符合 ^[A-Za-z][A-Za-z0-9_]*$；与业务字段冲突时报错
  4. XLSX 坐标单元格为数值；CSV 带 UTF-8 BOM、字段名/数值正确
  5. 写出后回读核对：记录数、行序、字段名、坐标数值与缺失
  6. 转换失败（not_converged）保留 GCJ-02 原值、WGS84 留空（表级）
  7. 离线补列：旧 X(经度)/Y(纬度) 迁移为英文名、追加 WGS84 与状态、
     业务列/行序/数量不变、输入文件不被覆盖
  8. 离线补列全程不导入 amap_api（无网络、不消耗额度）
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import coordinate_transform as ct  # noqa: E402
import output_writer as ow  # noqa: E402

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


TMP = tempfile.mkdtemp(prefix="amap_outtest_")
ROWS = os.path.join(TMP, "rows.json")
RESULTS = os.path.join(TMP, "results.json")
MANUAL = os.path.join(TMP, "manual.json")

with open(ROWS, "w", encoding="utf-8") as f:
    json.dump([
        {"序号": 1, "名录原文": "1、凤安村（苏坊镇）", "村落名称": "凤安村", "备注": ""},
        {"序号": 2, "名录原文": "2、李家沟（自然村）", "村落名称": "李家沟", "备注": "歧义"},
        {"序号": 3, "名录原文": "3、王村", "村落名称": "王村", "备注": ""},
        {"序号": 4, "名录原文": "4、营上村（武功镇）", "村落名称": "营上村", "备注": ""},
        {"序号": 5, "名录原文": "5、东京测试点", "村落名称": "东京测试点", "备注": "范围外"},
    ], f, ensure_ascii=False, indent=1)
with open(RESULTS, "w", encoding="utf-8") as f:
    json.dump({"outcomes": {
        "r001": {"id": "r001", "status": "confirmed",
                 "coordinate": {"lng": "108.100000", "lat": "34.300000"}},
        "r002": {"id": "r002", "status": "ambiguous", "reason": "同名候选需消歧"},
        "r003": {"id": "r003", "status": "not_found", "reason": "未找到"},
        "r004": {"id": "r004", "status": "confirmed",
                 "coordinate": {"lng": "108.300000", "lat": "34.500000"}},
        "r005": {"id": "r005", "status": "confirmed",
                 "coordinate": {"lng": "139.691700", "lat": "35.689500"}},
    }}, f, ensure_ascii=False, indent=1)
with open(MANUAL, "w", encoding="utf-8") as f:
    json.dump({"r003": {"lng": "108.200000", "lat": "34.400000"}}, f)

# ---- 1-2. 主流程合并 + manual ----
header, data, stats = ow.build_table(
    json.load(open(ROWS, encoding="utf-8")),
    json.load(open(RESULTS, encoding="utf-8"))["outcomes"],
    json.load(open(MANUAL, encoding="utf-8")))
check("表头含全部新字段", header[-5:] == ow.NEW_FIELDS, str(header[-5:]))
check("记录数一致", len(data) == 5)
by_id = {str(r[0]): r for r in data}   # 行布局：业务列 + [4..7]坐标 + [8]状态
r1 = by_id["1"]
check("confirmed行有GCJ02原值", r1[4] == "108.100000" and r1[5] == "34.300000")
check("confirmed行WGS84为7位小数",
      r1[6] is not None and len(r1[6].split(".")[1]) == 7 and len(r1[7].split(".")[1]) == 7, r1)
check("confirmed行状态converted", r1[8] == "converted")
r2 = by_id["2"]
check("歧义行四列留空", all(v is None for v in r2[4:8]))
check("歧义行状态missing", r2[8] == "missing")
r3 = by_id["3"]
check("manual补录生效", r3[4] == "108.200000" and r3[8] == "converted")
r5 = by_id["5"]
check("范围外行透传", r5[6] == "139.691700" and r5[8] == "out_of_scope_passthrough")
check("业务列/行序保留", [str(r[0]) for r in data] == ["1", "2", "3", "4", "5"])

# ---- 3. 字段名约束与冲突 ----
for name in ow.NEW_FIELDS:
    check(f"字段名合法 {name}", bool(ow.FIELD_RE.match(name)))
try:
    bad_rows = [{"序号": 1, "村落名称": "凤安村", "longitude_gcj02": "x"}]
    ow.build_table(bad_rows, {}, None, "gcj02")
    check("业务字段冲突报错", False, "未报错")
except ow.FieldNameError as e:
    check("业务字段冲突报错", "longitude_gcj02" in str(e))

# ---- 4-5. XLSX/CSV 写出 + 回读核对 ----
XLSX = os.path.join(TMP, "out.xlsx")
CSV = os.path.join(TMP, "out.csv")
ow.write_xlsx(XLSX, header, data)
ow.write_csv(CSV, header, data)
ver_x = ow.verify_output(XLSX, header, data)
check("XLSX回读核对通过", ver_x["ok"], "; ".join(ver_x["issues"]))
ver_c = ow.verify_output(CSV, header, data)
check("CSV回读核对通过", ver_c["ok"], "; ".join(ver_c["issues"]))
with open(CSV, "rb") as f:
    check("CSV带UTF-8 BOM", f.read(3) == b"\xef\xbb\xbf")
ws = ow._read_xlsx(XLSX)
check("XLSX表头逐字一致", [str(v) for v in ws[0]] == header)
coord_cells = [ws[i][j] for i in range(1, 6) for j in range(4, 8)]
check("XLSX坐标单元格为数值或空",
      all(v is None or isinstance(v, (float, int)) for v in coord_cells),
      str(coord_cells[:6]))
check("XLSX缺失行坐标单元格为空", ws[2][4] is None and ws[2][6] is None)
check("XLSX状态列非空", all(ws[i][8] in ct.VALID_STATUSES for i in range(1, 6)))
rows_c = ow._read_csv(CSV)
check("CSV行数与表头对齐", len(rows_c) == 6 and rows_c[0] == header)

# ---- 6. 表级转换失败：保留 GCJ-02、WGS84 留空 ----
orig = ct.gcj02_to_wgs84
ct.gcj02_to_wgs84 = lambda lng, lat, **kw: (_ for _ in ()).throw(
    ct.NotConvergedError("模拟未收敛"))
try:
    header2, data2, _ = ow.build_table(
        [{"序号": 1, "村落名称": "凤安村"}],
        {"r001": {"status": "confirmed",
                  "coordinate": {"lng": "108.100000", "lat": "34.300000"}}},
        None, "gcj02")
    # 行布局：序号,村落名称, gcj02_lng, gcj02_lat, wgs84_lng, wgs84_lat, status
    check("表级未收敛状态", data2[0][6] == "not_converged", str(data2[0]))
    check("表级未收敛保留GCJ02", data2[0][2] == "108.100000" and data2[0][3] == "34.300000")
    check("表级未收敛WGS84留空", data2[0][4] is None and data2[0][5] is None)
finally:
    ct.gcj02_to_wgs84 = orig

# ---- 7. 离线补列：旧表迁移 + 追加 ----
OLD = os.path.join(TMP, "old.xlsx")
NEW = os.path.join(TMP, "new.xlsx")
ow.write_xlsx(OLD, ["序号", "名录原文", "X(经度)", "Y(纬度)"],
              [[1, "1、凤安村（苏坊镇）", 108.100000, 34.300000],
               [2, "2、李家沟（自然村）", None, None]])
before = open(OLD, "rb").read()
rc = ow.offline_supplement(OLD, NEW)
check("离线补列返回0", rc == 0)
after = open(OLD, "rb").read()
check("输入文件未被覆盖", before == after)
new_rows = ow._read_xlsx(NEW)
check("离线表头：中文列迁移为英文",
      new_rows[0] == ["序号", "名录原文", "longitude_gcj02", "latitude_gcj02",
                      "longitude_wgs84", "latitude_wgs84", "conversion_status"],
      str(new_rows[0]))
check("离线行序/数量/业务列保留",
      len(new_rows) == 3 and new_rows[1][0] == 1 and new_rows[2][0] == 2
      and new_rows[1][1] == "1、凤安村（苏坊镇）")
check("离线GCJ02数值保留", new_rows[1][2] == 108.1 and new_rows[1][3] == 34.3)
check("离线WGS84为数值且状态converted",
      isinstance(new_rows[1][4], float) and new_rows[1][6] == "converted")
check("离线缺失行状态missing", new_rows[2][2] is None
      and new_rows[2][4] is None and new_rows[2][6] == "missing")
check("离线输出不残留中文坐标列", all("X(经度)" not in str(h) and "Y(纬度)" not in str(h)
      for h in new_rows[0]))

# ---- 8. 离线/写出全程不加载 amap_api（无网络、无额度）----
check("未导入amap_api模块", "amap_api" not in sys.modules)

# ---- 报告 ----
failed = 0
for name, ok, detail in CHECKS:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" — {detail}"))
    if not ok:
        failed += 1
print("ALL PASS" if failed == 0 else f"HAS {failed} FAILURE(S)")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if failed == 0 else 1)
