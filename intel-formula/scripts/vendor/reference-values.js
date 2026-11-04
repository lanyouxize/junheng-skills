/**
 * 参数参照表：把「该拿哪个数去比」变成**可读到的数**。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 为什么需要这张表
 * ══════════════════════════════════════════════════════════════════════
 * 本项目 120 个细项各带 `queries`（搜什么词）与 `checklist`（核什么点）。
 * 核查点写得不算差，但**通篇没有数**。典型的一条是泌尿那组：
 *
 *      「尿液酸化类原料是否核算过安全区间——过度酸化会反向促发草酸钙结石」
 *
 * 这句话是对的，也指对了方向，但它等于让人**自己去建一套标准**：
 * 安全区间是什么？过度酸化在哪一点开始？谁定的？
 * 于是执行时只剩两条路 —— 要么去翻商品粮的文案，要么凭印象拍一个值。
 * 两条都不可靠，而后者还多一层错觉（拍完就以为有依据了）。
 *
 * 合规模块早就解决了同一类问题：它把法定门槛（26% / 14% / 4% / ≥15%）
 * **直接写进理由**，使用者看到的是「去核对 26%」，而不是「去核对含量门槛」。
 * 这条经验没有任何理由只服务于合规。本模块就是把它推广到营养与临床侧。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 三条设计约束（每一条都对应一种会出事的形态）
 * ══════════════════════════════════════════════════════════════════════
 * ① **口径必须显式，缺失即拒绝入库。**
 *    数值最容易出事的地方不是错，而是**对的数被安到错的口径上**。
 *    AAFCO 的 26% 是**干物质（DM）基础、且假定 4000 kcal ME/kg**；
 *    把它和自然状态（as-fed）保证值放一起比，是行业里最常见的误用。
 *    所以每条都必须写明 物种 / 生命阶段 / 数值口径，三项缺一即判不合格
 *    （`validateReferenceValues()` 会把问题逐条列出来，测试里钉住它）。
 *
 * ② **出处必须带档位，二手必须自认二手。**
 *    `tier: 'L1'` = 官方文件或同行评议一手，可直接引用；
 *    `tier: 'L2'` = 权威二手转述，**必须**填 `verifyNote` 且句中出现「需回一手核对」。
 *    这不是形式要求 —— 一张「看起来都是数」的表，会把二手与一手拉平。
 *
 * ③ **数值一旦写死就会过期，所以每条都带 `updatedAt`，且界面要显示。**
 *    另外 AAFCO 的数值会随版本修订，本表载入的是附录 A 修订版；
 *    引用前核对版本年份这件事写进了 `caveat`，而不是靠使用者自己想到。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 与合规模块的关系：**复用不重抄**
 * ══════════════════════════════════════════════════════════════════════
 * 「标签数值」那一组（26 / 14 / 4 / 3 / ≥15% / 低脂肪低能量分档）已经存在于
 * `compliance.js` 的规则理由里。这里再抄一遍，代价不是代码重复，
 * 而是**两份数字迟早对不上** —— 那时「合规页说 26%、参照表说 25%」会同时出现在一屏。
 * 所以测试里有一条**双向漂移守卫**：本表的每个法定数字，必须能在
 * `compliance.js` 源码里找到；反之亦然（见 scripts/reference-test.mjs）。
 *
 * 本模块**零依赖、纯数据 + 纯函数**：不 import 任何 `node:` 模块，也不 import
 * 其它项目模块。原因同 `page-quality.js`：`src/lib` 同时被静态暴露给浏览器
 * （`app.js` 直接 import 它），一旦带上 `node:` 依赖，整张前端模块图会加载失败。
 */

/** 表的整体口径声明。界面上要原样显示，不要改写成更自信的说法。 */
export const REFERENCE_DISCLAIMER = '本表是**核对方向的参照值**，不是标准原文、也不是判定依据。'
  + '数值会随标准修订而过期：每条都带更新日期与来源档位，正式引用前请回到来源原文核对版本。'
  + '涉及合规判断的，一律以现行法规与标准原文为准。';

