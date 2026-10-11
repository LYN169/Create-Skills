#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resolver.py — 按记录自动执行「首选接口 → 校验 → 条件补查/逆查」的查询衔接。

职责边界：
- 脚本：首选接口选择（可被 AI 覆盖）、候选过滤（县/名称/类型/粒度）、
  条件补查、筛选后逆查、状态判定、预算遵守、摘要生成。
- AI：输入解析（名称/行政上下文/地点类型/首选接口）、身份消歧、
  沿革证据、输入不足等例外。

规则要点（与 SKILL.md 一致）：
- 首选接口按地点类型：普通行政村→geocode；古街/遗址/建筑/明确景点→search。
  不对所有地点同时双查。
- geocode 只有 level=村庄 且县一致、地址链含地点名才算 confirmed；
  乡镇/区县级回退只能触发补查，不能作为村落坐标。
- search 候选先按县（adname）排除跨县项；字段缺失标未知，不当吻合。
  名称匹配：exact=核心名一致（允许村委会等机构后缀）；variant（去后缀含入）
  只能生成候选，不能自动确认。
- 逆查只对筛选后仍缺归属信息的候选（至多 2 个），不做前 N 条无差别逆查。
- 同名多候选、自然村与行政村、旧村与合并社区、村落与村委会不自动等同；
  逆查乡镇吻合也不能单独证明身份。
