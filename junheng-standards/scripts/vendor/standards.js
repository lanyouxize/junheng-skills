/**
 * 营养标准体系注册表 + 目标市场模式（任务 4）。
 *
 * ## 数据来源与可信度分级（逐项可追溯，这是本模块的第一原则）
 *
 *   · `CN-GB`  —— 中国国家标准，**条款已核**。来源：
 *       GB/T 31216-2014《全价宠物食品 犬粮》表 2（主要理化指标）、表 3（水分）；
 *       GB/T 31217-2014《全价宠物食品 猫粮》表 1（主要理化指标）、表 2（水分）。
 *       取自国家标准全文公开系统（openstd.samr.gov.cn）与标准原文。
 *   · `AAFCO`  —— 美国饲料管理协会 Nutrient Profiles。数值**沿用系统原有代码**，
 *       尚未与官方出版物逐项核对 → 全部条目带 `verified: false`，界面显示「待核对现行版本」。
 *   · `FEDIAF` —— 欧洲宠物食品工业协会 Nutritional Guidelines 2025。本轮**已核实并参与判定**：
 *       数值取自官方 PDF（europeanpetfood.org，2025-09 发布）Table III-3/III-4
 *       per 100 g DM，已逐项抽取并核对（犬 41/38、猫 40/38 条）。参与 `cn-intl` / `intl` 模式，
 *       与 CN-GB、AAFCO 合并时取最严值。注：FEDIAF 官方亦提供 per-MJ 基准主表，本模块采用其等价
 *       的 per-100g-DM 表（数值等同 %DM），故无需另建能量基准口径。
 *
 * ## 三种目标市场模式（用户可选，持久化在设置里）
 *
 *   cn       仅中国 GB 标签            → 只按 CN-GB 判定
 *   cn-intl  中国 GB + 国际（AAFCO）   → 同时满足，取最严
 *   intl     仅国际（AAFCO）           → 只按 AAFCO 判定
 *
 * ## 合并规则（多体系同时满足时）
 *
 *   下限取各体系的**最大值**（都要满足 ⇒ 取最严的那个下限）
 *   上限取各体系的**最小值**
 *   区间取**交集**（左端取 max、右端取 min），交集为空时显式报冲突
 *   项目取**并集**（某体系要求的项目，即使另一体系没要求也要判）
 *   每一项都保留 `sources`（各体系原值文案）与 `cites`（条款出处），便于追溯
 *
 * ## 不参与自动判定的项目
 *
 *   原料库没有氨基酸字段 → 赖氨酸（犬）、牛磺酸（猫）标为 `dataField: null`，
 *   判定为「系统无此原料数据，暂无法判定」，**不冒充「未达标」**。
 */

/**
 * 营养素元信息。
 *   dataField —— 取自原料库的哪个字段；null 表示系统没有这项数据
 *   unit      —— 展示单位（统一按干物质基础，与 GB 表 2/1 一致）
 *   kind      —— min 下限 / max 上限 / range 区间 / info 仅展示
 */
