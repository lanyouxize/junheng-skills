# 命令参考（完整参数）

统一入口 `scripts/collect.py`。所有命令均需 `--yes`（非交互合规确认）。

## L1 单/多 URL

```bash
# --urls 逗号分隔，或 --url-file 每行一个
python collect.py --config config.yaml --yes url \
  --urls "https://mp.weixin.qq.com/s/xxxx" --out out/v1.jsonl
```

需要 Playwright（`playwright install chromium`）。正文图片走 `data-src` 懒加载，脚本已等 `networkidle` + 滚动，详见 SKILL.md 避坑提示。

## L2 按号批量历史

```bash
# cookie 复用 profile_ext 翻页
python collect.py --yes account --biz <__biz> \
  --cookie-file cookies.json --limit 20 --out out/v3.jsonl
```

端点与已知坑见 `wechat-endpoints.md`。

## L3 PC 微信自动驱动

```bash
# --assist = 用户协助在微信里打开文章；拦截由 mitmproxy 完成
# 模式 auto：先试 local 透明劫持，驱动装不上自动降级 regular（临时接管系统代理，退出还原）
python collect.py --yes desktop --account "公众号名" --mitm-mode auto --assist --out out/v4.jsonl

# 驱动装不上的机器（HVCI / 驱动黑名单 / 签名过期）：显式 regular + 系统代理
python collect.py --yes desktop --account "公众号名" --mitm-mode regular --system-proxy --out out/v4.jsonl
```

环境搭建（CA 证书 / 防火墙 / 权限）见 `l3-setup.md`。

## exe 兜底

```bash
# 先探测 CLI；不支持则启动进程 + 扫描输出目录
python collect.py --yes exe --exe "D:/tools/4.0.exe" \
  --target "公众号名" --out out/v4e.jsonl
```

## 写库

```bash
# --dry-run 只打印将发送的 payload，不写入
python collect.py --yes write --in out/v1.jsonl --library-node <node_id> --dry-run
python collect.py --yes write --in out/v1.jsonl --library-node <node_id>
```

`create-database` 一次建 24 列；`batch-add-records` 每批 50–100 条，带礼貌延迟。

## 双写（云端资料库 + 本地 vault）

```bash
# 复用同一份分类结论；离域不写；vault 失败 best-effort，不阻断云端
python collect.py --yes write --in out/v1.jsonl --library-node <node_id> --vault
```

- `--vault` 默认关（只写云端）。
- 本地 vault 根目录见 config `vault.root`。
- `vault.enabled: true` 可让每次 write 常驻双写；`vault.auto_apply: false` 转为预览。

## 常用参数速查

| 参数 | 作用 |
|---|---|
| `--config` | 配置文件路径；`refresh` 子命令下即 subscriptions.yaml |
| `--out` | JSONL 输出路径；省略则输出到 stdout（可管道给 jq） |
| `--library-node` | 目标数据表所在节点 id（精确，推荐） |
| `--dry-run` | 只打印将执行的 payload / 命令，不产生副作用 |
| `--yes` | 非交互合规确认；用户已在对话中授权时才代传 |
| `--since-days N` | 仅 `refresh`：给所有 account 源注入 `--since`（today−N） |
