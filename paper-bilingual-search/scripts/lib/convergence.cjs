'use strict';
/**
 * lib/convergence.cjs — 残差维度的**收敛判据**：跨轮追踪同一个簇的生命周期（纯函数）
 *
 * 解决什么：`diagnose.cjs` 只答「**这一轮**残差缺哪个维度」，`iterate.cjs` 只答「补词还能挖多深」。
 *   两者之间缺一层记忆 ⇒ 同一个维度会在每份报告里**重新**出现、每次 support 都是新的绝对值，
 *   人看不出它是「上一轮那个维度还在」「正在缩小」还是「卡死了」。缺的判据就是：
 *   **簇消失**（support 落到最小支持数以下 / 记录已升档）才算这个维度收敛 ——
 *   否则 `--iterate` 会一轮一轮重复报同一个维度，且每次都像新发现。
 *
 * ★ 六态穷举（不得出现「说不清的簇」）：
 *   `resolved`  末轮观测中已无该 key —— 收敛（support < minSupport 或记录升档）
 *   `stalled`   末轮仍在，且与上一次观测 support **完全相等**（≥2 次观测）⇒ 补词治不了
 *   `shrinking` 末轮仍在，support 严格下降 ⇒ 仍在收敛中
 *   `grew`      末轮仍在，support 严格上升 ⇒ 反向（须核查是否换了语义）
 *   `emerged`   只有一次观测（末轮首次出现）⇒ 趋势未知，不得当结论
 *   `capped`    末轮缺失，但末轮簇数**超出上报上限** ⇒ 无法判定「真消失」还是「被上限挤出」
 *
 * ★ 收敛判定（`state` 五态穷举）：
 *   `converged`    无 capped，且所有存活簇均为 stalled（没有「还在变」的簇）
 *   `converging`   有 shrinking，且无 grew/emerged
 *   `active`       有 grew/emerged
 *   `inconclusive` 存在 capped —— **宁可说不知道，不可误报收敛**
 *   `insufficient` 观测 < 2 轮（一轮看不出趋势）
 *   ★ 残差为 0（空簇）判 `converged`：没有维度需要收敛。
 *
 * ★ 只读：不改词表、不产提案、不发请求 —— 与 `diagnose`/`query-plan` 同一条纪律。
 *   本模块**不允许**出现 `--apply` 语义：收敛是按 key 的追踪，不是补词通道。
 */

const VERSION = 'dim-convergence/v1';

/** 判据标识（写进报告与 JSON，便于事后核对「用的是哪条判据」）。 */
const CRITERION = 'cluster-absent-or-below-min-support';

const STATUS = Object.freeze({
  RESOLVED: 'resolved',
  STALLED: 'stalled',
  SHRINKING: 'shrinking',
  GREW: 'grew',
  EMERGED: 'emerged',
  CAPPED: 'capped',
});

const STATE = Object.freeze({
  CONVERGED: 'converged',
  CONVERGING: 'converging',
  ACTIVE: 'active',
  INCONCLUSIVE: 'inconclusive',
  INSUFFICIENT: 'insufficient',
});

const STATUS_NOTE = {
  resolved: '已消失（support 落到阈值以下或记录已升档）⇒ 该维度收敛',
  stalled: 'support 连续未降 ⇒ 补词治不了，属检索式/站点侧的活',
  shrinking: 'support 在下降 ⇒ 补词仍在起效',
  grew: 'support 上升 ⇒ 反向变化，须核查是否换成了别的语义',
  emerged: '仅一轮观测 ⇒ 趋势未知，不得当结论',
  capped: '末轮簇数超出上报上限 ⇒ 无法判定真消失还是被挤出',
};

/** 簇的稳定标识：诊断层已给 `key`（压缩后的 n-gram 键），缺失时退回 label。 */
function keyOf(c) {
  const k = (c && (c.key || c.label)) || '';
  return String(k);
}

function num(v, dflt) {
  return typeof v === 'number' && isFinite(v) ? v : dflt;
}

/**
 * 跨轮追踪残差簇。
 * @param {Array} series 逐轮诊断观测（按 round 升序不必预排）
 *   每项：`{round, clusters:[{key,label,kind,support}], clustersTotal?, residualTotal?}`
 * @returns {Object} 见文件末尾的返回形状
 */
