# schema.md — 25 列文章记录契约（wechat-article-collector）

> 真源：`scripts/normalize.py`（列定义 COLUMN_CONFIGS / 值映射 to_property_values / 校验 validate_article 的唯一实现）。
> 本文档是语义契约；两者不一致时以代码为准并修订本文。生成日期：2026-10-22。

## 1. 设计词汇 → 平台真实类型映射

平台列类型白名单来自 `library/database/_db_types.py: VALID_TYPE_KEYS`（text/number/currency/select/multi_select/date/checkbox/url/email/phone_number/image/attachment/person），**没有** enum/int/datetime/text[]。映射关系 2026-10-22 实测 manifest 后确定：

| 设计词汇（Spec §6） | 平台类型 key | 映射性质 | 说明 |
|---|---|---|---|
| enum | `select` | 直接映射 | SelectConfig：`{options:[{text}]}`，选项 id 可省略由服务端生成；已存在选项 id 永久有效 |
| datetime | `date` | 直接映射 | DateConfig：`{format:"yyyy-mm-dd hh:mm"}`；写入值 ISO 8601（如 `2026-10-22T10:00:00Z`） |
| int | `number` | 直接映射 | NumberConfig：`{decimalPlaces:0, useSeparate:false}`；写入 `{"number": <int>}` |
| text[] | `text` | **MVP 降级（服务端强制）** | 仅 keyword_tags 用。原设计 `multi_select + options:[]`，2026-10-22 真机 V2 实测被服务端拒绝：`code=11607 spaceengine/database: select/multi_select property requires non-empty options: keyword_tags` —— **空 options 的 select/multi_select 建不出列**。词表未定前用 `text` 存逗号分隔标签（当前恒空，零损失）。升级路径：词表确定后 `update_database_field` 改 multi_select 并回填 |
| url | `text` | **MVP 降级** | 平台 url 列写入值为对象 `{text,link}`，与全链路字符串传输契约不一致，且无筛选增益，故 url/cover_url/video_url 三列降级 text。升级路径：`update_database_field` 改列类型为 url + `to_property_values` 对应 put 改对象结构；列为纯展示列，升级收益低，V2 后按需评估 |

## 2. 25 列总表

★ = 下游主筛选轴（account / publish_time / media_type / keyword_tags）。"可空"指 validate_article 是否容忍缺失：否 = REQUIRED_FIELDS 成员，缺失即 status=fail。

> 注意：`keyword_tags` 当前恒空（四层均未向它传参），四轴实际仅 3 轴可筛；它**不可作为筛选/统计依据**（详见 #20 与 OPEN-DECISIONS B5）。

| # | 列名 | 平台类型 | 可空 | 含义 | 备注 |
|---|---|---|---|---|---|
| 1 | record_id | text | 否 | 业务主键，uuid5(canonical_url) | 幂等去重；与平台系统列 `_id` 区分（§5） |
| 2 | title | text | 否 | 文章标题 | extract.py：og:title → msg_title → h1 |
| 3 | account | text | 否 | 公众号名称 | ★ 主筛选轴；js_name → nickname |
| 4 | account_id | text | 是 | 公众号标识 | __biz（L2 请求参数 / L1·L3 页面 `biz` 变量） |
| 5 | author | text | 是 | 作者 | 页面 `author` 变量 → .rich_media_meta_text |
| 6 | publish_time | date | 是 | 发布时间 | ★ 主筛选轴；页面 `ct` epoch 秒 → UTC ISO |
| 7 | collected_at | date | 否 | 采集时间 | common.now_iso()，UTC Z 后缀 |
| 8 | media_type | select | 否 | 媒体形态 | ★ 主筛选轴；text / video-meta / video-file |
| 9 | collect_layer | select | 否 | 采集层 | url / account / desktop / exe |
| 10 | status | select | 否 | 记录状态 | 仅 ok / partial；fail 不写库（§6） |
| 11 | url | text | 否 | 规范化文章 URL | 设计为 url 列，MVP 降级 text（§1） |
| 12 | cover_url | text | 是 | 封面图 URL | msg_cdn_url → og:image |
| 13 | video_url | text | 是 | 视频播放页 URL | 仅 video-meta/video-file 非空；v.qq.com/mpvideo |
| 14 | digest | text | 是 | 文章摘要 | description meta → msg_desc |
| 15 | body_ref | text | 否 | 正文 HTML 引用 | 指向 `<out>.media/<record_id>.html`（§7）；**exe 层为例外**：指向 `<stem>_<hash8><ext>`（已知降级，见 §7） |
| 16 | body_url | text | 是 | 正文库内 URL | `--import-media` 上传后回填，指向资料库中的归档副本；与 body_ref（本地路径）互补，不替代 |
| 17 | images_count | number | 否 | 正文图片数 | 0 合法；REQUIRED 但不要求非零 |
| 18 | images_ref | text | 是 | 图片清单引用 | count=0 时省略（服务端留空） |
| 19 | videos_count | number | 否 | 视频数 | 0 合法 |
| 20 | videos_ref | text | 是 | 视频清单引用 | count=0 时省略 |
| 21 | keyword_tags | text | 是 | 关键词标签 | ★ 主筛选轴，但**当前恒空**（四层未传参，四轴仅落 3 轴）；**不可作为筛选/统计依据**；后续首选填充来源为 L2 `--keyword` 命中词。列类型为 `text`（逗号分隔）：原 `multi_select + options=[]` 被服务端以 11607 拒绝，见 §1 映射表 |
| 22 | word_count | number | 是 | 正文字数 | CJK 按字 + 拉丁/数字按词（extract._count_words） |
| 23 | license | text | 否 | 授权标识 | 固定 `collector-attestation: authorized-only` |
| 24 | extractor | text | 否 | 提取器标识 | 代码实测值：`l1:playwright` / `l2:profile_ext` / `l3:mitm+uia` / `exe:<exe文件名>`（如 `exe:4.0`） |
| 25 | fidelity | select | 否 | 完整度 | full / partial |

