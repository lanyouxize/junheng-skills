# fixture 格式（reva-fixture/1）

```json
{
  "schema": "reva-fixture/1",
  "name": "strings",
  "frozen_at": "2026-11-01T23:30:00+08:00",
  "mode": "exact",
  "producer": "rev-static",
  "channel": "strings",
  "target_id": "tgt-abc123",
  "sample_sha256": "<输入二进制的全量 sha256>",
  "source_facts_sha256": "<被冻结 facts 文件的 sha256>",
  "argv": ["python", "scripts/cli.py", "strings", "--sample", "x.exe", "--out", "r2"],
  "cwd": ".",
  "status": "ok",
  "count": 300,
  "entries": [
    {"id": "strings-0001", "kind": "string-ascii", "value": "MZ...",
     "digest": "<对 value 的 sha256>", "locator_mode": "file"}
  ]
}
```

## 字段作用

| 字段 | 为什么必须有 |
|---|---|
| `mode` | 决定是否允许新增事实；混淆 exact/subset 会让动态验证假绿 |
| `sample_sha256` | 换版本后行为不同是正常的，但那就不是同一次验证 |
| `source_facts_sha256` | 能反查这条基线是从哪个文件冻出来的 |
| `argv` + `cwd` | 没有重跑命令的基线只能比对手工产物，验不出"同样的输入再来一次" |
| `entries[].digest` | 只比 value 会漏掉"值相同但字节不同"；只比 digest 会漏掉"digest 是伪造的" |

## 为什么 digest 对 value 的 UTF-8 字节算

不重放那次采集就无法重算字节级 digest。以 value 为锚点，任何持有 value 的人都能独立复算——
这样校验第三方给的 fixture 时不需要有原始样本。

## 不许做的事

- 不许把 `mode` 从 exact 改成 subset 来"修好"失配。那是在改判据，不是改事实。
- 不许在失配后重跑 `freeze` 覆盖基线。要更新基线必须显式说明"基线已过期"，并保留旧文件。
