/**
 * BCS（体况评分）参考示意图 —— 纯 SVG 矢量、零依赖、可离线内联。
 *
 * 为什么不直接搬用权威机构的现成 BCS 图：
 *   1. 通行的 BCS 图（WSAVA / APOP / Purina / Royal Canin）**都受版权保护**
 *      —— APOP 的图表上就印着「© APOP」，把它翻译、改字后重新发布属演绎作品，
 *      商用交付需事先取得书面授权。本文件只按**公开发表的判据**
 *      （Laflamme 1997；体脂率区间据 2021 AAHA）自行绘制，画面与配色均为原创；
 *   2. 导出文档要求**自包含**（不允许外链图片），数张实拍图 base64 内联会把文档撑到几 MB；
 *   3. 实拍素材受毛长、拍摄角度、个体差异影响极大，宠主对着自己的狗反而更难判断。
 *      判据本身（腹部上提 / 腰线内收 / 肋骨可触）才是判断依据，矢量图只画判据。
 *
 * 视角对齐通行做法：每档给「侧视」（看腹部上提）+「俯视」（看腰线内收）。
 *
 * ⚠ 单一真值源：几何数据只在本文件定义一次，React 组件与导出 HTML 渲染同一份数据
 *   （组件用 `figureShapes()` 取数据渲染，导出用 `figureSvg()` 拼字符串）。
 * ⚠ 本文件属于「渲染出来的文案」，**不许出现 Markdown 星号**（会被 jsx-text-markdown 扫到）。
 */

/** 体型分类：用户要能按「大型犬 / 小型犬 / 猫」分别对照 */
export const BCS_FIGURE_TYPES = [
  { id: 'smallDog', label: '小型犬', hint: '成年体重 10 kg 以下（吉娃娃、博美、泰迪等）' },
  { id: 'largeDog', label: '大型犬', hint: '成年体重 25 kg 以上（金毛、拉布拉多、德牧等）' },
  { id: 'cat', label: '猫', hint: '不限品种；长毛猫请以「触摸肋骨」为准，毛量会掩盖腰线' },
]

/** 三档对照：造型按 3 / 5 / 7 分画，但卡片标注必须写**覆盖区间**。
 *  ⚠ 只写 「BCS 7」会误导：8~9 分（肥胖）也归在这一档卡上，
 *    实测示例犬 BCS 8 时卡片标着「偏胖（BCS 7）· 当前档」，数字对不上。 */
export const BCS_FIGURE_LEVELS = [
  { key: 'thin', group: 'thin', score: 3, range: '1–3', label: '偏瘦' },
  { key: 'ideal', group: 'ideal', score: 5, range: '4–5', label: '理想' },
  { key: 'over', group: 'over', score: 7, range: '6–9', label: '偏胖/肥胖' },
]

/** 组合画布：侧视在左、俯视在右 */
export const FIGURE_VIEW = { w: 344, h: 108, topDx: 184, sideW: 160 }

/** 单幅画布 160 × 108，地面 y = 98（脚底） */
const CANVAS = { w: 160, h: 108, ground: 98 }

const r1 = (v) => Math.round(v * 10) / 10

/* ---- 侧视骨架（理想档的基准值）----
   shoulderX → hipX 是躯干长度，backY → chestY 是躯干深度，两者之比约 2.4~2.7
   （早期版本把躯干画成了 4:1 的细长条，看着像腊肠而不是犬）。
   chestY 是躯干轮廓的最低点（胸底），tuckY 是腹线上提末端 —— 两者之差 upTuck
   就是 BCS 侧视的核心判据「腹部上提」。 */
const SIDE_BASE = {
  smallDog: {
    head: { cx: 35, cy: 25, r: 13 }, muzzle: { len: 12, h: 10 }, ear: 'drop',
    shoulderX: 52, hipX: 122, backY: 34, chestY: 62, tuckY: 54,
    frontW: 7.5, rearW: 10, tail: 'up',
  },
  largeDog: {
    head: { cx: 36, cy: 23, r: 12 }, muzzle: { len: 14, h: 11 }, ear: 'drop',
    shoulderX: 54, hipX: 132, backY: 28, chestY: 64, tuckY: 56,
    frontW: 9.5, rearW: 12.5, tail: 'down',
  },
  cat: {
    head: { cx: 36, cy: 27, r: 11.5 }, muzzle: { len: 8, h: 7.5 }, ear: 'prick',
    shoulderX: 52, hipX: 122, backY: 36, chestY: 62, tuckY: 55,
    frontW: 6.5, rearW: 8.5, tail: 'curl',
  },
}

