'use strict';
/**
 * lib/converge-state.cjs — 收敛状态的**跨运行记忆**：让同一个维度只被正经报一次（纯函数，零 IO）
 *
 * 解决什么：`convergence.cjs` 的追踪只活在**单次运行内**。跨运行它就失明了 ——
 *   同一个 `Kidney` 维度，今天跑是 `stalled`、明天跑还是 `stalled`，每份报告都写一遍，
 *   建议检索式也每份都给一遍。人读到第三遍时的自然反应是「早就知道了」，第四遍开始就不读了。
 *   真正需要跨运行区分的是四件事：
 *     ① 这个维度是**这次才发现**的，还是**上次就报过**的？
 *     ② 上次报过、这次还在 ⇒ 是不是**同一个结论**（`persistent`）？还是**变了**（support 动了）？
 *     ③ 上次判过收敛、这次又冒出来 ⇒ **回归**（`recurred`）：这是警示，说明上次的收敛不可信。
 *     ④ 上次报过、这次连影子都没有 ⇒ 真的解决了（`cleared` / `resolved`）。
 *
 * ★ 五态穷举、互斥、无「说不清」（`trend`，跨运行方向）：
 *   `new`        上次没有，这次有 —— 首次报告
 *   `persistent` 上次活着，这次还活着 —— **结论没变**（suppress 的候选）
 *   `resolved`   上次活着，这次末轮已缺席，但本次运行内出现过 —— 刚收敛
 *   `cleared`    上次活着，这次**连出现都没有**；或上次已收敛、这次仍没出现 —— 彻底消失
 *   `recurred`   上次**已判收敛**，这次又出现 —— 回归（★ 优先于 persistent，必须重报）
 *
 * ★ 两条判据不许含糊：
 *   ① `suppress`（建议检索式不再重复出）必须**同时**满足：`persistent` + `stalled` + `reportCount ≥ 2`。
 *      缺任一条都不抑制 —— 结论变了（support 动了）要报；刚回归要报；第一次要给式子。
 *   ② 指纹不符（`--topic` 变了）⇒ **拒绝合并**。拿另一个主题的 `stalled` 去抑制本主题的维度，
 *      会让「这个方向已经查过」的假记忆悄悄成立 —— 这是本模块唯一不可让步的闸门。
 *      语料规模（`corpus`）变化**不**拒绝（新增文献是正常演进），只标记 `corpusChanged` 供人判断。
 *
 * ★ 只读纪律（与 diagnose / query-plan / convergence 同源）：
 *   不改词表、不产提案、不发请求、**不碰文件系统** —— IO 全在 CLI 层（读一次、写一次），
 *   本模块只吃「已解析的对象」、吐「待序列化的对象」。源码守卫钉死：不得出现 fs/net/子进程。
 *
 * ★ v2：单文件多主题槽（2026-10-19，解决「换个词表就把上一个主题的记忆覆盖掉」）。
 *   v1 的状态文件是**单主题**的：同一路径跑另一个 `--topic` ⇒ 旧结论被整体覆盖
 *   （实测 `fix4-changed` 把 gutkidney 的 3 次历史清成 runs=1）。一个项目本来就该有多个主题，
 *   记忆不能互删。v2 把文件变成 `{version, savedAt, slots:[槽…]}`，每个主题一个槽：
 *     - 按**双键**匹配（`hash` + `topic`）：只看 hash 有碰撞风险，只看 topic 又无法识别「同一主题换了写法」；
 *     - 本主题无槽 ⇒ `none`（首次），**不是**拒绝 —— 其他主题的槽原样保留；
 *     - v1 文件读进来自动迁移（单槽），数据零丢失；
 *     - 槽数上限 `MAX_SLOTS`，淘汰最旧的**必须留痕**（`evicted`），静默丢记忆等于数据损坏。
 */

const crypto = require('crypto');

const VERSION = 'dim-converge-state/v2';
/** v1 格式（单主题平铺）。读到时自动按「单槽」迁移，**不得**因为升版就失忆。 */
const V1_VERSION = 'dim-converge-state/v1';
/** 一个状态文件最多保留多少个主题槽（超出淘汰最旧的，且必须留痕）。 */
const MAX_SLOTS = 20;
/** 判据标识透传（与 convergence 同源，报告中并列显示，便于事后核对用的是哪条判据）。 */
const CRITERION = 'cluster-absent-or-below-min-support';

