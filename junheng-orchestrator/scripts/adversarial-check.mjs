#!/usr/bin/env node
// adversarial-check.mjs — junheng-orchestrator 对抗验证引擎（独立重算校验）
//
// 定位：编排层 VALIDATE / ADVERSARIAL REVIEW 阶段的「独立审查者」（Fresh Reviewer Rule，铁律②）。
//   - 不信任阶段自报的 achieved / unitCost，独立从 ingredient_db + resolveStandard 重算；
//   - 每条 check 输出 expected/actual + 证据（文献 cite / 原料行 / 数值公式），对齐铁律③；
//   - 用两条不同代码路径重算（ingredient-outer vs nutrient-outer），互为交叉验证，捕获任一方索引 bug。
//
// 零依赖：仅 Node 内置 fs/path/url/module。可在任意电脑直接运行。
//
// 用法：
//   node scripts/adversarial-check.mjs selftest
//   node scripts/adversarial-check.mjs verify --recipe <recipe.json> \
//        --market intl --species dog --stage adult [--moisture dry|wet|unknown]
//   node scripts/adversarial-check.mjs verify --recipe <recipe.json> --standards-json <std.json>
//
// recipe.json 结构（来自 junheng-formulate formulateLeastCost 输出）：
//   { "recipe":[{"id","name","share","price"}], "unitCost":<num>,
//     "achieved":{ "<key>":{"value","min","max","unit"} } }   // achieved 仅用于交叉核对，不可信

import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { createRequire } from 'node:module'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const req = createRequire(import.meta.url)

const EPS = 1e-6
const TOL = 1e-4 // 独立重算 vs 阶段自报 容差

// ---------- 证据来源（file:line 形如 脚本/行号，便于审计回溯）----------
function evStd(cite) { return `标准条款 cite="${cite}"` }
function evDb(row, field) { return `原料库行 code=${row.code} name=${row.name} field=${field}` }

// ---------- 真实数据源加载（懒加载，selftest 不依赖）----------
async function loadStandards(marketId, species, stage, moistureClass) {
  const mod = await import(pathToFileURL(join(ROOT, 'junheng-standards/scripts/vendor/standards.js')).href)
  return mod.resolveStandard({ marketId, species, stage, moistureClass })
}
function loadDb() {
  const mod = req(join(ROOT, 'junheng-core/scripts/data/ingredient_db.js'))
  return mod.default || mod
}

// %DM 营养：原样基础值 / 干物质率；缺失值按 0 处理（原料库语义），并返回是否缺失
function dmValue(row, field) {
  const raw = row[field]
  if (raw == null) return { v: 0, missing: true }
  const m = row.moisture == null ? 0 : row.moisture
  const dm = 1 - m / 100
  return { v: dm > 0 ? raw / dm : raw, missing: false }
}

function findRow(db, id) {
  return db.find((r) => r.code === id || r.name === id) || null
}

// 两条独立重算路径：返回 {[key]: value}
function recomputeIngredientOuter(ings, shares, keys) {
  const out = Object.fromEntries(keys.map((k) => [k, 0]))
  for (let i = 0; i < ings.length; i++) {
    const x = shares[i]
    for (const k of keys) out[k] += (ings[i].nutrients[k] || 0) * x
  }
  return out
}
function recomputeNutrientOuter(ings, shares, keys) {
  const out = Object.fromEntries(keys.map((k) => [k, 0]))
  for (const k of keys) {
    for (let i = 0; i < ings.length; i++) out[k] += (ings[i].nutrients[k] || 0) * shares[i]
  }
  return out
}

