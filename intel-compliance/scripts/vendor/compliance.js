// 宣称合规审查：在「一句话能不能这么说」这件事上，给出一份**可复核**的清单。
//
// ══════════════════════════════════════════════════════════════════════
// 这个模块的立场（决定了它的每一个设计取舍）
// ══════════════════════════════════════════════════════════════════════
// 它**不是**合规判定器，也不出「合规 / 不合规」的结论。
// 它只做一件事：把一句话里**可能踩线**的措辞挑出来，标明风险等级、**该去核对的条款**
// 与「为什么值得看一眼」，让人带着问题回去核对现行标准原文。理由很直接 ——
// 「允许不允许、限量多少、怎么标」的最终依据只能是一手法规文件
//（见 docs/taxonomy.md § 法规与合规：「必须盯一手文件，不接受二手解读作结论」）。
//
// 本轮的规则主要依据（一手文本）：农业农村部公告第 20 号《宠物饲料标签规定》第二十条
// （成分、功能、特性声称），以及《广告法》第九条 / 第二十一条 / 第二十八条 / 第五十八条。
// 逐条对照过程与处置结论见 docs/plan-v2.md。
//
// ══════════════════════════════════════════════════════════════════════
// 误报比漏报更伤（这一条是本模块最重要的工程约束）
// ══════════════════════════════════════════════════════════════════════
// 参考实现把 `促进` / `有助于` / `天然` 一律「命中即报」。那会产生什么问题：
//   ① `促进消化` / `有助于维持泌尿健康` 在宠物饲料标签语境下恰恰是**合规的弱化措辞**
//      （法规禁止的是疗效宣称，不是功能描述），把它标成 warn 是**系统性误报**；
//   ② 「宠物食品**不得**宣称疗效」这种讲合规的句子本身含「疗效」，
//      一律命中就报的规则会把它标成违规 —— 而它正是**正确**的表述；
//   ③ 一个「点一下就报三十条」的工具会被整体无视。
//      本项目在视觉回归的假红上吃过完全同形的亏（把环境限制伪装成代码缺陷），
//      结论是一样的：**噪声会让人连真问题一起忽略**。
//
// 所以本模块的默认值是**保守**：只报有把握的，宁可漏。
// 四层降噪机制：
//   ① 分句判定（`。！？；` 与换行）—— 语境是句子级的，跨句算命中没有意义；
//   ② 语境抑制：句中出现法条名、标准号、检测报告、具体数值、试验/文献、
//      以及否定/禁止表述、历史陈述、讲规矩的说明文时，说明这句话在**引用或否定**，
//      不是在做宣称 → 降级；
//   ③ `guard` 守卫：有些规则的成立条件是**「A 且非 B」**（例如「有试验词」**且**
//      「没写试验动物」），词表本身表达不了「非」，所以给规则留一个守卫函数；
//   ④ 与库内证据联动：宣称若在本库里已有 L1/L2 证据支撑，风险等级下调一档
//      （这正是把「合规审查」接进本系统的价值 —— 孤立词表给不出这个判断）。

import { levelOf, LEVEL_WEIGHT } from './schema.js';

/** 风险等级。数字只用于「降一档」的运算，不对外暴露。 */
export const COMPLIANCE_SEVERITY = { error: 3, warn: 2, info: 1 };
const RANK = { error: 3, warn: 2, info: 1 };
const RANK_NAME = { 3: 'error', 2: 'warn', 1: 'info' };
const downgrade = (sev) => RANK_NAME[Math.max(1, (RANK[sev] || 1) - 1)];

/** 第二十条（二）给出的、可接受的证明材料清单。多处复用，抽出来避免两处说法不一致。 */
const MATERIALS_NOTE = '第二十条（二）要求「所有声称应当具备证明材料」，可接受的包括：公开发表的出版物、教科书、配方组成、检测数据或者试验报告。';

/**
 * 规则表。每条规则都给出：
 *   · `clause`  —— **具体条款号**（如 `《宠物饲料标签规定》第二十条（三）3`）。
 *     为什么要精确到条：同类工具（如 TextComply）把「带出对应法规」做成核心能力，
 *     而只写「标签与宣称合规」这五个字，使用者拿着它还得在两万字的法规原文里自己找。
 *   · `docRef`  —— 该去哪一类文件里核对（对齐 docs/taxonomy.md § 法规与合规 的细项名，
 *     不另建一套法规库；否则「词表说查这里、分类法说查那里」迟早对不上）
 *   · `reason`  —— 为什么它值得看一眼（不是「违反了第 X 条」，那需要看原文）。
 *     有法定数值门槛的（26% / 14% / 4% / ≥15% / 低脂肪低能量 / 18 个月）**直接把数字写进来** ——
 *     这个模块现在的短板不是覆盖面，是「可核对性」：它告诉人「这句话值得看」，
 *     却没告诉人「去看什么数」。
 *   · `guard`   —— 可选。成立条件为「命中 patterns **且** guard 为真」时才会报。
 */
