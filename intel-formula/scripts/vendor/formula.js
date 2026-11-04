// 配方核对：把配方里的实际用量与参照值放在一起看，**只做方向核对，不下判定结论**。
//
// #3（2026-10-03）。审查报告原方案是「剂量-配方换算」，落地前复核发现前提不成立：
// 库里 10 条参照值里**没有一条是「原料建议添加量」**（如「0.2%~0.5%」），
// 它们分属**四种量纲**：
//
//   ① `urine`  —— **尿液实测 pH**。与「配方里加了多少」完全不同量纲：
//      它是吃一段时间之后去验尿的数，不是配料表里的浓度。
//   ② `aafco`  —— **占干物质（DM）**的最低量/上限。量纲与产品总重不同：
//      同一份配方，DM 口径与全价口径差一个水分因子。
//   ③ `fiber`  —— **占日粮比例**的 TdF。是「日粮里膳食纤维总量」，
//      不是「某一种纤维原料加了多少」（这两件事差一个纯物质占比）。
//   ④ `label`  —— **占产品总重**的法定声称门槛。量纲是产品总重，
//      但语义是**标签合规**（能不能这么写），不是营养有效量。
//
// 硬搬报告的「剂量换算」会造出一个**量纲混用的伪工具**：
// 拿 11% TdF 去比「车前子壳添加量」，拿 0.5% DM 的牛磺酸去比产品总重含量，
// 算出来的数全是错的，而且**看起来专业**。
//
// 所以这里做的是三件事：
//   1. **剂量单位归一**（mg/kg / ppm / g/kg / % 互算，IUPAC 质量分数 vs 百万分比）——
//      这部分与量纲无关，是纯算术，做对了一个数量级不会错。
//   2. **口径（量纲）显式化 + 子指标指名** —— 任何比较都必须先声明
//      「这两边是不是同一个口径」「比的是哪一条子指标」，不是就**拒绝比较并说清为什么**，
//      而不是给一个错答案。
//   3. **区间定位**（不是「达标/不达标」）—— 输出「你的 0.3% 落在参照区间的哪一段」。
//      措辞纪律见 `REFERENCE_DISCLAIMER`：本模块是核对方向的参照值，不是判定依据。
//
// ⚠ 唯一给「结论」的地方是 `label` 组的**法定声称门槛** —— 那是法规写死的数字，
//   不是营养有效量，所以可以说「低于门槛则该声称不成立」。但即使那里也只陈述
//   「数值与门槛的关系」，**不代替使用者下「产品合规」的结论**（那是法务与检测的事）。
//
// ⚠⚠ **落地时又抓到第四种混用，本模块第一版自己犯了**（写在这里防止重犯）：
//   参照值里**一条 ref 底下有多个子指标**（`aafco-cat-essential` 有 8 个 values），
//   而第一版「取前两个数字当下限与上限」把它们压成了一个区间。实测后果：
//     · 取到「牛磺酸**成年维持** 0.10%」与「牛磺酸**生长繁殖** 0.20%」
//       ⇒ **把两个生命阶段的下限当成一个区间**，于是 0.30% 被判「高于参照上限」。
//     · `hairball-fiber-dose` 取到「**对照组** 6%」与「试验组1 11%」⇒ 把对照组当上限。
//     · `label-lowfat-lowenergy` 从「水分**<20%** 且 ≤9%」里抓到 `20`
//       ⇒ 那个 20 是**水分门槛**不是剂量，**差 100 倍**；该条后两个 values
//       是 kJ ME/100g，**根本不是质量分数**。
//   修法见 {@link parseSpec}：**认不出形态就返回 `null`，绝不凑一个区间**；
//   子指标多于一个时**必须指名**，见 {@link checkAgainstReference}。
import {
  REFERENCE_VALUES, REFERENCE_GROUP_MAP, REFERENCE_DISCLAIMER, referenceById,
} from './reference-values.js';

export { REFERENCE_DISCLAIMER as FORMULA_DISCLAIMER };

/* ══════════════════════ 1. 单位表（唯一一份） ══════════════════════ */

/**
 * 单位 → 质量分数的换算系数。**只有这一份表**。
 *
 * ⚠⚠ **最易错的一格是 `ppm`**：`1 ppm = 1 mg/kg = 1e-6 质量分数 = 0.0001%`
 *   （**不是 0.001%**）。把 ppm 当「千分之几」就会把 100 ppm 写成 0.1% —— 差 10 倍。
 *   复制这张表到别处 = 抄错一处就静默错一个数量级，所以抽出来共用。
 */
const UNIT_TABLE = [
  // ⚠ `%` / `％` 必须**排除重复写法**（`0.3%%`）。只用 `^(%)` 的话
  //   `%%` 会通过 —— 实测踩过：`0.3%%` 被当成 0.3% 接受，而它显然是笔误。
  //   `(?!%)` / `(?![%％])` 是「后面不许再跟一个百分号」。
  [/^(?:%(?!%)|％(?!％))/, 1e-2],
  [/^(‰)/, 1e-3],
  [/^(?:ppm|ppmw)\b/i, 1e-6],
  [/^mg\s*\/\s*kg\b/i, 1e-6],
  [/^ug\s*\/\s*kg\b/i, 1e-9],
  [/^g\s*\/\s*kg\b/i, 1e-3],
  [/^g\s*\/\s*1000g\b/i, 1e-3],
  [/^kg\s*\/\s*t\b/i, 1e-3],
];

/**
 * @param {string} tail 单位文本（**允许带前导空格**，本函数自己 trim）
 * @returns {[number|null, boolean]} `[系数, 是否认识]`
 */
function unitFactor(tail) {
  const t = String(tail ?? '').trim();
  for (const [re, k] of UNIT_TABLE) if (re.test(t)) return [k, true];
  return [null, false];
}

/* ══════════════════════ 2. 使用者填的那个数 ══════════════════════ */

/**
 * 把一个带单位的剂量文本解析成 `{ massFrac }`（**质量分数**，无量纲，1 = 100%）。
 *
 * ⚠⚠ **三个必须显式处理的陷阱**（错一个就是 10 倍或 100 倍）：
 *
 *   ① **ppm ≠ 千分之几**（见上）。`100 ppm` 是 `0.0001%`，不是 `0.1%`。
 *   ② **`%` 在本项目里有两个口径**：`占产品总重` 与 `占干物质`。
 *      本函数**不判断是哪个**（它拿不到那个上下文），所以返回里带 `basisHint`，
 *      由调用方强制与参照值口径对齐。
 *   ③ **「数字 + 单位」的形态不止一种**，而不同形态语义完全不同：
 *      `0.20% DM` 是**单点**、`1.2% / 1.8% DM` 是**区间**、`26% 以上` 只有**下限**、
 *      `≤9%` 只有**上限**。参照值那一侧一律走 {@link parseSpec}（它保留形态）；
 *      本函数只负责使用者填的数（取第一个，多半只有一个）。
 *
 * @returns {{massFrac:number, unit:string, basisHint:string, raw:string}|null}
 *   解析不了就返回 `null` —— **不猜、不返回 0**。
 *   返回 0 会让「没写」与「真的是 0」在下游长得一样。
 */
