#!/usr/bin/env node
// junheng-orchestrator / prime.mjs
// 知识库 grep 注入：按关键词匹配 knowledge/*.jsonl，输出可注入编排上下文的知识块。
// 零依赖：仅用 Node 内置 fs/path。对齐 metaswarm knowledge「prime 前加载」范式。
//
// 用法：
//   node scripts/prime.mjs 钙磷比 脂肪酸
//   node scripts/prime.mjs --list            # 列出全部 topic 标签
//   node scripts/prime.mjs                   # 无参数 → 提示用法 + 可用 topic

import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const KNOWLEDGE_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'knowledge')

function loadFacts() {
  const facts = []
  for (const fn of readdirSync(KNOWLEDGE_DIR)) {
    if (!fn.endsWith('.jsonl')) continue
    const type = fn.replace(/\.jsonl$/, '')
    const text = readFileSync(join(KNOWLEDGE_DIR, fn), 'utf8')
    for (const line of text.split('\n')) {
      const s = line.trim()
      if (!s) continue
      try {
        const obj = JSON.parse(s)
        facts.push({ type, ...obj })
      } catch {
        // 跳过损坏行，不中断
      }
    }
  }
  return facts
}

const args = process.argv.slice(2)

if (args.length === 0) {
  const facts = loadFacts()
  const topics = new Set()
  facts.forEach((f) => (f.tags || []).forEach((t) => topics.add(t)))
  console.log('用法: node scripts/prime.mjs <关键词1> [关键词2 ...]')
  console.log('可用 topic 标签:', [...topics].sort().join(', '))
  console.log(`知识库当前共 ${facts.length} 条 (gotchas/patterns/decisions/anti-patterns)`)
  process.exit(0)
}

if (args[0] === '--list') {
  const facts = loadFacts()
  const topics = new Set()
  facts.forEach((f) => (f.tags || []).forEach((t) => topics.add(t)))
  console.log([...topics].sort().join(', '))
  process.exit(0)
}

const kws = args.map((a) => a.toLowerCase())
const facts = loadFacts()
const hits = facts.filter((f) => {
  const hay = JSON.stringify(f).toLowerCase()
  return kws.some((k) => hay.includes(k))
})

if (hits.length === 0) {
  console.log(`[prime] 无命中: ${kws.join(' / ')}`)
  console.log(`[prime] 可用 topic 见: node scripts/prime.mjs --list`)
  process.exit(0)
}

console.log(`=== junheng-orchestrator 知识库命中 ${hits.length} 条 (topic: ${kws.join(' / ')}) ===`)
for (const f of hits) {
  console.log(`\n[${f.type}] ${f.id} (confidence=${f.confidence})`)
  console.log(`  fact: ${f.fact}`)
  console.log(`  recommendation: ${f.recommendation}`)
  if (f.provenance) console.log(`  provenance: ${f.provenance}`)
  if (f.affectedFiles) console.log(`  affectedFiles: ${f.affectedFiles.join(', ')}`)
  if (f.tags && f.tags.length) console.log(`  tags: ${f.tags.join(', ')}`)
}
console.log('\n=== 注入完毕（以上块可粘贴进编排上下文）===')
