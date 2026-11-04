/**
 * 零依赖 PDF 文本抽取（v4.15 / C 批）
 *
 * 只做一件事：从 PDF 字节里取回**可读正文**，取不回来就明确报告原因，
 * 绝不返回「看起来像正文」的垃圾。下游的归属校验（标题实词命中）由
 * fulltext-chain.cjs 的 assessText 负责，本模块只提供文本与自证统计。
 *
 * 为什么不用第三方库：本技能承诺零依赖（`--sources` 通道下连浏览器都不装）。
 * 实测可覆盖的 PDF 类型（见 CHANGELOG 取证）：未加密、无对象流、正文用
 * 字面串或可映射十六进制串的文本型 PDF —— 包括 PMC 那些「扫描图 + 不可见
 * OCR 文字层」的老文献（`3 Tr` 渲染模式，正是我们要的文本）。
 *
 * 明确不支持（返回 reason 而不猜）：
 *   - 加密 PDF（AES/RC4，零依赖解密不现实）
 *   - CID / Identity-H 且无 ToUnicode 的字体（抽出来是乱码，宁可不抽）
 *   - 纯图片扫描件（无文字层，需要 OCR）
 */

'use strict';

const zlib = require('zlib');

const PDF_MAGIC = '%PDF-';

/** Windows-1252 的 0x80–0x9F 区段（PDF 里最常见的「中文引号/破折号」来源） */
const CP1252_HIGH = {
  0x80: '\u20AC', 0x82: '\u201A', 0x83: '\u0192', 0x84: '\u201E', 0x85: '\u2026',
  0x86: '\u2020', 0x87: '\u2021', 0x88: '\u02C6', 0x89: '\u2030', 0x8A: '\u0160',
  0x8B: '\u2039', 0x8C: '\u0152', 0x8E: '\u017D', 0x91: '\u2018', 0x92: '\u2019',
  0x93: '\u201C', 0x94: '\u201D', 0x95: '\u2022', 0x96: '\u2013', 0x97: '\u2014',
  0x98: '\u02DC', 0x99: '\u2122', 0x9A: '\u0161', 0x9B: '\u203A', 0x9C: '\u0153',
  0x9E: '\u017E', 0x9F: '\u0178',
};

/** 是 PDF 吗（允许开头有少量 BOM/空白，实测有服务器前置换行） */
function isPdf(buf) {
  if (!buf || !buf.length) return false;
  const head = Buffer.isBuffer(buf) ? buf.subarray(0, 1024).toString('latin1') : String(buf).slice(0, 1024);
  return head.indexOf(PDF_MAGIC) >= 0;
}

/** 声明了加密就不能解（抽出来必然是乱码） */
function isEncrypted(buf) {
  const head = buf.subarray(0, Math.min(buf.length, 200 * 1024)).toString('latin1');
  return /\/Encrypt\s+\d+\s+\d+\s+R/.test(head);
}

/**
 * 扫描全部 stream…endstream 并尝试解压。
 *
 * 不做完整 xref 解析：本模块的判据是「拿到正文」，不是「符合 PDF 规范」。
 * 实测 PDF 1.3–1.7 的内容流都能被这条暴力扫描捞到；捞不到也只会漏（返回
 * 词数不足），不会误报（不会把图片流当成正文）。图片流解压后不含 BT/Tj。
 */
function inflateStreams(buf) {
  const out = { scanned: 0, inflated: 0, failed: 0, contents: [] };
  let from = 0;
  for (;;) {
    const s = buf.indexOf('stream', from);
    if (s < 0) break;
    // `stream` 后面必须是 CRLF 或 LF，否则是 endstream 里的子串
    let p = s + 6;
    if (buf[p] === 0x0d && buf[p + 1] === 0x0a) p += 2;
    else if (buf[p] === 0x0a) p += 1;
    else { from = s + 6; continue; }
    const e = buf.indexOf('endstream', p);
    if (e < 0) break;
    from = e + 9;
    out.scanned += 1;
    let blob = buf.subarray(p, e);
    // 去掉 endstream 前的 EOL
    let end = blob.length;
    if (end && blob[end - 1] === 0x0a) end -= 1;
    if (end && blob[end - 1] === 0x0d) end -= 1;
    blob = blob.subarray(0, end);
    let data = null;
    for (const fn of [() => zlib.inflateSync(blob), () => zlib.inflateRawSync(blob)]) {
      try { data = fn(); break; } catch (err) { /* 下一个 */ }
    }
    if (data) {
      out.inflated += 1;
      const s2 = data.toString('latin1');
      if (s2.indexOf('BT') >= 0 && (s2.indexOf('Tj') >= 0 || s2.indexOf('TJ') >= 0)) {
        out.contents.push(s2);
      }
    } else {
      out.failed += 1;
      // 未压缩的内容流（老 PDF 常见）：原样当内容流看
      const s2 = blob.toString('latin1');
      if (s2.indexOf('BT') >= 0 && (s2.indexOf('Tj') >= 0 || s2.indexOf('TJ') >= 0)) {
        out.contents.push(s2);
      }
    }
  }
  return out;
}

