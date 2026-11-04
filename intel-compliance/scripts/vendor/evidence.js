/**
 * 证据颗粒度（可判读性）：在「有没有出处」之外，回答**这个来源能不能支撑这个结论**。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 为什么需要它（这一条是实测出来的，不是设想）
 * ══════════════════════════════════════════════════════════════════════
 * 现有 `evidenceLevel`（L1 法规标准 / L2 同行评议 / L3 机构报告 / L4 企业观点 / L5 待查证）
 * 判定的是**「那句话有没有出处」**。README 也诚实地写着「等级不等于结论正确」。
 * 问题在于：**同一等级内部的差异，恰恰是研发最需要看到的。**
 *
 * 以「膳食纤维减少猫毛球」为例，本次检索到的五项证据里有四项都落在 L2，但强度相差数档：
 *
 *   · Loureiro 2014  —— 梯度剂量对照，32 只猫，甘蔗纤维使粪毛排出**剂量依赖**下降
 *   · Weber 2015     —— 交叉设计，车前子 + 11%/15% 总膳食纤维，长毛猫粪毛排出 +81%/+113%
 *   · Beynen 2011    —— 双盲，吐毛/呕吐发生率降 79%/91%（**结局来自主人报告**）
 *   · Tournier 2005  —— 梯度剂量，4.5%/7.8% 粗纤维使粪毛 +26%/+72%
 *   · Cannon 2013    —— 系统综述：**麦芽膏、凡士林膏这类「化毛膏」从未有任何对照研究评价过**
 *
 * 五条都能标 L2，但第一条是「干预性研究 + 剂量效应」，第五条是「用了三十年但从未被验证」。
 * 决定能不能写进配方的，是**研究设计、样本量、试验动物、终点类型、亚组限定、利益相关**
 * 这六个维度，而不是「有没有出处」。
 *
 * 项目对**试验动物**已经有一条规则（`compliance.js` 的 `EVIDENCE_SPECIES`：用大鼠或体外做的
 * 试验不能直接支撑面向犬猫的宣称），思路完全正确，**只是没有推广到其余五个维度**。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 三条硬约束（每一条都对应一种会安静出事的形态）
 * ══════════════════════════════════════════════════════════════════════
 * ① **只搬运「原文写了什么」，不评价「这研究好不好」。**
 *    六个字段没有一处是判断，`conflictFlag` 也只是把「作者隶属皇家宠物食品研究院」
 *    这个**客观事实**摆出来，判断权留给使用者。这是项目「只搬运不评价」底线的正确用法。
 *
 * ② **给不出就留空，绝不用默认值填。**
 *    留空**不是**「没有」，而是**「没识别出来」**——两件事的处置方式完全不同。
 *    所以本模块统一用**同一个空值**表示未识别（`''`，样本量用 `0`），
 *    而不给每个字段各造一种「未填」写法：否则「未识别」会有六种表达，
 *    而统计「有多少条根本没抽到」需要的恰恰是**同一个信号**。
 *
 * ③ **`endpointType` 规则通道一律不填。**
 *    这一栏是全组最要紧的：一个只在**替代终点**上有效的干预，被写成「减少毛球」的功能声称，
 *    是行业里最典型的**证据越界** —— 而「有没有出处」当年完全看不出这件事。
 *    判定它需要领域判断（「粪毛排出量」是替代终点，「吐毛次数」才是临床终点），
 *    规则通道猜错的形态是**把替代终点悄悄升级成临床终点**：比留空坏得多。
 *    所以规则通道**只抽能字面读到的字段**（物种 / 样本量 / 设计 / 亚组 / 利益相关），
 *    终点类型只接受人工或大模型给出。
 *
 * ══════════════════════════════════════════════════════════════════════
 * 与 A3（参数参照表）的口径同源：**猫与犬不能合并成「宠物」**
 * ══════════════════════════════════════════════════════════════════════
 * `SPECIES_VALUES` 里没有「宠物」这一档，也没有「犬猫通用」这类合并写法 ——
 * 合并之后就无法回答「这条结论能不能用在只做猫的配方上」，而那是本模块存在的理由。
 * 两项都写明的场合用「犬与猫」，这**不是**合并，是如实说两者都做了。
 *
 * 本模块**零依赖、纯数据 + 纯函数**：不 import 任何 `node:` 模块，也不 import
 * 其它项目模块。原因同 `page-quality.js` / `reference-values.js`：`src/lib` 同时被
 * 静态暴露给浏览器（`app.js` 直接 import 它取标签与徽章），一旦带上 `node:` 依赖，
 * 整张前端模块图会加载失败（而 ES module 图只要有一个模块挂掉就整体不执行 → 白屏）。
 */

