#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_security.py — 凭据安全与发布规范测试（无网络、无真实 Key 依赖）

运行：cd <skill根目录> && python tests/test_security.py
覆盖：
  1. 缺少 Key 时安全退出（明确提示、非零退出码、不打印任何 Key 值）
  2. 合成测试凭据：错误消息/异常/调试输出/批量摘要均不泄露其值
     （原始、URL 编码、base64 编码三种形式）
  3. 示例文件不依赖真实 Key（plan.example.json 无凭据字段；
     坐标自检与写出/离线测试可无 Key 运行）
  4. 四个坐标字段与转换状态名称符合 ^[A-Za-z][A-Za-z0-9_]*$
  5. CSV/XLSX 写出后重新读取：记录数、行序、数值正确（复用
     test_output_writer 的验证逻辑，此处做最小回归）
  6. 通用凭据模式（key=/sig=/authorization=）即使未预先登记也会被脱敏
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import amap_api  # noqa: E402
import coordinate_transform as ct  # noqa: E402
import output_writer as ow  # noqa: E402

CHECKS = []
FAKE_KEY = "TEST_SYNTHETIC_KEY_9f8e7d6c5b4a"


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


# ---- 1. 缺少 Key 时安全退出 ----
tmp = tempfile.mkdtemp(prefix="amap_seckey_")
api_copy = os.path.join(tmp, "amap_api.py")
shutil.copy(os.path.join(SCRIPTS, "amap_api.py"), api_copy)
env = {k: v for k, v in os.environ.items()
       if k not in ("AMAP_KEY", "AMAP_KEY_FILE", "AMAP_BASE_URL")}
env.pop("AMAP_KEY", None)
p = subprocess.run([sys.executable, api_copy, "geocode", "--address", "北京市"],
                   capture_output=True, text=True, encoding="utf-8",
                   env=env, cwd=tmp, timeout=60)
check("无Key时非零退出", p.returncode != 0, f"rc={p.returncode}")
check("无Key时给出配置提示", "AMAP_KEY" in (p.stderr + p.stdout)
      and "未配置" in (p.stderr + p.stdout), (p.stderr + p.stdout)[:120])
check("无Key提示不包含可疑Key值", "TEST_SYNTHETIC" not in p.stderr
      and "key=" not in p.stderr.lower().replace("amap_key", ""),
      (p.stderr + p.stdout)[:120])

# ---- 2. 合成凭据不泄露（原始/URL编码/base64）----
amap_api._register_secret(FAKE_KEY)
enc = FAKE_KEY.replace("_", "%5F").replace("TEST_", "TEST%5F")
import urllib.parse as _up
b64 = __import__("base64").b64encode(FAKE_KEY.encode()).decode()

cases = [
    f"网络错误（重试 3 次仍失败）: urlopen error key={FAKE_KEY}",
    f"接口错误 10001: 请求 URL 含 ?key={enc}&sig=abc123",
    f"Authorization: Bearer {FAKE_KEY}",
    f"key参数={b64}",
]
for i, raw in enumerate(cases):
    e = amap_api.AmapError("error", raw)
    check(f"错误消息脱敏-{i}", FAKE_KEY not in str(e) and "<REDACTED>" in str(e),
          str(e)[:80])
check("错误消息不含base64形式", b64 not in str(amap_api.AmapError("error", b64)))
# 调试输出脱敏
buf = []
import io as _io
orig = sys.stderr
sys.stderr = _io.StringIO()
try:
    os.environ["AMAP_DEBUG"] = "1"
    os.environ["AMAP_KEY"] = FAKE_KEY
    os.environ["AMAP_BASE_URL"] = "https://example.invalid/v3"
    try:
        amap_api.geocode("北京市")
    except Exception:
        pass
    debug_out = sys.stderr.getvalue()
finally:
    sys.stderr = orig
    for k in ("AMAP_DEBUG", "AMAP_KEY", "AMAP_BASE_URL"):
        os.environ.pop(k, None)
check("AMAP_DEBUG输出不泄露Key",
      FAKE_KEY not in debug_out and ("<KEY>" in debug_out or "<REDACTED>" in debug_out),
      debug_out[:100])

# ---- 3. 示例不依赖真实 Key ----
plan = json.load(open(os.path.join(SKILL_ROOT, "examples", "plan.example.json"),
                      encoding="utf-8"))
check("示例无凭据字段", not any("key" in q for q in plan)
      and "YOUR_" not in json.dumps(plan, ensure_ascii=False))
p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "coordinate_transform.py"),
                    "--self-test"], capture_output=True, text=True,
                   encoding="utf-8", env=env, cwd=tmp, timeout=120)
check("坐标自检无Key可运行", p.returncode == 0 and "ALL PASS" in p.stdout,
      (p.stdout + p.stderr)[-60:])

# ---- 4. 字段名规范 ----
FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
check("四坐标字段+状态名符合规范",
      all(FIELD_RE.match(f) for f in ct.COORD_FIELDS)
      and FIELD_RE.match("conversion_status") is not None)
check("转换状态取值齐全",
      set(ct.VALID_STATUSES) == {"converted", "already_wgs84",
                                 "out_of_scope_passthrough", "missing",
                                 "invalid", "not_converged", "unknown_source_crs"})

# ---- 5. CSV/XLSX 写出后重读（最小回归，无网络）----
rows = [{"id": "r001", "序号": 1, "名录原文": "1、合成示例村", "村落名称": "合成示例村"}]
results = {"r001": {"status": "confirmed",
                    "coordinate": {"lng": "108.100000", "lat": "34.300000"}}}
header, data, _ = ow.build_table(rows, results, None, "gcj02")
out_xlsx = os.path.join(tmp, "t.xlsx")
out_csv = os.path.join(tmp, "t.csv")
ow.write_xlsx(out_xlsx, header, data)
ow.write_csv(out_csv, header, data)
ver_x = ow.verify_output(out_xlsx, header, data)
ver_c = ow.verify_output(out_csv, header, data)
check("XLSX回读核对", ver_x["ok"], "; ".join(ver_x["issues"]))
check("CSV回读核对", ver_c["ok"], "; ".join(ver_c["issues"]))

# ---- 6. 通用凭据模式脱敏（未登记值）----
amap_api._SECRETS.clear()
e = amap_api.AmapError("error", "请求失败: ?key=SOMEONE_ELSES_KEY_123&sig=xyz")
check("未登记key=模式也脱敏", "SOMEONE_ELSES_KEY_123" not in str(e), str(e))
e = amap_api.AmapError("error", "Authorization: Bearer abcdef.ghijk.lmnop")
check("Authorization模式脱敏", "abcdef" not in str(e), str(e))
amap_api._SECRETS.add(FAKE_KEY)  # 还原，避免影响其他测试

# ---- 报告 ----
failed = 0
for name, ok, detail in CHECKS:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" — {detail}"))
    if not ok:
        failed += 1
print("ALL PASS" if failed == 0 else f"HAS {failed} FAILURE(S)")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if failed == 0 else 1)