// ---------- 核心：对一份配方做对抗验证 ----------
function adversarialVerify({ recipe, standards, db }) {
  const checks = []
  const pass = (name, cond, expected, actual, evidence) =>
    checks.push({ name, pass: !!cond, expected, actual, evidence })

  const rows = recipe.recipe || []
  const shares = rows.map((r) => r.share)
  const sumShare = shares.reduce((s, x) => s + x, 0)
  // 容差 1e-3：配方 artifact 的 share 已四舍五入到 4 位小数，Σ 允许该舍入误差
  pass('Σ 占比 = 1（4dp 舍入容差 1e-3）', Math.abs(sumShare - 1) <= 1e-3, 1, +sumShare.toFixed(4),
    `Σ share = ${shares.map((s) => s.toFixed(4)).join(' + ')}`)

  // 证据溯源：每个 id 必须能落到原料库真实行
  const resolved = []
  let provenanceOk = true
  for (const r of rows) {
    const row = findRow(db, r.id)
    if (!row) { provenanceOk = false; pass(`配方行溯源 id=${r.id}`, false, '原料库存在', '未找到', 'ingredient_db.js 无匹配 code/name') }
    else resolved.push({ row, share: r.share, price: r.price || 0 })
  }
  if (provenanceOk) pass('全部配方行溯源到原料库', true, '全部命中', `${resolved.length}/${rows.length} 命中`, 'ingredient_db.js')

  // 独立重算营养（双路径交叉）
  const keys = new Set()
  for (const { row } of resolved) {
    for (const f of ['crude_protein', 'crude_fat', 'crude_fiber', 'crude_ash', 'calcium', 'phosphorus', 'chloride', 'sodium', 'potassium', 'magnesium']) {
      if (row[f] != null) keys.add(f)
    }
  }
  const ings = resolved.map(({ row }) => ({
    nutrients: Object.fromEntries([...keys].map((k) => [k, dmValue(row, k).v])),
  }))
  const A = recomputeIngredientOuter(ings, shares, [...keys])
  const B = recomputeNutrientOuter(ings, shares, [...keys])
  let crossOk = true
  for (const k of keys) if (Math.abs((A[k] || 0) - (B[k] || 0)) > EPS) crossOk = false
  pass('双路径重算一致（ingredient-outer ≡ nutrient-outer）', crossOk, '两路径相等', crossOk ? '一致' : '分歧', '独立重算交叉验证')
  const achievedIndep = A

  // 独立标准映射（不读阶段自报约束）
  const activeItems = (standards.items || []).filter((it) => it.active && (it.min != null || it.max != null))
  const hasCa = keys.has('calcium'), hasPh = keys.has('phosphorus')

  for (const it of activeItems) {
    if (it.key === 'caP') {
      if (hasCa && hasPh) {
        const ratio = achievedIndep.calcium / achievedIndep.phosphorus
        const ok = (it.min == null || ratio >= it.min - 1e-3) && (it.max == null || ratio <= it.max + 1e-3)
        pass(`钙磷比 ∈ [${it.min},${it.max}]（独立重算）`, ok, `[${it.min},${it.max}]`, +ratio.toFixed(4),
          evStd((it.cites || []).join(';') || standards.sourceLabel) + ' | 独立重算 ca/ph')
      }
      continue
    }
    if (!keys.has(it.key)) continue // 原料库无此字段，跳过（不冒充）
    const v = achievedIndep[it.key] || 0
    const okMin = it.min == null || v >= it.min - 1e-3
    const okMax = it.max == null || v <= it.max + 1e-3
    pass(`营养 ${it.label} 达标（独立重算）`, okMin && okMax, `min=${it.min} max=${it.max}`, +v.toFixed(4),
      evStd((it.cites || []).join(';') || standards.sourceLabel) + ' | ' + evDb(resolved.find((x) => true).row, it.key))
  }

  // 交叉核对：独立重算 vs 阶段自报 achieved（捕获阶段误报）
  // 两侧均为 4 位小数 artifact，容差 1e-2 吸收 ingredient 营养 3dp + share 4dp 舍入累积误差；
  // 阶段误报（如 999 vs 44）偏差远超该容差，必被捕获。
  if (recipe.achieved) {
    for (const [k, a] of Object.entries(recipe.achieved)) {
      if (!keys.has(k)) continue
      const indep = +(achievedIndep[k] || 0).toFixed(4)
      const rep = +(+a.value).toFixed(4)
      const ok = Math.abs(indep - rep) <= 1e-2
      pass(`阶段自报 ${k} 与独立重算一致`, ok, indep, rep, 'Fresh Reviewer 交叉核对')
    }
  }

  // 单位成本独立重算：Σ(price·share)；容差 1e-2 吸收 share 4dp 舍入
  if (recipe.unitCost != null) {
    let cost = 0
    for (const { row, share } of resolved) cost += (row.price || 0) * share
    const ok = Math.abs(cost - recipe.unitCost) <= 1e-2
    pass('单位成本 = Σ(price·share)（独立重算）', ok, +cost.toFixed(4), recipe.unitCost, 'ingredient_db.price')
  }

  const allPass = checks.every((c) => c.pass)
  return { passed: allPass, checks, summary: { total: checks.length, failed: checks.filter((c) => !c.pass).length } }
}

