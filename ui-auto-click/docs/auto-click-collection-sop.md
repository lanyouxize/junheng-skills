# 自动点击采集流程规范（SOP）

> 适用技能：`ui-auto-click`（桌面软件自动点击 RPA）
> 目标：驱动「微信 PC 4.x」+「微信公众号文章批量下载工具 4.0」两个桌面程序，
> 把公众号文章（单号批量 / 赞和收藏逐篇）下载到
> `C:\Users\Administrator\Desktop\下载\<号名>\`。
> 本规范严格对齐代码（`pipeline.py` / `favorites_chain.py` / `wechat_favorites.py` /
> `clicker.py` / `capture_templates.py`），不凭空描述。

---

## 0. 一句话总览

自动点击 ≠ 鼠标乱点。它要求：**微信前台可见且停在特定页面**、**下载工具已开**、
**模板已校准**，然后「先干跑（`--dry-run`）验证页面状态 → 再 `--yes` 真跑」。
判成功**只看产物**，不靠日志/toast。

---

## 1. 三种执行路径

| 路径 | 入口 | 用途 | 是否需要微信在「赞和收藏」页 |
|---|---|---|---|
| A 单号批量 | `clicker.py run --profile wechat_batch_downloader` | 已知公众号名，直接驱动下载工具拉全历史 | 否（需该号任一文章页已打开） |
| B 赞和收藏逐篇（主流程） | `favorites_chain.py` | 七步串联，跨微信+下载工具，自动逐篇采集收藏 | **是（硬要求）** |
| C scout 发现 | `wechat_favorites.py` | 基于已采集名单，只点没采过的号 | 是 |
| D 全链路编排 | `pipeline.py` | 采集→清洗→入库元典→站点（14 阶段） | 视起点阶段 |

> 日常「采集」用 **B** 或 **A** 即可达成（落盘到 `Desktop\下载`）。
> **D** 的入库下游（ingest→verify）依赖元典 vault，当前有独立问题（见 §8），纯采集不受影响。

---

## 2. 硬前置（必须人工满足，脚本只校验不替你做）

### 2.1 软件（一次到位）
- 微信 PC 已安装并登录（`WeChat.exe` 或 `Weixin.exe` 进程在跑）。
- 下载工具 4.0 在桌面：`C:/Users/Administrator/Desktop/微信公众号批量下载工具4.0.exe`。
- `pywinauto` 装在 `envs/default`（`pipeline._pick_python()` 会自动挑出能 import 的解释器）。

### 2.2 运行态（最常漏，脚本会拒绝执行）
- 微信必须 **前台可见、未最小化、不被其他窗口遮挡**，且停在 **「赞和收藏」列表页**
  （进入路径：微信 → 公众号 → 个人中心 → 赞和收藏）。
- 这是 `favorites_chain.py` / `wechat_favorites.py` 的硬闸门：`ensure_window()` 找不到微信窗口返回
  `EXIT_ENV=6`；页面不在「赞和收藏」页返回 `EXIT_ERROR=3`（`chain.wrong_page`）。
- 落点护栏：`assert_point_belongs()` 校验鼠标点击的顶层窗口归属，被遮挡会
  **fail-closed 拒绝点击**（曾误点到 Wise Care 365），所以微信必须露出屏幕可见区域。

### 2.3 人工 3 步（首次 / 换号必做）
1. 微信打开该公众号**任意一篇**文章；
2. 复制该文章链接；
3. 粘进下载工具顶部的「微信文章链接」框（`Form.PlainTextEdit`）并点一次「1.获取公众号id」，
   让工具拿到该号 `__biz` / 密钥。

### 2.4 会话环境
- 必须是有窗口站的会话（RDP / 控制台），不能是纯无头。`DISPLAY` 环境变量在 Windows 上无意义，
  以 `tasklist` 里能否看到微信进程、脚本能否 `find_windows` 到窗口为准。

---

## 3. 环境自检闸门（先干跑，再动手）

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
cd "C:/Users/Administrator/.workbuddy/skills/ui-auto-click"

# (1) 下载工具窗口 + 微信状态 + 依赖（只读）
"$PY" scripts/pipeline.py --plan --account "食品研发与生产"
#     preflight 会报「微信 PC 端：在运行 / 未检测到」「下载工具：已在运行 / 未运行」

# (2) 页面判定模板是否可靠（scout / 主流程 wrong_page 判据用）
"$PY" scripts/capture_templates.py --verify
#     若 templates/page-title.png 缺失 → 先跑校准（见 §7.10）

# (3) 采集前必跑只读（只判页 / 选行 / 打印计划，不点击不下载）
"$PY" scripts/favorites_chain.py --dry-run --max 1
#     → 看到 chain.wrong_page：回到 §2.2 把页面摆好再跑
#     → 看到 chain.would_click：可以真跑
```