export function parseDose(text, { basis = 'productWeight' } = {}) {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (!s) return null;

  // 区间取下限（`0.2%~0.5%` → 0.2%）。**刻意不返回区间**：
  //   「你的值落在参照区间哪一段」需要的是「参照区间」，那在参照值那边取。
  const num = s.match(/(-?\d+(?:\.\d+)?)/);
  if (!num) return null;
  const v = Number(num[1]);
  if (!Number.isFinite(v)) return null;

  // ⚠ **必须先 trim**：`'1 ppm'` 的数字之后是 `" ppm"`（带前导空格），
  //   而所有单位正则都用 `^` 锚定 ⇒ 不 trim 的话**每一个带空格写法都匹配不上**。
  //   实测踩过：`1 ppm` 解析不出来，而 `1%` 可以（它本来就没有空格）。
  const tail = s.slice(num.index + num[0].length);
  const [k, known] = unitFactor(tail);
  if (!known) return null;   // 裸数（`12`）、无单位、无法识别的单位 —— **不猜**
  return {
    massFrac: v * k,
    unit: tail.trim().split(/\s/)[0] || tail.trim(),
    basisHint: basis === 'dryMatter' ? '占干物质' : '占产品总重',
    raw: s,
  };
}

/**
 * 剂量单位互算。返回**同一个量纲**（质量分数）下的数值。
 * 例：`convertDose(500, 'ppm', '%')` → `0.05`
 */
export function convertDose(value, from, to) {
  const a = parseDose(`${value}${unitSuffix(from)}`);
  const b = parseDose(`1${unitSuffix(to)}`);
  if (!a || !b || b.massFrac === 0) return null;
  return a.massFrac / b.massFrac;
}

const UNIT_SUFFIX = {
  '%': '%', '％': '%', '‰': '‰', ppm: 'ppm', ppmw: 'ppmw',
  'mg/kg': 'mg/kg', 'ug/kg': 'ug/kg', 'g/kg': 'g/kg', 'kg/t': 'kg/t',
};
const unitSuffix = (u) => UNIT_SUFFIX[String(u).trim()] ?? u;

/* ══════════════════════ 3. 参照值那一侧的「剂量规格」 ══════════════════════ */

/**
 * 参照值一个子指标的**形态**是四种之一，而它们的语义完全不同：
 *
 *   | kind      | 库里实例          | 语义                     | 能说「高于它」吗 |
 *   |-----------|-------------------|--------------------------|------------------|
 *   | `point`   | `0.20% DM`        | 一个参考水平             | **不能**（不是上限）|
 *   | `range`   | `1.2% / 1.8% DM`  | 真区间（钙最低/最高）    | 能               |
 *   | `atLeast` | `26% 以上`        | 只有下限（声称门槛）     | **不能**         |
 *   | `atMost`  | `≤9%`             | 只有上限（低脂声称上限） | 能               |
 *
 * ⚠⚠ **这四种不能压成一个 `[min, max]`** —— 压了就会造出**不存在的上限**。
 *   踩过的坑见文件头（牛磺酸两个生命阶段、对照组当上限、水分 20% 差 100 倍）。
 *   本函数**认不出就返回 `null`**，绝不「取第一个数字凑一个区间」。
 *
 * @returns {{kind:string, min:number|null, max:number|null, unit:string}|null}
 */
export function parseSpec(text) {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (!s) return null;
  // ⚠⚠ **`U`（语法上「像单位」）必须比 `UNIT_TABLE`（真正认得的量纲）宽**，
  //   否则 `if (!known) return null` 那道量纲防线**不可达** ⇒ 整段是死代码。
  //   实测踩过：变异把量纲守卫删掉，守卫**一条都没红** ——
  //   因为能匹配 `U` 的单位必然都在 `UNIT_TABLE` 里，那道检查从来没被触发过。
  //   **恒绿的守卫比没有守卫更坏**：它让人以为量纲有校验。
  //
  //   所以这里**故意**列了几个语法合法但量纲不认的单位（`kJ/100g` 是能量密度、
  //   `mg/g` 与 `mg/kg` 差 1000 倍），让它们成为那道防线的可达路径。
  //
  // ⚠ **`U` 与 `UNIT_TABLE` 必须逐项对齐**（守卫里有断言）。
  //   实测踩过：`g/1000g` 在 `UNIT_TABLE` 里却不在 `U` 里 ⇒
  //   `parseDose('1 g/1000g')` 认得、`parseSpec('1.2 g/1000g')` 不认 ——
  //   同一份单位表在两个函数里行为不一致，而两边都「看起来对」。
  const U = '(%|％|‰|ppmw?|mg\\s*/\\s*kg|ug\\s*/\\s*kg|g\\s*/\\s*kg|g\\s*/\\s*1000g|kg\\s*/\\s*t'
    + '|mg\\s*/\\s*g|kJ(?:\\s*/\\s*100\\s*g)?|kJ\\s*ME\\s*/\\s*100g)';
  const N = '(\\d+(?:\\.\\d+)?)';
  // 尾部允许一个**不改变量纲**的修饰词（`DM` / `TdF`）。
  const T = '(?:\\s*(?:DM|dry\\s*matter|TdF|NFE|as\\s*fed))?';
  // ⚠ 顺序有讲究：区间必须排在单点前面，否则 `1.2% / 1.8% DM` 会先被单点否掉。
  const FORMS = [
    { kind: 'range', re: new RegExp(`^${N}\\s*${U}\\s*(?:\\/|~|-|–|—|至|～)\\s*${N}\\s*${U}${T}$`, 'i') },
    { kind: 'atLeast', re: new RegExp(`^(?:≥|>=|不低于|至少)\\s*${N}\\s*${U}${T}$`, 'i') },
    { kind: 'atLeast', re: new RegExp(`^${N}\\s*${U}\\s*(?:以上|及以上)$`, 'i') },
    { kind: 'atMost', re: new RegExp(`^(?:≤|<=|不高于|最多)\\s*${N}\\s*${U}${T}$`, 'i') },
    { kind: 'atMost', re: new RegExp(`^${N}\\s*${U}\\s*(?:以下|及以下)$`, 'i') },
    { kind: 'point', re: new RegExp(`^${N}\\s*${U}${T}$`, 'i') },
  ];
  for (const f of FORMS) {
    const m = f.re.exec(s);
    if (!m) continue;
    const [k, known] = unitFactor(m[2]);
    if (!known) return null;
    if (f.kind === 'range') {
      const a = Number(m[1]);
      const b = Number(m[3]);
      // ⚠ 区间两端单位必须一致 —— `1.2% / 1.8 g/kg` 这类写法不认，
      //   否则会把两个不同量纲拼成一个「不存在的区间」。
      const [k2, known2] = unitFactor(m[4]);
      if (!Number.isFinite(a) || !Number.isFinite(b) || !known2 || k2 !== k) return null;
      return { kind: 'range', min: Math.min(a, b) * k, max: Math.max(a, b) * k, unit: m[2] };
    }
    const a = Number(m[1]);
    if (!Number.isFinite(a)) return null;
    if (f.kind === 'point') return { kind: 'point', min: a * k, max: a * k, unit: m[2] };
    if (f.kind === 'atLeast') return { kind: 'atLeast', min: a * k, max: null, unit: m[2] };
    return { kind: 'atMost', min: null, max: a * k, unit: m[2] };
  }
  return null;
}

