#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_coordinate_transform.py — 坐标转换本地测试（无网络、无高德请求）

运行：cd <skill根目录> && python tests/test_coordinate_transform.py
覆盖：
  1. 有来源的独立参考样例（wandergis/coordtransform README、mapchaxun.cn 对照页）
  2. 中国大陆多点正向回代残差（残差 ≤1e-7 度）
  3. 空值/非法数值/定义域/单边缺失
  4. 范围外透传（out_of_scope_passthrough，不标为转换成功）
  5. 未收敛（not_converged）：GCJ-02 保留、WGS84 留空
  6. already_wgs84 不重复转换
  7. 原始 GCJ-02 字符串不被反算覆盖
  8. unknown_source_crs 不猜测
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import coordinate_transform as ct  # noqa: E402

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def approx(a, b, tol):
    return abs(a - b) <= tol


# ---- 1. 独立参考样例（来源注明）----
# 样例 A：wandergis/coordtransform（MIT）README 公开示例
#   wgs84(116.404, 39.915) → gcj02(116.41024449916938, 39.91640428150164)
f = ct.wgs84_to_gcj02(116.404, 39.915)
check("参考样例A-正向(coordtransform README)",
      approx(f[0], 116.41024449916938, 1e-9) and approx(f[1], 39.91640428150164, 1e-9),
      f"got {f}")
# 同一 README 的 gcj02towgs84(116.404,39.915) 为“一步近似”值
# (116.39775550083061, 39.91359571849836)；本实现迭代精修二阶项，
# 差异约 5e-7 度（厘米级），容差 1e-6。
i = ct.gcj02_to_wgs84(116.404, 39.915)
d = (i[0] - 116.39775550083061, i[1] - 39.91359571849836)
check("参考样例A-逆向(一步近似值, 容差1e-6)",
      abs(d[0]) < 1e-6 and abs(d[1]) < 1e-6, f"diff={d}")
# 样例 B：mapchaxun.cn WGS84↔GCJ02 对照页（https://www.mapchaxun.cn/wgs84-gcj02）
#   wgs84(116.391275, 39.907201) → gcj02(116.397516, 39.908602)
f2 = ct.wgs84_to_gcj02(116.391275, 39.907201)
check("参考样例B-正向(mapchaxun.cn)",
      approx(f2[0], 116.397516, 1e-6) and approx(f2[1], 39.908602, 1e-6),
      f"got {f2}")
# 回代通过本身不能证明真实位置精度：迭代阈值只衡量所选公式的数值收敛。

# ---- 2. 中国大陆多点：转换 + 正向回代残差 ----
for name, gcj in [("北京", (116.397428, 39.909230)),
                  ("上海", (121.473701, 31.230416)),
                  ("西安", (108.940174, 34.341568)),
                  ("成都", (104.066541, 30.572269)),
                  ("广州", (113.264385, 23.129112)),
                  ("哈尔滨", (126.534967, 45.803775)),
                  ("拉萨", (91.140856, 29.645554)),
                  ("乌鲁木齐", (87.616848, 43.825592))]:
    w = ct.gcj02_to_wgs84(*gcj)
    back = ct.wgs84_to_gcj02(*w)
    err = max(abs(back[0] - gcj[0]), abs(back[1] - gcj[1]))
    check(f"回代残差≤1e-7 {name}", err <= 1e-7, f"err={err:g}")

# ---- 3. 空值 / 非法数值 / 定义域 / 单边缺失 ----
r = ct.convert(None, None)
check("空值(None,None)→missing", r["conversion_status"] == "missing")
check("空值四列全空", all(r[k] is None for k in ct.COORD_FIELDS))
r = ct.convert("", "")
check("空串→missing", r["conversion_status"] == "missing")
r = ct.convert("abc", "34.3")
check("非数值→invalid", r["conversion_status"] == "invalid")
r = ct.convert("116.4", "")
check("单边缺失→invalid", r["conversion_status"] == "invalid")
r = ct.convert(float("nan"), 34.3)
check("NaN→invalid", r["conversion_status"] == "invalid")
r = ct.convert(float("inf"), 34.3)
check("Infinity→invalid", r["conversion_status"] == "invalid")
r = ct.convert(200.0, 34.3)
check("经度200→invalid", r["conversion_status"] == "invalid")
r = ct.convert(116.4, 95.0)
check("纬度95→invalid", r["conversion_status"] == "invalid")
r = ct.convert(-200.0, 34.3)
check("经度-200→invalid", r["conversion_status"] == "invalid")

# ---- 4. 范围外透传 ----
r = ct.convert("139.691700", "35.689500")  # 东京（矩形外）
check("范围外→out_of_scope_passthrough", r["conversion_status"] == "out_of_scope_passthrough")
check("范围外原值透传", r["longitude_wgs84"] == "139.691700"
      and r["latitude_wgs84"] == "35.689500")
check("范围外不被标为converted", r["conversion_status"] != "converted")
r = ct.convert("2.352200", "48.856600")  # 巴黎
check("范围外(巴黎)→out_of_scope_passthrough",
      r["conversion_status"] == "out_of_scope_passthrough")

# ---- 5. 未收敛：GCJ-02 保留、WGS84 留空 ----
r = ct.convert("116.397428", "39.909230", max_iter=0)
check("未收敛→not_converged", r["conversion_status"] == "not_converged")
check("未收敛保留GCJ02原值", r["longitude_gcj02"] == "116.397428"
      and r["latitude_gcj02"] == "39.909230")
check("未收敛WGS84留空", r["longitude_wgs84"] is None and r["latitude_wgs84"] is None)

# ---- 6. already_wgs84 不重复转换 ----
r = ct.convert("116.404", "39.915", source_crs="wgs84")
check("already_wgs84状态", r["conversion_status"] == "already_wgs84")
check("WGS84列取原值", r["longitude_wgs84"] == "116.404"
      and r["latitude_wgs84"] == "39.915")
check("GCJ02列留空(不误标)", r["longitude_gcj02"] is None
      and r["latitude_gcj02"] is None)

# ---- 7. 原始 GCJ-02 字符串不被反算覆盖 ----
r = ct.convert("116.41024449916938", "39.91640428150164")
check("GCJ02列与原输入逐字一致", r["longitude_gcj02"] == "116.41024449916938"
      and r["latitude_gcj02"] == "39.91640428150164")
check("正常转换状态converted", r["conversion_status"] == "converted")
check("WGS84默认7位小数", (len(r["longitude_wgs84"].split(".")[1]) == 7
      and len(r["latitude_wgs84"].split(".")[1]) == 7), r)
r = ct.convert("108.132600", "34.336400")
check("GCJ02原始精度保留(尾零不丢)", r["longitude_gcj02"] == "108.132600"
      and r["latitude_gcj02"] == "34.336400")

# ---- 8. unknown_source_crs ----
r = ct.convert("116.404", "39.915", source_crs="bd09")
check("未知源坐标系→unknown_source_crs", r["conversion_status"] == "unknown_source_crs")
check("未知源坐标系四列全空", all(r[k] is None for k in ct.COORD_FIELDS))

# ---- 报告 ----
failed = 0
for name, ok, detail in CHECKS:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" — {detail}"))
    if not ok:
        failed += 1
print("ALL PASS" if failed == 0 else f"HAS {failed} FAILURE(S)")
sys.exit(0 if failed == 0 else 1)
