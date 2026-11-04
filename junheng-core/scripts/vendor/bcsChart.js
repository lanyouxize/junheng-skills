/**
 * BCS 9 分制**逐分判定表**（犬 / 猫分开）—— 体况评估的判据原文。
 *
 * 为什么单独一个模块：`feedingGuide.js` 里的 `BCS_SCALE` 只承载**引擎参数**
 * （归类、能量调整幅度、是否必须就医），每分一行简述；而宠主真正对照着打分需要的是
 * 「侧视看什么 / 俯视看什么 / 手摸什么」这三列逐分标准。两者用途不同，混在一处会
 * 既不好读也不好维护。
 *
 * 依赖说明：本模块**只依赖 `species.js` 这一个零依赖常量模块**（取物种缺省与归一化）。
 * `species.js` 本身不 import 任何东西，所以本模块仍可被界面、导出文档、离线脚本同时引用，
 * 不会引入任何依赖环。
 *
 * 出处：
 *   · 判定标准与体脂率区间：Association for Pet Obesity Prevention (APOP)
 *     犬 / 猫 9 分制 BCS 图（原文为英文，本模块译为中文）。
 *   · 该图自身改编自 Laflamme DP. Canine Pract. 1997;22(1):10–15（犬）、
 *     Feline Pract. 1997;25:13–18（猫）；体脂率区间据 Cline MG, et al.
 *     2021 AAHA Nutrition and Weight Management Guidelines for Dogs and Cats.
 *     J Am Vet Med Assoc / JAAHA 2021;57:153–178。
 *   · 其它被引用的原始研究：Mawby DI, et al. JAAHA 2004;40(2):109–114（犬）；
 *     Bjornvad CR, et al. Am J Vet Res 2011;72:433–437（猫）；
 *     WSAVA Nutrition Committee. Body Condition Score: Cats. 2025。
 *
 * ⚠ 版权说明：APOP 的图**受版权保护**，本模块只**翻译其判据文字**，不内嵌其图片；
 *   界面与导出文档里画的示意图是本工具自绘的矢量图（见 `bcsFigure.js`），不是原图。
 *
 * ⚠ 本文件会被**渲染成文案**（界面与导出文档直接取值）：
 *   字符串里不要写 Markdown 星号、反引号或英文原句，否则会原样显示给客户。
 */
import { normSpecies } from './species.js'

/** 表格三列（界面、导出文档、文本版共用一份列名，避免三处各写一套） */
export const BCS_CHART_COLUMNS = [
  { key: 'lateral', label: '侧视（看腹部上提）' },
  { key: 'dorsal', label: '俯视（看腰线内收）' },
  { key: 'palpation', label: '触摸（摸肋骨与脂肪层）' },
]

/**
 * 临床肥胖筛查区。⚠ 这是**筛查阈值，不是诊断** ——
 * 官方原文明写：BCS 7~9 属于以肥胖为目标的临床筛查区，但 BCS 本身不能诊断临床肥胖
 * （确诊需要结合肌肉状况、体重趋势、饮食史、活动能力与体检）。
 * 以前本工具只把 8、9 分标成「需兽医评估」，漏掉了 7 分已在筛查区内。
 */
export const BCS_OBESITY_SCREENING_ZONE = { from: 7, to: 9, label: '临床肥胖筛查区' }

/** 体况评分的可靠性边界与误差说明（导出文档与界面都要出现，不能只留在注释里） */
export const BCS_CHART_CAVEATS = [
  '体脂率为近似估算值，会随性别、绝育与否、年龄、品种、活动量与测量方法变化，个体误差约正负 5 个百分点',
  '体脂超过约 45% 时，BCS 的区分度明显下降（肋骨完全摸不到就没有可评的依据了），此时应改用体脂指数（BFI）、体尺测量或 DXA 等方法',
  'BCS 7~9 属于临床肥胖筛查区：它是一个筛查阈值，不是诊断。BCS 本身不能诊断临床肥胖，确诊需要由兽医结合肌肉状况、体重趋势、饮食史、活动能力与体检结果',
  '任何不在理想区的评分（犬 4~5 分、猫 5 分）都建议请兽医团队评估一次；请勿只凭本表大幅增减喂食量或运动量',
]

