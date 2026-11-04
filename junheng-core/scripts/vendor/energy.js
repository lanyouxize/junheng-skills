/**
 * 能量体系：总能 GE / 消化能 DE / 代谢能 ME（多口径）。
 *
 * ## 为什么单独立一个模块
 * 项目原先只在 `nutrition.js` 里内联了两条 ME 公式（改良 Atwater / 经典 Atwater），
 * 而「总能 GE」需要一整套来自 NRC 2006 的燃烧热系数 + 消化率方程 + 尿能扣减。
 * 把它们放在这里，是为了让**每一条系数都带出处**，并且能被脚本单独测试
 * （`scripts/energy-ge-test.mjs`），不必先造一整个配方。
 *
 * ## 口径与出处（全部为 NRC 2006《Nutrient Requirements of Dogs and Cats》）
 * - 表 VII-5 预测总能值：粗蛋白 5.7 kcal/g（23.8 kJ/g）、粗脂肪 9.4（39.3）、
 *   无氮浸出物 NFE + 粗纤维 4.1（17.1）。
 *   ⚠ **粗纤维要并进碳水那一项**，不是丢掉：`NFE + CF = 100 − 水分 − 粗蛋白 − 粗脂肪 − 粗灰分`。
 *   不少实现只用 NFE、把粗纤维漏掉 → 总能系统性偏低（偏低量恰好 = 4.1 × CF × 10 kcal/kg）。
 * - 能量消化率：犬 `91.2 − 1.43 × 粗纤维%DM`；猫 `87.9 − 0.88 × 粗纤维%DM`。
 * - 尿能扣减：犬 `− 1.04 × 粗蛋白(g/100g)`；猫 `− 0.77 × 粗蛋白`。
 * - 改良 Atwater（AAFCO 标签算法，犬猫同系数）：蛋白 3.5 / 脂肪 8.5 / 碳水 3.5 kcal/g。
 * - 经典 Atwater（参照）：4 / 9 / 4 kcal/g。
 *
 * ## 适用边界（不隐藏，照算但打标）
 * 消化率方程是**线性回归式**，粗纤维越高越不可靠；CF%DM > 10 之后属于外推，
 * 结果里会带 `digestibilityExtrapolated: true`，界面与文档必须把这句话显示出来。
 *
 * ## 缺数据怎么办
 * NFE 依赖水分。**水分整列缺失时 NFE/总能不可靠 → 不出数**，只返回提示；
 * 水分有值但覆盖率不足（部分原料缺）时照算但标 `reliable:false`。
 * 绝不静默按「0 水分」兜底（项目铁律：缺数据一律提示待确认）。
 */
import { DEFAULT_SPECIES, normSpecies } from './species.js'

/** 燃烧热（总能 GE），kcal/g。NRC 2006 表 VII-5 */
export const GE_FACTORS = { protein: 5.7, fat: 9.4, carb: 4.1 }
/**
 * 燃烧热，kJ/g。同表（23.8 / 39.3 / 17.1）。
 *
 * ⚠ **不要把它改写成 `GE_FACTORS[k] × 4.184`**：NRC 是**按 kJ 独立取整**公布的，
 *   逐项比值是 4.175 / 4.181 / 4.171，并不精确等于 4.184（差 0.1%~0.3%）。
 *   改成精确换算反而偏离原表。要用换算值时必须写明是换算、不是原表值。
 */
export const GE_FACTORS_KJ = { protein: 23.8, fat: 39.3, carb: 17.1 }
/** 改良 Atwater（AAFCO 认可的标签代谢能算法），kcal/g */
export const MODIFIED_ATWATER = { protein: 3.5, fat: 8.5, carb: 3.5 }
/** 经典 Atwater（参照值，非标签算法），kcal/g */
export const ATWATER = { protein: 4, fat: 9, carb: 4 }