export const COMPLIANCE_RULES = [
  /* ─────────────── 一、绝对化用语与唯一性用语（《广告法》第九条） ─────────────── */
  {
    code: 'ABSOLUTE_TERM',
    severity: 'error',
    label: '绝对化用语',
    clause: '《广告法》第九条（三）',
    docRef: '标签与宣称合规',
    reason: '禁止「国家级 / 最高级 / 最佳」这类绝对化用语。此处刻意不收「最新」——「最新研究」是中性表述，一律命中会把正常内容打成违规。',
    patterns: [/最好(?:的)?/g, /最佳/g, /最优(?:秀|质)?/g, /最先进/g, /最顶级|顶级的?/g, /最高级/g, /最强/g, /最有效/g, /最安全/g, /最健康/g, /独一无二/g, /全国第一|世界第一|行业第一/g, /国家级/g, /100%/g, /百分百/g, /绝对安全/g],
  },
  {
    code: 'ABSOLUTE_UNIQUENESS',
    severity: 'error',
    label: '唯一性用语',
    clause: '《广告法》第九条（三）· 表示唯一性',
    docRef: '标签与宣称合规',
    reason: '「首个 / 首款 / 首家 / 首创 / 独家配方 / 唯一之选」属表示**唯一性**的绝对化用语，同被《广告法》第九条禁止。有真实案例可依：上海某宠物粮因「国内首款：烘焙粮」被认定违反绝对化用语。注意：**「首创于 1962 年」这类历史陈述不受此限**，已由「历史陈述」抑制降级。',
    patterns: [/首(?:款|个|家|创)/g, /独家(?:配方|技术|工艺|代理|拥有|授权|生产|供应|首发)/g, /唯一(?:一家|之选|选择|指定|授权|配方|来源|产地|供应商)/g, /仅此一家|独此一家/g, /全(?:球|国)独创/g],
  },

  /* ─────────────── 二、疗效 / 医疗宣称（第二十条（一）） ─────────────── */
  {
    code: 'THERAPEUTIC_CLAIM',
    severity: 'error',
    label: '疗效 / 医疗宣称',
    clause: '《宠物饲料标签规定》第二十条（一）',
    docRef: '标签与宣称合规',
    reason: '第二十条（一）：禁止对宠物饲料作具有**预防或者治疗宠物疾病**的说明或者宣传。宠物饲料不是兽药，这是本项目里最硬的一条红线。「增强免疫力 / 抗病 / 消炎 / 清火」属**医学用语** —— 判据不是措辞强度，而是语义指向是不是疾病或医学功能，所以它们也收在这一档，而不是「强功能宣称」。下列词均来自真实处罚决定书：`清火 / 下火`（渝大渡口市监处罚〔2025〕270 号「清火淡泪痕」）、`增强免疫力`（上海某宠物粮案）。',
    patterns: [/治疗/g, /治愈/g, /根治/g, /药效/g, /疗效/g, /药用/g, /处方药/g, /替代(?:药物|用药)/g, /不用吃药|无需用药/g, /防治(?:疾病)?/g, /抗癌|抗肿瘤/g, /杀菌消毒/g, /(?:增强|提高|提升|强化|增加|调节)?\s*免疫(?:力|功能)/g, /增免疫/g, /抗病(?:毒)?/g, /抗病毒/g, /消炎|抗炎|炎症|发炎/g, /清火|去火|降火|下火/g],
  },
  {
    code: 'CURE_DISEASE_SPECIFIC',
    severity: 'warn',
    label: '指向具体疾病的表述',
    clause: '《宠物饲料标签规定》第二十条（一）',
    docRef: '标签与宣称合规',
    reason: '把功能指向具体疾病名（肾衰、结石、糖尿病…）时，实际已构成疾病治疗/预防宣称。是否允许取决于产品属性（处方粮有单独的准入与标识要求，见第十二条：须标示适用状态与「请在执业兽医指导下使用」），必须回去核对。',
    patterns: [/肾衰|肾功能不(?:全|佳)/g, /结石|尿结石|膀胱结石/g, /糖尿病/g, /关节(?:炎|病)/g, /皮肤病/g, /心脏病|心脏(?:健康|功能)/g, /肝(?:病|衰竭)/g, /肥胖症/g, /过敏(?:性皮炎)?/g, /泪痕/g, /视网膜(?:功能|健康)?|视力(?:保护|健康)?/g],
  },

  /* ─────────────── 三、安全性断言（《广告法》第二十一条第一款） ─────────────── */
  {
    code: 'SAFETY_ASSERTION',
    severity: 'error',
    label: '安全性断言',
    clause: '《广告法》第二十一条第一款',
    docRef: '标签与宣称合规',
    reason: '第二十一条第一款：农药、兽药、**饲料和饲料添加剂**广告不得含有表示功效、安全性的**断言或者保证**（罚则见第五十八条第一款第四项：责令停止发布、消除影响，并处十万元以上二十万元以下罚款）。「不伤胃 / 不呕吐 / 完全无害 / 可长期食用」是对安全性下断言而非描述，有真实案例可依 —— 湘潭县市监处罚〔2026〕111 号即因「不肥胖、不伤胃、不呕吐、更容易消化」被罚。',
    patterns: [/不伤(?:肝|肾|胃|肠|眼|身|毛)/g, /不(?:呕吐|腹泻|拉稀|软便|肥胖|发胖)/g, /无毒无害|安全无毒|完全无害|无(?:任何)?(?:毒)?副作用|零风险/g, /(?:可以?|能够?)(?:长期|放心|安全)(?:食用|吃|喂养|使用)/g, /(?:不会|不产生)(?:耐药|依赖性)/g, /放心(?:食用|吃|喂养)/g],
  },

  /* ─────────────── 四、功能声称（第二十条 首句 + （二）） ─────────────── */
  {
    code: 'FUNCTION_CLAIM_STRONG',
    severity: 'warn',
    label: '强功能宣称',
    clause: '《宠物饲料标签规定》第二十条（二）',
    docRef: '标签与宣称合规',
    reason: '第二十条允许作功能声称，但（二）要求**所有声称应当具备证明材料**。这类表述本身不必然违规，却已从「描述成分」跨到「承诺效果」，且不得与「预防/治疗疾病」的边界模糊 —— 需要一并核对**依据**与措辞强度。注意 `促进` / `有助于` **刻意不收**：它们在宠物饲料语境下是合规的弱化措辞，收了就是系统性误报。`增肥 / 发腮 / 壮骨` 出自玛纳斯县市监处罚〔2026〕61 号（「增肥发腮」，被认定存在主观故意）。',
    patterns: [/预防/g, /缓解/g, /改善/g, /消除/g, /抑制|抑菌/g, /除螨|驱虫/g, /排毛|化毛/g, /美毛|靓毛/g, /护(?:肾|肝|肠|胃|关节|毛)/g, /去泪痕/g, /除口臭/g, /抗(?:氧化|衰老)/g, /增肥|发腮|壮骨|催肥/g],
  },

  /* ─────────────── 五、成分声称（第二十条（三）） ─────────────── */
  {
    code: 'INGREDIENT_CLAIM_RATIO',
    severity: 'warn',
    label: '原料 / 成分声称（有法定含量门槛）',
    clause: '《宠物饲料标签规定》第二十条（三）3',
    docRef: '标签与宣称合规',
    reason: '成分声称有**硬性含量门槛**：「××配方」要求该原料达产品总重的 **26% 以上**；「含××配方」要求 **14% 以上**；「含××」要求 **4% 以上**。组合声称时至少一种达到上述比例、**其余每种均需达 3% 以上**，并按重量百分比**降序排列**。经脱水处理的原料可依**水分还原后**的含量计算（附录 7；若还原，附录 7 涉及的三类原料应同时还原）。请回到配方组成核对 —— 本系统的 L1 档「配方组成」正是法定可接受的证明材料之一。',
    patterns: [/配方/g],
  },
  {
    code: 'NUTRIENT_CLAIM',
    severity: 'info',
    label: '营养素 / 添加剂声称',
    clause: '《宠物饲料标签规定》第二十条（三）6',
    docRef: '标签与宣称合规',
    reason: '第二十条（三）6：声称某营养素或饲料添加剂可赋予产品特有属性时，应使用「含××」字样；**营养素应在产品成分分析保证值中列示**，**饲料添加剂应在添加剂组成中列示并标示其添加量**。只写「含 DHA」「添加益生菌」而不在相应位置列示，是不符合本条的形式。',
    patterns: [/(?:含|含有|添加|添加了|富含|特别添加)\s*(?:维生素[A-Z]?|矿物质|微量元素|氨基酸|牛磺酸|卵磷脂|DHA|EPA|Omega|欧米伽|Ω|益生菌|益生元|膳食纤维|葡萄糖胺|氨基葡萄糖|软骨素|酶制剂)/gi],
  },
  {
    code: 'NO_SUBSTANCE_CLAIM',
    severity: 'warn',
    label: '「无×× / 不含××」声称',
    clause: '《宠物饲料标签规定》第二十条（三）7',
    docRef: '标签与宣称合规',
    reason: '第二十条（三）7 的适用范围是**封闭的**：只可以对**饲料原料**或**饲料添加剂**作不含有声称（用「无××」或「不含××」），**除这两类外，不得对其他任何物质进行不含有声称**。因此「不含激素」「0 添加」「无化学添加」在形式上就不成立（激素、化学添加既不是原料也不是添加剂）。唯一例外：麸质含量 **≤20 mg/kg** 时可称「无麸质 / 不含麸质」。',
    patterns: [/(?:无|不含|零|0)\s*(?:激素|抗生素|药物|化学成分?|色素|香精|诱食剂|防腐剂|添加剂|转基因|谷物|谷|麸质)/g, /(?:0|零)\s*添加/g],
  },
  {
    code: 'ADDED_RATIO_REQUIRED',
    severity: 'info',
    label: '声称原料需标注添加量',
    clause: '《宠物饲料标签规定》第二十条（三）1、5',
    docRef: '标签与宣称合规',
    reason: '第二十条（三）1：声称使用某种饲料原料时，应当在**原料组成**中标示其名称，并**在名称后标示其添加量**（用类别名称标示的，须在类别名称后以括号标明品种名称及添加量）。第 5 项：添加量虽未达 4%、但足以赋予产品某种特有属性时，可用「添加××」声称。此处只提示「有强调、请自查是否标了添加量」。',
    patterns: [/特别添加/g, /精选/g, /足量添加/g, /添加了?/g, /含有/g, /富含/g],
  },
  {
    code: 'COMPARATIVE_CLAIM',
    severity: 'info',
    label: '泛化比较表述',
    clause: '《广告法》第二十八条（虚假广告）',
    docRef: '标签与宣称合规',
    reason: '「更好 / 更优 / 优于 / 胜过」没有可比对的量，容易被认定为缺乏依据的贬褒性表述（并可能贬低同类产品）。列出来供自查。带具体增减百分比的比较声称另有硬性要求，见「含量增减比较声称」一条。`更容易消化` 出自湘潭县市监处罚〔2026〕111 号。',
    patterns: [/更好/g, /更优/g, /更健康/g, /优于/g, /胜过/g, /远超/g, /高于(?:同类|行业|标准)/g, /更容易(?:吸收|消化)?/g],
  },
  {
    code: 'COMPARATIVE_RATIO_REQUIRED',
    severity: 'warn',
    label: '含量增减比较声称',
    clause: '《宠物饲料标签规定》第二十条（三）8',
    docRef: '标签与宣称合规',
    reason: '第二十条（三）8 对含量比较声称设了**三个硬条件**：① **以本企业的产品作为参照物且明确列示**（不得拿别人的产品作参照）；② 增高或降低的比例应达 **15% 以上**；③ 对**常量营养素**，该百分比还应**能够通过配方进行验证**。「比市面优质尿垫增加 3 倍以上」这类既没有本企业参照物、也无配方可验证的表述是最典型的不符合项。',
    patterns: [/(?:高|增高|提高|提升|低|降低|减少|增加)\s*(?:了)?\s*\d+(?:\.\d+)?\s*(?:%|个百分点|倍)/g, /(?:比|较)\s*(?:市面|同类|其他|普通|常用|传统|竞品)[^\s，。；]{0,10}/g],
    // 这条规则的命中**必然**含数字（要求比例 ≥15%），不豁免就会被永久降级。
    ignoreDampeners: ['NUMERIC_BASIS'],
  },

  /* ─────────────── 六、特性声称（第二十条（四）） ─────────────── */
  {
    code: 'NATURAL_CLAIM',
    severity: 'warn',
    label: '「天然」声称',
    clause: '《宠物饲料标签规定》第二十条（四）1、2',
    docRef: '标签与宣称合规',
    reason: '「天然」不是营销形容词，是一条**有严格工艺条件的规则**：要求产品使用的**所有**饲料原料与添加剂均来自「未经加工、非化学工艺加工，或只经物理加工、热加工、提取、纯化、水解、酶解、发酵或烟熏」处理的植物、动物或矿物质微量元素。若添加了**化学合成**的维生素、氨基酸、矿物质微量元素，**仍可**声称天然，但**必须同时标示**这些物质并使用「**天然粮，添加××**」字样。另有形式要求：所有声称文字须置于同一展示版面、同字体字号颜色、中间不得插入其他内容、不得突出某一部分。提醒：鱼油虽为天然来源，但经精炼（属允许工艺之一）能否满足这里的条件需逐项核对，不能仅凭「天然来源」推定。',
    patterns: [/天然(?!的?味)/g],
  },
  {
    code: 'FRESH_CLAIM',
    severity: 'warn',
    label: '「新鲜 / 鲜」声称',
    clause: '《宠物饲料标签规定》第二十条（四）3',
    docRef: '标签与宣称合规',
    reason: '「新鲜」同样有法定条件：该饲料原料除**冷藏**外未经**蒸煮、干燥、冷冻、水解**等任何处理过程，**且不含有氯化钠、防腐剂或者其他饲料添加剂**。这三项要同时满足，且对原料的仓储与运输（冷藏链）有现实要求 —— 处置方式不是「换个说法」，而是回去核对这批原料的工艺与贮运条件。',
    patterns: [/(?:新鲜|鲜肉|鲜肉源|鲜粮|鲜鸡|鲜牛|鲜鱼|鲜鸭|鲜虾)/g],
  },
  {
    code: 'LOW_FAT_LOW_ENERGY_CLAIM',
    severity: 'warn',
    label: '「低脂肪 / 低能量」声称',
    clause: '《宠物饲料标签规定》第二十条（四）4、5',
    docRef: '标签与宣称合规',
    reason: '这两项有**可直接比对的法定数值**（按犬/猫与水分含量分档）——「低脂肪」：犬 水分<20% 且脂肪 ≤9%、水分 20%~65% 且 ≤7%、水分>65% 且 ≤4%；猫 水分<20% 且 ≤10%、20%~65% 且 ≤8%、>65% 且 ≤5%。「低能量」：犬 水分<20% 且 ≤1296 kJ ME/100g、20%~65% 且 ≤1045、≥65% 且 ≤376；猫 水分<20% 且 ≤1359、20%~65% 且 ≤1108、≥65% 且 ≤397。作低能量声称时还须以「能量」或「能量值」为引导词、置于同一展示版面、以代谢能（ME）值表示并在值后括号注明「计算值」。请直接拿成分分析保证值来比。',
    patterns: [/(?:低脂肪|低脂|低能量|低卡|低热量)/g],
  },
  {
    code: 'PRODUCT_UPGRADE_CLAIM',
    severity: 'info',
    label: '「新产品 / 升级」声称',
    clause: '《宠物饲料标签规定》第二十条（四）6',
    docRef: '标签与宣称合规',
    reason: '第二十条（四）6 允许使用「新产品」「配方升级」「产品升级」或类似声称，但设了**两个条件**：① 声称应当有**充分证据**；② 该声称**在产品标签上标示的时间不得超过 18 个月**。也就是说这是一条有时效的声称，包装改版时要一并核。',
    patterns: [/(?:新产品|配方升级|产品升级|全新升级|全新配方|新配方)/g],
  },
  {
    code: 'FOREIGN_STANDARD_CLAIM',
    severity: 'info',
    label: '符合国外标准的声称',
    clause: '《宠物饲料标签规定》第二十条（四）7',
    docRef: '标签与宣称合规',
    reason: '第二十条（四）7：声称符合国际或国外标准时，产品应当符合**该标准的所有要求**（注意「所有」——不能只挑满足的那几项），且在监管部门要求时能够提供**检测报告或者产品配方**等证明材料。行业里常见「符合 AAFCO / FEDIAF」，这类声称需要第三方符合性检测报告兜底。',
    patterns: [/(?:AAFCO|FEDIAF|欧盟标准|美国标准|日本标准|符合国际标准|符合国外标准)/gi],
    // 这条规则的命中**必然**点名某个标准，不豁免就会被「引用了法规或标准」恒久降级，
    // 并且每张卡片上都会挂一条**误导性**的抑制依据（它并不是在引用标准讲合规，而是在做声称）。
    ignoreDampeners: ['STANDARD_REF'],
  },

  /* ─────────────── 七、有法定定义的用语（第五条 / 第十二条） ─────────────── */
  {
    code: 'LEGAL_DEFINITION_TERM',
    severity: 'warn',
    label: '有法定定义的用语',
    clause: '《宠物饲料标签规定》第五条、第十二条',
    docRef: '标签与宣称合规',
    reason: '「全价」「处方」在标准里是**通用名称**（第五条第（一）项明确列出「宠物配合饲料 / 宠物全价饲料 / 全价宠物食品 / 全价」的法定写法，并要求标示适用动物种类与生命阶段）。「处方」还要另加第十二条的两项要求：注明适用的生理 / 病理状态与主要营养特征，并在醒目位置标示「请在执业兽医指导下使用」，且需备有能验证产品效果的科学试验数据及配方组成。这些不是营销形容词，用错不是措辞问题而是**标示合规问题**。「低敏 / 人食级 / 医用级」在现行标准里没有统一定义（「有机」另有认证要求），无定义就无从核对，同样需要回去确认。',
    patterns: [/全价/g, /处方(?:粮|食品|罐|湿粮)?/g, /低敏|低过敏/g, /人食级|人类食用级|医用级/g, /有机(?:认证)?/g],
  },

  /* ─────────────── 八、证据本身的要求（第二十条（二）） ─────────────── */
  {
    code: 'EVIDENCE_SPECIES',
    severity: 'info',
    label: '证据的试验动物',
    clause: '《宠物饲料标签规定》第二十条（二）',
    docRef: '标签与宣称合规',
    reason: `${MATERIALS_NOTE} 本条与「是犬猫还是别的动物」直接相关：**以犬猫为试验动物**的试验报告，对本产品才有直接证明力；用大鼠做的抗氧化试验、或体外细胞试验，只能作为机制线索，不能直接支撑一条面向犬猫产品的功能声称。这条只在句中**没有**出现犬/猫/狗/宠物时提示 —— 已经写明试验动物的句子不构成缺口，再报就是噪声。`,
    patterns: [/试验|实验|研究(?:表明|显示|发现)|文献|数据显示|临床/g],
    // 「有试验词」**且**「没写试验动物」才提示。词表表达不了「非」，所以用守卫。
    guard: (s) => !/(?:犬|猫|狗|幼犬|幼猫|宠物)/.test(s),
  },

  /* ─────────────── 九、无定义的模糊褒义表述 ─────────────── */
  {
    code: 'VAGUE_QUALITY_WORD',
    severity: 'info',
    label: '模糊褒义表述',
    clause: '《广告法》第二十八条（虚假广告）',
    docRef: '标签与宣称合规',
    reason: '「优质」「甄选」「高端」这类词没有可核对的定义，容易被认定为缺乏依据的贬褒性表述；`神器` 一类夸饰词在真实处罚决定书里也被一并认定（湘潭县市监处罚〔2026〕111 号：「下火神器」）。列出来供权衡。',
    patterns: [/优质/g, /甄选/g, /顶级原料/g, /高端/g, /旗舰/g, /神器/g],
  },
];