/**
 * 一条参照值底下**带标签的可用规格**。
 *
 * ⚠ 只收 `parseSpec` 认得出的 —— 收不着的**不进清单**，由调用方显式说明
 *   「这一条有几个子指标不可用、为什么」，而不是让它们混进来被当成可比项。
 *
 * @returns {{label:string, text:string, spec:object}[]}
 */
export function specsOf(ref) {
  const out = [];
  for (const v of (ref?.values || [])) {
    const spec = parseSpec(v.value);
    if (spec) out.push({ label: v.label || v.name || v.value, text: String(v.value), spec });
  }
  return out;
}

/* ══════════════════════ 4. 口径（量纲） ══════════════════════ */

/**
 * 每个参照值组**各自的度量口径**。
 *
 * ⚠ 这张表是本模块存在的理由 —— 审查报告假设「所有参照值都是建议添加量」，
 *   实测不是。**把不同口径的数放在一起比，是本项目最容易犯且最难发现的错误**：
 *   它算出来的数有模有样，误差可能 10 倍。
 */
export const BASIS_BY_GROUP = {
  urine: {
    id: 'urine',
    label: '尿液实测 pH',
    measurable: false,
    why: '这一组要验的是**吃一段时间之后的尿液**，不是配料表里的浓度。'
      + '拿它去比「配方里加了什么」是量纲错误 —— 而且方向会反：'
      + '酸化剂加得越多，尿液越酸，而「越酸」对草酸钙是**不好**的方向。',
  },
  aafco: {
    id: 'aafco',
    label: '占干物质（DM）',
    measurable: true,
    why: 'AAFCO 的最低量/上限是**干物质基础**，并假定能量密度 4000 kcal ME/kg。'
      + '与「占产品总重」差一个水分因子 —— 湿粮与干粮的同一个数字，'
      + '换算到产品总重会差 10% 以上（水分 10% 时差约 11%）。',
  },
  fiber: {
    id: 'fiber',
    label: '占日粮比例（TdF，总膳食纤维）',
    measurable: true,
    // ⚠ 这一组的量纲与「占产品总重」**可换算但不相等** —— 差一个水分因子。
    //   所以它归到「可测」而不是「不可测」：数字本身有意义，
    //   但**必须同时给出水分**，否则干粮与湿粮的同一个 TdF% 差 10% 以上。
    convertible: true,
    why: '这一组是**日粮里膳食纤维的总量**，不是某一种纤维原料的添加量。'
      + '试验里的 11% TdF 与「配料表加一点车前子壳」不是一个量级 ——'
      + '后者要乘上该原料的纯物质占比才知道折合多少 TdF。',
    caveat: '这一组的分母是**日粮**。要与「占产品总重」比较，必须先换算水分：'
      + '约 DM% = 产品总重% × (1 + 水分%)。湿粮（水分 80%）与干粮（水分 10%）'
      + '的同一个 TdF 目标，换算到产品总重会差 3 倍以上。',
  },
  label: {
    id: 'label',
    label: '占产品总重（法定声称门槛）',
    measurable: true,
    why: '这一组是**法规写死的标签门槛**，量纲是产品总重。'
      + '它管的是「这句话能不能这么写」，不是「这个成分有没有营养价值」——'
      + '两件事的方向可能相反（加到 4% 才够写「含××」，但营养上早已过量）。',
  },
};

/**
 * 口径是否可比。
 * @returns {{ok:boolean, reason:string, caveat:string, needsMoisture:boolean}}
 *   `ok:false` 时**必须**给出可读的 why —— 只给一个 `false` 会让使用者以为
 *   「数据不可用」，而真因是「量纲不对」。
 */
export function compareBasis(groupId, myBasis) {
  const b = BASIS_BY_GROUP[groupId];
  if (!b) return { ok: false, reason: `未知的参照组：${groupId}`, caveat: '', needsMoisture: false };
  if (!b.measurable) {
    return {
      ok: false,
      reason: `${b.label}不是配方里能算出来的量 —— ${b.why}`,
      caveat: '', needsMoisture: false,
    };
  }
  const mine = myBasis === 'dryMatter' ? '占干物质'
    : myBasis === 'productWeight' ? '占产品总重' : String(myBasis);
  // `convertible` 组（fiber）：量纲**可以对上**，但要换算 —— 放行并带上警示，
  //   而不是判它「口径不同」。判据过严会把一条**本来能做**的核对挡在门外，
  //   而使用者看到的理由是「口径不同」—— 他会以为要改口径，其实要填水分。
  if (b.convertible) {
    return { ok: true, reason: '', caveat: b.caveat || '', needsMoisture: true };
  }
  const same = b.label.includes(mine);
  if (!same) {
    return {
      ok: false,
      reason: `口径不同：参照值是「${b.label}」，你给的是「${mine}」。${b.why}`,
      caveat: '', needsMoisture: false,
    };
  }
  return { ok: true, reason: '', caveat: '', needsMoisture: false };
}

/* ══════════════════════ 5. 区间定位（不给达标结论） ══════════════════════ */

/**
 * 定位档位。**措辞是纪律**：不写「达标/不达标」—— 那是判定结论，
 * 与 `REFERENCE_DISCLAIMER`（参照值不是判定依据）冲突。
 *
 * ⚠⚠ **档位必须按「参照值形态」分开措辞，不能一套词走天下**。
 *   同一句「低于参照下限」对三种形态是三种意思：
 *
 *   | 形态 | 库里的实例 | 那个数到底是什么 | 措辞 |
 *   |---|---|---|---|
 *   | `atLeast` | `26% 以上`（「含××」声称门槛） | **门槛** | 说「下限」成立 |
 *   | `range`   | `1.2% / 1.8% DM`（钙最低/最高） | **真区间** | 说「下限/上限」成立 |
 *   | `atMost`  | `≤9%`（低脂肪声称上限） | **只有上限** | 不能说「下限」 |
 *   | `point`   | `11% TdF`（**试验组 1**）、`6.0% TdF`（**对照组**） | **一个试验水平** | **说「下限」是错的** |
 *
 *   `point` 那一格是实测踩出来的：`hairball-fiber-dose` 的第一个子指标是
 *   「对照（低纤维）6.0% TdF」—— 对照组**不是门槛**。第一版把 `point` 当
 *   下限用，于是「你的 6.5% TdF 高于对照组」被说成「不低于参照下限」，
 *   而真相比那弱得多（对照组是**试验的起点**，不是「够不够」）。
 *   所以 `point` 一律用「参考水平」措辞，只陈述关系。
 *
 * ⚠ `id` 是**稳定契约**（判定逻辑与守卫按 id 匹配），`label` 可改措辞。
 *   加档位请同步更新 `scripts/batch3-hardening-test.mjs` 的「形态 × 分支全覆盖」断言。
 */
