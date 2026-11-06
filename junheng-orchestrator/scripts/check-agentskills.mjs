#!/usr/bin/env node
// check-agentskills.mjs — junheng 技能 agentskills.io 兼容性核查（零依赖）
//
// 依据（分级，不臆造强制项）：
//   Tier1 强制：agentskills.io 开放标准（已抓取验证）
//     - 技能 = 含 SKILL.md 的文件夹
//     - SKILL.md frontmatter 至少含 name + description
//     - 含指令正文
//   Tier2 推荐：Anthropic 开放标准惯例（明确标注，非 agentskills.io 强制）
//     - name == 目录名；name 符合 ^[a-z0-9]+(-[a-z0-9]+)*$
//     - description ≤1024 字符且含触发词
//     - 双语 description_en（钧衡内部约定）；author / version 存在
//
// 退出码：任一 Tier1 FAIL → 1；否则 0（WARN 不阻断，供人工跟进）。

import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs'
import { join, basename, resolve } from 'node:path'

const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/
const DESC_MAX = 1024
const TRIGGERS = ['当用户', '使用', '问', 'when', 'When']

function parseFrontmatter(text) {
  // 取第一对 --- 围栏之间的内容；支持带引号的值（剥离外层引号）
  const fm = {}
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/)
  if (!m) return { fm, hasFence: false, body: text.replace(/^---\r?\n?/, '') }
  const block = m[1]
  for (const line of block.split(/\r?\n/)) {
    const mm = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/)
    if (!mm) continue
    const key = mm[1]
    let val = mm[2].trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    fm[key] = val
  }
  const body = text.slice((m[0].length)).replace(/^\r?\n/, '')
  return { fm, hasFence: true, body }
}

function checkSkill(dir) {
  const name = basename(dir)
  const skillMd = join(dir, 'SKILL.md')
  const res = { skill: name, checks: [], hardFail: false }

  const add = (id, tier, label, status, detail) => {
    if (tier === 'T1' && status === 'FAIL') res.hardFail = true
    res.checks.push({ id, tier, label, status, detail })
  }

  if (!existsSync(skillMd)) {
    add('C1', 'T1', 'SKILL.md 存在', 'FAIL', '缺少 SKILL.md')
    return res
  }
  const text = readFileSync(skillMd, 'utf8')
  const { fm, hasFence, body } = parseFrontmatter(text)

  // T1-1 frontmatter 存在
  add('C2', 'T1', 'frontmatter 合法 (--- 围栏)', hasFence ? 'PASS' : 'FAIL', hasFence ? '已解析' : '未找到 --- 围栏')

  // T1-2 name 非空
  const nm = fm.name || ''
  add('C3', 'T1', 'name 非空', nm ? 'PASS' : 'FAIL', nm ? `name="${nm}"` : 'frontmatter 无 name')

  // T1-3 description 非空
  const desc = fm.description || ''
  add('C4', 'T1', 'description 非空', desc ? 'PASS' : 'FAIL', desc ? `长度 ${[...desc].length}` : 'frontmatter 无 description')

  // T1-4 指令正文
  const bodyLen = [...(body || '')].length
  add('C5', 'T1', '含指令正文', bodyLen > 50 ? 'PASS' : 'FAIL', `正文 ${bodyLen} 字符`)

  // T2-1 name == 目录名
  if (nm) add('C6', 'T2', 'name == 目录名', nm === name ? 'PASS' : 'WARN', `name="${nm}" dir="${name}"`)

  // T2-2 name 正则
  if (nm) add('C7', 'T2', 'name 符合 ^[a-z0-9]+(-[a-z0-9]+)*$', NAME_RE.test(nm) ? 'PASS' : 'WARN', NAME_RE.test(nm) ? '匹配' : `不符: ${nm}`)

  // T2-3 description 长度
  if (desc) {
    const len = [...desc].length
    add('C8', 'T2', `description ≤${DESC_MAX} 字符`, len <= DESC_MAX ? 'PASS' : 'WARN', `长度 ${len}`)
  }

  // T2-4 触发词
  if (desc) {
    const hit = TRIGGERS.find((t) => desc.includes(t))
    add('C9', 'T2', 'description 含触发词', hit ? 'PASS' : 'WARN', hit ? `命中 "${hit}"` : '无触发词（建议补"当用户…时使用"）')
  }

  // T2-5 双语 description_en
  add('C10', 'T2', '双语 description_en', fm.description_en ? 'PASS' : 'WARN', fm.description_en ? '存在' : '缺失（钧衡内部约定）')

  // T2-6 author
  add('C11', 'T2', 'author 存在', fm.author ? 'PASS' : 'WARN', fm.author || '缺失')

  // T2-7 version
  add('C12', 'T2', 'version 存在', fm.version ? 'PASS' : 'WARN', fm.version || '缺失')

  // INFO 可选目录
  const optDirs = ['scripts', 'references', 'assets']
  const present = optDirs.filter((d) => existsSync(join(dir, d)) && statSync(join(dir, d)).isDirectory())
  add('C13', 'INFO', '可选目录', 'INFO', present.length ? present.join(', ') : '无（可选）')

  return res
}

function main() {
  const root = resolve(process.argv[2] || process.env.HOME + '/.workbuddy/skills')
  const onlyJson = process.argv.includes('--json')
  const dirs = readdirSync(root, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => join(root, e.name))
    .filter((d) => existsSync(join(d, 'SKILL.md')))
    .sort()

  const results = dirs.map(checkSkill)

  if (onlyJson) {
    console.log(JSON.stringify(results, null, 2))
    process.exit(results.some((r) => r.hardFail) ? 1 : 0)
  }

  let totalFail = 0, totalWarn = 0
  console.log(`agentskills.io 兼容性核查 — 根目录: ${root}`)
  console.log(`共 ${results.length} 个技能\n`)
  for (const r of results) {
    const fails = r.checks.filter((c) => c.status === 'FAIL').length
    const warns = r.checks.filter((c) => c.status === 'WARN').length
    totalFail += fails; totalWarn += warns
    const tag = fails ? '✗ FAIL' : warns ? '△ WARN' : '✓ PASS'
    console.log(`【${r.skill}】 ${tag}  (FAIL ${fails} / WARN ${warns})`)
    for (const c of r.checks) {
      if (c.status === 'INFO') continue
      const mark = c.status === 'PASS' ? '✓' : c.status === 'FAIL' ? '✗' : '△'
      console.log(`   ${mark} [${c.tier}] ${c.label} — ${c.detail}`)
    }
  }
  console.log(`\n汇总: 技能 ${results.length} | Tier1 FAIL ${totalFail} | Tier2 WARN ${totalWarn}`)
  console.log(totalFail ? '结论: 不兼容（存在 Tier1 强制项 FAIL）' : '结论: 兼容 agentskills.io 强制规范（WARN 为推荐项，不阻断）')
  process.exit(totalFail ? 1 : 0)
}

main()
