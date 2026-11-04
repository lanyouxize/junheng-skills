/**
 * 猫用安全性种子表 —— `junheng-safety` 安全闸的**唯一数据源**。
 *
 * ## 为什么需要这一层
 * 配方算完营养、算完成本，仍可能「营养达标但有毒」：洋葱粉、葡萄渣、
 * 可可粉在配方表里都是一行原料。缺了这层，任何达标结论都可能指向一份
 * 不该给出的配方。所以安全闸必须**先于**营养结论。
 *
 * ## 数据边界（硬规则，2026-10-13 用户确认为硬规则）
 *   ① **只引事实，不复制来源原文**：`basis` 一律是**自撰的事实陈述**，
 *      不搬 ASPCA 条目原句；可核性由 `sourceIds` → `SOURCES` 的
 *      `org / item / url / fetchedAt` 四元组保证。
 *   ② **无来源不收录**：每条必须有 ≥1 个 `sourceIds`。宁缺毋滥。
 *   ③ **先做猫**：`species` 记录**来源实际支持**的物种，不是「猫犬都写上更保险」。
 *      来源只支持猫的（百合、氯菊酯）就**只写 cat** —— 这决定了
 *      「猫配方里氯菊酯 ⇒ banned」而「犬配方里氯菊酯 ⇒ 不判定」这类正确行为。
 *
 * ## 与 `level` 的关系（★ 不要在这里造 `ok`）
 * 本表只出 `banned` / `caution` 两态。`ok` 属**显式安全声明**，
 * 未收录一律 `unknown` —— 判定逻辑在 `src/lib/toxicology.js`，本文件是纯数据。
 *
 * ## 字段
 *   id          稳定标识（判据与测试引用它，勿改）
 *   substance   规范名（中文，可读）
 *   latin       学名 / 化学名（无则 null）
 *   aliases     匹配用别名（中文 + 英文，小写）；判定走**包含**匹配
 *   species     来源实际支持的物种：'cat' | 'dog'
 *   level       'banned'（禁用）| 'caution'（条件/限量）
 *   conditions  `caution` 必带：什么条件下可用（`banned` 恒为 null）
 *   category    场景分类：food | plant | drug | household（供调用方过滤）
 *   basis       事实陈述（自撰）
 *   sourceIds   指向 `SOURCES` 的键
 */

/**
 * 来源字典。**每条都必须可回溯**：org（机构）/ item（条目标题）/ url / fetchedAt。
 * ⚠ 新增条目时若来源不在表内，先补来源 —— 不允许内联一个没有四元组的「来源」。
 */
export const SOURCES = {
  'aspca-people-foods': {
    org: 'ASPCA Animal Poison Control Center',
    item: 'People Foods to Avoid Feeding Your Pets',
    url: 'https://www.aspca.org/pet-care/aspca-poison-control/people-foods-avoid-feeding-your-pets/',
    fetchedAt: '2026-10-13',
  },
  'aspcapro-never-eat': {
    org: 'ASPCApro',
    item: 'People Foods Pets Should Never Eat',
    url: 'https://www.aspcapro.org/resource/people-foods-pets-should-never-eat',
    fetchedAt: '2026-10-13',
  },
  'aspca-toxic-plants': {
    org: 'ASPCA Animal Poison Control Center',
    item: 'Do You Know Which Flowers and Plants are Toxic to Pets?',
    url: 'https://www.aspca.org/news/do-you-know-which-flowers-and-plants-are-toxic-pets-our-experts-explain',
    fetchedAt: '2026-10-13',
  },
  'aspca-lilies': {
    org: 'ASPCA Animal Poison Control Center',
    item: 'Getting to the Bottom of the Dangers of Easter Lilies',
    url: 'https://www.aspca.org/news/getting-bottom-dangers-easter-lilies',
    fetchedAt: '2026-10-13',
  },
  'aspca-feline-hazards': {
    org: 'ASPCA Animal Poison Control Center',
    item: 'Feline Toxins to Steer Clear of This Kitten Season',
    url: 'https://www.aspca.org/news/feline-toxins-steer-clear-kitten-season',
    fetchedAt: '2026-10-13',
  },
  'aspca-flea-products': {
    org: 'ASPCA Animal Poison Control Center',
    item: 'Should You Fear the Flea?（跳蚤药与氯菊酯警示）',
    url: 'https://www.aspca.org/node/62440',
    fetchedAt: '2026-10-13',
  },
  'aspcapro-poison-tips': {
    org: 'ASPCApro',
    item: 'Poison Prevention Tips（家居危害清单）',
    url: 'https://www.aspcapro.org/sites/default/files/apcc-houshold-hazards.pdf',
    fetchedAt: '2026-10-13',
  },
}

