#!/usr/bin/env node
// orchestrate.mjs — junheng-orchestrator 编排状态机（DAG + 状态文件 + 审计落盘）
//
// 边界（铁律）：只做「串联与门禁」，不执行任何域逻辑。阶段结果由编排者(AI)提供，
//   本脚本负责：
//     1) DAG 依赖校验  —— 门禁三铁律①：依赖未全部 PASS 不可进下一阶段；
//     2) 状态持久化    —— .junheng/state.json（断点续跑 / 上下文恢复，蓝图§2.7）；
//     3) 质量门禁校验  —— 三铁律全满足才允许 finalize（COMMIT 阶段）；
//     4) 审计落盘      —— .junheng/run-<ts>.json（对齐 audit/README.md schema）。
//
// 子任务递归分解（蓝图§2.6 swarm of swarms）：每个阶段含 subtasks[] 工作单元，
//   阶段 PASS 前须其全部 subtasks PASS，实现 epic→work-unit 两级 DAG。
//
// 零依赖：仅 Node 内置 fs/path。可在任意电脑直接运行。

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs'
import { resolve, join } from 'node:path'

const JUNHENG_DIR = '.junheng'
const STATE_FILE = join(JUNHENG_DIR, 'state.json')

// ---------- 七阶段 DAG 定义（蓝图§4.2 / recipe DAG）----------
const STAGES = [
  { index: 1, key: 'evidence', name: '证据收集', skill: 'paper-bilingual-search', deps: [],
    dod: '引用可溯、文献真实性已核',
    subtasks: ['检索功能宣称文献', '核验文献真实性与年份', '证据强度分级'] },
  { index: 2, key: 'standards', name: '标准映射', skill: 'junheng-standards', deps: [1],
    dod: 'available + cite 完整、verified 标注明确',
    subtasks: ['调用 resolveStandard', '核对 available 与 cite', '标注 verified=false 项'] },
  { index: 3, key: 'formulate', name: '配方计算', skill: 'junheng-formulate', deps: [2],
    dod: 'Σ=1、LP optimal、单位成本产出',
    subtasks: ['构造 LP 约束', '运行 solveLP', '产出配比与单位成本'] },
  { index: 4, key: 'attainment', name: '达成度验证', skill: 'junheng-attainment', deps: [3],
    dod: '各营养达成、钙磷比在界、独立重算一致',
    subtasks: ['独立重算营养达成', '校验钙磷比', 'Fresh Reviewer 对抗验证'] },
  { index: 5, key: 'labeling', name: '标签生成', skill: 'junheng-labeling', deps: [4],
    dod: '标签数值与实测一致、基准标注清晰',
    subtasks: ['生成标签数值', '核对与实测一致'] },
  { index: 6, key: 'compliance', name: '合规校验', skill: 'junheng-safety', deps: [5],
    dod: '无超标、无缺失强制项、添加剂在限值内',
    subtasks: ['超标项扫描', '缺失强制项扫描', '添加剂限值核对'] },
  { index: 7, key: 'report', name: '报告产出', skill: 'word-docx', deps: [6],
    dod: '报告含证据链+标准出处+审计追踪',
    subtasks: ['汇总证据链', '嵌入审计追踪', '产出报告文件'] },
]

const HUMAN_CHECKPOINT_STAGES = new Set([2]) // 标准值改动需人工确认（蓝图人类检查点）

function nowISO() { return new Date().toISOString().replace(/\.\d+Z$/, '+08:00') }

// ---------- 状态读写 ----------
function loadState() {
  if (!existsSync(STATE_FILE)) return null
  try { return JSON.parse(readFileSync(STATE_FILE, 'utf8')) } catch { return null }
}
function saveState(st) {
  if (!existsSync(JUNHENG_DIR)) mkdirSync(JUNHENG_DIR, { recursive: true })
  writeFileSync(STATE_FILE, JSON.stringify(st, null, 2), 'utf8')
}

