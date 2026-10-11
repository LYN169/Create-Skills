# SECURITY.md · 凭据安全与泄露处理

## 安全配置 Key

- **优先级**：环境变量 `AMAP_KEY` → 环境变量 `AMAP_KEY_FILE` 指向的凭据文件（建议放在仓库/工作目录之外）→ 脚本同目录 `amap_key.txt`（仅本地兼容）。
- **不要**把 Key 写入源码、SKILL.md、README、任务计划或聊天消息；不建议把 Key 放在命令行参数或完整请求 URL 中。
- 配置模板（`scripts/amap_key.txt.example`）只含 `YOUR_AMAP_KEY_HERE` 占位符；`amap_key.txt` 已被 `.gitignore` 排除，不会进入发布包。
- 无 Key 时脚本打印简短的配置提示并安全退出，**绝不打印任何已存在的 Key**。

## 脱敏机制

`scripts/amap_api.py` 内置统一脱敏（`redact()`）：

- 已读取的凭据值及其 URL 编码、base64 形式一律替换为 `<REDACTED>`；
- 未预先登记的 `key=`、`sig=`、`signature=`、`token=`、`Authorization: Bearer ...` 等通用凭据模式同样会被脱敏；
- 覆盖所有错误消息、网络异常（含异常携带的完整 URL）、`AMAP_DEBUG` 调试输出、批量摘要与 AI 回传内容。日志只显示接口、状态、耗时与脱敏参数。

## 禁止行为

- **不要在公开 Issue / PR / 讨论中粘贴 Key**。需要提供报错信息时，先确认输出已脱敏，或只贴错误码与现象。
- 不要把 Key 通过任何公开渠道分享；本仓库不提供共享 Key。

## 发现 Key 泄露后的处理

1. **立即撤销**：登录[高德开放平台控制台](https://console.amap.com/)删除该 Key，重新创建新 Key（Key 不支持修改值，只能删除重建）；
2. **更新本地配置**：替换环境变量 `AMAP_KEY`/`AMAP_KEY_FILE` 或 `scripts/amap_key.txt` 中的旧值；
3. **清理泄露面**：删除或撤回公开内容（Issue/PR/提交）；
4. **若泄露在 Git 历史中**：仅删除当前文件不够，已推送的历史仍可被检索。小仓库可联系管理员处理；公开仓库请把该 Key 视为已泄露——先撤销再清理历史，不要只删文件后继续使用。

## 报告安全问题

不要在公开渠道披露。请通过私密渠道联系仓库维护者（如 GitHub 私信或邮箱），说明影响范围；确认修复后再公开细节。
