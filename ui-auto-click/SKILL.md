---
name: ui-auto-click
description: 把人工在桌面软件上的点击流程固化为可复现的自动点击步骤表。用 Windows UIA 模式驱动控件，不抢焦点、不误点；支持干跑定位、可逆自检与证据留痕。内置公众号文章采集清洗到入库导站的一条命令全链路。
license: Proprietary
compatibility: Python 3.9+; 浏览器（内置 IAB 或浏览器扩展）; 需网络访问.
---

# ui-auto-click · 桌面自动点击

把一段人工操作（例如视频教程里演示的流程）变成**可复现、可核对、可回滚**的步骤表。

## 什么时候用

- 有个桌面软件要按固定顺序点若干下（填参数 → 点按钮 → 等结果 → 开目录）。
- 你手上有教程视频/截图，想把里面的操作固化下来反复用。
- 已有的 RPA 脚本一点就崩：因为用鼠标坐标点，窗口一换位置就点错。

## 四条硬规则（血泪换来）

1. **模式优先，鼠标垫底**
   `Invoke` / `Toggle` / `SetValue` 直接进控件，**不需要窗口在前台、甚至最小化也能用**。
   `click_input` 是真实鼠标：实测在目标窗口被全屏程序盖住时，点击落到了前台窗口上（差点点到别人的游戏里）。
   所以 `click` 动作默认禁用，必须显式声明且先通过前台校验。
2. **`automation_id` 优先于控件名**
   控件文字会随版本改，`automation_id`（如 `Form.PushButton`）通常稳定。选择器写 `auto_id` 为主、`name` 兜底。
   注意：引擎是**枚举后代再在 Python 侧精确比对 `automation_id`**——不要试图把它当 `descendants()` 的参数传下去（见避坑）。
3. **认控件靠证据，不靠名字联想**
   `PlainTextEdit` 不一定是日志框、`TextEdit` 也可能是日志区。判断依据是**尺寸 + 读出来的内容**：
   能读出"使用教程：…"的那个才是日志区。指错了控件，`wait_log` 只会静默超时。
4. **先干跑，再动手**
   `--dry-run` 只做定位并打印"命中了哪个控件的哪个位置、现值多少"；`verify` 做可逆动作（勾选→取消→还原）并回读。
   两者都过了才 `run --yes`。

## 用法

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/Administrator/.workbuddy/skills/ui-auto-click"

# 1) 侦察：列出目标窗口里所有可交互控件（auto_id / 类型 / 当前状态）
"$PY" "$SK/scripts/clicker.py" probe --window-regex "公众号.*下载工具"

# 2) 干跑：只定位 + 打印将执行的每一步，不动控件
"$PY" "$SK/scripts/clicker.py" run --profile wechat_batch_downloader --dry-run

# 3) 可逆自检：把 flags 里的复选框开→关→回原状，回读确认
"$PY" "$SK/scripts/clicker.py" verify --profile wechat_batch_downloader

# 4) 真执行（写操作，必须 --yes）
"$PY" "$SK/scripts/clicker.py" run --profile wechat_batch_downloader --yes

# 分段推进：--max-steps 跑到第 N 步，--from-step 从第 N 步开始（避免重复点有副作用的按钮）
"$PY" "$SK/scripts/clicker.py" run --profile wechat_batch_downloader --yes --max-steps 12
"$PY" "$SK/scripts/clicker.py" run --profile wechat_batch_downloader --yes --from-step 13
```

## 内置流程

| profile | 说明 |
|---|---|
| `wechat_batch_downloader` | 「微信公众号文章批量下载工具」（长风998，2.4/4.0）：获取公众号id → 等密钥 → 批量下载 → 文件落盘 → 截图留证（18 步）。流程取自视频教程复刻 + 真机校准，控件映射与真执行记录见 `references/wechat-batch-downloader-flow.md`、`out/run-20261022.md` |

> 2026-10-22 真机跑通：103 篇文章 / 1487 个文件 / 309 MB，落在 `C:\Users\Administrator\Desktop\下载\食品研发与生产\`。
> 导出目录目前写死本机，接「铭衍·元典」智库的方案见 `out/run-20261022.md` §5（作为独立上传阶段，不与下载流程耦合）。

## 一条命令跑完全链路（采集 → 入库 → 导出）

`scripts/pipeline.py` 把「下载 → 清洗 → 补元数据 → 打包 → 写智库 → 重建入口页 → 导站点 → 校验」
编排成 11 个阶段。**任务目标就是公众号名称**，它同时决定下载目录名，换个号只改这一个参数。

### 前置：人工只做 3 步（脚本无法代劳，因为密钥来自微信客户端）

1. 在**微信 PC 端**打开目标公众号，随便点开一篇文章；
2. 右上角「…」→ **复制链接**；
3. 粘进下载工具的「文章下载」框，**点一次下载**（让工具拿到该号的 `__biz`/密钥）。

> 不做这 3 步，`download` 阶段必然报「无新增 md」。脚本会在 preflight 里明确提示
> 「微信 PC 端：未检测到」。

### 命令

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/Administrator/.workbuddy/skills/ui-auto-click"

# 只看计划 + 环境检查（只读；preflight 与 verify 会真跑，其余标「跳过」）
"$PY" "$SK/scripts/pipeline.py" --account "食品研发与生产" --plan

# 全跑（写操作必须 --yes）
"$PY" "$SK/scripts/pipeline.py" --account "食品研发与生产" --yes

# 跳过某几段 / 从某个失败点续跑（断点续跑是设计目标，不会重复写库）
"$PY" "$SK/scripts/pipeline.py" --account "食品研发与生产" --yes --skip download,export
"$PY" "$SK/scripts/pipeline.py" --account "食品研发与生产" --yes --from-step manifest
```