/** 六字段的必填口径。测试逐条检查；界面按同一份说明渲染，避免「界面忘了某一栏」。 */
export const REFERENCE_FIELD_SPEC = [
  { key: 'values', label: '数值', note: '必填；至少一项，每项要有标签与实际取值' },
  { key: 'basis', label: '口径', note: '必填；DM/ME？全价？尿检？——数值最容易出错的地方就是口径被省略' },
  { key: 'species', label: '适用物种', note: '必填；猫与犬不能合并成「宠物」' },
  { key: 'lifeStage', label: '适用生命阶段 / 状态', note: '必填；不限也要显式写「不限」，缺省不等于不限' },
  { key: 'source', label: '出处', note: '必填；带档位 L1（一手，可直接引用）/ L2（二手，须回一手核对）' },
  { key: 'updatedAt', label: '更新日期', note: '必填；数值会过期，界面要显示它' },
];

/** 分组。界面按组呈现；`compliance` 标记决定它是否也出现在宣称合规页。 */
export const REFERENCE_GROUPS = [
  {
    id: 'urine', name: '泌尿：尿液 pH 目标区间', icon: '⊕',
    why: '同一只猫不可能同时满足两个方向 —— 溶解磷酸铵镁要酸、预防草酸钙怕酸。'
      + '「酸化剂加多少」这个问题因此**没有单一答案**，必须先明确目标结晶类型。',
  },
  {
    id: 'aafco', name: '营养基准：AAFCO 最低值与上限', icon: '⊞',
    why: '所有「够不够」的比较都要回到两个限定：**干物质基础**与**假定能量密度 4000 kcal ME/kg**。',
  },
  {
    id: 'fiber', name: '毛球与排毛：已研究的纤维剂量', icon: '◍',
    why: '这一组存在的意义是把「概念添加」暴露出来：试验剂量 11%–15% TdF，'
      + '与「配料表里加一点车前子壳」不是一个量级。',
  },
  {
    id: 'label', name: '标签数值：法定门槛（与合规模块同源）', icon: '§',
    why: '合规规则里已经写死的数值。收进这张表是为了让检索地图的条目也能直接看到数，'
      + '而不是看到「有含量门槛」四个字。',
  },
];

export const REFERENCE_GROUP_MAP = Object.fromEntries(REFERENCE_GROUPS.map((g) => [g.id, g]));

/**
 * 参照值条目。
 *
 * `subs` 里的 id 必须真实存在于 `sources.js` 的细项中 —— 写错一个字母的后果是
 * 「这条参照值永远不会出现在任何细项下」，而且是静默的。测试里有专门一条钉住它。
 */
