'use strict';
/**
 * lib/iterate.cjs — 多轮迭代闭环：补词 → 重排 → 再诊断（纯函数，零网络、零文件系统）
 *
 * 解决什么：单轮 `--apply` 只答「补这几个词有没有用」，答不了「**这个词表还能挖到多少**」。
 *   本模块把「诊断 → 补词 → 重排」迭代到收敛，产出：① 每轮增益曲线 ② 饱和轮次
 *   ③ 最终词表（**待人工确认**）。
 *
 * ★ 定位与纪律（本模块是**上限探测**，不是自动改词表）：
 *   迭代会**自动**按 `batch` 批量取候选，因此产物**不代表建议词表** ——
 *   真正的采纳仍只走 `rank-records --apply`（唯一人工通道）。渲染层强制输出该免责声明。
 *   `pick=extends` 是更保守的档：只自动补「词表词 + 修饰」（`肾脏保健` ⊃ `肾脏`）——
 *   这类在语义上只是把已知词延伸；半重叠类（可能是真缺词、也可能是 n-gram 分词错位）
 *   **一律进 `deferred` 交人判断**，不自动补。
 *
 * 停止条件（**穷举四种**；不得出现「说不清的停止」）：
 *   ① `no-candidates` 语料里没有可补的词（含「候选存在但均被 pick 过滤」）
 *   ② `all-covered`   取到的词全部已在词表（跨模块去重语义一致性的防线，理论不可达）
 *   ③ `no-gain`       补入后主题命中数未增加（不空转）
 *   ④ `max-rounds`    达到轮数上限
 *
 * ★ 不变量（每轮核对并暴露，异常即缺陷）：
 *   补词只增命中 ⇒ 分数单调不减 ⇒ 每轮**降级必为 0**；词表**单调增长**。
 *
 * ★ 维度收敛判据（2026-10-18 补，解决「同一维度被反复当新发现报出来」）：
 *   逐轮做残差诊断（round 0 = 起始词表），按簇 key 跨轮追踪 ⇒ `convergence`：
 *     **簇消失**（support 落到 minSupport 以下 / 记录升档）才算该维度收敛；
 *     末轮仍在且 support 未降 ⇒ `stalled`（补词治不了，是检索式/站点侧的活）。
 *   ★ 追踪用 `maxClusters=10`（诊断输出上限），报告仍用默认 5 —— 否则「被上限挤出的簇」
 *     会被误判成「已消失」（正是 `capped` 态要挡的假收敛）。
 *   ★ 收敛判定只进报告：**不参与循环控制**，停止原因仍是下面穷举的四种（不新增第五种）。
 *
 * ★ 跨运行记忆（2026-10-18 补，解决「同一维度每份报告都重报一遍」）：
 *   传入 `priorFile`（CLI 读文件的结果 `{exists,data,error}`）⇒ 用**主题指纹**校验后合并，
 *   给每个簇贴 `trend`（new / persistent / resolved / cleared / recurred）与 `reportCount`。
 *   `persistent + stalled + reportCount ≥ 2` ⇒ `suppress`，建议检索式不再重复出这条式子。
 *   ★ 主题词表变了 ⇒ 拒绝合并（不同词表是不同的问题定义，沿用旧结论会造出「查过」的假记忆）。
 *   ★ 只读：本模块仍**不碰文件系统** —— 读在 CLI、写也在 CLI，这里只吃已解析对象、吐待写对象。
 *   ★ 抑制必须发生在 `buildQueryPlans` **之前**（否则式子已经生成，只能事后删，容易漏）。
 *
 * 依赖：仅 `relevance`（buildTopic / rankAll / mergeTerms / diffRanks）、
 *   `suggest`（buildSuggestions）、`diagnose`（diagnoseResidual，残差维度诊断）、
 *   `convergence`（trackClusters / annotateClusters，跨轮收敛判据）
 *   与 `converge-state`（readPrior / mergePrior / annotateCrossRun，跨运行记忆）。
 *   词表合并**必须**走 `mergeTerms`，不得另写去重逻辑。
 *   ★ `diagnosis` 只进报告、**不回流**：新维度 ≠ 词表词，自动升格会让「什么算相关」被悄悄改写。
 */

const REL = require('./relevance.cjs');
const SG = require('./suggest.cjs');
const DIAG = require('./diagnose.cjs');   // 残差维度诊断（只提示，产物**不**回流词表）
const QP = require('./query-plan.cjs');    // 维度 → 建议检索式（只出方案，不执行）
const CV = require('./convergence.cjs');   // 跨轮收敛判据（簇消失 / support 未降）
const CSG = require('./converge-state.cjs'); // 跨运行记忆（主题指纹校验 + 五态 trend + 抑制）