- 预算在每次请求尝试处原子执行；跨 batch/resolve 累计，不因新批次重置。
- 输出保留原始顺序与全部记录；失败/未确认行坐标留空，不填 0,0。
"""
import argparse
import concurrent.futures
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amap_api

# geocode 级别：村落只接受村庄级；POI 类对象接受非行政区划级别
VILLAGE_LEVELS = {"村庄"}
POI_OK_LEVELS = {"村庄", "门牌号", "道路", "住宅区", "公交地铁站点",
                 "公园广场", "风景名胜", "商务住宅", "科教文化服务", "通行设施"}
ADMIN_LEVELS = {"省", "市", "区县", "乡镇"}

# 状态：confirmed / ambiguous / need_evidence / not_found /
#       input_insufficient / interface_error / budget
PENDING_STATUSES = ("ambiguous", "need_evidence", "not_found", "input_insufficient")

_SUFFIXES = ("村民委员会", "村委会", "居民委员会", "居委会",
             "社区", "村", "镇", "乡", "街道", "组")

_STATIC_ADCODES = None


def _load_static_adcodes():
    """可选辅助资源：references 下的 adcode 表。缺项返回 None，不阻塞其他地区。"""
    global _STATIC_ADCODES
    if _STATIC_ADCODES is None:
        _STATIC_ADCODES = {}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "references", "shaanxi_adcodes.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for code, v in (data.get("counties") or {}).items():
                for name in [v.get("name")] + list(v.get("aliases") or []):
                    if name:
                        _STATIC_ADCODES.setdefault(str(name).strip(), code)
        except (OSError, ValueError):
            pass
    return _STATIC_ADCODES


def _strip_suffixes(s):
    s = str(s or "").strip()
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
                changed = True
                break
    return s


def _county_ok(cand_county, expect):
    """候选县 vs 期望县：True 吻合 / False 明确不符 / None 未知（字段缺失）。"""
    if not cand_county:
        return None
    c, e = str(cand_county).strip(), str(expect or "").strip()
    if not e:
        return None
    if c == e:
        return True
    for suf in ("区", "县", "市", "新区", "示范区"):
        if (c + suf) == e or c == (e + suf):
            return True
    return False


def _name_match(cand_name, rec_name):
    """exact：名称相等，或去掉机构后缀后核心名相等；
    variant：核心名互相含入（如“行家庄村东”、插字名）——只能生成候选，不能确认；
    None：不匹配。同音字/异体字（楞/塄、洼/坬）脚本无法判定，交 AI 沿革证据处理。"""
    cn, rn = str(cand_name or "").strip(), str(rec_name or "").strip()
    if not cn or not rn:
        return None
    if cn == rn:
        return "exact"
    ccn, crn = _strip_suffixes(cn), _strip_suffixes(rn)
    if ccn and crn and ccn == crn:
        return "exact"
    if ccn and crn and (ccn in crn or crn in ccn):
        return "variant"
    return None


def _cand(p, source):
    """候选摘要：只保留必要字段。"""
    return {
        "source": source,
        "name": p.get("name") or p.get("formatted_address"),
        "address": p.get("address"),
        "district": p.get("adname") or p.get("district"),
        "level": p.get("level") or p.get("type"),
        "id": p.get("id"),
        "location": p.get("location"),
        "match": p.get("_match"),
        "county_ok": p.get("_county_ok"),
    }


def _confirm(out, coord, source, note, matched=None):
    lng, _, lat = str(coord).partition(",")
    out["status"] = "confirmed"
    out["coordinate"] = {"lng": lng.strip(), "lat": lat.strip()}
    out["source"] = source
    out["note"] = note
    if matched:
        out["matched"] = _cand(matched, source)


def _regeo_township(lng, lat):
    r = amap_api.regeocode(lng, lat)
    return r.get("township"), r


def _fail_status(e):
    """预算类错误单独标记，其余为接口失败。"""
    return "budget" if getattr(e, "kind", None) == "budget" else "interface_error"


def _judge_geocode(result, rec, out):
    """geocode 结果校验 → confirmed / need_fallback / ambiguous / not_found。"""
    geos = result.get("geocodes") or []
    good, excluded = [], []
    for g in geos:
        cnt_ok = _county_ok(g.get("district"), rec.get("county"))
        g["_county_ok"] = cnt_ok
        # geocode 的确认信号：地址链以名录名结尾（回显链被截断/替换则不含），
        # 用 endswith 避免“北村”误配“西北村”这类含入误判
        fmt = str(g.get("formatted_address") or "")
        g["_match"] = "exact" if fmt.endswith(str(rec.get("name"))) else None
        if cnt_ok is False:
            excluded.append(g)
        elif g.get("level") in VILLAGE_LEVELS and g["_match"] == "exact":
            good.append(g)
    for g in excluded:
        out.setdefault("excluded", []).append(_cand(g, "geocode"))
    if len(good) == 1:
        g = good[0]
        gt = g.get("township")
        if isinstance(gt, list):
            gt = gt[0] if gt else None
        tw = str(rec.get("township") or "").strip()
        if tw:
            if gt == tw:
                _confirm(out, g["location"], "geocode",
                         "geocode 村庄级且县/名称/乡镇吻合", g)
                return "confirmed"
            if gt:  # 接口给了乡镇但与名录不符 → 直接歧义
                out["status"] = "ambiguous"
                out["reason"] = f"geocode 乡镇 {gt} 与名录 {tw} 不符，需人工消歧/沿革核实"
                return "ambiguous"
            # 乡镇字段缺失：回显链不可靠，必须逆查核实归属
            out["regeo_candidates"] = [g]
            out["reason"] = "geocode 村庄级但乡镇字段缺失，逆查核实归属"
            return "need_regeo"
        _confirm(out, g["location"], "geocode",
                 "geocode 村庄级且县/名称吻合（名录无乡镇信息）", g)
        return "confirmed"
    if len(good) > 1:
        out["candidates"] = [_cand(g, "geocode") for g in good]
        out["status"] = "ambiguous"
        out["reason"] = f"geocode 返回 {len(good)} 个同名村庄级候选，需人工消歧"
        return "ambiguous"
    # 未解析到村庄级（乡镇/区县回退或名称被丢弃）→ 用另一接口补查
    if geos:
        levels = {g.get("level") for g in geos}
        out["reason"] = f"geocode 未解析到村庄级（{sorted(levels)}），尝试搜索补查"
    else:
        out["reason"] = "geocode 无结果，尝试搜索补查"
    return "need_fallback"


def _judge_search(result, rec, out):
    """search 候选过滤 + 归属判断 → confirmed / need_regeo / ambiguous /
    need_evidence / not_found。"""
    pois = result.get("pois") or []
    strong, weak, excluded = [], [], []
    for p in pois:
        cnt_ok = _county_ok(p.get("adname"), rec.get("county"))
        p["_county_ok"] = cnt_ok
        p["_match"] = _name_match(p.get("name"), rec.get("name"))
        if cnt_ok is False:
            excluded.append(p)
        elif p["_match"] == "exact":
            strong.append(p)
        elif p["_match"] == "variant":
            weak.append(p)
    for p in excluded:
        out.setdefault("excluded", []).append(_cand(p, "search"))
    out.setdefault("candidates", []).extend(_cand(p, "search") for p in strong)
    out.setdefault("candidates", []).extend(_cand(p, "search") for p in weak)
    out["candidate_total"] = len(strong) + len(weak)

    tw = str(rec.get("township") or "").strip()
    if strong:
        if tw:
            in_tw = [p for p in strong if tw in str(p.get("address") or "")]
            if len(in_tw) == 1:
                _confirm(out, in_tw[0]["location"], "search",
                         "搜索候选地址含期望乡镇", in_tw[0])
                return "confirmed"
            if len(in_tw) > 1:
                out["status"] = "ambiguous"
                out["reason"] = f"多个候选地址含期望乡镇 {tw}，需人工消歧"
                return "ambiguous"
        if len(strong) == 1:
            p = strong[0]
            addr = str(p.get("address") or "")
            if (rec.get("county") and rec.get("county") in addr) or (tw and tw in addr):
                _confirm(out, p["location"], "search",
                         "搜索唯一候选且地址含县/乡镇", p)
                return "confirmed"
            if p.get("_county_ok") is True:
                out["regeo_candidates"] = [p]
                out["reason"] = "唯一候选，但地址缺归属信息，需逆查核实乡镇"
                return "need_regeo"
            out["status"] = "need_evidence"
            out["reason"] = "唯一候选但县级归属未知（字段缺失），需人工核实"
            return "need_evidence"
        # 多个同名候选：至多逆查 2 个核实乡镇
        if p.get("_county_ok") is not False and len(strong) <= 2:
            out["regeo_candidates"] = strong[:2]
            out["reason"] = f"{len(strong)} 个同名候选，逆查核实乡镇归属"
            return "need_regeo"
        out["status"] = "ambiguous"
        out["reason"] = f"{len(strong)} 个同名候选（{len(weak)} 个近似），需人工消歧"
        return "ambiguous"
    if weak:
        out["status"] = "need_evidence"
        out["reason"] = ("只有名称近似候选（去后缀变体），脚本不自动等同；"
                         "需沿革/人工证据")
        return "need_evidence"
    if excluded:
        out["status"] = "not_found"
        out["reason"] = f"无本县候选（{len(excluded)} 条跨县同名已排除）"
        return "not_found"
    out["status"] = "not_found"
    out["reason"] = "搜索无候选"
    return "not_found"


def _do_regeo(out, rec, source="search"):
    """对筛选后的候选（≤2 个）逆查；乡镇吻合唯一则确认，否则歧义/需证据。"""
    tw = str(rec.get("township") or "").strip()
    for p in out.get("regeo_candidates", []):
        loc = p.get("location")
        if not loc:
            p["_regeo"] = {"error": "无坐标"}
            continue
        lng, _, lat = str(loc).partition(",")
        try:
            ts, r = _regeo_township(lng.strip(), lat.strip())
        except amap_api.AmapError as e:
            out.update(status=_fail_status(e), reason=f"逆查: {e.kind} {e}")
            return _fail_status(e)
        p["_regeo"] = {"township": ts, "formatted": r.get("formatted_address")}
    cands = out.get("regeo_candidates", [])
    hit = [p for p in cands if p.get("_regeo", {}).get("township") == tw]
    if tw and len(hit) == 1:
        _confirm(out, hit[0]["location"], f"{source}+regeocode",
                 f"逆查乡镇 {tw} 与名录一致", hit[0])
        return "confirmed"
    if tw and len(hit) > 1:
        out["status"] = "ambiguous"
        out["reason"] = f"逆查后 {len(hit)} 个候选乡镇均为 {tw}，仍需人工消歧"
        return "ambiguous"
    out["status"] = "ambiguous"
    got = ", ".join(str(p.get("_regeo", {}).get("township")) for p in cands)
    out["reason"] = f"逆查乡镇（{got}）与名录 {tw or '未知'} 不符，需人工消歧/沿革核实"
    return "ambiguous"


def resolve(records, budget_cfg=None, max_workers=None):
    """records: [{id, name, province, city, county, township, kind, prefer?, adcode?, search_kw?}]
    kind: village(默认) | poi | natural_village | unknown
    prefer: geocode | search（缺省按 kind；AI 可覆盖）
    返回按输入顺序的 {id: outcome}。
    """
    amap_api.set_budget(budget_cfg or {})
    limiter = amap_api.get_limiter()
    adcache = {}
    lock = threading.Lock()
    _load_static_adcodes()

    def get_adcode(rec):
        key = (rec.get("province"), rec.get("city"), rec.get("county"))
        with lock:
            if key in adcache:
                return adcache[key]
        code = rec.get("adcode") or _STATIC_ADCODES.get(str(rec.get("county") or "").strip())
        if not code:
            r = amap_api.geocode(
                f"{rec.get('province','')}{rec.get('city','')}{rec.get('county','')}")
            code = (r.get("geocodes") or [{}])[0].get("adcode")
        with lock:
            adcache[key] = code
        return code

    def run_record(rec):
        rid = rec.get("id") or rec.get("name")
        amap_api._ctx.record_key = rid
        out = {"id": rid, "name": rec.get("name"),
               "province": rec.get("province"), "city": rec.get("city"),
               "county": rec.get("county"), "township": rec.get("township"),
               "status": "pending", "reason": "", "candidates": []}
        kind = rec.get("kind") or "village"
        prefer = rec.get("prefer") or ("search" if kind in ("poi", "natural_village") else "geocode")

        # ---- 首选接口 ----
        if prefer == "geocode":
            addr = "".join(str(x or "") for x in
                           (rec.get("province"), rec.get("city"), rec.get("county"),
                            rec.get("township"), rec.get("name")))
            try:
                result = amap_api.geocode(addr, rec.get("city"))
            except amap_api.AmapError as e:
                out.update(status=_fail_status(e), reason=f"geocode: {e.kind} {e}")
                return out
            st = _judge_geocode(result, rec, out)
            regeo_source = "geocode"
        else:
            try:
                code = get_adcode(rec)
            except amap_api.AmapError as e:
                out.update(status=_fail_status(e), reason=f"查码: {e.kind} {e}")
                return out
            if not code:
                out.update(status="input_insufficient",
                           reason="缺少县 adcode 且查码失败，无法县域限定搜索")
                return out
            kw = rec.get("search_kw") or rec.get("name")
            try:
                result = amap_api.search_poi(kw, code, True, 1, 10)
            except amap_api.AmapError as e:
                out.update(status=_fail_status(e), reason=f"search: {e.kind} {e}")
                return out
            st = _judge_search(result, rec, out)
            regeo_source = "search"

        # ---- 条件补查 ----
        if st == "need_fallback":
            try:
                code = get_adcode(rec)
            except amap_api.AmapError as e:
                out.update(status=_fail_status(e), reason=f"查码: {e.kind} {e}")
                return out
            if not code:
                out.update(status="input_insufficient",
                           reason="需搜索补查但缺少县 adcode 且查码失败")
                return out
            try:
                result = amap_api.search_poi(
                    rec.get("search_kw") or rec.get("name"), code, True, 1, 10)
            except amap_api.AmapError as e:
                out.update(status=_fail_status(e),
                           reason=f"补查 search: {e.kind} {e}")
                return out
            st = _judge_search(result, rec, out)
            regeo_source = "search"
        if st == "need_regeo":
            st = _do_regeo(out, rec, source=regeo_source)
        return out

    outcomes = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers or limiter.max_inflight
    ) as pool:
        futures = [pool.submit(run_record, r) for r in records]
        for rec, fut in zip(records, futures):
            outcomes[rec.get("id") or rec.get("name")] = fut.result()
    return outcomes


def summary(outcomes):
    """精简回传：计数 + 待 AI 处理记录（候选截断并注明总数）。"""
    counts = {}
    pending = []
    for rid, o in outcomes.items():
        counts[o["status"]] = counts.get(o["status"], 0) + 1
        if o["status"] in PENDING_STATUSES:
            item = {k: o.get(k) for k in
                    ("id", "name", "province", "city", "county", "township",
                     "status", "reason")}
            cands = o.get("candidates") or []
            item["candidates"] = cands[:3]
            item["candidate_total"] = o.get("candidate_total",
                                            o.get("candidates_total", len(cands)))
            if len(cands) > 3:
                item["candidates_truncated"] = True
            if o.get("excluded"):
                item["excluded_total"] = len(o["excluded"])
            pending.append(item)
    return {
        "input": len(outcomes),
        "confirmed": counts.get("confirmed", 0),
        "pending_ai": len(pending),
        "status_counts": counts,
        "usage": amap_api.usage.snapshot(),
        "budget": amap_api._budget_limits,
        "pending_records": pending,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="按记录自动解析（首选接口→校验→条件补查/逆查），AI 只处理歧义与证据")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--detail", default=None,
                        help="按记录编号输出完整详情（调试用，Key 不落盘）")
    args = parser.parse_args(argv)
    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records") if isinstance(data, dict) else data
    outcomes = resolve(records, data.get("budget") if isinstance(data, dict) else None)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"outcomes": outcomes, "summary": summary(outcomes)},
                  f, ensure_ascii=False, indent=2)
    if args.detail:
        print(json.dumps(outcomes.get(args.detail), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary(outcomes), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
