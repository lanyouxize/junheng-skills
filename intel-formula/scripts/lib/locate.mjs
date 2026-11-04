/**
 * 定位「被镜像的源码目录」（下称 vendor）与「是否主入口」判定。
 *
 * 为什么需要它：
 *   同一份门面脚本要在**三种**布局下都能跑通 ——
 *     · 项目布局：<repo>/cli/standards.mjs        → 源码在 <repo>/src/lib/
 *     · 技能布局（独立）：<skill>/scripts/cli.mjs → 源码在 <skill>/scripts/vendor/
 *     · 技能布局（引用共享核心）：<skill>/scripts/cli.mjs
 *                                                   → 源码在 <skills>/<core>/scripts/vendor/
 *   三种布局的**相对深度不同**。这里在运行时解析，而不是在同步时改写 import 路径。
 *   改写路径属于高危做法：一旦规则漏掉一种写法（`import './x.js'` 与 `import("./x.js")`
 *   混用、动态 import、再导出），就是「宿主机上正常、技能目录里崩」的隐蔽 bug。
 *
 *   第三种候选（共享核心）：门面位于 `<skill>/scripts/`，core 位于**同级**目录
 *   `<skills>/<core>/`，故相对深度是 `../../<core>/scripts/vendor`。
 *   探测顺序把项目布局放最前（开发时优先用真源，避免改错副本）。
 *
 * 本文件是**共享面成员**（`parity.json` 的 `shared`）：两域逐字节相同。
 *   唯一按域取值的是同目录的 `core-name.mjs`（差异 = 一行常量）。
 *   本模块零依赖（只用 node 内置），因为它自身也要被同步进技能目录。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { CORE_DIR_NAME } from './core-name.mjs'

// 重新导出：既有调用方（各域 `scripts/*contract-test.mjs`）仍可从本文件取该常量。
export { CORE_DIR_NAME }

/** 候选源码目录（按优先级返回，不判断存在性；便于测试与错误提示复用） */
export function vendorCandidates(here) {
  return [
    path.join(here, '..', 'src', 'lib'),                        // 项目布局：cli/ → ../src/lib
    path.join(here, 'vendor'),                                  // 技能布局（独立）：scripts/ → ./vendor
    path.join(here, '..', '..', CORE_DIR_NAME, 'scripts', 'vendor'), // 技能布局（共享核心）
  ]
}

/**
 * 选出真实存在的源码目录：要求**全部**探测文件都落在同一候选目录内。
 * 返回 null 表示都没命中 —— 调用方必须据此报「前置条件缺失」，
 * 绝不能猜一个路径硬跑（那会以 ENOENT 的形式炸在更深的地方，难以定位）。
 */
export function pickVendorDir(here, probe, exists = fs.existsSync) {
  const files = Array.isArray(probe) ? probe : [probe]
  if (files.length === 0) throw new Error('pickVendorDir 至少需要一个探测文件名')
  for (const dir of vendorCandidates(here)) {
    if (files.every((f) => exists(path.join(dir, f)))) return dir
  }
  return null
}

/** 从 vendor 载入源码模块；找不到目录时抛 `code='VENDOR_NOT_FOUND'` 的错误 */
export async function importFromVendor(here, probe, file) {
  const dir = pickVendorDir(here, probe)
  if (!dir) {
    const err = new Error(
      '找不到源码目录（前置条件缺失）。已尝试：\n'
      + vendorCandidates(here).map((d) => `      ${d}`).join('\n')
      + `\n      期望其中包含：${[].concat(probe).join('、')}\n`
      + '      项目内运行：确认 src/lib/ 存在。\n'
      + '      技能目录内运行：先执行 node scripts/sync-skills.mjs 同步镜像'
      + `（依赖共享核心的技能还需要同步 ${CORE_DIR_NAME}）。`,
    )
    err.code = 'VENDOR_NOT_FOUND'
    throw err
  }
  return import(pathToFileURL(path.join(dir, file)).href)
}

/**
 * 判断本模块是否被「直接执行」（而非被 import）。
 * 必须在 Windows 盘符大小写、符号链接、相对 argv[1] 三种情况下都判对 ——
 * 判错的后果是：测试里 import 门面 → 门面以为自己是主入口 → 去读 process.argv 并退出。
 */
export function isEntrypoint(metaUrl, argv1 = process.argv[1], realpath = fs.realpathSync) {
  if (!argv1) return false
  const self = fileURLToPath(metaUrl)
  const norm = (p) => {
    let q = p
    try { q = realpath(p) } catch { /* 文件不存在时退回原路径 */ }
    q = path.resolve(q)
    return process.platform === 'win32' ? q.toLowerCase() : q
  }
  return norm(self) === norm(argv1)
}
