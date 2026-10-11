#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
amap_api.py — 高德 Web 服务 API 最小调用工具
（地理编码 geocode / POI 关键字搜索 search / 逆地理编码 regeocode / 批量 batch）

职责边界：只负责请求、限速、瞬时错误重试、错误分类与坐标校验。
查询策略、名称消歧、结果确认由调用方（AI）按 SKILL.md 规则决策，本脚本不做判断。

用法：
    python amap_api.py geocode --address "陕西省咸阳市武功县苏坊镇凤安村" --city "咸阳市"
    python amap_api.py search --keywords "凤安村" --city 610431 --page 1 --offset 10
    python amap_api.py regeocode --lng 108.1326 --lat 34.3364
    python amap_api.py batch --input plan.json --output results.json

Key 读取顺序（优先级从高到低；任何情况下都不打印 Key 值）：
    1) 环境变量 AMAP_KEY
    2) 环境变量 AMAP_KEY_FILE 指向的凭据文件（建议放在仓库/工作目录之外；
       文件内空行与 # 注释行会被跳过）
    3) 本脚本同目录下的 amap_key.txt（兼容本地旧用法，已 gitignore，
       绝不提交、绝不打印；空行与 # 注释行会被跳过）

其他环境变量：
    AMAP_QPS          全局启动节拍：所有高德请求合计每秒最多启动数，默认 2
                      （本机实测账户严格按滑动窗口限 3 QPS，取 2 留余量；额度以高德控制台为准）
    AMAP_SEARCH_QPS   搜索接口额外保守上限（叠加在全局节拍上），默认 1，待控制台核实后调整
    AMAP_MAX_INFLIGHT 最大在途请求数（含重试），默认 4；与 QPS 相互独立
    AMAP_TIMEOUT      单次请求超时秒数，默认 10
    AMAP_USE_SYSTEM_PROXY 设为 1 时走系统代理；默认绕过系统代理直连高德
                      （本机系统代理实测延迟 7s+ 且间歇性 ENOENT，直连约 0.2s；
                      应用层绕过系统代理不保证绕过 VPN 等网络层路由）
    AMAP_BUDGET_TOTAL / AMAP_BUDGET_SEARCH / AMAP_BUDGET_PER_RECORD
                      任务自设请求预算（0=不限，含重试/分页/逆查），batch 用尽后未执行项记 budget
    AMAP_BASE_URL     接口地址覆盖（仅测试用，正式任务勿设）
    AMAP_DEBUG        设为 1 时把请求 URL 打印到 stderr（Key 自动隐藏）

脱敏：所有错误消息、网络异常、调试输出在构造/输出前统一脱敏——已读取的
凭据值（含 URL 编码与 base64 形式）替换为 <REDACTED>，并额外匹配
key=/sig=/signature=/authorization=/token= 等通用凭据模式。