/** 把字面串的原始字节解码成文字；返回 {text, bad} */
function decodeStringBytes(bytes) {
  let text = '';
  let bad = 0;
  for (const b of bytes) {
    if (b === 0x09 || b === 0x0a || b === 0x0d) { text += ' '; continue; }
    if (b < 0x20) { bad += 1; continue; }
    if (b < 0x7f) { text += String.fromCharCode(b); continue; }
    if (b === 0x7f) { bad += 1; continue; }
    if (CP1252_HIGH[b]) { text += CP1252_HIGH[b]; continue; }
    if (b >= 0xa0) { text += String.fromCharCode(b); continue; }
    bad += 1;
  }
  return { text, bad };
}

/** 解 `(...)` 字面串：处理转义与嵌套括号 */
function readLiteral(src, i) {
  // src[i] === '('
  let depth = 1;
  let j = i + 1;
  const bytes = [];
  while (j < src.length) {
    const c = src[j];
    if (c === '\\') {
      const n = src[j + 1];
      if (n === 'n') { bytes.push(0x0a); j += 2; continue; }
      if (n === 'r') { bytes.push(0x0d); j += 2; continue; }
      if (n === 't') { bytes.push(0x09); j += 2; continue; }
      if (n === 'b') { bytes.push(0x08); j += 2; continue; }
      if (n === 'f') { bytes.push(0x0c); j += 2; continue; }
      if (n === '(' || n === ')' || n === '\\') { bytes.push(n.charCodeAt(0)); j += 2; continue; }
      if (/[0-7]/.test(n || '')) {
        let oct = '';
        let k = j + 1;
        while (k < src.length && oct.length < 3 && /[0-7]/.test(src[k])) { oct += src[k]; k += 1; }
        bytes.push(parseInt(oct, 8) & 0xff);
        j = k;
        continue;
      }
      if (n === '\n') { j += 2; continue; }   // 续行
      j += 2;
      continue;
    }
    if (c === '(') { depth += 1; bytes.push(0x28); j += 1; continue; }
    if (c === ')') {
      depth -= 1;
      if (!depth) { j += 1; break; }
      bytes.push(0x29); j += 1; continue;
    }
    bytes.push(c.charCodeAt(0) & 0xff);
    j += 1;
  }
  return { bytes, next: j };
}

/** 解 `<...>` 十六进制串 */
function readHex(src, i) {
  const end = src.indexOf('>', i);
  if (end < 0) return { bytes: [], next: src.length, isHex: true };
  let hex = src.slice(i + 1, end).replace(/[^0-9A-Fa-f]/g, '');
  if (hex.length % 2) hex += '0';
  const bytes = [];
  for (let k = 0; k < hex.length; k += 2) bytes.push(parseInt(hex.substr(k, 2), 16));
  return { bytes, next: end + 1, isHex: true };
}

const isDelim = (c) => c === undefined || ' \t\r\n\f\0()<>[]{}/%'.indexOf(c) >= 0;

/**
 * 从内容流里抽文本。
 *
 * 换行靠 y 坐标变化判断（Tm 的第 6 个操作数 / Td·TD 的 ty），不靠猜标点 ——
 * PDF 里没有「段落」概念，只有定位。TJ 数组里的负数间距按千分之一字号折算：
 * 实测 Cambridge 那篇 -335.7@15pt ≈ 5pt ≈ 0.33em 是词间空格，+40.5 是字间调距，
 * 故阈值取 -180（千分之一字号），既不吞空格也不把每个字母拆成单词。
 */
