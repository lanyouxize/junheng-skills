#!/usr/bin/env node
// reflect.mjs — junheng-orchestrator self-reflect（自动回写 knowledge/*.jsonl）
//
// 边界（铁律）：只做「结构化提取 + schema 校验 + 去重追加」，不执行任何域逻辑。
//   本脚本关闭「自我改进」闭环：阶段运行后，编排者(AI)整理教训，本脚本把教训持久化到
//   正确的知识库文件，避免人工手改 JSONL 出错。
//
// 两条入口：
//   --lesson '<json>'       单条整理好的教训（推荐：AI 在 run 收尾时整理）
//   --lessons '<json-array>' 批量
//   --auto                  从最新 .junheng/run-*.json 审计确定性派生（仅产出有真源支撑的条目）
//
// 路由表（type → 文件）：
//   gotcha        → knowledge/gotchas.jsonl
//   pattern       → knowledge/patterns.jsonl
//   decision      → knowledge/decisions.jsonl
//   anti-pattern  → knowledge/anti-patterns.jsonl
//
// 去重：按 id 精确匹配，已存在则跳过（不覆盖、不重复追加，符合记忆治理 M3）。
// 零依赖：仅 Node 内置 fs/path/url。可从任意工作目录运行。

import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const KNOWLEDGE_DIR = join(SCRIPT_DIR, '..', 'knowledge')

const TYPE_FILE = {
  gotcha: 'gotchas.jsonl',
  pattern: 'patterns.jsonl',
  decision: 'decisions.jsonl',
  'anti-pattern': 'anti-patterns.jsonl',
}

// ---------- schema 校验 ----------
function validate(entry) {
  const errs = []
  if (!entry || typeof entry !== 'object') return { errs: ['entry 须为对象'], file: null }
  if (!entry.id || typeof entry.id !== 'string') errs.push('id 缺失或非字符串')
  const file = TYPE_FILE[entry.type]
  if (!file) errs.push(`type 须为 gotcha|pattern|decision|anti-pattern（收到: ${entry.type}）`)
  if (!entry.fact || typeof entry.fact !== 'string') errs.push('fact 缺失或非字符串')
  if (!entry.recommendation || typeof entry.recommendation !== 'string') errs.push('recommendation 缺失或非字符串')
  if (!entry.provenance || typeof entry.provenance !== 'string') errs.push('provenance 缺失（须标注来源，如 run-20261106-080000 / A1 实测）')
  if (!Array.isArray(entry.tags)) errs.push('tags 须为数组')
  if (!Array.isArray(entry.affectedFiles)) errs.push('affectedFiles 须为数组')
  if (entry.confidence == null) entry.confidence = 'high'
  return { errs, file }
}

// ---------- JSONL 读写 + 去重追加 ----------
function readExisting(file) {
  const path = join(KNOWLEDGE_DIR, file)
  if (!existsSync(path)) return { entries: [], ids: new Set() }
  const raw = readFileSync(path, 'utf8').split('\n').filter((l) => l.trim())
  const entries = []
  const ids = new Set()
  for (const line of raw) {
    try { const o = JSON.parse(line); entries.push(o); if (o.id) ids.add(o.id) } catch { /* 跳过坏行 */ }
  }
  return { entries, ids }
}

function appendUnique(file, newEntries) {
  const path = join(KNOWLEDGE_DIR, file)
  const { entries, ids } = readExisting(file)
  const added = []
  const skipped = []
  for (const e of newEntries) {
    if (ids.has(e.id)) { skipped.push(e.id); continue }
    entries.push(e); ids.add(e.id); added.push(e.id)
  }
  writeFileSync(path, entries.map((e) => JSON.stringify(e)).join('\n') + '\n', 'utf8')
  return { added, skipped, path }
}

// ---------- 单条/批量整理入口 ----------
function fromLessons(jsonArg) {
  let parsed
  try { parsed = JSON.parse(jsonArg) } catch (e) { console.error('[reflect] JSON 解析失败:', e.message); process.exit(2) }
  const list = Array.isArray(parsed) ? parsed : [parsed]
  const results = []
  for (const entry of list) {
    const { errs, file } = validate(entry)
    if (errs.length) { results.push({ id: entry?.id || '?', ok: false, errs }); continue }
    const { added, skipped } = appendUnique(file, [entry])
    results.push({ id: entry.id, ok: true, added, skipped, file })
  }
  return results
}

// ---------- --auto：从审计确定性派生 ----------
function findLatestAudit() {
  const dir = '.junheng'
  if (!existsSync(dir)) return null
  const files = readdirSync(dir).filter((f) => /^run-\d{8}-\d{6}\.json$/.test(f))
  if (!files.length) return null
  files.sort() // run-YYYYMMDD-HHMMSS 字典序即时间序
  return join(dir, files[files.length - 1])
}

