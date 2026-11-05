// poc.mjs — junheng-formulate 运行时验证套件
// 覆盖：求解器数学正确性 + 多营养 + 比值约束(caP) + 原料上限 + 三策略 + 真实 junheng 数据接线 + 不可行诊断
// 运行：cd junheng-formulate && node scripts/poc.mjs
import { solveLP, formulateLeastCost } from './formulate.mjs'
import { createRequire } from 'module'
import { fileURLToPath, pathToFileURL } from 'url'
import path from 'path'

const req = createRequire(import.meta.url)
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

let pass = 0, fail = 0
function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log('  ✓', name) }
  else { fail++; console.log('  ✗ FAIL', name, extra) }
}
const approx = (a, b, tol = 1e-3) => Math.abs(a - b) <= tol
const sum1 = (r) => r.recipe.reduce((s, x) => s + x.share, 0)

// ---------- 基础求解器（手算可验）----------
console.log('\n[1] 求解器基础：合成两变量 min 5x+40y s.t. 5x+40y>=18, x+y=1')
{
  const r = solveLP({
    nVars: 2, objective: [2, 10],
    constraints: [{ coeffs: [5, 40], op: '>=', rhs: 18 }, { coeffs: [1, 1], op: '=', rhs: 1 }],
  })
  ok('状态 optimal', r.status === 'optimal')
  ok('x1=0.6286', approx(r.x[0], 0.6286, 1e-3), JSON.stringify(r.x))
  ok('x2=0.3714', approx(r.x[1], 0.3714, 1e-3))
  ok('obj=4.9714', approx(r.objective, 4.9714, 1e-3))
}

// ---------- 多营养 + 比值约束（caP）+ 真实可手算 ----------
console.log('\n[2] 多营养 + caP 比值：A(cp40,ca2,ph1) B(cp10) C(filler)')
{
  const ings = [
    { id: 'A', name: '蛋白源', price: 5, nutrients: { crude_protein: 40, calcium: 2, phosphorus: 1 } },
    { id: 'B', name: '次蛋白', price: 8, nutrients: { crude_protein: 10, calcium: 0, phosphorus: 0 } },
    { id: 'C', name: '填充', price: 1, nutrients: { crude_protein: 0, calcium: 0, phosphorus: 0 } },
  ]
  const cons = [
    { key: 'crude_protein', label: '粗蛋白', min: 18, unit: '%' },
    { key: 'calcium', label: '钙', min: 0.5, unit: '%' },
    { key: 'phosphorus', label: '磷', min: 0.4, unit: '%' },
    { key: 'caP', label: '钙磷比', min: 1.0, max: 2.0, unit: 'ratio', ratio: { num: 'calcium', den: 'phosphorus' } },
  ]
  const r = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'least_cost' })
  ok('状态 optimal', r.status === 'optimal')
  ok('Σ占比=1', approx(sum1(r), 1, 1e-3), 'sum=' + sum1(r))
  const a = r.recipe.find((x) => x.id === 'A').share
  ok('A≈0.45（cp 下限绑定）', approx(a, 0.45, 1e-2), 'A=' + a)
  ok('粗蛋白达成≥18', r.achieved.crude_protein.value >= 18 - 1e-3)
  ok('钙达成≥0.5', r.achieved.calcium.value >= 0.5 - 1e-3)
  ok('磷达成≥0.4', r.achieved.phosphorus.value >= 0.4 - 1e-3)
  const ratio = r.achieved.calcium.value / r.achieved.phosphorus.value
  ok('钙磷比∈[1,2]', ratio >= 1 - 1e-3 && ratio <= 2 + 1e-3, 'ratio=' + ratio.toFixed(3))
  ok('成本=2.8', approx(r.unitCost, 2.8, 1e-2), 'cost=' + r.unitCost)
}

// ---------- 原料上限 ingredient_max ----------
console.log('\n[3] 原料上限：填充 C 限 0.3 → 强制启用 B')
{
  const ings = [
    { id: 'A', name: '蛋白源', price: 5, nutrients: { crude_protein: 40, calcium: 2, phosphorus: 1 } },
    { id: 'B', name: '次蛋白', price: 8, nutrients: { crude_protein: 10, calcium: 0, phosphorus: 0 } },
    { id: 'C', name: '填充', price: 1, nutrients: { crude_protein: 0, calcium: 0, phosphorus: 0 } },
  ]
  const cons = [
    { key: 'crude_protein', label: '粗蛋白', min: 18, unit: '%' },
    { key: 'calcium', label: '钙', min: 0.5, unit: '%' },
    { key: 'phosphorus', label: '磷', min: 0.4, unit: '%' },
  ]
  const r = formulateLeastCost({ ingredients: ings, constraints: cons, ingredientMax: { C: 0.3 }, strategy: 'least_cost' })
  ok('状态 optimal', r.status === 'optimal')
  const c = r.recipe.find((x) => x.id === 'C').share
  ok('C≤0.3001（上限生效）', c <= 0.3001 + 1e-6, 'C=' + c)
  ok('Σ占比=1', approx(sum1(r), 1, 1e-3))
}