/**
 * 尿能扣减系数（每 1 g 粗蛋白扣减的 kcal）。
 *
 * ⚠ **两套报道值并存，本工具并列呈现、不替使用者裁决。**
 *   - `nrc2006`（**主口径**，参与计算）：犬 1.04 / 猫 0.77
 *   - `plos2019`（**备选口径**，仅并列展示）：犬 0.86 / 猫 1.25
 *
 * 两套值**方向相反**（犬的备选值更低、猫的备选值更高）。这不是笔误：
 * 不同研究对「尿氮损失与蛋白摄入的关系」拟合方式不同，项目内暂无压倒性裁决依据。
 * ⇒ 删掉任何一套都会让使用者无法判断口径差异；要改必须先有文献裁决（见 `PITFALLS.md`）。
 */
export const URINE_FACTORS = {
  nrc2006: {
    dog: 1.04,
    cat: 0.77,
    label: 'NRC 2006',
    cite: 'NRC 2006 尿能扣减（犬 −1.04×粗蛋白 g/100g；猫 −0.77×粗蛋白）',
  },
  plos2019: {
    dog: 0.86,
    cat: 1.25,
    label: 'PLOS One 2019',
    cite: 'PLOS One 2019 报道值（犬 0.86 / 猫 1.25；与 NRC 2006 方向相反）',
  },
}

/** 主口径键名 —— **ME(NRC) 计算只用这一套** */
export const URINE_PRIMARY = 'nrc2006'
/** 备选口径键名 —— 仅并列展示，不参与计算 */
export const URINE_ALTERNATIVE = 'plos2019'

/**
 * 尿能口径披露文案（**唯一真源**）。
 *
 * ⚠ 界面 / 导出 / CLI 一律读 `energyProfile(...).urine.disclosure`，
 *   **不要在渲染层重新拼一遍这句话**：同一句披露被写进多个渲染点必然漂移，
 *   改了一处漏一处会让用户看到「两个数字各配各的说明」。
 *
 * @param {'cat'|'dog'} species
 * @returns {string}
 */
export function urineDisclosure(species) {
  const sp = normSpecies(species)
  const p = URINE_FACTORS[URINE_PRIMARY]
  const a = URINE_FACTORS[URINE_ALTERNATIVE]
  return `尿能扣减：本结果按 ${p.label}（犬 ${p.dog} / 猫 ${p.cat} × 粗蛋白 g/100g，本次取 ${p[sp]}）；`
    + `另有 ${a.label} 报道值（犬 ${a.dog} / 猫 ${a.cat}，本次取 ${a[sp]}）——两套值方向相反，本工具并列呈现、不替你裁决。`
}

/** 供界面/文档回显用的出处文本（避免各处各写一份） */
export const ENERGY_CITES = {
  ge: 'NRC 2006 表 VII-5 燃烧热（蛋白 5.7 / 脂肪 9.4 / NFE+粗纤维 4.1 kcal/g）',
  digestibility: 'NRC 2006 能量消化率方程（犬 91.2 − 1.43×粗纤维%DM；猫 87.9 − 0.88×粗纤维%DM）',
  urine: URINE_FACTORS[URINE_PRIMARY].cite,
  /** 备选尿能口径出处（仅并列展示；值引用常量，不复制字符串） */
  urineAlt: URINE_FACTORS[URINE_ALTERNATIVE].cite,
  /** 口径归属说明：让读者知道「哪个数算出来的」 */
  urineBasis: 'ME(NRC) 主口径取 NRC 2006 尿能系数；备选口径仅并列展示，见 urine.disclosure',
  modifiedAtwater: '改良 Atwater（AAFCO 标签算法）：蛋白 3.5 / 脂肪 8.5 / 碳水 3.5 kcal/g',
  atwater: '经典 Atwater（参照）：蛋白 4 / 脂肪 9 / 碳水 4 kcal/g',
}

/** kJ ↔ kcal 换算（文档里给 kJ 时用） */
export const KCAL_TO_KJ = 4.184

