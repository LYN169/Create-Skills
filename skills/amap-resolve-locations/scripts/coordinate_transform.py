#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coordinate_transform.py — GCJ-02 ↔ WGS84 本地确定性转换（无网络、纯标准库）

算法来源与许可证
----------------
- 正向公式（WGS84→GCJ-02）：公开逆向推导的 GCJ-02 偏移公式，参数
  a=6378245.0、ee=0.00669342162296594323，与开源项目
  wandergis/coordtransform（MIT License）及 googollee/eviltransform
  （MIT License）的实现一致。本项目按公式重新实现，仅取数学表达式，
  不含上述项目源码。
- 逆向（GCJ-02→WGS84）：残差迭代反算——以输入 GCJ-02 为初值，把估计的
  WGS84 代入正向公式，用与输入 GCJ-02 的经纬度残差修正估计值，直至收敛
  （默认：经纬度最大绝对残差 ≤1e-7 度、最多 30 次迭代）。
- 本实现**不是高德官方逆变换**；迭代收敛只证明所选公式的数值闭合，
  不代表真实地面定位精度。地理编码代表点误差不会因转换而消失。

适用范围
--------
- 使用常见矩形范围（中国内地粗界）：lng∈[72.004,137.8347]、lat∈[0.8293,55.8271]。
  该矩形**不是精确国界**（不含港澳台等无偏移区域，个别边境点可能误判）。
- 范围外默认不施加偏移、原值透传，状态标 out_of_scope_passthrough。

状态定义（conversion_status）
------------------------------
converted / already_wgs84 / out_of_scope_passthrough /
missing / invalid / not_converged / unknown_source_crs
"""
import json
import math
import sys

# ---- 正向公式参数（公开逆向推导，见模块 docstring）----
_A = 6378245.0
_EE = 0.00669342162296594323

# 适用范围矩形（lng_min, lng_max, lat_min, lat_max；非精确国界）
CHINA_RECT = (72.004, 137.8347, 0.8293, 55.8271)

# 迭代反算参数
CONV_THRESHOLD = 1e-7   # 经纬度最大绝对残差（度）
MAX_ITER = 30

# WGS84 写出小数位（小数位数不代表定位精度）
WGS84_DECIMALS = 7

VALID_STATUSES = (
    "converted",
    "already_wgs84",
    "out_of_scope_passthrough",
    "missing",
    "invalid",
    "not_converged",
    "unknown_source_crs",
)

# 四个坐标输出字段（英文名，只允许 ^[A-Za-z][A-Za-z0-9_]*$）
COORD_FIELDS = ("longitude_gcj02", "latitude_gcj02",
                "longitude_wgs84", "latitude_wgs84")

_PI = math.pi


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y \
        + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y \
        + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng, lat):
    """正向：WGS84 → GCJ-02（纯数学公式，不做范围判断）。"""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1.0 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng, lat, threshold=CONV_THRESHOLD, max_iter=MAX_ITER):
    """逆向：GCJ-02 → WGS84，残差迭代反算。

    收敛判定：正向回代的经纬度最大绝对残差 ≤ threshold（度）。
    未收敛抛 NotConvergedError。返回值保留完整浮点精度。
    """
    est_lng, est_lat = float(lng), float(lat)
    for _ in range(max(0, int(max_iter))):
        f_lng, f_lat = wgs84_to_gcj02(est_lng, est_lat)
        res_lng = est_lng + (float(lng) - f_lng)
        res_lat = est_lat + (float(lat) - f_lat)
        err = max(abs(res_lng - est_lng), abs(res_lat - est_lat))
        est_lng, est_lat = res_lng, res_lat
        if err <= threshold:
            return est_lng, est_lat
    raise NotConvergedError(
        f"GCJ-02 反算未收敛（阈值 {threshold:g} 度 / {max_iter} 次迭代）")


class NotConvergedError(Exception):
    """残差迭代未在迭代上限内收敛。"""


def in_china_rect(lng, lat):
    """常见矩形范围判断（非精确国界，见模块 docstring）。"""
    lng_min, lng_max, lat_min, lat_max = CHINA_RECT
    return lng_min <= lng <= lng_max and lat_min <= lat <= lat_max


def _to_num(v):
    """None/空串 → None；数值字符串 → float；不可解析抛 ValueError。"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        return float(s)
    return float(v)