const VERSION = 'term-iterate/v3';
const DEFAULT_MAX_ROUNDS = 3;
const MAX_ROUNDS_CAP = 8;
const DEFAULT_BATCH = 5;
const BATCH_CAP = 50;
const PICKS = ['all', 'extends'];
/** 追踪口径：支持数下限与诊断默认一致；簇上限取诊断允许的最大值（10），避免被截断误判为消失。 */
const TRACK_MIN_SUPPORT = 2;
const TRACK_MAX_CLUSTERS = 10;

const STOP = Object.freeze({
  NO_CANDIDATES: 'no-candidates',
  ALL_COVERED: 'all-covered',
  NO_GAIN: 'no-gain',
  MAX_ROUNDS: 'max-rounds',
});

/** 整数钳制（非法值一律回落默认，不抛错 —— 参数校验属 CLI 层职责）。 */
function clampInt(v, dflt, lo, hi) {
  const n = Number(v);
  if (!Number.isInteger(n)) return dflt;
  return Math.min(hi, Math.max(lo, n));
}

/** 本轮状态快照（供渲染与断言，避免把内部可变对象泄出去）。 */
function snapshot(result) {
  return { total: result.total, stat: Object.assign({}, result.stat), exactRate: result.exactRate };
}

/**
 * 单轮观测：残差维度诊断的**收敛追踪视图**（只留判据需要的字段，不搬题名/记录）。
 * ★ 与报告用的诊断分开调用：追踪要 10 簇、报告要默认 5 簇，混用会让「簇被上限挤出」
 *   变成「已消失」（假收敛）。
 */
function observe(round, rows, topic) {
  const dg = DIAG.diagnoseResidual(rows, topic, {
    minSupport: TRACK_MIN_SUPPORT, maxClusters: TRACK_MAX_CLUSTERS,
  });
  return {
    round,
    verdict: dg.verdict,
    clustersTotal: dg.clustersTotal == null ? dg.clusters.length : dg.clustersTotal,
    clusters: dg.clusters.map(c => ({
      key: c.key, label: c.label, kind: c.kind, support: c.support,
    })),
    residualTotal: (dg.residual || {}).total == null ? null : dg.residual.total,
  };
}

/**
 * 迭代补词直到收敛。
 * @param {Object} opts
 *   groups            readRawGroups 的产物
 *   topicSpec         初始词表 `{terms, near, exclude}`
 *   maxRounds         轮数上限（默认 3，钳制 1–8）
 *   batch             每轮补入上限（默认 5，钳制 1–50）—— 模拟人工「一次挑几个」
 *   pick              `all`（上限探测，默认）| `extends`（只补词表词+修饰）
 *   minDf / scope / suggestTop   透传 suggest
 *   rankAll / buildSuggestions   可注入（测试用）
 */