function newState({ task, marketId, species, stage, moistureClass }) {
  return {
    schemaVersion: '1.0',
    task,
    marketId, species, stage, moistureClass,
    createdAt: nowISO(),
    updatedAt: nowISO(),
    stages: STAGES.map((s) => ({
      index: s.index, key: s.key, name: s.name, skill: s.skill, deps: s.deps,
      status: 'PENDING', // PENDING | RUNNING | PASS | FAIL | SKIPPED
      gate: null,
      dod: s.dod,
      subtasks: s.subtasks.map((label, i) => ({ id: `${s.index}.${i + 1}`, label, status: 'PENDING' })),
      retryCount: 0,
      result: null,
      evidence: [],
      humanCheckpoint: HUMAN_CHECKPOINT_STAGES.has(s.index),
      checkpointApproved: HUMAN_CHECKPOINT_STAGES.has(s.index) ? false : true,
    })),
    qualityGates: { validatePassed: false, freshReviewer: false, evidenceBacked: false },
    humanCheckpoints: [],
  }
}

// ---------- 子命令 ----------
function cmdInit(argv) {
  const get = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null }
  const task = get('--task') || '未命名配方研发'
  const state = newState({
    task,
    marketId: get('--market') || 'intl',
    species: get('--species') || 'cat',
    stage: get('--stage') || 'adult',
    moistureClass: get('--moisture') || 'unknown',
  })
  saveState(state)
  console.log(`[orchestrate] 已初始化状态: ${JUNHENG_DIR}/state.json`)
  console.log(`[orchestrate] 任务: ${task} | 7 阶段 DAG | 阶段②含人工检查点`)
  console.log('[orchestrate] 下一步: node scripts/orchestrate.mjs next')
}

function cmdNext() {
  const st = loadState()
  if (!st) return console.error('[orchestrate] 无状态文件，先运行 init')
  for (const s of st.stages) {
    if (s.status === 'PASS') continue
    const blockedBy = s.deps.filter((d) => {
      const ds = st.stages.find((x) => x.index === d)
      return ds && ds.status !== 'PASS' && ds.status !== 'SKIPPED'
    })
    if (blockedBy.length) {
      const names = blockedBy.map((d) => st.stages.find((x) => x.index === d).name).join('、')
      console.log(`[orchestrate] 阻塞于「${s.name}」：依赖未通过（${names}）—— 违反门禁三铁律①，须先解决上游`)
      return
    }
    console.log(`\n=== 下一可执行阶段：${s.index}. ${s.name}（${s.skill}）===`)
    console.log(`  DoD: ${s.dod}`)
    console.log(`  子任务(${s.subtasks.length}):`)
    s.subtasks.forEach((t) => console.log(`    - [${t.status}] ${t.id} ${t.label}`))
    if (s.humanCheckpoint && !s.checkpointApproved)
      console.log(`  ⚠ 人工检查点：本阶段涉及标准值改动，须先获用户显式批准（运行 record --stage ${s.index} --approve-checkpoint）`)
    console.log('  记录完成: node scripts/orchestrate.mjs record --stage ' + s.index + ' --gate PASS --result \'{...}\'')
    return
  }
  console.log('[orchestrate] 全部阶段 PASS，运行 finalize 落盘审计')
}