/* ---- 俯视骨架（理想档的基准值）---- */
const TOP_BASE = {
  smallDog: { headR: 11, headY: 20, shoulderY: 44, waistY: 62, hipY: 80 },
  largeDog: { headR: 10.5, headY: 19, shoulderY: 40, waistY: 58, hipY: 78 },
  cat: { headR: 10, headY: 20, shoulderY: 46, waistY: 66, hipY: 82 },
}

const TOP_CX = 80

/* ---- 档位偏移 ----
   chest / tuck / back 是侧视的纵向偏移（y 越大越靠下）；
   waist / shoulder / hip 是俯视的半宽。
   ⚠ 三档必须让「腹部上提量」单调递减（thin > ideal > over）、
     俯视腰宽单调递增 —— 这是参考图唯一真正要表达的东西，其余都是造型。 */
const LEVEL_ADJ = {
  thin: { chest: -7, tuck: -10, back: -2, waist: 9, shoulder: 24, hip: 22 },
  ideal: { chest: 0, tuck: 0, back: 0, waist: 19, shoulder: 28, hip: 26 },
  over: { chest: 7, tuck: 11, back: 2, waist: 32, shoulder: 34, hip: 33 },
}

/* ---- 图层 ---------------------------------------------------------------
   部件的画法是「统一剪影」两遍法：把所有躯干部件先按粗描边画一遍，
   再用纯填充盖住内部的描边 —— 这样重叠处（颈/躯干/腿/头）不会露出一堆内部线条，
   整只动物只有一条外轮廓。早先各部件各画各的，叠在一起像卡通积木，非常廉价。

   back  = 背景层（地面线、尾、远侧腿）—— 会被剪影盖住一部分
   sil   = 剪影层（颈、躯干、近侧腿、头、吻、耳）—— 画两遍（描边遍 + 填充遍）
   front = 前景层（眼、腰线辅助线）—— 必须压在最上面
   ⚠ 渲染顺序必须是 back → sil(描边) → sil(填充) → front，换序就会破功。 */
export const FIGURE_LAYERS = ['back', 'sil', 'front']

/** 把扁平图元按图层分组（React 与导出共用同一套分组，避免两边各写一遍） */
export function figureLayers(shapes) {
  const out = { back: [], sil: [], front: [] }
  for (const sh of shapes) out[sh.layer || 'sil'].push(sh)
  return out
}

/* ---- 部件形状 ---------------------------------------------------------- */

/** 前肢：从胸底垂下的柱体，脚掌略圆。
 *  ⚠ 远侧腿（far）归 `back` 层，要在躯干**之前**画；近侧腿归 `sil` 层参与剪影合成。 */
const frontLeg = (x, top, gy, w, cls, layer = 'sil') => ({
  el: 'path',
  cls,
  layer,
  d: `M ${r1(x)},${r1(top)} L ${r1(x + w)},${r1(top)}`
    + ` L ${r1(x + w - 1.2)},${r1(gy - 5)}`
    + ` Q ${r1(x + w / 2)},${r1(gy + 1.6)} ${r1(x + 1.2)},${r1(gy - 5)} Z`,
})

/** 后肢：上段（大腿）向后鼓起，收到飞节后再垂直落地 —— 这个转折是犬后肢的识别特征。
 *  ⚠ 别把大腿画成挂在腹侧的「鸡腿」：上段的宽度要收在躯干轮廓里，只让飞节以下露出来。 */
const rearLeg = (x, top, gy, w, cls, layer = 'sil') => {
  const hockY = r1(gy - 13)
  const bulge = r1(top + (hockY - top) * 0.55)
  return {
    el: 'path',
    cls,
    layer,
    d: `M ${r1(x)},${r1(top)} L ${r1(x + w)},${r1(top)}`
      + ` C ${r1(x + w + 2)},${bulge} ${r1(x + w - 1.5)},${r1(hockY - 4)} ${r1(x + w - 3)},${hockY}`
      + ` L ${r1(x + w - 3.5)},${r1(gy - 5)}`
      + ` Q ${r1(x + w / 2)},${r1(gy + 1.6)} ${r1(x + 3.5)},${r1(gy - 5)}`
      + ` L ${r1(x + 3)},${hockY}`
      + ` C ${r1(x + 1.5)},${r1(hockY - 4)} ${r1(x - 2)},${bulge} ${r1(x)},${r1(top)} Z`,
  }
}