/**
 * 种子表。排序：`banned` 在前、`caution` 在后；同类按 id 字典序，便于 diff。
 */
export const TOXIC_SUBSTANCES = [
  // ── banned：任何条件下都不得出现在猫配方中 ──────────────────────────────
  {
    id: 'allium',
    substance: '葱属植物（洋葱 / 大蒜 / 韭菜 / 葱）',
    latin: 'Allium spp.',
    aliases: ['洋葱', '洋葱粉', '大蒜', '大蒜粉', '蒜', '韭菜', '葱', '青葱', '红葱', 'allium', 'onion', 'garlic', 'chive', 'leek', 'shallot', 'scallion'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '葱属各部位（含干粉）可引起胃肠刺激并破坏红细胞，导致溶血性贫血；猫比犬更敏感。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'chocolate-cocoa',
    substance: '巧克力 / 可可制品',
    latin: 'Theobroma cacao',
    aliases: ['巧克力', '可可', '可可粉', '可可脂', '巧克力粉', 'chocolate', 'cocoa'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '可可含甲基黄嘌呤类生物碱，可致呕吐腹泻、心律异常、震颤、惊厥；可可含量越高风险越大。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'caffeine',
    substance: '咖啡因（含咖啡 / 茶叶 / 咖啡渣）',
    latin: '1,3,7-trimethylxanthine',
    aliases: ['咖啡因', '咖啡', '咖啡渣', '茶叶', '茶多酚咖啡因', 'caffeine', 'coffee', 'tea'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '与可可同属甲基黄嘌呤类，兴奋中枢与心脏，可致心动过速、震颤与惊厥。',
    sourceIds: ['aspca-people-foods', 'aspcapro-poison-tips'],
  },
  {
    id: 'grapes-raisins',
    substance: '葡萄 / 葡萄干',
    latin: 'Vitis vinifera',
    aliases: ['葡萄', '葡萄干', '葡萄渣', '提子', 'grape', 'raisin', 'currant'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '可致急性肾损伤乃至肾衰竭，毒性成分尚未完全确认（疑与酒石酸有关），个体差异大。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat', 'aspcapro-poison-tips'],
  },
  {
    id: 'xylitol',
    substance: '木糖醇',
    latin: null,
    aliases: ['木糖醇', 'xylitol', '桦木糖'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '促胰岛素释放致低血糖，并可进展为肝损伤/肝衰竭；多数物种敏感。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'ethanol',
    substance: '乙醇（酒精及含醇制品）',
    latin: 'ethanol',
    aliases: ['乙醇', '酒精', '酒', '白酒', '啤酒', '葡萄酒提取物', 'ethanol', 'alcohol'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '吸收快，抑制中枢，可致共济失调、呼吸抑制、代谢性酸中毒、昏迷甚至死亡。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'raw-yeast-dough',
    substance: '生酵母面团（活性酵母）',
    latin: null,
    aliases: ['生面团', '酵母面团', '活性干酵母', '鲜酵母', 'yeast dough', 'raw dough'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'food',
    basis: '面团在胃内继续发酵产气致胃扩张/扭转，并可生成乙醇产生继发酒精中毒。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'lilium',
    substance: '百合属 / 萱草属植物',
    latin: 'Lilium spp. / Hemerocallis spp.',
    aliases: ['百合', '百合花', '萱草', '黄花菜', 'lily', 'lilium', 'hemerocallis', 'daylily'],
    species: ['cat'],
    level: 'banned',
    conditions: null,
    category: 'plant',
    basis: '猫摄入任何部位（含花粉、插花水）即可致急性肾损伤；延迟治疗常致死。犬不敏感。',
    sourceIds: ['aspca-lilies', 'aspca-toxic-plants', 'aspca-feline-hazards'],
  },
  {
    id: 'sago-palm',
    substance: '苏铁 / 西米棕榈',
    latin: 'Cycas revoluta',
    aliases: ['苏铁', '西米棕榈', '铁树', 'cycad', 'sago palm'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'plant',
    basis: '全株有毒、种子毒性最高，可致严重胃肠反应、肝损伤、低血糖、凝血异常乃至惊厥死亡。',
    sourceIds: ['aspca-toxic-plants'],
  },
  {
    id: 'oleander',
    substance: '夹竹桃',
    latin: 'Nerium oleander',
    aliases: ['夹竹桃', 'oleander'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'plant',
    basis: '含强心苷，可致心律失常与低血压，症状可能延迟出现，前期多见呕吐腹泻。',
    sourceIds: ['aspca-toxic-plants'],
  },
  {
    id: 'autumn-crocus',
    substance: '秋水仙（秋番红花）',
    latin: 'Colchicum autumnale',
    aliases: ['秋水仙', '秋番红花', 'autumn crocus', 'colchicum'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'plant',
    basis: '含秋水仙碱，极小量即可致严重胃肠反应、心功能与肝肾功能损害、凝血与骨髓抑制。',
    sourceIds: ['aspca-toxic-plants'],
  },
  {
    id: 'castor-bean',
    substance: '蓖麻籽 / 蓖麻',
    latin: 'Ricinus communis',
    aliases: ['蓖麻', '蓖麻籽', '蓖麻油渣', '蓖麻粕', 'castor bean', 'ricinus'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'plant',
    basis: '含蓖麻毒素，可致肾衰竭、惊厥甚至死亡（蓖麻粕作饲料原料时尤须警觉）。',
    sourceIds: ['aspcapro-poison-tips'],
  },
  {
    id: 'acetaminophen',
    substance: '对乙酰氨基酚（扑热息痛）',
    latin: 'acetaminophen',
    aliases: ['对乙酰氨基酚', '扑热息痛', '泰诺', 'paracetamol', 'acetaminophen'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'drug',
    basis: '损伤红细胞携氧能力（高铁血红蛋白血症）并可致肝肾损伤；猫尤敏感，极小量即严重后果。',
    sourceIds: ['aspca-feline-hazards'],
  },
  {
    id: 'ibuprofen',
    substance: '布洛芬',
    latin: 'ibuprofen',
    aliases: ['布洛芬', 'ibuprofen'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'drug',
    basis: '非甾体抗炎药，可致呕吐腹泻、胃肠溃疡与肾损伤；猫剂量安全窗极窄。',
    sourceIds: ['aspca-feline-hazards'],
  },
  {
    id: 'naproxen',
    substance: '萘普生',
    latin: 'naproxen',
    aliases: ['萘普生', 'naproxen'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'drug',
    basis: '与布洛芬同类，胃肠溃疡与肾损伤风险显著；猫极敏感。',
    sourceIds: ['aspca-feline-hazards'],
  },
  {
    id: 'permethrin',
    substance: '氯菊酯（含高浓度犬用滴剂）',
    latin: 'permethrin',
    aliases: ['氯菊酯', '百灭宁', '除虫菊酯', '菊酯', 'permethrin', 'pyrethrin', 'pyrethroid'],
    species: ['cat'],
    level: 'banned',
    conditions: null,
    category: 'drug',
    basis: '猫缺乏葡萄糖醛酸转移酶、代谢能力差，接触高浓度犬用滴剂可致流涎、共济失调、震颤甚至惊厥死亡。犬按说明使用安全，故只标 cat。',
    sourceIds: ['aspca-flea-products', 'aspca-feline-hazards'],
  },
  {
    id: 'ethylene-glycol',
    substance: '乙二醇（防冻液）',
    latin: 'ethylene glycol',
    aliases: ['乙二醇', '防冻液', 'antifreeze', 'ethylene glycol'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'household',
    basis: '极少量即可致死，代谢产物致急性草酸钙性肾损伤。',
    sourceIds: ['aspcapro-poison-tips'],
  },
  {
    id: 'mothballs',
    substance: '樟脑丸（萘 / 对二氯苯）',
    latin: null,
    aliases: ['樟脑丸', '樟脑', '卫生球', '萘', '对二氯苯', 'mothball', 'naphthalene'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'household',
    basis: '可致呕吐、嗜睡、惊厥与溶血性贫血；小型动物摄入一颗即可能严重。',
    sourceIds: ['aspcapro-poison-tips'],
  },
  {
    id: 'anticoagulant-rodenticide',
    substance: '抗凝血类鼠药',
    latin: null,
    aliases: ['鼠药', '老鼠药', '灭鼠药', '抗凝血', '溴敌隆', '溴鼠灵', 'rodenticide', 'anticoagulant'],
    species: ['cat', 'dog'],
    level: 'banned',
    conditions: null,
    category: 'household',
    basis: '抑制维生素 K 循环致延迟性出血倾向，症状可在数日后才显现。',
    sourceIds: ['aspcapro-poison-tips'],
  },

  // ── caution：可用但必须限定条件 ────────────────────────────────────────
  {
    id: 'avocado',
    substance: '牛油果（鳄梨）',
    latin: 'Persea americana',
    aliases: ['牛油果', '鳄梨', 'avocado'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '猫犬对 persin 的敏感性低于鸟兔等物种，但果核、叶、皮应完全去除；果肉仅限少量且不作为配方主要油脂来源。',
    category: 'plant',
    basis: '全株含 persin，可致呕吐腹泻；果核另有梗阻风险。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'citrus-essential-oil',
    substance: '柑橘（果皮 / 叶 / 茎精油）',
    latin: 'Citrus spp.',
    aliases: ['柑橘', '橙皮', '柠檬皮', '柑橘精油', 'd-limonene', 'citrus', 'limonene'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '果肉少量通常仅致轻微胃肠不适；果皮、叶、茎及「浓缩精油」刺激性显著，配方中不得使用精油形态。',
    category: 'plant',
    basis: '含柠檬酸与挥发性精油，大量摄入可致刺激与中枢抑制。',
    sourceIds: ['aspca-people-foods', 'aspcapro-poison-tips'],
  },
  {
    id: 'dairy-lactose',
    substance: '乳制品（乳糖）',
    latin: null,
    aliases: ['牛奶', '全脂奶粉', '乳清粉', '脱脂奶粉', '奶酪', '乳糖', 'milk', 'lactose', 'dairy'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '乳糖酶活性随断奶下降，成年猫犬大量摄入易致腹泻；配方中乳制品上限应以不引起软便为准，必要时改用低乳糖乳制品。',
    category: 'food',
    basis: '成年猫犬乳糖酶不足，未消化乳糖在肠道发酵致腹泻等消化道不适。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'raw-meat-egg',
    substance: '生肉 / 生蛋（未熟制）',
    latin: null,
    aliases: ['生肉', '生鸡肉', '生蛋', '生鸡蛋', '生骨肉', 'raw meat', 'raw egg'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '存在沙门氏菌、大肠杆菌等微生物风险；生蛋清含抗生物素蛋白，会降低生物素吸收 —— 有蛋清的配方须充分加热灭活。',
    category: 'food',
    basis: '微生物污染风险；生蛋清的抗生物素蛋白影响 B 族维生素吸收，可致被毛与皮肤问题。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'sodium-chloride',
    substance: '食盐（钠）',
    latin: 'sodium chloride',
    aliases: ['食盐', '盐', '氯化钠', '钠盐', 'salt', 'sodium chloride'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '须在配方钠需求范围内使用；过量可致口渴多尿乃至钠离子中毒（呕吐、腹泻、震颤、体温升高、惊厥）。',
    category: 'food',
    basis: '大量摄入致高钠血症与神经系统症状。',
    sourceIds: ['aspcapro-never-eat'],
  },
  {
    id: 'tree-nuts',
    substance: '坚果（杏仁 / 碧根果 / 核桃等）',
    latin: null,
    aliases: ['杏仁', '碧根果', '核桃', '腰果', '坚果', 'almond', 'pecan', 'walnut', 'nut'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '高脂易致呕吐腹泻甚至胰腺炎；须严格限量或不使用。⚠ 澳洲坚果（macadamia）证据仅支持犬，本轮不收录为猫条目。',
    category: 'food',
    basis: '油脂与脂肪含量高，可诱发消化道症状与胰腺炎。',
    sourceIds: ['aspca-people-foods', 'aspcapro-never-eat'],
  },
  {
    id: 'coconut',
    substance: '椰子 / 椰子油',
    latin: 'Cocos nucifera',
    aliases: ['椰子', '椰子油', '椰蓉', 'coconut'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '少量通常无害；新鲜椰肉与椰奶的油脂可致胃部不适与软便，配方中须限量。',
    category: 'food',
    basis: '油脂含量高，可能引起胃肠不适与稀便。',
    sourceIds: ['aspca-people-foods'],
  },
  {
    id: 'tulip',
    substance: '郁金香（含球茎）',
    latin: 'Tulipa spp.',
    aliases: ['郁金香', 'tulip'],
    species: ['cat', 'dog'],
    level: 'caution',
    conditions: '球茎毒性最高；花叶可致胃肠不适与精神沉郁，大量球茎另有梗阻风险。',
    category: 'plant',
    basis: '含郁金香苷等刺激成分，可致明显胃肠反应。',
    sourceIds: ['aspca-toxic-plants'],
  },
]

/** 全部合法 `level` 值（判定四态中的前两态，另两态见 `toxicology.js`） */
export const TOXIC_LEVEL_VALUES = ['banned', 'caution']

/** 全部合法 `category` 值 */
export const TOXIC_CATEGORIES = ['food', 'plant', 'drug', 'household']