/**
 * 物种差异。⚠ 三条都是**会被误判的点**，不是可选提示：
 *   · 犬的理想是 4~5 分，猫只有 5 分 —— 把猫按 4 分养等于长期偏瘦；
 *   · 猫腹部下垂可能是**原始袋**（正常解剖结构），不能用腹部外形单独推分；
 *   · 细长体型的犬（灵缇、细犬）天然腰线极细，宽胸短头品种（法斗、巴哥）骨架宽，
 *     两者轮廓都不可靠，必须以触摸肋骨为准。
 */
export const BCS_SPECIES_NOTE = {
  dog: {
    idealScores: [4, 5],
    idealText: '犬的理想体况为 4~5 分',
    notes: [
      '犬的理想体况是 4~5 分：4 分常见于运动犬，5 分是家养伴侣犬的最佳状态',
      '细长体型犬（灵缇、细犬等）天生腰线极细，不能只看轮廓；宽胸短头犬（法斗、巴哥等）骨架宽、容易藏脂肪，都应以触摸肋骨为准',
      '可能出现混合表现：腰椎、骨盆、肩胛摸着硌手，但肋骨、胸廓与腹部仍有脂肪堆积。此时脂肪与肌肉要分开评',
    ],
  },
  cat: {
    idealScores: [5],
    idealText: '猫的理想体况为 5 分',
    notes: [
      '猫的理想体况是 5 分（不是 4 分）：按 4 分长期饲喂会偏瘦',
      '不能只靠腹部外形判断：猫下腹常有一层「原始袋」（正常解剖结构、与肥胖无关的皮肤脂肪褶），请以触摸肋骨为准',
      '长毛猫腰线被毛量掩盖，必须触摸肋骨与腰椎',
      '减重速度必须比犬更慢：猫减重过快会诱发肝脂沉积症（俗称猫脂肪肝），可危及生命',
    ],
  },
}

/** 体脂率区间的显示文案（1~9 分，源自 APOP 图 / 2021 AAHA） */
const FAT_TEXT = ['不足 5%', '5%~9%', '10%~14%', '15%~19%', '20%~24%', '25%~29%', '30%~34%', '35%~39%', '40%~45% 以上']

/** 数值区间（给测试与将来画图用）：fatMax 为 null 表示上不封顶 */
const FAT_RANGE = [
  [0, 5], [5, 9], [10, 14], [15, 19], [20, 24], [25, 29], [30, 34], [35, 39], [40, null],
]

/**
 * 犬的逐分判定。字段：
 *   score 分数 / label 中文名 / group 四档归类 / fatText 体脂率
 *   lateral 侧视 / dorsal 俯视 / palpation 触摸
 */
