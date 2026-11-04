// 数据契约：分类体系、证据分级、字段归一化。修改这里等于修改产品语义。

import { normalizeEvidenceMeta } from './evidence.js';

/**
 * 抽取规则（词表 / 字段结构 / 分级口径）的版本号。
 *
 * 凡改动本文件里影响抽取结果的定义，都应把它 +1 —— 它是 `diffAnalysis`
 * 判断「结论变化是不是规则改的」的**第一依据**，漏加会让人把规则变更误读成模型漂移。
 *
 * v3 → v4：要点与论断上新增**证据颗粒度**六字段
 * （研究设计 / 样本量 / 试验动物 / 终点类型 / 亚组限定 / 利益相关，见 `evidence.js`）。
 * 这是一次**纯增量**扩容：老记录的这六个字段为空，界面会把它们当作「未识别」显式标出，
 * 而不是当作「默认值」——所以 v3 的旧结论不会被误读，只是暂时缺这一层信息；
 * 重抽之后 `diffAnalysis` 会把「哪些论断的颗粒度字段变了」单独列出来。
 */
export const ANALYSIS_VERSION = 4;

export const EVIDENCE_LEVELS = [
  { id: 'L1', name: '法规与标准', weight: 5, desc: '现行法规、国家/行业标准、官方公告' },
  { id: 'L2', name: '同行评议文献', weight: 4, desc: '可追溯的期刊论文、系统综述、临床试验' },
  { id: 'L3', name: '行业报告/机构白皮书', weight: 3, desc: '可追溯的第三方数据、专业机构报告' },
  { id: 'L4', name: '企业与专家观点', weight: 2, desc: '有署名主体但未经独立验证' },
  { id: 'L5', name: '待查证', weight: 1, desc: '未标注来源或来源不可追溯' },
];

export const LEVEL_MAP = Object.fromEntries(EVIDENCE_LEVELS.map((l) => [l.id, l]));
export const LEVEL_WEIGHT = Object.fromEntries(EVIDENCE_LEVELS.map((l) => [l.id, l.weight]));

export function levelOf(id) {
  return LEVEL_MAP[id] || LEVEL_MAP.L5;
}

/** 一级分类：内容性质 */
export const PRIMARY_CATEGORIES = [
  { id: 'regulation', name: '法规与合规', hint: '法规、标准、公告、标签要求、准入清单' },
  { id: 'research', name: '研究证据', hint: '动物试验、临床研究、体外/成分机理' },
  { id: 'method', name: '方法与工艺', hint: '配方设计、加工工艺、检测分析、试验方法' },
  { id: 'safety', name: '安全与风险', hint: '污染物、过敏原、抗营养因子、召回、不良反应' },
  { id: 'industry', name: '产业与市场', hint: '市场规模、消费趋势、供应链、投融资' },
  { id: 'product', name: '产品与评测', hint: '新品、配方拆解、标签比对、测评' },
  { id: 'opinion', name: '观点与评论', hint: '行业评论、专栏观点、趋势判断' },
];

export const CATEGORY_MAP = Object.fromEntries(PRIMARY_CATEGORIES.map((c) => [c.id, c]));

/** 领域预设：决定实体类型与二级话题词典，可在设置里替换 */
export const DOMAIN_PRESETS = {
  petfood: {
    name: '宠物食品与营养',
    entityTypes: ['原料', '营养成分', '功效宣称', '添加剂', '疾病与健康', '标准法规', '机构组织', '品牌产品', '工艺设备', '检测指标', '其他'],
    topics: ['蛋白与氨基酸', '脂肪与脂肪酸', '碳水与纤维', '维生素与矿物质', '功能成分', '益生菌与肠道', '口腔与牙齿', '皮肤与被毛', '泌尿系统', '体重管理', '幼宠与老年', '适口性', '加工工艺', '保质期与包装', '标签与宣称', '检测与安全', '市场与消费', '法规与准入',
      // 与「大板块 → 小板块」对齐的细分话题：让文章能直接落到具体小板块，而不是只落在「加工工艺」这种大筐里
      '动物源原料', '植物源原料', '功能性原料', '昆虫与新型蛋白', '原料掺假与鉴别',
      '膨化工艺', '烘焙工艺', '冻干工艺', '湿粮与猫条', '咬胶与零食', '适口性工艺', '设备与产线'],
    dict: ['粗蛋白', '粗脂肪', '粗纤维', '粗灰分', '水分', '牛磺酸', '赖氨酸', '蛋氨酸', '色氨酸', '精氨酸', 'Omega-3', 'EPA', 'DHA', '益生菌', '益生元', '果寡糖', '甘露寡糖', '抗氧化', '排毛', '化毛', '靓毛', '泌尿', '适口性', '消化率', '膨化', '烘焙', '冻干', '湿粮', '干粮', '诱食剂', '霉菌毒素', '沙门氏菌', 'AAFCO', 'FEDIAF', 'NRC', '代谢能', '钙磷比', '宠物食品', '内脏', '副产物', '豆类', '膳食纤维', '猫条', '咬胶', '洁齿', '绿唇贝', '卵磷脂', '辅酶Q10'],
  },
  general: {
    name: '通用（科技与商业）',
    entityTypes: ['公司组织', '人物', '产品', '技术概念', '市场指标', '政策法规', '事件'],
    topics: ['技术趋势', '产品发布', '市场格局', '政策法规', '商业模式', '人物观点', '数据指标', '风险事件'],
    dict: ['市场规模', '同比增长', '渗透率', '毛利率', '供应链', '监管', '合规', '人工智能', '大模型', '国产替代', '出口', '消费降级'],
  },
};

