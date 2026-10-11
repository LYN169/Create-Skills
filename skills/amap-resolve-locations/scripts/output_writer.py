#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
output_writer.py — 结果表写出：合并确认坐标 → 本地转换 → CSV/XLSX → 回读校验

职责
----
- 把 resolver 的 results.json（及 AI 定案的人工补录）按 rows.json 的行序合并，
  输出四个英文坐标字段 + conversion_status：
    longitude_gcj02, latitude_gcj02, longitude_wgs84, latitude_wgs84, conversion_status
- 转换由 scripts/coordinate_transform.py 本地完成（纯数值、无网络、无高德请求），
  不把整批坐标交给模型计算。
- 未确认（匹配失败/歧义/预算/接口错误）记录：四个坐标字段留空、
  conversion_status=missing，保留原行与行序。
- 转换失败（not_converged）：保留 GCJ-02 原始值，WGS84 两列留空。
- 默认另存新文件，不覆盖输入；与用户业务字段重名时报错，不悄悄覆盖。

新增字段名约束：只允许 ^[A-Za-z][A-Za-z0-9_]*$（无中文/括号/空格/连字符）。

写出规则
--------
- XLSX：坐标单元格写数值（float），不写带单位字符串；需要 openpyxl
  （可选依赖；CSV 流程纯标准库）。
- CSV：规范 csv 写出，十进制度数、小数点为点号；默认 UTF-8 BOM
  （可 --csv-encoding 覆盖）。
- GCJ-02 保留接口原值精度；WGS84 默认 7 位小数（小数位数不代表定位精度）。
- 写出后由程序重新读取核对：记录数、行序、字段名、坐标数值与缺失。

离线补列（--offline）
---------------------
对已有坐标表（如旧版 X(经度)/Y(纬度) 结果）本地补充两套坐标：
旧坐标列迁移为 longitude_gcj02/latitude_gcj02（新文件中不再保留中文坐标列），
追加 WGS84 两列与 conversion_status；其余业务列、行序、记录数保持不变；
全程不调用网络、不消耗高德额度。

用法
----
    # 主流程：rows.json + results.json → xlsx/csv
    python output_writer.py --rows rows.json --results results.json \
        --out result.xlsx [--out-csv result.csv] \
        [--manual manual.json] [--source-crs gcj02|wgs84]

    # 离线补列：旧表（X(经度)/Y(纬度) 或已有 gcj02 英文列）→ 新表
    python output_writer.py --offline --input-table old.xlsx --out new.xlsx \
        [--lng-col "X(经度)" --lat-col "Y(纬度)"] [--source-crs gcj02]
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coordinate_transform as ct  # noqa: E402

FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
NEW_FIELDS = ["longitude_gcj02", "latitude_gcj02",
              "longitude_wgs84", "latitude_wgs84", "conversion_status"]
COORD_FIELDS = list(ct.COORD_FIELDS)

# 旧版/常见中文坐标列名（离线补列自动识别时用）
LEGACY_LNG_NAMES = ("X(经度)", "经度", "longitude_gcj02", "lng", "longitude")
LEGACY_LAT_NAMES = ("Y(纬度)", "纬度", "latitude_gcj02", "lat", "latitude")


class FieldNameError(ValueError):
    """新增字段名不符合英文命名约束或与用户字段冲突。"""


def _check_new_fields(business_cols):
    for name in NEW_FIELDS:
        if not FIELD_RE.match(name):
            raise FieldNameError(f"新增字段名 {name!r} 不符合 ^[A-Za-z][A-Za-z0-9_]*$")
    clash = [c for c in business_cols if c in NEW_FIELDS]
    if clash:
        raise FieldNameError(
            f"输入表已有与坐标输出同名的列 {clash}；请先在输入表中改名/删除，"
            "避免悄悄覆盖无关数据")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _row_id(row):
    if "id" in row:
        return str(row["id"])
    if "序号" in row:
        return f"r{int(row['序号']):03d}"
    raise ValueError("rows.json 每行需含 id 或 序号（用作与 results.json 对齐的键）")


