/* eslint-disable */
/**
 * lib/sources/normalize.cjs — 多源记录的统一形状（canonical record）
 *
 * 为什么需要这一层（v4.15 新增，对应 GitHub 调研的 A/P0 差距）：
 *   旧实现只有一个采集函数 `searchKuluer()`，记录形状是**在采集循环里就地拼出来的**，
 *   等于「站点 DOM 的形状」直接泄漏成了「全链路的数据契约」。接入多源后若各连接器各自拼
 *   字段，下游 rank-records / evidence / assemble-report 会同时面对 4 种方言。
 *
 * 因此本层的职责是**唯一**的形状权威：
 *   ① 连接器只负责把自家响应映射成「半成品」，缺字段一律填 null（不得省略 key）；
 *   ② 本层补齐 idx/keyword/domain/provenance 等派生字段，并保证**每个 key 都存在**；
 *   ③ 新增字段一律**只加不改** —— 现有 12 个字段的口径一个字都不动，
 *      否则 459 项闸门里所有依赖记录形状的用例会集体红。
 *
 * 字段口径（★ 不改的 12 个）：
 *   titleEn / titleZh / authors / source / year / domain / abstractEn / abstractZh
 *   citedBy / paperUrl / sourceUrl / doiFromUrl / translatedBySite / translateStatus
 * 本轮新增（只加）：
 *   doi / pmid / pmcid / oaStatus / pubType / provenance
 *
 * ⚠️ `translateStatus` 对 HTTP 源一律为 **null**（不是 'not_attempted'）：
 *   prisma.cjs:176 的判据是 `if (r.translateStatus && r.translateStatus !== 'ok')`，
 *   只有 null 会被跳过；引入新枚举值会把「本来就没有译文」误记成 PRISMA 异常行。
 */
'use strict';

/** 记录的全字段清单（顺序即 JSON 落盘顺序，便于人工比对与 git diff） */
const RECORD_KEYS = Object.freeze([
  'idx', 'keyword', 'page',
  'titleEn', 'titleZh', 'authors', 'source', 'year', 'domain',
  'abstractEn', 'abstractZh', 'citedBy', 'paperUrl', 'sourceUrl', 'doiFromUrl',
  'translatedBySite', 'translateStatus',
  // ── v4.15 新增 ──
  'doi', 'pmid', 'pmcid', 'oaStatus', 'pubType',
  'provenance',
]);

/** 空白/纯空白 → null；非字符串一律 null（防止源端给数字型 title 污染下游 .trim()） */
function asText(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).replace(/\s+/g, ' ').trim();
  return s || null;
}

/** 年份：容忍 "2020"、"2020-01-01"、2020；非法 → null（绝不臆造） */
function asYear(v) {
  if (v === null || v === undefined || v === '') return null;
  const m = String(v).match(/(1[5-9]\d{2}|20\d{2}|21\d{2})/);
  return m ? Number(m[1]) : null;
}