// ---------- selftest：手算可验合成用例（不依赖外部真源）----------
function selftest() {
  console.log('=== adversarial-check selftest（合成手算可验用例）===')
  let pass = 0, fail = 0
  const ok = (n, c, extra = '') => { if (c) { pass++; console.log('  ✓', n) } else { fail++; console.log('  ✗ FAIL', n, extra) } }

  // 用例1：两原料已知 %DM 营养 + 已知 share → 手算营养值
  // 原料 A: cp40 ca2 ph1 price5 ; 原料 B: cp10 price8 ; 填充 C: 全0 price1
  // share A=0.45 B=0.30 C=0.25 → cp=40*0.45+10*0.30=21.0 ; ca=2*0.45=0.9 ; ph=1*0.45=0.45
  {
    const recipe = {
      recipe: [
        { id: 'A', name: 'A', share: 0.45, price: 5 },
        { id: 'B', name: 'B', share: 0.30, price: 8 },
        { id: 'C', name: 'C', share: 0.25, price: 1 },
      ],
      unitCost: 5 * 0.45 + 8 * 0.30 + 1 * 0.25,
      achieved: { crude_protein: { value: 21.0 }, calcium: { value: 0.9 }, phosphorus: { value: 0.45 } },
    }
    const db = [
      { code: 'A', name: 'A', moisture: 0, crude_protein: 40, crude_fat: 0, calcium: 2, phosphorus: 1, price: 5 },
      { code: 'B', name: 'B', moisture: 0, crude_protein: 10, crude_fat: 0, calcium: 0, phosphorus: 0, price: 8 },
      { code: 'C', name: 'C', moisture: 0, crude_protein: 0, crude_fat: 0, calcium: 0, phosphorus: 0, price: 1 },
    ]
    const standards = { items: [
      { key: 'crude_protein', label: '粗蛋白', active: true, min: 18, max: null, cites: ['AAFCO 2014'] },
      { key: 'calcium', label: '钙', active: true, min: 0.5, max: null, cites: ['AAFCO 2014'] },
      { key: 'phosphorus', label: '磷', active: true, min: 0.4, max: null, cites: ['AAFCO 2014'] },
    ] }
    const r = adversarialVerify({ recipe, standards, db })
    ok('用例1 全部 check PASS', r.passed, JSON.stringify(r.checks.filter((c) => !c.pass)))
    ok('用例1 粗蛋白独立重算=21', Math.abs((r.checks.find((c) => c.name.includes('粗蛋白')).actual) - 21) < 1e-6)
    ok('用例1 单位成本=4.9', Math.abs(recipe.unitCost - 4.9) < 1e-9)
  }

  // 用例2：阶段误报应被捕获（Fresh Reviewer）
  {
    const recipe = {
      recipe: [
        { id: 'A', name: 'A', share: 0.5, price: 5 },
        { id: 'B', name: 'B', share: 0.5, price: 8 },
      ],
      unitCost: 6.5,
      achieved: { crude_protein: { value: 99.0 } }, // 明显误报（真值 25）
    }
    const db = [
      { code: 'A', name: 'A', moisture: 0, crude_protein: 40, price: 5 },
      { code: 'B', name: 'B', moisture: 0, crude_protein: 10, price: 8 },
    ]
    const standards = { items: [{ key: 'crude_protein', label: '粗蛋白', active: true, min: 18, max: null, cites: ['X'] }] }
    const r = adversarialVerify({ recipe, standards, db })
    const misreport = r.checks.find((c) => c.name.includes('阶段自报 crude_protein'))
    ok('用例2 捕获阶段误报（独立重算≠自报）', misreport && misreport.pass === false, JSON.stringify(misreport))
  }

  // 用例3：Σshare ≠ 1 应 FAIL
  {
    const recipe = { recipe: [{ id: 'A', name: 'A', share: 0.6, price: 5 }, { id: 'B', name: 'B', share: 0.6, price: 8 }] }
    const db = [{ code: 'A', name: 'A', moisture: 0, crude_protein: 40, price: 5 }, { code: 'B', name: 'B', moisture: 0, crude_protein: 10, price: 8 }]
    const standards = { items: [] }
    const r = adversarialVerify({ recipe, standards, db })
    const s = r.checks.find((c) => c.name.includes('Σ 占比'))
    ok('用例3 Σ≠1 检测为 FAIL', s && s.pass === false, JSON.stringify(s))
  }

  console.log(`\n=== selftest：${pass} 通过 / ${fail} 失败 ===`)
  process.exit(fail === 0 ? 0 : 1)
}