export const NUTRIENT_META = {
  crude_protein: { label: '粗蛋白质', unit: '%DM', dataField: 'crude_protein', kind: 'min' },
  crude_fat: { label: '粗脂肪', unit: '%DM', dataField: 'crude_fat', kind: 'min' },
  crude_fiber: { label: '粗纤维', unit: '%DM', dataField: 'crude_fiber', kind: 'max' },
  crude_ash: { label: '粗灰分', unit: '%DM', dataField: 'crude_ash', kind: 'max' },
  calcium: { label: '钙', unit: '%DM', dataField: 'calcium', kind: 'min' },
  phosphorus: { label: '总磷', unit: '%DM', dataField: 'phosphorus', kind: 'min' },
  chloride: { label: '水溶性氯化物', unit: '%DM', dataField: 'chloride', kind: 'min' },
  lysine: { label: '赖氨酸', unit: '%DM', dataField: null, kind: 'min' },
  taurine: { label: '牛磺酸', unit: '%DM', dataField: null, kind: 'min' },
  caP: { label: '钙磷比（干物质基）', unit: '', dataField: null, kind: 'range', computed: 'caP' },
  me: { label: '代谢能（干物质基）', unit: 'kcal/kg DM', dataField: null, kind: 'min', computed: 'me' },
  // —— 以下 6 项由任务 A1 从 pawcook AAFCO 数据吸收（批 A），dataField:null 表示
  //    原料库当前无氨基酸/脂肪酸分析字段，仅登记标准、系统暂无法自动判定（与 lysine/taurine 同机制）。
  //    出处：SirAllap/pawcook aafco.json / aafco-cat.json 转译；AAFCO 集整体 verified:false，待官核。
  linoleic_acid: { label: '亚油酸', unit: '%DM', dataField: null, kind: 'min' },
  ala: { label: 'α-亚麻酸', unit: '%DM', dataField: null, kind: 'min' },
  epa_dha: { label: 'EPA+DHA', unit: '%DM', dataField: null, kind: 'min' },
  arachidonic_acid: { label: '花生四烯酸', unit: '%DM', dataField: null, kind: 'min' },
  arginine: { label: '精氨酸', unit: '%DM', dataField: null, kind: 'min' },
  methionine: { label: '蛋氨酸', unit: '%DM', dataField: null, kind: 'min' },
  histidine: { label: '组氨酸', unit: '%DM', dataField: null, kind: 'min' },
  isoleucine: { label: '异亮氨酸', unit: '%DM', dataField: null, kind: 'min' },
  leucine: { label: '亮氨酸', unit: '%DM', dataField: null, kind: 'min' },
  methionine_cystine: { label: '蛋氨酸+胱氨酸', unit: '%DM', dataField: null, kind: 'min' },
  phenylalanine: { label: '苯丙氨酸', unit: '%DM', dataField: null, kind: 'min' },
  phenylalanine_tyrosine: { label: '苯丙氨酸+酪氨酸', unit: '%DM', dataField: null, kind: 'min' },
  threonine: { label: '苏氨酸', unit: '%DM', dataField: null, kind: 'min' },
  tryptophan: { label: '色氨酸', unit: '%DM', dataField: null, kind: 'min' },
  valine: { label: '缬氨酸', unit: '%DM', dataField: null, kind: 'min' },
  potassium: { label: '钾', unit: '%DM', dataField: null, kind: 'min' },
  sodium: { label: '钠', unit: '%DM', dataField: null, kind: 'min' },
  magnesium: { label: '镁', unit: '%DM', dataField: null, kind: 'min' },
  copper: { label: '铜', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  iodine: { label: '碘', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  iron: { label: '铁', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  manganese: { label: '锰', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  selenium_wet: { label: '硒(湿粮)', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  selenium_dry: { label: '硒(干粮)', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  zinc: { label: '锌', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_a: { label: '维生素A', unit: 'IU/100g DM', dataField: null, kind: 'min' },
  vitamin_d: { label: '维生素D', unit: 'IU/100g DM', dataField: null, kind: 'min' },
  vitamin_e: { label: '维生素E', unit: 'IU/100g DM', dataField: null, kind: 'min' },
  vitamin_b1: { label: '维生素B1(硫胺素)', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_b2: { label: '维生素B2(核黄素)', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_b5: { label: '维生素B5(泛酸)', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_b6: { label: '维生素B6(吡哆醇)', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_b12: { label: '维生素B12(氰钴胺)', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  vitamin_b3: { label: '维生素B3(烟酸)', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_b9: { label: '维生素B9(叶酸)', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  vitamin_b7: { label: '维生素B7(生物素)', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  choline: { label: '胆碱', unit: 'mg/100g DM', dataField: null, kind: 'min' },
  vitamin_k: { label: '维生素K', unit: 'µg/100g DM', dataField: null, kind: 'min' },
  taurine_canned: { label: '牛磺酸(罐装)', unit: '%DM', dataField: null, kind: 'min' },
  taurine_dry: { label: '牛磺酸(干粮)', unit: '%DM', dataField: null, kind: 'min' },
}

/**
 * 标准体系注册表。
 * 每个体系按 物种(species) → 生命阶段档(stage: growth|adult) → { 项目: 条款 }。
 * 条款形式：
 *   { min }        下限
 *   { max }        上限
 *   { min, max }   区间
 *   { min, wetMin }  湿粮适用另一下限（牛磺酸）
 */
export const STANDARD_SETS = {
  'CN-GB': {
    id: 'CN-GB',
    label: '中国 GB',
    fullLabel: '中国国家标准（GB/T 31216-2014 犬粮 · GB/T 31217-2014 猫粮）',
    verified: true,
    // 水分形态分级（两个标准完全一致，放在体系级）
    moistureGrades: [
      { id: 'dry', label: '干性', test: (x) => x < 14.0, cite: 'GB/T 31216 表3 / GB/T 31217 表2' },
      { id: 'semi-moist', label: '半湿性', test: (x) => x >= 14.0 && x < 60.0, cite: '同上' },
      { id: 'wet', label: '湿性', test: (x) => x >= 60.0, cite: '同上' },
    ],
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 22.0, cite: 'GB/T 31216-2014 表2 · 幼犬粮/妊娠期/哺乳期犬粮' },
          crude_fat: { min: 8.0, cite: 'GB/T 31216-2014 表2' },
          crude_ash: { max: 10.0, cite: 'GB/T 31216-2014 表2' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31216-2014 表2' },
          calcium: { min: 1.0, cite: 'GB/T 31216-2014 表2' },
          phosphorus: { min: 0.8, cite: 'GB/T 31216-2014 表2' },
          caP: { min: 1.0, max: 1.8, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.45, cite: 'GB/T 31216-2014 表2' },
          lysine: { min: 0.77, cite: 'GB/T 31216-2014 表2' },
        },
        adult: {
          crude_protein: { min: 18.0, cite: 'GB/T 31216-2014 表2 · 成年犬粮' },
          crude_fat: { min: 5.0, cite: 'GB/T 31216-2014 表2' },
          crude_ash: { max: 10.0, cite: 'GB/T 31216-2014 表2' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31216-2014 表2' },
          calcium: { min: 0.6, cite: 'GB/T 31216-2014 表2' },
          phosphorus: { min: 0.5, cite: 'GB/T 31216-2014 表2' },
          caP: { min: 1.0, max: 2.0, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.09, cite: 'GB/T 31216-2014 表2' },
          lysine: { min: 0.63, cite: 'GB/T 31216-2014 表2' },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 28.0, cite: 'GB/T 31217-2014 表1 · 幼猫粮/妊娠期/哺乳期猫粮' },
          crude_fat: { min: 9.0, cite: 'GB/T 31217-2014 表1' },
          crude_ash: { max: 10.0, cite: 'GB/T 31217-2014 表1' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31217-2014 表1' },
          calcium: { min: 1.0, cite: 'GB/T 31217-2014 表1' },
          phosphorus: { min: 0.8, cite: 'GB/T 31217-2014 表1' },
          caP: { min: 1.0, max: 1.8, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.3, cite: 'GB/T 31217-2014 表1' },
          taurine: { min: 0.1, wetMin: 0.2, cite: 'GB/T 31217-2014 表1（湿粮 ≥0.2）' },
        },
        adult: {
          crude_protein: { min: 25.0, cite: 'GB/T 31217-2014 表1 · 成年猫粮' },
          crude_fat: { min: 9.0, cite: 'GB/T 31217-2014 表1' },
          crude_ash: { max: 10.0, cite: 'GB/T 31217-2014 表1' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31217-2014 表1' },
          calcium: { min: 0.6, cite: 'GB/T 31217-2014 表1' },
          phosphorus: { min: 0.5, cite: 'GB/T 31217-2014 表1' },
          caP: { min: 1.0, max: 2.0, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.3, cite: 'GB/T 31217-2014 表1' },
          taurine: { min: 0.1, wetMin: 0.2, cite: 'GB/T 31217-2014 表1（湿粮 ≥0.2）' },
        },
      },
    },
  },

  AAFCO: {
    id: 'AAFCO',
    label: 'AAFCO',
    fullLabel: 'AAFCO Dog and Cat Food Nutrient Profiles',
    verified: false,
    verifyNote: '数值沿用系统原有实现，尚未与 AAFCO 官方出版物逐项核对现行版本年份，结论仅供参考。',
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 22.5 },
          crude_fat: { min: 8.5 },
          linoleic_acid: { min: 1.3, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          ala: { min: 0.08, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          epa_dha: { min: 0.05, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          calcium: { min: 1.2 },
          phosphorus: { min: 1.0 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 1.8 },
          me: { min: 3500 },
        },
        adult: {
          crude_protein: { min: 18.0 },
          crude_fat: { min: 5.5 },
          linoleic_acid: { min: 1.1, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          calcium: { min: 0.5 },
          phosphorus: { min: 0.4 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 2.0 },
          me: { min: 3250 },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 30.0 },
          crude_fat: { min: 9.0 },
          linoleic_acid: { min: 0.55, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arachidonic_acid: { min: 0.02, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          epa_dha: { min: 0.012, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arginine: { min: 1.24, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          methionine: { min: 0.20, max: 1.50, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          lysine: { min: 1.20, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          taurine: { min: 0.10, wetMin: 0.20, cite: 'AAFCO 2014 猫（干粮≥0.10%/湿粮≥0.20% DM；参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          calcium: { min: 1.2 },
          phosphorus: { min: 1.0 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 1.8 },
          me: { min: 3500 },
        },
        adult: {
          crude_protein: { min: 26.0 },
          crude_fat: { min: 9.0 },
          linoleic_acid: { min: 0.55, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arachidonic_acid: { min: 0.02, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arginine: { min: 1.04, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          methionine: { min: 0.20, max: 1.50, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          lysine: { min: 0.34, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          taurine: { min: 0.10, wetMin: 0.20, cite: 'AAFCO 2014 猫（干粮≥0.10%/湿粮≥0.20% DM；参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          calcium: { min: 0.6 },
          phosphorus: { min: 0.5 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 2.0 },
          me: { min: 4000 },
        },
      },
    },
  },

  FEDIAF: {
    id: 'FEDIAF',
    label: 'FEDIAF',
    fullLabel: 'FEDIAF Nutritional Guidelines for Complete and Complementary Pet Food for Cats and Dogs (2025)',
    verified: true,
    verifyNote: '数值取自 FEDIAF 2025 官方 PDF（europeanpetfood.org，2025-09 发布）Table III-3/III-4 per 100 g DM，已逐项抽取并核对。犬生长档取各亚型(早/繁殖/晚)最小值的最大值；猫取生长/繁殖档最大值。',
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 25.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arginine: { min: 0.82, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          histidine: { min: 0.39, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          isoleucine: { min: 0.65, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          leucine: { min: 1.29, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          lysine: { min: 0.88, max: 2.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine: { min: 0.4, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine_cystine: { min: 0.76, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine: { min: 0.65, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine_tyrosine: { min: 1.3, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          threonine: { min: 0.81, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          valine: { min: 0.68, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          crude_fat: { min: 8.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          linoleic_acid: { min: 1.32, max: 6.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arachidonic_acid: { min: 0.03, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          ala: { min: 0.08, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          epa_dha: { min: 0.05, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          calcium: { min: 1.0, max: 1.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phosphorus: { min: 0.9, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          potassium: { min: 0.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          sodium: { min: 0.22, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          chloride: { min: 0.33, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          magnesium: { min: 0.07, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          copper: { min: 1.1, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iodine: { min: 0.15, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iron: { min: 8.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          manganese: { min: 0.58, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          selenium_wet: { min: 40.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          selenium_dry: { min: 40.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          zinc: { min: 10.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_a: { min: 606.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_d: { min: 55.2, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_e: { min: 5.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b1: { min: 0.21, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b2: { min: 0.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b5: { min: 1.42, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b6: { min: 0.15, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b12: { min: 3.35, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b3: { min: 1.64, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b9: { min: 25.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          choline: { min: 170.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
        },
        adult: {
          crude_protein: { min: 21.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arginine: { min: 0.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          histidine: { min: 0.27, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          isoleucine: { min: 0.53, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          leucine: { min: 0.95, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          lysine: { min: 0.46, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine: { min: 0.46, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine_cystine: { min: 0.88, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine: { min: 0.63, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine_tyrosine: { min: 1.03, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          threonine: { min: 0.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          valine: { min: 0.68, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          crude_fat: { min: 5.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          linoleic_acid: { min: 1.53, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          calcium: { min: 0.58, max: 2.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phosphorus: { min: 0.46, max: 1.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          potassium: { min: 0.58, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          sodium: { min: 0.12, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          chloride: { min: 0.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          magnesium: { min: 0.08, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          copper: { min: 0.83, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iodine: { min: 0.12, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iron: { min: 4.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          manganese: { min: 0.67, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          selenium_wet: { min: 27.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          selenium_dry: { min: 22.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          zinc: { min: 8.34, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_a: { min: 702.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_d: { min: 63.9, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_e: { min: 4.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b1: { min: 0.25, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b2: { min: 0.69, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b5: { min: 1.64, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b6: { min: 0.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b12: { min: 3.87, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b3: { min: 1.89, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b9: { min: 29.9, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          choline: { min: 189.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 25.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arginine: { min: 1.0, max: 3.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          histidine: { min: 0.33, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          isoleucine: { min: 0.54, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          leucine: { min: 1.28, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          lysine: { min: 0.85, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine: { min: 0.44, max: 1.3, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine_cystine: { min: 0.88, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine: { min: 0.5, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine_tyrosine: { min: 1.91, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          threonine: { min: 0.65, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          tryptophan: { min: 0.16, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          valine: { min: 0.64, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          crude_fat: { min: 9.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          linoleic_acid: { min: 0.55, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arachidonic_acid: { min: 0.02, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          ala: { min: 0.02, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          epa_dha: { min: 0.01, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          calcium: { min: 1.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phosphorus: { min: 0.84, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          potassium: { min: 0.6, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          sodium: { min: 0.16, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          chloride: { min: 0.24, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          copper: { min: 1.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iodine: { min: 0.18, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iron: { min: 8.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          manganese: { min: 1.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_a: { min: 900.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_d: { min: 28.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_e: { min: 3.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b1: { min: 0.55, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b2: { min: 0.32, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b5: { min: 0.58, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b6: { min: 0.25, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b12: { min: 1.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b3: { min: 3.2, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b9: { min: 75.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b7: { min: 7.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          choline: { min: 240.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          taurine: { min: 0.10, wetMin: 0.25, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },  // cat growth: 干粮≥0.10 / 罐装≥0.25 %DM
        },
        adult: {
          crude_protein: { min: 33.3, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arginine: { min: 1.3, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          histidine: { min: 0.35, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          isoleucine: { min: 0.57, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          leucine: { min: 1.36, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          lysine: { min: 0.45, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine: { min: 0.23, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          methionine_cystine: { min: 0.45, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine: { min: 0.53, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phenylalanine_tyrosine: { min: 2.04, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          threonine: { min: 0.69, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          tryptophan: { min: 0.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          valine: { min: 0.68, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          crude_fat: { min: 9.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          linoleic_acid: { min: 0.67, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          arachidonic_acid: { min: 0.008, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          calcium: { min: 0.53, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          phosphorus: { min: 0.35, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          potassium: { min: 0.8, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          sodium: { min: 0.1, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          chloride: { min: 0.15, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          copper: { min: 0.67, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iodine: { min: 0.17, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          iron: { min: 10.7, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          manganese: { min: 0.67, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_a: { min: 444.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_d: { min: 33.3, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_e: { min: 5.07, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b1: { min: 0.59, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b2: { min: 0.42, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b5: { min: 0.77, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b6: { min: 0.33, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b12: { min: 2.35, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b3: { min: 4.21, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b9: { min: 101.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          vitamin_b7: { min: 8.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          choline: { min: 320.0, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },
          taurine: { min: 0.13, wetMin: 0.27, cite: 'FEDIAF 2025 Table III-3/III-4 (per 100 g DM), 官方 PDF 2025-09, verified:true' },  // cat adult: 干粮≥0.13 / 罐装≥0.27 %DM
        },
      },
    },
  },
  NRC: {
    id: 'NRC',
    label: 'NRC 2006',
    fullLabel: "NRC 2006\u300a\u72ac\u732b\u8425\u517b\u9700\u8981\u300b(Nutrient Requirements of Dogs and Cats, \u4e2d\u6587\u7248)",
    verified: true,
    verifyNote: 'NRC 2006 \u56db\u6863\u5747\u5df2\u9010\u9879 4:1 \u6821\u9a8c\u843d\u5e93\uff1a\u886815-3 \u5e7c\u72ac\u751f\u957f dog.growth(43)\u3001\u886815-5 \u72ac\u7ef4\u6301 dog.adult(18)\u3001\u886815-10 \u65ad\u5976\u5e7c\u732b\u751f\u957f cat.growth(32)\u3001\u886815-12 \u6210\u5e74\u732b\u7ef4\u6301 cat.adult(24)\u3002\u5355\u4f4d\u53cc\u57fa\u51c6(per 100g DM \u7684 min \u4e0e per 1000 kcal ME \u7684 minME)\u5bf9\u9f50 FEDIAF\uff1bNRC.min \u4e3a\u6700\u4f4e\u9700\u8981\u91cf\u79d1\u5b66\u4e0b\u9650\uff0cresolveStandard \u53d6\u591a\u4f53\u7cfb max(min) \u65f6\u81ea\u52a8\u6210\u4e3a\u786c\u5730\u677f\u3002\u77ff\u7269/\u7ef4\u751f\u7d20\u4ec5\u5728\u5176\u6700\u4f4e\u7ec4\u786e\u6709\u6570\u503c\u65f6\u5199\u5165\uff0c\u7a7a\u767d\u6700\u4f4e\u7ec4\u4e0d\u5199\u5165(\u5730\u677f\u7531 AAFCO/FEDIAF/GB \u63d0\u4f9b)\u3002',
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 18.0, minME: 45.0, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          arginine: { min: 0.63, minME: 1.58, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          histidine: { min: 0.31, minME: 0.78, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          isoleucine: { min: 0.52, minME: 1.3, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          leucine: { min: 1.03, minME: 2.58, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          lysine: { min: 0.7, minME: 1.75, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine: { min: 0.28, minME: 0.7, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine_cystine: { min: 0.56, minME: 1.4, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine: { min: 0.52, minME: 1.3, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine_tyrosine: { min: 1.04, minME: 2.6, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          threonine: { min: 0.65, minME: 1.63, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          tryptophan: { min: 0.18, minME: 0.45, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          valine: { min: 0.54, minME: 1.35, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          crude_fat: { min: 8.5, minME: 21.3, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          linoleic_acid: { min: 1.18, minME: 3.0, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          ala: { min: 0.07, minME: 0.18, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          arachidonic_acid: { min: 0.03, minME: 0.08, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          epa_dha: { min: 0.05, minME: 0.13, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          calcium: { min: 0.8, minME: 2.0, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          phosphorus: { min: 1.0, minME: 2.5, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          potassium: { min: 0.44, minME: 1.1, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          sodium: { min: 0.22, minME: 550, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          chloride: { min: 0.29, minME: 720, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          magnesium: { min: 0.018, minME: 45, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          copper: { min: 1.1, minME: 2.7, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          iron: { min: 7.2, minME: 18, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          manganese: { min: 0.56, minME: 1.4, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          zinc: { min: 4.0, minME: 10, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          selenium_dry: { min: 21.0, minME: 52.5, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          selenium_wet: { min: 21.0, minME: 52.5, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          iodine: { min: 0.088, minME: 220, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_a: { min: 403.596, minME: 303, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_d: { min: 44.0, minME: 2.75, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_e: { min: 4.47, minME: 7.5, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_k: { min: 130.0, minME: 0.33, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b1: { min: 0.108, minME: 0.27, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b2: { min: 0.42, minME: 1.05, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b5: { min: 1.2, minME: 3.0, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b6: { min: 0.12, minME: 0.3, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b12: { min: 3.5, minME: 8.75, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b3: { min: 1.36, minME: 3.4, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b9: { min: 21.6, minME: 54, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
          choline: { min: 136.0, minME: 340, cite: 'NRC 2006《犬猫营养需要》表15-3（幼犬断奶后生长需要量），4-14周龄最低需要量/适宜量；per kg DM 与 per 1000 kcal ME 双基准，本模块折算为 per-100g-DM 口径对齐 FEDIAF' },
        },
        adult: {
          crude_protein: { min: 8.0, minME: 20.0, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          arginine: { min: 0.28, minME: 0.70, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          histidine: { min: 0.15, minME: 0.37, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          isoleucine: { min: 0.30, minME: 0.75, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          leucine: { min: 0.54, minME: 1.35, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          lysine: { min: 0.28, minME: 0.70, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine: { min: 0.26, minME: 0.65, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine_cystine: { min: 0.52, minME: 1.30, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine: { min: 0.36, minME: 0.90, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine_tyrosine: { min: 0.59, minME: 1.48, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          threonine: { min: 0.34, minME: 0.85, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          tryptophan: { min: 0.11, minME: 0.28, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          valine: { min: 0.39, minME: 0.98, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          calcium: { min: 0.20, minME: 0.50, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          magnesium: { min: 0.018, minME: 45.0, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          sodium: { min: 0.03, minME: 75.0, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          iodine: { min: 0.07, minME: 175.0, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b2: { min: 0.42, minME: 1.05, cite: 'NRC 2006《犬猫营养需要》表15-5（犬维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 18.0, minME: 45.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          arginine: { min: 0.772, minME: 1.93, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          histidine: { min: 0.26, minME: 0.65, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          isoleucine: { min: 0.432, minME: 1.08, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          leucine: { min: 1.02, minME: 2.55, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          lysine: { min: 0.68, minME: 1.7, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine: { min: 0.352, minME: 0.88, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine_cystine: { min: 0.7, minME: 1.75, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine: { min: 0.4, minME: 1.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine_tyrosine: { min: 1.532, minME: 3.83, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          threonine: { min: 0.52, minME: 1.3, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          tryptophan: { min: 0.132, minME: 0.33, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          valine: { min: 0.512, minME: 1.28, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          taurine: { min: 0.032, minME: 0.08, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          calcium: { min: 0.52, minME: 1.3, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phosphorus: { min: 0.48, minME: 1.2, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          potassium: { min: 0.268, minME: 0.67, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          sodium: { min: 0.124, minME: 310.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          chloride: { min: 0.076, minME: 190.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          magnesium: { min: 0.016, minME: 40.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          iron: { min: 6.8, minME: 17.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          copper: { min: 0.44, minME: 1.1, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          manganese: { min: 0.48, minME: 1.2, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          zinc: { min: 5.0, minME: 12.5, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          selenium_dry: { min: 12.0, minME: 30.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          iodine: { min: 0.18, minME: 450.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b1: { min: 0.44, minME: 1.1, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b5: { min: 0.46, minME: 1.15, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b6: { min: 0.2, minME: 0.5, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b9: { min: 60.0, minME: 150.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_d: { min: 11.0, minME: 0.7, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          choline: { min: 204.0, minME: 510.0, cite: 'NRC 2006《犬猫营养需要》表15-10（断奶幼猫生长需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
        },
        adult: {
          crude_protein: { min: 16.0, minME: 40.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          arginine: { min: 0.77, minME: 1.93, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          histidine: { min: 0.26, minME: 0.65, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          isoleucine: { min: 0.43, minME: 1.08, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          leucine: { min: 1.02, minME: 2.55, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          lysine: { min: 0.27, minME: 0.68, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine: { min: 0.135, minME: 0.34, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          methionine_cystine: { min: 0.27, minME: 0.68, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine: { min: 0.4, minME: 1.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phenylalanine_tyrosine: { min: 1.53, minME: 3.83, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          threonine: { min: 0.52, minME: 1.3, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          tryptophan: { min: 0.13, minME: 0.33, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          valine: { min: 0.51, minME: 1.28, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          taurine: { min: 0.032, minME: 0.08, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          calcium: { min: 0.16, minME: 0.4, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          phosphorus: { min: 0.14, minME: 0.35, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          magnesium: { min: 0.02, minME: 50.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          sodium: { min: 0.064, minME: 160.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          iodine: { min: 0.128, minME: 320.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b5: { min: 0.46, minME: 1.15, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b6: { min: 0.2, minME: 0.5, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_b9: { min: 60.0, minME: 150.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          vitamin_d: { min: 22.4, minME: 1.4, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
          choline: { min: 204.0, minME: 510.0, cite: 'NRC 2006《犬猫营养需要》表15-12（成年猫维持营养需要量），最低需要量；per kg DM 与 per 1000 kcal ME 双基准，折算为 per-100g-DM 口径对齐 FEDIAF' },
        },
      },
    },
  },
}

export const STANDARD_SET_IDS = Object.keys(STANDARD_SETS)

/**
 * 目标市场模式：决定要**同时满足**哪些标准体系。
 * 默认 `cn`（在中国境内生产销售，GB 是法定依据）。
 */
export const MARKET_MODES = [
  {
    id: 'cn',
    label: '仅中国 GB 标签',
    desc: '按 GB/T 31216-2014（犬粮）、GB/T 31217-2014（猫粮）判定，适用于国内生产销售。',
    sets: ['CN-GB'],
  },
  {
    id: 'cn-intl',
    label: '中国 GB + 国际（AAFCO/FEDIAF）',
    desc: '同时满足国标与出口市场的营养要求，逐项取最严值。',
    sets: ['CN-GB', 'AAFCO', 'FEDIAF', 'NRC'],
  },
  {
    id: 'intl',
    label: '仅国际（AAFCO/FEDIAF）',
    desc: '按 AAFCO / FEDIAF 判定，适用于出口或不以国标为验收依据的场景。',
    sets: ['AAFCO', 'FEDIAF', 'NRC'],
  },
]

export const DEFAULT_MARKET = 'cn'

export function getMarketMode(id) {
  return MARKET_MODES.find((m) => m.id === id) || MARKET_MODES.find((m) => m.id === DEFAULT_MARKET)
}

/** 生命阶段档位：生长/繁殖/泌乳合并为 growth（与 GB 表的分组方式一致） */
export function stageOf(status) {
  return (status === 'growth' || status === 'gestation' || status === 'lactation') ? 'growth' : 'adult'
}

/**
 * 水分形态分级（GB 表 3 / 表 2）。返回 { id, label, cite, available }
 * 水分不足 14% 为干性，14~60% 半湿性，≥60% 湿性。
 */
export function classifyMoisture(moisturePercent) {
  const UNKNOWN = { id: 'unknown', label: '未判定', cite: '', available: false }
  // 注意：Number(null) === 0 且有限，会被误判成「水分 0% → 干性」。空值必须先挡掉。
  // ⚠ 空白串（' '）与布尔/数组同样会被 Number() 变成 0/1，一并按「未判定」处理
  //   —— 与 data/moistureProfiles.js 的 parseMoisturePercent 保持同一口径。
  // ★ 本函数只管「**标准分档**」：x 是**检测/标示**水分，用来查 GB 表 3 的干性/半湿/湿性。
  //   引擎侧另有一道 ≥1% 硬下限（nutrition.js 的 below_min_moisture，常量在
  //   moistureProfiles.MIN_FINISHED_MOISTURE），那是「**成品水分折算**」的业务闸门。
  //   两者职责不同，别把硬下限搬到这里 —— 否则 0% 会连标准分档都判不出来。
  if (moisturePercent == null) return UNKNOWN
  if (typeof moisturePercent === 'string' && moisturePercent.trim() === '') return UNKNOWN
  if (typeof moisturePercent !== 'number' && typeof moisturePercent !== 'string') return UNKNOWN
  const x = Number(moisturePercent)
  if (!Number.isFinite(x)) return UNKNOWN
  const g = STANDARD_SETS['CN-GB'].moistureGrades.find((it) => it.test(x))
  return g ? { id: g.id, label: g.label, cite: g.cite, available: true } : { id: 'unknown', label: '未判定', cite: '', available: false }
}

/** 条款 → 展示文案（如 '≥22.0' / '≤10.0' / '1.0:1 ~ 1.8:1'） */
export function clauseText(clause, { unit = '%DM', key = '' } = {}) {
  if (!clause) return '—'
  const fmt = (n) => (Number.isInteger(n) ? n.toFixed(1) : String(n))
  const isRatio = key === 'caP'
  const hasMin = clause.min != null
  const hasMax = clause.max != null
  if (hasMin && hasMax) return isRatio ? `${fmt(clause.min)}:1 ~ ${fmt(clause.max)}:1` : `${fmt(clause.min)} ~ ${fmt(clause.unit || unit)}`
  if (hasMin) return isRatio ? `≥${fmt(clause.min)}:1` : `≥${fmt(clause.min)}`
  if (hasMax) return isRatio ? `≤${fmt(clause.max)}:1` : `≤${fmt(clause.max)}`
  return '—'
}

/**
 * 解析出「本配方应同时满足的合并标准」。
 *
 * @param {object} opts
 *   marketId      目标市场模式 id（缺省 DEFAULT_MARKET）
 *   species       'cat' | 'dog'
 *   stage         'growth' | 'adult'
 *   moistureClass 'dry' | 'semi-moist' | 'wet' | 'unknown'（用于牛磺酸湿粮档）
 * @returns {{
 *   marketId, marketLabel, marketDesc, setIds, setLabels,
 *   items: Array<{
 *     key, label, unit, kind, dataField, available, computed,
 *     min, max, sources: Object<string,string>, cites: string[],
 *     text: string, active: boolean, warn: string
 *   }>,
 *   warnings: string[], setNotes: Array<{id,label,note}>,
 *   moistureClass, sourceLabel
 * }}
 */
export function resolveStandard({ marketId, species = 'cat', stage = 'adult', moistureClass = 'unknown' } = {}) {
  const market = getMarketMode(marketId)
  const activeSets = market.sets.map((id) => STANDARD_SETS[id]).filter(Boolean)
  const sp = species === 'dog' ? 'dog' : 'cat'

  const warnings = []
  const setNotes = []
  for (const s of activeSets) {
    if (s.valuesPending) {
      setNotes.push({ id: s.id, label: s.label, note: s.pendingNote })
      warnings.push(`${s.label} 已登记但数值待补，本轮不参与判定（${s.pendingNote}）`)
    } else if (s.verified === false && s.verifyNote) {
      setNotes.push({ id: s.id, label: s.label, note: s.verifyNote })
      warnings.push(`${s.label}：${s.verifyNote}`)
    }
  }

  // 汇总所有体系的条款：项目取并集
  const keys = []
  for (const s of activeSets) {
    const tbl = s.stages?.[sp]?.[stage]
    if (!tbl) continue
    for (const k of Object.keys(tbl)) if (!keys.includes(k)) keys.push(k)
  }

  const items = keys.map((k) => {
    const meta = NUTRIENT_META[k] || { label: k, unit: '', dataField: null, kind: 'min' }
    const sources = {}
    const cites = []
    let min = null
    let max = null
    let wetMin = null
    let conflict = ''

    for (const s of activeSets) {
      const clause = s.stages?.[sp]?.[stage]?.[k]
      if (!clause) continue
      sources[s.id] = clauseText(clause, { unit: meta.unit, key: k })
      if (clause.cite) cites.push(`${s.label} ${clause.cite}`)
      if (clause.min != null) {
        if (min == null || clause.min > min) min = clause.min
      }
      if (clause.max != null) {
        if (max == null || clause.max < max) max = clause.max
      }
      if (clause.wetMin != null) {
        if (wetMin == null || clause.wetMin > wetMin) wetMin = clause.wetMin
      }
    }

    // 湿粮档：牛磺酸等在湿性产品上适用更严的下限
    let appliedMin = min
    let wetApplied = false
    if (wetMin != null && moistureClass === 'wet' && (min == null || wetMin > min)) {
      appliedMin = wetMin
      wetApplied = true
    }

    if (appliedMin != null && max != null && appliedMin > max) {
      conflict = `各体系条款区间无交集（下限 ${appliedMin} > 上限 ${max}），请人工核对标准原文`
      warnings.push(`${meta.label}：${conflict}`)
    }

    const text = clauseText({ min: appliedMin, max }, { unit: meta.unit, key: k })

    return {
      key: k,
      label: meta.label,
      unit: meta.unit,
      kind: meta.kind,
      dataField: meta.dataField,
      computed: meta.computed || null,
      available: !!meta.dataField || !!meta.computed,
      min: appliedMin,
      max,
      sources,
      cites,
      text,
      wetApplied,
      warn: conflict,
      // 仅展示、不参与达标判定的条目（系统无数据支撑的氨基酸类）
      active: (!!meta.dataField || !!meta.computed) && !conflict && (appliedMin != null || max != null),
    }
  })

  // 标记系统无数据支撑的项目（不冒充未达标）
  const unavailable = items.filter((it) => !it.available).map((it) => it.label)
  if (unavailable.length) {
    warnings.push(`原料库无${unavailable.join('、')}数据，这些项目无法自动判定（需先补氨基酸/相关检测数据）`)
  }

  const setLabels = activeSets.filter((s) => !s.valuesPending).map((s) => s.label)
  const sourceLabel = setLabels.length
    ? `${market.label}（${setLabels.join(' + ')}）`
    : market.label

  return {
    marketId: market.id,
    marketLabel: market.label,
    marketDesc: market.desc,
    setIds: activeSets.map((s) => s.id),
    setLabels,
    items,
    warnings,
    setNotes,
    moistureClass,
    sourceLabel,
  }
}