function extractTextFromContent(src, acc) {
  const state = { y: 0, size: 12, leading: 0, line: '', lines: [] };
  const flush = () => {
    const t = state.line.replace(/[ \t]+/g, ' ').trim();
    if (t) state.lines.push(t);
    state.line = '';
  };
  const emit = (s) => { if (s) state.line += s; };

  let i = 0;
  const operands = [];
  const SPACE_KERN = -180;

  while (i < src.length) {
    const c = src[i];
    if (isDelim(c)) {
      if (c === '(') {
        const r = readLiteral(src, i);
        operands.push({ t: 'str', v: decodeStringBytes(r.bytes) });
        i = r.next;
        continue;
      }
      if (c === '<' && src[i + 1] !== '<') {
        const r = readHex(src, i);
        const dec = decodeStringBytes(r.bytes);
        operands.push({ t: 'hex', v: dec });
        i = r.next;
        continue;
      }
      if (c === '[') { operands.push({ t: 'openarr' }); i += 1; continue; }
      if (c === ']') {
        // 收拢到最近的 openarr
        const arr = [];
        while (operands.length) {
          const top = operands.pop();
          if (top.t === 'openarr') break;
          arr.unshift(top);
        }
        operands.push({ t: 'arr', v: arr });
        i += 1;
        continue;
      }
      if (c === '%') { while (i < src.length && src[i] !== '\n') i += 1; continue; }
      if (c === '/' || c === ')' || c === '>' || c === '{' || c === '}' || c === '\0') { i += 1; continue; }
      i += 1;  // 空白
      continue;
    }

    // 数字
    if (/[0-9+\-.]/.test(c)) {
      let j = i;
      while (j < src.length && /[0-9+\-.]/.test(src[j])) j += 1;
      const n = Number(src.slice(i, j));
      operands.push({ t: 'num', v: Number.isFinite(n) ? n : 0 });
      i = j;
      continue;
    }

    // 名字 / 操作符
    if (/[A-Za-z'"*]/.test(c)) {
      let j = i;
      while (j < src.length && !isDelim(src[j])) j += 1;
      const op = src.slice(i, j);
      i = j;
      const lastNum = () => {
        for (let k = operands.length - 1; k >= 0; k -= 1) if (operands[k].t === 'num') return operands[k].v;
        return 0;
      };
      switch (op) {
        case 'Tf': state.size = lastNum() || state.size; break;
        case 'TL': state.leading = lastNum(); break;
        case 'Tm': {
          const nums = operands.filter(o => o.t === 'num');
          if (nums.length >= 6) {
            const ny = nums[5].v;
            if (Math.abs(ny - state.y) > 1) flush();
            state.y = ny;
          }
          break;
        }
        case 'Td':
        case 'TD': {
          const nums = operands.filter(o => o.t === 'num');
          if (nums.length >= 2) {
            const tx = nums[nums.length - 2].v;
            const ty = nums[nums.length - 1].v;
            if (Math.abs(ty) > 1) { flush(); state.y += ty; }
            // ★ 水平大跳 = 词间空格。实测 PMC 的 OCR 文字层（B2 那篇 1960 年
            //   扫描件）**不写空格字符**，靠 Td 定位单词：0.00 0 Td、33.36 0 Td、
            //   88.44 0 Td。不补这一步，整页文字会粘成 TRICHOBEZOARORHAIRBALLINACAT。
            //   阈值取 0.6 em：字符推进（约 0.5 em）不触发，够大才当空格，
            //   因此对「逐字 Td 定位」的 PDF 不会把每个字母拆开。
            else if (tx > 0.6 * (state.size || 12)) { emit(' '); }
          }
          break;
        }
        case 'T*': flush(); state.y -= state.leading || state.size * 1.2; break;
        case 'Tj': {
          const s = operands.length ? operands[operands.length - 1] : null;
          if (s && (s.t === 'str' || s.t === 'hex')) {
            emit(s.v.text);
            acc.chars += s.v.text.length;
            acc.bad += s.v.bad;
            if (s.t === 'hex') acc.hexChars += s.v.text.length;
          }
          break;
        }
        case 'TJ': {
          const a = operands.length ? operands[operands.length - 1] : null;
          if (a && a.t === 'arr') {
            for (const el of a.v) {
              if (el.t === 'str' || el.t === 'hex') {
                emit(el.v.text);
                acc.chars += el.v.text.length;
                acc.bad += el.v.bad;
                if (el.t === 'hex') acc.hexChars += el.v.text.length;
              } else if (el.t === 'num' && el.v < SPACE_KERN) {
                emit(' ');
              }
            }
          }
          break;
        }
        case "'":
        case '"': {
          flush();
          const s = operands.length ? operands[operands.length - 1] : null;
          if (s && (s.t === 'str' || s.t === 'hex')) {
            emit(s.v.text);
            acc.chars += s.v.text.length;
            acc.bad += s.v.bad;
            if (s.t === 'hex') acc.hexChars += s.v.text.length;
          }
          break;
        }
        case 'BT': flush(); break;
        case 'ET': flush(); break;
        default: break;
      }
      operands.length = 0;
      continue;
    }

    i += 1;
  }
  flush();
  return state.lines;
}

/**
 * 主入口。
 * @returns {{ok:boolean, reason:string|null, text:string, words:number, stats:object}}
 */
function extractPdfText(buf, opts) {
  const o = opts || {};
  const minWords = o.minWords == null ? 120 : o.minWords;
  const maxHexRatio = o.maxHexRatio == null ? 0.3 : o.maxHexRatio;

  const stats = {
    bytes: buf && buf.length ? buf.length : 0, encrypted: false,
    streams: 0, inflated: 0, inflateFailed: 0, contentStreams: 0,
    chars: 0, badChars: 0, hexChars: 0, hexRatio: 0, lines: 0, words: 0,
  };

  if (!isPdf(buf)) return { ok: false, reason: 'not_pdf', text: '', words: 0, stats };
  if (isEncrypted(buf)) {
    stats.encrypted = true;
    return { ok: false, reason: 'pdf_encrypted', text: '', words: 0, stats };
  }

  const scan = inflateStreams(buf);
  stats.streams = scan.scanned;
  stats.inflated = scan.inflated;
  stats.inflateFailed = scan.failed;
  stats.contentStreams = scan.contents.length;
  if (!scan.contents.length) {
    return { ok: false, reason: 'pdf_no_text_layer', text: '', words: 0, stats };
  }

  const acc = { chars: 0, bad: 0, hexChars: 0 };
  const lines = [];
  for (const content of scan.contents) {
    for (const ln of extractTextFromContent(content, acc)) lines.push(ln);
  }
  stats.chars = acc.chars;
  stats.badChars = acc.bad;
  stats.hexChars = acc.hexChars;
  stats.hexRatio = acc.chars ? Number((acc.hexChars / acc.chars).toFixed(3)) : 0;
  stats.lines = lines.length;

  // 乱码率：控制字符占比高说明编码没对上（典型是 CID 字体当单字节读了）
  const garble = acc.chars ? acc.bad / acc.chars : 1;
  if (garble > 0.2) {
    return { ok: false, reason: 'pdf_garbled_' + Math.round(garble * 100) + 'pct', text: '', words: 0, stats };
  }
  if (stats.hexRatio > maxHexRatio) {
    return { ok: false, reason: 'pdf_cid_encoding_unsupported', text: '', words: 0, stats };
  }

  const text = lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  const words = (text.match(/[A-Za-z]{2,}/g) || []).length;
  const letters = (text.match(/[A-Za-z]/g) || []).length;
  const spaces = (text.match(/ /g) || []).length;
  stats.words = words;
  stats.spaceRatio = letters ? Number((spaces / letters).toFixed(3)) : 0;

  // ★ 词间距丢失自证：英文正文空格数约占字母数 0.15–0.20。若远低于此，
  //   说明这一页的定位信息没能还原成空格（文字会粘成一长串），此时抽出来
  //   的「文本」不可用于检索与证据提取 —— 宁可判失败，不产出假正文。
  if (letters > 500 && stats.spaceRatio < 0.05) {
    return { ok: false, reason: 'pdf_word_spacing_lost', text, words, stats };
  }
  if (words < minWords) {
    return { ok: false, reason: 'pdf_too_few_words_' + words, text, words, stats };
  }
  return { ok: true, reason: null, text, words, stats };
}

module.exports = {
  PDF_MAGIC, isPdf, isEncrypted, inflateStreams, extractTextFromContent, extractPdfText,
};