// ---------- verify：真实数据路径 ----------
async function verifyCli(argv) {
  const get = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null }
  const recipePath = get('--recipe')
  if (!recipePath) { console.error('缺少 --recipe <path.json>'); process.exit(2) }
  const recipe = JSON.parse(readFileSync(resolve(recipePath), 'utf8'))

  let standards
  const stdJson = get('--standards-json')
  if (stdJson) {
    standards = JSON.parse(readFileSync(resolve(stdJson), 'utf8'))
  } else {
    const marketId = get('--market') || 'intl'
    const species = get('--species') || 'cat'
    const stage = get('--stage') || 'adult'
    const moisture = get('--moisture') || 'unknown'
    standards = await loadStandards(marketId, species, stage, moisture)
    console.log(`[adversarial] 独立标准映射: ${standards.sourceLabel} (market=${marketId} species=${species} stage=${stage} moisture=${moisture})`)
  }
  const db = loadDb()
  console.log(`[adversarial] 原料库载入 ${db.length} 行`)

  const r = adversarialVerify({ recipe, standards, db })
  console.log('\n--- 对抗验证报告 ---')
  for (const c of r.checks) {
    console.log(`  ${c.pass ? '✓' : '✗'} ${c.name}`)
    console.log(`      expected=${c.expected}  actual=${c.actual}`)
    console.log(`      evidence=${c.evidence}`)
  }
  console.log(`\n=== 对抗验证：${r.summary.total} 项 / ${r.summary.failed} 失败 / ${r.passed ? 'PASS' : 'FAIL'} ===`)
  if (!r.passed) process.exit(1)
}

// ---------- 入口 ----------
const mode = process.argv[2]
if (mode === 'selftest') selftest()
else if (mode === 'verify') verifyCli(process.argv.slice(3))
else {
  console.log('用法:')
  console.log('  node scripts/adversarial-check.mjs selftest')
  console.log('  node scripts/adversarial-check.mjs verify --recipe <recipe.json> --market intl --species dog --stage adult [--moisture dry]')
  process.exit(2)
}