/** 整体的口径声明。界面上要原样显示，不要改写成更自信的说法。 */
export const EVIDENCE_META_NOTE = '这六个字段记录的是**原文写了什么**，不是对研究质量的评价 ——'
  + '「样本量 32」不等于「结论可靠」，「未识别」也不等于「没有」。'
  + '抽不到的字段一律留空并在界面上显式标出，绝不替原文补一个默认值。';

/** 未识别的统一空值说明。 */
export const UNIDENTIFIED_NOTE = '留空 = **没识别出来**，不是「没有」。'
  + '所以界面上不会把空字段藏起来（藏起来与「原文确实没写」长得一模一样），'
  + '而是显式写「未识别」——至少两个字段（试验动物、终点类型）空着这件事本身就是要紧信息。';

/* ───────────────────────── 研究设计 ───────────────────────── */

/**
 * 研究设计的**两级**口径。
 *
 * 一级是研究类型（这一层是有公认次序的：干预性 > 二次研究 > 观察性 > 体外），
 * 二级是同一类型内的具体设计。用两级而不是一条直线，是因为「系统综述 vs 观察性」
 * 本来就不在同一个轴上，硬排成一条线会造出一个假的精度。
 */
export const STUDY_DESIGN_GROUPS = [
  { id: 'interventional', name: '干预性', rank: 1, why: '研究者主动施加处理并观察后果 —— 这一层才有资格谈因果' },
  { id: 'synthesis', name: '二次研究', rank: 2, why: '综述/汇总，它的强度取决于它汇总了哪些一手研究' },
  { id: 'observational', name: '观察性', rank: 3, why: '只观察不干预，混杂因素无法排除' },
  { id: 'lab', name: '体外 / 实验室', rank: 4, why: '不进入动物体 —— 只能作为机制线索' },
  { id: 'none', name: '未设设计 / 无对照', rank: 5, why: '原文明确写了没有对照，或只有个案' },
];

/**
 * ⚠ 与原方案的一处**有意偏离**，理由写在这里。
 *
 * 原方案列为 6 档（随机对照 / 交叉 / 双盲 / 观察性 / 体外 / 无），
 * 但真实语料里有两类**归并不进去**的设计：
 *   · **梯度剂量对照**（Loureiro 2014 / Tournier 2005）—— 它既不必然随机分组，
 *     而「有没有做出剂量梯度」又正是这类研究最关键的信息。强行归到「随机对照」是**猜**。
 *   · **系统综述**（Cannon 2013）—— 它不是一手研究，强度取决于它汇总了什么，
 *     「综述了 0 项对照研究」与「综述了 12 项 RCT」用同一个标签就丢掉了全部分量。
 * 所以补到 8 档。本模块的底线是不猜，档位不够用时补档比凑合归并更诚实。
 */
