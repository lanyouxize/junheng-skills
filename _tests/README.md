# 技能契约验证（`_tests/`）

## 这是什么

一套可机检、**可证伪**的技能契约断言。用来回答一个问题：

> 改了某个技能之后，它还是原来那个技能吗？

当前规模：**24 个模块 / 124 条断言**，正常态 124 通过 / 0 失败，`--fault` 24/24 全部能检出。

## 快速使用

```bash
cd C:/Users/Administrator/.workbuddy/skills/_tests

python verify.py                    # 跑全部
python verify.py --only junheng     # 只跑名字含 junheng 的
python verify.py --fault            # 证伪模式：改坏数据，断言必须报错
python verify.py --selftest         # 框架自检：内置必败断言，验证框架能报错
git -C .. hook run pre-commit       # 手动触发提交闸门（等价 commit 时的钩子）
```

退出码：`0` 符合预期；`1` 有失败 / 证伪未触发。

## pre-commit 闸门（批 C-2 装）

- 钩子源码：`_tests/hooks/pre-commit`（**在版本控制内**，不在 `.git/hooks/`）
- 启用方式：仓库本地 `git config core.hooksPath _tests/hooks`（`.git/config` 不随 clone 传播）
- 行为：每次 `git commit` 自动跑 `python _tests/verify.py --quiet`，失败即拒绝提交；耗时约 0.6s
- 应急绕过：`SKIP_SKILLS_VERIFY=1 git commit ...` —— **会打印留痕**，不要常态使用
- **换机复现**：clone 后必须手动执行上面那条 `git config`，否则钩子不生效

### 闸门的可证伪证据

`t5b_install_hook.py` 做过真实故障注入：把 `standards.js` 的 `vitamin_d.minME` 从 `138.0` 改为 `1380.0` → 钩子 `exit=1` 拒绝；恢复后 `exit=0` 放行；文件 sha256 复原到 `99dfbfc45e9b24f364a0`，零残留。证据见 `t5b_hook_evidence.json`。

## 三态结果

| 标记 | 含义 | 是否阻塞 |
|---|---|---|
| `✓` 通过 | 契约成立 | — |
| `!` 警告 | 检出了问题，但属已知态势（**必须写明原因与处置计划**） | 不阻塞 |
| `✗` 失败 | 契约被破坏 | 阻塞 |

> 警告态的纪律：**警告不是逃避失败的出口**。当前正常态 0 警告；`--fault` 下 `junheng-cost` 出现 1 条警告属预期（污染被检出）。
> 历史遗留的「15 个技能 MANIFEST sha256 不符」已于批 C-1 **根治**（改上游源而非改校验和），现存 180/180 一致。

## 为什么要"证伪模式"

**从不失败的检查器 = 没有检查器。**

`--fault` 会给每个技能注入一处数据污染，然后要求断言**必须报错**。
如果某个技能在污染后仍然全绿，框架直接判定该技能的检查器无效（退出码 1）。

注入点分三类：
- 有 `MANIFEST.entries` 的技能 → 篡改 `MANIFEST.json` 的 `sha256` 键
- 无 entries 的技能 → 篡改 `SKILL.md` 的 `description:` 键
- 批 B 的 5 个模块 → 各自专属注入（4:1 违例、非法 JSON、语法错误、自动清理开启等）

## 断言分组

| 组 | 数量 | 核心不变量 |
|---|---|---|
| 批 B 原有 | 5 模块 | NRC 4:1 自洽、防无人值守清理、MANIFEST sha、引擎台账、仅标准库 |
| `_bg_adoption`（横切） | 1 模块 | 5 个长任务技能必须含 `--declare/--complete/--resume`，且 `bg_check.py --selftest` 通过 |
| 批 C-2 生成 | 17 模块 | frontmatter 严格 YAML、顶层 JSON 数与可解析性、`scripts/*.py` AST 可编译、MANIFEST entries 数与 sha256 一致 |
| `_t4_split`（横切） | 1 模块 | 拆分后主体 <500 行、导航表覆盖 5 个 references、外置文件非空、断点段落与 frontmatter 未丢 |

> 生成器的反作弊纪律：`MANIFEST.entries` 为 0 时**跳过** sha 判据并明示原因——0 条断言等于没检查，不能算作有效覆盖。判据基准全部来自 `t5_probe_candidates.py` 的真实探测，不写猜测值。

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

## 历史发现（留痕，均已处置或已定性）

1. **15 个技能 MANIFEST sha256 不符** —— 根因「改的是同步产物，不是源」；批 C-1 已回流上游源仓并同步，180/180 一致。
2. **`paper-quick-reader`/`dev-expert` 的 `allowed-tools` 含 6 个宿主不存在的工具名** —— 批 A 已修。
3. **批 1 的「8 组重复安装」为误判** —— 7 个 `*__skillhub` 目录均为唯一样本，`__skillhub` 是安装器命名规则（`{包名}__{来源}`）。
4. **`bg_check.py --declare` 的 exit=1 是「满足 T4 → 应派发」语义，不是失败**；`--complete` 会拒绝缺失/空的交付物（反作弊设计）。