/** 尾：三套**闭合锥形**路径（上翘 / 下垂 / 长而卷），起笔落在臀部之内。
 *  ⚠ 别用「粗描边」画尾：粗描边的尾与臀线一叠，就成了插在屁股上的三角旗。
 *    改成剪影层的实心图形后，尾与躯干合成同一条外轮廓，是真正的尾形。 */
const TAIL_D = {
  up: (x, y) => `M ${x},${y} C ${x + 6},${y - 8} ${x + 12},${y - 15} ${x + 20},${y - 16}`
    + ` C ${x + 18},${y - 9} ${x + 13},${y - 2} ${x + 7},${y + 6} Z`,
  down: (x, y) => `M ${x},${y} C ${x + 8},${y} ${x + 15},${y + 4} ${x + 19},${y + 11}`
    + ` C ${x + 12},${y + 11} ${x + 5},${y + 8} ${x - 1},${y + 4} Z`,
  curl: (x, y) => `M ${x},${y} C ${x + 11},${y - 2} ${x + 19},${y + 6} ${x + 17},${y + 15}`
    + ` C ${x + 15},${y + 23} ${x + 7},${y + 25} ${x + 2},${y + 20}`
    + ` C ${x + 7},${y + 21} ${x + 12},${y + 18} ${x + 11},${y + 11}`
    + ` C ${x + 10},${y + 5} ${x + 5},${y + 2} ${x},${y + 3} Z`,
}

/** 头：颅 + 吻 + 耳 + 眼。⚠ 吻部别拉长、也别收成尖楔 —— 圆躯干 + 尖长鼻会读成鸟。
 *  ⚠ 垂耳（犬）要够大：小小的耳片会让整只读不出犬相。 */
function headShapes(h, m, ear) {
  const out = []
  out.push({ el: 'circle', cls: 'fig-body', layer: 'sil', cx: h.cx, cy: h.cy, r: h.r })
  const x0 = h.cx - h.r + 5
  const x1 = h.cx - h.r - m.len
  const yT = h.cy - m.h / 2
  const yB = h.cy + m.h / 2
  out.push({
    el: 'path',
    cls: 'fig-body',
    layer: 'sil',
    d: `M ${r1(x0)},${r1(yT)} L ${r1(x1 + 3)},${r1(yT + 0.6)}`
      + ` Q ${r1(x1)},${r1(yT + 2)} ${r1(x1)},${r1(h.cy)}`
      + ` Q ${r1(x1)},${r1(yB - 2)} ${r1(x1 + 3)},${r1(yB - 0.6)}`
      + ` L ${r1(x0)},${r1(yB)} Z`,
  })
  if (ear === 'prick') {
    out.push({ el: 'path', cls: 'fig-body', layer: 'sil', d: `M ${h.cx - 5},${r1(h.cy - h.r + 5)} L ${h.cx - 8},${r1(h.cy - h.r - 11)} L ${h.cx + 4},${r1(h.cy - h.r + 3)} Z` })
    out.push({ el: 'path', cls: 'fig-body', layer: 'sil', d: `M ${h.cx + 4},${r1(h.cy - h.r + 3)} L ${h.cx + 9},${r1(h.cy - h.r - 9)} L ${h.cx + 13},${r1(h.cy - h.r + 7)} Z` })
  } else {
    out.push({
      el: 'path',
      cls: 'fig-body',
      layer: 'sil',
      d: `M ${r1(h.cx + 2)},${r1(h.cy - h.r + 1)} C ${r1(h.cx + h.r + 3)},${r1(h.cy - h.r + 3)}`
        + ` ${r1(h.cx + h.r + 2)},${r1(h.cy + 8)} ${r1(h.cx + 5)},${r1(h.cy + 9)}`
        + ` C ${r1(h.cx - 1)},${r1(h.cy + 9)} ${r1(h.cx - 1)},${r1(h.cy - h.r + 4)} ${r1(h.cx + 2)},${r1(h.cy - h.r + 1)} Z`,
    })
  }
  /* 眼：`front` 层，必须压在剪影之上，否则会被填充遍整个盖掉 */
  out.push({ el: 'circle', cls: 'fig-dot', layer: 'front', cx: r1(h.cx - 5), cy: r1(h.cy - 1), r: 1.7 })
  return out
}