> ⚠ `favorites_chain.py` 自身**没有** pipeline 那种「解释器缺 pywinauto 自动 re-exec」逻辑，
> 必须用上面 `$PY`（envs/default）直接跑，否则模块顶层 import 会失败。

---

## 4. 标准命令序列

### 4.1 路径 B（推荐：赞和收藏逐篇）
```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
cd "C:/Users/Administrator/.workbuddy/skills/ui-auto-click"

# 0) 只读验证（见 §3）
"$PY" scripts/favorites_chain.py --dry-run --max 1

# 1) 先只验证微信侧：拿到文章链接但不调用下载工具
"$PY" scripts/favorites_chain.py --max 1 --yes --skip-download

# 2) 整链路真跑（一篇；默认 range=all 全历史）
"$PY" scripts/favorites_chain.py --max 1 --yes

# 3) 批量（N 篇；只追新用 --range monthly）
"$PY" scripts/favorites_chain.py --max 20 --yes
```

参数（对齐 `favorites_chain.py:1066`）：
- `--max N`：本次最多处理几篇（默认 1）。
- `--range all|monthly`：下载工具时间范围。**批量取全历史必须 `all`**，`monthly` 会把更早篇目静默漏掉。
- `--skip-download`：只验证微信侧 1~2 步，不下载、不写台账。
- `--ignore-ledger`：忽略账号级去重，强制重下已有号。
- `--journal`：跨次运行去重台账（默认 `out/favorites-chain-journal.jsonl`）。

### 4.2 路径 A（已知号，直接驱动下载工具）
```bash
# 只读先验证控件命中（15~33 步全部命中）
"$PY" scripts/clicker.py run --profile wechat_batch_downloader --dry-run

# 真跑：链接要「全格式」，短链会取 id 失败
"$PY" scripts/clicker.py run --profile wechat_batch_downloader \
      --var ARTICLE_URL="https://mp.weixin.qq.com/s?__biz=...&mid=...&idx=...&sn=...#rd" \
      --var RANGE=all --yes
```
要点（对齐 `references/wechat-batch-downloader-flow.md`）：
- 链接需**全格式**（`/s?__biz=...&sn=...`），短链 `/s/<short>` 会退化成「未知错误」页 → 取 id 失败。
- 取 id 失败工具会**自行退出进程**，所以「启动→步骤→读日志」必须在同一条命令里。
- `pipeline.stage_download` 已固定 cwd = exe 目录（否则取不到密钥）；`pipeline._clean_env()` 已剥代理。

### 4.3 路径 D（全链路，含入库）
```bash
"$PY" scripts/pipeline.py --account "食品研发与生产" --plan           # 只读预检
"$PY" scripts/pipeline.py --account "食品研发与生产" --yes            # 全跑
"$PY" scripts/pipeline.py --account "X" --yes --from-step clean      # 断点续跑
"$PY" scripts/pipeline.py --account "X" --yes --skip download,export # 跳过某阶段
```
⚠ `--vein` 必须指向**真实**元典工作区。脚本默认 `D:/workbuddy重做系统后版本/2026-10-16-21-12-03`
已过期，且当前该 vault 的 `verify` 阶段因 21 处失效引用 FAIL（见 §8）。**纯采集只跑到
`download` 阶段即可；要入库必须先修元典。**

---

## 5. 判成功依据（只看产物，不信日志/toast）

- **download 阶段**：新增 `*.md` 数 > 0，且空壳（<400B）比例 < 30%（`pipeline.stage_download`）。
  工具弹「下载成功！」但正文没抓到 → 仍判失败。
- **favorites_chain**：退出码 0/5，且 `out/favorites-chain-journal.jsonl` 里该篇 `decision=click`，
  台账 `docs/favorites-ledger.md` 新增一行（仅真下载成功才记账）。
