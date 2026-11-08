---
name: wechat-article-collector
description: 自动采集微信公众号文章（图文/视频元数据）并归档写入「铭衍·元典」资料库数据表。当用户要求采集/保存/批量下载公众号文章、按公众号批量抓历史、把微信文章入库或导出 JSONL 时触发；四层采集 url/account/desktop/exe + write 写库，仅限本机、仅限已授权内容。
disable-model-invocation: true
license: Proprietary
compatibility: Python 3.9+; pip 可安装第三方包.
---

# wechat-article-collector 公众号文章采集器

把微信公众号文章（图文/视频）归一化为统一 24 列 schema，写入「铭衍·元典」智库子数据表，供下游情报筛选。纯本机 skill，运行于 WorkBuddy 托管 Python 3.13.12 / Windows。

## 何时用 / 不做什么

- **用**：用户给出文章 URL 要归档；按公众号批量抓历史；本机 PC 微信辅助采集（desktop）；exe 兜底；把已采集 JSONL 写库。
- **不做**：协议级逆向/mTLS 签名伪造、手机微信、评论/阅读量/点赞指标、云端部署、抓非授权号。
- **合规闸（强制，AC-10）**：仅限自有/已授权内容；每次运行打印合规声明，非交互会话必须传 `--yes`（用户已在对话中授权时才代传）。

**同类技能分工（按工序选，勿混用）**：

| 需求 | 用哪个 |
|---|---|
| 关键词检索、要前 10 条列表 | `wechat-article-search`（仅需 node，最轻） |
| 抓正文导出到 IMA / Dify / Obsidian | `wechat-article-scraper` |
| 整站历史归档成 HTML 阅读器 / TXT / Word | `wechat-article-archive` |
| **采集 → 写库**（建表并写入「铭衍·元典」） | **本技能** |

本技能有写副作用（建表 + 写行），不承担通用检索，不做纯文本导出。

## 环境准备

```bash
# 本机已验证的解释器（bs4/lxml/pyyaml/requests/tenacity/playwright 均已就位）。
# 命令与测试一律显式用全路径，避免命中系统 python 误报"缺依赖"：
# C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe

python -m venv <env> && <env>/pip install -r requirements.txt
playwright install chromium          # L1/L2 文章页渲染需要
```

## 操作步骤

1. **确认授权**：目标公众号为本人自有或已获授权；未确认不得运行。
2. **准备配置**：复制 `config.example.yaml` 为 `config.yaml`，填 `library.node_id`（或运行时 `--library-node`）。
3. **选采集层**：单/多篇 `url`；按号批量 `account`；PC 微信辅助 `desktop`；exe 兜底 `exe`。
4. **执行采集**：产出 JSONL（24 列，`status=fail` 行带 `fail_reason`，不静默丢弃）。
5. **写库**：先 `--dry-run` 核对 payload，再正式写（建表 24 列 + 每批 50–100 条，带礼貌延迟）。
6. **验收**：断言 JSONL `status=ok` 且字段齐全；写库后按 account/publish_time 可筛出。
   `keyword_tags` 当前恒空、暂不可依赖（见 `references/schema.md` B5）。

## 命令速查

完整参数见 **`references/commands.md`**。

```bash
# 采集：四层任选其一
python collect.py --yes url     --urls "https://mp.weixin.qq.com/s/xxxx" --out out/v1.jsonl
python collect.py --yes account --biz <__biz> --cookie-file cookies.json --limit 20 --out out/v3.jsonl
python collect.py --yes desktop --account "公众号名" --mitm-mode auto --assist --out out/v4.jsonl
python collect.py --yes exe     --exe "D:/tools/4.0.exe" --target "公众号名" --out out/v4e.jsonl

# 写库：先 dry-run 看 payload，再正式写；加 --vault 同时写本地 vault
python collect.py --yes write --in out/v1.jsonl --library-node <node_id> --dry-run
python collect.py --yes write --in out/v1.jsonl --library-node <node_id> --vault

# 每日刷新：编排、注册计划任务、看状态
python collect.py refresh run     --yes --config subscriptions.yaml
python collect.py refresh install --config subscriptions.yaml --time 08:00
python collect.py refresh status  --config subscriptions.yaml
```

`--vault` 默认关（只写云端）；`vault.enabled: true` 常驻双写，`vault.auto_apply: false` 转预览。
每日刷新的产物、去重、重试与告警细则见 **`references/refresh.md`**。

## 省时技巧

- `--out` 省略时 JSONL 直接进 stdout，可管道给 `jq` 过滤后再写库。
- **采集与写库分离**：先落 JSONL，人工抽查后再 `write`；失败行已在 JSONL 标注原因。
- `write` 按规范化 URL 去重（保留 `__biz+mid+idx`，剥离 `sn/chksm/utm`），重复执行不写重行。
- 媒体文件落在 `<out 去扩展名>.media/`，`body_ref/images_ref/videos_ref` 指向该目录。
- **产物不要留在技能目录**：历史 `out/`（229 文件 / 76.4 MB）已外置到
  `D:/workbuddy重做系统后版本/2026-10-23-14-10-52/data/wechat-article-collector/`。
  新采集把 `--out` 直接指向该目录（脚本会自动建父目录）。

## 避坑提示

**L1 图片为空**：文章图用 `data-src` 懒加载而非 `src`，必须等 `networkidle` 并滚动页面后再取 HTML。
这是"正文有了图没了"的最常见原因。

**L3 跑满窗口 0 捕获**：`local` 模式依赖 WinDivert 内核驱动。驱动签名过期或被 HVCI/黑名单拦截时，
mitmdump 主进程**仍然存活**但内部 redirector 已退出（日志 `Task failed: ...`）。
故启动探活必须同时读日志特征，不能只看进程存活；`--mitm-mode auto` 会在此时自动降级 `regular`。

## 参考文件

| 文件 | 内容 |
|---|---|
| `references/commands.md` | 完整命令与参数速查 |
| `references/refresh.md` | 每日刷新：产物、去重增量、重试告警 |
| `references/schema.md` | 24 列契约与类型映射 |
| `references/wechat-endpoints.md` | profile_ext 等端点与已知坑 |
| `references/l3-setup.md` | L3 环境搭建（CA / 防火墙 / 权限） |
| `references/modules.md` | 模块结构与退出码（0/2/3/4/5/6） |
