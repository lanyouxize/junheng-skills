#!/usr/bin/env node
/* eslint-disable */
/**
 * doc-actions.cjs — 资料库 direct-edit action 的提交前预检（纯函数，零 IO / 零网络）
 *
 * 为什么要有这个模块
 * ------------------
 * direct-edit 契约里，**同一锚点的多条 insert_after 会按数组倒序落位**。
 * 2026-10-21 实测：61 条同锚 insert_after 提交后落成「十八…十四」，与数组顺序相反。
 * 此后改为「一条 action + content 内空行串联全部块」，落位才与数组同序。
 * 这条教训此前只写在项目记忆里 —— 记忆不会让机器拒绝错误输入，所以把它做成可执行判据。
 *
 * 契约（以 2026-10-21 / 10-24 共 14 份真实 actions JSON 为样本，type 取值仅三种）
 * --------------------------------------------------------------------------
 *   { type: 'insert_after',  id: <锚点块 id>, content: '<块1>\n\n<块2>…' }
 *   { type: 'insert_before', id: <锚点块 id>, content: '<块1>\n\n<块2>…' }
 *   { type: 'delete',        id: <被删块 id> }
 *
 * ⚠ delete 的 id 是「被删块」而不是锚点，(insert_after A, delete A) 语义不同、不算冲突。
 *
 * 方向性是**实测结论，不是推测**（2026-10-24，临时页 dGLW5PdQigMjD3PHsKuyxf）
 * ----------------------------------------------------------------------
 *   insert_after  × 2 同锚  ⇒ 落位 **倒序**（数组第 2 条先落），复现 2026-10-21 事故
 *   insert_before × 2 同锚  ⇒ 落位 **正序**（数组顺序 = 落位顺序）
 *   insert_before × 3 同锚  ⇒ 落位 **严格正序**（排除「两条恰好互换」的巧合）
 * ⇒ 冲突判定**只针对 insert_after**。对 insert_before 施加同一判据会误拒合法写法，
 *   而误报比漏报更糟（调用方会以为契约有问题，反而绕过预检）。
 */
'use strict';

const INSERT = 'insert_after';
const INSERT_BEFORE = 'insert_before';
const DELETE = 'delete';
const INSERT_TYPES = [INSERT, INSERT_BEFORE];
const KNOWN_TYPES = [INSERT, INSERT_BEFORE, DELETE];

// 会**倒序**落位的插入方向。实测只有 insert_after（见头注释三行实测表）；
// insert_before 是正序，多条目安全，不得纳入判据。
const ORDER_REVERSING_TYPES = [INSERT];

// 行首开标签。块有两种真实形态：跨行（<Paragraph> 换行 文本 换行 </Paragraph>）
// 与单行（<Paragraph>文本</Paragraph>），后者必须按「行内含闭标签」单独识别，
// 否则真实数据里大量单行块会被数成 0 —— 判据先读真实样本，再写正则。
const OPEN_RE = /^<([A-Za-z][A-Za-z0-9]*)(\s[^>]*)?>/;
const CLOSE_ONLY_RE = /^<\/([A-Za-z][A-Za-z0-9]*)>$/;
const SELF_CLOSE_RE = /\/>$/;

/** 归一化并校验 action 数组的形状；抛错即拒绝提交。 */
function normalizeActions(actions) {
  if (!Array.isArray(actions)) throw new Error('actions 必须是数组');
  return actions.map((a, i) => {
    if (!a || typeof a !== 'object') throw new Error('第 ' + i + ' 条不是对象');
    const type = String(a.type || '').trim();
    if (KNOWN_TYPES.indexOf(type) < 0) {
      throw new Error('第 ' + i + ' 条 type 未知：' + JSON.stringify(a.type) +
        '（已知：' + KNOWN_TYPES.join(' / ') + '；若为合法新 type，须先登记判据再放行）');
    }
    const id = String(a.id || '').trim();
    if (!id) throw new Error('第 ' + i + ' 条缺 id');
    if (INSERT_TYPES.indexOf(type) >= 0 && typeof a.content !== 'string') {
      throw new Error('第 ' + i + ' 条 ' + type + ' 缺 content');
    }
    return { type: type, id: id, content: a.content, index: i };
  });
}

