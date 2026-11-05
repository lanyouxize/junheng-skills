// poc.mjs — junheng-formulate POC：纯 JS 单纯形求解器 + junheng 数据接线验证
// 运行：node ~/.workbuddy/skills/junheng-formulate/scripts/poc.mjs
import { solveLP, formulateLeastCost } from './formulate.mjs'
import { createRequire } from 'module'
import { fileURLToPath, pathToFileURL } from 'url'
import path from 'path'

const req = createRequire(import.meta.url)
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const standardsPath = path.join(ROOT, 'junheng-standards/scripts/vendor/standards.js')
const ingredientDbPath = path.join(ROOT, 'junheng-core/scripts/data/ingredient_db.js')

let pass = 0, fail = 0
const approx = (a, b, eps = 1e-3) => Math.abs(a - b) <= eps
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  ✓ ${name}  ${detail ?? ''}`) }
  else { fail++; console.log(`  ✗ ${name}  ${detail ?? ''}`) }
}

console.log('\n========== 用例 A：合成 2 原料（手算可验）==========')
// 原料 A(填料): 价2, 蛋白5%DM ; 原料 B(蛋白源): 价10, 蛋白40%DM
// 约束: 蛋白>=18, Σ=1 → 解析解 B=0.3714, A=0.6286, 成本=4.971
{
  const ingredients = [
    { id: 'A', name: '填料', price: 2, nutrients: { crude_protein: 5 } },
    { id: 'B', name: '蛋白源', price: 10, nutrients: { crude_protein: 40 } },
  ]
  const constraints = [{ key: 'crude_protein', label: '粗蛋白', min: 18, unit: '%DM' }]
  const r = formulateLeastCost({ ingredients, constraints })
  const xB = r.recipe[1].share, xA = r.recipe[0].share
  console.log(`  结果: A=${xA}, B=${xB}, 单位成本=${r.unitCost}, 达成蛋白=${r.achieved.crude_protein.value}`)
  check('求解最优', r.status === 'optimal')
  check('B 占比=0.3714', approx(xB, 0.3714), `got ${xB}`)
  check('A 占比=0.6286', approx(xA, 0.6286), `got ${xA}`)
  check('单位成本=4.971', approx(r.unitCost, 4.971, 1e-2), `got ${r.unitCost}`)
  check('蛋白约束达成(>=18)', r.achieved.crude_protein.value >= 18 - 1e-6, `got ${r.achieved.crude_protein.value}`)
  check('占比和=1', approx(xA + xB, 1), `got ${xA + xB}`)
}

console.log('\n========== 用例 B：真实 junheng 数据（约束取自 resolveStandard）==========')
{
  const { resolveStandard } = await import(pathToFileURL(standardsPath).href)
  const db = req(ingredientDbPath).default
  // 取真实原料并按 %DM 折算粗蛋白
  const byCode = Object.fromEntries(db.map((x) => [x.code, x]))
  const pick = (code) => {
    const x = byCode[code]
    const cpDM = x.crude_protein / (1 - x.moisture / 100)
    return { id: x.code, name: x.name, price: x.price, cpDM, cpAF: x.crude_protein, moist: x.moisture }
  }
  const corn = pick('02010004')   // 玉米淀粉
  const meal = pick('01020114')   // 水解鸡肉粉
  console.log(`  玉米淀粉: 价${corn.price}, 粗蛋白(风干前)${corn.cpAF}%, 水分${corn.moist}%, 折算%DM=${corn.cpDM.toFixed(2)}`)
  console.log(`  水解鸡肉粉: 价${meal.price}, 粗蛋白(风干前)${meal.cpAF}%, 水分${meal.moist}%, 折算%DM=${meal.cpDM.toFixed(2)}`)

  const std = resolveStandard({ marketId: 'intl', species: 'dog', stage: 'adult' })
  const cpItem = std.items.find((i) => i.key === 'crude_protein')
  console.log(`  resolveStandard(intl,dog,adult) 粗蛋白约束: ${cpItem.text} (min=${cpItem.min})`)

  const ingredients = [
    { id: corn.id, name: corn.name, price: corn.price, nutrients: { crude_protein: +corn.cpDM.toFixed(4) } },
    { id: meal.id, name: meal.name, price: meal.price, nutrients: { crude_protein: +meal.cpDM.toFixed(4) } },
  ]
  const r = formulateLeastCost({ ingredients, constraints: [cpItem] })

  // 解析解（仅 2 原料 + 蛋白下限，最优点落在蛋白边界）
  const cp0 = corn.cpDM, cp1 = meal.cpDM, p0 = corn.price, p1 = meal.price, min = cpItem.min
  const x1exp = (min - cp0) / (cp1 - cp0)
  const x0exp = 1 - x1exp
  const costExp = p0 * x0exp + p1 * x1exp
  console.log(`  结果: 玉米淀粉=${r.recipe[0].share}, 水解鸡肉粉=${r.recipe[1].share}, 单位成本=${r.unitCost}, 达成蛋白=${r.achieved.crude_protein.value}`)
  console.log(`  解析解: 玉米淀粉=${x0exp.toFixed(4)}, 水解鸡肉粉=${x1exp.toFixed(4)}, 成本=${costExp.toFixed(4)}`)
  check('求解最优', r.status === 'optimal')
  check('水解鸡肉粉占比=解析解', approx(r.recipe[1].share, x1exp, 1e-3), `got ${r.recipe[1].share}`)
  check('玉米淀粉占比=解析解', approx(r.recipe[0].share, x0exp, 1e-3), `got ${r.recipe[0].share}`)
  check('单位成本=解析解', approx(r.unitCost, costExp, 1e-2), `got ${r.unitCost}`)
  check('蛋白约束精确绑定(=18)', approx(r.achieved.crude_protein.value, 18, 1e-2), `got ${r.achieved.crude_protein.value}`)
  check('占比和=1', approx(r.recipe[0].share + r.recipe[1].share, 1), `got ${r.recipe[0].share + r.recipe[1].share}`)
}

console.log(`\n========== POC 结果: ${pass} 通过 / ${fail} 失败 ==========\n`)
process.exit(fail === 0 ? 0 : 1)