export const DEFAULT_PRESET = 'petfood';

export function getPreset(key) {
  return DOMAIN_PRESETS[key] || DOMAIN_PRESETS[DEFAULT_PRESET];
}

/**
 * 归一化一篇分析记录。无论来自 LLM 还是规则引擎，落库前必须过这一层，
 * 保证下游（图谱、导出、图表）拿到的字段永远存在且类型正确。
 */
export function normalizeAnalysis(input, article, opts = {}) {
  const preset = opts.preset || getPreset(opts.presetKey);
  const src = input && typeof input === 'object' ? input : {};

  const str = (v, d = '') => (typeof v === 'string' ? v.trim() : Array.isArray(v) ? v.map((x) => String(x).trim()).filter(Boolean).join('') : d);
  const num = (v, d = 0) => (Number.isFinite(Number(v)) ? Number(v) : d);

  const normLevel = (v) => {
    const s = String(v || '').toUpperCase().trim();
    if (/^L?[1-5]$/.test(s)) return `L${s.replace('L', '')}`;
    if (LEVEL_MAP[s]) return s;
    return 'L5';
  };

  const normCategory = (v) => {
    const s = String(v || '').toLowerCase().trim();
    if (CATEGORY_MAP[s]) return s;
    const hit = PRIMARY_CATEGORIES.find((c) => c.name === v || String(v).includes(c.name));
    return hit ? hit.id : 'opinion';
  };

  const keypoints = (Array.isArray(src.keypoints) ? src.keypoints : [])
    .map((k) => (typeof k === 'string' ? { text: k } : k || {}))
    .map((k) => ({
      id: str(k.id) || `kp-${Math.random().toString(36).slice(2, 8)}`,
      text: str(k.text),
      evidenceLevel: normLevel(k.evidenceLevel || k.level),
      quote: str(k.quote || k.sourceQuote),
      paraIndex: num(k.paraIndex, -1),
      tags: Array.isArray(k.tags) ? k.tags.map((t) => String(t).trim()).filter(Boolean).slice(0, 6) : [],
      // 证据颗粒度六字段。**给不出就是空**（见 evidence.js）——这里不做任何默认值兜底，
      // 空值在界面上会被显式标成「未识别」，兜一个默认值反而会把它藏起来。
      evidence: normalizeEvidenceMeta(k.evidence || k),
    }))
    .filter((k) => k.text.length >= 4)
    .slice(0, 12);

  const entities = (Array.isArray(src.entities) ? src.entities : [])
    .map((e) => (typeof e === 'string' ? { name: e } : e || {}))
    .map((e) => ({
      name: str(e.name),
      type: preset.entityTypes.includes(e.type) ? e.type : (e.type ? String(e.type) : '其他'),
      note: str(e.note || e.desc),
      mentions: Math.max(1, num(e.mentions, 1)),
      alias: Array.isArray(e.alias) ? e.alias.map((a) => String(a).trim()).filter(Boolean).slice(0, 5) : [],
    }))
    .filter((e) => e.name.length >= 2 && e.name.length <= 40)
    .slice(0, 40);

  const claims = (Array.isArray(src.claims) ? src.claims : [])
    .map((c) => (typeof c === 'string' ? { claim: c } : c || {}))
    .map((c) => ({
      claim: str(c.claim || c.text),
      subject: str(c.subject || c.entity),
      stance: ['支持', '反对', '中性', '限定'].includes(c.stance) ? c.stance : '中性',
      evidenceLevel: normLevel(c.evidenceLevel || c.level),
      quote: str(c.quote),
      qualifier: str(c.qualifier),
      // 转述他人说法 / 绝对化表述：不参与立场对照，只作为待核项
      unverified: Boolean(c.unverified || c.relayed),
      unverifiedReason: str(c.unverifiedReason),
      evidence: normalizeEvidenceMeta(c.evidence || c),
    }))
    .filter((c) => c.claim.length >= 4)
    .slice(0, 20);

  const todos = (Array.isArray(src.todoItems || src.todo) ? (src.todoItems || src.todo) : [])
    .map((t) => (typeof t === 'string' ? { item: t } : t || {}))
    .map((t) => ({ item: str(t.item || t.text), reason: str(t.reason) }))
    .filter((t) => t.item.length >= 2)
    .slice(0, 15);

  const topics = dedupeStrings(
    (Array.isArray(src.topics) ? src.topics : []).concat(
      Array.isArray(src.domainTags) ? src.domainTags : []
    ),
    preset.topics
  ).slice(0, 8);

  const confidenceMap = { 高: '高', 中: '中', 低: '低' };
  const confidence = confidenceMap[src.confidence] || '中';

  return {
    tldr: str(src.tldr || src.summary || src.oneLine),
    keypoints,
    entities,
    claims,
    todoItems: todos,
    primaryCategory: normCategory(src.primaryCategory || src.category),
    topics,
    confidence,
    // 平均证据等级：要点-level 加权中位数
    evidenceLevel: keypoints.length
      ? EVIDENCE_LEVELS[
          Math.max(
            0,
            Math.min(
              4,
              4 - Math.round(
                keypoints.reduce((s, k) => s + (LEVEL_WEIGHT[k.evidenceLevel] || 1), 0) / keypoints.length - 1
              )
            )
          )
        ].id
      : 'L5',
    analyzedAt: new Date().toISOString(),
    engine: opts.engine || 'rule',
    model: opts.model || '',
    // 词表/字段结构的版本号。它回答的是「这份结论是用哪一版规则产出的」——
    // 没有它，词表改版后重新解析，旧结论被覆盖，就再也分不清
    // 「结论变了」是因为**词表变了**、**模型换了**，还是**文章本身被改了**。
    schemaVersion: ANALYSIS_VERSION,
  };
}