/**
 * 粗纤维高于此值（干物质基 %）时，NRC 消化率方程进入外推区。
 * 犬的斜率 1.43 比猫的 0.88 陡，同一个 10%DM 对犬的扣减更狠；
 * 取 10 作为共同标记线，是「常见全价粮粗纤维上限」的经验位置。
 */
export const FIBER_EXTRAPOLATION_DM = 10.0

/**
 * 静息能量需求 RER 的体重指数：**犬猫同为 0.75**。
 *
 * 出处：NRC 2006（Kleiber 1932 异速生长式的兽医化形式）、AAHA 2010 Nutritional
 * Assessment Guidelines、WSAVA Global Nutrition Toolkit、ISFM 住院猫营养指南 ——
 * 四家对 RER 一律给 `70 × BW(kg)^0.75`，不区分犬猫。
 *
 * ⚠ 2026-10-25 纠正：本项目此前把猫写成 `70 × BW^0.67`。那个 0.67 来自
 *   NRC 的**猫维持能量**公式 `MER = 100 × BW^0.67`（瘦猫）／`130 × BW^0.40`（超重猫），
 *   属于 **MER** 的指数，被误植到了 RER 上。后果是猫的 RER 展示值系统性偏低
 *   10.5%~13.4%（4kg 猫 177 vs 198 kcal），而「RER 打底 × 系数」的整个链条
 *   都建立在这个偏低基数上。猫的 NRC 维持口径保留为**独立参照**，
 *   见下面的 `felineNrcMer()` —— 并列展示，不参与本项目 MER 计算。
 *
 * ⚠ 这是**全站唯一的 RER 定义处** —— `nutrition.computeRequirements` 与饲喂指导书的
 *   喂食量速查表都调这里，不要在两处各写一遍（改一处漏一处会让「按体重换算」与
 *   「按需求换算」得出两套数）。
 */
export const RER_EXPONENT = { dog: 0.75, cat: 0.75 }

/**
 * 猫的 NRC 维持能量**参照值**（kcal/日）：瘦猫 `100 × BW^0.67`。
 *
 * 定位：**仅并列展示，不参与 MER 计算**。它与本项目的
 * `RER(70×BW^0.75) × 状态活动系数` 是两套独立证据：
 *   - 本项目口径：RER × 系数，与 AAHA/WSAFA 的「生命阶段 × 活动」表逐格对应；
 *   - NRC 口径：直接给猫的维持能量，指数 0.67 来自猫的实测数据拟合。
 * 两者数值接近（4kg 绝育猫：1.2×198=238 vs 100×2.539=254，差 6%），
 * 但**分解结构不同**，混用会出现「RER 用 0.67、MER 再乘 1.2」这种双重折算。
 *
 * @param {number} kg 体重（kg）
 * @returns {number|null} kcal/日；体重非法时返回 null（不返回 0，避免被当成有效值）
 */
export function felineNrcMer(kg) {
  const w = Number(kg)
  if (!Number.isFinite(w) || w <= 0) return null
  return 100 * Math.pow(w, 0.67)
}

/**
 * **全站统一的物种缺省值** —— 定义在 `species.js`（唯一真源），这里只转出。
 *
 * 保留转出是为了兼容既有 `import { DEFAULT_SPECIES } from './energy.js'`；
 * 新代码请直接从 `species.js` 取。
 */
export { DEFAULT_SPECIES, normSpecies, SPECIES_IDS } from './species.js'

/** 静息能量需求 RER（kcal/日）。体重 ≤ 0 时返回 0，由调用方判缺数据。 */
export function restingEnergy(species, kg) {
  const w = Number(kg)
  if (!Number.isFinite(w) || w <= 0) return 0
  const e = RER_EXPONENT[normSpecies(species)]
  return 70 * Math.pow(w, e)
}

const r0 = (n) => Math.round(n)
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
const isNum = (v) => v !== '' && v != null && Number.isFinite(Number(v))