function iterateRounds(opts) {
  const o = opts || {};
  const groups = o.groups || [];
  const spec = o.topicSpec || {};
  const maxRounds = clampInt(o.maxRounds, DEFAULT_MAX_ROUNDS, 1, MAX_ROUNDS_CAP);
  const batch = clampInt(o.batch, DEFAULT_BATCH, 1, BATCH_CAP);
  const pick = PICKS.indexOf(o.pick) >= 0 ? o.pick : 'all';
  const minDf = Number.isInteger(o.minDf) && o.minDf > 0 ? o.minDf : SG.DEFAULT_MIN_DF;
  const scope = o.scope || SG.DEFAULT_SCOPE;
  const suggestTop = Number.isInteger(o.suggestTop) && o.suggestTop > 0 ? o.suggestTop : SG.DEFAULT_TOP;
  const rankAll = o.rankAll || REL.rankAll;
  const buildSuggestions = o.buildSuggestions || SG.buildSuggestions;
  const near = spec.near;
  const exclude = spec.exclude;

  let termsText = spec.terms;
  let topic = REL.buildTopic({ terms: termsText, near, exclude });
  let result = rankAll(groups, topic);

  const baseline = snapshot(result);
  baseline.terms = REL.mergeTerms(termsText, '').terms;

  // round 0 = 起始词表的残差诊断 —— 没有它就看不出第 1 轮的维度是「新出现」还是「本来就在」
  const diagSeries = [observe(0, result.ranked, topic)];

  const rounds = [];
  let stopReason = null;
  let stopDetail = '';

  for (let n = 1; n <= maxRounds; n++) {
    const sg = buildSuggestions(result.ranked, topic, { scope, minDf, suggestTop });
    const pool = pick === 'all' ? sg.candidates : sg.candidates.filter(c => c.extendsTopic);
    const deferred = sg.candidates.filter(c => pool.indexOf(c) < 0).map(c => c.term);
    const picked = pool.slice(0, batch).map(c => c.term);

    // 词表合并**必须**走 mergeTerms —— 同一套去重语义（含简繁等价、保原文形态）
    const merged = REL.mergeTerms(termsText, picked);

    const stall = (reason, detail) => {
      rounds.push({
        n,
        appended: [],
        deferred,
        terms: merged.terms,
        stat: Object.assign({}, result.stat),
        exactRate: result.exactRate,
        deltaExact: 0,
        upgraded: 0,
        downgraded: 0,
        candidatesSeen: sg.candidates.length,
        note: detail,
      });
      stopReason = reason;
      stopDetail = detail;
    };

    if (!sg.candidates.length) {
      stall(STOP.NO_CANDIDATES,
        '扫 ' + sg.corpus + ' 条题名（范围 ' + scope + '），无「词表外且高频」的领域词');
      break;
    }
    if (!merged.appended.length) {
      // 理论不可达：suggest 已过滤 covered。保留为**跨模块去重语义一致性**的防线
      //   （一旦 suggest 与 mergeTerms 的归一规则分叉，这里会立刻显形，而不是静默空转）。
      stall(pool.length ? STOP.ALL_COVERED : STOP.NO_CANDIDATES,
        pool.length
          ? '本轮取到的词全部已在词表（' + picked.join(',') + '）'
          : '候选 ' + sg.candidates.length + ' 个均被 pick=' + pick + ' 过滤，已列入 deferred');
      break;
    }

    const nextTopic = REL.buildTopic({ terms: merged.terms.join(','), near, exclude });
    const nextResult = rankAll(groups, nextTopic);
    const diff = REL.diffRanks(result, nextResult, { addedTerms: merged.appended });

    const rd = {
      n,
      appended: merged.appended,
      deferred,
      terms: merged.terms,
      stat: Object.assign({}, nextResult.stat),
      exactRate: nextResult.exactRate,
      deltaExact: nextResult.stat.exact - result.stat.exact,
      upgraded: diff.upgraded.length,
      downgraded: diff.downgraded.length,
      candidatesSeen: sg.candidates.length,
      note: '',
    };
    rounds.push(rd);

    termsText = merged.terms.join(',');
    topic = nextTopic;
    result = nextResult;
    diagSeries.push(observe(n, result.ranked, topic));

    if (rd.deltaExact <= 0) {
      // 不空转：补入的词只加分、不升档 ⇒ 继续迭代也只是烧人力
      stopReason = STOP.NO_GAIN;
      stopDetail = '第 ' + n + ' 轮补入 ' + rd.appended.length + ' 词，主题命中数未增加（仍 ' + rd.stat.exact + '）';
      break;
    }
  }

  if (!stopReason) {
    stopReason = STOP.MAX_ROUNDS;
    stopDetail = '已达轮数上限 ' + maxRounds + ' —— 续跑可能仍有增益，调大 --iterate 可继续探测';
  }

  const final = snapshot(result);
  final.terms = REL.mergeTerms(termsText, '').terms;

  // 收敛后仍非「主题命中」的记录：这不是「词表写法不够」（补词能治），而是
  //   **缺主题维度**（补词治不了）—— 迭代再深也只会围绕同一批字面，故单列出来交人判断。
  const residual = result.ranked
    .filter(r => r.rel.level !== 'exact')
    .map(r => ({
      idx: (r.rec || {}).idx == null ? null : r.rec.idx,
      title: (r.rec || {}).titleZh || (r.rec || {}).titleEn || '',
      year: (r.rec || {}).year == null ? null : r.rec.year,
      level: r.rel.level,
      excluded: !!(r.rel || {}).excluded,   // 与维度诊断同口径（诊断会跳过排除记录）
    }));

  // 残差 → 「缺哪个维度」。★ 结果**只进报告**：不得参与下一轮补词（新维度 ≠ 词表词）。
  const diagnosis = DIAG.diagnoseResidual(result.ranked, topic, { minSupport: 2 });
  // 维度生命周期：簇消失 ⇒ 收敛；末轮仍在且 support 未降 ⇒ stalled（补词治不了，别再重复当新发现）。
  const convergence = CV.trackClusters(diagSeries);
  // 收敛状态**贴回**簇（供报告与建议检索式引用），未追踪到的簇 status 为 null（不臆造）
  diagnosis.clusters = CV.annotateClusters(diagnosis.clusters, convergence);
  // 跨运行记忆是否参与本次诊断。★ 必须是**数据字段**而非序列化时现算：
  //   报告 JSON 走的是原始对象（renderJson 的 raw 通道），现算只会在 compactIterate 那条通道生效
  //   ⇒ 实测出现过「文件 JSON 有 suppress 却缺 crossActive」的两通道不一致。
  diagnosis.crossActive = false;

  // 跨运行记忆：**必须**在 buildQueryPlans 之前 —— 抑制要在出式子那一刻生效，不是出完再删。
  //   指纹取**起始词表**（问题定义）与语料总数（用于提示「文献变了」，不用于拒绝合并）。
  let crossRun = null;
  let stateNext = null;
  let stateInput = null;
  if (o.priorFile) {
    const fp = CSG.fingerprintOf({ topic: spec.terms, corpus: baseline.total, pick });
    const prior = CSG.readPrior(o.priorFile, fp);
    crossRun = CSG.mergePrior(convergence.clusters, prior);
    crossRun.fingerprint = fp;
    crossRun.format = prior.format;                 // 'v1'（自动迁移）/ 'v2' / null（无文件）
    crossRun.otherSlots = prior.otherSlots || 0;    // 文件里**其他主题**的槽数（换主题不再覆盖）
    diagnosis.clusters = CSG.annotateCrossRun(diagnosis.clusters, crossRun);
    diagnosis.crossActive = true;
    // 待写盘对象（CLI 负责序列化与落盘；本模块不碰文件系统）
    // ★ 批 2（2026-10-24）：buildState 的**入参**也回传给 CLI。原因：
    //   `prevFile` 决定「保留其他主题的槽」，而这里拿到的是 **run 开始那一刻**的快照。
    //   一次 run 中间隔着整批站点请求与多轮迭代（分钟级），期间别的进程新建的槽会被这份陈旧快照覆盖。
    //   ⇒ CLI 在**写盘前**重读磁盘，用新鲜快照重新 buildState（见 rank-records.cjs）。
    //   这里仍先构建一份，供报告里的 slotCount / evicted 使用；CLI 重建后必须回填这两个字段。
    stateInput = {
      cross: crossRun, convergence, fingerprint: fp,
      now: o.now instanceof Date ? o.now : undefined,
    };
    const built = CSG.buildState(Object.assign({}, stateInput, { prevFile: o.priorFile.data }));
    stateNext = built.state;
    crossRun.slotCount = built.state.slots.length;
    crossRun.evicted = built.evicted;               // ★ 超出上限被淘汰的槽（丢记忆必须可见）
  }

  // 维度 → 「下一步该用什么检索式去验证」。同样**只进报告**；`executed` 恒 false（不自动跑）。
  diagnosis.queries = QP.buildQueryPlans(diagnosis.clusters, {
    rows: result.ranked, species: o.species, cap: o.queryCap,
    topic: result.topic,          // ★ 主题锚取自词表：缺了它，式子会退化成「物种 × 维度大类」
  });

  return {
    version: VERSION,
    stationRequests: 0,                 // 声明式：迭代全程零站点请求（只读同一批 ranked 行）
    pick, maxRounds, batch, scope, minDf,
    baseline,
    rounds,
    stopReason,
    stopDetail,
    terms: final.terms,
    final,
    residual,
    diagnosis,
    convergence,                        // 维度收敛判据（只读；不参与循环控制）
    crossRun,                           // 跨运行记忆（null = 未传 priorFile，零回归）
    stateNext,                          // 待写盘的状态对象（null = 不记忆）
    stateInput,                         // buildState 入参（CLI 写盘前用重读到的快照重建；null = 不记忆）
    totalGain: final.stat.exact - baseline.stat.exact,
    totalAppended: rounds.reduce((s, r) => s + r.appended.length, 0),
    saturationRound: rounds.length,     // 饱和发生在第几轮（= 实际跑了几轮）
  };
}

module.exports = {
  VERSION, DEFAULT_MAX_ROUNDS, MAX_ROUNDS_CAP, DEFAULT_BATCH, BATCH_CAP, PICKS, STOP,
  iterateRounds,
};