/* ------------------------- 抽取结果的版本化与比对 ------------------------- */

/** 单条文本的留档上限：旧版摘要只服务「变了没、变在哪」，不服务全文复现。 */
const SNAP_TEXT_MAX = 120;

/**
 * 一次抽取结果的**摘要快照**。用于在覆盖前把上一版留一份。
 *
 * 刻意只留**摘要**不留全文（与「集约化」的原则一致）：
 * 留全文会让 `articles.json` 随重解析次数线性膨胀，而它已是最大的单点。
 * 一层摘要已足够回答本次要回答的两个问题 ——「变了没」和「变在哪一类字段」。
 */
/**
 * 快照里每条论断额外带一份证据颗粒度的**非空字段**。
 *
 * 只留非空字段的理由：这些字段里有两个是自由文本（亚组限定 / 利益相关），
 * 全留会让每条论断无论有没有信息都背上六个键 —— 而快照要在一篇文章里放 20 条论断。
 * 非空即留，既保住了「变没变、变在哪一栏」，又让绝大多数条目只多几字节。
 *
 * ⚠ 要点（`keypoints`）在快照里**仍是纯字符串**，不带颗粒度字段：
 * 快照的用途是回答「变了没、变在哪一类」，而论断（claims）带 subject/stance，
 * 本来就是判断变化的那一层；要点保持字符串可以让快照体积不因本轮扩容而翻倍。
 */
function evidenceOf(entry) {
  const ev = normalizeEvidenceMeta(entry?.evidence || entry || {});
  const out = {};
  for (const [k, v] of Object.entries(ev)) {
    if (k === 'sampleSize') { if (v >= 1) out[k] = v; continue; }
    if (String(v || '').trim()) out[k] = v;
  }
  return out;
}