/**
 * 碳水（能提供总能的那部分）% 原样基础 = NFE + 粗纤维
 *   = 100 − 水分 − 粗蛋白 − 粗脂肪 − 粗灰分
 * 负值按 0 处理（常规成分合计 > 100% 时会出现负的「差值」，那是数据错误，
 * 由调用方的合理性闸门负责报警，这里不制造负能量）。
 */
export function carbFraction(asFed = {}) {
  const v = 100 - num(asFed.moisture) - num(asFed.crude_protein)
    - num(asFed.crude_fat) - num(asFed.crude_ash)
  return Math.max(0, v)
}

/** 无氮浸出物 NFE（不含粗纤维）% 原样基础 —— 标签口径，供能比用 */
export function nfeOf(asFed = {}) {
  const v = 100 - num(asFed.moisture) - num(asFed.crude_protein)
    - num(asFed.crude_fat) - num(asFed.crude_fiber) - num(asFed.crude_ash)
  return Math.max(0, v)
}

/**
 * 改良 Atwater ME（AAFCO / FEDIAF 标签算法），kcal/kg **原样基础**。
 *
 * 系数见 `MODIFIED_ATWATER`：蛋白 3.5 / 脂肪 8.5 / 碳水 3.5 kcal·g⁻¹。
 * ⚠ 碳水取 **NFE（已扣粗纤维）**，不是 GE 口径的「NFE + 粗纤维」——两套口径不可混算，
 *   混了就会得到既不是标签值也不是总能值的第三种数。
 *
 * **本函数是全站唯一实现**。此前 `nutrition.js` 的两条计算路径各自内联了同一行算术
 * （`(3.5×蛋白 + 8.5×脂肪 + 3.5×NFE) × 10`），改系数时要靠人肉记住改两处；现在只剩这里。
 */
export function modifiedAtwaterME(asFed = {}) {
  return (MODIFIED_ATWATER.protein * num(asFed.crude_protein)
    + MODIFIED_ATWATER.fat * num(asFed.crude_fat)
    + MODIFIED_ATWATER.carb * nfeOf(asFed)) * 10
}

/**
 * 经典 Atwater ME（**参照口径，非标签算法**），kcal/kg 原样基础。4 / 9 / 4 kcal·g⁻¹。
 * 判据不得挂在它上面 —— 全站判定口径是 `modifiedAtwaterME`。
 */
export function classicAtwaterME(asFed = {}) {
  return (ATWATER.protein * num(asFed.crude_protein)
    + ATWATER.fat * num(asFed.crude_fat)
    + ATWATER.carb * nfeOf(asFed)) * 10
}

/**
 * 总能 GE。
 *
 * @param {Object} asFed     原样基础常规成分（%）：crude_protein / crude_fat / crude_ash / moisture / crude_fiber
 * @param {number} dmPercent 干物质含量（100 − 水分）；<=0 时不返回干基值
 * @returns {{ok:boolean, kcalPerKg:number|null, kcalPer100g:number|null, kJPerKg:number|null,
 *            kcalPerKgDM:number|null, carbPercent:number, note:string}}
 *          `ok:false` = 水分缺失，本项不出数（值是 null，不是 0）
 */
export function grossEnergy(asFed = {}, dmPercent = 0) {
  const cp = num(asFed.crude_protein)
  const fat = num(asFed.crude_fat)
  const moistureKnown = isNum(asFed.moisture)

  if (!moistureKnown) {
    return {
      ok: false,
      kcalPerKg: null,
      kcalPer100g: null,
      kJPerKg: null,
      kcalPerKgDM: null,
      carbPercent: null,
      note: '缺少水分值：无氮浸出物（NFE）与总能无法可靠换算，本项不出数（请先补水分）',
    }
  }

  const carb = carbFraction(asFed)
  const kcalPer100g = GE_FACTORS.protein * cp + GE_FACTORS.fat * fat + GE_FACTORS.carb * carb
  const kJPer100g = GE_FACTORS_KJ.protein * cp + GE_FACTORS_KJ.fat * fat + GE_FACTORS_KJ.carb * carb
  const dm = Number(dmPercent)
  const canDM = Number.isFinite(dm) && dm > 0.01

  return {
    ok: true,
    kcalPer100g: r2(kcalPer100g),
    kcalPerKg: r0(kcalPer100g * 10),
    kJPerKg: r0(kJPer100g * 10),
    kcalPerKgDM: canDM ? r0((kcalPer100g * 10) / (dm / 100)) : null,
    carbPercent: r2(carb),
    note: '',
  }
}