| 参数 | 说明 |
|---|---|
| `--account` | **必填**。公众号名称 = 任务目标 = `桌面\下载\<名称>\` 目录名 |
| `--base` | 下载根目录，默认 `桌面\下载` |
| `--vein` | 元典工作区，默认 `D:\...\2026-10-16-21-12-03` |
| `--exe` | 下载工具路径；需要时脚本会**以正确的 cwd 启动它**（产物才会落到 `--account` 目录） |
| `--from-step` / `--to-step` / `--skip` | 阶段级断点与裁剪 |
| `--return-key` | scout 点开文章后是否回列表：默认 `none`（把文章页留给 download），单独跑 scout 想回列表用 `ctrlw` |
| `--dry` / `--plan` | 只跑只读阶段 |
| `--yes` | 确认执行写操作 |

### 11 个阶段

| 阶段 | 做什么 | 判成功的依据 |
|---|---|---|
| `preflight` | 查目录 / 微信 / 工具窗口 / 元典三件套 / node / python | 缺什么直接报缺，不猜 |
| `download` | 启动或附着下载工具 → `clicker run` | **新增 md > 0**；空壳 > 30% 打警告 |
| `clean` | 图片路径本地化 + 清微信 UI 噪声 | 幂等，先备份 |
| `manifest` | 生成入库清单（继承旧元数据，不清零） | `missing_metadata` |
| `meta` | 补原文链接 / 公众号 / 发表日期 | 三件套非空数 |
| `package` | 打 `articles.ndjson` + 12 项回读核对 | 12 项全绿，否则报出**具体哪几项** |
| `ingest` | 写 vault（source 笔记 + 分类 JSON） | 写入数；正则失配时退回数 vault 实数 |
| `maps` | 重建「智库链接模块」 | 写入行数 |
| `derived` | 重建 Home / hot / log / canvas / orphans | `hotlog` 未收敛属设计（流水每跑必变） |
| `export` | 导出静态站点 | 文件数 + 内容指纹 |
| `verify` | `validate.py --self-test` | `VERDICT: PASS`，且**笔记数 == 分类条目数** |

> **判成功只看产物，不看日志和 toast。** 工具会弹「下载成功！」但正文其实没抓到；
> 所以 `download` 以文件数与空壳比例为准，`package` 以 12 项核对为准。

### 常见中断与处置

| 现象 | 原因 | 处置 |
|---|---|---|
| `无新增 md` | 没在微信里先打开该号文章 / 工具保存目录不对 / 时间范围设置不对 | 补做前置 3 步，或改工具的保存目录后 `--from-step download` |
| 日志卡在「开始获取密钥...」很久没有下文 | **工具启动时的 cwd 不是 exe 所在目录**（2026-10-23 二分：cwd=exe 目录 3/3 成功，cwd=下载目录/空目录 3/3 失败；与缓存体积、目录内容无关） | 一律用 `cwd=exe.parent` 启动工具；`stage_download` 已固定这样，手工启动时别在别的目录里双击 |
| 反复刷「请先在微信打开复制的链接」 | 点「1.获取公众号id」时微信**已经停在** profile_ext 页，之后没有真实导航；工具只在点 id 之后读一次当前页 | 保留 profile 第 18 步「预热」：点 id **之前**先把微信导到该号**文章页**，点 id **之后**再导到 profile_ext。顺序反了（点 id 后才预热）会刷一次「开始获取密钥」然后死等 |
| 点了按钮但目标软件毫无反应 | **坐标系不一致**：clicker 没做 DPI 感知时 UIA 给物理像素、`GetWindowRect` 给逻辑像素 | 已内置 `_ensure_dpi_aware()`（import 时执行）＋ 点击点必须落在窗口矩形内的守卫；出现该报错说明两个坐标系仍不一致，别绕过 |
| 工具日志只刷「可以把梯子关了试一试」 | 子进程继承了 `HTTP(S)_PROXY`（WorkBuddy 内部代理），工具以为用户开了梯子 | `stage_download` 已用 `_clean_env()` 剥掉代理变量；手工启动工具时也要在无代理的 shell 里启 |
| 工具进程几分钟后自己退出 | 取 id 失败后工具自行退出（闭源行为），本次无法绕过 | 重开工具后从 `--from-step download` 续跑；连续失败请人工用工具跑一次确认可用 |
| `pywinauto` 缺失 / 阶段内 `SystemExit(6)` | 当前解释器是裸 `versions\x\python.exe`，没装依赖 | 用 `envs\default\Scripts\python.exe` 跑（pipeline 会自动切换，也可 `set UIAC_PY=`） |
| `超短篇均已打标` 失败 | 图片型文章（正文是长图）字数天然极低 | 已改为 `build_manifest` **自动判定**（有图→`image_only_content`，无图→`short_text`），无需人工标记 |
| 导出指纹变了 | `derived` 改写了 `log.md`（操作流水） | 属设计；只验证幂等时连跑两次 `export`，指纹应完全相同 |


### 需要细节时再读

scout 逐篇发现与步骤表 YAML 格式的完整说明在 references/，按当前任务选一篇读：

| 内容 | 何时读 | 文件 |
|------|--------|------|
| 赞和收藏逐篇发现（scout） | 要自动遍历「我已点赞」、判断该篇是否已采集时 | `references/scout.md` |
| 步骤表 YAML 写法 | 要写或改批量任务的步骤表时 | `references/step-table.md` |
| 逐篇点击流程（设计与取证） | 要弄清为什么不能用控件树、看真机标定细节时 | `references/wechat-favorites-flow.md` |
| 七步串联（设计与标定） | 要看七步链路的原始设计与标定数据时 | `references/wechat-favorites-to-download.md` |
| 视频教程流程复刻 | 要对照原始视频教程的完整链路时 | `references/wechat-batch-downloader-flow.md` |

## 赞和收藏 → 复制链接 → 获取公众号id → 批量下载（七步串联）

scout 只负责"点开哪一篇"，**下载工具那半段要人接**。`favorites_chain.py` 把两半接起来，
一条命令走完用户口述的整套人工操作：

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

"$PY" scripts/favorites_chain.py --dry-run --max 3              # 只看选行计划，零点击
"$PY" scripts/favorites_chain.py --max 1 --yes --skip-download  # 只验微信侧（1~2 步）
"$PY" scripts/favorites_chain.py --max 3 --yes                  # 整链路（会真的开始下载）
```