限速器为进程内单例：跨 batch 调用不重置节拍记录（不积攒空闲额度、不突发）。
调用方需保证同一时刻只运行一个高德批处理进程；多进程无法共享限速，
同账户多 Key/多会话也不能叠加吞吐（额度按账户与服务接口计）。
"""

import argparse
import base64
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("AMAP_BASE_URL", "https://restapi.amap.com/v3")  # 仅测试覆盖，正式任务勿设

# 高德错误码分类（对照官方文档 2022-10-12 版：
# https://developer.amap.com/api/webservice/guide/tools/info）
INVALID_KEY_CODES = {"10001", "10005", "10006", "10009"}
    # key不正确/过期、IP白名单、key回收、key与平台不符 → 停止全部
QPS_LIMIT_CODES = {"10004", "10019", "10020", "10021"}
    # 访问过于频繁 / 服务总、Key、账号维度 QPS → 冷却降速后有限重试
DAILY_LIMIT_CODES = {"10003", "10044", "40000", "40002"}
    # 日访问量/日调用量超限、余额耗尽、购买服务到期 → 停止对应服务队列
UNRECOGNIZED_LIMIT_CODES = {"10022", "10023"}
    # 官方文档未核实的额度类错误码：保留原始 info/infocode，不自动分类、不无限重试
STOP_ALL_KINDS = ("invalid_key",)        # 遇到即停止全部请求
QPS_SERVICE_STOP_AFTER = 3               # 某服务累计 QPS 超限记录达该数即停止该队列（初始策略，按日志调整）

# 中国大陆经纬度大致范围（超出即视为异常值）
LNG_RANGE = (73.0, 136.0)
LAT_RANGE = (3.0, 54.0)


_SECRETS = set()  # 已读取的凭据值（原始/URL编码/base64），仅用于脱敏，绝不打印


def _register_secret(value):
    """把凭据值登记进脱敏集合（含常见编码形式）。"""
    if not value:
        return
    v = str(value).strip()
    if not v or v in _SECRETS:
        return
    _SECRETS.add(v)
    _SECRETS.add(urllib.parse.quote(v, safe=""))
    _SECRETS.add(urllib.parse.quote_plus(v))
    try:
        _SECRETS.add(base64.b64encode(v.encode("utf-8")).decode("ascii"))
    except Exception:
        pass


_GENERIC_CRED_PATTERNS = (
    re.compile(r"(key|sig|signature|token)\s*=\s*[^&\s\"',]+", re.I),
    re.compile(r"(authorization)\s*[:=]\s*(Bearer\s+)?[^\s\"',]+", re.I),
)


def redact(text):
    """脱敏：已登记凭据值（含编码形式）与通用凭据模式一律替换为 <REDACTED>。"""
    s = str(text)
    for sec in sorted(_SECRETS, key=len, reverse=True):
        if sec:
            s = s.replace(sec, "<REDACTED>")
    for pat in _GENERIC_CRED_PATTERNS:
        s = pat.sub(lambda m: f"{m.group(1)}=<REDACTED>", s)
    return s


class AmapError(Exception):
    """kind: invalid_key | daily_limit | qps_limit | network | local_error | error

    构造时统一脱敏 message（凭据值、URL 携带的 key/sig/authorization 等）。
    """

    def __init__(self, kind, message, infocode=None):
        super().__init__(redact(message))
        self.kind = kind
        self.infocode = infocode


class RateLimiter:
    """并发与启动速率分离的限速器（进程内单例，所有请求类型/批次共享）。

    - 全局启动节拍：所有高德请求合计每秒最多启动 qps 次（无突发、不积攒空闲额度）
    - 搜索节拍：搜索接口额外保守上限 search_qps（叠加在全局节拍之上）
    - max_inflight：最大在途请求数（含重试），信号量控制，应对偶发慢请求
    吞吐量 ≈ min(QPS 上限, 并发数 / 平均请求耗时)，三者相互独立。
    slow_down()：QPS 超限后全局降到 ≤1 QPS，不重置节拍记录。
    """

    def __init__(self, qps=2, search_qps=1, max_inflight=4):
        self.max_inflight = max(int(max_inflight), 1)
        self._qps_interval = 1.0 / max(float(qps), 0.1)
        self._search_interval = 1.0 / max(float(search_qps), 0.1)
        self._sem = threading.Semaphore(self.max_inflight)
        self._lock = threading.Lock()          # 全局节拍
        self._search_lock = threading.Lock()   # 搜索节拍
        self._last_start = 0.0
        self._last_search = 0.0

    def acquire(self, service="geocode"):
        """service: geocode|search；搜索请求同时受全局与搜索节拍约束。"""
        with self._lock:
            now = time.monotonic()
            delay = self._last_start + self._qps_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last_start = max(now, self._last_start + self._qps_interval)
        if service == "search":
            with self._search_lock:
                now = time.monotonic()
                delay = self._last_search + self._search_interval - now
                if delay > 0:
                    time.sleep(delay)
                self._last_search = max(now, self._last_search + self._search_interval)
        self._sem.acquire()

    def release(self):
        self._sem.release()

    def slow_down(self):
        """QPS 超限后降速：全局与搜索节拍都降到 ≤1 次/秒（只放宽间隔，不重置记录）。"""
        with self._lock:
            self._qps_interval = max(self._qps_interval, 1.0)
        with self._search_lock:
            self._search_interval = max(self._search_interval, 1.0)


_limiter = None


def get_limiter():
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(
            qps=float(os.environ.get("AMAP_QPS", "2")),
            search_qps=float(os.environ.get("AMAP_SEARCH_QPS", "1")),
            max_inflight=int(os.environ.get("AMAP_MAX_INFLIGHT", "4")),
        )
    return _limiter


def _first_valid_line(path):
    """读取凭据文件第一行有效内容（跳过空行与 # 注释行）。"""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