export const STUDY_DESIGNS = [
  { id: 'rct', name: '随机对照', group: 'interventional', rank: 1, hint: '随机分组 + 设对照组' },
  { id: 'crossover', name: '交叉设计', group: 'interventional', rank: 2, hint: '同一批动物先后接受不同处理（自身对照）' },
  { id: 'dose-response', name: '梯度剂量', group: 'interventional', rank: 3, hint: '设了多个剂量水平，能看到剂量效应' },
  { id: 'blinded', name: '盲法', group: 'interventional', rank: 4, hint: '单盲 / 双盲 / 盲评' },
  { id: 'review', name: '系统综述 / 综述', group: 'synthesis', rank: 1, hint: '汇总他人研究；分量取决于汇总了什么' },
  { id: 'observational', name: '观察性', group: 'observational', rank: 1, hint: '队列 / 横断面 / 病例对照 / 回顾性' },
  { id: 'in-vitro', name: '体外', group: 'lab', rank: 1, hint: '细胞、酶解、模拟消化 —— 未进入动物体' },
  { id: 'none', name: '无对照', group: 'none', rank: 1, hint: '原文明确无对照，或仅个案报告' },
];

export const STUDY_DESIGN_MAP = Object.fromEntries(STUDY_DESIGNS.map((d) => [d.name, d]));
export const STUDY_DESIGN_BY_ID = Object.fromEntries(STUDY_DESIGNS.map((d) => [d.id, d]));

/**
 * 设计维度是**单选**，而真实研究常同时满足多条（Weber 2015 是双盲 + 交叉 + 随机）。
 * 单选必然丢信息 —— 所以这里定死一条**明确优先级**（上表顺序，越靠前越强），
 * 并且**原句摘录始终与字段并列显示**：需要精确判断时以原文为准，不以字段为准。
 *
 * 排序键只用于**展示顺序**，不是质量评分。它回答的是「先看哪一条」，
 * 不回答「这条研究好不好」——后者本模块不做。
 */
export function designRank(design) {
  const d = typeof design === 'string' ? STUDY_DESIGN_MAP[design] : design;
  if (!d) return 999;
  const g = STUDY_DESIGN_GROUPS.find((x) => x.id === d.group);
  return (g ? g.rank : 9) * 100 + (d.rank || 9);
}

/**
 * 设计的别名。大模型不总会逐字输出受控名（「交叉」「随机对照试验」「RCT」都很常见），
 * 不认这些写法就等于把一条抽对了的记录判成「未识别」——
 * 而「未识别」在界面上是个**警告**，会让使用者去核对一条本来没问题的记录。
 *
 * ⚠ 这张表里**没有**「无」→「无对照」的映射：单写一个「无」到底是
 * 「原文明确说了无对照」还是「模型想写没写」，无从判断，判断权不归这里。
 */
export const DESIGN_ALIASES = {
  rct: '随机对照', '随机对照试验': '随机对照', '随机对照实验': '随机对照',
  交叉: '交叉设计', crossover: '交叉设计', '交叉试验': '交叉设计',
  '剂量效应': '梯度剂量', '剂量依赖': '梯度剂量', '剂量-反应': '梯度剂量', '剂量反应': '梯度剂量',
  '双盲': '盲法', '单盲': '盲法', blinded: '盲法', blind: '盲法',
  '系统综述': '系统综述 / 综述', '综述': '系统综述 / 综述', review: '系统综述 / 综述', '荟萃分析': '系统综述 / 综述',
  observational: '观察性', '队列研究': '观察性', '横断面': '观察性',
  'in vitro': '体外', 'in-vitro': '体外', vitro: '体外',
  '无对照': '无对照', 'uncontrolled': '无对照',
};

/** 终点类型的别名。同理：`clinical` / `surrogate` 与「临床」「替代」都是常见写法。 */
export const ENDPOINT_ALIASES = {
  clinical: '临床终点', '临床': '临床终点', '临床结局': '临床终点', outcome: '临床终点',
  surrogate: '替代终点', '替代': '替代终点', '替代指标': '替代终点', '中间指标': '替代终点',
};

/* ───────────────────────── 终点类型 ───────────────────────── */

export const ENDPOINT_TYPES = [
  { id: 'clinical', name: '临床终点', hint: '测的是动物身上真实发生的事：吐毛次数、腹泻发生率、复发率、存活' },
  { id: 'surrogate', name: '替代终点', hint: '测的是中间指标（粪毛排出量、血检值），要**再假定**它代表临床结局' },
];