export const REFERENCE_VALUES = [
  /* ─────────────────────── 泌尿：尿液 pH ─────────────────────── */
  {
    id: 'cat-urine-ph-targets',
    group: 'urine',
    compliance: true,
    title: '猫尿液 pH：按目标结晶类型分档（两个方向互相拉扯）',
    species: '猫',
    lifeStage: '成年（已确诊或高风险的尿石症管理）',
    basis: '尿液 pH（需实测，不是日粮口径）',
    values: [
      { label: '溶解磷酸铵镁（struvite）—— 目标', value: 'pH < 6.4' },
      { label: '预防草酸钙复发 —— 关注', value: '避免持续性过度酸化；若 pH 持续 < 6.5 应考虑碱化（如钾柠檬酸盐）' },
    ],
    source: {
      tier: 'L1',
      name: '2025 iCatCare 猫下泌尿道疾病诊疗共识（Journal of Feline Medicine and Surgery）',
      year: 2025,
      url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC11816079/',
    },
    updatedAt: '2026-10-01',
    caveat: '这两条**方向相反**，正是本组要暴露的东西：struvite 要酸、草酸钙怕酸。'
      + '所以任何「猫粮尿 pH 应控制在 X–Y」的说法，如果不先说明**目标结晶类型**，就是不完整的。'
      + '配方上「多加酸化剂」从来不是单向更安全。',
    subs: ['rf-urinary', 'cl-renal'],
  },
  {
    id: 'urine-ph-dissolve-prevent',
    group: 'urine',
    compliance: true,
    title: '犬猫尿液 pH：溶解 / 预防 / 草酸钙 的分档目标（二手，待核）',
    species: '犬与猫',
    lifeStage: '不限（结石管理）',
    basis: '尿液 pH（需实测）',
    values: [
      { label: '溶解 struvite · 猫', value: '5.9 – 6.1' },
      { label: '溶解 struvite · 犬', value: '5.8 – 6.2' },
      { label: '预防复发 · 犬与猫', value: '6.2 – 6.4' },
      { label: '草酸钙管理目标 · 猫', value: '约 6.8' },
      { label: '草酸钙管理目标 · 犬', value: '7.1 – 7.7' },
      { label: '尿酸盐管理 · 犬', value: '> 7.1' },
    ],
    source: {
      tier: 'L2',
      name: '兽医临床营养教材章节（经二手转载，原始文献未在系统内核到）',
      year: 0,
      url: '',
    },
    verifyNote: '本组数字来自教材章节的**二手转述**，系统未核到原始文献 —— **需回一手核对**后再用于配方决策。'
      + '上面 `cat-urine-ph-targets` 那条 L1 共识给的方向与它一致（struvite 要酸、草酸钙怕酸），可用作交叉印证，但具体区间值以一手为准。',
    updatedAt: '2026-10-01',
    caveat: '注意「溶解」与「预防」是两套目标值，不是同一套的宽窄版本：'
      + '治疗期可以压到 5.9–6.1，长期维持压在 6.2–6.4，而草酸钙高风险个体反而要往上走。'
      + '拿治疗期目标当长期配方目标，是这组数值最常见的误用。',
    subs: ['rf-urinary', 'cl-renal', 'lc-senior'],
  },
  {
    id: 'urine-ph-commercial-claim',
    group: 'urine',
    compliance: false,
    title: '商品处方粮公开的技术资料口径（厂商声明，待核）',
    species: '猫',
    lifeStage: '成年（非生长期、非 CKD / 非心衰）',
    basis: '尿液 pH',
    values: [
      { label: '厂商声明的产品目标区间', value: 'pH 6.0 – 6.5' },
      { label: '厂商声明的合规基础', value: 'EU Commission Regulation (EU) 2020/354（系统未核对原文）' },
    ],
    source: {
      tier: 'L2',
      name: '商品处方粮技术资料（厂商口径）',
      year: 2017,
      url: '',
    },
    verifyNote: '这是**厂商技术资料**，不是官方标准。列在这里是因为研发最常照抄的正是它 —— '
      + '把她当依据之前**需回一手核对**（其声称的合规基础为欧盟 2020/354，本系统未核原文）。',
    updatedAt: '2026-10-01',
    caveat: '同一厂商的溶解期产品与长期维持产品是两个不同的目标值。'
      + '把商品粮文案里的区间直接当自家配方目标，等于把别人的**产品设定**当成了**行业标准**。',
    subs: ['rf-urinary', 'prod-rx', 'reg-eu'],
  },

  /* ─────────────────── 营养基准：AAFCO ─────────────────── */
  {
    id: 'aafco-macronutrient',
    group: 'aafco',
    compliance: false,
    title: '犬猫 AAFCO 粗蛋白 / 粗脂肪最低值（四个档位）',
    species: '犬与猫',
    lifeStage: '成年维持 / 生长与繁殖（两档）',
    basis: '干物质（DM）基础；AAFCO 假定能量密度 4000 kcal ME/kg',
    values: [
      { label: '犬 · 生长与繁殖 · 粗蛋白（最低）', value: '22.5% DM' },
      { label: '犬 · 成年维持 · 粗蛋白（最低）', value: '18.0% DM' },
      { label: '猫 · 生长与繁殖 · 粗蛋白（最低）', value: '30.0% DM' },
      { label: '猫 · 成年维持 · 粗蛋白（最低）', value: '26.0% DM' },
      { label: '犬 · 生长与繁殖 · 粗脂肪（最低）', value: '8.5% DM' },
      { label: '犬 · 成年维持 · 粗脂肪（最低）', value: '5.5% DM' },
      { label: '猫 · 生长与繁殖 · 粗脂肪（最低）', value: '9.0% DM' },
      { label: '猫 · 成年维持 · 粗脂肪（最低）', value: '9.0% DM' },
    ],
    source: {
      tier: 'L1',
      name: 'AAFCO Dog and Cat Food Nutrient Profiles（附录 A 修订版）',
      year: 2014,
      url: 'https://www.aafco.org/wp-content/uploads/2023/01/Pet_Food_Report_Annual_2014-Appendix_A-Revised_AAFCO_Nutrient_Profiles-Final_092214.pdf',
    },
    updatedAt: '2026-10-01',
    caveat: '三个必须同时记住的限定：① **干物质基础**（不是保证值上的自然状态百分比）；'
      + '② 假定能量密度 **4000 kcal ME/kg** —— 高于 4000 的配方需按能量密度校正，**低于 4000 的不做校正**；'
      + '③ 猫的粗蛋白最低值比犬高一档以上，**猫不是小号的犬**。'
      + 'AAFCO 的数值会随版本修订，正式引用前请核对版本年份。',
    subs: ['raw-standard', 'raw-protein', 'raw-fat', 'lc-growth', 'lc-species'],
  },
  {
    id: 'aafco-minerals',
    group: 'aafco',
    compliance: false,
    title: '犬猫 AAFCO 钙 / 磷 的最低与**最高**（四个档位）',
    species: '犬与猫',
    lifeStage: '成年维持 / 生长与繁殖（两档）',
    basis: '干物质（DM）基础；AAFCO 假定能量密度 4000 kcal ME/kg',
    values: [
      { label: '犬 · 生长与繁殖 · 钙（最低 / 最高）', value: '1.2% / 1.8% DM' },
      { label: '犬 · 成年维持 · 钙（最低 / 最高）', value: '0.5% / 2.5% DM' },
      { label: '猫 · 生长与繁殖 · 钙（最低 / 最高）', value: '1.0% / 1.8% DM' },
      { label: '猫 · 成年维持 · 钙（最低 / 最高）', value: '0.6% / 2.5% DM' },
      { label: '犬 · 生长与繁殖 · 磷（最低 / 最高）', value: '1.0% / 1.6% DM' },
      { label: '犬 · 成年维持 · 磷（最低 / 最高）', value: '0.4% / 1.6% DM' },
      { label: '猫 · 生长与繁殖 · 磷（最低 / 最高）', value: '0.8% / 1.6% DM' },
      { label: '猫 · 成年维持 · 磷（最低 / 最高）', value: '0.5% / 1.8% DM' },
      { label: '钙磷比（生长与繁殖）', value: '1:1 至 2:1' },
    ],
    source: {
      tier: 'L1',
      name: 'AAFCO Dog and Cat Food Nutrient Profiles（附录 A 修订版）',
      year: 2014,
      url: 'https://www.aafco.org/wp-content/uploads/2023/01/Pet_Food_Report_Annual_2014-Appendix_A-Revised_AAFCO_Nutrient_Profiles-Final_092214.pdf',
    },
    updatedAt: '2026-10-01',
    caveat: '**最高限量与最低值同样重要**，而这正是「补钙/补磷」类卖点最容易越线的地方：'
      + '幼犬钙上限 1.8% DM、成犬 2.5% DM；磷上限固定 1.6% DM（猫成年维持 1.8%）。'
      + '只看最低值会让「钙磷双补」的配方在生长阶段直接超限 —— 而生长阶段的超限代价是骨骼发育异常。',
    subs: ['raw-standard', 'raw-vitmin', 'lc-growth'],
  },
  {
    id: 'aafco-cat-essential',
    group: 'aafco',
    compliance: false,
    title: '猫的几项「不是可选」：牛磺酸 / 精氨酸 / 亚油酸 最低值',
    species: '猫',
    lifeStage: '成年维持 / 生长与繁殖（两档）',
    basis: '干物质（DM）基础；AAFCO 假定能量密度 4000 kcal ME/kg',
    values: [
      { label: '牛磺酸（最低）· 生长与繁殖', value: '0.20% DM' },
      { label: '牛磺酸（最低）· 成年维持', value: '0.10% DM' },
      { label: '精氨酸（最低）· 生长与繁殖', value: '1.25% DM' },
      { label: '精氨酸（最低）· 成年维持', value: '1.04% DM' },
      { label: '亚油酸（最低）· 两档相同', value: '0.5% DM' },
    ],
    source: {
      tier: 'L1',
      name: 'AAFCO Cat Food Nutrient Profiles（附录 A 修订版）',
      year: 2014,
      url: 'https://www.aafco.org/wp-content/uploads/2023/01/Pet_Food_Report_Annual_2014-Appendix_A-Revised_AAFCO_Nutrient_Profiles-Final_092214.pdf',
    },
    updatedAt: '2026-10-01',
    caveat: '牛磺酸这一行要连口径一起用：数值是**配方终产品的 DM 最低值**，'
      + '不能拿单一原料的引入量去比 —— 加工损失、原料本底波动与配方占比三者都要进核算。'
      + '精氨酸缺乏在猫身上急性且严重，它在表里是「最低值」，不是「参考值」。',
    subs: ['raw-protein', 'raw-vitmin', 'rf-heart', 'cl-cardio'],
  },

  /* ─────────────── 毛球与排毛：已研究的纤维剂量 ─────────────── */
  {
    id: 'hairball-fiber-dose',
    group: 'fiber',
    compliance: false,
    title: '猫粪便排毛：已研究的膳食纤维剂量（Weber 2015）',
    species: '猫（**仅长毛猫观察到效果**）',
    lifeStage: '成年',
    basis: '总膳食纤维（TdF）占日粮比例；试验期 14 天；**避开换毛季**',
    values: [
      { label: '对照（低纤维）', value: '6.0% TdF' },
      { label: '试验组 1', value: '11% TdF' },
      { label: '试验组 2', value: '15% TdF' },
      { label: '长毛猫粪便排毛量（11% vs 6%）', value: '增加 81%（P<0.001）' },
      { label: '长毛猫粪便排毛量（15% vs 6%）', value: '增加 113%（P<0.001）' },
      { label: '短毛猫', value: '11% 与 15% 均未观察到影响' },
    ],
    source: {
      tier: 'L1',
      name: 'Weber M, Sams L, Feugier A, Michel S, Biourge V. Influence of the dietary fibre levels on faecal hair excretion after 14 days in short and long-haired domestic cats. Vet Med Sci. 2015;1(1):30–37.',
      year: 2015,
      url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC5645811/',
    },
    updatedAt: '2026-10-01',
    caveat: '**这一条是本表的重点，也是「概念添加」最容易在这里暴露的地方。**'
      + '引用它必须连同三个限定一起引用：① 效果**只在长毛猫**身上观察到，短毛猫无差异；'
      + '② 试验期只有 **14 天**、且明确避开了换毛季，不能外推到全年；'
      + '③ 剂量是 **11%–15% TdF**，这是一个远高于「配料表里加一点车前子壳」的量级。'
      + '把「纤维有助于排毛」简化成「加了纤维就能排毛」，正是本表要挡的那一步。',
    subs: ['rp-fiber', 'raw-carb', 'rf-coat', 'cl-gi'],
  },

  /* ─────────── 标签数值：法定门槛（与合规模块同源） ─────────── */
  {
    id: 'label-wording-threshold',
    group: 'label',
    compliance: true,
    title: '成分声称的用量门槛（标签规定第二十条（三）3、（三）5）',
    species: '犬与猫（不区分）',
    lifeStage: '不限',
    basis: '该原料在**产品总重**中的占比；经脱水处理的原料可依**水分还原后**计（附录 7）',
    values: [
      { label: '「××配方」', value: '26% 以上' },
      { label: '「含××配方」', value: '14% 以上' },
      { label: '「含××」', value: '4% 以上' },
      { label: '「添加××」', value: '无比例门槛（未达 4%、但足以赋予产品某种特有属性时可用）' },
      { label: '组合声称中的其余每一种', value: '3% 以上，且按重量百分比降序排列' },
    ],
    source: {
      tier: 'L1',
      name: '《宠物饲料标签规定》（农业农村部公告第 20 号）第二十条（三）3、（三）5、附录 7',
      year: 2018,
      url: '',
    },
    updatedAt: '2026-10-01',
    caveat: '上述数值与 `src/lib/compliance.js` 的规则理由**同源**（测试里有双向漂移守卫）。'
      + '达标的证明方式见第二十条（二）的封闭列举：**配方组成**就是其中之一 —— '
      + '也就是说「本系统里没有这个数」与「法律上没有这个要求」是两件事。',
    subs: ['reg-label', 'add-functional', 'add-compliance'],
  },
  {
    id: 'label-compare-threshold',
    group: 'label',
    compliance: true,
    title: '含量比较声称的三个法定条件（第二十条（三）8）',
    species: '犬与猫（不区分）',
    lifeStage: '不限',
    basis: '与本企业**自身产品**的比较比例',
    values: [
      { label: '增高或降低的比例', value: '15% 以上' },
      { label: '参照物', value: '须为本企业产品并明确列示（不得以他人产品作参照）' },
      { label: '常量营养素', value: '该百分比还须能够通过配方进行验证' },
    ],
    source: {
      tier: 'L1',
      name: '《宠物饲料标签规定》第二十条（三）8',
      year: 2018,
      url: '',
    },
    updatedAt: '2026-10-01',
    caveat: '三个条件是**并列**的，缺一即不符合 —— 最常见的漏项是第二条：'
      + '「比市面某产品高 3 倍」既没有本企业参照物，也无配方可验证，形式上就不成立。',
    subs: ['reg-label', 'add-functional'],
  },
  {
    id: 'label-lowfat-lowenergy',
    group: 'label',
    compliance: true,
    title: '「低脂肪」「低能量」的法定分档阈值（按物种与水分含量）',
    species: '犬与猫（分档不同）',
    lifeStage: '不限',
    basis: '按**水分含量**分三档比较（水分含量决定用哪一档）',
    values: [
      { label: '低脂肪 · 犬', value: '水分<20% 且 ≤9%；20%~65% 且 ≤7%；>65% 且 ≤4%' },
      { label: '低脂肪 · 猫', value: '水分<20% 且 ≤10%；20%~65% 且 ≤8%；>65% 且 ≤5%' },
      { label: '低能量 · 犬（kJ ME/100g）', value: '<20% 且 ≤1296；20%~65% 且 ≤1045；≥65% 且 ≤376' },
      { label: '低能量 · 猫（kJ ME/100g）', value: '<20% 且 ≤1359；20%~65% 且 ≤1108；≥65% 且 ≤397' },
      { label: '形式要求', value: '以「能量」或「能量值」为引导词、同一展示版面、以 ME 表示并在值后括号注明「计算值」' },
    ],
    source: {
      tier: 'L1',
      name: '《宠物饲料标签规定》第二十条（三）相关项（低脂肪 / 低能量声称）',
      year: 2018,
      url: '',
    },
    updatedAt: '2026-10-01',
    caveat: '「低脂肪」在**湿粮**上的门槛比干粮严格得多（犬 4% / 猫 5%），'
      + '因为它按水分分档 —— 用干粮的 9% 去比一罐湿粮的 4%，会得出完全错误的结论。'
      + '这一组数值在 compliance.js 里有对应的命中规则（会直接写进理由）。',
    subs: ['reg-label', 'prod-rx', 'prod-dry', 'prod-wet'],
  },
];