function fromAudit() {
  const auditPath = findLatestAudit()
  if (!auditPath) { console.error('[reflect] 未找到 .junheng/run-*.json 审计文件（先 finalize 或提供审计）'); process.exit(1) }
  let audit
  try { audit = JSON.parse(readFileSync(auditPath, 'utf8')) } catch (e) { console.error('[reflect] 审计解析失败:', e.message); process.exit(2) }
  const runId = audit.runId || 'run-unknown'
  const out = []
  const stages = audit.stages || []

  const allPass = stages.length && stages.every((s) => s.gate === 'PASS')
  // pattern：全流程通过且 Fresh Reviewer 门禁生效
  if (allPass && audit.qualityGates?.freshReviewer) {
    out.push({
      id: `REF-${runId}-pat-1`,
      type: 'pattern',
      fact: `7 阶段编排在本 run（${runId}）全 PASS 且质量门禁② Fresh Reviewer 独立重算生效；编排层「串联+门禁+审计」范式可复用于同类配方研发任务。`,
      recommendation: '同类任务直接复用七阶段 DAG；VALIDATE 阶段务必保留独立重算路径（不读技能自报）。',
      confidence: 'high',
      provenance: `${runId} audit | task=${audit.task}`,
      tags: ['编排', '门禁', 'self-reflect'],
      affectedFiles: ['junheng-orchestrator/scripts/orchestrate.mjs'],
    })
  }
  // gotcha：每个 FAIL 阶段派生一条（真源支撑，非合成）
  for (const s of stages) {
    if (s.gate === 'FAIL') {
      out.push({
        id: `REF-${runId}-got-${s.index}`,
        type: 'gotcha',
        fact: `run ${runId} 阶段${s.index}（${s.name}/${s.skill}）门禁 FAIL；该阶段 DoD「${s.dod}」未达成，需回退上游重做。`,
        recommendation: 'FAIL 阶段不可跳过；先修上游依赖（门禁三铁律①）再重记 PASS。',
        confidence: 'high',
        provenance: `${runId} audit stage ${s.index}`,
        tags: ['门禁', 'FAIL', s.skill],
        affectedFiles: ['junheng-orchestrator/scripts/orchestrate.mjs'],
      })
    }
  }
  // decision：每个已批准人工检查点派生一条
  for (const cp of (audit.humanCheckpoints || [])) {
    out.push({
      id: `REF-${runId}-dec-${cp.at || 'cp'}`,
      type: 'decision',
      fact: `run ${runId} 人工检查点 ${cp.at} 已由 ${cp.approvedBy || 'user'} 于 ${cp.approvedAt || '?'} 授权，高风险动作（标准值/编排边界改动）经显式批准后继续。`,
      recommendation: '含标准值改动的阶段须走 approve-checkpoint；未授权不得记录 PASS。',
      confidence: 'high',
      provenance: `${runId} audit checkpoint`,
      tags: ['人工检查点', '授权', '高风险'],
      affectedFiles: ['junheng-orchestrator/scripts/orchestrate.mjs'],
    })
  }
  if (!out.length) { console.log(`[reflect] --auto：审计 ${runId} 无新增派生条目（无需回写）`); return [] }
  // 路由追加
  const byFile = {}
  for (const e of out) { const f = TYPE_FILE[e.type]; (byFile[f] ||= []).push(e) }
  const summary = []
  for (const [f, list] of Object.entries(byFile)) {
    const { added, skipped } = appendUnique(f, list)
    summary.push({ file: f, added, skipped })
  }
  return summary
}

// ---------- 入口 ----------
function main() {
  const argv = process.argv.slice(2)
  const mode = argv.find((a) => a === '--lesson' || a === '--lessons' || a === '--auto')
  if (!mode) {
    console.log('junheng-orchestrator self-reflect — 自动回写 knowledge/*.jsonl')
    console.log('  子命令:')
    console.log('    --lesson  \'<json>\'       单条教训（id/type/fact/recommendation/provenance/tags/affectedFiles）')
    console.log('    --lessons \'<json-array>\'  批量教训')
    console.log('    --auto                      从最新 .junheng/run-*.json 确定性派生并回写')
    console.log('  例: node scripts/reflect.mjs --lesson \'{"id":"GOT-005","type":"gotcha","fact":"...","recommendation":"...","provenance":"B1 阶段C 实测","tags":["x"],"affectedFiles":["junheng-orchestrator/..."]}\'')
    process.exit(2)
  }
  if (mode === '--auto') {
    const summary = fromAudit()
    if (summary.length) {
      console.log('[reflect] --auto 回写结果:')
      for (const s of summary) console.log(`  ${s.file}: +${s.added.length} 新增 [${s.added.join(', ')}]` + (s.skipped.length ? ` / 跳过 ${s.skipped.length} 重复` : ''))
    }
    process.exit(0)
  }
  const jsonArg = argv[argv.indexOf(mode) + 1]
  if (!jsonArg) { console.error(`[reflect] ${mode} 需提供 JSON 参数`); process.exit(2) }
  const results = fromLessons(jsonArg)
  let fail = 0
  for (const r of results) {
    if (r.ok) console.log(`[reflect] ✓ ${r.id} → ${r.file}（新增 ${r.added.length}${r.skipped.length ? ` / 跳过重复 ${r.skipped.length}` : ''}）`)
    else { fail++; console.error(`[reflect] ✗ ${r.id} 校验失败: ${r.errs.join('; ')}`) }
  }
  process.exit(fail ? 1 : 0)
}
main()