export const ENDPOINT_TYPE_MAP = Object.fromEntries(ENDPOINT_TYPES.map((e) => [e.name, e]));

export const ENDPOINT_NOTE = '这一栏是本组字段里最要紧的一条。'
  + '一个只在**替代终点**（如「粪毛排出量增加」）上有效的干预，被写成「减少毛球」的功能声称，'
  + '就是证据越界 —— 而「有没有出处」这件事完全看不出来。'
  + '规则通道**不填这一栏**：判定它需要领域判断，猜错会把替代终点悄悄升级成临床终点。';

/* ───────────────────────── 试验动物 ───────────────────────── */

/**
 * 物种口径与 A3 参数参照表同源（见 `reference-values.js` 的 `REFERENCE_FIELD_SPEC`：
 * 「猫与犬不能合并成『宠物』」）。这里同样不设「宠物」档。
 * 「犬与猫」不在此列 —— 那不是合并，是如实说两者都做了。
 */
export const SPECIES_VALUES = ['猫', '犬', '犬与猫', '大鼠', '小鼠', '体外', '其他种属'];

/** 物种留空时界面上的写法。原方案要求「未写明 → 显式标『试验动物未识别』」，就是这一句。 */
export const SPECIES_UNKNOWN_LABEL = '试验动物未识别';

export const SPECIES_NOTE = '留空并标「试验动物未识别」，是因为**错配**正是要拦住的东西：'
  + '用大鼠做的抗氧化试验、或体外细胞试验，只能作为机制线索，不能直接支撑一条面向犬猫产品的宣称。'
  + '合并成「宠物」会让这件事无从判断，所以不设那一档。';

/* ───────────────────────── 字段清单 ───────────────────────── */

export const EVIDENCE_META_FIELDS = [
  { key: 'studyDesign', label: '研究设计', kind: 'enum' },
  { key: 'sampleSize', label: '样本量', kind: 'int' },
  { key: 'species', label: '试验动物', kind: 'enum' },
  { key: 'endpointType', label: '终点类型', kind: 'enum' },
  { key: 'subgroup', label: '亚组限定', kind: 'text' },
  { key: 'conflictFlag', label: '利益相关', kind: 'text' },
];

/** 空着也**必须显式说出来**的两个字段。其余四个空着只是「信息不全」。 */
export const MUST_SHOW_WHEN_EMPTY = ['species', 'endpointType'];

/** 字段上限。抽出来的自由文本不设上限会一路顶到界面上。 */
export const META_TEXT_MAX = { subgroup: 40, conflictFlag: 80 };

/** 样本量的合理上限。超过它的数字一律视为抽错（不是「把上限调高一点」）。 */
export const SAMPLE_SIZE_MAX = 9999;

/**
 * 未识别的**统一**表示：文本字段是空串，样本量是 0。
 *
 * 为什么样本量用 0 而不是空串：它要参与排序与显示（`n=32`），全程当字符串会很别扭。
 * 为什么 0 可以安全地承载「未识别」：真实研究不存在 0 例样本。
 * ⚠ 这句话必须写下来 —— 否则下一个人会把 0 读成「一篇没做实验的文章」。
 */
export const UNIDENTIFIED = { text: '', count: 0 };

/* ───────────────────────── 归一化 ───────────────────────── */

/** 受控词的归一化：接受 `name`、`id` 或别名，**都不认就留空**（绝不退回默认值）。 */
function normEnum(value, list, aliases = null) {
  const s = String(value ?? '').trim();
  if (!s) return '';
  const byName = list.find((x) => x.name === s);
  if (byName) return byName.name;
  const byId = list.find((x) => x.id === s.toLowerCase());
  if (byId) return byId.name;
  if (aliases) {
    const hit = aliases[s] || aliases[s.toLowerCase()];
    // 别名表里的值必须在受控表内 —— 否则就是绕过受控词表塞进一个没定义的档位
    if (hit && list.some((x) => x.name === hit)) return hit;
  }
  return '';
}