const BY_ID = new Map(REFERENCE_VALUES.map((e) => [e.id, e]));

/** 按 id 取一条。取不到返回 null（不猜、不造一条空壳）。 */
export function referenceById(id) {
  return BY_ID.get(String(id || '')) || null;
}

/** 某个细项下的参照值。细项页用它决定「要不要显示参照值按钮」。 */
export function valuesForSub(subId) {
  const id = String(subId || '');
  if (!id) return [];
  return REFERENCE_VALUES.filter((e) => (e.subs || []).includes(id));
}

/** 某一组（或全部）的参照值。传空 / 不传视为「全部」。 */
export function valuesByGroup(groupId) {
  const g = String(groupId || '');
  if (!g || g === 'all') return REFERENCE_VALUES.slice();
  return REFERENCE_VALUES.filter((e) => e.group === g);
}

/** 宣称合规页要显示的那些（`compliance: true`）。 */
export function complianceReferenceValues() {
  return REFERENCE_VALUES.filter((e) => e.compliance === true);
}

/** 汇总：条数、覆盖的细项数、来源档位分布。用于界面上一句「本表有多少条」。 */
export function referenceStats(list = REFERENCE_VALUES) {
  const subs = new Set();
  for (const e of list) for (const s of (e.subs || [])) subs.add(s);
  const byTier = {};
  for (const e of list) {
    const t = e?.source?.tier || '未标';
    byTier[t] = (byTier[t] || 0) + 1;
  }
  return { entries: list.length, subs: subs.size, groups: REFERENCE_GROUPS.length, byTier };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * 逐条体检，返回**问题清单**（空数组 = 合格）。
 *
 * 为什么是「返回问题」而不是「抛错」：这条函数同时被三处用 ——
 * 测试（断言它为空的）、界面（有问题时如实显示）、以及将来可能的入库校验。
 * 抛错只服务第一处，另外两处还得再包一层 try。
 */
export function validateReferenceValues(list = REFERENCE_VALUES, { today = '2026-10-01' } = {}) {
  const problems = [];
  const seen = new Set();
  const knownGroups = new Set(REFERENCE_GROUPS.map((g) => g.id));

  for (const e of Array.isArray(list) ? list : []) {
    const tag = `[${e?.id || '未命名'}]`;
    if (!e || typeof e !== 'object') { problems.push('存在不是对象的条目'); continue; }
    if (!e.id) problems.push(`${tag} 缺 id`);
    else if (seen.has(e.id)) problems.push(`${tag} id 重复`);
    else seen.add(e.id);

    if (!knownGroups.has(e.group)) problems.push(`${tag} group「${e.group}」不在 REFERENCE_GROUPS 里`);

    // ① 数值
    if (!Array.isArray(e.values) || !e.values.length) {
      problems.push(`${tag} 缺数值（values 为空）`);
    } else {
      e.values.forEach((v, i) => {
        if (!v || typeof v !== 'object') problems.push(`${tag} 第 ${i + 1} 项数值不是对象`);
        else {
          if (!String(v.label || '').trim()) problems.push(`${tag} 第 ${i + 1} 项数值缺 label`);
          if (!String(v.value ?? '').trim()) problems.push(`${tag} 第 ${i + 1} 项数值缺 value`);
        }
      });
    }

    // ② 口径 / ③ 物种 / ④ 生命阶段 —— 三项缺一即不合格。缺省不等于「不限」。
    if (!String(e.basis || '').trim()) problems.push(`${tag} 缺口径（basis）—— 数值最容易出错的地方就是口径被省略`);
    if (!String(e.species || '').trim()) problems.push(`${tag} 缺适用物种`);
    if (!String(e.lifeStage || '').trim()) problems.push(`${tag} 缺适用生命阶段（不限也要显式写「不限」）`);

    // ⑤ 出处：档位 + 名称；非 L1 必须自认二手。
    const tier = e?.source?.tier;
    if (tier !== 'L1' && tier !== 'L2') problems.push(`${tag} 出处的档位必须是 L1 或 L2（当前「${tier}」）`);
    if (!String(e?.source?.name || '').trim()) problems.push(`${tag} 缺出处名称`);
    if (tier === 'L2' && !/需回一手核对/.test(String(e.verifyNote || ''))) {
      problems.push(`${tag} 是二手来源（L2），verifyNote 里必须出现「需回一手核对」`);
    }
    if (tier === 'L1' && String(e.verifyNote || '').trim()) {
      problems.push(`${tag} 标为 L1（一手）却带了 verifyNote —— 一手与二手不能两说`);
    }

    // ⑥ 更新日期
    const d = String(e.updatedAt || '');
    if (!DATE_RE.test(d)) problems.push(`${tag} 更新日期必须是 YYYY-MM-DD（当前「${d}」）`);
    else if (d > today) problems.push(`${tag} 更新日期「${d}」晚于今天 —— 日期写错会让整张表的时效判断失真`);

    if (!Array.isArray(e.subs) || !e.subs.length) problems.push(`${tag} 没有关联任何细项（subs 为空）`);
  }
  return problems;
}

/**
 * 把一组参照值拼成纯文本。给「复制参照值」用 ——
 * 与界面渲染**同源**，避免屏幕上是一套、复制出来是另一套。
 */
export function referenceToText(list = []) {
  const lines = [];
  for (const e of list) {
    lines.push(`${e.title}`);
    lines.push(`  物种：${e.species}　阶段：${e.lifeStage}`);
    lines.push(`  口径：${e.basis}`);
    for (const v of (e.values || [])) lines.push(`  · ${v.label}：${v.value}`);
    lines.push(`  出处：${e.source?.name || ''}${e.source?.year ? `（${e.source.year}）` : ''}　档位 ${e.source?.tier || '未标'}`);
    if (e.verifyNote) lines.push(`  注意：${e.verifyNote}`);
    lines.push(`  更新日期：${e.updatedAt}`);
    if (e.caveat) lines.push(`  使用边界：${e.caveat}`);
    lines.push('');
  }
  lines.push(`—— ${REFERENCE_DISCLAIMER}`);
  return lines.join('\n');
}