/** 跨运行方向（`trend`）五态。 */
const TREND = Object.freeze({
  NEW: 'new',
  PERSISTENT: 'persistent',
  RESOLVED: 'resolved',
  CLEARED: 'cleared',
  RECURRED: 'recurred',
});

/** 上次状态的可用性（读取结果，四态穷举）。 */
const PRIOR = Object.freeze({
  NONE: 'none',           // 文件不存在 ⇒ 首次运行（不是错误）
  OK: 'ok',               // 版本与指纹都匹配，可合并
  REJECTED: 'rejected',   // 版本或指纹不符 ⇒ **不合并**，但仍覆盖写回新状态
  CORRUPT: 'corrupt',     // 文件存在但解析失败 ⇒ 同上
});

/** 抑制阈值：报过这么多轮之后，同一结论不再重复出式子。 */
const SUPPRESS_MIN_REPORTS = 2;

/** 报告措辞（渲染层唯一一份中文；lib 侧只给机器码 + 简短 note 骨架）。 */
const TREND_NOTE = {
  new: '首次报告',
  persistent: '上次已报，结论未变',
  resolved: '本次已收敛',
  cleared: '已彻底消失',
  recurred: '★ 上次判过收敛，本次回归',
};

/**
 * 词表规范化：去空白、去空项、**排序**后拼接。
 * 排序是为了「同一组词换个顺序」不被当成不同主题（用户的输入顺序不承载语义）。
 */
function canonTopic(text) {
  return String(text == null ? '' : text)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .sort()
    .join('|');
}

/**
 * 主题指纹：判定「这是不是同一个问题」的唯一依据。
 * ★ `hash` **不参与判定**（只用完整 `topic` 字符串比对）—— 截断 hash 存在碰撞可能，
 *   一旦碰撞就会把不相关主题的历史当成本主题的历史，属于不可接受的假记忆。
 *   hash 仅用于报告里的短标识与人眼快速辨认。
 */
function fingerprintOf(input) {
  const o = input || {};
  const topic = canonTopic(o.topic);
  const corpus = Number.isInteger(o.corpus) ? o.corpus : null;
  const pick = o.pick == null ? null : String(o.pick);
  const hash = crypto.createHash('sha1').update(topic).digest('hex').slice(0, 12);
  return { topic, hash, corpus, pick };
}

/**
 * 取出状态文件里的「槽数组」。
 * v2 ⇒ `slots`；v1 ⇒ 文件本身就是一个槽（迁移）；其他 ⇒ 空（由调用方判版本不符）。
 */
function slotsOf(data) {
  if (!data || typeof data !== 'object') return [];
  if (Array.isArray(data.slots)) return data.slots.filter(s => s && typeof s === 'object');
  if (data.version === V1_VERSION || Array.isArray(data.clusters)) return [data];
  return [];
}

/**
 * 槽的主题键：v2 存 `topic`，v1 存 `fingerprint.topic`。
 * ★ 槽内的 topic 由 `buildState` 写成**规范形**（已排序的 `|` 连接），故这里直接用 `canonTopic`。
 *   曾经写过一个「先把 `|` 还原成逗号再规范化」的包装，实测**恒等于** `canonTopic`
 *   （规范形本身已排序、单项 split 不变）⇒ 冗余代码，删掉。
 *   手改成非规范形（如 `b|a`）的后果是「视为新主题、多一个槽」—— 属安全侧，不会误合并。
 */
function slotTopic(s) {
  if (!s) return '';
  return canonTopic(s.topic != null ? s.topic : ((s.fingerprint || {}).topic));
}

/** 槽的 hash（v1 从 fingerprint 取）。 */
function slotHash(s) {
  if (!s) return '';
  return s.hash != null ? String(s.hash) : String((s.fingerprint || {}).hash || '');
}