export const LOCATE_BANDS = [
  {
    id: 'below',
    label: '低于参照下限',
    advice: '落在这一段说明与参照区间的差距是**方向性**的，先确认口径与单位有没有搞错。',
  },
  {
    id: 'belowLevel',
    label: '低于该参考水平',
    advice: '该参照值是**一个参考水平**（例如试验里的某一档），不是门槛。'
      + '低于它只说明「与那一档的差距」，**不构成不足或超标**。',
  },
  {
    id: 'at',
    label: '与该参考水平相同',
    advice: '与该参考水平相同。若那条是「最低量」类门槛，相同意味着刚好在门槛上。',
  },
  {
    id: 'atLeastOk',
    label: '不低于参照下限',
    advice: '该参照值只给了下限（属于「最低量」或声称门槛类），**不低于它本身不说明充分** —— '
      + '上限要看另一些参照值。',
  },
  {
    id: 'lower',
    label: '区间下段',
    advice: '在参照区间之内，但偏下沿。是否需要调整取决于目标，不是「不够」的意思。',
  },
  {
    id: 'upper',
    label: '区间上段',
    advice: '在参照区间之内，偏上沿。注意与上限类参照值的关系。',
  },
  {
    id: 'above',
    label: '高于参照上限',
    advice: '超出参照区间。**这一档值得停下来看**：可能是添加过量，也可能是口径/水分算错了。',
  },
  {
    id: 'aboveLevel',
    label: '高于该参考水平',
    advice: '该参照值只给了一个参考水平（或下限），**高于它本身不构成超标** —— '
      + '上限要看另一些参照值。若怀疑确实过量，请核对同组其他子指标与水分口径。',
  },
  {
    id: 'atMostOk',
    label: '未超过参照上限',
    advice: '该参照值只给了上限（属于「不得超过」类）。**它不设下限** —— '
      + '「远低于上限」同样可能有问题（例如声称低脂肪却含 9% 脂肪）。',
  },
  {
    id: 'unparsed',
    label: '参照值不是可比数值，未做定位',
    advice: '该条参照值是区间、方向性描述或需实测的指标，不能定位到某一段。',
  },
];

/** 按 id 取档位。取不到就是 `unparsed` —— 拼错的 id 不许悄悄变成别的档。 */
export const bandMeta = (id) => LOCATE_BANDS.find((b) => b.id === id) || bandMeta('unparsed');

/**
 * 把「你的实际值」放进**一条具体的参照规格**，给出定位。
 *
 * ⚠⚠ **分支按 `spec.kind` 走，不按「有没有 max」走**。理由见 {@link LOCATE_BANDS}：
 *   `point`（试验水平）与 `atLeast`（门槛）都只有下限，但前者**不是下限** ——
 *   混着说会把「与对照组高一点」讲成「不低于参照下限」。
 *
 * @param {number} mine 我的值（**同一个量纲**，已换算成质量分数）
 * @param {object} spec {@link parseSpec} 的结果（`kind` + `min`/`max`）
 * @param {object} [ref] 参照值本体，只用于回显来源信息
 * @returns {{band:string, label:string, advice:string, hasUpper:boolean, hasLower:boolean}}
 */
export function locateInRange(mine, spec, ref) {
  const base = {
    refId: ref?.id || '',
    refSource: ref?.source?.name || '',
    refTier: ref?.source?.tier || '',
    refUpdatedAt: ref?.updatedAt || '',
  };
  const out = (band, hasUpper, hasLower) => {
    const m = bandMeta(band);
    return { ...base, band, label: m.label, advice: m.advice, hasUpper, hasLower };
  };
  if (!spec || !Number.isFinite(mine)) return out('unparsed', false, false);

  const { min, max, kind } = spec;
  const hasMin = Number.isFinite(min);
  const hasMax = Number.isFinite(max);

  // ① `atMost`：只有上限。没有下限可比，所以「远低于上限」不报任何档 ——
  //   报「区间下段」会凭空造出一个下限。
  if (kind === 'atMost') {
    if (!hasMax) return out('unparsed', false, false);
    return mine > max ? out('above', true, false) : out('atMostOk', true, false);
  }

  // ② `point`：一个参考水平/单点，**不是门槛**。只陈述关系。
  if (kind === 'point') {
    if (!hasMin) return out('unparsed', false, false);
    if (mine < min) return out('belowLevel', false, true);
    if (mine === min) return out('at', false, true);
    return out('aboveLevel', false, true);
  }

  // ③ `atLeast`：真下限（门槛 / 最低量）。说「下限」成立。
  if (kind === 'atLeast') {
    if (!hasMin) return out('unparsed', false, true);
    return mine < min ? out('below', false, true) : out('atLeastOk', false, true);
  }

  // ④ `range`：真区间，两头都有。
  if (kind !== 'range' || !hasMin || !hasMax) return out('unparsed', false, false);
  if (mine < min) return out('below', true, true);
  if (mine < min + (max - min) / 2) return out('lower', true, true);
  if (mine <= max) return out('upper', true, true);
  return out('above', true, true);
}

/* ══════════════════════ 6. 主入口 ══════════════════════ */

/**
 * 拿配方里某一项的**文本**（如 `"0.3%"`）去与**某条参照值的一个子指标**比。
 *
 * ⚠⚠ **`metric` 不是可选的礼貌参数，而是正确性前提**：
 *   一条 ref 底下常有多个子指标（`aafco-cat-essential` 有 8 个），把它们的数字
 *   压成一个「区间」会造出**不存在的上下限**（见文件头）。所以当一条 ref 有
 *   **多于一个**可用子指标而调用方没指名时，这里**拒绝比较**并把候选列出来 ——
 *   这是本模块唯一允许的「不知道」，其余情况一律给出可读的 why。
 *
 * @param {object} p
 * @param {string} p.mine 我的用量（带单位，如 `'0.3%'` / `'3000 ppm'`）
 * @param {string} [p.myBasis] 我的口径：`'productWeight'`（默认）| `'dryMatter'`
 * @param {string} p.refId 参照值 id（用 `referenceById` 查，**不新造数据源**）
 * @param {string|number} [p.metric] 子指标：**标签原文**或**下标**。
 *   省略时，只有该 ref **恰好一个**可用子指标才会自动选中。
 */