/** DOI 归一：去 URL 前缀/协议/dx.、全小写、去尾部标点。跨源去重的第一顺位键 */
function normDoi(v) {
  if (!v) return null;
  let s = String(v).trim().toLowerCase();
  s = s.replace(/^https?:\/\/(dx\.)?doi\.org\//, '');
  s = s.replace(/^doi:\s*/, '');
  s = s.replace(/[\s.]+$/, '');
  return /^10\.\d{4,9}\/\S+$/.test(s) ? s : null;
}

const STOP = new Set(['the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'were', 'its', 'not']);

/**
 * 英式/美式拼写等价表（**只收学术标题高频对**，不做通用折叠）。
 *
 * 为什么必须有（2026-10-26 实测踩到）：跨源去重时无 DOI 要退回标题键，而
 * `Effects of dietary **fibre** on hairball excretion`（EPMC）与
 * `Effects of Dietary **Fiber** on Hairball Excretion`（Crossref）折叠后键不同 ⇒ 同一篇被算两条。
 * 兽医/营养文献里 fibre/fiber、faecal/fecal、oesophageal/esophageal 成对出现是常态。
 *
 * 为什么用**白名单**而不是通用规则（如 our→or / re→er）：
 *   通用规则会把 there→ther、where→wher、store→stor 一并折叠，两边同样折叠虽不影响匹配，
 *   却让两条不同的标题有概率撞键 —— 而「误合并两条不同文献」比「漏合并」严重得多
 *   （前者直接污染证据表，后者只是多一行重复）。故取可控、可审计、可逐条验证的方案。
 */
const SPELLING_EQUIV = Object.freeze({
  // -re / -er
  fibre: 'fiber', fibres: 'fibers', litre: 'liter', metre: 'meter', centre: 'center', centres: 'centers',
  // -our / -or
  colour: 'color', colours: 'colors', behaviour: 'behavior', behaviours: 'behaviors',
  tumour: 'tumor', tumours: 'tumors', flavour: 'flavor', odour: 'odor', favours: 'favors',
  // -ae / -e
  anaemia: 'anemia', anaemic: 'anemic', diarrhoea: 'diarrhea', oestrus: 'estrus', oestrogen: 'estrogen',
  haemoglobin: 'hemoglobin', haemorrhage: 'hemorrhage', gynaecology: 'gynecology',
  // 双元音 ae / oe
  faecal: 'fecal', faeces: 'feces', caecal: 'cecal', caecum: 'cecum',
  oedema: 'edema', oesophageal: 'esophageal', oesophagus: 'esophagus',
  paediatric: 'pediatric', orthopaedic: 'orthopedic',
  // 其他高频
  sulphur: 'sulfur', aluminium: 'aluminum', programme: 'program', defence: 'defense',
  analyse: 'analyze', analysed: 'analyzed', catalogue: 'catalog', grey: 'gray',
});

/** 单复数/词尾归一：让 fibers 与 fiber、effects 与 effect 撞上同一个键 */
function stemWord(w) {
  const base = SPELLING_EQUIV[w] || w;
  if (base.length <= 4) return base;                    // 短词不削，避免 age→ag 这类事故
  if (base.endsWith('ies') && base.length > 5) return base.slice(0, -3) + 'y';
  if (base.endsWith('sses')) return base.slice(0, -2);  // classes → class
  if (base.endsWith('s') && !base.endsWith('ss') && !base.endsWith('us')) return base.slice(0, -1);
  return base;
}

/** 标题归一键：折叠拼写差异 + 去停用词/短词/单复数。用于无 DOI 时的跨源合并 */
function normTitleKey(t) {
  return String(t || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(w => w && w.length > 2 && !STOP.has(w))
    .map(stemWord)
    .join(' ');
}

/**
 * 剥掉 Crossref 摘要里的 JATS 标签。
 * 实测：Crossref 的 `abstract` 是 `<jats:p>...</jats:p>` 形态，且常带 `<jats:italic>` 等内联标签；
 * 不剥会在报告里直接显示成尖括号标签（这是「拿到摘要」与「能用摘要」的差别）。
 */
function stripJats(s) {
  if (!s) return null;
  let t = String(s);
  t = t.replace(/<jats:title>([\s\S]*?)<\/jats:title>/gi, ' $1: ');
  t = t.replace(/<[^>]+>/g, ' ');
  t = t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"').replace(/&#x?[0-9a-f]+;/gi, ' ');
  return asText(t);
}

/**
 * OpenAlex 的摘要编码是「倒排索引」：{词: [位置...]}。
 * 必须按位置重排才能还原成句子 —— 直接 Object.keys() 拼出来是乱序词袋，看着像摘要但读不通。
 * 实测（2026-10-26）：还原后 1728 字符的甘蔗纤维那篇与 Europe PMC 的 abstractText 一致。
 */
function abstractFromInvertedIndex(inv) {
  if (!inv || typeof inv !== 'object') return null;
  const pos = [];
  for (const [w, ps] of Object.entries(inv)) {
    if (!Array.isArray(ps)) continue;
    for (const p of ps) if (Number.isInteger(p)) pos.push([p, w]);
  }
  if (!pos.length) return null;
  pos.sort((a, b) => a[0] - b[0]);
  return asText(pos.map(x => x[1]).join(' '));
}

/** 从 URL 猜域名（现有 domain 字段口径：byline 解析出的站点域名，这里对齐） */
function domainOf(url) {
  if (!url) return null;
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return null; }
}

/**
 * 从「检索式」抽词袋。
 * 为什么必须有：实测（2026-10-26）Crossref 的 `query.bibliographic` **完全不解析布尔运算符** ——
 *   传 `(cat OR feline) AND hairball` 与传 `cat feline hairball` 得到**逐字相同**的
 *   total(358659) 与 top4 结果。即 OR/AND/括号被当成噪音，检索式越复杂它反而越偏。
 * 故 bag 型源必须先剥离运算符，只留实词。
 */
function booleanToBag(q) {
  if (!q) return '';
  const toks = String(q)
    .replace(/[()"]/g, ' ')
    .replace(/\b(AND|OR|NOT|and|or|not)\b/g, ' ')
    .split(/\s+/)
    .map(w => w.trim())
    .filter(w => w && !/^[A-Z_]+:/.test(w) && !STOP.has(w.toLowerCase()));
  // 去重但保留首次出现顺序：重复词会让 Crossref 的软匹配分数被同一词反复加权
  const seen = new Set();
  const out = [];
  for (const w of toks) {
    const k = w.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(w);
  }
  return out.join(' ');
}

/**
 * 补齐一条记录：保证 RECORD_KEYS 全部存在，派生字段算好。
 * @param {object} raw  连接器产出的半成品（必须含 titleEn）
 * @param {object} ctx  { keyword, idx, page, sourceId, sourceLabel, rank, countSemantics }
 */
function canonicalRecord(raw, ctx) {
  const c = ctx || {};
  const doi = normDoi(raw.doi) || normDoi(raw.doiFromUrl);
  const sourceUrl = asText(raw.sourceUrl) || (doi ? 'https://doi.org/' + doi : null);
  const rec = {
    idx: Number.isInteger(raw.idx) ? raw.idx : (c.idx == null ? null : c.idx),
    keyword: asText(raw.keyword) || asText(c.keyword),
    page: Number.isInteger(raw.page) ? raw.page : (c.page == null ? 1 : c.page),
    titleEn: asText(raw.titleEn),
    titleZh: asText(raw.titleZh),
    authors: asText(raw.authors),
    source: asText(raw.source),
    year: asYear(raw.year),
    domain: asText(raw.domain) || domainOf(sourceUrl) || domainOf(raw.paperUrl),
    abstractEn: asText(raw.abstractEn),
    abstractZh: asText(raw.abstractZh),
    citedBy: Number.isFinite(raw.citedBy) ? raw.citedBy : null,
    paperUrl: asText(raw.paperUrl),
    sourceUrl,
    doiFromUrl: doi ? 'https://doi.org/' + doi : null,
    // 记录级译文真值：HTTP 源天然无译文；只有站点自带的 AI 译文才置 true
    translatedBySite: raw.translatedBySite === true,
    translateStatus: raw.translateStatus === undefined ? null : raw.translateStatus,
    // ── 新增 ──
    doi,
    pmid: asText(raw.pmid),
    pmcid: asText(raw.pmcid),
    oaStatus: raw.oaStatus === undefined ? null : raw.oaStatus,   // true/false/null(未知) 三态
    pubType: asText(raw.pubType),
    provenance: {
      sourceId: c.sourceId || null,
      sourceLabel: c.sourceLabel || null,
      rank: Number.isInteger(c.rank) ? c.rank : null,
      countSemantics: c.countSemantics || null,
    },
  };
  return rec;
}

/** 记录是否「可用的检索命中」：无标题的记录对证据表毫无价值，必须能被识别出来 */
function isUsable(rec) {
  return !!(rec && rec.titleEn);
}

/**
 * 合并同一篇文献的两条来源记录（跨源去重后保留信息量更大的那份）。
 * 原则：**只填空，不覆盖已有值** —— 先到的来源（注册表顺序即优先级）说了算，
 * 避免低可信源把高可信源的正确字段改掉。
 */
function mergeInto(base, extra) {
  if (!base) return extra;
  if (!extra) return base;
  for (const k of RECORD_KEYS) {
    if (k === 'provenance') continue;
    const b = base[k];
    const e = extra[k];
    const bEmpty = b === null || b === undefined || b === '';
    if (bEmpty && !(e === null || e === undefined || e === '')) base[k] = e;
    else if (k === 'abstractEn' && typeof b === 'string' && typeof e === 'string' && e.length > b.length * 1.5) {
      // 摘要例外：更长的摘要通常是「有摘要」vs「只有一句」的差别，取长的
      base[k] = e;
    }
  }
  // 双源见证：PRISMA 需要知道同一篇被几个库命中（这是「去重前总数」的依据）
  base.provenance = base.provenance || {};
  const seen = base.provenance.alsoFoundIn || [];
  if (extra.provenance && extra.provenance.sourceId && extra.provenance.sourceId !== base.provenance.sourceId
      && !seen.includes(extra.provenance.sourceId)) {
    seen.push(extra.provenance.sourceId);
  }
  if (seen.length) base.provenance.alsoFoundIn = seen;
  return base;
}

module.exports = {
  RECORD_KEYS, SPELLING_EQUIV, canonicalRecord, isUsable, mergeInto,
  normDoi, normTitleKey, stemWord, asText, asYear, stripJats, abstractFromInvertedIndex,
  booleanToBag, domainOf,
};