/**
 * 校验上次状态是否可用于本次运行。
 * @param {Object} input `{exists:boolean, data:any, error:string|null}`（CLI 层读文件的结果）
 * @param {Object} fp `fingerprintOf()` 的产物
 * @returns {Object} `{status, reason, runs, savedAt, clusters, corpusChanged, fingerprint, format, otherSlots}`
 *   ★ `status !== 'ok'` 时 `clusters` 恒为空数组 —— 调用方不必再判一次「能不能用」。
 *   ★ v2 下「本主题无槽」是 `none`（首次），**不是** `rejected` —— 其他主题的槽原样保留，不算冲突。
 */
function readPrior(input, fp) {
  const i = input || {};
  const base = {
    status: PRIOR.NONE, reason: '', runs: 0, savedAt: null,
    clusters: [], corpusChanged: false, fingerprint: null,
    format: null, otherSlots: 0,
  };
  if (!i.exists) {
    base.reason = '首次运行（无历史状态文件）⇒ 全部维度按 new 报。';
    return base;
  }
  if (i.error || i.data == null || typeof i.data !== 'object' || Array.isArray(i.data)) {
    base.status = PRIOR.CORRUPT;
    base.reason = '历史状态无法解析（' + (i.error || '内容不是 JSON 对象') + '）⇒ 不合并，按首次运行处理并覆盖写回。';
    return base;
  }
  const d = i.data;
  if (d.version !== VERSION && d.version !== V1_VERSION) {
    base.status = PRIOR.REJECTED;
    base.reason = '历史状态版本不符（文件 ' + JSON.stringify(d.version) + '，当前 ' + VERSION + '）'
      + '⇒ 不合并（格式语义可能已变），覆盖写回。';
    return base;
  }
  const format = d.version === V1_VERSION ? 'v1' : 'v2';
  const slots = slotsOf(d);
  base.format = format;
  const nowTopic = (fp && fp.topic) || '';
  const nowHash = (fp && fp.hash) || '';
  // ★ 双键匹配：topic 必须一致；v2 还要求 hash 一致（hash 只作标识，单独不足以防串主题）
  const hit = slots.find(s => slotTopic(s) === nowTopic
    && (format === 'v1' || slotHash(s) === nowHash));
  if (!hit) {
    base.status = PRIOR.NONE;
    base.otherSlots = slots.length;
    base.reason = slots.length
      ? '本主题无历史（文件里还有 **' + slots.length + '** 个其他主题的槽，原样保留）⇒ 全部维度按 new 报。'
      : '首次运行（状态文件存在但还没有任何主题槽）⇒ 全部维度按 new 报。';
    return base;
  }
  if (!Array.isArray(hit.clusters)) {
    base.status = PRIOR.CORRUPT;
    base.reason = '历史状态的本主题槽缺 clusters 数组 ⇒ 不合并，覆盖写回。';
    return base;
  }
  const pfp = hit.fingerprint || {};
  base.status = PRIOR.OK;
  base.otherSlots = Math.max(0, slots.length - 1);
  base.runs = Number.isInteger(hit.runs) && hit.runs > 0 ? hit.runs : 1;
  base.savedAt = hit.savedAt == null ? null : String(hit.savedAt);
  base.fingerprint = pfp;
  base.clusters = hit.clusters
    .filter(c => c && c.key != null)
    .map(c => ({
      key: String(c.key),
      label: c.label == null ? String(c.key) : String(c.label),
      kind: c.kind == null ? null : String(c.kind),
      status: c.status == null ? null : String(c.status),
      support: typeof c.support === 'number' ? c.support : null,
      reportCount: Number.isInteger(c.reportCount) && c.reportCount > 0 ? c.reportCount : 1,
      supportSeries: Array.isArray(c.supportSeries) ? c.supportSeries.slice() : [],
    }));
  // 语料规模变化：不拒绝，但必须让人看见（新增文献后 support 变动是正常的，不是缺陷）
  if (fp && fp.corpus != null && pfp.corpus != null && pfp.corpus !== fp.corpus) {
    base.corpusChanged = true;
    base.reason = '语料规模已变（' + pfp.corpus + ' → ' + fp.corpus + ' 条）⇒ 仍合并，'
      + '但 support 变动可能来自新文献而非补词效果，判读时须分开。';
  }
  return base;
}

/**
 * 抑制判据（**唯一一份**，导出供单测直打）。
 * 三条同时成立才抑制：结论未变（persistent）+ 补词治不了（stalled）+ 已经报过至少一次。
 * ★ 缺任一条都不抑制：support 动了要报（有新信息）、回归要报（警示）、首次要给式子。
 */