/**
 * 样本量归一化：只接受**正整数**且不超过 `SAMPLE_SIZE_MAX`，其余一律 0（未识别）。
 * 小数、负数、`''`、`'n≈32'` 这类写法都不猜 —— 猜出来的数字会以 `n=32` 的形式
 * 出现在界面上，与真抽出来的数字**长得完全一样**。
 */
export function normalizeSampleSize(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const n = Math.floor(value);
    return n >= 1 && n <= SAMPLE_SIZE_MAX ? n : UNIDENTIFIED.count;
  }
  const m = String(value ?? '').trim().match(/^(\d{1,5})$/);
  if (!m) return UNIDENTIFIED.count;
  const n = Number(m[1]);
  return n >= 1 && n <= SAMPLE_SIZE_MAX ? n : UNIDENTIFIED.count;
}

function normText(value, max) {
  const s = String(value ?? '').replace(/\s+/g, ' ').trim();
  return s.length > max ? s.slice(0, max) : s;
}

/**
 * 归一化一组证据颗粒度字段。
 *
 * 无论来自 LLM 还是规则通道，落库前都过这一层：下游（界面、排序、导出）
 * 拿到的字段永远存在、类型正确、且**取值一定在受控表内或为空**。
 */
export function normalizeEvidenceMeta(raw = {}) {
  const r = raw && typeof raw === 'object' ? raw : {};
  return {
    studyDesign: normEnum(r.studyDesign || r.design, STUDY_DESIGNS, DESIGN_ALIASES),
    sampleSize: normalizeSampleSize(r.sampleSize ?? r.n ?? r.samples),
    species: normSpecies(r.species || r.animal),
    endpointType: normEnum(r.endpointType || r.endpoint, ENDPOINT_TYPES, ENDPOINT_ALIASES),
    subgroup: normText(r.subgroup, META_TEXT_MAX.subgroup),
    conflictFlag: normText(r.conflictFlag || r.conflict, META_TEXT_MAX.conflictFlag),
  };
}

/**
 * 物种的英文别名。大模型有时整条用英文回答（`cat` / `in vitro`），
 * 不认这些写法就等于把一条抽对了的记录判成「未识别」——
 * 而「未识别」在界面上是个**警告**，会让使用者去核对一条本来没问题的记录。
 */
export const SPECIES_ALIASES = {
  cat: '猫', cats: '猫', feline: '猫',
  dog: '犬', dogs: '犬', canine: '犬', 'dog and cat': '犬与猫', 'cats and dogs': '犬与猫',
  '犬猫': '犬与猫', '猫狗': '犬与猫', '犬和猫': '犬与猫', '猫与犬': '犬与猫',
  rat: '大鼠', rats: '大鼠', mouse: '小鼠', mice: '小鼠',
  'in vitro': '体外', vitro: '体外', 'other species': '其他种属',
};

/** 物种归一化：中文受控词优先，其次英文别名，都不认就留空。 */
function normSpecies(value) {
  const s = String(value ?? '').trim();
  if (!s) return '';
  if (SPECIES_VALUES.includes(s)) return s;
  return SPECIES_ALIASES[s.toLowerCase()] || '';
}

/** 该字段是否**未识别**（空串 / 0）。 */
export function isUnidentified(key, value) {
  if (key === 'sampleSize') return !(Number(value) >= 1);
  return !String(value ?? '').trim();
}

/** 未识别的字段 key 列表。界面据此决定要显式说「未识别」的是哪几个。 */
export function evidenceMetaGaps(meta = {}) {
  const m = normalizeEvidenceMeta(meta);
  return EVIDENCE_META_FIELDS.filter((f) => isUnidentified(f.key, m[f.key])).map((f) => f.key);
}

/** 有没有抽到任何一项。全空时界面不该铺一排「未识别」徽章。 */
export function hasAnyEvidenceMeta(meta = {}) {
  const m = normalizeEvidenceMeta(meta);
  return evidenceMetaGaps(m).length < EVIDENCE_META_FIELDS.length;
}

/* ───────────────────────── 规则通道抽取 ───────────────────────── */