枚举值域（normalize.py 常量）：

| 列 | 值域 |
|---|---|
| media_type | text / video-meta / video-file |
| collect_layer | url / account / desktop / exe |
| status（写库） | ok / partial |
| fidelity | full / partial |

## 3. 去重键规则（canonicalize_url）

规范化后 URL 即去重键；非公众号域名或非法 URL 返回 None（调用方置 fail）。

| 规则 | 行为 |
|---|---|
| 协议 | 缺省补 `https://`；输出恒为 https |
| 域名 | hostname 必须 `mp.weixin.qq.com` 结尾，否则 None |
| 保留参数 | 仅 `__biz`、`mid`、`idx`（按 key 排序后重组） |
| 剥离参数 | `sn`、`chksm`、`utm_*`、`scene`、`src`、`chksm` 等一切其余 query |
| 路径 | 保留原 path（空则 `/`） |
| fragment | 丢弃 |

续采跳过：write 前按 record_id（或规范化 url）对目标表做 `query-database`（filter：text equals）查询，已存在即跳过，不重复写入。

## 4. record_id 幂等规则

- `record_id = uuid5(NAMESPACE_URL, canonical_url)`（build_article 默认派生）：同一文章无论经哪层采集、重复采集多少次，派生结果一致，天然幂等。
- 调用方可显式传 `record_id` 覆盖（如 exe 兜底用自身输出 id 时需先评估冲突）。
- **与平台 `_id` 的区别**：`_id` 是平台为每条记录自动注入的系统列（建表/写入时均不声明）；record_id 是承载 collectId 的**业务主键**，用于 upsert 去重与续采跳过，二者不可互相替代。

## 5. 写库侧不手建系统列

平台自动附加 `_id` / `created` / `updated` / `owner` 等系统列，`create-database` 的 properties 只声明 24 个业务列；总列数 24 + 系统列远低于 50 列上限（§8）。

## 6. 传输 JSONL 行格式

采集层（L1/L2/L3/exe）统一产出 JSONL；status 三态 = `TRANSPORT_STATUSES = ok/partial/fail`，写库二态 = `LIBRARY_STATUSES = ok/partial`。

| 行类型 | 结构 | 写库行为 |
|---|---|---|
| ok | 25 字段完整 JSON 对象，status=ok | 写入 |
| partial | 25 字段对象，status=partial（validate 降级：如 images_count>0 但 images_ref 缺失） | 写入 |
| fail | 至少含 `url` + `fail_reason`（附已获得的字段），status=fail | **不过滤不静默，写库前剔除** |

`fail_reason` 由 validate_article 的 reasons 列表拼接（如 `missing required field: body_ref; invalid url: ...`）。stdout 只留数据行，事件流（含 warn/error）走 stderr（common.emit_event）。

进程退出码（common.py，与事件 level 1:1）：

| 退出码 | 含义 |
|---|---|
| 0 | ok / info |
| 2 | 参数错误 |
| 3 | 运行错误 |
| 4 | 合规拦截（未确认授权） |
| 5 | 部分完成（partial） |
| 6 | 环境缺失（依赖/CA/防火墙等预检失败） |

边界情形（B1 裁定）：
- **零产出（全 fail）**：`total>0 且 ok==0 且 partial==0` → `3`（error）+ 对应层 `*.zero_yield` 事件。
- **账号合法但零文章**：`total==0`（ret==0 且无记录）→ `0` + `l2.empty` warn（不误判为失败）。
- **部分完成**：`partial>0`（有成功也有失败）→ 仍为 `5`；不因个别失败升级为 3。

## 7. 媒体目录约定

媒体目录默认取 `<out 去扩展名>.media/`（如 `out/v1.jsonl` → `out/v1.media/`；`--out` 省略时为 `./wechat-collected-media/`；可用 `--media-dir` 覆盖；L1/L3 同规则，代码实测）。