function sideShapes(s, lv) {
  const backY = s.backY + lv.back
  const chestY = s.chestY + lv.chest
  const tuckY = s.tuckY + lv.tuck
  const sx = s.shoulderX
  const hx = s.hipX
  const chestX = sx + 14      // 胸底最深处
  const tuckX = hx - 22       // 腹线上提末端
  const gy = CANVAS.ground
  const out = []

  /* 0) 地面线：给画面一个立足基准，不参与判据（背景层，会被剪影压住中段） */
  out.push({ el: 'path', cls: 'fig-ground', layer: 'back', d: `M 6,${gy} L 154,${gy}` })

  /* 1) 尾（剪影层，起笔点在躯干内部，只有露在躯干外的部分可见） */
  out.push({ el: 'path', cls: 'fig-body', layer: 'sil', d: TAIL_D[s.tail](r1(hx - 4), r1(backY + 4)) })

  /* 2) 远侧两条腿（背景层，淡色；上段会被躯干填充盖住，只留下露在躯干外的一段） */
  out.push(frontLeg(sx + 13, chestY - 5, gy, s.frontW - 1, 'fig-leg far', 'back'))
  out.push(rearLeg(hx - 10, tuckY - 2, gy, s.rearW - 1.5, 'fig-leg far', 'back'))

  /* 3) 颈（剪影层，右半段被躯干盖住，避免「头浮在身体旁边」） */
  out.push({
    el: 'path',
    cls: 'fig-body',
    layer: 'sil',
    d: `M ${r1(s.head.cx + 2)},${r1(s.head.cy - 6)} L ${r1(sx + 4)},${r1(backY + 1)}`
      + ` L ${r1(sx + 4)},${r1(chestY - 14)} L ${r1(s.head.cx + 2)},${r1(s.head.cy + 9)} Z`,
  })

  /* 4) 躯干：背线 → 臀 → 腹线（关键判据）→ 前胸
     控制点全部写成「相对量」，同一个骨架公式就能自然适配三档三体型。 */
  out.push({
    el: 'path',
    cls: 'fig-body',
    layer: 'sil',
    d: [
      `M ${sx},${backY}`,
      `C ${r1(sx + 24)},${r1(backY - 5)} ${r1(hx - 28)},${r1(backY - 6)} ${hx},${backY}`,
      `C ${r1(hx + 6)},${r1(backY + (tuckY - backY) * 0.58)}`
        + ` ${r1(hx + 2)},${r1(tuckY - (tuckY - backY) * 0.14)}`
        + ` ${r1(tuckX + 14)},${tuckY}`,
      `C ${r1(tuckX - 6)},${r1(tuckY + (chestY - tuckY) * 0.10)}`
        + ` ${r1(chestX + 16)},${r1(chestY - (chestY - tuckY) * 0.42)}`
        + ` ${chestX},${chestY}`,
      `C ${r1(chestX - 12)},${r1(chestY - (chestY - backY) * 0.16)}`
        + ` ${r1(sx - 4)},${r1(chestY - (chestY - backY) * 0.72)}`
        + ` ${sx},${backY}`,
      'Z',
    ].join(' '),
  })

  /* 5) 近侧两条腿（剪影层：与躯干合成同一个填充、同一条外轮廓，前后关系靠远侧腿的浅色区分） */
  out.push(frontLeg(sx + 2, chestY - 5, gy, s.frontW, 'fig-leg'))
  out.push(rearLeg(hx - 21, tuckY - 1, gy, s.rearW, 'fig-leg'))

  /* 6) 头（剪影层 + 前景层的眼） */
  out.push(...headShapes(s.head, s.muzzle, s.ear))

  return {
    shapes: out,
    meta: { chestY, tuckY, upTuck: r1(chestY - tuckY), backY },
  }
}