const DOG_ROWS = [
  {
    label: '极度消瘦', group: 'thin',
    lateral: '肋骨、腰椎、骨盆骨与骨性突起远距离即可看出；腹部严重上收',
    dorsal: '躯干极窄，脊椎与骨盆骨清晰外露，看不出腰线',
    palpation: '完全摸不到皮下脂肪，骨缘扎手；肌肉量明显流失',
  },
  {
    label: '明显偏瘦', group: 'thin',
    lateral: '肋骨清晰可见；腹部明显上收',
    dorsal: '脊椎可辨成一条，腰线极深，躯干呈沙漏形',
    palpation: '肋骨、腰椎与骨盆骨一触即到，几乎无脂肪覆盖；肌肉量轻度流失',
  },
  {
    label: '偏瘦', group: 'thin',
    lateral: '肋骨轻易可辨，短毛犬可能隐约可见；腹部明显上提',
    dorsal: '腰椎可见，骨盆骨开始突出，腰线非常明显',
    palpation: '肋骨容易摸到，脂肪覆盖极少',
  },
  /* ⚠ 名称只写**形态**，「是不是理想」一律交给 group / groupLabel 表达。
     以前这里写「略瘦（理想）」，等于把物种无关的判断烙进名称：
     犬 4 分是理想、猫 4 分是偏瘦，同一个名却只能有一种括注，必然误导一半用户。 */
  {
    label: '略瘦', group: 'ideal',
    lateral: '肋骨后方到后腿之间有清晰的腹部上提',
    dorsal: '肋骨后方可见清晰的腰线',
    palpation: '肋骨上只有薄薄一层脂肪，轻触即可摸到',
  },
  {
    label: '理想', group: 'ideal',
    lateral: '腹部有上提，但幅度自然、不夸张',
    dorsal: '肋骨后方可见腰线',
    palpation: '肋骨可摸到、无明显多余脂肪覆盖；腰椎与尾根无硬块',
  },
  {
    label: '略胖', group: 'over',
    lateral: '腹部上提存在但已减弱',
    dorsal: '腰线可以分辨，但已不明显',
    palpation: '肋骨上脂肪略多，稍加压力即可摸到',
  },
  {
    label: '偏胖', group: 'over',
    lateral: '腹部上提只剩很少，甚至看不出',
    dorsal: '腰线难以看清',
    palpation: '需用力按压才能摸到肋骨；腰背部与尾根上已出现脂肪堆积',
  },
  {
    label: '肥胖', group: 'obese',
    lateral: '腹部上提消失，腹部可能显得圆润膨出',
    dorsal: '无腰线',
    palpation: '厚脂肪覆盖，摸不到或很难摸到肋骨；腰背部与尾根脂肪明显堆积',
  },
  {
    label: '严重肥胖', group: 'obese',
    lateral: '腹部圆润并明显下垂膨出',
    dorsal: '无腰线',
    palpation: '大量脂肪覆盖，完全摸不到肋骨；胸廓、脊椎、腰背、尾根、颈部与四肢均有脂肪堆积',
  },
]

const CAT_ROWS = [
  {
    label: '极度消瘦', group: 'thin',
    lateral: '肋骨、脊椎与骨盆骨远距离即可看出；腹部明显上收',
    dorsal: '躯干极窄，脊椎与骨盆骨清晰外露，看不出腰线',
    palpation: '完全摸不到皮下脂肪；肌肉量明显流失',
  },
  {
    label: '明显偏瘦', group: 'thin',
    lateral: '肋骨与整条脊椎可辨可见；腹部明显上收',
    dorsal: '整条脊椎凸起，骨盆骨突出，腰线极细',
    palpation: '几乎无脂肪覆盖；肌肉量轻度流失',
  },
  {
    label: '偏瘦', group: 'thin',
    lateral: '腹部明显上提，下腹脂肪垫很少',
    dorsal: '腰椎与骨盆骨可辨，腰线明显',
    palpation: '肋骨可摸到，脂肪覆盖极少',
  },
  /* ⚠ 猫的 4 分**不是**理想（猫只有 5 分是理想）。以前这一行的 label 与 group
     是从犬表连同样本一起抄过来的「略瘦（理想）/ideal」，导致：
     界面显示「略瘦（理想）」、建议「按维持量饲喂」、能量系数 0（=维持量）——
     正好造出 SKILL 自己警告的「把猫按 4 分养会长期偏瘦」。
     犬 4 分仍是理想，所以两物种在这一行**本来就不一样**，不能逐格对齐。 */
  {
    label: '略瘦', group: 'thin',
    lateral: '下腹脂肪垫极小，腹部上提清晰',
    dorsal: '肋骨后方腰线清晰可见',
    palpation: '肋骨上只有薄层脂肪，轻触即可摸到',
  },
  {
    label: '理想', group: 'ideal',
    lateral: '下腹有轻薄、可轻微晃动的脂肪垫，但不垂坠',
    dorsal: '肋骨后方可见腰线',
    palpation: '肋骨上有一层薄脂肪，可轻松摸到',
  },
  {
    label: '略胖', group: 'over',
    lateral: '腹部不再上提，下腹脂肪垫开始增厚',
    dorsal: '腰线不清晰',
    palpation: '肋骨上脂肪略多，稍加压力即可摸到',
  },
  {
    label: '偏胖', group: 'over',
    lateral: '下腹脂肪垫明显（中度）',
    dorsal: '腰线难以看清',
    palpation: '需用力按压才能摸到肋骨',
  },
  {
    label: '肥胖', group: 'obese',
    lateral: '下腹脂肪垫明显下垂，腹部膨出',
    dorsal: '无腰线',
    palpation: '厚脂肪覆盖，摸不到肋骨；腰椎处有脂肪沉积',
  },
  {
    label: '严重肥胖', group: 'obese',
    lateral: '下腹脂肪垫巨大、明显下垂',
    dorsal: '无腰线',
    palpation: '大量脂肪覆盖，完全摸不到肋骨；腰椎、面部与四肢均有脂肪沉积',
  },
]