function shouldSuppress(entry) {
  return !!entry
    && entry.trend === TREND.PERSISTENT
    && entry.status === 'stalled'
    && entry.reportCount >= SUPPRESS_MIN_REPORTS;
}

/**
 * 把本次运行与上次状态合并。
 * @param {Array} nowClusters `convergence.clusters`（本次运行内追踪到的簇；含 status/support）
 * @param {Object} prior `readPrior()` 的返回值
 * @returns {Object} `{status, reason, runs, clusters, summary, suppressedKeys}`
 *   `status` 透传 prior 状态；`clusters` 含**本次没有但历史有**的条目（`cleared`）—— 否则
 *   「上次报的维度这次没了」这件事会静默消失，人只能自己记得。
 */
function mergePrior(nowClusters, prior) {
  const now = new Map();
  for (const c of nowClusters || []) {
    const k = c && (c.key || c.label);
    if (k) now.set(String(k), c);
  }
  const old = new Map();
  const p = prior || {};
  if (p.status === PRIOR.OK) {
    for (const c of p.clusters || []) old.set(c.key, c);
  }
  const runs = (p.status === PRIOR.OK ? p.runs : 0) + 1;

  const keys = [];
  const seen = new Set();
  // 先本次的（顺序沿用 convergence 的排序：新维度优先 → support 降），再历史独有的
  for (const c of nowClusters || []) {
    const k = String(c && (c.key || c.label) || '');
    if (!k || seen.has(k)) continue;
    seen.add(k);
    keys.push(k);
  }
  for (const k of Array.from(old.keys()).sort()) {
    if (seen.has(k)) continue;
    seen.add(k);
    keys.push(k);
  }

  const entries = [];
  for (const k of keys) {
    const n = now.get(k) || null;
    const o = old.get(k) || null;
    const nowPresent = !!n;
    const nowStatus = n ? (n.status == null ? null : String(n.status)) : null;
    const priorResolved = !!(o && o.status === 'resolved');

    // ★ 五态穷举（互斥）：先判「上次有没有」，再判「上次是否已收敛」，最后判本次形态。
    let trend;
    if (!o) trend = TREND.NEW;
    else if (priorResolved) {
      // ★ 只有「本次末轮**仍在**」才算回归。判定必须看末轮，不能看「本次出没出现过」：
      //   本次也判 `resolved` 说明它这次出现过又被消掉了 —— 那是**持续收敛**，不是回归。
      //   真实语料 2026-10-18 打出的假阳性：`慢性`/`调控` 两次都 resolved，却被标成「回归」。
      //   `capped` 是「末轮缺席但可能只是被上限挤出」⇒ 同样不能算回归，但要标 uncertain。
      const liveNow = nowPresent && nowStatus !== 'resolved' && nowStatus !== 'capped';
      trend = liveNow ? TREND.RECURRED : TREND.CLEARED;
    } else if (!nowPresent) trend = TREND.CLEARED;
    else if (nowStatus === 'resolved') trend = TREND.RESOLVED;
    else trend = TREND.PERSISTENT;

    const priorReports = o ? o.reportCount : 0;
    // 本次是否「被报告」：只要出现在本次追踪表里就算（含 resolved/capped —— 它们也都进了报告）
    const reportedNow = nowPresent;
    const reportCount = priorReports + (reportedNow ? 1 : 0);

    const entry = {
      key: k,
      label: n ? (n.label == null ? k : String(n.label)) : (o.label == null ? k : o.label),
      kind: n ? (n.kind == null ? null : String(n.kind)) : (o.kind == null ? null : o.kind),
      trend,
      status: nowStatus,                       // 本次运行内的状态；cleared ⇒ null（本次没出现，不臆造）
      support: n && typeof n.support === 'number' ? n.support : null,
      priorStatus: o ? o.status : null,
      priorSupport: o && typeof o.support === 'number' ? o.support : null,
      reportCount,
      supportSeries: n && Array.isArray(n.supportSeries) ? n.supportSeries.slice()
        : (o && Array.isArray(o.supportSeries) ? o.supportSeries.slice() : []),
      runs: o ? runs : 1,
      suppress: false,
      // 本次末轮「消失」无法核实（簇数超上报上限）⇒ 结论不可当确定（与 convergence.capped 同源）
      uncertain: nowStatus === 'capped',
    };
    // 支持数变动（同一 trend 内的「结论没变但强度变了」）—— 报告要看得见
    if (entry.support != null && entry.priorSupport != null) {
      entry.supportDelta = entry.support - entry.priorSupport;
    }
    entry.suppress = shouldSuppress(entry);
    entries.push(entry);
  }

  const summary = { new: 0, persistent: 0, resolved: 0, cleared: 0, recurred: 0, suppressed: 0 };
  entries.forEach(e => {
    summary[e.trend] = (summary[e.trend] || 0) + 1;
    if (e.suppress) summary.suppressed++;
  });

  return {
    status: p.status || PRIOR.NONE,
    reason: p.reason || '',
    runs,
    corpusChanged: !!p.corpusChanged,
    savedAt: p.savedAt || null,
    clusters: entries,
    summary,
    suppressedKeys: entries.filter(e => e.suppress).map(e => e.key),
  };
}