// ---------- 三策略对比（单营养 min+max，目标中点效应）----------
console.log('\n[4] 三策略：A(X40,p2) B(X0,p1)，X∈[10,30] 目标20')
{
  const ings = [
    { id: 'A', name: '高X', price: 2, nutrients: { X: 40 } },
    { id: 'B', name: '零X', price: 1, nutrients: { X: 0 } },
  ]
  const cons = [{ key: 'X', label: 'X', min: 10, max: 30, unit: '%' }]
  const lc = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'least_cost' })
  const bal = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'balanced' })
  ok('least_cost optimal', lc.status === 'optimal')
  ok('balanced optimal', bal.status === 'optimal')
  ok('least_cost 成本≤ balanced 成本', lc.unitCost <= bal.unitCost + 1e-9, `${lc.unitCost} vs ${bal.unitCost}`)
  ok('least_cost X≈10（贴下限）', approx(lc.achieved.X.value, 10, 1e-2), 'X=' + lc.achieved.X.value)
  ok('balanced X≈20（贴目标中点）', approx(bal.achieved.X.value, 20, 1e-2), 'X=' + bal.achieved.X.value)
  ok('balanced 偏差和≈0', approx(bal.deviationSum, 0, 1e-2), 'dev=' + bal.deviationSum)
}

// ---------- nutrient_max 预算上限 ----------
console.log('\n[5] nutrient_max 预算上限')
{
  const ings = [
    { id: 'A', name: '高X', price: 2, nutrients: { X: 40 } },
    { id: 'B', name: '零X', price: 1, nutrients: { X: 0 } },
  ]
  const cons = [{ key: 'X', label: 'X', min: 10, max: 30, unit: '%' }]
  const tight = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'nutrient_max', budget: 1.2 })
  const loose = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'nutrient_max', budget: 1.3 })
  ok('预算 1.2 < 最低成本 → 不可行', tight.status === 'infeasible', 'status=' + tight.status)
  ok('预算 1.3 ≥ 最低成本 → 可行', loose.status === 'optimal')
  ok('可行解成本≤1.3', loose.unitCost <= 1.3 + 1e-9, 'cost=' + loose.unitCost)
}

// ---------- 不可行诊断 ----------
console.log('\n[6] 不可行约束诊断')
{
  const ings = [
    { id: 'A', name: '蛋白源', price: 5, nutrients: { crude_protein: 40 } },
    { id: 'C', name: '填充', price: 1, nutrients: { crude_protein: 0 } },
  ]
  const r = formulateLeastCost({ ingredients: ings, constraints: [{ key: 'crude_protein', label: '粗蛋白', min: 100, unit: '%' }], strategy: 'least_cost' })
  ok('状态 infeasible', r.status === 'infeasible')
  ok('含质量门禁诊断', r.diagnostics && r.diagnostics.status === 'infeasible')
}

// ---------- 真实 junheng 数据接线 ----------
console.log('\n[7] 真实 junheng 接线：resolveStandard(intl,dog,adult) + 原料库真实行')
{
  let standards, db
  try {
    const stdMod = await import(pathToFileURL(`${ROOT}/junheng-standards/scripts/vendor/standards.js`).href)
    standards = stdMod
    const dbMod = req(`${ROOT}/junheng-core/scripts/data/ingredient_db.js`)
    db = dbMod.default || dbMod
  } catch (e) {
    console.log('  (跳过真实接线：本地真源不可达)', e.message)
  }
  if (standards && db) {
    const std = standards.resolveStandard({ marketId: 'intl', species: 'dog', stage: 'adult' })
    const codes = ['01020114', '02010004', '02020043']
    const names = ['鸡脂油', '湿粮调味粉CWP-7']
    const rows = db.filter((x) => codes.includes(x.code) || (names.some((n) => x.name.includes(n)) && x.price > 0))
    const ings = rows.map((x) => {
      const dm = 1 - x.moisture / 100
      return {
        id: x.code || x.name, name: x.name, price: x.price,
        nutrients: {
          crude_protein: +(x.crude_protein / dm).toFixed(3),
          crude_fat: +(x.crude_fat / dm).toFixed(3),
          calcium: +(x.calcium / dm).toFixed(4),
          phosphorus: +(x.phosphorus / dm).toFixed(4),
          chloride: +(x.chloride / dm).toFixed(4),
        },
      }
    })
    const keys = new Set(ings[0] ? Object.keys(ings[0].nutrients) : [])
    const cons = std.items
      .filter((it) => (it.min != null || it.max != null))
      .filter((it) => (it.key === 'caP' ? (keys.has('calcium') && keys.has('phosphorus')) : keys.has(it.key)))
      .map((it) => (it.key === 'caP'
        ? { key: 'caP', label: it.label, min: it.min, max: it.max, unit: it.unit, ratio: { num: 'calcium', den: 'phosphorus' } }
        : { key: it.key, label: it.label, min: it.min, max: it.max, unit: it.unit }))
    ok('原料集≥4（覆盖各营养素）', ings.length >= 4, 'count=' + ings.length)
    const r = formulateLeastCost({ ingredients: ings, constraints: cons, strategy: 'least_cost' })
    ok('状态 optimal', r.status === 'optimal', JSON.stringify(r.diagnostics))
    ok('Σ占比=1', approx(sum1(r), 1, 1e-3), 'sum=' + sum1(r))
    let allMin = true
    for (const k of ['crude_protein', 'crude_fat', 'calcium', 'phosphorus', 'chloride']) {
      const a = r.achieved[k]
      if (a && a.min != null && a.value < a.min - 1e-2) { allMin = false; console.log('    未达标', k, a.value, '<', a.min) }
    }
    ok('全部营养 min 达标', allMin)
    const ca = r.achieved.calcium.value, ph = r.achieved.phosphorus.value
    ok('钙磷比∈[1,2]', ca / ph >= 1 - 1e-2 && ca / ph <= 2 + 1e-2, 'ratio=' + (ca / ph).toFixed(3))
    console.log('    配方:', r.recipe.filter((x) => x.share > 1e-4).map((x) => `${x.name}:${(x.share * 100).toFixed(1)}%`).join(' '), '| 成本', r.unitCost)
  }
}

console.log(`\n=== POC 结果：${pass} 通过 / ${fail} 失败 ===`)
process.exit(fail === 0 ? 0 : 1)