/** 把行数组补齐 score / fatText / 体脂数值区间，避免手写 9 遍出错 */
function buildRows(rows) {
  return rows.map((r, i) => ({
    score: i + 1,
    label: r.label,
    group: r.group,
    fatText: FAT_TEXT[i],
    fatMin: FAT_RANGE[i][0],
    fatMax: FAT_RANGE[i][1],
    lateral: r.lateral,
    dorsal: r.dorsal,
    palpation: r.palpation,
  }))
}

/** 逐分判定表：{ dog: [9 行], cat: [9 行] } */
export const BCS_CHART = {
  dog: buildRows(DOG_ROWS),
  cat: buildRows(CAT_ROWS),
}

/**
 * 归一化物种取值。
 *
 * ⚠ 缺省一律回落 **DEFAULT_SPECIES（猫）**，与全站统一口径一致。
 *   历史上这里缺省是犬，导致「不传 species 时 BCS 按犬判、营养需求按猫算」——
 *   同一只宠物在两处被当成不同物种。改为引用 `energy.js` 的同一个常量，
 *   使「默认物种」全站只有一处定义。
 */
export function normBcsSpecies(species) {
  return normSpecies(species)
}

/** 取某物种的整张表（9 行，已按分数升序） */
export function bcsChartFor(species) {
  return BCS_CHART[normBcsSpecies(species)]
}

/** 取某物种某一分的判定行；分数非法返回 null（不替用户假定 5 分） */
export function bcsChartRow(species, score) {
  const n = Math.round(Number(score))
  if (!Number.isFinite(n) || n < 1 || n > 9) return null
  return bcsChartFor(species)[n - 1]
}

/** 是否落在临床肥胖筛查区（BCS 7~9） */
export function inObesityScreeningZone(score) {
  const n = Math.round(Number(score))
  if (!Number.isFinite(n)) return false
  return n >= BCS_OBESITY_SCREENING_ZONE.from && n <= BCS_OBESITY_SCREENING_ZONE.to
}

/** 该物种的理想分数区间（犬 4~5、猫仅 5） */
export function idealScoresFor(species) {
  return BCS_SPECIES_NOTE[normBcsSpecies(species)].idealScores
}

/** 某个分数对该物种是否属于理想区 */
export function isIdealFor(species, score) {
  const n = Math.round(Number(score))
  return Number.isFinite(n) && idealScoresFor(species).includes(n)
}

/** 一句话的出处说明（界面页脚、导出文档脚注共用） */
export function bcsChartSourceText() {
  return '判定标准译自 Association for Pet Obesity Prevention (APOP) 犬猫 9 分制 BCS 图，'
    + '该图改编自 Laflamme DP (Canine Pract. 1997; Feline Pract. 1997)，'
    + '体脂率区间据 2021 AAHA Nutrition and Weight Management Guidelines (JAAHA 2021;57:153–178)'
}