七步落点：点列表行 → 点标签栏「⊙」→ 菜单「复制链接」→ 读剪贴板得文章链接 →
交给 `clicker.py run --profile wechat_batch_downloader --var ARTICLE_URL=… --var RANGE=all`（该 profile
内部完成"填链接 / 选时间范围 / 点获取公众号id / 放大镜打开 / 点批量下载"）→ 写台账。

下载工具的时间范围由 `RANGE` 决定：`all`＝全部历史（默认，批量采集一个号必须用这个）、
`monthly`＝一个月内。`favorites_chain.py --range` 与 `pipeline.py --range` 都透传它；
**不传也是 all**，但命令行里显式出现才查得出"这批是按什么口径抓的"。

标定与真机坐标见 `references/wechat-favorites-to-download.md`。三个反直觉点：

1. **必须补第 8 步"切回列表页"**：下载工具用放大镜打开了 profile_ext 页面，跑完微信
   停在那个页面。`--max>1` 时下一轮第一步就是判页 → 直接"不在列表页"退出，表现成
   "只处理了第一篇"。`restore_list()` 只在**当前不是列表页**时按**一次** Ctrl+W
   （多按可能把列表页本身关掉）。
2. **journal 的 `decision` 只有整条链路成功才记 `click`**：`processed_fingerprints` 只认
   `click`，语义是"这行永远不再处理"。拿到链接就记 click ⇒ 下载工具失败的那篇下次被
   静默跳过（漏采且无人发现）。故 `link_ok / download_failed / not_opened / failed`
   一律不参与去重，重跑会重试。
