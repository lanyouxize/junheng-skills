/**
 * 共享核心的目录名 —— `cli/lib/` 里**唯一**按域取值的常量。
 *
 * ⚠ 必须与 `scripts/lib/skills-manifest.mjs` 的 `CORE_NAME` 逐字相等。
 *   两者**无法合并成单一来源**：本文件要被镜像进技能目录
 *   （`<skill>/scripts/lib/core-name.mjs`），而 `skills-manifest.mjs` **不镜像**
 *   （它在项目层），技能布局下那条相对路径不存在。
 *   ⇒ 唯一可行的兜底是**契约守卫**：断言两者相等，且本域**代码行**上该字面量只有一种。
 *
 * 为什么单独成文件（而不是写在 `locate.mjs` 里）：
 *   那样 `locate.mjs` 会带上一行域差异，两域无法逐字节共享。外提之后
 *   `locate.mjs` 成为**共享面成员**（`parity.json` 的 shared），
 *   域差异收敛到本文件的**一行常量**，跨域比对可归一化抹平。
 */
export const CORE_DIR_NAME = 'junheng-core'
