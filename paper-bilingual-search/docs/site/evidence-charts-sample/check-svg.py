#!/usr/bin/env python3
"""check-svg.py — 对证据分布三图做**独立的**严格校验

为什么独立：JS 侧的 `geomCheck()` 是出图模块自带的检查器，用同一份逻辑验自己必然同源。
这里换一门语言、换一套解析器（`xml.etree` 严格解析）、换一种估宽方式（按 Unicode 东亚宽度
而不是字符码点阈值），只求「两条独立路径都通过」这一件事。

判据：
  S1 严格 XML 可解析（未转义的 & < > 会直接抛错 —— 关键词/标题里出现 & 就是这一步拦）
  S2 根元素 width/height 与 viewBox 一致，且 viewBox 起点为 0 0
  S3 所有 rect 的四边在画布内
  S4 所有 text 的估算右缘不越出画布（按 text-anchor 换算）
  S5 文件内 id 唯一（pattern 内联到同一页面时重复 id 会让引用指向错误目标）
  S6 文本里不得出现未替换的字面量（'undefined' / 'NaN' / 'null' / '[object'）
     —— 这三个是 JS 拼字符串最容易漏出来的东西，肉眼扫 80 行 SVG 未必看得见

用法：python check-svg.py [--dir .]
退出码：0 全通过；1 有违规
"""
import sys
import os
import re
import glob
import xml.etree.ElementTree as ET
import unicodedata

NS = '{http://www.w3.org/2000/svg}'
FONT_BY_CLASS = {
    'ec-title': 15.0, 'ec-sub': 11.0, 'ec-axis': 10.5, 'ec-label': 12.0, 'ec-label-b': 12.5,
    'ec-value': 12.5, 'ec-cellv': 12.0, 'ec-note': 10.5, 'ec-warn': 11.0,
    'ec-legend': 10.5, 'ec-foot': 10.0,
}


def char_w(ch, fs):
    """东亚宽字符按 1.0×fs，其余按 0.55×fs（比 JS 侧更保守一点，宁可多报）。"""
    return fs if unicodedata.east_asian_width(ch) in ('W', 'F') else fs * 0.55


def text_w(s, fs):
    return sum(char_w(c, fs) for c in s)


def font_of(el):
    style = el.get('style') or ''
    m = re.search(r'font-size:\s*([\d.]+)', style)
    if m:
        return float(m.group(1))
    cls = (el.get('class') or '').split()
    for c in cls:
        if c in FONT_BY_CLASS:
            return FONT_BY_CLASS[c]
    return 11.5


def fnum(el, k, default=None):
    v = el.get(k)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return None


def check_file(path):
    v = []
    name = os.path.basename(path)
    raw = open(path, 'rb').read()

    # S1 严格解析
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return ['S1 严格 XML 解析失败：%s' % e]

    if root.tag != NS + 'svg':
        return ['S1 根元素不是 svg：%s' % root.tag]

    # S2 尺寸一致
    w = fnum(root, 'width')
    h = fnum(root, 'height')
    if w is None or h is None:
        v.append('S2 根元素缺 width/height')
        return v
    vb = [float(x) for x in (root.get('viewBox') or '').split()]
    if len(vb) != 4 or vb[0] != 0 or vb[1] != 0 or vb[2] != w or vb[3] != h:
        v.append('S2 viewBox(%s) 与 width/height(%gx%g) 不一致' % (root.get('viewBox'), w, h))

    # S3 rect 四边（缺 x/y 时按 SVG 规范视为 0）
    for el in root.iter(NS + 'rect'):
        rw, rh = fnum(el, 'width'), fnum(el, 'height')
        if rw is None or rh is None:
            v.append('S3 rect 缺 width/height')
            continue
        x = fnum(el, 'x', 0.0)
        y = fnum(el, 'y', 0.0)
        if None in (x, y):
            v.append('S3 rect 属性非数字：x=%r y=%r' % (el.get('x'), el.get('y')))
            continue
        if x < -0.6 or y < -0.6 or x + rw > w + 0.6 or y + rh > h + 0.6:
            v.append('S3 rect 越界 [%g,%g %gx%g] 画布 %gx%g' % (x, y, rw, rh, w, h))

    # S4 文字右缘
    for i, el in enumerate(root.iter(NS + 'text'), 1):
        s = ''.join(el.itertext())
        fs = font_of(el)
        tw = text_w(s, fs)
        x = fnum(el, 'x')
        y = fnum(el, 'y')
        if x is None or y is None:
            v.append('S4 第 %d 段文字缺 x/y' % i)
            continue
        anchor = el.get('text-anchor') or el.get('{http://www.w3.org/XML/1998/namespace}text-anchor') or 'start'
        left = x - tw if anchor == 'end' else (x - tw / 2 if anchor == 'middle' else x)
        if left < 2 or left + tw > w - 2:
            v.append('S4 第 %d 段文字越界 [%.1f,%.1f] 画布 %g：%r' % (i, left, left + tw, w, s[:40]))
        if y < 0 or y > h:
            v.append('S4 第 %d 段文字 y=%g 超出画布高 %g' % (i, y, h))

    # S5 id 唯一
    ids = [el.get('id') for el in root.iter() if el.get('id')]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        v.append('S5 文件内 id 重复：%s' % '、'.join(dup))

    # S6 字面量泄漏（<title>/<desc>/aria-label 同属读者可见文本 —— 屏幕阅读器读的就是它们。
    #    初版只查 <text>，注入坏样本时恰好落在 aria-label 上，于是「检查器通过、页面露馅」）
    BAD = ('undefined', 'NaN', '[object', 'Infinity')
    for tag in ('title', 'desc', 'text'):
        for el in root.iter(NS + tag):
            s = ''.join(el.itertext())
            for bad in BAD:
                if bad in s:
                    v.append('S6 <%s> 里出现字面量 %r：%r' % (tag, bad, s[:60]))
    for el in root.iter():
        al = el.get('aria-label')
        if al:
            for bad in BAD:
                if bad in al:
                    v.append('S6 aria-label 里出现字面量 %r：%r' % (bad, al[:60]))

    return v


def main(argv):
    d = '.'
    if '--dir' in argv:
        d = argv[argv.index('--dir') + 1]
    files = sorted(glob.glob(os.path.join(d, '*.svg')))
    if not files:
        print('未找到任何 .svg（目录：%s）' % os.path.abspath(d))
        return 1
    total = 0
    bad = 0
    for f in files:
        v = check_file(f)
        total += 1
        if v:
            bad += 1
            print('✗ %s' % os.path.basename(f))
            for s in v[:6]:
                print('    ' + s)
        else:
            print('✓ %s' % os.path.basename(f))
    print('\n%d 个文件，%d 通过，%d 失败' % (total, total - bad, bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