/**
 * NRC 2006 能量消化率（%）。
 * @param {'cat'|'dog'} species
 * @param {number} cfPercentDM 粗纤维干物质基 %
 * @returns {{percent:number, extrapolated:boolean, cite:string}}
 */
export function energyDigestibility(species, cfPercentDM) {
  const cf = Math.max(0, Number(cfPercentDM) || 0)
  const isCat = species === 'cat'
  return {
    percent: r1(isCat ? 87.9 - 0.88 * cf : 91.2 - 1.43 * cf),
    extrapolated: cf > FIBER_EXTRAPOLATION_DM,
    cite: ENERGY_CITES.digestibility,
  }
}

/**
 * 一整套能量学结果（GE → DE → ME），以及供能比。
 *
 * @param {Object} asFed        原样基础常规成分 %
 * @param {number} dmPercent    干物质含量 %
 * @param {'cat'|'dog'} species 物种（决定消化率方程与尿能系数），非法值按 dog
 * @param {Object} [opts]
 * @param {number} [opts.moistureCoverage] **重量加权**水分覆盖率 0~1（＝有水分数值的原料重量占比）；
 *   <1 时标 `reliable:false`。⚠ 必须是重量口径：加权水分是按重量算的，
 *   用「条数占比」会在「大料缺水、微量料全有值」时给出虚假的乐观值。
 * @param {boolean} [opts.moistureOverridden] 原样成分是否已被「成品水分设定」折算过。
 *   为 true 时覆盖率不足的**失真方向相反**（落在折算系数 k 上而非 NFE 上），提示词要换一套。
 * @returns {Object}
 */