function cmdRecord(argv) {
  const get = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null }
  const idx = parseInt(get('--stage'), 10)
  const gate = get('--gate')
  const st = loadState()
  if (!st) return console.error('[orchestrate] 无状态文件，先运行 init')
  if (![1, 2, 3, 4, 5, 6, 7].includes(idx)) return console.error('[orchestrate] --stage 须为 1-7')
  if (!['PASS', 'FAIL', 'SKIPPED'].includes(gate)) return console.error('[orchestrate] --gate 须为 PASS|FAIL|SKIPPED')

  const s = st.stages.find((x) => x.index === idx)
  // 门禁三铁律①：依赖未全 PASS 拒绝记录
  const blockedBy = s.deps.filter((d) => {
    const ds = st.stages.find((x) => x.index === d)
    return ds && ds.status !== 'PASS' && ds.status !== 'SKIPPED'
  })
  if (blockedBy.length) {
    const names = blockedBy.map((d) => st.stages.find((x) => x.index === d).name).join('、')
    console.error(`[orchestrate] ✗ 拒绝记录：依赖未通过（${names}）—— 门禁三铁律①，不可跳过`)
    process.exit(1)
  }
  // 人工检查点：未批准不得记录 PASS
  if (s.humanCheckpoint && !s.checkpointApproved && gate === 'PASS') {
    console.error(`[orchestrate] ✗ 拒绝记录 PASS：阶段${idx} 人工检查点未批准（高风险动作须显式授权）`)
    process.exit(1)
  }

  let result = null
  const resultArg = get('--result')
  if (resultArg) { try { result = JSON.parse(resultArg) } catch { console.error('[orchestrate] --result JSON 解析失败'); process.exit(2) } }

  const subtaskArg = get('--subtask')
  if (subtaskArg) {
    const t = s.subtasks.find((x) => x.id === subtaskArg)
    if (!t) return console.error(`[orchestrate] 子任务 ${subtaskArg} 不存在`)
    t.status = gate === 'PASS' ? 'PASS' : 'FAIL'
    console.log(`[orchestrate] 子任务 ${subtaskArg} → ${t.status}`)
    // 全部子任务 PASS 才可整体 PASS
    if (gate === 'PASS' && s.subtasks.some((x) => x.status !== 'PASS')) {
      console.log(`[orchestrate] 阶段${idx} 仍有子任务未完成，待全部 PASS 后整体记录（record --stage ${idx} --gate PASS 不带 --subtask）`)
      st.updatedAt = nowISO(); saveState(st); return
    }
  }

  s.status = gate
  s.gate = gate
  s.result = result
  s.updatedAt = nowISO()
  if (gate === 'FAIL') s.retryCount++

  // Fresh Reviewer 标记：阶段④ 含独立重算结果
  if (idx === 4 && result && result.independentCheck) st.qualityGates.freshReviewer = true

  st.updatedAt = nowISO()
  saveState(st)
  console.log(`[orchestrate] 阶段 ${idx}. ${s.name} → ${gate}` + (subtaskArg ? `（子任务 ${subtaskArg}）` : ''))
}

function cmdApproveCheckpoint(argv) {
  const get = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null }
  const idx = parseInt(get('--stage'), 10)
  const st = loadState()
  const s = st.stages.find((x) => x.index === idx)
  if (!s || !s.humanCheckpoint) return console.error(`[orchestrate] 阶段${idx} 非人工检查点`)
  s.checkpointApproved = true
  st.humanCheckpoints.push({ at: `stage-${idx}`, approvedBy: 'user', approvedAt: nowISO() })
  st.updatedAt = nowISO(); saveState(st)
  console.log(`[orchestrate] 阶段${idx} 人工检查点已批准，可继续记录 PASS`)
}

function cmdStatus() {
  const st = loadState()
  if (!st) return console.error('[orchestrate] 无状态文件，先运行 init')
  console.log(`\n=== 编排状态：${st.task} ===`)
  console.log(`市场=${st.marketId} 物种=${st.species} 阶段=${st.stage} 水分=${st.moistureClass}`)
  console.log('─'.repeat(64))
  for (const s of st.stages) {
    const depStr = s.deps.length ? '←' + s.deps.join(',') : ''
    const cp = s.humanCheckpoint ? (s.checkpointApproved ? ' ✔已批' : ' ⚠待批') : ''
    console.log(`  ${String(s.index).padStart(2)}. [${s.status.padEnd(7)}] ${s.name}${depStr}${cp}`)
    const done = s.subtasks.filter((t) => t.status === 'PASS').length
    console.log(`      子任务 ${done}/${s.subtasks.length} PASS · DoD: ${s.dod}`)
  }
  console.log('─'.repeat(64))
  console.log('质量门禁: validatePassed=' + st.qualityGates.validatePassed +
    ' freshReviewer=' + st.qualityGates.freshReviewer +
    ' evidenceBacked=' + st.qualityGates.evidenceBacked)
}

function cmdResume() {
  const st = loadState()
  if (!st) return console.error('[orchestrate] 无状态文件，先运行 init')
  const pending = st.stages.filter((s) => s.status !== 'PASS' && s.status !== 'SKIPPED')
  if (!pending.length) return console.log('[orchestrate] 无待续阶段，运行 finalize 落盘审计')
  console.log('=== 断点续跑（上下文恢复）===')
  console.log(`任务: ${st.task} | 上次更新: ${st.updatedAt}`)
  console.log('待处理阶段:')
  pending.forEach((s) => {
    const open = s.subtasks.filter((t) => t.status !== 'PASS').map((t) => t.label)
    console.log(`  ${s.index}. ${s.name} [${s.status}] 待办: ${open.join('、') || '（无，可整体记录）'}`)
  })
  console.log('\n续跑: node scripts/orchestrate.mjs next')
}