/**
 * 句子必须先含「研究线索词」才做抽取。
 *
 * 这一道过滤是必要的：只有 `/猫/` 就抽物种，会把「猫粮适口性测评」这种
 * 营销文案判成「猫的试验」—— 而抽错的字段在界面上与自己抽出来的**长得一模一样**。
 * 宁可少抽（留空会被显式标出来），不可错抽。
 */
const STUDY_CUE = /(试验|实验|研究|受试|样本|饲喂|喂食|临床|随机|对照|双盲|单盲|盲法|交叉|剂量|组间|病例|队列|综述|meta|体外|细胞|in\s?vitro)/i;

/** 设计识别的尝试顺序 = 上表的优先级顺序（越强越先试）。 */
const DESIGN_PATTERNS = [
  { id: 'rct', re: /(随机对照|RCT|随机(?:分组|分配)[^，。；]{0,12}对照|对照[^，。；]{0,12}随机)/i },
  { id: 'crossover', re: /(交叉(?:设计|试验|饲喂|对照)?|自身对照|crossover)/i },
  { id: 'dose-response', re: /(梯度剂量|剂量梯度|剂量依赖|剂量-?反应|剂量效应|不同(?:剂量|添加量|含量|水平)|梯度含量|浓度梯度)/i },
  { id: 'blinded', re: /(双盲|单盲|盲法|盲评|blind)/i },
  { id: 'review', re: /(系统综述|荟萃分析|meta\s?-?分析|文献综述|综述)/i },
  { id: 'observational', re: /(观察性|队列|横断面|病例对照|回顾性|流行病学)/i },
  { id: 'in-vitro', re: /(体外|细胞(?:试验|实验|培养)|in\s?vitro|模拟消化|酶解)/i },
  { id: 'none', re: /(无对照|未设对照|没有对照组|无对照组|个案报告)/i },
];

const SPECIES_RULES = [
  { value: '体外', re: /(体外|细胞(?:试验|实验|培养)|in\s?vitro)/i },
  { value: '大鼠', re: /大鼠/ },
  { value: '小鼠', re: /小鼠/ },
];

/** `32 只猫` / `n=24` / `受试动物 16 条` —— 必须有量词或 `n=`，否则不认。 */
const SAMPLE_PATTERNS = [
  /(?:^|[^\d])(\d{1,4})\s*(?:只|头|例|条|份|名)\s*(?:猫|犬|狗|大鼠|小鼠|鼠|动物|受试)?/,
  /(?:^|[^\w])n\s*[=＝]\s*(\d{1,4})/i,
];

/**
 * 亚组限定的引导词里**刻意没有「只」**：它与量词「只」逐字相同，
 * 于是「32 只猫的梯度剂量对照试验」会被抽成亚组「猫的梯度剂量对照试验」。
 * 少一个引导词只损失一点召回（留空会被显式标出来），多一个会安静地抽错。
 */
const SUBGROUP_LEAD = /(仅限|仅限于|仅限于|仅|限于|单独|特指)/;

/** 亚组限定必须落在物种 / 生命阶段 / 品种上，且至少 3 个字（「仅猫」这类无信息量）。 */
const SUBGROUP_SUBJECT = /^[^，。；、]{0,10}(?:长毛|短毛|幼猫|幼犬|成年猫|成年犬|老年|绝育|公猫|母猫|公犬|母犬|健康|患病|猫|犬|狗|品种)/;

const SUBGROUP_MIN = 3;

/**
 * 利益相关的抽取形状。
 *
 * ⚠ 抓「作者隶属」时**必须锚到机构后缀**，不能用 `([^，。；]{2,24})` 直接吞到标点：
 * 实测「作者隶属皇家宠物食品研究院的团队开展了这项交叉试验」会被抽成
 * 「作者单位：皇家宠物食品研究院的团队开展了这项交叉试验」——**其余半句全被当成机构名**。
 * 锚到「研究院/公司/大学…」这类后缀，抽出来才是机构；没有后缀时退到第一个「的」为止。
 */