export function checkAgainstReference({ mine, myBasis = 'productWeight', refId, metric } = {}) {
  const fail = (reason, extra) => ({
    ok: false, reason, band: 'unparsed', label: '未做定位', advice: '', ...extra,
  });
  const ref = referenceById(refId);
  if (!ref) return fail(`找不到参照值 ${refId}`);

  // ① 口径先判 —— 量纲不对时，后面算得再准也没意义。
  const basis = compareBasis(ref.group, myBasis);
  const refEcho = { refId: ref.id, refSource: ref.source?.name || '' };
  if (!basis.ok) {
    return fail(basis.reason, {
      ...refEcho,
      label: '未做定位（口径不可比）',
      advice: '把口径对齐后再比。**不要把两个不同口径的数放在一起算** —— 结果有模有样但可能差 10 倍。',
    });
  }

  // ② 子指标指名。
  const specs = specsOf(ref);
  if (!specs.length) {
    return fail(
      `参照值 ${ref.id} 底下没有可比的数值规格（${(ref.values || []).map((v) => v.value).join(' / ').slice(0, 90)}）`,
      { ...refEcho, label: bandMeta('unparsed').label, advice: bandMeta('unparsed').advice },
    );
  }
  let picked = null;
  if (metric === undefined || metric === null || metric === '') {
    if (specs.length > 1) {
      return fail(`参照值 ${ref.id} 有 ${specs.length} 个子指标，必须指明比哪一个`, {
        ...refEcho,
        candidates: specs.map((s) => s.label),
        label: '未做定位（未指明子指标）',
        advice: '把它们压成一个区间会造出**不存在的上下限** ——'
          + '例如「牛磺酸成年 0.10%」与「牛磺酸生长 0.20%」是两个下限，不是区间。',
      });
    }
    picked = specs[0];
  } else {
    picked = typeof metric === 'number'
      ? specs[metric]
      : specs.find((s) => s.label === metric || s.text === String(metric));
    if (!picked) {
      return fail(`参照值 ${ref.id} 里没有名为「${metric}」的子指标`, {
        ...refEcho,
        candidates: specs.map((s) => s.label),
        label: '未做定位（子指标不存在）',
      });
    }
  }

  // ③ 使用者那个数。
  const mineParsed = parseDose(mine, { basis: myBasis });
  if (!mineParsed) {
    return fail(
      `解析不了用量 ${JSON.stringify(mine)}（缺单位？裸数无法判断是 % 还是 ppm）`,
      { ...refEcho, label: '未做定位', advice: '请带上单位，例如 `0.3%` 或 `3000 ppm`。' },
    );
  }

  // ④ 定位。
  const loc = locateInRange(mineParsed.massFrac, picked.spec, ref);
  return {
    ok: true,
    reason: '',
    // ⚠ 可换算的组（fiber）要**把 caveat 一起带出去** ——
    //   放行比较却不给换算提醒，等于把「差一个水分因子」这个坑留在使用者脚下。
    caveat: basis.caveat || '',
    needsMoisture: Boolean(basis.needsMoisture),
    mine: { text: String(mine), massFrac: mineParsed.massFrac, unit: mineParsed.unit },
    ref: { id: ref.id, title: ref.title, basis: ref.basis, group: ref.group },
    metric: { label: picked.label, text: picked.text, spec: picked.spec },
    ...loc,
  };
}

/**
 * 列出**可与配方核对**的子指标 —— 也就是量纲对得上、且形态认得出的那些。
 *
 * ⚠ **按子指标展开，不按 ref 展开**。按 ref 展开就必须「把一条 ref 压成一个区间」，
 *   而那正是本模块第一版的错。
 *
 * 口径不可比的整组也会进来（进 `skipped`）并带 why —— **不许悄悄消失**：
 *   使用者需要知道「库里其实有这一组参照值，只是量纲不同」，而不是以为没有。
 *
 * @returns {{ok:object[], skipped:object[], groups:object}}
 */
export function comparableReferences(myBasis = 'productWeight') {
  const ok = [];
  const skipped = [];
  for (const r of REFERENCE_VALUES) {
    const c = compareBasis(r.group, myBasis);
    if (!c.ok) {
      skipped.push({ refId: r.id, title: r.title, group: r.group, why: c.reason });
      continue;
    }
    const specs = specsOf(r);
    if (!specs.length) {
      skipped.push({
        refId: r.id, title: r.title, group: r.group,
        why: `这一条的取值都不是可比的剂量数值：${(r.values || []).map((v) => v.value).join(' / ').slice(0, 90)}`,
      });
      continue;
    }
    for (const s of specs) {
      ok.push({
        refId: r.id, title: r.title, group: r.group,
        metric: s.label, metricText: s.text, spec: s.spec,
        caveat: c.caveat || '', needsMoisture: Boolean(c.needsMoisture),
      });
    }
  }
  return { ok, skipped, groups: REFERENCE_GROUP_MAP };
}

/* ══════════════════════ 7. 批量核对（整张配方表一起核） ══════════════════════ */

/**
 * 行内参照值选择的**合并键分隔符**：`refId` + 本分隔符 + 子指标标签。
 *
 * 为什么是合并键而不是两个字段：批量表每一行的参照值下拉，option value 就是
 * `comparableReferences()` 吐出的 key（`${refId}|||${metric}`）—— 界面直接存它，
 * 状态里只有一个 `metric` 字段。而本文件的文档契约是 `refId` 与 `metric`
 * 分列两行。**两边曾各写各的**：2026-10-15 实测，批量模式的按钮挂在 change 上
 * 整个不可达，这个行形状不一致因此从未被执行到；按钮一修好，它立刻表现为
 * 「选了下标却报未选参照值」。修在边界上：`refId` 缺失而 `metric` 含本分隔符时
 * 由 {@link checkFormulaTable} 拆开。
 *
 * ⚠ app.js 的下拉 value 也用它 —— 分隔符只有这一份定义，UI 侧 import 本常量，
 * 不许再出现字面量 `'|||'`（两份定义迟早对不上，而对不上的表现是静默的：
 * 拆不开 ⇒ 全部行报「未选参照值」）。
 */
export const METRIC_KEY_SEP = '|||';

/**
 * 把**一整张配方表**逐行核一遍。
 *
 * ## 为什么要有这个函数（不是把单条核对做快一点）
 *
 * 真实的配方工作是：手上有一张 20~40 行的配料表，每行一个原料，
 * 要拿每一行去对一遍参照值。原来的界面一次只能填一行 ——
 * 于是每核一行就要「重开下拉 → 重选口径 → 重选子指标 → 读结果 → 清空再来」。
 * **漏行不会有任何提示**（漏掉的行根本没进过界面），
 * 而「漏掉一行」恰好是这个工具最需要防的失效模式。
 *
 * ## 三条设计约束（每条都对应一个具体的坑）
 *
 *   ① **逐行独立，一行坏不影响别的行。** 不做「先全部校验通过才输出」——
 *      那会让一行填错导致整表空白，而使用者无法知道是哪一行的问题。
 *   ② **`status` 必须区分「未填」与「填了但核不了」。**
 *      两者在下游长得一模一样（都没有定位结果），但含义完全相反：
 *      未填 = 还没做；核不了 = 做了但被拒绝（口径不对/子指标不存在/单位认不出）。
 *      **合并这两个状态 = 把「漏项」伪装成「已处理」**，这正是本模块最需要防的失效模式
 *      —— 漏行是静默的，而静默失效比报错更坏。
 *   ③ **不用异常表达业务拒绝。** 每行都返回结构化结果，
 *      这样「8 行里 3 行核不了」是数据而不是崩溃。
 *
 * @param {Array<{name?:string, mine?:string, refId?:string, metric?:string}>} rows
 *   配方表。`myBasis` 取自每个 row（缺省 `productWeight`）。
 *   `refId` 与 `metric` 可分列两字段，也可只给合并键 `metric = refId + METRIC_KEY_SEP + 标签`
 *   （批量表 UI 的行形状，见 {@link METRIC_KEY_SEP}）—— 两种形态等价。
 *   **逐行独立**是刻意的：真实配方表里确实会出现一行是 %DM、另一行是产品总重。
 * @returns {{rows:object[], summary:object}}
 */
