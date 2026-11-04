# wechat-endpoints.md — 微信端点与页面结构契约（wechat-article-collector）

> 覆盖 L2 的 profile_ext 历史消息端点、文章页 JS 变量、已知坑与频率合规约定。
> 响应结构以真实抓包为准；本文标注"待真机复测"处未在开发机验证。生成日期：2026-10-22。

## 1. profile_ext 历史消息端点（L2 核心）

```
GET https://mp.weixin.qq.com/mp/profile_ext
    ?action=getmsg&__biz=<biz>&f=json&offset=<n>&count=10
    &is_ok=1&scene=<n>&uin=<uin>&key=<key>
    &pass_ticket=<pass_ticket>&wxtoken=<wxtoken>&appmsg_token=<appmsg_token>
Cookie: 已登录微信网页会话的 cookie（devicid / RK / ua / appmsg_token 等）
```

| 参数 | 含义 | 获取方式 |
|---|---|---|
| action | 固定 `getmsg`，请求历史消息列表动作 | 常量 |
| __biz | 公众号唯一 biz | 文章页 JS `biz` 变量 / 任意文章 URL 的 `__biz` 参数 |
| f | 固定 `json`，响应格式 | 常量 |
| offset | 分页偏移，从 0 起按 count 递增 | 翻页循环自增 |
| count | 每页条数，惯例 10 | 常量（可调小降频） |
| is_ok | 状态位 0/1，心跳/登录态探测 | 常量 1 |
| scene | 场景标识（历史页入口场景值） | 抓包常量（不同入口可能不同，以实测为准） |
| uin | 登录账号 uin | cookie 或同次抓包 URL |
| key | 会话 key，随登录态变化 | 抓包 URL |
| pass_ticket | 扫码登录后下发的票据 | 抓包 URL / cookie |
| wxtoken | 微信 web token，profile_ext 鉴权关键 | cookie（wxtoken） |
| appmsg_token | 文章列表 token，部分版本必需 | cookie / URL |

鉴权材料统称"cookie 三形态"（l2_fetch_account.py 解析）：浏览器 cookies.txt（Netscape）、Playwright storage_state JSON、原始 header 字符串。uin/key/pass_ticket/appmsg_token 优先从 cookie 解析，缺失时从同次抓包的请求 URL 回填；wxtoken 必须存在于 cookie。三种形态的字段名差异与解析优先级以 l2_fetch_account.py 为准（该模块实现中，契约待其落盘后对齐复核）。

## 2. general_msg_list 响应结构与翻页语义

顶层字段：

| 字段 | 含义 |
|---|---|
| ret | 0=成功；非 0=失败（cookie 失效 / 被限频 / 参数过期） |
| errmsg | 失败描述 |
| can_msg_continue | 1=仍有下一页；0=已到历史尽头 |
| general_msg_list | **JSON 字符串**，需二次 json.loads 解析 |
| msg_count | 本页消息数（部分版本存在，可选） |

`general_msg_list.list[]` 每一项：

| 层级 | 字段 | 含义 |
|---|---|---|
| comm_msg_info | datetime | 发布时间 epoch 秒 → UTC ISO |
| app_msg_ext_info | title | 头条文章标题 |
| app_msg_ext_info | digest | 摘要 |
| app_msg_ext_info | cover | 封面（`//mmbiz.qpic.cn/...` 相对协议，补 `https:`） |
| app_msg_ext_info | link | 文章链接（`/s?__biz=...&mid=...&idx=...&sn=...` 相对路径，补 `https://mp.weixin.qq.com`） |
| app_msg_ext_info | author | 作者（可选） |
| app_msg_ext_info | multi_app_msg_item_list[] | 多图文推文的其余文章（同结构，idx 递增） |

翻页语义：`offset += count` 循环请求，`can_msg_continue=0` 即停；`--limit` 达到即停。实现兜底：`can_msg_continue` 缺失时回退读 `is_continue`，再缺省视为不可继续（l2_fetch_account.py 实测行为，比裸判 can_msg_continue 更稳健）。`ret!=0` 处置：tenacity 指数退避重试（AC-06，3 次尝试），重登 cookie 后仍失败即停并报告（有产出退出码 5，无产出退出码 3），不静默跳过。

## 3. 文章页 JS 变量清单与 extract.py 消费

文章页 HTML 内 `var <name> = '...';` 形式的内联变量（extract.py `_js_var` 正则提取，容忍转义引号与中文）：

| 变量 | 含义 | extract.py 消费方式 |
|---|---|---|
| msg_title | 文章标题 | title 第二优先级（og:title 之后） |
| nickname | 公众号名称 | account 第二优先级（#js_name 之后） |
| author | 作者 | author 第一优先级 |
| msg_desc | 摘要 | digest 第二优先级（description meta 之后） |
| msg_cdn_url | 封面图 CDN 地址 | cover 第一优先级 |
| ct | 发布时间 epoch 秒 | publish_time：`_epoch_to_iso`（9–11 位数字才转，否则空） |
| biz | 公众号 __biz | account_id |
| vid | 视频 id（视频文章） | **不直接消费**；视频识别走 iframe(v.qq.com/mpvideo) 或 `<mpvideo>` 标签的 data-src |

正文与图片：正文取 `#js_content`（或 `.rich_media_content`）的 inner HTML；图片 `data-src` 优先、`src` 兜底，仅保留 mmbiz/qpic CDN（过滤统计像素与图标）。视频文章 media_type=video-meta，video_url 记播放页；加密原文件直下仅 L3/exe 可达（video-file）。

## 4. 已知坑表（对齐 Spec §11）

| 坑 | 指纹 | 根因 | 修法 |
|---|---|---|---|
| L1 图片懒加载 | playwright + data-src | 公众号图用 data-src 非 src | 直取 data-src；networkidle + 滚动后再取 HTML |
| L2 ret!=0 / 频率限制 | profile_ext | cookie 过期或被限频 | tenacity 退避 + 重登 cookie；超阈即停 |
| L3 CA 未装 | mitmproxy | 自签 CA 未进受信任根 | 管理员 certutil 预装 + 写前预检（见 l3-setup.md） |
| L3 防火墙拦截 | mitmproxy local 模式 | Defender 挡代理端口（8080） | New-NetFirewallRule 精确放行（见 l3-setup.md） |
| L3 视频加密 URL | mpvideo | 视频 URL 带时效 token | 仅记 metadata + cover，不强抓原文件 |
| 写库 API 名漂移 | library space_api | manifest 名与口头称呼不符 | 以 manifest 实测名为准：space.database.create-database / add-field / batch-add-records / query-database；KB 型容器回退 space.importer.create-doc / space.workspace.submit-doc-edit |

补充坑（实测补充）：KB 型智库节点不被 list-nodes 枚举（BFS 495 节点未命中），写库节点 id 必须运行期 `--library-node` 直传，list-nodes 按标题查找仅作尽力回退（OPEN-DECISIONS #1）。

## 5. 频率与合规

| 项 | 约定 | 出处 |
|---|---|---|
| 请求间隔 | 3–8s 均匀抖动（rate_limit.min/max_delay_seconds，common.sleep_polite） | Spec §10 |
| 单账号单日上限 | 200 篇（rate_limit.max_per_day） | DEFAULT_CONFIG |
| 失败即停 | 连续失败不无限重试，tenacity 超阈停并报告 | AC-06 |
| 合规 | 仅自有/已授权公众号；每次运行打印声明 + 人工确认闸（--yes 或交互输入） | AC-10 |
| 验证码/滑块 | 不绕过，遇验证即停转人工 | Spec §3 |