def get_key():
    """按优先级读取 Key：AMAP_KEY 环境变量 → AMAP_KEY_FILE 文件 → 脚本同目录 amap_key.txt。

    读取成功后登记进脱敏集合；任何分支都不打印 Key 值。
    """
    key = os.environ.get("AMAP_KEY", "").strip()
    if key:
        _register_secret(key)
        return key
    env_file = os.environ.get("AMAP_KEY_FILE", "").strip()
    if env_file:
        if not os.path.isfile(env_file):
            raise AmapError(
                "invalid_key",
                "AMAP_KEY_FILE 指向的文件不存在；请检查路径，或改用 AMAP_KEY 环境变量",
            )
        key = _first_valid_line(env_file)
        if key:
            _register_secret(key)
            return key
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amap_key.txt")
    if os.path.isfile(key_file):
        key = _first_valid_line(key_file)
        if key:
            _register_secret(key)
            return key
    raise AmapError(
        "invalid_key",
        "未配置高德 Key：请设置环境变量 AMAP_KEY，或 AMAP_KEY_FILE 指向私人凭据文件，"
        "或在脚本同目录放置 amap_key.txt（勿提交仓库）。"
        "获取方式：高德开放平台 → 控制台 → 应用管理 → 创建应用 → 添加 Key（Web 服务）",
    )


def set_budget(limits):
    """设置任务预算上限（total/search/per_record，0=不限）。

    usage 为进程级累计，跨 batch/resolve 不重置——新批次不会重新获得完整预算。
    同一任务内应保持同一预算配置；并发下的预算检查在 try_consume 中原子完成。
    """
    global _budget_limits
    _budget_limits = {k: int(v or 0) for k, v in (limits or {}).items()}


_opener = None


def _build_opener():
    """默认绕过系统代理直连高德；AMAP_USE_SYSTEM_PROXY=1 时恢复系统代理。

    依据实测：本机系统代理下单请求 7s+ 且间歇性 ENOENT，
    直连 restapi.amap.com 约 0.2s 且稳定。
    注意：应用层绕过系统代理不保证绕过 VPN 等网络层路由。
    """
    if os.environ.get("AMAP_USE_SYSTEM_PROXY", "0") != "1":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


