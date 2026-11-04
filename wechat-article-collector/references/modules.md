# 模块结构与退出码

## 目录

```
scripts/
  collect.py                 统一派发器（register/run 契约）
  common.py                  退出码/事件流/配置/合规闸/JSONL/礼貌延迟
  normalize.py               24 列 schema、校验、去重键、PropertyValue 映射
  extract.py                 文章页 HTML 纯解析（三层共用）
  l1_fetch_urls.py           L1 Playwright 单/多 URL
  l2_fetch_account.py        L2 profile_ext 按号批量
  l3_drive_wechat.py         L3 PC 微信驱动（pywinauto + mitmproxy 编排）
  addons/wechat_article_addon.py   mitmproxy 附加脚本（抓文章页响应）
  exe_wrapper.py             闭源 exe 兜底
  write_to_library.py        写库（space_api.py CLI 转发）
  refresh.py                 每日自动刷新编排（调度/重试/状态/告警）
tests/                       unittest（extract / normalize / collect）
references/
  schema.md                  24 列契约与类型映射
  wechat-endpoints.md        profile_ext 等端点与已知坑
  l3-setup.md                L3 环境搭建（CA / 防火墙 / 权限）
  commands.md                完整命令与参数速查
  refresh.md                 每日刷新编排细则
  modules.md                 本文件
docs/decisions/              ADR-001/002/003（实现阶段落盘）
```

## 退出码（与事件 level 1:1）

| 码 | 含义 |
|---|---|
| `0` | ok / info |
| `2` | 参数错误 |
| `3` | 错误 |
| `4` | 合规拦截 |
| `5` | 部分完成 |
| `6` | 环境缺失 |

## 派发约定

新增采集层需在 `collect.py` 注册，并遵守统一契约：接收 `--config` / `--out` / `--yes`，
输出 `revfact` 之外的 JSONL 记录流，通过 `common.py` 的 `emit_event` 打事件，
失败不得静默丢弃（`status=fail` 行必须带 `fail_reason`）。