function topShapes(t, lv, typeId) {
  const cx = TOP_CX
  const shW = lv.shoulder
  const waistW = lv.waist
  const hipW = lv.hip
  /* ⚠ 颈部起点要**往头里多插一点**（neckY < headBottom）：只差 3px 时头与躯干
     的剪影刚好相切，合出来会在脖子上留一个豁口。 */
  const headBottom = t.headY + t.headR - 3
  const neckY = headBottom - 6
  const out = []

  /* 躯干：颈 → 肩（最宽）→ 腰（关键判据：内收多少）→ 臀 → 尾端 */
  out.push({
    el: 'path',
    cls: 'fig-body',
    layer: 'sil',
    d: [
      `M ${r1(cx - 7)},${neckY}`,
      `C ${r1(cx - 8)},${r1(neckY + 10)} ${r1(cx - shW + 5)},${r1(t.shoulderY - 8)} ${r1(cx - shW)},${t.shoulderY}`,
      `C ${r1(cx - shW)},${r1(t.shoulderY + 7)} ${r1(cx - waistW - 3)},${r1(t.waistY - 9)} ${r1(cx - waistW)},${t.waistY}`,
      `C ${r1(cx - waistW + 4)},${r1(t.waistY + 6)} ${r1(cx - hipW)},${r1(t.hipY - 9)} ${r1(cx - hipW + 2)},${t.hipY}`,
      `C ${r1(cx - hipW + 5)},${r1(t.hipY + 11)} ${r1(cx - 8)},${r1(t.hipY + 15)} ${cx},${r1(t.hipY + 17)}`,
      `C ${r1(cx + 8)},${r1(t.hipY + 15)} ${r1(cx + hipW - 5)},${r1(t.hipY + 11)} ${r1(cx + hipW - 2)},${t.hipY}`,
      `C ${r1(cx + hipW)},${r1(t.hipY - 9)} ${r1(cx + waistW - 4)},${r1(t.waistY + 6)} ${r1(cx + waistW)},${t.waistY}`,
      `C ${r1(cx + waistW + 3)},${r1(t.waistY - 9)} ${r1(cx + shW)},${r1(t.shoulderY + 7)} ${r1(cx + shW)},${t.shoulderY}`,
      `C ${r1(cx + shW - 5)},${r1(t.shoulderY - 8)} ${r1(cx + 8)},${r1(neckY + 10)} ${r1(cx + 7)},${neckY}`,
      'Z',
    ].join(' '),
  })
  /* 尾（剪影层：俯视看是一条向后的锥形，与臀部合成一条外轮廓） */
  out.push({
    el: 'path',
    cls: 'fig-body',
    layer: 'sil',
    d: `M ${r1(cx - 4.5)},${r1(t.hipY + 6)} L ${r1(cx + 4.5)},${r1(t.hipY + 6)}`
      + ` C ${r1(cx + 4)},${r1(t.hipY + 14)} ${r1(cx + 2)},${r1(t.hipY + 19)} ${cx},${r1(t.hipY + 22)}`
      + ` C ${r1(cx - 2)},${r1(t.hipY + 19)} ${r1(cx - 4)},${r1(t.hipY + 14)} ${r1(cx - 4.5)},${r1(t.hipY + 6)} Z`,
  })
  /* 头（剪影层，与躯干合成一条外轮廓） */
  out.push({ el: 'circle', cls: 'fig-body', layer: 'sil', cx, cy: t.headY, r: t.headR })
  /* 双耳：耳尖 y = headY − headR − 8，故 headY 必须 ≥ headR + 8 才不被画布裁掉 */
  if (typeId === 'cat') {
    out.push({ el: 'path', cls: 'fig-body', layer: 'sil', d: `M ${cx - 9},${r1(t.headY - t.headR + 5)} L ${cx - 13},${r1(t.headY - t.headR - 8)} L ${cx - 1},${r1(t.headY - t.headR + 2)} Z` })
    out.push({ el: 'path', cls: 'fig-body', layer: 'sil', d: `M ${cx + 1},${r1(t.headY - t.headR + 2)} L ${cx + 13},${r1(t.headY - t.headR - 8)} L ${cx + 9},${r1(t.headY - t.headR + 5)} Z` })
  } else {
    out.push({
      el: 'path',
      cls: 'fig-body',
      layer: 'sil',
      d: `M ${r1(cx - 10)},${r1(t.headY - 5)} Q ${r1(cx - 17)},${t.headY} ${r1(cx - 12)},${r1(t.headY + 7)}`
        + ` Q ${r1(cx - 6)},${r1(t.headY + 4)} ${r1(cx - 10)},${r1(t.headY - 5)} Z`,
    })
    out.push({
      el: 'path',
      cls: 'fig-body',
      layer: 'sil',
      d: `M ${r1(cx + 10)},${r1(t.headY - 5)} Q ${r1(cx + 17)},${t.headY} ${r1(cx + 12)},${r1(t.headY + 7)}`
        + ` Q ${r1(cx + 6)},${r1(t.headY + 4)} ${r1(cx + 10)},${r1(t.headY - 5)} Z`,
    })
  }
  /* 腰线标注：两侧腰点连线，宽度差就是「收没收腰」（前景层，必须压在最上面） */
  out.push({ el: 'path', cls: 'fig-guide', layer: 'front', d: `M ${r1(cx - waistW)},${t.waistY} L ${r1(cx + waistW)},${t.waistY}` })

  return {
    shapes: out,
    meta: { waistHalf: waistW, shoulderHalf: shW, hipHalf: hipW },
  }
}