def validate_coord(lng, lat):
    """坐标完整性校验。返回 (lng_num, lat_num, error)。

    拒绝：单边缺失、空值、NaN、Infinity、非数值、超出经纬度定义域
    （lng∈[-180,180]、lat∈[-90,90]）。
    """
    try:
        ln, la = _to_num(lng), _to_num(lat)
    except (TypeError, ValueError):
        return None, None, "坐标不是有效数值"
    if ln is None and la is None:
        return None, None, None  # 双侧缺失 → 上层判 missing
    if ln is None or la is None:
        return None, None, "坐标单边缺失"
    if not (math.isfinite(ln) and math.isfinite(la)):
        return None, None, "坐标含 NaN/Infinity"
    if not (-180.0 <= ln <= 180.0 and -90.0 <= la <= 90.0):
        return None, None, "坐标超出经纬度定义域"
    return ln, la, None


def _raw_str(v):
    """保留输入原始精度：字符串原样；浮点取 repr 往返精度。"""
    if isinstance(v, str):
        return v
    return repr(float(v))


def convert(lng, lat, source_crs="gcj02",
            threshold=CONV_THRESHOLD, max_iter=MAX_ITER):
    """单条坐标转换。

    参数：
        lng, lat  输入坐标（str/float/None），经度在前。
        source_crs  源坐标系：'gcj02'（默认，高德接口原值）
                    / 'wgs84' / 其他值 → unknown_source_crs。
    返回 dict：
        longitude_gcj02 / latitude_gcj02   原始 GCJ-02 值（原精度字符串；缺失/无效为 None）
        longitude_wgs84 / latitude_wgs84   转换结果（7 位小数字符串；未转换/失败为 None）
        conversion_status                  见模块 docstring
        detail                             简短原因（无异常为 None）
    """
    out = {"longitude_gcj02": None, "latitude_gcj02": None,
           "longitude_wgs84": None, "latitude_wgs84": None,
           "conversion_status": None, "detail": None}
    if source_crs not in ("gcj02", "wgs84"):
        out["conversion_status"] = "unknown_source_crs"
        out["detail"] = f"无法确认输入坐标系（source_crs={source_crs!r}），未写入任何坐标列"
        return out
    ln, la, err = validate_coord(lng, lat)
    if err is None and ln is None and la is None:
        out["conversion_status"] = "missing"
        out["detail"] = "没有可输出的已确认坐标"
        return out
    if err is not None:
        out["conversion_status"] = "invalid"
        out["detail"] = err
        return out
    if source_crs == "wgs84":
        # 已声明为 WGS84：不执行 GCJ-02 反算，原值放入 WGS84 列
        out["longitude_wgs84"] = _raw_str(lng)
        out["latitude_wgs84"] = _raw_str(lat)
        out["conversion_status"] = "already_wgs84"
        out["detail"] = "输入已为 WGS84，未重复转换"
        return out
    # source_crs == "gcj02"
    out["longitude_gcj02"] = _raw_str(lng)
    out["latitude_gcj02"] = _raw_str(lat)
    if not in_china_rect(ln, la):
        # 适用范围外：不施加偏移、原值透传，不标为正常转换成功
        out["longitude_wgs84"] = _raw_str(lng)
        out["latitude_wgs84"] = _raw_str(lat)
        out["conversion_status"] = "out_of_scope_passthrough"
        out["detail"] = ("位于适用矩形范围外（该矩形非精确国界），"
                         "未施加偏移，原值透传")
        return out
    try:
        w_lng, w_lat = gcj02_to_wgs84(ln, la, threshold=threshold, max_iter=max_iter)
    except NotConvergedError as e:
        out["conversion_status"] = "not_converged"
        out["detail"] = str(e)
        return out
    out["longitude_wgs84"] = f"{w_lng:.{WGS84_DECIMALS}f}"
    out["latitude_wgs84"] = f"{w_lat:.{WGS84_DECIMALS}f}"
    out["conversion_status"] = "converted"
    return out


