---
name: rev-verify
description: 验证对拍。要把"我看到过"变成"任何人都能再验一遍"时用它：把事实冻结成基线与判定哪些断言必须成立，重跑后零容忍比对。失配即报错，绝不自动更新基线。
description_zh: 验证对拍：fixture 冻结与零容忍重放，区分静态 exact 与动态 subset 两类断言
description_en: "Verification by replay: frozen fixtures compared with zero tolerance, exact for static and subset for dynamic"
version: 1.0.0
display_name: rev-verify
license: Proprietary
compatibility: Python 3.9+.
---

# rev-verify

把一次性观测变成可重复验证的基线。

## 不做什么

- **不判断结论对不对**。它只回答"这次跑出来的和上次是不是同一批"，不回答"这条结论是否正确"。
- **不自动修基线**。失配就 `exit 1`，绝不悄悄把 fixture 更新成当前结果——那等于把检查器改成永远绿的装饰品。
- **不接受空基线**。`facts` 为空的 fixture 冻结时直接拒绝：空集合永远匹配空集合。
- **不替动态观测伪造 exact**。动态产物含 session id、时间戳、渲染进程数，天然不可精确复现；只允许 `subset`。

## 两类断言

| 模式 | 语义 | 适用 |
|---|---|---|
| `exact` | 条目集合、值、digest、条数全部必须相同 | `rev-static` 等确定性产物 |
| `subset` | 基线里每条必须出现且一致；允许新增 | `rev-runtime` 等含噪声产物 |

`freeze` 会拒绝给非 `rev-static` 的产物建 `exact` 基线。这是刻意的：把噪声当确定性，验证就会变成假绿。

## 用法

```bash
# 1. 冻结基线（静态产物，带重跑命令）
python scripts/cli.py freeze --facts case/facts/strings.json --out case/fixtures \
       --mode exact --name strings \
       --argv '["python","scripts/cli.py","strings","--sample","x.exe","--out","r2"]'

# 2. 重跑并零容忍比对
python scripts/cli.py replay --fixture case/fixtures/strings.fixture.json \
       --facts r2/facts/strings.json
# 或一步到位（fixture 里已记录 argv）
python scripts/cli.py replay --fixture case/fixtures/strings.fixture.json --facts r2/facts/strings.json

# 3. 两份产物直接比对
python scripts/cli.py diff --a before.json --b after.json
```

## 判据

`replay` 会在下列任一条成立时判失配（`exit 1`）：

1. 基线条目在新结果中缺失
2. `digest` 不符（值被改或字节被换）
3. `value` 不符
4. `exact` 模式下出现基线外新增事实，或总条数不同
5. `status` / `producer` 与基线不同
6. **输入二进制哈希变了**（版本不同就不是同一次验证）

## 退出码

`0` 一致｜`1` 失配｜`2` 参数或格式错误

## 自检证明判据能失败

`selftest` 有 20 项断言，其中 12 项是"必须判失败"的负向断言（少一条、改值、只改 digest、多一条、二进制变、空基线、动态产物用 exact……）。变异测试（故意删掉每一条检查逻辑）6/6 全部被检出。

另含真实产物验证：在 `notepad.exe` 上独立跑两次 `rev-static strings`（各 300 条事实），两次 digest 集合完全一致。
