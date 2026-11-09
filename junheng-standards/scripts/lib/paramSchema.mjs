/**
 * 参数面**单一真源**（param face single source）。
 *
 * ## 为什么需要它
 * 门面的参数枚举此前**各写一份**：`const SPECIES = ['cat', 'dog']` 在 6 个门面里
 * 逐字重复（`standards` / `energy` / `feeding` / `nutrition` / `pipeline` / `attainment`）。
 * 而 `src/lib/species.js` 本来就导出 `SPECIES_IDS` —— 也就是说「同一事实手工登记在 7 处」。
 * 后果不是「看起来冗余」而是**漂移**：真源增删一个物种时，6 处字面量不会跟着动，
 * 于是出现「校验层拒绝合法物种 / `--help` 列出过时枚举」这类自相矛盾的状态。
 *
 * 本模块把参数面枚举收敛到**一处**，并由校验（`validate`）与 usage/`--help`
 * **同源消费**同一份 `params` —— 改一处、两处同步变。
 *
 * ## 取值口径（★ 不静默兜底）
 *   · `speciesEnum(api)` / `marketEnum(api)` 的**真源是已加载的源码模块**
 *     （`species.js` 的 `SPECIES_IDS`、`standards.js` 的 `MARKET_MODES`）。
 *     取不到即**抛错**，绝不退回硬编码数组 —— 否则「真源缺失」会被伪装成
 *     「枚举本来就只有这两项」，而这正是本项目最想避免的失败模式。
 *   · `STAGES` / `MOISTURE_CLASSES` 无源码常量可依（`standards.js` 只导出
 *     `stageOf()` / `classifyMoisture()` 两个函数，档位 id 散落在判定逻辑内），
 *     故在此**单点声明**，仍保证只有一处。
 *
 * ## 归属
 * 本文件是**域内文件**（不在 `parity.json` 的 `shared` 5 文件内），但会被
 * `scripts/lib/skills-manifest.mjs` 的 `commonLibFiles()` **动态发现**，随技能镜像
 * 同步到 `<skill>/scripts/lib/`。因此它能且只能依赖 node 内置 —— 不得 import 域外模块。
 */

/** 物种枚举 —— 真源 = `src/lib/species.js` 的 `SPECIES_IDS`（全站物种缺省值的唯一真源） */
export function speciesEnum(api) {
  const ids = api && api.SPECIES_IDS
  if (!Array.isArray(ids) || ids.length === 0) {
    throw new Error(
      '参数面真源缺失：api.SPECIES_IDS 不可用。'
      + '门面必须在 api 加载阶段并入 species.js（见 PROBE / importFromVendor）。',
    )
  }
  return ids.slice()
}

/**
 * 剂量口径枚举 —— 真源 = `src/lib/nutrition.js` 的 `DOSE_BASES`。
 * 与 speciesEnum 同一口径：取不到即抛错，不退回硬编码数组。
 */
export function doseBases(api) {
  const v = api && api.DOSE_BASES
  if (!Array.isArray(v) || v.length === 0) {
    throw new Error(
      '参数面真源缺失：api.DOSE_BASES 不可用（应随 nutrition.js 一并加载）。',
    )
  }
  return v.slice()
}

/** 剂量单位枚举 —— 真源 = `src/lib/nutrition.js` 的 `DOSE_UNITS`。 */
export function doseUnits(api) {
  const v = api && api.DOSE_UNITS
  if (!Array.isArray(v) || v.length === 0) {
    throw new Error(
      '参数面真源缺失：api.DOSE_UNITS 不可用（应随 nutrition.js 一并加载）。',
    )
  }
  return v.slice()
}

/** 目标市场枚举 —— 真源 = `src/lib/standards.js` 的 `MARKET_MODES`（只取 id） */
export function marketEnum(api) {
  const modes = api && api.MARKET_MODES
  if (!Array.isArray(modes) || modes.length === 0) {
    throw new Error(
      '参数面真源缺失：api.MARKET_MODES 不可用。'
      + '门面必须在 api 加载阶段并入 standards.js（见 PROBE / importFromVendor）。',
    )
  }
  return modes.map((m) => m.id)
}

/**
 * 生命阶段档。取值与 `standards.js` 的 `stageOf()` 产出一致
 * （`growth` 生长期 / `reproduction` 妊娠·泌乳期 / `adult` 其余）—— 该函数只判不列，故列表在此声明。
 */
export const STAGES = ['growth', 'reproduction', 'adult']

/**
 * 水分形态（GB 表 3 / 表 2 的三档 + `unknown` 未判定）。
 * `standards.js` 的 `classifyMoisture()` 从 `moistureGrades` 取 id，取值与此一致。
 */
export const MOISTURE_CLASSES = ['dry', 'semi-moist', 'wet', 'unknown']