class _UsageCounter:
    """请求消耗计数（含重试/分页/逆查），供任务预算使用；try_consume 原子检查并计入。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.search = 0
        self.per_record = {}

    def try_consume(self, service, record_key, limits):
        """原子检查预算并计入一次请求（含重试）。limits 项为 0/缺失表示不限。
        返回 None（已计入）或超支项名（total/search/per_record，未计入）。"""
        with self._lock:
            if limits.get("total") and self.total >= limits["total"]:
                return "total"
            if service == "search" and limits.get("search") and self.search >= limits["search"]:
                return "search"
            if record_key and limits.get("per_record") and \
                    self.per_record.get(record_key, 0) >= limits["per_record"]:
                return "per_record"
            self.total += 1
            if service == "search":
                self.search += 1
            if record_key:
                self.per_record[record_key] = self.per_record.get(record_key, 0) + 1
            return None

    def snapshot(self):
        with self._lock:
            return {"total": self.total, "search": self.search,
                    "per_record": dict(self.per_record)}


usage = _UsageCounter()
_ctx = threading.local()          # 当前查询所属记录（供预算按记录计数）
_budget_limits = {}               # 任务预算上限（0=不限），由 batch/resolve 设置


def _http_get(url, timeout, service):
    """裸 HTTP GET：统一限速（节拍+在途）、原子预算检查、瞬时网络错误退避重试、
    ENOENT 不重试。每次尝试（含重试）都计入同一任务预算。"""
    last_exc = None
    for attempt in range(3):
        get_limiter().acquire(service)
        try:
            over = usage.try_consume(service, getattr(_ctx, "record_key", None), _budget_limits)
            if over:
                raise AmapError("budget", f"任务预算用尽({over})，未发送请求")
            req = urllib.request.Request(
                url, headers={"User-Agent": "amap-resolve-locations/1.0"}
            )
            with _opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(reason, OSError) and reason.errno == 2:
                raise AmapError(
                    "local_error",
                    f"本机环境错误(ENOENT)，未重试: {reason}",
                ) from exc
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s 退避
            continue
        except json.JSONDecodeError as exc:
            raise AmapError("error", f"响应不是有效 JSON: {exc}") from exc
        finally:
            get_limiter().release()
    raise AmapError("network", f"网络错误（重试 3 次仍失败）: {last_exc}")


def request_json(path, params, service="geocode"):
    """GET 请求 + 业务错误分类。

    QPS 超限（非额度耗尽）：冷却 2s、全局降速至 ≤1 QPS 后有限重试（每条最多 2 次），
    仍超限抛 qps_limit，由 batch 层决定是否停止该服务队列。
    """
    global _opener
    if _opener is None:
        _opener = _build_opener()

    params = dict(params)
    params["key"] = get_key()
    url = f"{BASE_URL}/{path}?" + urllib.parse.urlencode(params)
    if os.environ.get("AMAP_DEBUG") == "1":
        safe = dict(params)
        safe["key"] = "<KEY>"
        print(redact(f"[amap] {BASE_URL}/{path}?" + urllib.parse.urlencode(safe)),
              file=sys.stderr)

    timeout = float(os.environ.get("AMAP_TIMEOUT", "10"))
    qps_retries_left = 2  # QPS 超限后的额外重试上限（初始策略）
    while True:
        data = _http_get(url, timeout, service)
        status = str(data.get("status"))
        infocode = str(data.get("infocode", ""))
        info = data.get("info", "")
        if status == "1":
            return data
        if infocode in QPS_LIMIT_CODES:
            if qps_retries_left > 0:
                qps_retries_left -= 1
                get_limiter().slow_down()
                time.sleep(2.0)
                continue
            raise AmapError("qps_limit", f"QPS 超限（冷却重试后仍超限）: {info}", infocode)
        if infocode in INVALID_KEY_CODES:
            raise AmapError("invalid_key", f"Key 无效或权限不足: {info}", infocode)
        if infocode in DAILY_LIMIT_CODES:
            raise AmapError("daily_limit", f"日额度/余额类超限: {info}", infocode)
        if infocode in UNRECOGNIZED_LIMIT_CODES:
            raise AmapError(
                "error",
                f"未识别服务错误（infocode={infocode}, info={info}；"
                f"官方文档未核实该码，保留原始信息，不自动分类、不重试）",
                infocode,
            )
        raise AmapError("error", f"接口错误 {infocode}: {info}", infocode)


def valid_coord(lng, lat):
    """校验经纬度数值与范围（中国大陆），返回错误信息或 None。"""
    try:
        lng, lat = float(lng), float(lat)
    except (TypeError, ValueError):
        return "非数值经纬度"
    if not (LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
        return f"经度 {lng} 超出中国大陆范围"
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        return f"纬度 {lat} 超出中国大陆范围"
    return None


def _fmt_coord(location):
    """location 形如 "lng,lat"。校验后保留接口原值字符串。"""
    if not location or "," not in location:
        return location or "", "缺少坐标"
    lng, _, lat = location.partition(",")
    err = valid_coord(lng.strip(), lat.strip())
    return location, err


def geocode(address, city=None):
    """地理编码。返回结构化候选，location 为接口原值。"""
    params = {"address": address}
    if city:
        params["city"] = city
    data = request_json("geocode/geo", params)
    geos = data.get("geocodes", [])
    out = []
    for g in geos:
        loc, err = _fmt_coord(g.get("location"))
        out.append(
            {
                "formatted_address": g.get("formatted_address"),
                "location": loc,           # 接口原值
                "coord_error": err,        # None 表示数值与范围校验通过
                "level": g.get("level"),   # 匹配级别：省/市/区县/乡镇/村庄/门牌号…
                "adcode": g.get("adcode"),
                "province": g.get("province"),
                "city": g.get("city"),
                "district": g.get("district"),
                "township": g.get("township"),
                "towncode": g.get("towncode"),
            }
        )
    return {"status": "ok", "count": int(data.get("count", 0)), "geocodes": out}


def search_poi(keywords, city=None, citylimit=True, page=1, offset=10):
    """POI 关键字搜索。city 可为市名、县名或 adcode；citylimit=true 时仅在 city 内。"""
    params = {
        "keywords": keywords,
        "citylimit": "true" if citylimit else "false",
        "page": page,
        "offset": offset,
        "extensions": "base",
    }
    if city:
        params["city"] = city
    data = request_json("place/text", params, service="search")
    pois = data.get("pois", [])
    out = []
    for p in pois:
        loc, err = _fmt_coord(p.get("location"))
        out.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "type": p.get("type"),
                "address": p.get("address"),
                "pname": p.get("pname"),
                "cityname": p.get("cityname"),
                "adname": p.get("adname"),
                "location": loc,
                "coord_error": err,
            }
        )
    return {"status": "ok", "count": int(data.get("count", 0)), "page": page, "pois": out}


def regeocode(lng, lat):
    """逆地理编码（仅用于候选复核，不能单独证明行政隶属）。"""
    err = valid_coord(lng, lat)
    if err:
        return {"status": "invalid", "error": err}
    data = request_json("geocode/regeo", {"location": f"{lng},{lat}", "extensions": "base"})
    rc = data.get("regeocode", {})
    comp = rc.get("addressComponent", {})
    return {
        "status": "ok",
        "formatted_address": rc.get("formatted_address"),
        "province": comp.get("province"),
        "city": comp.get("city"),
        "district": comp.get("district"),
        "township": comp.get("township"),
        "adcode": comp.get("adcode"),
        "towncode": comp.get("towncode"),
        "pois": [p.get("name") for p in (rc.get("pois") or [])[:5]],
        "roads": [r.get("name") for r in (rc.get("roads") or [])[:5]],
    }


def batch(plan):
    """并发执行查询计划：任务预算 + 查询去重 + 分服务停止 + 统一限速。

    plan: 查询列表，或 {"queries": [...], "budget": {"total": N, "search": N, "per_record": N}}
    预算为任务自设上限（非高德平台限制），包含重试/分页/逆查；用尽后未执行项记 budget。
    去重键 = 查询类型 + 全部参数（不同县同名村的查询参数不同，不会被合并）；
    重复查询只发一次，结果回填到各 query_id（标记 dedup_of）。
    invalid_key 停止全部；daily_limit 停止对应服务队列；
    某服务累计 QPS 超限记录达 QPS_SERVICE_STOP_AFTER 条即停止该队列（初始策略）。
    返回 {"results", "errors", "stopped", "usage", "budget"}。
    """
    budget_cfg = {}
    if isinstance(plan, dict):
        budget_cfg = plan.get("budget") or {}
        plan = plan.get("queries") or []
    B = {
        "total": int(budget_cfg.get("total") or os.environ.get("AMAP_BUDGET_TOTAL", "0") or 0),
        "search": int(budget_cfg.get("search") or os.environ.get("AMAP_BUDGET_SEARCH", "0") or 0),
        "per_record": int(budget_cfg.get("per_record") or os.environ.get("AMAP_BUDGET_PER_RECORD", "0") or 0),
    }
    set_budget(B)  # 原子预算在 _http_get 每次尝试处强制（含重试）

    def dedup_key(q):
        t = q.get("type")
        if t == "geocode":
            return ("geocode", q.get("address", ""), q.get("city"))
        if t == "search":
            return ("search", q.get("keywords", ""), q.get("city"),
                    q.get("citylimit"), q.get("page"), q.get("offset"))
        if t == "regeocode":
            return ("regeocode", q.get("lng"), q.get("lat"))
        return None

    seen = {}
    for q in plan:
        key = dedup_key(q)
        if key is not None:
            if key in seen:
                q["_dedup_of"] = seen[key]
            else:
                seen[key] = q.get("query_id")

    results, errors = {}, {}
    stop_event = threading.Event()        # invalid_key → 全停
    budget_stop = threading.Event()       # 预算用尽 → 剩余记 budget
    service_stop = {}                     # service -> (kind, message)
    qps_fails = {"geocode": 0, "search": 0}
    stop_kind = None

    def budget_exceeded(qtype, record_key):
        u = usage.snapshot()
        if B["total"] and u["total"] >= B["total"]:
            return "total"
        if qtype == "search" and B["search"] and u["search"] >= B["search"]:
            return "search"
        if B["per_record"] and record_key and u["per_record"].get(record_key, 0) >= B["per_record"]:
            return "per_record"
        return None

    def run_one(q):
        qid = q.get("query_id") or "?"
        if q.get("_dedup_of"):
            return qid, None, {"kind": "dedup", "message": f"与 {q['_dedup_of']} 相同，复用其结果"}
        record_key = q.get("_record_key") or (qid.split("-")[0] if "-" in qid else qid)
        if stop_event.is_set():
            return qid, None, {"kind": "stopped", "message": "因前序错误停止"}
        if budget_stop.is_set():
            return qid, None, {"kind": "budget", "message": "预算用尽"}
        qtype = q.get("type")
        svc = "search" if qtype == "search" else "geocode"
        if qtype not in ("geocode", "search", "regeocode"):
            return qid, None, {"kind": "error", "message": f"未知查询类型: {qtype}"}
        if svc in service_stop:
            return qid, None, {"kind": service_stop[svc][0], "message": service_stop[svc][1]}
        be = budget_exceeded(qtype, record_key)
        if be:
            budget_stop.set()
            return qid, None, {"kind": "budget", "message": f"预算用尽({be})，未执行"}
        _ctx.record_key = record_key
        try:
            if qtype == "geocode":
                result = geocode(q.get("address", ""), q.get("city"))
            elif qtype == "search":
                result = search_poi(
                    q.get("keywords", ""),
                    q.get("city"),
                    bool(q.get("citylimit", True)),
                    int(q.get("page", 1)),
                    int(q.get("offset", 10)),
                )
            else:
                result = regeocode(q.get("lng"), q.get("lat"))
        except AmapError as exc:
            err = {"kind": exc.kind, "message": str(exc), "infocode": exc.infocode}
            if exc.kind == "invalid_key":
                stop_event.set()
            elif exc.kind == "daily_limit":
                service_stop[svc] = ("daily_limit", f"该服务日额度/余额类超限，停止后续请求: {exc}")
            elif exc.kind == "qps_limit":
                qps_fails[svc] += 1
                if qps_fails[svc] >= QPS_SERVICE_STOP_AFTER:
                    service_stop[svc] = ("qps_limit", f"该服务持续 QPS 超限，停止后续请求")
            elif exc.kind == "budget":
                budget_stop.set()
            return qid, None, err
        return qid, result, None

    limiter = get_limiter()
    pending_dedup = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=limiter.max_inflight
    ) as pool:
        futures = [pool.submit(run_one, q) for q in plan]
        for q, fut in zip(plan, futures):
            qid, result, err = fut.result()
            if err is not None:
                if err["kind"] == "dedup":
                    pending_dedup[qid] = q.get("_dedup_of")
                    continue
                errors[qid] = err
                if err["kind"] in STOP_ALL_KINDS and stop_kind is None:
                    stop_kind = err["kind"]
            else:
                results[qid] = result

    # 去重回填（按计划顺序追加）
    for q in plan:
        qid = q.get("query_id")
        if qid not in pending_dedup:
            continue
        first = pending_dedup[qid]
        if first in results:
            results[qid] = dict(results[first])
            results[qid]["dedup_of"] = first
        elif first in errors:
            errors[qid] = dict(errors[first])
            errors[qid]["message"] = f"复用 {first} 的结果: {errors[first]['message']}"
    return {"results": results, "errors": errors, "stopped": stop_kind,
            "usage": usage.snapshot(), "budget": {k: v for k, v in B.items() if v}}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="高德 Web 服务 API 最小调用工具（请求/限速/校验；决策由 AI 负责）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("geocode", help="地理编码（完整行政层级＋名称优先）")
    p.add_argument("--address", required=True)
    p.add_argument("--city", default=None)

    p = sub.add_parser("search", help="POI 关键字搜索（县域限制用 --city adcode）")
    p.add_argument("--keywords", required=True)
    p.add_argument("--city", default=None)
    p.add_argument("--citylimit", default=True, type=lambda s: s.lower() not in ("false", "0", "no"))
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--offset", type=int, default=10)

    p = sub.add_parser("regeocode", help="逆地理编码（候选复核用）")
    p.add_argument("--lng", required=True)
    p.add_argument("--lat", required=True)

    p = sub.add_parser("batch", help="按查询计划批量执行")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "geocode":
            result = geocode(args.address, args.city)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.cmd == "search":
            result = search_poi(args.keywords, args.city, args.citylimit, args.page, args.offset)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.cmd == "regeocode":
            result = regeocode(args.lng, args.lat)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:  # batch
            with open(args.input, encoding="utf-8") as f:
                plan = json.load(f)
            result = batch(plan)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            err_kinds = {}
            for e in result["errors"].values():
                err_kinds[e["kind"]] = err_kinds.get(e["kind"], 0) + 1
            n = len(plan if isinstance(plan, list) else plan.get("queries", []))
            print(
                json.dumps(
                    {
                        "written_to": args.output,
                        "total": n,
                        "ok": len(result["results"]),
                        "errors": err_kinds,
                        "stopped": result["stopped"],
                        "usage": result.get("usage", {}),
                        "budget": result.get("budget", {}),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    except AmapError as exc:
        print(
            json.dumps(
                {"status": "error", "kind": exc.kind, "message": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
