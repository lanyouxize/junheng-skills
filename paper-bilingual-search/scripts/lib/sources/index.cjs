/* eslint-disable */
/**
 * lib/sources/index.cjs — 源注册表（唯一的「有哪些源、各自能干什么」权威）
 *
 * 设计动因（对应 2026-10-26 GitHub 调研的 P0 差距）：
 *   我方原状 = 1 个源、硬编码在 `searchKuluer()` 里、无降级。而头部项目（paper-search-mcp 23 源、
 *   zotero-mcp 5.5k★）全部是「统一层 + 连接器层」。多源化的第一块砖不是「多写几个 fetch」，
 *   而是**先把契约固定下来**，否则 4 个连接器会各自发明字段与错误语义，调度器无从降级。
 *
 * 三条设计红线：
 *   ① 能力必须**声明**而非**假设**。最有价值的两条声明是：
 *      `countSemantics`（这个源的命中数能不能进 PRISMA）与
 *      `queryDialect`（这个源认不认布尔运算符）—— 这两条都是踩过坑才懂的（见 crossref.cjs 头注释）。
 *   ② 未注册的源 id **必须报错**，不得静默回落默认源。
 *      与 v4.1 修 `--site` 白名单同一理由：静默回落会让 summary/PRISMA 的元数据说谎。
 *   ③ 契约校验要能单独调用（`validateConnector`），供单测对**每个**连接器跑一遍，
 *      新增源忘记实现某个方法时在闸门里就红，而不是等到跑检索时才炸。
 */
'use strict';

const europepmc = require('./europepmc.cjs');
const crossref = require('./crossref.cjs');

/** 连接器契约的必填字段与类型（新增源若缺项，validateConnector 会点名） */
const CONTRACT = Object.freeze({
  id: 'string',
  label: 'string',
  kind: 'string',            // 'http' | 'browser'
  queryDialect: 'string',    // 'boolean'（可直传布尔式）| 'bag'（须转译为词袋）
  countSemantics: 'string',  // 'exact'（可进 PRISMA）| 'none'（禁止用于计数）
  capabilities: 'object',
  search: 'function',
});

const VALID = Object.freeze({
  kind: ['http', 'browser'],
  queryDialect: ['boolean', 'bag'],
  countSemantics: ['exact', 'none'],
});

/** 注册表。**顺序即默认优先级**：跨源去重时先到者说了算（见 normalize.mergeInto） */
const REGISTRY = Object.freeze({
  europepmc,
  crossref,
});

/** 预设组合：
 *   - `http`  = 不依赖浏览器的源，可在无 Edge/Chrome 的环境跑（CI 可用）
 *   - `all`   = 全部已注册源
 *   - `default` 与 `http` 同 —— 目前所有源都是 HTTP；站点源接入后此处要显式加回
 */
const PRESETS = Object.freeze({
  http: ['europepmc', 'crossref'],
  default: ['europepmc', 'crossref'],
  all: Object.keys(REGISTRY),
});

/**
 * 校验一个连接器是否满足契约。
 * @returns {{ok:boolean, id:string|null, errors:string[]}}
 */
function validateConnector(mod) {
  const errors = [];
  if (!mod || typeof mod !== 'object') return { ok: false, id: null, errors: ['连接器不是对象'] };
  for (const [k, t] of Object.entries(CONTRACT)) {
    const v = mod[k];
    if (typeof v !== t) errors.push('缺字段或类型错: ' + k + ' 应为 ' + t + '，实为 ' + (v === undefined ? 'undefined' : typeof v));
  }
  for (const [k, allowed] of Object.entries(VALID)) {
    if (typeof mod[k] === 'string' && !allowed.includes(mod[k])) {
      errors.push('取值非法: ' + k + '=' + JSON.stringify(mod[k]) + '，允许 ' + allowed.join('/'));
    }
  }
  if (mod.capabilities && typeof mod.capabilities === 'object') {
    const need = ['abstract', 'doi', 'oa', 'translate'];
    for (const k of need) {
      if (typeof mod.capabilities[k] !== 'boolean') errors.push('capabilities.' + k + ' 必须是布尔值（能力必须显式声明，不得省略）');
    }
  }
  return { ok: errors.length === 0, id: typeof mod.id === 'string' ? mod.id : null, errors };
}

/** 校验全部已注册源。供闸门一次性检查（新增源忘了实现 search 会在这里红） */
function validateAll() {
  const out = [];
  for (const [key, mod] of Object.entries(REGISTRY)) {
    const v = validateConnector(mod);
    if (v.id !== key) v.errors.push('注册键 "' + key + '" 与 id "' + v.id + '" 不一致');
    out.push({ key, ...v, ok: v.ok && v.id === key });
  }
  return out;
}

/**
 * 把用户输入解析成源列表。
 * 支持：'europepmc'、'europepmc,crossref'、'http'、'all'、'all,-crossref'（减号排除）。
 * 未知 id 一律抛错并给出可用清单 —— 绝不静默回落（红线②）。
 * @param {string|string[]} spec
 * @returns {string[]} 去重后的源 id 列表（保持输入顺序）
 */
function resolveSources(spec) {
  const raw = Array.isArray(spec) ? spec : String(spec == null ? '' : spec).split(',');
  const tokens = raw.map(s => String(s).trim()).filter(Boolean);
  if (!tokens.length) return PRESETS.default.slice();

  const out = [];
  const excluded = new Set();
  for (const tk of tokens) {
    if (tk.startsWith('-')) {
      const id = tk.slice(1).trim();
      if (!REGISTRY[id]) throw new Error('未知源（排除项）: ' + JSON.stringify(id) + '\n  可用: ' + Object.keys(REGISTRY).join(', '));
      excluded.add(id);
      continue;
    }
    if (PRESETS[tk]) { for (const id of PRESETS[tk]) if (!out.includes(id)) out.push(id); continue; }
    if (REGISTRY[tk]) { if (!out.includes(tk)) out.push(tk); continue; }
    throw new Error('未知源: ' + JSON.stringify(tk) + '\n  可用: ' + Object.keys(REGISTRY).join(', ')
      + '\n  预设: ' + Object.keys(PRESETS).join(', ') + '；排除用 -<id>（例: all,-crossref）');
  }
  const final = out.filter(id => !excluded.has(id));
  if (!final.length) {
    throw new Error('源列表为空（排除后无剩余）: ' + JSON.stringify(tokens) + '\n  可用: ' + Object.keys(REGISTRY).join(', '));
  }
  return final;
}

/** 取一个连接器；未注册返回 null（调用方决定报错方式，不在此处抛） */
function getSource(id) {
  return REGISTRY[id] || null;
}

/** 全部已注册源的元信息（不含函数，便于直接序列化进 summary/PRISMA） */
function listSources() {
  return Object.entries(REGISTRY).map(([id, m]) => ({
    id,
    label: m.label,
    kind: m.kind,
    queryDialect: m.queryDialect,
    countSemantics: m.countSemantics,
    capabilities: { ...m.capabilities },
    notes: m.notes || null,
  }));
}

module.exports = {
  REGISTRY, PRESETS, CONTRACT, validateConnector, validateAll,
  resolveSources, getSource, listSources, sourceIds: () => Object.keys(REGISTRY),
};