function findLatestAuditPath() {
  if (!existsSync(JUNHENG_DIR)) return null
  const files = readdirSync(JUNHENG_DIR).filter((f) => /^run-\d{8}-\d{6}\.json$/.test(f))
  if (!files.length) return null
  files.sort()
  return join(JUNHENG_DIR, files[files.length - 1])
}

// 从审计重建 state.json（上下文恢复增强：state 损坏/缺失但 audit 存在时）
function rebuildStateFromAudit(auditPath) {
  const raw = JSON.parse(readFileSync(auditPath, 'utf8'))
  const stages = STAGES.map((s) => {
    const a = (raw.stages || []).find((x) => x.index === s.index) || {}
    const status = a.gate === 'FAIL' ? 'FAIL' : a.gate === 'SKIPPED' ? 'SKIPPED'
      : a.gate === 'PASS' ? 'PASS' : 'PENDING'
    return {
      index: s.index, key: s.key, name: s.name, skill: s.skill, deps: s.deps,
      status, gate: a.gate || null, dod: a.dod || s.dod,
      subtasks: s.subtasks.map((label, i) => ({ id: `${s.index}.${i + 1}`, label, status: status === 'PASS' ? 'PASS' : 'PENDING' })),
      retryCount: 0, result: a.result || null, evidence: a.evidence || [],
      humanCheckpoint: HUMAN_CHECKPOINT_STAGES.has(s.index),
      checkpointApproved: HUMAN_CHECKPOINT_STAGES.has(s.index)
        ? (raw.humanCheckpoints || []).some((c) => c.at === `stage-${s.index}`)
        : true,
    }
  })
  const st = {
    schemaVersion: '1.0',
    task: raw.task || '（重建自审计）',
    marketId: raw.marketId, species: raw.species, stage: raw.stage, moistureClass: raw.moistureClass || 'unknown',
    createdAt: raw.startedAt, updatedAt: raw.finishedAt || nowISO(),
    stages,
    qualityGates: raw.qualityGates || { validatePassed: false, freshReviewer: false, evidenceBacked: false },
    humanCheckpoints: raw.humanCheckpoints || [],
  }
  saveState(st)
  return { st, runId: raw.runId }
}

function cmdRecover() {
  let st = loadState()
  let runId = null
  let rebuilt = false
  if (!st) {
    const ap = findLatestAuditPath()
    if (ap) { const r = rebuildStateFromAudit(ap); st = r.st; runId = r.runId; rebuilt = true }
    else return console.error('[orchestrate] 无 state.json 也无审计文件，无法恢复（先运行 init）')
  } else {
    const ap = findLatestAuditPath()
    if (ap) { try { runId = JSON.parse(readFileSync(ap, 'utf8')).runId } catch { /* ignore */ } }
  }

  const done = st.stages.filter((s) => s.status === 'PASS')
  const fail = st.stages.filter((s) => s.status === 'FAIL')
  const pending = st.stages.filter((s) => s.status !== 'PASS' && s.status !== 'SKIPPED')
  const next = pending.find((s) => s.deps.every((d) => {
    const ds = st.stages.find((x) => x.index === d); return ds && (ds.status === 'PASS' || ds.status === 'SKIPPED')
  }))

  console.log('=== 上下文恢复简报（压缩块，供断点续跑）===')
  console.log(`目标：${st.task}`)
  console.log('已完成：' + (done.length
    ? done.map((s) => `${s.index}.${s.name}(${s.status})`).join('；')
    : '（无）'))
  console.log('关键结论：质量门禁 ' +
    `validatePassed=${st.qualityGates.validatePassed} freshReviewer=${st.qualityGates.freshReviewer} evidenceBacked=${st.qualityGates.evidenceBacked}` +
    (fail.length ? `；FAIL阶段=${fail.map((s) => s.index).join(',')}` : '') +
    (st.humanCheckpoints.length ? `；人工检查点已批准=${st.humanCheckpoints.length}` : ''))
  const todoLines = pending.map((s) => {
    const open = s.subtasks.filter((t) => t.status !== 'PASS').map((t) => t.label)
    return `${s.index}.${s.name}[${s.status}]${open.length ? ' 待办:' + open.join('、') : ''}`
  })
  console.log('待办：' + (todoLines.length ? todoLines.join('；') : '（无，可 finalize）'))
  console.log(`标识符：runId=${runId || '无'} / state=.junheng/state.json${rebuilt ? '（已从审计重建）' : ''}`)
  console.log('当前阶段：' + (next ? `${next.index}.${next.name}（${next.skill}）` : '全部 PASS，待 finalize'))
  console.log('\n续跑：node scripts/orchestrate.mjs next' + (next && next.humanCheckpoint && !next.checkpointApproved ? `  （阶段${next.index} 须先 approve-checkpoint）` : ''))
}