function trackClusters(series) {
  const obsList = (series || [])
    .filter(x => x && Array.isArray(x.clusters))
    .map(x => {
      const clusters = x.clusters;
      return {
        round: num(x.round, 0),
        clusters,
        // 末轮簇数 > 上报簇数 ⇒ 有簇被上限截掉（诊断层 `shown = clusters.slice(0, maxClusters)`）
        clustersTotal: num(x.clustersTotal, clusters.length),
        residualTotal: x.residualTotal == null ? null : num(x.residualTotal, null),
      };
    })
    .sort((a, b) => a.round - b.round);

  if (!obsList.length) {
    return {
      version: VERSION, criterion: CRITERION,
      observations: 0, rounds: [], residualSeries: [], residualMonotonic: true,
      clusters: [], counts: emptyCounts(), live: 0, cappedCount: 0,
      state: STATE.INSUFFICIENT, converged: false,
      note: '无观测：未产生任何残差诊断（无从判断维度趋势）。',
    };
  }

  const last = obsList[obsList.length - 1];
  const lastRound = last.round;
  const capRisk = last.clustersTotal > last.clusters.length;

  // ---- ① 逐 key 收集观测（同一 key 在同一轮出现多次时取最大 support，并留痕）
  const map = new Map();
  for (const ob of obsList) {
    for (const c of ob.clusters) {
      const key = keyOf(c);
      if (!key) continue;
      if (!map.has(key)) {
        map.set(key, {
          key, label: c.label == null ? key : String(c.label),
          kind: c.kind || 'new-dimension', firstKind: c.kind || 'new-dimension',
          byRound: new Map(), duplicated: false,
        });
      }
      const e = map.get(key);
      const sup = num(c.support, 0);
      if (e.byRound.has(ob.round)) {
        e.duplicated = true;
        if (sup > e.byRound.get(ob.round)) e.byRound.set(ob.round, sup);
      } else {
        e.byRound.set(ob.round, sup);
      }
      // 标签/类型以**最新**观测为准，但类型变化要留痕（新维度 ↔ 同轴，语义不同）
      e.label = c.label == null ? e.label : String(c.label);
      if (c.kind) e.kind = c.kind;
    }
  }

  // ---- ② 逐 key 定状态
  const tracked = [];
  for (const e of map.values()) {
    const obs = Array.from(e.byRound.entries())
      .map(([round, support]) => ({ round, support }))
      .sort((a, b) => a.round - b.round);
    const supportSeries = obs.map(x => x.support);
    const firstRound = obs[0].round;
    const lastSeen = obs[obs.length - 1].round;
    const presentAtLast = lastSeen === lastRound;
    let status;
    if (!presentAtLast) {
      status = capRisk ? STATUS.CAPPED : STATUS.RESOLVED;
    } else if (obs.length === 1) {
      status = STATUS.EMERGED;
    } else {
      const delta = obs[obs.length - 1].support - obs[obs.length - 2].support;
      status = delta < 0 ? STATUS.SHRINKING : delta > 0 ? STATUS.GREW : STATUS.STALLED;
    }
    // 尾部连续「support 未降」的观测数（stalled 的强度；亦用于报告文案）
    let stallRounds = 0;
    for (let i = obs.length - 1; i > 0; i--) {
      if (obs[i].support === obs[i - 1].support) stallRounds++;
      else break;
    }
    tracked.push({
      key: e.key, label: e.label, kind: e.kind,
      kindChanged: e.kind !== e.firstKind,
      duplicated: e.duplicated,
      status,
      note: STATUS_NOTE[status],
      support: supportSeries[supportSeries.length - 1],
      supportSeries,
      firstRound,
      lastSeenRound: lastSeen,
      persistRounds: obs.length,      // 观测到该 key 的轮数（≥2 即「持续存在」）
      stallRounds,                    // 尾部 support 未降的连续跨度
      roundsAbsent: lastRound - lastSeen,
    });
  }

  // 排序：新维度优先 → support 降 → key 升（与 diagnose 的簇排序同口径，便于逐行对照）
  tracked.sort((a, b) => ((a.kind === 'new-dimension' ? 0 : 1) - (b.kind === 'new-dimension' ? 0 : 1))
    || (b.support - a.support) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  const counts = emptyCounts();
  tracked.forEach(c => { counts[c.status] = (counts[c.status] || 0) + 1; });
  const grounded = tracked.filter(c => c.status !== STATUS.RESOLVED && c.status !== STATUS.CAPPED);
  const cappedCount = counts[STATUS.CAPPED] || 0;

  // ---- ③ 收敛判定
  let state;
  if (obsList.length < 2) state = STATE.INSUFFICIENT;
  else if (cappedCount > 0) state = STATE.INCONCLUSIVE;
  else if (!grounded.length) state = STATE.CONVERGED;                    // 含「残差为 0」的空集
  // ★ 顺序即语义：grew/emerged 优先于 shrinking —— 同时存在「缩小的」与「长出来的」时，
  //   结论不能是「收敛中」（那会把新维度吞掉）。实测由单测 CV_A 夹具逼出（初版顺序写反）。
  else if (counts[STATUS.GREW] || counts[STATUS.EMERGED]) state = STATE.ACTIVE;
  else if (counts[STATUS.SHRINKING]) state = STATE.CONVERGING;
  // ★ 走到这里只剩 stalled：六态里 resolved/capped 已被 grounded 排除，grew/emerged/shrinking 已判过
  else state = STATE.CONVERGED;

  // ---- ④ 不变量：残差只减不增（补词只升档 ⇒ 残差规模单调不增）。违反即缺陷，须显式暴露
  const residualSeries = obsList.map(x => ({ round: x.round, total: x.residualTotal }));
  const known = residualSeries.filter(x => x.total != null);
  const residualMonotonic = known.every((x, i) => i === 0 || x.total <= known[i - 1].total);
  const lastResidual = known.length ? known[known.length - 1].total : null;

  return {
    version: VERSION, criterion: CRITERION,
    observations: obsList.length,
    rounds: obsList.map(x => x.round),
    residualSeries, residualMonotonic,
    clusters: tracked,
    counts,
    live: grounded.length,
    cappedCount,
    capRisk,
    state,
    converged: state === STATE.CONVERGED,
    note: noteOf(state, counts, grounded, obsList.length, lastResidual),
  };
}

function emptyCounts() {
  const c = {};
  Object.keys(STATUS).forEach(k => { c[STATUS[k]] = 0; });
  return c;
}

function noteOf(state, counts, grounded, nObs, lastResidual) {
  if (state === STATE.INSUFFICIENT) {
    return '观测 ' + nObs + ' 轮（< 2）⇒ 看不出维度趋势，不得据此判断收敛。';
  }
  if (state === STATE.INCONCLUSIVE) {
    return '末轮有 ' + counts[STATUS.CAPPED] + ' 个簇的消失无法核实（簇数超出上报上限）⇒ '
      + '「已收敛」与「被挤出」不可区分；请提高簇上限或直接核读残差清单。';
  }
  if (state === STATE.CONVERGED) {
    // ★ 「没有维度」≠「残差为 0」：前者可能是「归不出共同维度」（no-shared-terms），
    //   那些记录须逐条判读，不能因为 state=converged 就被当成「已覆盖」。
    if (!grounded.length) {
      return lastResidual > 0
        ? '无存活维度，但残差仍有 ' + lastResidual + ' 条归不出共同维度 ⇒ **没有维度可收敛**；'
          + '这些记录须逐条人工判读（多为个案或跑题文献）。'
        : '残差维度已全部收敛（残差为 0）。';
    }
    return '所有存活维度（' + grounded.length + '）support 均连续未降 ⇒ **已收敛**：'
      + '再补词不会消除它们，下一步是检索式/站点侧的活（见建议检索式）。';
  }
  if (state === STATE.CONVERGING) {
    return '仍有 ' + counts[STATUS.SHRINKING] + ' 个维度 support 在下降 ⇒ 尚未收敛，补词仍有效。';
  }
  return '末轮出现 ' + (counts[STATUS.GREW] + counts[STATUS.EMERGED]) + ' 个上升/新出现维度 ⇒ '
    + '尚未收敛，且方向未必是「缺词」（可能是语义漂移）。';
}

/**
 * 把收敛状态**贴回**簇对象（供报告与建议检索式引用）。
 * 纯映射：不改入参；未追踪到的簇 `status = null`（不臆造结论）。
 */
function annotateClusters(clusters, conv) {
  const byKey = new Map();
  ((conv && conv.clusters) || []).forEach(c => byKey.set(c.key, c));
  return (clusters || []).map(c => {
    const t = byKey.get(keyOf(c));
    const out = Object.assign({}, c, {
      status: t ? t.status : null,
      persistRounds: t ? t.persistRounds : 0,
      stallRounds: t ? t.stallRounds : 0,
      supportSeries: t ? t.supportSeries.slice() : [],
    });
    if (t && t.kindChanged) out.kindChanged = true;
    return out;
  });
}

module.exports = {
  VERSION, CRITERION, STATUS, STATE, STATUS_NOTE,
  trackClusters, annotateClusters, keyOf,
};