export function checkFormulaTable(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const out = list.map((r, i) => {
    const name = String(r?.name ?? '').trim();
    const mine = String(r?.mine ?? '').trim();
    const myBasis = r?.myBasis === 'dryMatter' ? 'dryMatter' : 'productWeight';

    // ① 整行空 ⇒ `empty`。**必须在任何解析之前判**：
    //   一行空行若被当成「解析失败」，统计里就会多出若干条「解析不了」的红，
    //   而它们其实只是还没填 —— 报告会把没做的事说成做砸了。
    if (!mine) {
      return {
        index: i, name, mine: '', status: 'empty', label: '未填写',
        reason: name ? `${name}：还没填用量。` : '这一行还没填原料名与用量。',
        advice: '空着的行**不算已核对** —— 补上带单位的数（例如 `0.3%` / `3000 ppm`）才会进入核对。',
      };
    }

    // ② 填了但没选参照值 ⇒ `unpicked`，与 `empty` 分开（见约束②）。
    // ⚠⚠ 行形状归一（2026-10-15）：UI 存的是合并键 `refId|||子指标标签`
    //   （下拉 option value 的原形，见 METRIC_KEY_SEP），没有独立的 refId 字段。
    //   这里在边界上拆开：显式给了 `refId` 的（文档契约原形）原样走；
    //   只给合并键的拆成 refId + 标签。两边从未对齐却能一起出货，是因为
    //   批量模式当时整个不可达 —— **不可达的代码不会被任何人执行到，包括写它的人**。
    let refId = String(r?.refId ?? '').trim();
    let metricKey = r?.metric;
    if (!refId && typeof metricKey === 'string' && metricKey.includes(METRIC_KEY_SEP)) {
      const at = metricKey.indexOf(METRIC_KEY_SEP);
      refId = metricKey.slice(0, at).trim();
      metricKey = metricKey.slice(at + METRIC_KEY_SEP.length);
    }
    if (!refId) {
      return {
        index: i, name, mine, status: 'unpicked', label: '未选参照值',
        reason: `${name || `第 ${i + 1} 行`}：填了用量但没选要比哪一条参照值。`,
        advice: '每行都要指名一条参照值 —— 拿「有值可取」的那条去比，会把不同生命阶段'
          + '或不同营养素的下限当成一个区间。',
      };
    }

    // ③ 真跑一次核对。它的失败形态（口径不可比 / 子指标不存在 / 单位认不出）
    //   已经各自带 reason 与 advice，这里**原样透出，不改写、不吞掉**。
    const res = checkAgainstReference({ mine, myBasis, refId, metric: metricKey });
    if (!res.ok) {
      return {
        index: i, name, mine, status: 'refused', label: res.label || '未做定位',
        reason: res.reason, advice: res.advice || '',
        refId, candidates: res.candidates || null,
      };
    }
    return {
      index: i, name, mine, status: 'ok', label: res.label, band: res.band,
      reason: '', advice: res.advice,
      refId, refTitle: res.ref?.title || '', refSource: res.refSource || '',
      refUpdatedAt: res.refUpdatedAt || '',
      metricLabel: res.metric?.label || '', metricText: res.metric?.text || '',
      hasUpper: Boolean(res.hasUpper),
      massFrac: res.mine?.massFrac ?? null,
      caveat: res.caveat || '', needsMoisture: Boolean(res.needsMoisture),
    };
  });

  // 统计**按状态分项计数**，不给一个「通过 N」的总分 ——
  //   一个把 3 行拒绝算成「27 行里 27 行通过」的总分，正是本模块要防的那种假绿。
  const summary = {
    total: out.length,
    ok: out.filter((x) => x.status === 'ok').length,
    empty: out.filter((x) => x.status === 'empty').length,
    unpicked: out.filter((x) => x.status === 'unpicked').length,
    refused: out.filter((x) => x.status === 'refused').length,
  };
  // ⚠ `pending = empty + unpicked` 才是「还没核对完」的数 ——
  //   把 refused 算进「已处理」会掩盖真的问题（那行确实没得到答案），
  //   把它算进「待办」又会让人去「修」一个其实已经给出拒绝理由的行。
  summary.pending = summary.empty + summary.unpicked;
  summary.done = summary.ok + summary.refused;
  return { rows: out, summary };
}

/** 本模块的输出**全都要带这句 —— 与 `REFERENCE_DISCLAIMER` 同源，不另立口径。 */
export const FORMULA_NOTE = '本模块只做方向核对：给出的是「你的值落在参照区间的哪一段」，'
  + '**不是达标/不达标的判定结论**。参照值会随标准修订而过期，正式引用前请回到来源原文核对版本。';

/**
 * 批量核对的界面纪律文案。**与 {@link FORMULA_NOTE} 分开** ——
 * 两者回答的问题不同：那句说「结论的性质」，这句说「这张表的状态怎么读」。
 */
export const TABLE_STATUS_HELP = [
  ['ok', '已定位', '这一行给出了它落在参照区间的哪一段。'],
  ['refused', '已处理但未定位', '这一行被拒绝了（口径不可比 / 子指标不存在 / 单位认不出），'
    + '拒绝理由与改法就在这一行里 —— 它**不是**「已核对」。'],
  ['empty', '未填写', '用量还空着。**空行不算已核对。**'],
  ['unpicked', '未选参照值', '填了用量但没指名要比哪一条 —— 没指名就不能比。'],
];

/* ══════════════════════ 8. 分组总览（同一子指标的多行合成一组看） ══════════════════════ */

/**
 * 十档空表。**显式列全十个键**，不用循环生成（照 `maturity.js`
 * `emptyGranular` 的显式字面量风格）—— 漏一个键不会报错，只会让那一档
 * **永远计不上**，而界面上的分布图会安静地少一条。
 */
function emptyBands() {
  return {
    below: 0, belowLevel: 0, at: 0, atLeastOk: 0, lower: 0, upper: 0,
    above: 0, aboveLevel: 0, atMostOk: 0, unparsed: 0,
  };
}

/** 十档 id 集合。计数时**只收表里的 id** —— 直接 `bands[band]++` 会让一个
 *  多出来/拼错的 band 悄悄往 `bands` 里**加键**，「十档」的形态就没了，
 *  而下游按固定十档渲染的界面会漏看它。 */
const BAND_IDS = new Set(LOCATE_BANDS.map((b) => b.id));

