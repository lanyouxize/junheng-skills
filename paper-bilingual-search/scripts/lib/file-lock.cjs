'use strict';
/**
 * 状态文件的**互斥锁**（批 3）—— 只覆盖「重读 → rename」这一段毫秒级临界区。
 *
 * ★ 为什么锁的粒度这么小（这条推翻了早先的判断，别再按老口径排期）：
 *   状态文件**每次 run 只在最后写一次**，且读是可重复的 ⇒ 临界区天然只有毫秒级。
 *   早先「锁要覆盖整次 run ⇒ 第二进程得等几分钟、残留锁会成为新故障模式」是**错的**：
 *   真正要挡住的只是「两个进程几乎同时完成『读-改-写』」，而不是整个抓取过程。
 *
 * 为什么在已有原子写 + CAS 之后仍需要锁：
 *   原子写只保证「读者不会看到半截文件」（M2），CAS 只能发现「**自己读过之后**」的变更（M1 压到 80%）。
 *   两个进程若几乎同时读、同时确认、同时写，**双双通过校验**，后写的仍覆盖先写的。
 *   文件系统没有「比较并交换」原语 ⇒ 无锁的读-改-写做不到零丢失。锁是唯一根治手段。
 *
 * ★ 死锁风险的处置（这是引入锁唯一的真实代价，必须显式兜住）：
 *   持有者在临界区内被杀 ⇒ 锁文件残留 ⇒ 后续进程全部等超时。三道处置：
 *   ① 临界区只有毫秒级，等锁上限 3 s 已是 1000 倍余量；
 *   ② 锁文件 mtime 超过 STALE_MS（10 s）⇒ 判为「持有者已崩」，**抢占**（unlink 后重新 wx 创建）；
 *   ③ 仍拿不到 ⇒ 调用方**跳过写状态**并大声告警（fail-closed：宁可不写，也不要无锁覆盖）。
 *
 * ★ 为什么用 mtime 而不是 pid 判活：**Windows 上不能用 `process.kill(pid, 0)` 探活** ——
 *   CPython/Node 在 Windows 上除 CTRL_C_EVENT 外一律走 TerminateProcess，探活会把目标**杀掉**，
 *   而且返回值还是「已死」。纯 Node 也拿不到 OpenProcess 的等价能力 ⇒ 只能靠 mtime + TTL。
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

/** 锁文件后缀：与目标**同目录**，避免跨盘/跨目录带来的可见性问题。 */
const LOCK_SUFFIX = '.lock';
/** 超过这个年龄的锁视为「持有者已崩」。临界区是毫秒级，10 s 是 1000 倍余量。 */
const STALE_MS = 10 * 1000;
/** 等锁上限。拿不到就 fail-closed（跳过写状态），绝不在无锁情况下覆盖写。 */
const WAIT_MS = 3 * 1000;
/** 轮询间隔。临界区极短，8 ms 足够，也不会把 CPU 烧起来。 */
const POLL_MS = 8;

function lockPathFor(filePath) {
  return filePath + LOCK_SUFFIX;
}

/**
 * 同步睡眠。
 * ★ 不能用 `setTimeout`（异步，拿不到同步语义），也不能写 busy loop（烧 CPU 且不稳）。
 *   Node 主线程允许 `Atomics.wait`，这是唯一可靠且不占 CPU 的同步等待。
 */