def status_counts(results):
    """转换结果列表 → 状态计数。"""
    counts = {}
    for r in results:
        s = r.get("conversion_status") or "missing"
        counts[s] = counts.get(s, 0) + 1
    return counts


def _self_test():
    """本地自检：参考样例 + 回代残差（不访问网络）。"""
    import traceback
    checks = []
    # 参考样例 1：wandergis/coordtransform README 示例（MIT 项目公开示例）
    # wgs84(116.404,39.915) → gcj02(116.41024449916938,39.91640428150164)
    f = wgs84_to_gcj02(116.404, 39.915)
    checks.append(("参考样例1-正向(coordtransform README)",
                   abs(f[0] - 116.41024449916938) < 1e-9 and
                   abs(f[1] - 39.91640428150164) < 1e-9))
    # 参考样例 1b：同一 README 的 gcj02towgs84(116.404,39.915)
    # → (116.39775550083061, 39.91359571849836)
    # 注意：该库逆向为“一步近似”(2x-forward(x))；本实现做残差迭代精修
    # 二阶项（差异约 5e-7 度 ≈ 厘米级），故容差取 1e-6 度。
    i = gcj02_to_wgs84(116.404, 39.915)
    checks.append(("参考样例1b-逆向(coordtransform README一步近似)",
                   abs(i[0] - 116.39775550083061) < 1e-6 and
                   abs(i[1] - 39.91359571849836) < 1e-6,
                   f"diff=({i[0]-116.39775550083061:g},{i[1]-39.91359571849836:g})"))
    # 参考样例 2：mapchaxun.cn WGS84↔GCJ02 对照（6 位小数）
    # wgs84(116.391275,39.907201) → gcj02(116.397516,39.908602)
    f2 = wgs84_to_gcj02(116.391275, 39.907201)
    checks.append(("参考样例2-正向(mapchaxun.cn)",
                   abs(f2[0] - 116.397516) < 1e-6 and
                   abs(f2[1] - 39.908602) < 1e-6))
    # 回代残差：中国大陆多点
    for name, gcj in [("北京", (116.397428, 39.909230)),
                      ("上海", (121.473701, 31.230416)),
                      ("西安", (108.940174, 34.341568)),
                      ("成都", (104.066541, 30.572269)),
                      ("广州", (113.264385, 23.129112)),
                      ("哈尔滨", (126.534967, 45.803775)),
                      ("拉萨", (91.140856, 29.645554)),
                      ("乌鲁木齐", (87.616848, 43.825592))]:
        try:
            w = gcj02_to_wgs84(*gcj)
            back = wgs84_to_gcj02(*w)
            err = max(abs(back[0] - gcj[0]), abs(back[1] - gcj[1]))
            checks.append((f"回代残差-{name}", err <= 1e-7, f"err={err:g}"))
        except Exception:
            checks.append((f"回代残差-{name}", False, traceback.format_exc(limit=1)))
    # 范围外透传
    r = convert(139.6917, 35.6895, "gcj02")
    checks.append(("范围外透传(东京)", r["conversion_status"] == "out_of_scope_passthrough"
                   and r["longitude_wgs84"] == "139.6917"))
    ok = all(p for _, p, *_ in checks)
    for name, passed, *rest in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}"
              + ("" if passed else f" — {rest[0] if rest else ''}"))
    print("ALL PASS" if ok else "HAS FAILURE(S)")
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    if "--lng" in argv and "--lat" in argv:
        lng = argv[argv.index("--lng") + 1]
        lat = argv[argv.index("--lat") + 1]
        crs = "gcj02"
        if "--source-crs" in argv:
            crs = argv[argv.index("--source-crs") + 1]
        print(json.dumps(convert(lng, lat, crs), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