/**
 * `bands`（十档）→ `rollup`（五档）的归并表。**模块级常量**：加档位只改这里，
 * 函数体里不出现第二份映射 —— 两份映射迟早对不上，而错的那份看起来一样顺。
 *
 * ⚠⚠ `belowLevel` / `aboveLevel` **不折进** `belowLower` / `aboveUpper`：
 *   这两档来自 `point` 形态的参照值（如 `hairball-fiber-dose` 的
 *   「对照组 6.0% TdF」），那是**试验档位不是门槛**。折进去就会重新制造
 *   本文件文件头记录的真实事故 —— 把「高于对照组」讲成「高于参照上限」。
 *   所以 point 形态的相对关系单独归 `levelRelative`，与门槛型分开。
 */
export const ROLLUP_FROM_BANDS = {
  inRange: ['atLeastOk', 'atMostOk', 'lower', 'upper'],
  belowLower: ['below'],
  aboveUpper: ['above'],
  levelRelative: ['belowLevel', 'at', 'aboveLevel'],
  unparsed: ['unparsed'],
};

/** 口径的人话名。与 `compareBasis` 的措辞一致 —— 两处各写一份就会对不上。 */
const basisLabel = (b) => (b === 'dryMatter' ? '占干物质'
  : b === 'productWeight' ? '占产品总重' : String(b || '未填'));

/**
 * 被拒行的组键分量：按 {@link checkAgainstReference} ③ 的**同一套规则**解析子指标。
 *
 * ⚠ 为什么被拒行也要解析（而不是直接用原始 `metric` 文本）：
 *   调用方可能传**下标**而不是标签（`metric: 0`）。已定位行回显的是标签，
 *   被拒行若沿用原始文本，同一个子指标会**裂成两组** —— 组内「混口径」
 *   标记（`bases.length > 1`）会因此漏检，而那正是本函数最要防的合并。
 *   这是一处**已知的镜像同步成本**：若 ③ 侧的解析规则变更，此处必须同步
 *   （由行为测试「同一子指标传标签 / 传下标必须同组」钉住，不许只改一侧）。
 *
 * @returns {{key:string, text:string}} 解析不出时 `key` 为原始 `metric` 文本、`text` 为 ''
 */
function metricKeyOfRefused(refId, metric) {
  const ref = referenceById(refId);
  const specs = ref ? specsOf(ref) : [];
  let picked = null;
  // ⚠ 合并键也要先剥掉 refId 前缀（UI 行形状，见 METRIC_KEY_SEP）：
  //   不剥的话被拒行的组键带着 `refId|||` 前缀，与同一子指标的已定位行
  //   **裂成两组** —— 正是这个函数的注释要防的那件事。
  if (typeof metric === 'string' && metric.includes(METRIC_KEY_SEP)) {
    metric = metric.slice(metric.indexOf(METRIC_KEY_SEP) + METRIC_KEY_SEP.length);
  }
  if (metric === undefined || metric === null || metric === '') {
    if (specs.length === 1) picked = specs[0];
  } else {
    picked = typeof metric === 'number'
      ? specs[metric]
      : specs.find((s) => s.label === metric || s.text === String(metric));
  }
  if (picked) return { key: picked.label, text: picked.text };
  return { key: String(metric ?? ''), text: '' };
}

/**
 * 混口径说明。**有冲突才非空**（`bases.length > 1`）—— 没冲突时补一句
 * 「口径一致」是废话，还会让「有没有冲突」这件事要多看一个字段。
 *
 * @param {string[]} bases 组内全部口径（首现序）
 * @param {Set<string>} okBases 已定位行的口径集合
 * @returns {string}
 */
function basisNoteOf(bases, okBases) {
  if (bases.length <= 1) return '';
  if (okBases.size > 1) {
    // 已定位行自身跨口径（只有 fiber 这类 convertible 组可能出现）——
    // 不同口径差一个水分因子，合并算出的数有模有样但是错的。
    return `口径冲突：本组已定位的行同时写着「${[...okBases].map(basisLabel).join('」「')}」。`
      + '不同口径之间差一个水分因子，把它们的数放进同一组算代表值、最小值、最大值与差值，'
      + '得出的是没有意义的数，因此本组这四个字段留空。';
  }
  if (okBases.size === 1) {
    const others = bases.filter((b) => !okBases.has(b)).map(basisLabel);
    return `本组已定位的行统一为「${basisLabel([...okBases][0])}」口径，`
      + '代表值、最小值、最大值与差值只按这些行计算；'
      + `另有被拒行声明的是「${others.join('」「')}」，它们已列入本组 refusedRows（被拒明细），不进入数值统计。`;
  }
  return `口径冲突：本组各行声明的口径有「${bases.map(basisLabel).join('」「')}」，且暂无已定位的行。`
    + '不同口径之间差一个水分因子，即使之后都能定位，也不能把不同口径的数合并成一算。';
}

/**
 * 把一整张配方表按 **`refId + 子指标`** 分组，给出总览。
 *
 * ## 为什么要有这个函数（不是把 `checkFormulaTable` 的结果排个序）
 *
 * 真实的核对场景是**多来源对同一个子指标**：标签保证值、自检、供应商 COA、
 * 文献值各给一个数，于是同一个子指标在表里出现多行，每行各自一个 band，
 * 使用者要自己心算分布。`checkFormulaTable` 刻意**不做汇总**（见 §7 约束②：
 * 合并状态会把漏项伪装成已处理），但「6 行里 4 行落在同一档」这种分布
 * 确实需要有人替使用者数出来。这个函数做的就是那一步：**只数分布，
 * 不下判定结论**（`FORMULA_NOTE` 同源纪律，边界契约 R2）。
 *
 * ## 四条设计约束（每条都对应一类会出事的形态）
 *
 *   ① **分组键是 `refId + 子指标`，不是单独的 `metric`。**
 *      `metricLabel` 是一条 ref 底下的子指标标签，跨 ref 会同名不同义
 *      （多条 AAFCO 条目都有「成年维持」下限）。只按 `metric` 分组会把
 *      不同参照值的行并成一组，min/max 跨越不同规格 —— 正是本文件文件头
 *      记录的「把两个生命阶段的下限当成一个区间」的翻版。
 *   ② **拒绝行进组但不进分布。** 被拒行指名了子指标并给了值，算组内一员
 *      （计入 `refused` 与 `refusedRows`，理由原样透出），但**不计入
 *      `bands`** —— 它没有得到答案，计进去就是假绿。空行与未选行
 *      **不进任何组**：空行不是指标，「没做的事不能说成做砸了」。
 *   ③ **代表值 = min（保守档），且与 min 恒等。** 用户拍板：保证值场景
 *      取最低来源更稳妥。`spread` 在 banded < 2 时为 `null` 而不是 0 ——
 *      单行组给 0 会假装测过离散度。
 *   ④ **混口径不合并。** 已定位行自身跨口径（只有 fiber 这类 convertible
 *      组可能出现）时，代表值 / 最小值 / 最大值 / 差值**全部留空**：
 *      不同口径差一个水分因子，合并会得出没有意义的数。宁空不给错数。
 *
 * ## 错误形态
 * 对任何输入不抛异常：非数组按 `[]`；行元素缺字段逐行降级（继承
 * `checkFormulaTable` 的容错）；业务拒绝全部是数据（`status` /
 * `refusedRows`），不用异常表达 —— 「8 行里 3 行核不了」是数据不是崩溃。
 *
 * @param {Array<{name?:string, mine?:string, myBasis?:'productWeight'|'dryMatter', refId?:string, metric?:string|number}>} rows
 *   与 {@link checkFormulaTable} 完全同构的配方表。
 * @returns {{rows:object[], summary:object, groups:object[], note:string}}
 *   `rows` / `summary` 是 `checkFormulaTable(rows)` 返回值的**透传**（同一个对象）；
 *   `groups` 按组内首现行序排列（**不排序** —— 排序即评分）；
 *   `note` 恒等于 {@link FORMULA_NOTE}（同源引用，不另立口径）。
 *   每个 group：`{key, refId, refTitle, refSource, refUpdatedAt, metricLabel,
 *   metricText, bases, basisConflict, basisNote, needsMoisture, caveat, rows,
 *   banded, refused, refusedRows, representative, min, max, spread, bands,
 *   rollup}`；`key = refId + "\\u0000" + metricKey`。
 */