/**
 * 语境抑制特征。句中出现任一者，说明这句话**在引用、在否定、在讲历史、或在讲规矩**，
 * 而不是在做宣称 —— 该句的风险等级下调一档。
 *
 * 为什么必须有它：讲合规的文章会成片命中自己讲的那些词。
 * 「宠物食品不得宣称疗效」若被报成「疗效宣称」，这个工具第一天就会失去信任。
 */
const CONTEXT_DAMPENERS = [
  { code: 'NEGATION', label: '否定 / 禁止语境', re: /不得|禁止|不允许|不能|不可(?:以)?宣称|禁用|剔除|避免使用|切勿|违规|违法|处罚|罚款|下架|召回|拆除|整改/ },
  { code: 'STANDARD_REF', label: '引用了法规或标准', re: /《[^》]{2,40}》|GB\s*\/?\s*T?\s*\d+|NY\s*\/\s*T\s*\d+|农业农村部|市场监管总局|公告(?:第)?\s*\d*\s*号|Regulation\s*\(?EU\)?\s*\d+|AAFCO|FEDIAF/ },
  { code: 'EVIDENCE_REF', label: '引用了检测或试验', re: /检测报告|检验报告|第三方检测|实测|检出|化验|试验|实验|研究(?:表明|显示|发现)|文献|数据显示|临床/ },
  { code: 'NUMERIC_BASIS', label: '给出了具体数值', re: /\d+(?:\.\d+)?\s*(?:%|‰|mg|μg|g\/kg|mg\/kg|IU|CFU|kcal|kJ|克|毫克|千克)/ },
  { code: 'QUOTED', label: '处于引述之中', re: /[「『"“][^」』"”]{1,60}[」』"”]|所谓|声称|宣称(?:说|称)|某品牌|有人认为/ },
  // 「首创于 1962 年」「已有一百多年历史」是在**陈述历史**，不是在做唯一性宣称。
  // 少了这一条，「1962 年首创的挤压工艺」会被判成绝对化用语 —— 那是纯误报。
  { code: 'HISTORICAL', label: '历史陈述', re: /(?:19|20)\d{2}\s*年|上世纪|起源于|历史悠久|由来已久|自\s*(?:19|20)\d{2}/ },
  // 「本规定第二十条」「见附录 7」「示例如下」是在**讲规矩**，不是在宣称。
  // 合规类文章里这类句子极多，不抑制会把整份文件报满。
  { code: 'GUIDE_DOC', label: '讲规则的说明文', re: /本(?:规定|办法|标准|条件|条|款|项)|第[一二三四五六七八九十百\d]+条|附录\s*\d|示例见|参见|详见|如下所示/ },
];

/** 对外只暴露标签（口径页要把它摊开给人看，但没必要把正则也发出去）。 */
export const CONTEXT_DAMPENER_LABELS = CONTEXT_DAMPENERS.map((d) => ({ code: d.code, label: d.label }));

/* ══════════════════════════════════════════════════════════════════════
 * 第二十条（五）功能声称：**允许侧**的正向通道
 * ══════════════════════════════════════════════════════════════════════
 * 上面的规则表只覆盖「违反侧」—— 命中一个措辞就报风险等级。它有一块结构性空白：
 * 第二十条是「**允许 + 附条件**」的立法结构，而（五）是其中唯一的**正向授权**。
 * 研发日常最常问的恰恰是「我这么写行不行」，现有实现回答不了这个问题。
 *
 * 这不是「少报了一条风险」，而是**整类声称不在检查范围内，而且界面上不说**：
 * 拿一段「本品有助于减少毛球形成」跑完审查，得到「无命中」，会被读成「没问题」，
 * 实际含义是「系统根本没看这一类」。这与本项目其它地方的纪律正好相反 ——
 * 候选池对「无摘要」如实标注、`/api/discover` 对「没核」不升成「已核验」、
 * 「抓到了 HTML ≠ 抓到了文章」。同一套诚实标准，在（五）这里是缺的一块。
 *
 * ⚠ 这一段的立场与风险规则表**完全一致**：只给条款号、措辞档位与材料类型，
 * 绝不替人下「这条合规」的结论 —— 判定权在现行法规原文。
 */
export const FUNCTION_CLAIM_CHANNEL = {
  clause: '《宠物饲料标签规定》第二十条（五）',
  docRef: '标签与宣称合规',
  basis: '《宠物饲料标签规定》第二十条（五）1、2 条文原文；以及北京市农业农村局 2022-06-28 对「宠物饲料标签可否标注健康类字样」的官方答复（该答复逐字引用了（五）1、2 两句）。',
  /**
   * 两条**并列**的授权，成立条件完全不同，混为一谈是本类问题最常见的错法：
   * 前者只覆盖「描述功能」，后者才额外授权「预防」这个字样。
   */
  grants: [
    {
      id: 'health-function',
      label: '维持 / 增强生长、发育、生理功能或机体健康',
      clause: '《宠物饲料标签规定》第二十条（五）首句、1',
      allowsPreventWord: false,
      requirement: '声称涉及的**饲料添加剂**应在「添加剂组成」或「产品成分分析保证值」中按本规定要求标示；声称涉及的**饲料原料**应在「原料组成」中标示其名称，**并在名称后标示其添加量**。',
      example: '「含菊苣根粉促进肠道有益菌增殖」「含钙促进骨骼发育」',
    },
    {
      id: 'non-disease-prevention',
      label: '预防非疾病性问题',
      clause: '《宠物饲料标签规定》第二十条（五）2',
      allowsPreventWord: true,
      requirement: '**仅限非疾病性**问题；且只对（五）2 所列的问题开放「预防」字样（完整清单示例见《规定》附录 1）。',
      example: '「预防毛球产生」「预防牙垢积聚」',
    },
  ],
  /**
   * ⚠ 只收**条文原文点名**的两项。
   * 附录 1 的完整清单不在本系统内 —— 多收一项就是替法规做了一次判定，那是本模块
   * 从一开始就拒绝做的事（见文件头的立场声明）。
   */
  nonDiseaseAppeals: [
    { id: 'hairball', label: '毛球产生', clause: '《宠物饲料标签规定》第二十条（五）2', terms: ['毛球', '排毛', '化毛', '吐毛'], origin: '条文原文点名' },
    { id: 'tartar', label: '牙垢积聚', clause: '《宠物饲料标签规定》第二十条（五）2', terms: ['牙垢', '牙菌斑'], origin: '条文原文点名' },
  ],
  /** 措辞档位。由该原料在**产品总重**中的占比决定 —— 这是（三）3 的硬性门槛。 */
  wordingTiers: [
    { id: 't26', min: 26, word: '「××配方」', clause: '《宠物饲料标签规定》第二十条（三）3', note: '该原料须达产品总重的 **26% 以上**' },
    { id: 't14', min: 14, word: '「含××配方」', clause: '《宠物饲料标签规定》第二十条（三）3', note: '**14% 以上**' },
    { id: 't4', min: 4, word: '「含××」', clause: '《宠物饲料标签规定》第二十条（三）3', note: '**4% 以上**' },
    { id: 'tadd', min: 0, word: '「添加××」', clause: '《宠物饲料标签规定》第二十条（三）5', note: '未达 4%、但**足以赋予产品某种特有属性**时可用（这一档没有比例门槛，但需要能说明该特有属性）' },
  ],
  wordingRules: {
    combination: '组合声称（「A+B 配方」这类）：至少一种达到上表比例，**其余每种均需达 3% 以上**，并按重量百分比**降序排列**。',
    rehydrate: '经脱水处理的原料可依**水分还原后**的含量计算（《规定》附录 7；若还原，附录 7 涉及的三类原料应同时还原）。',
  },
  /**
   * （二）给出的、**封闭列举**的证明材料类型。每次判定都带上这一清单：
   * 「库里没有」与「法律要求你有」是两件事，只说前一件等于把法定义务说成了盘点结果。
   */
  materials: [
    { id: 'publication', label: '公开发表的出版物', inSystem: '库内可检索（L2 同行评议）' },
    { id: 'textbook', label: '教科书', inSystem: '需自备' },
    { id: 'formula', label: '配方组成', inSystem: '本系统 L1 档可直接生成' },
    { id: 'testdata', label: '检测数据', inSystem: '需自备' },
    { id: 'trialreport', label: '试验报告', inSystem: '需自备', note: '面向犬猫的功能声称，以**犬猫为试验动物**的报告才有直接证明力' },
  ],
  /** 形式要求。与风险规则表里的理由同源，不复写第二套说法。 */
  formRequirements: [
    { clause: '《宠物饲料标签规定》第二十条（五）1', text: '声称涉及的饲料添加剂 → 在「添加剂组成」或「产品成分分析保证值」中标示；声称涉及的饲料原料 → 在「原料组成」中标示名称**并在名称后标示其添加量**。' },
    { clause: '《宠物饲料标签规定》第二十条（二）', text: '所有声称应当具备证明材料（类型见上）。' },
  ],
  appendixNote: '《规定》第二十条（五）1、2 两处都写「示例见《规定》附录 1」。**附录 1 的完整清单不在本系统内** —— 除条文点名的「毛球产生」「牙垢积聚」之外，还有哪些属于「等**非疾病性问题**」，必须回附录 1 原文与官方解读核对，本系统不代为判定。',
  disclaimer: '本通道只给条款号、措辞档位与材料类型，**不构成合规认定**；判定权在现行法规原文。',
};

/** 按占比算出措辞档位。占比没给就不给档位 —— 宁可说不出来，也不猜一个写法。 */
export function wordingFor(ratio) {
  const r = Number(ratio);
  if (!Number.isFinite(r) || r <= 0) return null;
  const tier = FUNCTION_CLAIM_CHANNEL.wordingTiers.find((t) => r >= t.min);
  if (!tier) return null;
  return {
    ratio: r,
    tier: tier.id,
    word: tier.word,
    clause: tier.clause,
    note: tier.note,
    combination: FUNCTION_CLAIM_CHANNEL.wordingRules.combination,
    rehydrate: FUNCTION_CLAIM_CHANNEL.wordingRules.rehydrate,
  };
}

/**
 * 疾病 / 医学功能那一侧的判定**复用风险规则表的词，不另抄一份**。
 * 两处各写一遍的代价不是代码重复，而是**两份清单迟早对不上** ——
 * 那时「风险规则说这是疾病」「正向通道说这可以预防」会同时出现在一张页面上。
 */
const DISEASE_RULE_CODES = ['THERAPEUTIC_CLAIM', 'CURE_DISEASE_SPECIFIC'];

function diseaseHitIn(text) {
  const s = String(text || '');
  for (const code of DISEASE_RULE_CODES) {
    const rule = COMPLIANCE_RULES.find((r) => r.code === code);
    if (!rule) continue;
    for (const re of rule.patterns) {
      // ⚠ 这些正则带 `g`，是**有状态**的模块级对象。取词之前先归零，
      //    取完再归零 —— 否则下一次调用会从上次的位置继续扫，前半句静默漏掉。
      re.lastIndex = 0;
      const m = re.exec(s);
      re.lastIndex = 0;
      if (m) return { term: m[0], code, label: rule.label, clause: rule.clause };
    }
  }
  return null;
}

/** 出现这些词，说明这句话在**描述功能**，而不只是在陈述一个词。用于决定要不要报。 */
const FUNCTION_VERB = /预防|防止|有助于|促进|维护|维持|改善|缓解|减少|降低|抑制|增强|提高|保护/;

/**
 * 判定一条功能声称诉求的可声称性。
 *
 * @param {{ appeal?: string, text?: string, ingredient?: string, ratio?: number }} input
 *        `appeal` 诉求（如「排毛」「预防毛球形成」「预防尿结石」）；
 *        `ingredient` 要声称的原料（可选，只用于回显）；
 *        `ratio` 该原料在产品总重中的占比（百分比数值，可选 —— 不给就不给措辞档位）
 * @returns 结构化结论。`verdict` 四取一：
 *   · `no-input`          没给诉求
 *   · `red-line`          指向疾病 / 医学功能 → 第二十条（一），**不能**靠（五）2 绕过去
 *   · `prevention-allowed` 命中（五）2 **条文点名**的非疾病性问题 → 可用「预防」字样
 *   · `check-appendix`    两者都不是 → 可作功能声称，但「预防」的授权范围要回附录 1 核对
 */
export function assessFunctionClaim(input = {}) {
  const appeal = String(input?.appeal ?? input?.text ?? '').replace(/\s+/g, ' ').trim();
  const ingredient = String(input?.ingredient ?? '').replace(/\s+/g, ' ').trim();
  const ratioNum = input?.ratio === '' || input?.ratio == null ? NaN : Number(input.ratio);
  const wording = wordingFor(ratioNum);

  const base = {
    channelClause: FUNCTION_CLAIM_CHANNEL.clause,
    docRef: FUNCTION_CLAIM_CHANNEL.docRef,
    appeal,
    ingredient,
    wording,
    wordingNote: wording ? ''
      : '未给出该原料在产品总重中的占比 —— 措辞档位（26% / 14% / 4% / 添加××）由占比决定，给一个 ratio（百分比数值）才能落到具体写法。',
    materials: FUNCTION_CLAIM_CHANNEL.materials,
    form: FUNCTION_CLAIM_CHANNEL.formRequirements,
    grants: FUNCTION_CLAIM_CHANNEL.grants,
    appendixNote: FUNCTION_CLAIM_CHANNEL.appendixNote,
    disclaimer: FUNCTION_CLAIM_CHANNEL.disclaimer,
  };

  if (!appeal) {
    return { ...base, verdict: 'no-input', kind: '', matched: null, diseaseHit: null, allowsPreventWord: null, note: '没有给出要判断的诉求。' };
  }

  // ① 疾病侧优先判。两侧同时命中时**按红线处理** —— 保守方向永远是「先别写」。
  const diseaseHit = diseaseHitIn(appeal);
  if (diseaseHit) {
    return {
      ...base,
      verdict: 'red-line',
      kind: 'disease',
      matched: null,
      diseaseHit,
      allowsPreventWord: false,
      note: `诉求里出现了指向**疾病 / 医学功能**的表述（${diseaseHit.term}），落在第二十条（一）：禁止对宠物饲料作具有预防或者治疗宠物疾病的说明或者宣传。这一档**不能**靠（五）2 的「预防」授权绕过去 —— 「预防」字样只对（五）2 所列的**非疾病性**问题开放。`,
    };
  }

  // ② 条文点名的非疾病性问题 → 这才是「预防」被明文授权的那一类。
  const listed = FUNCTION_CLAIM_CHANNEL.nonDiseaseAppeals.find((a) => a.terms.some((t) => appeal.includes(t)));
  if (listed) {
    const term = listed.terms.find((t) => appeal.includes(t));
    return {
      ...base,
      verdict: 'prevention-allowed',
      kind: 'non-disease',
      matched: { id: listed.id, label: listed.label, clause: listed.clause, term, origin: listed.origin },
      diseaseHit: null,
      allowsPreventWord: true,
      note: `诉求对应第二十条（五）2 **条文原文点名**的非疾病性问题「${listed.label}」—— 可以作功能声称，且**可以使用「预防」字样**并表示该产品可以预防的非疾病问题。落实前请一并核（二）的证明材料与（五）1 的标示要求。`,
    };
  }

  // ③ 两侧都不是 → 不代判，指回附录 1。
  return {
    ...base,
    verdict: 'check-appendix',
    kind: '',
    matched: null,
    diseaseHit: null,
    allowsPreventWord: false,
    note: '诉求既没有指向疾病（不在（一）的范围内），也不在本系统收录的条文点名项之列。按（五）首句可以作**功能声称**（维持 / 增强生长、发育、生理功能或机体健康），但「预防」字样在条文里**只**在（五）2 授权，而那一条的完整清单见《规定》附录 1 —— 本系统没有那份清单，**不代为判定**，请回附录 1 与官方解读核对。',
  };
}

/** 分句：语境是句子级的，跨句命中没有意义。 */
function splitSentences(text) {
  const out = [];
  let buf = '';
  for (const ch of String(text || '')) {
    buf += ch;
    if ('。！？；!?;\n'.includes(ch)) {
      if (buf.trim()) out.push(buf.trim());
      buf = '';
    }
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

/**
 * 命中的上下文片段（给复核用，两侧各留一点，避免只看到孤零零一个词）。
 *
 * ⚠ 刻意**不叫 `snippetOf`** —— `src/lib/keywords.js:193` 有一个**同名**的
 *   `snippetOf(article, terms: string[], opts)`，而且它已export 给了 `server.js:38`。
 *   两个函数第2 个参数的类型完全不同（这里是 `index: number`，那边是 `terms: string[]`），
 *   所以「顺手复用一下现成函数」会**静默拿到错误语义**：类型不匹配不会报错，
 *   只是算出一个看起来合理、实际错误的片段。改名是消除这个坑最省事的办法。
 */
function windowAround(sentence, index, termLen) {
  const start = Math.max(0, index - 14);
  const end = Math.min(sentence.length, index + termLen + 14);
  return `${start > 0 ? '…' : ''}${sentence.slice(start, end)}${end < sentence.length ? '…' : ''}`;
}

/**
 * 在本库里为一条声称找最硬的证据。
 *
 * 这是本模块与「孤立词表」的分界：合规风险与**是否有依据**是两件事，而本系统恰好
 * 存着依据的等级（L1–L5）。有 L1/L2 支撑的宣称，处置方式完全不同 —— 它需要的是
 * 核对措辞边界，而不是补证据。找不到证据时**如实说明找不到**，不假装。
 */
function bestEvidence(articles, sentence) {
  if (!Array.isArray(articles) || !articles.length) return null;
  // 取句子里的实词（长度 ≥2 的连续汉字/字母数字片段）作为匹配线索
  const frags = (sentence.match(/[\u4e00-\u9fa5A-Za-z0-9]{2,}/g) || []).slice(0, 12);
  if (!frags.length) return null;
  let best = null;
  for (const a of articles) {
    const lvl = a?.analysis?.evidenceLevel || a?.evidenceLevel || '';
    const w = LEVEL_WEIGHT[lvl] || 0;
    if (!w) continue;
    const hay = `${a.title || ''}\n${a?.analysis?.tldr || ''}\n${a?.analysis?.summary || ''}\n${(a?.analysis?.claims || []).map((c) => (typeof c === 'string' ? c : c?.claim || c?.subject || '')).join(' ')}`;
    if (!frags.some((f) => hay.includes(f))) continue;
    if (!best || w > best.weight) best = { id: a.id, title: a.title || a.id, level: lvl, levelName: levelOf(lvl).name, weight: w };
  }
  return best;
}

/**
 * 审查一段文本（或一篇文章的正文与要点）。
 *
 * @param {string} text 待审文本。传 article 时由调用方拼好，本模块不猜字段。
 * @param {{ articles?: object[], maxFindings?: number }} opts
 *        `articles` —— 库内文章，用于给每条声称找证据等级（可选，不传则不做这一步）
 * @returns 结构化结论。**没有 findings 不等于「合规」**，见 `note`。
 */
export function reviewClaims(text, opts = {}) {
  const src = String(text || '');
  const maxFindings = Math.max(1, Math.min(500, Number(opts.maxFindings) || 200));
  const sentences = splitSentences(src);
  const findings = [];

  for (const s of sentences) {
    for (const rule of COMPLIANCE_RULES) {
      // 守卫：规则的成立条件是「命中 **且** guard 为真」。放 here 而不是放进正则，
      // 是因为守卫要表达的是「**不**出现某个词」—— 正则里的否定断言可读性极差。
      if (typeof rule.guard === 'function' && !rule.guard(s)) continue;

      // ⚠ 豁免清单：有些规则**天生**会带着某个降噪特征。
      // 「含量增减比较声称」要求比例 ≥15%，所以它的命中里**必然有数字** ——
      // 于是它每次都被「给出了具体数值」降级，warn 永远显示成 info，
      // 降噪机制反过来把这条规则静默废掉了（不报错、不消失，只是永远低一档）。
      // 「符合国外标准的声称」同理：它的命中必然含 AAFCO/FEDIAF，必然触发「引用了法规或标准」。
      const skip = rule.ignoreDampeners || [];
      const dampeners = CONTEXT_DAMPENERS.filter((d) => d.re.test(s) && !skip.includes(d.code));

      const hits = [];
      for (const re of rule.patterns) {
        // 每条规则的正则都带 g，复用前必须把 lastIndex 归零 ——
        // 否则同一份规则表在第二次调用时会从上次的位置继续扫，**漏掉前半句**。
        // 这种错法极其隐蔽：第一段文本查得对，第二段就查不全。
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(s)) !== null) {
          hits.push({ term: m[0], index: m.index });
          if (m.index === re.lastIndex) re.lastIndex += 1; // 零宽匹配保护
        }
      }
      if (!hits.length) continue;

      const evidence = bestEvidence(opts.articles, s);
      // 有 L1/L2 证据 → 下调一档：此时该做的是核对措辞边界，而不是补依据
      const strongEvidence = evidence && evidence.weight >= 4;
      const suppressedBy = [...dampeners.map((d) => d.label)];
      let severity = rule.severity;
      if (strongEvidence) { severity = downgrade(severity); suppressedBy.push(`库内已有 ${evidence.level} 证据（${evidence.levelName}）`); }
      if (dampeners.length) severity = downgrade(severity);

      for (const h of hits.slice(0, 5)) {
        if (findings.length >= maxFindings) break;
        findings.push({
          code: rule.code,
          label: rule.label,
          clause: rule.clause || '',
          severity,
          baseSeverity: rule.severity,
          term: h.term,
          sentence: s.length > 160 ? `${s.slice(0, 160)}…` : s,
          snippet: windowAround(s, h.index, h.term.length),
          reason: rule.reason,
          docRef: rule.docRef,
          suppressedBy,
          evidence: evidence || null,
          // 「库里没有」与「法律要求你有」是两件事。只说前一件，等于把法定义务说成了盘点结果。
          basis: evidence ? '' : `库内未找到对应证据 —— 但这不等于不需要有。${MATERIALS_NOTE}`,
        });
      }
    }
  }

  /* ── 正向通道：这一趟文本里出现的**功能声称诉求**，逐条给（五）下的可声称性 ──
     ⚠ 它必须与 findings **并列**，绝不能混进 findings：那里装的是「风险等级」，
     这里装的是「法规允许你怎么写」。混在一起的后果很具体 —— 「可用『预防』字样」
     会带上一条告警卡片的配色，读起来像一条问题。 */
  const fcHits = [];
  const fcSeen = new Set();
  for (const s of sentences) {
    if (fcHits.length >= 20) break;
    const r = assessFunctionClaim({ appeal: s });
    // 只在「这句话确实在谈这件事」时才报，避免把安静文本也染上（本模块的第一约束是降噪）：
    //   · 条文点名的非疾病性问题 → 直接报（「毛球」这类词极少是随口一提）
    //   · 疾病侧 → 句中还有功能动词时才报（那才是在做声称，而不是在列举疾病名）
    //   · 其余 → 只有出现「预防 / 防止」时才报（那正是需要回附录 1 核对的那个问题）
    const quiet = r.verdict === 'prevention-allowed' ? false
      : r.verdict === 'red-line' ? !FUNCTION_VERB.test(s)
        : r.verdict === 'check-appendix' ? !/预防|防止/.test(s)
          : true;
    if (quiet) continue;
    const key = `${r.verdict}:${r.matched?.id || r.diseaseHit?.term || ''}`;
    if (fcSeen.has(key)) continue;
    fcSeen.add(key);
    fcHits.push({
      verdict: r.verdict,
      kind: r.kind,
      appeal: r.appeal,
      matched: r.matched,
      diseaseHit: r.diseaseHit,
      allowsPreventWord: r.allowsPreventWord,
      clause: r.matched?.clause || r.diseaseHit?.clause || r.channelClause,
      sentence: s.length > 160 ? `${s.slice(0, 160)}…` : s,
      note: r.note,
    });
  }

  const summary = {
    sentences: sentences.length,
    error: findings.filter((f) => f.severity === 'error').length,
    warn: findings.filter((f) => f.severity === 'warn').length,
    info: findings.filter((f) => f.severity === 'info').length,
    downgraded: findings.filter((f) => f.severity !== f.baseSeverity).length,
  };

  return {
    findings,
    summary,
    // 去重后的待核对文件方向：让人知道该去翻哪一类文件，而不是只看到一堆词
    docRefs: [...new Set(findings.map((f) => f.docRef))].map((name) => ({ name, section: '法规与合规', item: name })),
    // 去重后的具体条款：这才是「拿着它就能翻到原文」的粒度
    clauses: [...new Set(findings.map((f) => f.clause).filter(Boolean))],
    levelNote: '证据等级沿用本系统的 L1–L5（L1 法规与标准 / L2 同行评议 / L3 行业报告 / L4 企业与专家 / L5 待查证）。宣称有 L1、L2 支撑时只下调风险等级 —— 有依据不等于措辞就合适，仍需核对边界。',
    /**
     * 第二十条（五）的**许可侧**。整份参照数据随回应一并回传，而不是让前端另取一次
     * `/api/compliance/rules`：否则「先点审查、后开口径」的顺序下，正向通道会因为拿不到
     * 参照表而整块消失 —— 而它最该被看见的时刻，恰恰是「有诉求、却一条风险都没命中」的时候。
     */
    functionClaim: {
      clause: FUNCTION_CLAIM_CHANNEL.clause,
      hits: fcHits,
      channel: FUNCTION_CLAIM_CHANNEL,
      disclaimer: FUNCTION_CLAIM_CHANNEL.disclaimer,
      note: fcHits.length
        ? '上面每一条给出的是**条款号 + 可使用的字样 + 落笔前要备的材料**，不是「这条合规」的认定。'
        : '本趟没有识别到（五）2 条文点名的非疾病性问题，也没有识别到含「预防」字样的疾病侧写法。识别是**启发式**的（按词表匹配），识别不到不代表没有该类声称。',
    },
    note: [
      '这是一份**待核对清单**，不是合规判定。风险等级衡量的是「这句话值得看一眼的程度」，不是「违反了哪一条」。',
      '最终依据只能是现行法规与标准原文（本系统的 L1 档），请带上述**条款号**回到原文核对。',
      `没有命中不代表合规 —— 词表是有限的，同义表达与新的营销话术一定漏（本次共扫描 ${sentences.length} 句）。`,
      '第二十条（五）功能声称的**许可侧**在 `functionClaim` 里 —— 它给的是条款号、措辞档位与法定材料类型，不是判定；识别是启发式的，识别不到不代表没有该类声称。',
      '已做语境抑制：句中若出现法条名/标准号、检测或试验、具体数值、否定或引述、历史陈述、讲规则的说明文，风险等级下调一档，并在「抑制依据」里写明原因。',
    ].join('\n'),
  };
}