3. **台账只在真下载成功时写**：预演、`--skip-download`、失败都不写。台账是"已采集"
   记录，写进去会和实际产物对不上。

## 采集台账（favorites-ledger）

每个号一行，记录文章链接、获取到的 `profile_ext` 网址、来源公众号、信息类型标签。

```bash
"$PY" scripts/ledger.py add --url "https://mp.weixin.qq.com/s/xxx" --profile-url "https://mp.weixin.qq.com/mp/profile_ext?...&__biz=..."
"$PY" scripts/ledger.py export          # 重新生成 docs/favorites-ledger.md
"$PY" scripts/ledger.py list --tag 宠物食品 --limit 20
"$PY" scripts/ledger.py tags            # 打印标签体系与命中关键词
```

- 落盘：`out/favorites-ledger.csv`（`utf-8-sig`，Excel 双击不乱码）+ `docs/favorites-ledger.md`（表格 + 标签分布）。
- **去重主键优先 `profile_ext`**：同一号的不同文章 profile_ext 是同一条 ⇒ 一个号收藏
  5 篇只出一行，其余链接收进备注「同号文章」清单。
- 标签固定 9 类 + `其他` 兜底：宠物食品 / 添加剂 / 乳化剂 / 原料 / 法规标准 /
  检测认证 / 行业信息 / 趋势 / AI。NFKC 归一化，全角 `ＧＢ２８０５０—２０２５`、
  `GB28050-2025`、小写 `haccp` 均命中。
- `account`/`title` 留空时会联网抓元信息（失败留空，不编），故一般不必手工传。

## 多公众号 × 逐月回溯（monthly-rollback）

按「一个月一窗」批量采集多个公众号的历史文章：**当期所有号都采满，窗口才整体
往前推一个月**，如此逐月回溯到下限为止。

```bash
"$PY" scripts/monthly_rollback.py init \
    --account "食品研发与生产=https://mp.weixin.qq.com/s/xxxx" \
    --account "宠物食品研发号A=https://mp.weixin.qq.com/s/yyyy"
"$PY" scripts/monthly_rollback.py status      # 窗口矩阵：每个号在这个月什么状态
"$PY" scripts/monthly_rollback.py next        # 下一个任务（JSON，供外部编排）
"$PY" scripts/monthly_rollback.py run --yes   # 自动推进：next → 下载 → mark
"$PY" scripts/monthly_rollback.py run --dry-run   # 只看将执行的命令
```

**闸门（这就是"先检查所有号"那条要求）**：窗口只在**该窗所有号都 done** 时关闭；
任何号失败/重试中都不推窗。任务失败按 `--max-attempts`（默认 3）重试，超限则
整体 `blocked`（退出码 7），**绝不跳过该号去推窗**——否则会出现"号 A 已回溯到
2024、号 B 还停在 2026"的错位，之后再也对不齐。

| 概念 | 说明 |
|---|---|
| 窗口 | **闭区间**，`W0001` 是最新一窗。相邻窗在边界日**重叠一天**（宁可重不漏） |
| rolling（默认） | `W0=[anchor-1月, anchor]`，符合"最近一个月内"的字面口径 |
| calendar | `W0=[本月1日, anchor]`，按自然月切，便于按「2026-10 这一窗」对账 |
| anchor | init 时**固化写进状态**。若每次用"今天"重算，隔天再跑窗口会漂移、已采月份被重复劳动 |
| 刹车 | `--max-windows`（默认 24）与 `--stop-before`（默认 2020-01-01）双闸，不会无限往回爬 |

- 落盘：`--state`（默认 `out/monthly_rollback/state.json`，原子写）。**正式用请指到数据目录**，
  产物不留在技能目录。
- 日期怎么设的：`RANGE=custom` + `DATE_START/DATE_END` → profile 的 `set_date` 动作。
  日期框是 Qt `QDateEdit`，**UIA SetValue 假成功、逐字符输入被吞**（2026-11-01 真机三条
  写法全部无变化），可靠通道只有「点进控件 → Ctrl+A → Ctrl+V」，已封装。
