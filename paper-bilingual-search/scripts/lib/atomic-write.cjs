'use strict';
/**
 * lib/atomic-write.cjs — 原子写：写同目录临时文件 → fsync → rename 覆盖
 *
 * ★ 为什么必须有（2026-10-24 实证，非推测）：
 *   `fs.writeFileSync` 的语义是 `O_TRUNC` 后写入。在写那 600 KB 的窗口里，
 *   另一个并发进程（例如同时在跑的 `rank-records --iterate --converge-state`）
 *   `readFileSync` 会读到**空文件**或**半截 JSON**。实测 200 次写 / 624 KB：
 *   读者读到空 128 次、`JSON.parse` 失败 67 次、合法仅 12 次
 *   （`.verify/prove-m2.cjs`，`prove-m2-legacy.json`）。
 *   而 `readPrior` 把「解析失败」判为 `CORRUPT` 并**覆盖写回** ——
 *   于是「偶发并发」被放大成「20 个主题槽一次性清空」。这不是概率问题，是必然路径。
 *
 *   换成 rename 后，读者看到的是**完整的旧文件**或**完整的新文件**，不存在第三种状态。
 *
 * ★ 边界（不夸大，写清楚防止被当成更强的保证）：
 *   1. 只保证「不产生半截/空文件」，**不保证不丢更新** —— 两个进程各读旧、各写新，
 *      后者覆盖前者仍是丢更新。那是合并写（批 2）要解决的，本模块不声称解决。
 *   2. 临时文件必须与目标**同目录**：跨文件系统 `rename` 会退化为 copy+unlink，原子性消失。
 *      本模块强制从 `dirname(filePath)` 生成临时名，调用方无从传错。
 *   3. 数据 fsync 了，**目录项没有** ⇒ 掉电后可能回退到旧版本。
 *      这是有意的取舍：宁可退回旧值，也不能出现「文件在、内容空」。
 *   4. 崩溃时会残留 `*.tmp-*` 文件；用 `sweepTempFiles()` 清理，**绝不**碰非本模块命名的文件。
 *
 * ★ 临时名里带 pid + 随机串：同目录多进程并发写同名临时文件会互相截断，
 *   这是把「原子写」做坏的最常见方式。
 *
 * ★ Windows 专有陷阱（2026-10-24 实证，不加处理会让本模块在并发场景**直接写失败**）：
 *   `rename` 覆盖一个**正被其他进程打开**的文件时，Windows 抛 `EPERM`（POSIX 允许，Windows 不允许）。
 *   同一实验装置实测：不重试时 `wrote: 1` —— 第一次就被 reader 的读句柄挡住，原子写完全没生效。
 *   但并发读者的句柄是**瞬时**的（`readFileSync` 打开即关），所以正确解法是**退避重试**，
 *   而不是放弃 rename 改用 copy（copy 会把 M2 原样带回来）。
 *   重试后同一装置：写 200 次全部成功、读者空读 0 次、解析失败 0 次。
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const TMP_MARK = '.tmp-';

// Windows rename 占用退避：约 8+16+…+96 ≈ 620 ms 封顶。
// 时间常数取得比典型读句柄寿命（微秒级）宽两三个数量级，避免在高负载下漏判。
const RENAME_RETRY = { attempts: 12, stepMs: 8 };

/** 同步睡眠（CLI 场景可接受阻塞；不用 sleep 命令，避免平台差异与子进程开销） */
function sleepSync(ms) {
  if (!(ms > 0)) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** rename，遇到 Windows 的瞬时占用则退避重试；不可重试的错误立刻抛 */
function renameWithRetry(tmp, dest) {
  let last = null;
  for (let i = 0; i < RENAME_RETRY.attempts; i++) {
    try {
      fs.renameSync(tmp, dest);
      return i;                                  // 返回重试次数，便于诊断
    } catch (e) {
      last = e;
      const code = e && e.code;
      const retriable = code === 'EPERM' || code === 'EBUSY' || code === 'EACCES';
      if (!retriable) throw e;
      sleepSync(RENAME_RETRY.stepMs * (i + 1));
    }
  }
  throw last;
}

/** 生成同目录下的唯一临时路径（同目录是原子性的前提，不接受调用方覆盖目录） */
function tempPathFor(filePath) {
  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  return path.join(dir, base + TMP_MARK + process.pid + '-' + crypto.randomBytes(6).toString('hex'));
}

/**
 * 原子地写文件。
 * @param {string} filePath 目标路径（父目录不存在则按 recursive 自建）
 * @param {string|Buffer} content 内容
 * @param {string} [encoding] 字符串编码，默认 utf8
 * @param {Object} [opts] `{ hooks: { afterTemp(tmpPath), beforeRename(tmpPath) } }`
 *   ★ hooks 只为**可测试性**存在：`afterTemp` 在「临时文件已落盘、rename 尚未发生」时被调用，
 *     测试可在此刻读主文件，断言读到的是**完整旧内容**。这是确定性证明，不靠 sleep 拼竞态。
 *   生产调用不传 hooks，行为完全一致。
 * @returns {string} 实际写入的路径
 */
function writeAtomicSync(filePath, content, encoding, opts) {
  const enc = typeof encoding === 'string' ? encoding : 'utf8';
  const o = typeof encoding === 'object' && encoding !== null ? encoding : (opts || {});
  const hooks = o.hooks || {};
  const buf = Buffer.isBuffer(content) ? content : Buffer.from(String(content), enc);

  const dir = path.dirname(filePath);
  if (dir && dir !== '.' && !fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const tmp = tempPathFor(filePath);
  let fd = null;
  try {
    fd = fs.openSync(tmp, 'wx', 0o600);       // 'wx'：已存在即失败，杜绝与别的进程撞名后互相截断
    let off = 0;
    while (off < buf.length) off += fs.writeSync(fd, buf, off, buf.length - off);
    fs.fsyncSync(fd);                          // 先落盘再改名：掉电最多退回旧版本，不会留下空文件
    fs.closeSync(fd);
    fd = null;
  } catch (e) {
    if (fd !== null) { try { fs.closeSync(fd); } catch (_) {} }
    try { fs.unlinkSync(tmp); } catch (_) {}   // 失败不留垃圾
    throw e;
  }

  try {
    if (typeof hooks.afterTemp === 'function') hooks.afterTemp(tmp);
    if (typeof hooks.beforeRename === 'function') hooks.beforeRename(tmp);
    // 同目录内原子替换；Windows 下目标被占用会 EPERM ⇒ 退避重试（见头注释）
    renameWithRetry(tmp, filePath);
  } catch (e) {
    try { fs.unlinkSync(tmp); } catch (_) {}
    throw e;
  }
  return filePath;
}

/**
 * 清理**本模块命名规则**的残留临时文件（崩溃遗留）。
 * 判据是名字里的 `TMP_MARK` + pid + 12 位 hex 结构；其他文件一律不碰。
 * @param {string} filePath 目标文件路径（只清它自己的残留）
 * @param {Object} [opts] `{ keepPid: boolean }` 默认保留当前进程的（可能有正在进行的写）
 * @returns {string[]} 被删掉的路径
 */
function sweepTempFiles(filePath, opts) {
  const o = opts || {};
  const dir = path.dirname(filePath);
  const re = new RegExp('^' + escapeRe(path.basename(filePath) + TMP_MARK) + '\\d+-[0-9a-f]{12}$');
  let names = [];
  try { names = fs.readdirSync(dir); } catch (_) { return []; }
  const gone = [];
  for (const n of names) {
    if (!re.test(n)) continue;
    if (o.keepPid !== false && n.slice(path.basename(filePath).length + TMP_MARK.length).split('-')[0] === String(process.pid)) continue;
    const p = path.join(dir, n);
    try { fs.unlinkSync(p); gone.push(p); } catch (_) {}
  }
  return gone;
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

module.exports = { TMP_MARK, RENAME_RETRY, tempPathFor, writeAtomicSync, sweepTempFiles };
