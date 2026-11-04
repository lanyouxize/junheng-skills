# 多公众号 × 逐月回溯：一次完整的采集时序

面向 `scripts/monthly_rollback.py`。这里不放代码细节（代码里的 docstring 已经写了
为什么），只放**跑起来到底发生什么**，方便对着状态文件核对进度。

## 1. 账号清单（accounts.yaml）

```yaml
accounts:
  - name: 食品研发与生产
    article_url: https://mp.weixin.qq.com/s/xxxxxxxx
  - name: 宠物食品研发号A
    article_url: https://mp.weixin.qq.com/s/yyyyyyyy
```

`article_url` 必须是该号**任意一篇当前能打开**的文章。原因：下载工具的
「1.获取公众号id」要先在微信内置浏览器打开该号页面才能读到 cookie；没有链接时
工具**不写任何日志**、直接空转，最后表现为超时，很难看出根因。skill 会先把这个
链接填进「微信文章链接」框，再用它做预热导航。

等价的命令行写法（省一个文件）：

```bash
python scripts/monthly_rollback.py init \
    --account "食品研发与生产=https://mp.weixin.qq.com/s/xxxxxxxx" \
    --account "宠物食品研发号A=https://mp.weixin.qq.com/s/yyyyyyyy" \
    --anchor 2026-11-01 --max-windows 24 --stop-before 2020-01-01
```

`--anchor` 建议显式给：它决定所有窗口的边界，之后**固化在状态文件里**。不给就是
运行当天。改 anchor 等于重排整条时间轴，已经采过的月份会对不上。

## 2. 时序（anchor=2026-11-01，两个号）

| 步 | 命令 | 窗口 | 谁 | 结果 | 窗口状态 |
|---|---|---|---|---|---|
| 1 | `next` | W0001 2026-10-01~11-01 | 食品研发与生产 | 下载 12 篇 → done | 进行中 |
| 2 | `next` | W0001 | 宠物食品研发号A | 下载 7 篇 → done | **已完成**（全 done 才关窗） |
| 3 | `next` | W0002 2026-09-01~10-01 | 食品研发与生产 | … | 进行中 |
| … | | | | | |
| n | `next` | W0024 | — | 到 `--max-windows` 上限 | 全部结束（`all_done`） |

关键点：第 1 步之后**不会**给「食品研发与生产」开新窗口。这是需求里"先检查所有
公众号是否都采完这个月"的那道闸——闸门判据只有一条：该窗**所有**账号 `done`。

## 3. 三种非正常态（都见过）

| 现象 | 调度器行为 | 人该做什么 |
|---|---|---|
| 某号下载失败（rc≠0/5） | 任务记 `failed`、`attempts+1`，**同窗其它号继续跑**；回头重试该号 | 看工具日志：多半是微信没打开该号文章 / 代理干扰 / 该号当月确实空 |
| 同号连续失败到 `--max-attempts` | `next` 返回 `blocked`、退出码 7，**窗口绝不前移** | 人工修好后 `run` 再跑，或 `mark ... --status pending` 重置该任务 |
| 想重采某一窗 | `rewind --window W0002` | 该窗所有任务回 `pending`，窗口回 `active` |

`blocked` 不退化成"跳过该号继续回溯"，是刻意的：一旦跳过，号 A 会跑到 2024 年，
号 B 还停在 2026 年，两边的月份再也对不齐，而状态文件看上去"一切正常"。

## 4. 窗口为什么重叠一天

`W0001 = [2026-10-01, 2026-11-01]`、`W0002 = [2026-09-01, 2026-10-01]`，
10-01 这一天在两个窗里。下载工具按文章去重，重了不会多出文件；漏一篇则是静默的
（产物照样"成功"，只是少了几篇），比报错更难发现。所以**宁可重，不可漏**。

## 5. 状态文件长什么样

```json
{
  "anchor": "2026-11-01",
  "policy": "rolling",
  "max_windows": 24,
  "stop_before": "2020-01-01",
  "max_attempts": 3,
  "accounts": [{"name": "食品研发与生产", "article_url": "https://..."}],
  "windows": [
    {"id": "W0001", "index": 0, "start": "2026-10-01", "end": "2026-11-01",
     "status": "completed", "completed_at": "2026-11-01T14:02:11"}
  ],
  "tasks": {
    "W0001": {
      "食品研发与生产": {"status": "done", "attempts": 0, "md_new": 12,
                     "at": "2026-11-01T13:58:02", "detail": "rc=0 新增md=12"}
    }
  }
}
```

`windows` 是**新→旧**排列，`tasks` 以 `窗口 → 账号` 二级索引。原子写（临时文件 +
`os.replace`），中断不会留半截 JSON。正式用请把 `--state` 指到数据目录，别留在
技能目录里。

## 6. 与既有链路的关系

- 单号全链路（clean → 入库 → 导出）：`pipeline.py`，一次一个号、一个范围；
- 七步串联（赞和收藏 → 取 id → 下载）：`favorites_chain.py`；
- **按月回溯（本文）**：只管"什么时候、用哪段日期、跑哪个号"，下载动作仍交给
  `clicker.py` + `wechat_batch_downloader` 步骤表（`RANGE=custom` 分支）。
  它不负责清洗与入库——那两段仍然跑 `pipeline.py --from-step clean`。
