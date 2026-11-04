#!/usr/bin/env node
/* eslint-disable */
/**
 * doc-actions.cjs（CLI）— 提交前预检 actions JSON，拦住「同锚点多条 insert_after」。
 *
 * 用法:
 *   node scripts/doc-actions.cjs check <actions.json> [more.json ...]
 *
 * 退出码: 0 全部通过 / 1 存在冲突或读取失败 / 2 用法错误
 * 判据与 lib/doc-actions.cjs 同源 —— CLI 只做读写与打印，不做第二套判断。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const DA = require('./lib/doc-actions.cjs');

function usage() {
  console.log([
    '用法: node scripts/doc-actions.cjs check <actions.json> [more.json ...]',
    '',
    '检查 direct-edit actions 是否在同一锚点上用了多条 insert_after。',
    '该形态会按数组倒序落位（2026-10-21 实测 61 条落成「十八…十四」；',
    '2026-10-24 临时页对照实验复现：after×2 倒序、before×2/×3 正序）。',
    '正确写法: 一条 insert_after，多块在 content 内用空行串联。',
    'insert_before 同锚多条为正序，可直接分条书写，不在判据内。',
  ].join('\n'));
}

function main(argv) {
  const args = argv.slice(2);
  if (args.length === 0 || args[0] === '-h' || args[0] === '--help') { usage(); return 0; }
  const cmd = args[0];
  if (cmd !== 'check') { console.error('未知命令: ' + cmd); usage(); return 2; }
  const files = args.slice(1).filter((a) => a && a.charAt(0) !== '-');
  if (files.length === 0) { console.error('check 需要至少一个 actions JSON 路径'); return 2; }

  let bad = 0;
  for (const f of files) {
    const p = path.resolve(f);
    let actions;
    try {
      actions = JSON.parse(fs.readFileSync(p, 'utf8'));
    } catch (e) {
      bad++;
      console.error('FAIL ' + path.basename(f) + '  读取失败: ' + e.message);
      continue;
    }
    try {
      DA.assertNoAnchorCollision(actions);
      const nAfter = actions.filter((a) => a && a.type === DA.INSERT).length;
      const nBefore = actions.filter((a) => a && a.type === DA.INSERT_BEFORE).length;
      console.log('OK   ' + path.basename(f) + '  insert_after ' + nAfter +
        ' 条 · insert_before ' + nBefore + ' 条 · 同锚倒序 0');
    } catch (e) {
      bad++;
      console.error('FAIL ' + path.basename(f) + '  ' + e.message);
    }
  }
  if (bad) console.error('\n' + bad + ' 个文件未通过预检 —— 拒绝提交');
  return bad ? 1 : 0;
}

process.exit(main(process.argv));
