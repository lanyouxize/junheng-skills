# 技能契约验证（`_tests/`）

## 这是什么

一套可机检、**可证伪**的技能契约断言。用来回答一个问题：

> 改了某个技能之后，它还是原来那个技能吗？

## 快速使用

```bash
cd C:/Users/Administrator/.workbuddy/skills/_tests

python verify.py                    # 跑全部
python verify.py --only junheng     # 只跑名字含 junheng 的
python verify.py --fault            # 证伪模式：改坏数据，断言必须报错
python verify.py --selftest         # 框架自检：内置必败断言，验证框架能报错
```

退出码：`0` 符合预期；`1` 有失败 / 证伪未触发。

## 三态结果

| 标记 | 含义 | 是否阻塞 |
|---|---|---|
| `✓` 通过 | 契约成立 | — |
| `!` 警告 | 检出了问题，但属已知态势（**必须写明原因与处置计划**） | 不阻塞 |
| `✗` 失败 | 契约被破坏 | 阻塞 |

> 警告态的纪律：**警告不是逃避失败的出口**。当前仅 1 项：
> `junheng-cost` 的 MANIFEST sha256 不符 —— 根因是该技能由上游 `sync-skills` 生成，本地批 A 补 `license/compatibility` 后 MANIFEST 未同步。处置：需在上游源仓同样补齐，否则下次同步会覆盖本地改动。

## 为什么要"证伪模式"

**从不失败的检查器 = 没有检查器。**

`--fault` 会给每个技能注入一处数据污染，然后要求断言**必须报错**。
如果某个技能在污染后仍然全绿，框架直接判定该技能的检查器无效（退出码 1）。

已覆盖的注入点：

| 技能 | 注入内容 | 应触发的断言 |
|---|---|---|
| `junheng-standards` | `vitamin_d.minME` 138.0 → 1380 | 4:1 自洽校验 |
| `junheng-cost` | MANIFEST 首个 sha256 → 全 0 | sha256 与磁盘一致 |
| `multi-search-engine` | `engine-health.jsonl` 首行改为非法 JSON | 台账可机读 |
| `token-usage` | `token_stats.py` 注入语法错误 | 语法可编译 |
| `memory-manager-v2` | `auto_clean` 改为 true + 语法错误 | 防无人值守清理不变量 |

## 现有 5 组断言（45 条）

| 技能 | 断言数 | 核心不变量 |
|---|---|---|
| `junheng-standards` | 8 | NRC 六档齐备；每档 ≥32 条；**4:1 自洽**（min×2.5≈minME，排除混合单位字段、容差 10%） |
| `memory-manager-v2` | 10 | **定时自动清理必须关闭**、**推送类自动清理必须关闭**、加固留痕存在 |
| `junheng-cost` | 8 | MANIFEST 声明的 dest 齐全 + sha256 一致 |
| `multi-search-engine` | 11 | 引擎清单 ≥17；SKILL.md 两节声明；健康台账逐行合法 JSON |
| `token-usage` | 8 | 仅标准库（AST 解析）、`--json`/`--html` 通道、echarts 自包含资产 |

## 加一个新技能

新建 `test_<技能名>.py`：

```python
SKILL = "your-skill"                       # 技能目录名

FAULTS = {                                 # 可证伪点（至少 1 个，否则证伪必失败）
    "SKILL.md": lambda t: t.replace("name: your-skill", "name: broken"),
}

def checks(ctx):
    out = []
    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"name=={SKILL}"))
    out.append((False, "已知问题：说明为什么这样是问题", "warn"))   # 三态写法
    return out
```

`ctx` 提供：`exists(rel)` / `read(rel)` / `read_bytes(rel)` / `json(rel)` / `frontmatter()` / `run(cmd)` / `path(rel)`。

## 已发现的真实问题（本套测试产出）

1. **15 个技能的 SKILL.md 与 MANIFEST 声明不符** —— 批 A 批量补 `license/compatibility` 所致。根因：**改的是同步产物，不是源**。需上游同步，否则下次同步会覆盖。
2. **`paper-quick-reader`/`dev-expert` 的 `allowed-tools` 含 6 个宿主不存在的工具名** —— 已修（见 `batchA_执行报告.md`）。
3. **批 1 的「8 组重复安装」为误判** —— 7 个 `*__skillhub` 目录均为唯一样本，`__skillhub` 是安装器命名规则（`{包名}__{来源}`），不是重复标记。