def _coord_of(row_id, outcomes, manual):
    """取已确认坐标：manual（AI 定案）优先，其次 results 中 confirmed 记录。

    只有 status=confirmed 且两值齐全才算有坐标；候选/歧义/失败一律 None。
    """
    m = (manual or {}).get(row_id)
    if m:
        lng, lat = m.get("lng"), m.get("lat")
        if lng is not None and lat is not None:
            return str(lng), str(lat), "manual"
    o = outcomes.get(row_id)
    if o and o.get("status") == "confirmed" and o.get("coordinate"):
        c = o["coordinate"]
        if c.get("lng") not in (None, "") and c.get("lat") not in (None, ""):
            return str(c["lng"]), str(c["lat"]), "confirmed"
    return None, None, None


def build_table(rows, outcomes, manual=None, source_crs="gcj02"):
    """rows: [{...业务字段..., "id" 或 "序号"}]
    outcomes: results.json 的 outcomes
    返回 (header, data, stats)。data 行为 list，与 header 对齐。
    """
    header = [k for k in rows[0] if k != "id"]
    _check_new_fields(header)
    data, match_counts, conv_results = [], {}, []
    missing_rows = []
    for row in rows:
        rid = _row_id(row)
        lng, lat, where = _coord_of(rid, outcomes, manual)
        match_counts[where if where else
                     (outcomes.get(rid, {}).get("status") or "missing")] = \
            match_counts.get(where if where else
                             (outcomes.get(rid, {}).get("status") or "missing"), 0) + 1
        conv = ct.convert(lng, lat, source_crs) if lng else \
            ct.convert(None, None, source_crs)
        conv_results.append(conv)
        if conv["conversion_status"] == "missing":
            missing_rows.append(rid)
        rec = [row.get(k) for k in header] + [
            conv["longitude_gcj02"], conv["latitude_gcj02"],
            conv["longitude_wgs84"], conv["latitude_wgs84"],
            conv["conversion_status"]]
        data.append(rec)
    header = header + NEW_FIELDS
    stats = {
        "total": len(rows),
        "match_counts": match_counts,
        "conversion_counts": ct.status_counts(conv_results),
        "missing_ids": missing_rows[:20],
        "missing_total": len(missing_rows),
    }
    return header, data, stats


# ---- 写出 ----

def _num(v):
    if v is None or v == "":
        return None
    return float(v)


def write_xlsx(path, header, data):
    try:
        from openpyxl import Workbook
    except ImportError as e:
        raise RuntimeError("XLSX 输出需要 openpyxl（pip install openpyxl）；"
                           "或改用 --out-csv 输出 CSV") from e
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    coord_idx = {name: i for i, name in enumerate(header) if name in COORD_FIELDS}
    for rec in data:
        row = list(rec)
        for i in coord_idx.values():
            row[i] = _num(row[i])  # 数值单元格，空值 → 空单元格
        ws.append(row)
    wb.save(path)


def write_csv(path, header, data, encoding="utf-8-sig"):
    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for rec in data:
            w.writerow(["" if v is None else v for v in rec])


def _read_xlsx(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True).active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.reader(f)]