/**
 * 抽出来的短语要去掉**前导标点**。
 *
 * 实测：`利益冲突[：:]?\s*([^，。；]{2,20})` 对「利益冲突：无」会失配
 * （冒号后的「无」只有 1 个字、不足 `{2,20}`），正则回退成「不消费冒号」，
 * 于是抽出来的机构/声明名称变成「：无」—— 界面上就成了「利益冲突声明：：无」。
 * 与其把每个 `{2,20}` 都调成 `{1,20}` 再各自处理，不如在出口统一削一次。
 */
const cutLead = (s) => String(s || '').replace(/^[\s：:，,、·\-—]+/, '').trim();

const ORG_SUFFIX = '(?:研究院|研究所|研究中心|公司|集团|大学|学院|实验室|事业部|企业|协会|学会|院|所)';
const CONFLICT_RULES = [
  { re: new RegExp(`(?:作者|研究人员|研究者|团队|课题组)(?:均)?(?:隶属|来自|就职于|供职于|任职于)([^，。；]{2,20}?${ORG_SUFFIX})`), text: (m) => `作者单位：${cutLead(m[1])}` },
  { re: /(?:作者|研究人员|研究者|团队|课题组)(?:均)?(?:隶属|来自|就职于|供职于|任职于)([^，。；的]{3,20})/, text: (m) => `作者单位：${cutLead(m[1])}` },
  { re: new RegExp(`(?:资助|经费|资金|基金)(?:来源|支持)[：:]?\\s*([^，。；]{2,20}?${ORG_SUFFIX})`), text: (m) => `资助方：${cutLead(m[1])}` },
  { re: /(?:资助|经费|资金|基金)(?:来源|支持)[：:]?\s*([^，。；的]{1,20})/, text: (m) => `资助方：${cutLead(m[1])}` },
  { re: /利益冲突[：:]?\s*([^，。；]{1,20})/, text: (m) => `利益冲突声明：${cutLead(m[1])}` },
];

/**
 * 规则通道：从**一个句子**里抽能字面读到的字段。
 *
 * 明确的覆盖边界（不是「以后再补」，是这套规则的固有形态）：
 *   · `endpointType` **永远留空** —— 判定它需要领域判断，见文件头 ③。
 *   · 设计维度单选，同时命中多条时取**最强的那一条**（`DESIGN_PATTERNS` 的顺序即优先级）。
 *   · 物种只做词面命中，不做语境判别：句中同时出现猫与犬就是「犬与猫」。
 *     想要更准只有两条路 —— 回原文人工核，或走大模型通道。
 *   · 抽不到就是空串 / 0，**不会**退回任何默认值。
 */
/** 亚组限定：取引导词之后**最靠后**的那个主体词结尾（于是「长毛猫」不会被截成「长毛」）。 */
function extractSubgroup(s) {
  const lead = s.match(SUBGROUP_LEAD);
  if (!lead) return '';
  const from = lead.index + lead[0].length;
  const rest = s.slice(from, from + 26).split(/[，。；、]/)[0];
  // 贪婪 `{0,10}` 会先吃满再回退，因此命中的是最后一个主体词 —— 这正是「长毛猫」需要的
  const t = rest.match(SUBGROUP_SUBJECT);
  const v = t ? String(t[0]).trim() : '';
  return v.length >= SUBGROUP_MIN ? v : '';
}