export function formulaOverview(rows) {
  const checked = checkFormulaTable(rows);
  const list = Array.isArray(rows) ? rows : [];
  const order = [];
  const byKey = new Map();

  for (const row of checked.rows) {
    // ① 只有「填了用量且指名了参照值」的行进组。empty / unpicked 不算指标 ——
    //   「没做的事不能说成做砸了」，它们只在整表 summary 里计数。
    //   （refId 为空的行在 checkFormulaTable 里已是 unpicked，这里是双保险。）
    if (row.status !== 'ok' && row.status !== 'refused') continue;
    if (!row.refId) continue;

    // ② 组键的 metric 分量：已定位行取回显标签；被拒行按 ③ 同规则解析
    //   （被拒行也必须解析，理由见 metricKeyOfRefused）。
    let metricLabel = '';
    let metricText = '';
    if (row.status === 'ok') {
      metricLabel = row.metricLabel;
      metricText = row.metricText || '';
    } else {
      const parsed = metricKeyOfRefused(row.refId, list[row.index]?.metric);
      metricLabel = parsed.key;
      metricText = parsed.text;
    }

    const key = `${row.refId}\u0000${metricLabel}`;
    let g = byKey.get(key);
    if (!g) {
      const ref = referenceById(row.refId);
      g = {
        key,
        refId: row.refId,
        // 组身份三字段与已定位行的回显**同源**（都取自 referenceById），
        // 不另起一套 —— 两份来源迟早对不上，而漂移是静默的。
        refTitle: ref?.title ?? '',
        refSource: ref?.source?.name ?? '',
        refUpdatedAt: ref?.updatedAt ?? '',
        metricLabel,
        metricText,
        bases: [],
        needsMoisture: false,
        caveat: '',
        rows: 0,
        banded: 0,
        refused: 0,
        refusedRows: [],
        bands: emptyBands(),
        okRows: [],
        okBases: new Set(),
        seenBases: new Set(),
      };
      byKey.set(key, g);
      order.push(g);
    }

    // ③ 口径从**原始输入行**按 index 取 —— checkFormulaTable 的回显不带 myBasis。
    //   归一规则与 checkFormulaTable 逐字一致（缺省 productWeight）：
    //   不归一的话，「没填口径」会变成第三种口径，无端制造冲突。
    const myBasis = list[row.index]?.myBasis === 'dryMatter' ? 'dryMatter' : 'productWeight';
    if (!g.seenBases.has(myBasis)) {
      g.seenBases.add(myBasis);
      g.bases.push(myBasis);
    }
    g.rows += 1;

    if (row.status === 'ok') {
      // 组内首个已定位行的 caveat（同一 refId+metric 的已定位行口径相同 ⇒ caveat 相同）
      if (!g.okRows.length) g.caveat = row.caveat;
      g.okRows.push(row);
      g.okBases.add(myBasis);
      g.banded += 1;
      if (BAND_IDS.has(row.band)) g.bands[row.band] += 1;
      if (row.needsMoisture) g.needsMoisture = true;
      if (!g.metricText && row.metricText) g.metricText = row.metricText;
    } else {
      // 被拒行：进组、单独计数、理由**原样透出**，但不进 bands ——
      // 它没有得到答案，计进分布就是假绿。
      g.refused += 1;
      g.refusedRows.push({ index: row.index, name: row.name, mine: row.mine, reason: row.reason });
      if (!g.metricText && metricText) g.metricText = metricText;
    }
  }

  const groups = order.map((g) => {
    // ④ 代表值 = min（用户拍板的保守档）。**与 min 是同一个值**（同一个对象
    //   引用）—— 写两套算法就会有两份漂移，而「代表值 ≠ 最小值」是最难
    //   发现的那种错。平手取 index 最小者：遍历即 index 升序，严格小于才换。
    let min = null;
    let max = null;
    for (const row of g.okRows) {
      if (!Number.isFinite(row.massFrac)) continue;   // 防御：ok 行必带有限值
      const v = { index: row.index, name: row.name, raw: row.mine, massFrac: row.massFrac };
      if (!min || v.massFrac < min.massFrac) min = v;
      if (!max || v.massFrac > max.massFrac) max = v;
    }
    const mixedOk = g.okBases.size > 1;
    if (mixedOk) {
      // ⑤ 混口径不合并：宁空不给错数（理由见 basisNoteOf）。
      min = null;
      max = null;
    }
    // ⑥ 差值：banded < 2 或混口径时为 null。单行组给 0 会假装测过离散度；
    //   两行同值时差值是**真的 0**（确实测了，只是没差别）。
    const spread = min && max && g.banded >= 2 && !mixedOk
      ? max.massFrac - min.massFrac
      : null;
    const basisConflict = g.bases.length > 1;
    const basisNote = basisNoteOf(g.bases, g.okBases);
    // ⑦ rollup：五档显式零初始化，再按模块级归并表查表相加。
    const rollup = { inRange: 0, belowLower: 0, aboveUpper: 0, levelRelative: 0, unparsed: 0 };
    for (const [rk, from] of Object.entries(ROLLUP_FROM_BANDS)) {
      rollup[rk] = from.reduce((n, b) => n + g.bands[b], 0);
    }
    return {
      key: g.key,
      refId: g.refId,
      refTitle: g.refTitle,
      refSource: g.refSource,
      refUpdatedAt: g.refUpdatedAt,
      metricLabel: g.metricLabel,
      metricText: g.metricText,
      bases: g.bases,
      basisConflict,
      basisNote,
      needsMoisture: g.needsMoisture,
      caveat: g.caveat,
      rows: g.rows,
      banded: g.banded,
      refused: g.refused,
      refusedRows: g.refusedRows,
      representative: min,
      min,
      max,
      spread,
      bands: g.bands,
      rollup,
    };
  });

  return { rows: checked.rows, summary: checked.summary, groups, note: FORMULA_NOTE };
}