def verify_output(path, header, data, key_idx=0):
    """回读核对：记录数、行序（首个业务列作键）、字段名、坐标单元格数值/缺失。"""
    issues = []
    rows = _read_xlsx(path) if path.lower().endswith(".xlsx") else _read_csv(path)
    if len(rows) != len(data) + 1:
        issues.append(f"行数不符：期望 {len(data) + 1}（含表头），实际 {len(rows)}")
        return {"ok": False, "issues": issues}
    if [str(v) if v is not None else "" for v in rows[0]] != header:
        issues.append(f"表头不符：期望 {header}，实际 {rows[0]}")
    key = [str(r[key_idx]) for r in rows[1:]]
    expected = [str(r[key_idx]) for r in data]
    if key != expected:
        issues.append(f"行序不符：第 {next((i for i, (a, b) in enumerate(zip(key, expected)) if a != b), -1) + 1} 行起不一致")
    n_nonempty = 0
    seen, dup_points = {}, []
    for i, r in enumerate(rows[1:], 1):
        for j, name in enumerate(header):
            if name in COORD_FIELDS and r[j] not in (None, ""):
                try:
                    float(r[j])
                    n_nonempty += 1
                except (TypeError, ValueError):
                    issues.append(f"第 {i} 行 {name} 单元格不是数值：{r[j]!r}")
        # 不同记录返回同一点的异常检查（警告级，不判失败——同点也可能合法）
        lng_i = header.index("longitude_gcj02") if "longitude_gcj02" in header else None
        lat_i = header.index("latitude_gcj02") if "latitude_gcj02" in header else None
        if lng_i is not None and r[lng_i] not in (None, "") and r[lat_i] not in (None, ""):
            pt = (str(r[lng_i]), str(r[lat_i]))
            if pt in seen:
                dup_points.append(f"第 {seen[pt]} 行与第 {i} 行 GCJ-02 坐标相同 {pt}")
            else:
                seen[pt] = i
    warnings = []
    if dup_points:
        warnings.append("重复点异常：" + "；".join(dup_points[:5]))
    return {"ok": not issues, "issues": issues, "warnings": warnings,
            "rows_read": len(rows) - 1, "coord_cells": n_nonempty}


def _write_outputs(out_path, out_csv, header, data, csv_encoding):
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".xlsx":
        write_xlsx(out_path, header, data)
    elif ext == ".csv":
        write_csv(out_path, header, data, csv_encoding)
    else:
        raise ValueError("--out 扩展名需为 .xlsx 或 .csv")
    if out_csv:
        write_csv(out_csv, header, data, csv_encoding)
    return verify_output(out_path, header, data)


def _summary_text(out_paths, stats, verifications):
    lines = [f"输出: {', '.join(out_paths)}",
             f"总记录数: {stats['total']}",
             "匹配状态: " + ", ".join(f"{k}={v}" for k, v in
                                      sorted(stats["match_counts"].items())),
             "转换状态: " + ", ".join(f"{k}={v}" for k, v in
                                      sorted(stats["conversion_counts"].items()))]
    for path, ver in verifications:
        lines.append(f"验证({os.path.basename(path)}): "
                     + ("通过（记录数/行序/字段名/坐标数值核对一致）" if ver["ok"]
                        else "; ".join(ver["issues"])))
    for path, ver in verifications:
        for w in ver.get("warnings", []):
            lines.append(f"  注意: {w}")
    if stats["missing_total"]:
        lines.append(f"未确认记录（坐标留空）: {stats['missing_total']} 条，"
                     f"如 {', '.join(stats['missing_ids'])}"
                     + ("…" if stats["missing_total"] > len(stats["missing_ids"]) else ""))
    return "\n".join(lines)


# ---- 离线补列 ----

def _find_coord_cols(header, lng_col, lat_col):
    if lng_col and lat_col:
        if lng_col not in header or lat_col not in header:
            raise ValueError(f"--lng-col/--lat-col 不存在于输入表：{lng_col},{lat_col}")
        return header.index(lng_col), header.index(lat_col)
    for a, b in zip(LEGACY_LNG_NAMES, LEGACY_LAT_NAMES):
        if a in header and b in header:
            return header.index(a), header.index(b)
    raise ValueError("未指定坐标列，且自动识别失败；请用 --lng-col/--lat-col 指定")