/**
 * 把跨运行结论**贴回**簇对象（供建议检索式读取 `suppress`）。
 * 纯映射：不改入参；未追踪到的簇 `trend = null`（不臆造）。
 */
function annotateCrossRun(clusters, cross) {
  const byKey = new Map();
  ((cross && cross.clusters) || []).forEach(c => byKey.set(c.key, c));
  return (clusters || []).map(c => {
    const k = String((c && (c.key || c.label)) || '');
    const t = byKey.get(k);
    const out = Object.assign({}, c, {
      trend: t ? t.trend : null,
      reportCount: t ? t.reportCount : 0,
      priorStatus: t ? t.priorStatus : null,
      suppress: !!(t && t.suppress),
    });
    return out;
  });
}

/** UTC ISO（秒级）：确定性输出，便于逐字节 diff。 */
function isoSeconds(d) {
  const t = d instanceof Date ? d : new Date();
  return t.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * 生成本次要写盘的状态文件（**纯对象**，序列化由调用方做）。
 * @param {Object} input `{cross, convergence, fingerprint, now, prevFile}`
 *   `prevFile` = CLI 读到的原始 JSON（用于保留其他主题的槽）；缺省则只写本槽。
 * @returns {{state:Object, evicted:Array}} `evicted` = 因超出 `MAX_SLOTS` 被淘汰的槽
 *   ★ 必须回传：淘汰是**丢记忆**，静默丢等于数据损坏，调用方要在报告里点名。
 *   ★ 其他槽**原样深拷贝**（不重建字段）—— 重建会丢掉本模块还不认识的字段，
 *     等于用一次升级把用户的历史啃掉一层。
 * ★ 键序与数组顺序都固定（槽按 savedAt 降序 + hash 升序、clusters 按 key 升序），
 *   否则每次运行都会产生无意义的 diff。
 */
function buildState(input) {
  const o = input || {};
  const cross = o.cross || null;
  const conv = o.convergence || {};
  const fp = o.fingerprint || {};
  const savedAt = isoSeconds(o.now);
  const list = ((cross && cross.clusters) || []).slice()
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  const slot = {
    hash: fp.hash == null ? '' : String(fp.hash),
    topic: fp.topic == null ? '' : String(fp.topic),
    savedAt,
    runs: (cross && cross.runs) || 1,
    criterion: CRITERION,
    state: conv.state == null ? null : String(conv.state),
    iterations: conv.observations == null ? null : conv.observations,
    fingerprint: {
      topic: fp.topic == null ? '' : String(fp.topic),
      hash: fp.hash == null ? '' : String(fp.hash),
      corpus: Number.isInteger(fp.corpus) ? fp.corpus : null,
      pick: fp.pick == null ? null : String(fp.pick),
    },
    clusters: list.map(e => ({
      key: e.key,
      label: e.label,
      kind: e.kind,
      status: e.status,
      trend: e.trend,
      support: e.support,
      reportCount: e.reportCount,
      supportSeries: e.supportSeries || [],
    })),
  };

  // 保留其他主题的槽：同主题的旧槽由 slot 取代，其余原样深拷贝
  // ★ v1 文件只有单槽、hash 由当时的 buildState 写入 ⇒ 迁移时**只比 topic**
  //   （若还要求 hash 相等，一份 hash 缺失/被手改过的 v1 文件会变成「新旧两个槽」并存）。
  const prevIsV1 = !!(o.prevFile && o.prevFile.version === V1_VERSION);
  const prevSlots = slotsOf(o.prevFile);
  const keep = [];
  for (const s of prevSlots) {
    if (slotTopic(s) === slot.topic && (prevIsV1 || slotHash(s) === slot.hash)) continue;
    keep.push(JSON.parse(JSON.stringify(s)));
  }

  let slots = [slot].concat(keep);
  // 排序：savedAt 降序（最新在前）+ hash 升序（同秒时确定性；不能依赖插入顺序）
  slots.sort((a, b) => {
    const sa = String((a && a.savedAt) || '');
    const sb = String((b && b.savedAt) || '');
    if (sa !== sb) return sa > sb ? -1 : 1;
    const ha = slotHash(a);
    const hb = slotHash(b);
    return ha < hb ? -1 : ha > hb ? 1 : 0;
  });
  const evicted = slots.length > MAX_SLOTS
    ? slots.slice(MAX_SLOTS).map(s => ({
      hash: slotHash(s), topic: slotTopic(s),
      savedAt: s && s.savedAt != null ? String(s.savedAt) : null,
    }))
    : [];
  if (evicted.length) slots = slots.slice(0, MAX_SLOTS);

  return {
    state: { version: VERSION, savedAt, slots },
    evicted,
  };
}

/** 确定性序列化：两空格缩进 + 结尾换行（LF）。同一输入必得同一字节串。 */
function serialise(state) {
  return JSON.stringify(state, null, 2) + '\n';
}

/**
 * 不可用状态文件的备份文件名（**纯函数**，零 IO —— 本模块不碰文件系统，守卫钉死）。
 *
 * ★ 为什么 CORRUPT / REJECTED 必须备份后才允许覆盖：
 *   CORRUPT 时 `buildState` 拿到的是 `prevFile.data = null`，其余主题槽根本不进 `keep`
 *   ⇒ 20 槽变 1 槽（实测 5,062 B → 497 B），而原字节**再也拿不回来**（本机删除即永久，不靠回收站）。
 *   REJECTED 虽**不丢槽**（`slotsOf` 不校验版本，槽照样搬），但那是「声明格式不可信、却按旧语义搬槽」——
 *   一旦对方格式真的变了，搬过去的是被静默曲解的槽，同样需要一份原样副本兜底。
 *   ⇒ 两条分支都要备份，但措辞必须分开，不能混为一谈（前者是数据丢失，后者是语义存疑）。
 *
 * @param {string} filePath 状态文件路径
 * @param {string} status `readPrior` 的 status（只接受 corrupt / rejected）
 * @param {Date|number} [now] 时间来源；测试注入固定值才能断言文件名
 * @returns {string|null} 不可用时返回备份路径，OK/NONE 返回 null（不需要备份）
 */
function backupNameFor(filePath, status, now) {
  if (status !== PRIOR.CORRUPT && status !== PRIOR.REJECTED) return null;
  const tag = status === PRIOR.CORRUPT ? 'corrupt' : 'legacy';
  const d = now instanceof Date ? now : new Date(now == null ? Date.now() : now);
  // toISOString: 2026-10-24T15:40:12.345Z ⇒ 去掉 - : . ⇒ 20261024T154012345Z
  // （冒号在 Windows 文件名里非法，且毫秒必须有 —— 同秒内两次触发会撞名）
  const stamp = d.toISOString().replace(/[-:.]/g, '');
  return String(filePath) + '.' + tag + '-' + stamp;
}

module.exports = {
  VERSION, V1_VERSION, MAX_SLOTS, CRITERION, TREND, PRIOR, TREND_NOTE,
  SUPPRESS_MIN_REPORTS,
  canonTopic, slotsOf, slotTopic, slotHash,
  fingerprintOf, readPrior, mergePrior, annotateCrossRun,
  shouldSuppress, buildState, serialise, isoSeconds, backupNameFor,
};
