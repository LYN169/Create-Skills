#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_mock.py — 无 Key 验收场景检查器

用法（在 tests/scenario 目录下）：
    1. 执行者（AI）阅读 input.txt 与 mock_api.json，按 SKILL.md 规则产出 output.csv
    2. python run_mock.py   检查 output.csv 是否符合 expected.csv

输出格式为新标准五列（见 SKILL.md §8）：
    longitude_gcj02,latitude_gcj02,longitude_wgs84,latitude_wgs84,conversion_status

检查项对应五条验收标准：
    1. 同名村不跨县误配（凤安村：陷阱在眉县同名村排第一）
    2. 自然村不被上级行政村/村委会替代（李家沟：只有凤安村与村委会的坐标）
    3. 乡镇中心不冒充村落（王村：地理编码只返回 level=乡镇 的武功镇）
    4. 失败行保留为空行、不填 0,0、行数与顺序不变
    5. 县域候选搜索路径可用（营上村：地理编码无结果，须转县域搜索）
"""

import csv
import sys

EXPECTED = "expected.csv"
OUTPUT = "output.csv"

COORD_COLS = ("longitude_gcj02", "latitude_gcj02",
              "longitude_wgs84", "latitude_wgs84")
STATUS_COL = "conversion_status"
VALID_STATUSES = ("converted", "already_wgs84", "out_of_scope_passthrough",
                  "missing", "invalid", "not_converged", "unknown_source_crs")


def read_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def main():
    exp = read_rows(EXPECTED)
    try:
        out = read_rows(OUTPUT)
    except FileNotFoundError:
        print("FAIL: 未找到 output.csv")
        return 1

    checks = []
    checks.append(
        ("行数与输入一致（含表头，不删失败行）", len(out) == len(exp),
         f"期望 {len(exp)} 行，实际 {len(out)} 行")
    )
    if out and exp:
        checks.append(("表头为英文坐标字段", out[0] == exp[0],
                       f"期望 {exp[0]}，实际 {out[0]}"))
    for i, (e, o) in enumerate(zip(exp, out)):
        if i == 0:  # 表头
            continue
        if len(e) < 5 or len(o) < 5:
            checks.append((f"第 {i + 1} 行应含五列（4 坐标 + 状态）", False,
                           f"期望 {e}，实际 {o}"))
            continue
        egcj, ogcj = (e[0].strip(), e[1].strip()), (o[0].strip(), o[1].strip())
        ewgs, owgs = (e[2].strip(), e[3].strip()), (o[2].strip(), o[3].strip())
        estatus, ostatus = e[4].strip(), o[4].strip()
        if egcj == ("", ""):
            checks.append(
                (f"记录 {i}: 无法确认时四个坐标字段留空",
                 ogcj == ("", "") and owgs == ("", ""),
                 f"实际 gcj02={ogcj} wgs84={owgs}")
            )
            checks.append((f"记录 {i}: 留空行状态为 missing",
                           ostatus == "missing", f"实际 {ostatus}"))
        else:
            checks.append(
                (f"记录 {i}: GCJ-02 坐标匹配且顺序对应",
                 ogcj == egcj, f"期望 {egcj}，实际 {ogcj}")
            )
            checks.append(
                (f"记录 {i}: WGS84 坐标匹配（7 位小数）",
                 owgs == ewgs, f"期望 {ewgs}，实际 {owgs}")
            )
            checks.append((f"记录 {i}: 状态为合法值",
                           ostatus in VALID_STATUSES, f"实际 {ostatus}"))
        if ogcj == ("0", "0") or owgs == ("0", "0"):
            checks.append((f"记录 {i}: 不得用 0,0 占位", False, "坐标均为 0"))

    failed = 0
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}"
              + ("" if passed else f" — {detail}"))
        if not passed:
            failed += 1
    print("ALL PASS" if failed == 0 else f"HAS {failed} FAILURE(S)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