function sleepSync(ms) {
  if (!(ms > 0)) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function newToken() {
  // token 是「我持有的是我创建的那个锁文件」的凭证：抢占/超时后不能误删别人的锁。
  return process.pid + '-' + crypto.randomBytes(8).toString('hex');
}

function readLockMeta(lp) {
  try {
    const raw = fs.readFileSync(lp, 'utf8');
    try {
      return { raw, meta: JSON.parse(raw) };
    } catch (e) {
      return { raw, meta: null };      // 半截/非法内容：当作未知持有者，交给 TTL 处置
    }
  } catch (e) {
    return null;                        // 不存在（或无权读）⇒ 与「没有锁」同义
  }
}

function lockAgeMs(lp) {
  try {
    return Date.now() - fs.statSync(lp).mtimeMs;
  } catch (e) {
    return null;                        // 刚好被释放 ⇒ 下一轮直接抢
  }
}

/**
 * 取锁。返回 `{ok:true, handle}` 或 `{ok:false, reason, waitedMs}`。
 * 不抛异常：调用方需要能明确区分「没拿到锁」并降级，而不是让整次 run 崩在收尾阶段。
 */
function acquireLock(filePath, opts) {
  const o = opts || {};
  const waitMs = Number.isFinite(o.waitMs) ? o.waitMs : WAIT_MS;
  const staleMs = Number.isFinite(o.staleMs) ? o.staleMs : STALE_MS;
  const pollMs = Number.isFinite(o.pollMs) ? o.pollMs : POLL_MS;
  const lp = lockPathFor(filePath);
  // ★ 锁可能在目标文件之前诞生（首次运行时目录还不存在）⇒ 必须自己建父目录，
  //   不能依赖 atomic-write 建（那是写盘那一步，锁比它更早）。
  //   否则 openSync 抛 ENOENT，而 ENOENT 不属于锁竞争 ⇒ 会一路炸到调用方。
  const dir = path.dirname(filePath);
  if (dir && dir !== '.' && !fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const token = newToken();
  const started = Date.now();
  let steals = 0;

  for (;;) {
    try {
      const fd = fs.openSync(lp, 'wx');   // 独占创建：互斥的唯一来源（O_CREAT|O_EXCL）
      try {
        fs.writeSync(fd, JSON.stringify({ token, pid: process.pid, at: new Date().toISOString() }));
        fs.fsyncSync(fd);                 // 内容先落盘，再让别的进程看到这个锁
      } finally {
        fs.closeSync(fd);
      }
      return { ok: true, handle: { path: lp, token, steals } };
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;   // 权限/路径问题必须炸掉，不能伪装成「锁竞争」
    }
    // 已被占用：先看是不是崩死留下的
    const age = lockAgeMs(lp);
    if (age != null && age > staleMs) {
      try { fs.unlinkSync(lp); steals++; } catch (_) { /* 别人先抢走并释放了 */ }
      continue;                           // 立刻重试抢锁，不消耗等待预算
    }
    if (Date.now() - started >= waitMs) {
      const cur = readLockMeta(lp);
      return { ok: false, reason: 'timeout', waitedMs: Date.now() - started,
               holder: cur && cur.meta ? cur.meta : null };
    }
    sleepSync(pollMs);
  }
}

/**
 * 放锁。**只在 token 匹配时删** —— 否则会删掉抢占者的锁，把互斥彻底破坏。
 * 返回 `{released:boolean, reason?:string}`，便于测试断言与告警。
 */
function releaseLock(handle) {
  if (!handle || !handle.path) return { released: false, reason: 'no_handle' };
  const cur = readLockMeta(handle.path);
  if (!cur) return { released: false, reason: 'gone' };
  if (!cur.meta || cur.meta.token !== handle.token) {
    return { released: false, reason: 'not_owner' };  // 锁已被 TTL 抢占：不碰它
  }
  try {
    fs.unlinkSync(handle.path);
    return { released: true };
  } catch (e) {
    return { released: false, reason: e.code };
  }
}

/**
 * 在锁内执行 `fn`。取不到锁时**不执行** `fn`，返回 `{locked:false, reason}` 交由调用方降级。
 * `fn` 抛错也会放锁（finally），不留残留。
 */
function withLock(filePath, fn, opts) {
  const got = acquireLock(filePath, opts);
  if (!got.ok) return { locked: false, reason: got.reason, waitedMs: got.waitedMs || 0 };
  try {
    return { locked: true, value: fn(got.handle) };
  } finally {
    releaseLock(got.handle);
  }
}

module.exports = {
  LOCK_SUFFIX, STALE_MS, WAIT_MS, POLL_MS,
  lockPathFor, sleepSync, newToken, readLockMeta, lockAgeMs,
  acquireLock, releaseLock, withLock,
};