export function energyProfile(asFed = {}, dmPercent = 0, species = DEFAULT_SPECIES, opts = {}) {
  const sp = normSpecies(species)
  const cp = num(asFed.crude_protein)
  const fat = num(asFed.crude_fat)
  const nfe = nfeOf(asFed)
  const cf = num(asFed.crude_fiber)
  const dm = Number(dmPercent)
  const canDM = Number.isFinite(dm) && dm > 0.01

  /* ---- 水分可用性：两个**独立**信号，任一成立就不出 GE/DE ----
   *   ① `asFed.moisture` 不是数字 → 调用方根本没给这一项；
   *   ② `moistureCoverage ≈ 0`  → 整批原料都没有水分数据，`asFed.moisture` 里的 0
   *      是「逐字段初始化」填出来的，**不是测量值**。
   * ⚠ 只查 ① 不够：`computeRecipe` 会把每个字段初始化成 0，水分整列缺失时
   *   也照样是 0（`isNum(0)` 为真）→ GE 会拿「0 水分」真算出一个虚高的数。
   *   实测过这个坑：虚高到 5110 kcal/kg，且看不出错。 */
  const cov = opts.moistureCoverage === undefined ? 1 : Number(opts.moistureCoverage)
  const covNum = Number.isFinite(cov) ? cov : 1
  const noMoisture = !isNum(asFed.moisture) || covNum <= 0

  const ge = grossEnergy(noMoisture ? { ...asFed, moisture: null } : asFed, noMoisture ? 0 : dmPercent)

  /* ---- ME 两口径（改良 / 经典 Atwater），均不依赖物种与水分 ---- */
  const meModPer100g = MODIFIED_ATWATER.protein * cp + MODIFIED_ATWATER.fat * fat
    + MODIFIED_ATWATER.carb * nfe
  const meAtwPer100g = ATWATER.protein * cp + ATWATER.fat * fat + ATWATER.carb * nfe

  /* ---- NRC 三步法：GE → 消化率 → DE → 扣尿能 → ME ----
   * DE/ME(NRC) 依赖「粗纤维%DM」，而 %DM 依赖水分 → 水分不可用时一并不出数
   * （干物质被当成 100%，算出来是系统性偏低的假数）。Atwater 两口径不受影响。 */
  const dmTrustworthy = !noMoisture && canDM
  const cfDM = dmTrustworthy ? (cf / dm) * 100 : null
  const dig = energyDigestibility(sp, cfDM == null ? 0 : cfDM)
  const dePer100g = ge.kcalPer100g == null || !dmTrustworthy
    ? null
    : (ge.kcalPer100g * dig.percent) / 100
  /* ---- 尿能扣减：主口径参与计算，备选口径并行算出仅供并列展示 ----
   * ⚠ 主口径数值与引入常量前**完全一致**（犬 1.04 / 猫 0.77），
   *   只是把魔数收进 `URINE_FACTORS`，好让备选口径不必再复制一份系数。 */
  const urinePrimaryFactor = URINE_FACTORS[URINE_PRIMARY][sp]
  const urineAltFactor = URINE_FACTORS[URINE_ALTERNATIVE][sp]
  const urineDeduct = urinePrimaryFactor * cp
  const meNrcPer100g = dePer100g == null ? null : Math.max(0, dePer100g - urineDeduct)
  const urineDeductAlt = urineAltFactor * cp
  const meNrcAltPer100g = dePer100g == null ? null : Math.max(0, dePer100g - urineDeductAlt)

  /* ---- 供能比（能量来源分布）：按**改良 Atwater ME** 口径 ----
   * 这是标签惯例（碳水用 3.5 而非 4.1），与基于 GE 的占比不是一回事，文档里要写明。 */
  const eProtein = MODIFIED_ATWATER.protein * cp
  const eFat = MODIFIED_ATWATER.fat * fat
  const eCarb = MODIFIED_ATWATER.carb * nfe
  const eSum = eProtein + eFat + eCarb
  const pct = (x) => (eSum > 0.01 ? r1((x / eSum) * 100) : 0)

  /* ---- 可靠性：水分覆盖率不足 → 数值系统性偏低，必须标出来 ----
   * covNum 是**重量加权**覆盖率（见 JSDoc）—— 与「加权水分按重量算」的口径一致。 */
  const covLow = covNum < 1
  /* 成品水分已按设定值折算时，「缺水」影响的不是 NFE 本身，而是折算系数 k
   * （k = 成品DM% ÷ 原料DM%，原料 DM% 被高估 ⇒ k 偏小 ⇒ 湿基数值偏低）。
   * 两种路径的失真方向相反，提示词必须分开写，否则等于给了一个错方向的解释。 */
  const overridden = opts.moistureOverridden === true
  const note = noMoisture
    ? (ge.note || '缺少水分数据：无氮浸出物（NFE）与总能无法可靠换算，GE / DE 不出数')
    : (covLow
      ? (overridden
        ? `重量加权水分覆盖率 ${Math.round(covNum * 100)}%：成品水分已按设定值折算，但折算系数 k 依赖原料干物质，而缺水的原料按 0 水分计 ⇒ 原料 DM% 偏高、k 偏小，湿基各项与能量系统性偏低，仅供参考`
        : `重量加权水分覆盖率 ${Math.round(covNum * 100)}%：缺水的原料按 0 水分计，干物质与 NFE 会偏高，总能/代谢能数值仅供参考`)
      : '')
  return {
    species: sp,
    // —— 总能 ——
    ge: ge.kcalPerKg,
    geDM: ge.kcalPerKgDM,
    geKJ: ge.kJPerKg,
    gePer100g: ge.kcalPer100g,
    carbPercent: ge.carbPercent,
    // —— 消化能 / 代谢能 ——
    digestibility: dig.percent,
    digestibilityExtrapolated: dig.extrapolated,
    cfDM: cfDM == null ? null : r2(cfDM),
    de: dePer100g == null ? null : r0(dePer100g * 10),
    deDM: dePer100g == null || !canDM ? null : r0((dePer100g * 10) / (dm / 100)),
    meModified: r1(meModPer100g * 10),
    meModifiedDM: canDM ? r1((meModPer100g * 10) / (dm / 100)) : null,
    meAtwater: r1(meAtwPer100g * 10),
    meNRC: meNrcPer100g == null ? null : r0(meNrcPer100g * 10),
    meNRCDM: meNrcPer100g == null || !canDM ? null : r0((meNrcPer100g * 10) / (dm / 100)),
    // —— 派生 ——
    meGeRatio: ge.kcalPerKg ? r1(((meModPer100g * 10) / ge.kcalPerKg) * 100) : null,
    meNRCGeRatio: ge.kcalPerKg && meNrcPer100g != null
      ? r1(((meNrcPer100g * 10) / ge.kcalPerKg) * 100)
      : null,
    /* —— 备选尿能口径的 ME（PLOS One 2019），**仅并列展示、不参与任何判定** ——
     * 方向提醒：犬的备选值更低（1.04→0.86）⇒ meNRCAlt > meNRC；
     *           猫的备选值更高（0.77→1.25）⇒ meNRCAlt < meNRC。
     * 守卫用这个方向关系抓「两套值贴反」。 */
    meNRCAlt: meNrcAltPer100g == null ? null : r0(meNrcAltPer100g * 10),
    meNRCAltDM: meNrcAltPer100g == null || !canDM
      ? null
      : r0((meNrcAltPer100g * 10) / (dm / 100)),
    meNRCAltGeRatio: ge.kcalPerKg && meNrcAltPer100g != null
      ? r1(((meNrcAltPer100g * 10) / ge.kcalPerKg) * 100)
      : null,
    nfe: r2(nfe),
    source: [
      { key: 'crude_protein', label: '粗蛋白', percent: pct(eProtein), kcalPerKg: r0(eProtein * 10) },
      { key: 'crude_fat', label: '粗脂肪', percent: pct(eFat), kcalPerKg: r0(eFat * 10) },
      { key: 'carb', label: '碳水（NFE）', percent: pct(eCarb), kcalPerKg: r0(eCarb * 10) },
    ],
    sourceBasis: 'ME 供能比（改良 Atwater 口径；碳水系数取 3.5 kcal/g，与标签惯例一致）',
    // —— 状态 ——
    ok: ge.ok,
    reliable: ge.ok && !covLow,
    noMoisture,
    moistureCoverage: r2(covNum),
    note,
    /* —— 尿能双口径的**机器可读披露块** ——
     * 界面 / 导出 / CLI 只读 `urine.disclosure` 这一句，不要各自重拼文案。 */
    urine: {
      applied: {
        key: URINE_PRIMARY,
        label: URINE_FACTORS[URINE_PRIMARY].label,
        factor: urinePrimaryFactor,
        cite: URINE_FACTORS[URINE_PRIMARY].cite,
      },
      alternative: {
        key: URINE_ALTERNATIVE,
        label: URINE_FACTORS[URINE_ALTERNATIVE].label,
        factor: urineAltFactor,
        cite: URINE_FACTORS[URINE_ALTERNATIVE].cite,
      },
      disclosure: urineDisclosure(sp),
      note: 'ME(NRC) 计算用 NRC 2006 尿能系数；PLOS One 2019 报道值方向相反，仅并列展示、不参与判定。',
    },
    cites: { ...ENERGY_CITES },
  }
}