/**
 * 数 content 里的**顶层块**个数（用括号深度，不用空行切分）。
 * 空行切分会在「块内含空行」时多算，因此改为逐行扫行首标签。
 * 单行块（开闭标签同一行）按行内闭合识别；嵌套块只计最外层。
 */
function countTopBlocks(content) {
  if (typeof content !== 'string') throw new Error('content 必须是字符串');
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  let depth = 0;
  let count = 0;
  for (const line of lines) {
    const t = line.trim();
    if (!t) continue;
    if (CLOSE_ONLY_RE.test(t)) {
      if (depth > 0) depth--;
      continue;
    }
    const open = OPEN_RE.exec(t);
    if (!open) continue;
    const tag = open[1];
    const tagName = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (SELF_CLOSE_RE.test(t)) {
      if (depth === 0) count++;
      continue;
    }
    if (new RegExp('</' + tagName + '>').test(t)) {
      // 单行整块：开闭在同一行，深度不变
      if (depth === 0) count++;
      continue;
    }
    if (depth === 0) count++;
    depth++;
  }
  return count;
}

/**
 * 找出「同一锚点被**倒序方向**命中 ≥2 次」的冲突项。
 * 只统计 ORDER_REVERSING_TYPES（当前仅 insert_after）；insert_before 正序落位，不计入。
 * 返回顺序 = 首次出现顺序（确定性），不按键名排序以免掩盖提交意图。
 */
function findAnchorCollisions(actions) {
  const list = normalizeActions(actions);
  const hits = new Map();
  for (const a of list) {
    if (ORDER_REVERSING_TYPES.indexOf(a.type) < 0) continue;
    if (!hits.has(a.id)) hits.set(a.id, { id: a.id, type: a.type, indexes: [] });
    hits.get(a.id).indexes.push(a.index);
  }
  const out = [];
  for (const h of hits.values()) {
    if (h.indexes.length >= 2) {
      out.push({ id: h.id, type: h.type, count: h.indexes.length, indexes: h.indexes.slice() });
    }
  }
  return out;
}

/**
 * 冲突即抛错。错误消息必须**点名锚点 + 方向 + 条数 + 修法**，否则调用方只能猜。
 */
function assertNoAnchorCollision(actions) {
  const bad = findAnchorCollisions(actions);
  if (bad.length === 0) return true;
  const detail = bad
    .map((b) => '锚点 ' + b.id + ' 被 ' + b.type + ' 命中 ' + b.count + ' 次（actions 序号 ' + b.indexes.join('/') + '）')
    .join('；');
  throw new Error(
    '同锚点多条 insert_after 会倒序落位：' + detail +
    '。修法：合并为**一条** insert_after，多块在 content 内用空行串联（见 planInsert）；' +
    'insert_before 多条为正序，可直接分条书写'
  );
}

/**
 * 把「锚点 + 若干块」编译成**一条** action —— 这是唯一被实测证明落位正确的写法。
 * 块数不守恒即抛错：说明调用方传进来的"一块"其实是多块，应拆开传。
 */
function planInsert(anchorId, blocks) {
  const aid = String(anchorId || '').trim();
  if (!aid) throw new Error('planInsert: 锚点 id 不能为空');
  if (!Array.isArray(blocks) || blocks.length === 0) {
    throw new Error('planInsert: blocks 必须是非空数组');
  }
  const parts = blocks.map((b, i) => {
    if (typeof b !== 'string' || !b.trim()) throw new Error('planInsert: 第 ' + i + ' 块为空');
    return b.trim();
  });
  const content = parts.join('\n\n');
  const n = countTopBlocks(content);
  if (n !== parts.length) {
    throw new Error('planInsert: 块数不守恒（入参 ' + parts.length + ' 块，编译后数出 ' + n + ' 块）');
  }
  return { type: INSERT, id: aid, content: content };
}

module.exports = {
  INSERT: INSERT,
  INSERT_BEFORE: INSERT_BEFORE,
  DELETE: DELETE,
  INSERT_TYPES: INSERT_TYPES,
  KNOWN_TYPES: KNOWN_TYPES,
  ORDER_REVERSING_TYPES: ORDER_REVERSING_TYPES,
  normalizeActions: normalizeActions,
  countTopBlocks: countTopBlocks,
  findAnchorCollisions: findAnchorCollisions,
  assertNoAnchorCollision: assertNoAnchorCollision,
  planInsert: planInsert,
};
