# 审计落盘格式（Audit Schema）

> 编排每次运行结束（或每个阶段完成）落盘 `.junheng/run-<ts>.json`，使配方研发流程**可回放、可审计**。
> 本文件仅固化格式（阶段 A 不写运行时代码）。实际写入由编排者 / 后续阶段 B 脚本完成。

## 文件位置

- 工作区根 `.junheng/run-<YYYYMMDD-HHMMSS>.json`（如 `D:/workbuddy.../.junheng/run-20261106-080000.json`）
- 同目录可放 `state.json`（断点续跑，阶段 B 实现）

## 结构（JSON Schema）

```jsonc
{
  "schemaVersion": "1.0",
  "runId": "run-20261106-080000",
  "task": "排毛功能配方研发 v3",
  "startedAt": "2026-11-06T08:00:00+08:00",
  "finishedAt": "2026-11-06T08:42:13+08:00",
  "marketId": "intl",
  "species": "cat",
  "stage": "adult",
  "stages": [
    {
      "index": 1,
      "name": "evidence",
      "skill": "paper-bilingual-search",
      "dod": "引用可溯、文献真实性已核",
      "gate": "PASS",            // PASS | FAIL | SKIPPED
      "evidence": [              // 来自 recipe 审计字段
        { "claim": "XX 原料排毛", "source": "文献名", "year": 2023, "strength": "中", "verified": true }
      ],
      "humanCheckpoint": false
    },
    {
      "index": 2,
      "name": "standards",
      "skill": "junheng-standards",
      "dod": "available + cite 完整",
      "gate": "PASS",
      "standardSet": { "marketId": "intl", "species": "cat", "stage": "adult",
                       "items": [{ "key": "crude_protein", "min": 26, "cite": "AAFCO 2014", "verified": false }] }
    },
    {
      "index": 3,
      "name": "formulate",
      "skill": "junheng-formulate",
      "dod": "Σ=1、LP optimal、单位成本产出",
      "gate": "PASS",
      "recipe": [{ "id": "x1", "name": "水解鸡肉粉", "share": 0.192, "price": 21 }],
      "unitCost": 7.26,
      "strategy": "least_cost"
    },
    {
      "index": 4,
      "name": "attainment",
      "skill": "junheng-attainment",
      "dod": "各营养达成、钙磷比在界、独立重算一致",
      "gate": "PASS",
      "independentCheck": true,    // Fresh Reviewer Rule 满足
      "achieved": [{ "key": "crude_protein", "value": 26.0, "min": 26, "ok": true }]
    },
    {
      "index": 5,
      "name": "labeling",
      "skill": "junheng-labeling",
      "gate": "PASS"
    },
    {
      "index": 6,
      "name": "compliance",
      "skill": "junheng-safety",
      "gate": "PASS",
      "compliance": { "overLimit": [], "missing": [], "passed": true }
    },
    {
      "index": 7,
      "name": "report",
      "skill": "word-docx",
      "gate": "PASS",
      "reportPath": "D:/.../排毛配方v3.docx"
    }
  ],
  "qualityGates": {
    "validatePassed": true,        // 门禁三铁律①
    "freshReviewer": true,         // 门禁三铁律②
    "evidenceBacked": true         // 门禁三铁律③
  },
  "humanCheckpoints": [            // 主动暂停记录
    { "at": "stage-2", "reason": "改 AAFCO 犬 adult 钙磷", "approvedBy": "user", "approvedAt": "..." }
  ],
  "lintBeforeCommit": "PASS(93 技能 0E0W)",
  "commit": "ca40c2a"
}
```

## 字段约束

- `gate` 取值 `PASS | FAIL | SKIPPED`；任一 `FAIL` 且未升级人工 → 整个 run 视为未通过。
- `qualityGates` 三铁律全 `true` 才允许 COMMIT 阶段。
- `humanCheckpoints` 非空且 `approvedBy` 缺失 → 视为未授权，编排不得继续高风险动作。
- `evidence[].source` 必须是**文献名**而非文件名（对齐用户铁律）。

## 阶段 B 待实现 / 已实现

- `state.json` 断点续跑（上下文恢复）—— **已实现**（阶段 B，`scripts/orchestrate.mjs` 的 `init/next/record/status/resume/finalize` 子命令管理 `.junheng/state.json` 持久化与 DAG 门禁）。
- self-reflect 自动提取回写 `knowledge/*.jsonl` —— **已实现**（阶段 C，`scripts/reflect.mjs`：`--lesson/--lessons` 收整理条目、`--auto` 从审计派生，schema 校验 + 按 id 去重追加）。
- `recover` 上下文恢复增强 —— **已实现**（阶段 C，`orchestrate.mjs recover`：压缩式恢复简报 + state 缺失时从审计重建）。
- `adversarial-check.mjs`（独立重算对抗验证，Fresh Reviewer，铁律②/③）—— **已实现**（阶段 B），供阶段③/④ VALIDATE/REVIEW 调用。