/** 取某体型 × 某档的几何数据（React 与导出共用）。
 *  `meta` 是给测试与调用方读的**语义值**（上提量、腰宽…），
 *  不必再从路径字符串里解析坐标 —— 那样一改造型断言就跟着碎。 */
export function figureShapes(typeId, levelKey) {
  const sb = SIDE_BASE[typeId] || SIDE_BASE.smallDog
  const tb = TOP_BASE[typeId] || TOP_BASE.smallDog
  const lv = LEVEL_ADJ[levelKey] || LEVEL_ADJ.ideal
  const side = sideShapes(sb, lv)
  const top = topShapes(tb, lv, typeId)
  return {
    side: side.shapes,
    top: top.shapes,
    meta: { ...side.meta, ...top.meta, canvas: CANVAS },
  }
}

/**
 * 由宠物档案推断该用哪套参考图。
 * 犬只分两套（大型 / 小型）：用户要的是「有可比对象」，中型犬按 18 kg 归到更接近的一侧；
 * 界面允许手动切换，所以这里只是**默认值**，不追求精确分类。
 */
export function figureTypeFor(pet = {}) {
  if (pet.species === 'cat') return 'cat'
  if (pet.size === 'large') return 'largeDog'
  if (pet.size === 'small') return 'smallDog'
  const w = Number(pet.weightKg)
  if (Number.isFinite(w) && w > 0) return w >= 18 ? 'largeDog' : 'smallDog'
  return 'smallDog'
}

const escAttr = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const shapeStr = (sh) => (sh.el === 'circle'
  ? `<circle class="${sh.cls}" cx="${r1(sh.cx)}" cy="${r1(sh.cy)}" r="${sh.r}"/>`
  : `<path class="${sh.cls}" d="${sh.d}"/>`)

/** 单个视角的图元 → SVG 字符串（「统一剪影」四遍：back → sil 描边 → sil 填充 → front）
 *  ⚠ 顺序不能动：`fig-out` 把整组躯干部件粗描边画一遍，`fig-fill` 紧接着用**同样的路径**
 *    纯填充盖一次，内部线条被吃掉，整只动物只剩一条外轮廓。 */
function viewStr(shapes) {
  const L = figureLayers(shapes)
  return `<g class="fig-back">${L.back.map(shapeStr).join('')}</g>`
    + `<g class="fig-sil fig-out">${L.sil.map(shapeStr).join('')}</g>`
    + `<g class="fig-sil fig-fill">${L.sil.map(shapeStr).join('')}</g>`
    + `<g class="fig-front">${L.front.map(shapeStr).join('')}</g>`
}

/** 导出用：一张「侧视 + 俯视」并排的自包含 SVG 字符串 */
export function figureSvg(typeId, levelKey, opts = {}) {
  const { side, top } = figureShapes(typeId, levelKey)
  const t = BCS_FIGURE_TYPES.find((x) => x.id === typeId) || BCS_FIGURE_TYPES[0]
  const l = BCS_FIGURE_LEVELS.find((x) => x.key === levelKey) || BCS_FIGURE_LEVELS[1]
  const aria = opts.aria || `${t.label} ${l.label}档 体况参考示意图（左：侧视，右：俯视）`
  return `<svg class="bcs-fig" viewBox="0 0 ${FIGURE_VIEW.w} ${FIGURE_VIEW.h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escAttr(aria)}">`
    + `<g class="fig-side">${viewStr(side)}</g>`
    + `<g class="fig-top" transform="translate(${FIGURE_VIEW.topDx},0)">${viewStr(top)}</g>`
    + '</svg>'
}
/* ⚠ 「怎么看」的文案不放在这里 —— 它是体况判据，归属 `feedingGuide.js` 的
   `BCS_VIEW_HINT`（与 `BCS_SCALE` 同一处），避免界面与导出各写一套而分叉。
   本文件只负责几何。 */