| 文件 | 引用列 | 内容 |
|---|---|---|
| `<media>/<record_id>.html` | body_ref | 正文 HTML（div#js_content 内容；L3 为由 mitm 捕获目录按 record_id 转存）。**exe 层已知降级**：body_ref 指向 `<stem>_<hash8><ext>`（exe 输入为结构化数据、无 HTML 正文；硬造 `<record_id>.html` 会污染"body_ref 指向可读正文"语义，故按已知降级处理，非缺陷） |
| `<media>/<record_id>.media.json` | images_ref / videos_ref | `{"images":[{"url","local_path"}], "videos":[{"url","local_path"}]}` 清单 |
| `<media>/images/<record_id>/<序号>.<ext>` | （清单内 local_path 指向） | 图片原文件（L1/L3 均下载；扩展名推断 wx_fmt > mmbiz_* 目录标记 > 路径后缀 > jpg，实现在 `common.guess_image_ext`） |

- count=0 时对应 ref 为 NULL（to_property_values 省略空值，服务端留空）。
- images_ref 与 videos_ref 可指向同一 manifest（build_article 的 media_ref 单参双用）；两者任一非空即写。
- 媒体先落本地，写库后经 `import-local-file` 入库回填（Spec §6）；库内只存轻量列 + ref，不存大文件。
- **单图失败不致命**：该条只写 `url`、不带 `local_path`，整篇 status 降级 `partial` 并在 `fail_reason` 记明（L1/L3 一致）。
- **跨层图片 URL 不可互换**（2026-10-22 实测）：同一篇文章经 L1（Playwright）与 L3（mitmproxy，微信内打开）采集，各 7 张图、数量一致，但 URL 集合**交集为 0**——微信按客户端返回不同 CDN 变体（抽检两侧 URL 均 `200 image/png`，均非坏链）。因此：① 不要用"URL 是否相同"判断两层是否采到同一篇（应比 `record_id` / 正文纯文本）；② 两层各自下载自己那套图，不做跨层去重或互补。

## 8. 表限额与建列方式

平台硬限额（library/database/params-reference.md §Limits，实测 2026-10-22）：

| 限额 | 值 | 超限错误码 |
|---|---|---|
| 单表最大行数 | 10,000 | 56150 |
| 单表最大列数 | 50 | 56152 |
| 单行最大体积 | 1 MB | 56153 |

- 24 业务列 + 系统列远低于 50；正文/媒体不入库（只存 ref）天然满足 1MB/行；行数超 1 万需分表（database_name_prefix + 序号）。
- **建列方式**：`create-database` 用 properties 数组一次建全 25 列（name + config 逐项对应 §2 表）；`add-field` 仅用于事后补列（如 keyword_tags 之外的标签化扩展）。写入前先 `--dry-run` 核对 payload。

create-database properties 片段示例（完整 24 项见 normalize.py COLUMN_CONFIGS）：

```json
{"name": "record_id", "config": {"text": ""}}
{"name": "publish_time", "config": {"date": {"format": "yyyy-mm-dd hh:mm"}}}
{"name": "media_type", "config": {"select": {"options": [{"text": "text"}, {"text": "video-meta"}, {"text": "video-file"}]}}}
{"name": "images_count", "config": {"number": {"decimalPlaces": 0, "useSeparate": false}}}
{"name": "keyword_tags", "config": {"text": ""}}
```

## 9. space_api.py CLI 调用要点（2026-10-22 实测）

写库层统一经 library skill 的 `space_api.py` 转发（`config.library.api_cli` 指向它）。三个必须遵守的实测结论：

| 要点 | 正确做法 | 反例 / 后果 |
|---|---|---|
| payload 传递 | `--stdin` 是 `store_true` 标志：payload 必须写子进程 stdin，如 `subprocess.run([sys.executable, api_cli, api, "--stdin"], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True)` | 把 JSON 作为 argv 元素（`[..., "--stdin", json]`）会报 `unexpected argument: [REQUEST_BODY_REDACTED]` |
| 成败判定 | `error_exit()` 默认退出码 **0**，失败时 stdout 输出 `{"error": "..."}`；必须解析 stdout 的 `error` 键，returncode 不可信 | 只看 returncode 会把失败当成功（随后 `data` 缺失才暴露） |
| 批次体积 | payload 走 stdin 无长度限制 | Windows 命令行上限 32,767 字符，50–100 条 `batch-add-records` 走 argv 会超限 |

其它约定：

- 调用形态 `python space_api.py <api 名> --stdin`；stdout 为 `{"api": ..., "data": ...}`（`data` 必为对象；`error` 信封仅失败时出现）；`data` 缺失或非对象即视为失败。
- `create-database` 的 `data.id` 即 databaseId，`data.url` 供汇报；`properties` 一次建全 25 列（§8）。
- 复用已有表用 `--database-id`（跳过 create-database 与节点解析），避免重复实跑在云端堆出多张同名表；`--dry-run` 不触发任何写调用。
- 表限额同 §8（10,000 行 / 50 列 / 单行 1 MB）。