export function extractStudyMeta(text) {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim();
  const empty = normalizeEvidenceMeta({});
  if (!s || !STUDY_CUE.test(s)) return empty;

  let studyDesign = '';
  for (const d of DESIGN_PATTERNS) {
    if (d.re.test(s)) { studyDesign = STUDY_DESIGN_BY_ID[d.id].name; break; }
  }

  let species = '';
  const inVitro = SPECIES_RULES.find((r) => r.re.test(s));
  if (inVitro) {
    species = inVitro.value;
  } else {
    const cat = /(猫|feline|cat)/i.test(s);
    const dog = /(犬|狗|canine|dog)/i.test(s);
    if (cat && dog) species = '犬与猫';
    else if (cat) species = '猫';
    else if (dog) species = '犬';
  }

  let sampleSize = UNIDENTIFIED.count;
  for (const re of SAMPLE_PATTERNS) {
    const m = s.match(re);
    if (m) { sampleSize = normalizeSampleSize(m[1]); if (sampleSize) break; }
  }

  const subgroup = extractSubgroup(s);

  let conflictFlag = '';
  for (const c of CONFLICT_RULES) {
    const m = s.match(c.re);
    if (m) { conflictFlag = normText(c.text(m), META_TEXT_MAX.conflictFlag); break; }
  }

  return normalizeEvidenceMeta({ studyDesign, sampleSize, species, endpointType: '', subgroup, conflictFlag });
}

/* ───────────────────────── 展示与排序 ───────────────────────── */

/**
 * 排序键：识别出的字段数（多者先），其次样本量（大者先）。
 *
 * ⚠ 它**只回答「先看哪一条」**，不回答「这条研究好不好」。
 * 我没有把 `designRank` 放进主排序，是因为那会把「按研究类型排序」偷偷变成
 * 「系统在给研究质量打分」——本项目不做评价，只做搬运。
 * 需要看设计强度的人，直接看那一栏即可。
 */
export function evidenceSortKey(meta = {}) {
  const m = normalizeEvidenceMeta(meta);
  return { identified: EVIDENCE_META_FIELDS.length - evidenceMetaGaps(m).length, sampleSize: m.sampleSize };
}

/** 展示顺序比较器。分数相同时返回 0（保持原有次序，不做二次猜测）。 */
export function compareByEvidence(a = {}, b = {}) {
  const x = evidenceSortKey(a);
  const y = evidenceSortKey(b);
  if (x.identified !== y.identified) return y.identified - x.identified;
  return y.sampleSize - x.sampleSize;
}

/**
 * 把一组字段摊成**界面直接可渲染**的徽章。
 *
 * 放在这里的理由：徽章文案是「口径」的一部分（「试验动物未识别」必须与
 * `SPECIES_UNKNOWN_LABEL` 逐字一致），让前端自己拼字符串迟早会与这里漂开。
 *
 * `tone` 只用于样式，**语义一律落在 `text` 里** —— 颜色不能是唯一的信息载体
 * （灰度打印、色觉障碍下只剩颜色就等于没有信息）。
 */
export function evidenceMetaChips(meta = {}) {
  const m = normalizeEvidenceMeta(meta);
  if (!hasAnyEvidenceMeta(m)) return [];
  const chips = [];
  const push = (key, label, text, tone) => chips.push({ key, label, text, tone });

  if (m.studyDesign) {
    const d = STUDY_DESIGN_MAP[m.studyDesign];
    const g = STUDY_DESIGN_GROUPS.find((x) => x.id === d?.group);
    push('studyDesign', '研究设计', m.studyDesign + (g ? `（${g.name}）` : ''), 'info');
  }
  if (m.sampleSize) push('sampleSize', '样本量', `n=${m.sampleSize}`, 'info');

  if (m.species) push('species', '试验动物', m.species, m.species === '体外' ? 'warn' : 'info');
  else push('species', '试验动物', SPECIES_UNKNOWN_LABEL, 'warn');

  if (m.endpointType) {
    push('endpointType', '终点类型', m.endpointType, m.endpointType === '替代终点' ? 'warn' : 'ok');
  } else {
    push('endpointType', '终点类型', '终点类型未识别', 'muted');
  }

  if (m.subgroup) push('subgroup', '亚组限定', m.subgroup, 'warn');
  if (m.conflictFlag) push('conflictFlag', '利益相关', m.conflictFlag, 'muted');
  return chips;
}

/** 复制/导出用的一行文本。与界面渲染**同源**，避免「看到的」与「复制走的」不一致。 */
export function evidenceMetaText(meta = {}) {
  const chips = evidenceMetaChips(meta);
  if (!chips.length) return '';
  return chips.map((c) => `${c.label}：${c.text}`).join('；');
}
