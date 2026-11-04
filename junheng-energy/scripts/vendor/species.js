/**
 * **物种口径的唯一真源**（cat / dog 的缺省值与归一化）。
 *
 * ## 为什么单独一个模块
 * `species` 是被 5 个以上模块共同消费的**基础事实**：energy（RER 指数）、bcsChart
 * （判据表）、feedingGuide（减重速度）、standards（限值档）、nutrition（需求计算）。
 * 此前各模块各写各的缺省值：
 *   · `standards.js` / `nutrition.js` / `feedingGuide.js` 缺省 **cat**
 *   · `energy.js` / `bcsChart.js` 缺省 **dog**
 * 于是**省略 species 时，同一只 4kg 宠物**在 `nutrition.requirements` 得 177 kcal（猫），
 * 在 `energy.rer` 得 198 kcal（犬）—— 相差 12%，两边都不报错，是最难发现的一类缺陷。
 *
 * 收敛办法：把「缺省是什么、怎么归一化」提到本模块，所有消费方 import 它。
 * 本模块**零依赖**（不 import 任何东西），因此不会在任何依赖方向上引入环；
 * 并且 `energy.js` 与 `bcsChart.js` 可以继续保持各自的「零依赖」设计属性。
 *
 * ## 为什么缺省是「猫」
 * 项目自身的权威默认已是猫，三处独立来源一致：
 *   · `healthCheck.js` 的 `DEFAULT_PROFILE.species = 'cat'`
 *   · `FormulaPage.jsx` 新建档案默认 `species: 'cat'`
 *   · `SPECIES` 常量排列顺序（cat 在前）
 * 因此把 energy / bcsChart 对齐到猫是**向既有权威收敛**，不是新立标准。
 *
 * ## 使用约定
 * 新增任何取 species 的模块，请 `import { DEFAULT_SPECIES, normSpecies } from './species.js'`，
 * **不要**再写字面量 `'cat'` / `'dog'` 作为缺省。
 */

/** 全站统一的物种缺省值 */
export const DEFAULT_SPECIES = 'cat'

/** 合法物种取值（供门面 enum / 校验复用） */
export const SPECIES_IDS = ['cat', 'dog']

/**
 * 把任意 species 值归一化为 `'cat' | 'dog'`。
 * 缺省、空值、非法值一律回落 `DEFAULT_SPECIES`（猫）—— 这是「缺省方向」的唯一决定处。
 */
export function normSpecies(species) {
  if (species === 'dog') return 'dog'
  if (species === 'cat') return 'cat'
  return DEFAULT_SPECIES
}