- `article_url` 必填：`1.获取公众号id` 要求微信里先打开该号文章；缺链接时工具不写日志、
  必然超时，`run` 会直接拦下（确需硬跑加 `--allow-no-url`）。
- 重跑某一窗：`rewind --window W0002`（该窗所有任务回 pending，窗口回 active）。
- 完整时序、状态文件字段、三种非正常态处置：`references/monthly-rollback.md`。
- 它只管"哪段日期、跑哪个号"，下载仍交给 `clicker.py`；清洗入库照旧跑
  `pipeline.py --from-step clean`。

## 退出码

| 码 | 含义 |
|---|---|
| 7 | 被阻塞：有任务重试超限，需人工介入（`monthly_rollback run/next`） |
|---|---|
| 0 | 全部步骤成功 |
| 2 | 参数/步骤表非法 |
| 3 | 执行失败（定位不到控件、等日志超时、断言不成立） |
| 5 | 部分成功（有 warn 级步骤/可选步骤失败但流程走完；`verify` 有控件因禁用被跳过也是 5） |
| 6 | 环境不具备（pywinauto 缺失 / 窗口不存在） |

## 省时技巧

- `probe` 的输出直接拿来写步骤表：`auto_id` 抄进去就是稳定选择器，比截图量坐标快十倍。
- 先用 `--max-steps N` 分段跑，确认前 N 步无误再放开整条流程，比一次跑完再排错省时间。
- 日志区就是天然的进度信号：把 `wait_log` 的 `contains_any` 写成工具自己输出的成功话术，比 `sleep 30` 稳得多；
  若日志控件不暴露文本，退到 `wait_file` 用落盘文件当证据。
- 截图走 `PrintWindow`（引擎内置）：窗口被遮挡或最小化也能抓对，不会再抓到前台别的程序。

## 避坑提示

1. **别用鼠标点击被遮挡的窗口**。`click_input` 是按屏幕坐标发真实鼠标事件，目标窗口一旦被别的窗口盖住，
   点击会落到最上层窗口上——实测在目标窗口被全屏程序遮挡时，点击打到了前台的全屏应用里。
   引擎会校验 `GetForegroundWindow` 才允许点。
2. **按钮的 `invoke` 可能是"假成功"**：`qfluentwidgets` 的按钮 `invoke()` 不报错但什么也不发生
   （最小化/恢复/置前三种状态实测均无效，日志一字未变）。改 `activate` + `click` 后立刻有反应。
   判断依据只能看**副作用**（日志/文件/控件状态），不能看"没抛异常"。
3. **按钮文字会随状态变**（`2.批量下载文章` ↔ `暂停中...`）。要点之前先 `wait_control` 等它变回来，
   否则会点在"暂停中"上。注意 `expect_name` / `expect_name_regex` 才是期望的控件文字，
   步骤顶层的 `name` 是步骤名，两者别搞混。
4. **`pywinauto 0.6.9` 的 `descendants()` 不认 `auto_id`**：`IUIA.build_condition()` 只支持
   process / class_name / title / control_type / content_only。传 `auto_id=` 抛的 TypeError 会被
   "选择器列表兜底"吞掉 → auto_id 静默失效、退到 `index` 命中**错误控件**
   （实测把"等待时间"写进了日志框）。引擎已改为枚举后在 Python 侧比对 `automation_id`。
5. **窗口标题在 UIA 侧会变**（中文标题 ↔ 进程名 `wechatdownload`），所以匹配以 `classes` 为准。
6. **最小化时 UIA 坐标是垃圾**（实测 `-31948,-31426`），但 `invoke`/`toggle` 照常生效 —— 别拿坐标判对错。
7. **控件被禁用 ≠ 已是目标态**。灰掉的复选框点了没反应，旧版引擎会把它记成"已是目标态"的假成功；
   现在会直接报"控件已禁用"。`verify` 遇到禁用控件记为**跳过**（退出码 5），不算失败。
8. **限速暂停别当成"跑完了"**：日志可能"暂停19秒，防止访问被限制"。判定结束要用
   "目标控件空闲 + 日志 60 秒零增长"，15 秒的窗口不够。
9. **最小化时 PrintWindow 只抓到标题栏**（232×26 废图）。引擎已改为"临时恢复→抓图→还原最小化"，
   并对异常尺寸直接拒图。