def offline_supplement(input_path, out_path, lng_col=None, lat_col=None,
                       source_crs="gcj02", csv_encoding="utf-8-sig"):
    """已有坐标表离线补列：迁移旧坐标列 + 追加 WGS84 与转换状态。"""
    if os.path.abspath(input_path) == os.path.abspath(out_path):
        raise ValueError("--out 不得覆盖输入文件；请另存新文件")
    if input_path.lower().endswith(".xlsx"):
        rows = _read_xlsx(input_path)
    else:
        rows = _read_csv(input_path)
    header = [str(h).strip() for h in rows[0]]
    li, lai = _find_coord_cols(header, lng_col, lat_col)
    # 冲突检查：已有英文坐标列/状态列不得悄悄覆盖
    for name in ("longitude_wgs84", "latitude_wgs84", "conversion_status"):
        if name in header:
            raise FieldNameError(f"输入表已有列 {name}；请先处理，避免覆盖无关数据")
    # 迁移：旧坐标列 → 英文 gcj02 列（中文列名不再保留；本身已是英文名则不动）
    new_header = list(header)
    new_header[li] = "longitude_gcj02"
    new_header[lai] = "latitude_gcj02"
    out_header = new_header + ["longitude_wgs84", "latitude_wgs84", "conversion_status"]
    data, conv_results, bad_rows = [], [], []
    for i, r in enumerate(rows[1:], 1):
        conv = ct.convert(r[li], r[lai], source_crs)
        conv_results.append(conv)
        if conv["conversion_status"] in ("invalid", "not_converged",
                                         "out_of_scope_passthrough",
                                         "unknown_source_crs"):
            bad_rows.append((i, conv["conversion_status"], conv.get("detail")))
        base = [r[j] for j in range(len(header))]
        base[li], base[lai] = conv["longitude_gcj02"], conv["latitude_gcj02"]
        data.append(base + [conv["longitude_wgs84"], conv["latitude_wgs84"],
                            conv["conversion_status"]])
    stats = {"total": len(data),
             "conversion_counts": ct.status_counts(conv_results),
             "match_counts": {"offline": len(data)},
             "missing_ids": [], "missing_total": 0}
    ver = _write_outputs(out_path, None, out_header, data, csv_encoding)
    print(_summary_text([out_path], stats, [(out_path, ver)]))
    for i, st, dt in bad_rows[:10]:
        print(f"  注意 第{i}行: {st} — {dt}")
    return 0


# ---- 主流程 ----

def main(argv=None):
    ap = argparse.ArgumentParser(description="结果表写出与离线补列（坐标转换本地完成，无网络）")
    ap.add_argument("--rows", help="rows.json：输入对齐表（含 id 或 序号）")
    ap.add_argument("--results", help="results.json：resolver 输出")
    ap.add_argument("--manual", help="manual.json：AI 定案补录 {id: {lng, lat}}")
    ap.add_argument("--out", help="输出文件（.xlsx/.csv）")
    ap.add_argument("--out-csv", default=None, help="额外输出 CSV 副本")
    ap.add_argument("--source-crs", default="gcj02", choices=["gcj02", "wgs84"],
                    help="源坐标系（默认 gcj02；wgs84 表示输入已是 WGS84，不重复转换）")
    ap.add_argument("--csv-encoding", default="utf-8-sig",
                    help="CSV 编码（默认 utf-8-sig 带 BOM）")
    ap.add_argument("--offline", action="store_true",
                    help="离线补列模式（对已有坐标表补充两套坐标，不调用网络）")
    ap.add_argument("--input-table", help="离线模式输入表（.xlsx/.csv）")
    ap.add_argument("--lng-col", default=None, help="离线模式经度列名")
    ap.add_argument("--lat-col", default=None, help="离线模式纬度列名")
    args = ap.parse_args(argv)

    if args.offline:
        if not (args.input_table and args.out):
            ap.error("--offline 需要 --input-table 与 --out")
        return offline_supplement(args.input_table, args.out,
                                  args.lng_col, args.lat_col,
                                  args.source_crs, args.csv_encoding)
    if not (args.rows and args.results and args.out):
        ap.error("需要 --rows、--results、--out（离线模式用 --offline）")
    rows = load_json(args.rows)
    res = load_json(args.results)
    outcomes = res.get("outcomes", res)
    manual = load_json(args.manual) if args.manual else None
    header, data, stats = build_table(rows, outcomes, manual, args.source_crs)
    ver = _write_outputs(args.out, args.out_csv, header, data, args.csv_encoding)
    out_paths = [p for p in (args.out, args.out_csv) if p]
    print(_summary_text(out_paths, stats, [(args.out, ver)]))
    return 0 if ver["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