export function analysisSnapshot(an) {
  if (!an || typeof an !== 'object') return null;
  const cut = (v) => {
    const s = String(v ?? '').replace(/\s+/g, ' ').trim();
    return s.length > SNAP_TEXT_MAX ? `${s.slice(0, SNAP_TEXT_MAX)}…` : s;
  };
  const keypoints = (Array.isArray(an.keypoints) ? an.keypoints : [])
    .map((k) => cut(typeof k === 'string' ? k : k?.text)).filter(Boolean);
  const claims = (Array.isArray(an.claims) ? an.claims : [])
    .map((c) => ({
      claim: cut(typeof c === 'string' ? c : c?.claim),
      subject: cut(typeof c === 'object' ? c?.subject : ''),
      stance: String((typeof c === 'object' && c?.stance) || '').trim(),
      evidenceLevel: String((typeof c === 'object' && c?.evidenceLevel) || '').trim(),
      ev: typeof c === 'object' && c ? evidenceOf(c) : {},
    }))
    .filter((c) => c.claim);
  const topics = [...new Set((Array.isArray(an.topics) ? an.topics : []).map((t) => String(t).trim()).filter(Boolean))];

  return {
    // 0 表示「本字段存在之前产出的结论」—— 不假装它等于当前版本
    schemaVersion: Number(an.schemaVersion) || 0,
    engine: String(an.engine || ''),
    model: String(an.model || ''),
    analyzedAt: String(an.analyzedAt || ''),
    evidenceLevel: String(an.evidenceLevel || ''),
    primaryCategory: String(an.primaryCategory || ''),
    tldr: cut(an.tldr),
    topics: topics.slice(0, 8),
    keypoints: keypoints.slice(0, 12),
    claims: claims.slice(0, 20),
    entityCount: Array.isArray(an.entities) ? an.entities.length : 0,
  };
}

/**
 * 比对两次抽取结果，并把「为什么变」尽量归因到具体那一项。
 *
 * ⚠ 归因只做**能确证的**那一层：版本/引擎/模型这三项是记录在案的事实，直接比即可。
 * 三者都没变却仍有差异时，只能如实说「同样的规则重跑出了不同结果」——
 * 那可能是模型的不确定性、也可能是文章本身被重新抓过，**不猜是哪一个**。
 */
export function diffAnalysis(prev, next, opts = {}) {
  const a = analysisSnapshot(prev);
  const b = analysisSnapshot(next);
  if (!a || !b) return null;

  const causes = [];
  if (a.schemaVersion !== b.schemaVersion) causes.push('schema');
  if (a.engine !== b.engine) causes.push('engine');
  if (a.model !== b.model) causes.push('model');

  const listDiff = (x = [], y = []) => {
    const xs = new Set(x);
    const ys = new Set(y);
    return {
      before: x.length,
      after: y.length,
      added: y.filter((v) => !xs.has(v)),
      removed: x.filter((v) => !ys.has(v)),
    };
  };

  const keypoints = listDiff(a.keypoints, b.keypoints);
  const topics = listDiff(a.topics, b.topics);

  // 论断按**原文**匹配：文本一字不差才算「同一条」。
  // 用相似度匹配会把「改写过的论断」误判成「立场翻转」，那种错误比漏报更糟。
  const claimKeep = new Map(a.claims.map((c) => [c.claim, c]));
  const claimNew = new Map(b.claims.map((c) => [c.claim, c]));
  const stanceChanges = [];
  for (const [text, nb] of claimNew) {
    const pb = claimKeep.get(text);
    if (pb && pb.stance && nb.stance && pb.stance !== nb.stance) {
      stanceChanges.push({ claim: text, subject: nb.subject, from: pb.stance, to: nb.stance });
    }
  }

  // 证据颗粒度的变化单独一栏。它回答的是一个**立场没变但结论分量变了**的问题：
  // 「同一句论断，上一版抽出的是『32 只猫的梯度剂量试验』，这一版什么也没抽到」——
  // 立场自然是「支持」，两版看起来一样，但实际上第二版再也支撑不了同一个结论。
  // 这类变化如果混进「立场变更」，会被读成结论翻转；单独列出才不会被误读。
  const evidenceChanges = [];
  for (const [text, nb] of claimNew) {
    const pb = claimKeep.get(text);
    if (!pb) continue;
    const from = pb.ev || {};
    const to = nb.ev || {};
    const keys = [...new Set([...Object.keys(from), ...Object.keys(to)])].sort();
    const fields = keys.filter((k) => String(from[k] ?? '') !== String(to[k] ?? ''));
    if (!fields.length) continue;
    evidenceChanges.push({
      claim: text, subject: nb.subject, fields,
      from: Object.fromEntries(fields.map((k) => [k, from[k] ?? ''])),
      to: Object.fromEntries(fields.map((k) => [k, to[k] ?? ''])),
    });
  }
  const claims = {
    ...listDiff(a.claims.map((c) => c.claim), b.claims.map((c) => c.claim)),
    stanceChanges,
  };

  const level = { from: a.evidenceLevel, to: b.evidenceLevel, changed: a.evidenceLevel !== b.evidenceLevel };
  const category = { from: a.primaryCategory, to: b.primaryCategory, changed: a.primaryCategory !== b.primaryCategory };
  const tldrChanged = a.tldr !== b.tldr;

  const changed = Boolean(
    keypoints.added.length || keypoints.removed.length
    || claims.added.length || claims.removed.length || stanceChanges.length || evidenceChanges.length
    || topics.added.length || topics.removed.length
    || level.changed || category.changed || tldrChanged
  );

  return {
    from: { schemaVersion: a.schemaVersion, engine: a.engine, model: a.model, analyzedAt: a.analyzedAt },
    to: { schemaVersion: b.schemaVersion, engine: b.engine, model: b.model, analyzedAt: b.analyzedAt },
    causes,
    causeText: causeTextOf(causes, a, b),
    changed,
    counts: {
      keypoints: { before: keypoints.before, after: keypoints.after },
      claims: { before: claims.before, after: claims.after },
      topics: { before: topics.before, after: topics.after },
      entities: { before: a.entityCount, after: b.entityCount },
    },
    addedKeypoints: keypoints.added.slice(0, 6),
    removedKeypoints: keypoints.removed.slice(0, 6),
    addedTopics: topics.added.slice(0, 8),
    removedTopics: topics.removed.slice(0, 8),
    addedClaims: claims.added.slice(0, 6),
    removedClaims: claims.removed.slice(0, 6),
    stanceChanges: stanceChanges.slice(0, 6),
    evidenceChanges: evidenceChanges.slice(0, 6),
    level,
    category,
    tldrChanged,
    comparedAt: String(opts.now || new Date().toISOString()),
  };
}