- **落盘位置**：`C:\Users\Administrator\Desktop\下载\<号名>\`（平铺：标题.md|html|mhtml + `图片/` + `封面/`）。

---

## 6. 退出码

`favorites_chain.py` / `wechat_favorites.py` / `clicker.py`：
- `0` ok　`2` 参数错　`3` 执行失败　`5` 部分成功（有 optional 步骤失败，如「导出HTML文件」勾选框本机恒禁用）　`6` 环境不具备（没微信窗口）

`pipeline.py`：
- `0` 全链路完成　`1` 中断于某阶段（用 `--from-step` 续跑）　`2` 参数错 / 缺写闸门（`--yes`）

---

## 7. 必读避坑（来自代码与真机，照做即可避）

1. **微信 4.x 是 CEF 自绘**，UIA/MSAA 都读不到界面内容 → 只能「截图+模板匹配+坐标点击」
   （`wechat_favorites.py` 设计说明）。
2. **落点护栏**：鼠标点击前 `assert_point_belongs` 校验顶层窗口归属，被遮挡即 fail-closed
   （曾点到 Wise Care 365）→ 微信必须露出可见区。
3. **⊙ 坐标随标签标题长度变** → 用 `wechat-more.png` 模板，失配才退回 (997,44) 兜底；
   「复制链接」用 `wechat-copy-link.png` 模板，**绝不**按菜单第 N 行数（会误点「刷新」）。
4. **三条不变式**：每轮重新截图（D1）、行指纹去重（D2）、先离页再认页（D3）。
5. **启动下载工具 cwd 必须是 exe 目录**（`pipeline.stage_download` 已固定），否则取不到密钥；
   产物目录不受 cwd 影响。
6. **剥代理 + 正向判据**：`pipeline._clean_env()` 已做；取 id 失败日志刷「可以把梯子关了试一试」
   是 hint 不是终态，正向判据用「获取公众号历史消息页面成功」。
7. **取密钥三步**：工具给 `profile_ext` → 点微信标题栏**最左**放大镜 → `Ctrl+V`+`Enter`
   （`wechat_open_url.py` 的 `open_url`）。
8. **短链失效、全格式稳定**；工具取 id 失败会自行退出进程 → 启动→步骤→读日志必须在同一条命令。
9. **账号级去重**：收藏里同号多篇文章会让整号历史下 N 遍；`profile_ext` 在「获取密钥成功」即拿到，
   链路口在段 A（1..27）/ 段 B（28..33）之间查台账，已采过则只补链接、不重下。
10. **scout 的 `page-title.png` 缺失会降级到 tab+rows 回退判据**（聊天页可能误判）→
   先 `capture_templates.py` 校准（微信停在赞和收藏页、不被遮挡）。

---

## 8. 当前环境状态（2026-10-27 实测）

| 项 | 状态 | 说明 |
|---|---|---|
| 微信 PC 进程 | ✅ 在运行 | `tasklist` 命中 `wechat.exe`/`weixin.exe` |
| 下载工具 4.0 | ✅ 已在运行（附着） | `find_windows("Mywindow")` 命中 |
| pywinauto / Node | ✅ 可用 | `envs/default` 可 import；`node v22.22.2` |
| 下载工具 exe | ✅ 桌面存在 | `C:/Users/Administrator/Desktop/微信公众号批量下载工具4.0.exe` |
| profile 步骤表 | ✅ 存在 | `scripts/profiles/wechat_batch_downloader.yaml`（33 步） |
| **微信窗口运行态** | ⚠ **阻塞** | dry-run 实测 `iconic:true`、页面 `on_favorites:false` → 必须人工摆到前台「赞和收藏」页 |
| `templates/page-title.png` | ⚠ 缺失 | 仅有 tab-all/wechat-more/wechat-copy-link/wechat-search；scout 降级，先校准 |
| 元典 vein 默认路径 | ⚠ 过期 + verify FAIL | 默认 `2026-10-16` 过期；`verify` 因 21 处失效引用 FAIL → 纯采集不受影响，入库先修元典 |

---

## 9. 一句话启动检查单

```
[ ] 微信前台可见、未最小化、停「赞和收藏」页
[ ] 下载工具已开
[ ] capture_templates.py --verify 通过（page-title.png 在）
[ ] favorites_chain.py --dry-run --max 1 出 chain.would_click
[ ] 再 --yes 真跑（先 --skip-download 验微信侧，再整链路）
```