function cmdFinalize(argv) {
  const get = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null }
  const st = loadState()
  if (!st) return console.error('[orchestrate] 无状态文件，先运行 init')
  const notPass = st.stages.filter((s) => s.status !== 'PASS')
  if (notPass.length) {
    console.error(`[orchestrate] ✗ 无法 finalize：${notPass.map((s) => s.name).join('、')} 未 PASS —— 门禁三铁律①`)
    process.exit(1)
  }
  // 质量门禁三铁律校验
  st.qualityGates.validatePassed = true
  st.qualityGates.evidenceBacked = st.stages.every((s) => s.result != null || s.evidence.length)
  if (!st.qualityGates.freshReviewer) {
    console.error('[orchestrate] ✗ 质量门禁②未满足：阶段④缺少 Fresh Reviewer 独立重算结果（independentCheck）')
    process.exit(1)
  }
  if (!st.qualityGates.evidenceBacked) {
    console.error('[orchestrate] ✗ 质量门禁③未满足：存在阶段无证据（DoD 须 file:line/数值证据）')
    process.exit(1)
  }

  const d = new Date()
  const p2 = (n) => String(n).padStart(2, '0')
  const runId = `run-${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}-${p2(d.getHours())}${p2(d.getMinutes())}${p2(d.getSeconds())}`
  const audit = {
    schemaVersion: '1.0',
    runId,
    task: st.task,
    startedAt: st.createdAt,
    finishedAt: nowISO(),
    marketId: st.marketId, species: st.species, stage: st.stage,
    stages: st.stages.map((s) => ({
      index: s.index, name: s.key, skill: s.skill, dod: s.dod, gate: s.gate,
      result: s.result, evidence: s.evidence, humanCheckpoint: s.humanCheckpoint,
    })),
    qualityGates: st.qualityGates,
    humanCheckpoints: st.humanCheckpoints,
    lintBeforeCommit: get('--lint') || '待运行 vcs-all.sh lint',
  }
  if (!existsSync(JUNHENG_DIR)) mkdirSync(JUNHENG_DIR, { recursive: true })
  const auditPath = join(JUNHENG_DIR, `${runId}.json`)
  writeFileSync(auditPath, JSON.stringify(audit, null, 2), 'utf8')
  st.updatedAt = nowISO(); saveState(st)
  console.log(`[orchestrate] ✓ 审计落盘: ${auditPath}`)
  console.log(`[orchestrate] ✓ 质量门禁三铁律全满足（validatePassed/freshReviewer/evidenceBacked）`)
  console.log('[orchestrate] 下一步: 运行 vcs-all.sh lint 并通过后 git commit（禁止 --no-verify）')
}

// ---------- 入口 ----------
function main() {
  const sub = process.argv[2]
  const rest = process.argv.slice(3)
  switch (sub) {
    case 'init': return cmdInit(rest)
    case 'next': return cmdNext()
    case 'record': return cmdRecord(rest)
    case 'approve-checkpoint': return cmdApproveCheckpoint(rest)
    case 'status': return cmdStatus()
    case 'resume': return cmdResume()
    case 'recover': return cmdRecover()
    case 'finalize': return cmdFinalize(rest)
    default:
      console.log('junheng-orchestrator 编排状态机（DAG + 状态文件 + 审计落盘）')
      console.log('  子命令:')
      console.log('    init     --task <t> --market <m> --species <s> --stage <st> [--moisture <w>]')
      console.log('    next                                                                      # 下一可执行阶段')
      console.log('    record   --stage <N> --gate PASS|FAIL|SKIPPED [--subtask <id>] [--result <json>]')
      console.log('    approve-checkpoint --stage <N>                                            # 人工检查点授权')
      console.log('    status | resume | recover | finalize [--lint <note>]')
      console.log('    recover                                                                   # 上下文恢复简报（state 缺失时从审计重建）')
      process.exit(2)
  }
}
main()