function causeTextOf(causes, a, b) {
  const bits = [];
  if (causes.includes('schema')) bits.push(`抽取规则版本 ${a.schemaVersion || '（未标）'} → ${b.schemaVersion}`);
  if (causes.includes('engine')) bits.push(`引擎 ${a.engine || '（未标）'} → ${b.engine}`);
  if (causes.includes('model')) bits.push(`模型 ${a.model || '（未标）'} → ${b.model}`);
  if (bits.length) return bits.join('；');
  return '规则版本、引擎、模型都没变 —— 同样条件下重跑出现了差异，需人工判断是模型不确定性还是原文被重新抓取过';
}

/** 「未标版本」的说明文字。它出现的地方很多（接口 notes、前端卡片），措辞必须一致。 */
export const UNVERSIONED_NOTE = '「未标版本」= 加上版本字段**之前**产出的结论（当时还没有这个字段）。它既不等于当前版本，也不代表结论有问题 —— 只是无从判断它出自哪一版规则。';

/**
 * 全库的「抽取结果版本状态」汇总。纯函数，便于单测与多入口复用。
 *
 * 它回答的是**规则或模型换代之后**那一刻的问题：「多少篇的结论变了、变化能不能
 * 用版本差异解释」。数据来自每篇在覆盖前留下的那一层旧版摘要（见 store.upsertArticle）。
 */
export function summarizeAnalysisVersions(articles = [], opts = {}) {
  const list = Array.isArray(articles) ? articles : [];
  const cur = Number(opts.currentVersion) || ANALYSIS_VERSION;
  const limit = Math.max(1, Math.min(500, Number(opts.limit) || 20));

  const stats = {
    total: list.length, analyzed: 0, unversioned: 0, outdated: 0,
    withHistory: 0, changed: 0, unchanged: 0,
  };
  const changes = [];
  for (const a of list) {
    const an = a?.analysis;
    if (!an) continue;
    stats.analyzed++;
    const v = Number(an.schemaVersion) || 0;
    if (!v) stats.unversioned++;
    else if (v < cur) stats.outdated++;
    if (!a.analysisDiff) continue;
    stats.withHistory++;
    if (a.analysisDiff.changed) stats.changed++; else stats.unchanged++;
    changes.push({
      id: a.id,
      title: a.title || '无标题',
      account: a.account || '',
      reanalyzedAt: a.reanalyzedAt || a.analysisDiff.comparedAt || '',
      ...a.analysisDiff,
    });
  }
  // 最近重抽的排前面：刚跑完一批时，想看的就是这批的结果
  changes.sort((x, y) => String(y.reanalyzedAt).localeCompare(String(x.reanalyzedAt)));

  return {
    currentVersion: cur,
    stats,
    changes: changes.slice(0, limit),
    returned: Math.min(limit, changes.length),
  };
}

function dedupeStrings(arr, allowed) {
  const set = new Set();
  for (const a of arr) {
    const s = String(a || '').trim();
    if (!s) continue;
    if (s.length > 30) continue;
    if (!allowed.includes(s)) continue; // 只允许预设话题，避免失控的自由标签
    set.add(s);
  }
  return [...set];
}
