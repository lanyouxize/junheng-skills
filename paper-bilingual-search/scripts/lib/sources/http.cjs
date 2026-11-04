/* eslint-disable */
/**
 * lib/sources/http.cjs — 连接器共用的 HTTP 取数（超时 / 429 区分 / 退避 / 重试）
 *
 * 为什么独立成一层：
 *   v4.3 的 enrich.cjs 已在**局部**踩过「429 被当成普通错误」的坑（当时 429 与超时都归成
 *   `error:no_response`，并发安全阀无法识别限流）。多源化后同样的坑会出现在每个连接器里，
 *   故在此统一处理，避免 4 份各自演进的重试逻辑漂移。
 *
 * 三条硬约定：
 *   ① **429 必须与其它错误分开返回**（`kind: 'rate_limited'`），并带 `retryAfter`——
 *      调度器据此决定「降速重试」还是「判该源本次不可用」。混为一谈会让降级判断失去依据。
 *   ② 超时用 AbortController 显式中止，**不依赖 socket 默认超时**（Node fetch 默认无超时，
 *      实测站点挂住时会一直等，导致整批 keyword_timeout 而不是单源失败）。
 *   ③ `User-Agent` 带上工具标识与联系邮箱：Crossref / OpenAlex 都按 UA 做礼貌池识别，
 *      实测（2026-10-26）不带 mailto 的 OpenAlex 会在第二次请求就 429。
 */
'use strict';

const DEFAULT_UA = 'paper-bilingual-search/4.15 (https://github.com/; mailto:research@example.com)';
const sleep = ms => new Promise(r => setTimeout(r, ms));

/**
 * 取 JSON。**永不抛**：失败一律以 { ok:false, kind, status, error } 返回，
 * 让调用方（连接器 → 调度器）能把「源失败」变成一条可上报的诊断，而不是一个异常。
 *
 * @returns {Promise<{ok:boolean, json?:any, status?:number, kind?:string, error?:string, retryAfter?:number, ms:number, attempts:number}>}
 */
async function fetchJson(url, opts) {
  const o = opts || {};
  const timeoutMs = o.timeoutMs == null ? 20000 : o.timeoutMs;
  const maxAttempts = o.maxAttempts == null ? 3 : o.maxAttempts;
  const ua = o.userAgent || DEFAULT_UA;
  const t0 = Date.now();
  let last = { ok: false, kind: 'not_attempted', error: 'not attempted' };

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const headers = { 'User-Agent': ua, Accept: 'application/json' };
      if (o.headers) Object.assign(headers, o.headers);
      const r = await fetch(url, { signal: ctl.signal, headers });
      clearTimeout(timer);
      if (r.status === 429) {
        // 站点自报的等待时间优先；没有就按指数退避（1.5s / 3s / 6s）
        const ra = Number(r.headers.get('retry-after'));
        last = {
          ok: false, kind: 'rate_limited', status: 429,
          retryAfter: Number.isFinite(ra) && ra > 0 ? ra : null,
          error: 'HTTP 429 rate limited',
        };
        if (attempt < maxAttempts) {
          await sleep(last.retryAfter ? Math.min(last.retryAfter * 1000, 15000) : 1500 * Math.pow(2, attempt - 1));
          continue;
        }
        break;
      }
      if (!r.ok) {
        last = { ok: false, kind: 'http_error', status: r.status, error: 'HTTP ' + r.status };
        // 5xx 值得重试，4xx（除 429）重试无意义 —— 实测 404 重试 3 次纯属浪费时间
        if (r.status >= 500 && attempt < maxAttempts) { await sleep(1200 * attempt); continue; }
        break;
      }
      let body;
      try { body = await r.text(); }
      catch (e) {
        last = { ok: false, kind: 'read_failed', status: r.status, error: String(e).slice(0, 120) };
        if (attempt < maxAttempts) { await sleep(800 * attempt); continue; }
        break;
      }
      try {
        const json = JSON.parse(body);
        return { ok: true, json, status: r.status, ms: Date.now() - t0, attempts: attempt };
      } catch (e) {
        // 200 但非 JSON：多为网关返回的 HTML 错误页。这不是「空结果」，必须如实标坏格式。
        last = {
          ok: false, kind: 'bad_json', status: r.status,
          error: 'invalid JSON: ' + String(body).slice(0, 120).replace(/\s+/g, ' '),
        };
        if (attempt < maxAttempts) { await sleep(1000 * attempt); continue; }
        break;
      }
    } catch (e) {
      clearTimeout(timer);
      const aborted = ctl.signal.aborted;
      last = {
        ok: false, kind: aborted ? 'timeout' : 'network',
        error: (aborted ? 'timeout after ' + timeoutMs + 'ms' : String(e).slice(0, 160)),
      };
      if (attempt < maxAttempts) { await sleep(1000 * attempt); continue; }
      break;
    }
  }
  return { ...last, ms: Date.now() - t0, attempts: maxAttempts };
}

/** 拼查询串：数组值自动重复 key（Crossref 的 select 需要逗号串，故这里只做通用形态） */
function qs(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === '') continue;
    sp.append(k, String(v));
  }
  return sp.toString();
}

module.exports = { fetchJson, qs, DEFAULT_UA };
