#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拟人节奏层：nap 等待加长 / 写动作间隔 / 写动作限流 / 点击落点抖动。

为什么需要这一层（血泪来源）
--------------------------
改造自开源项目 fanyuantaier/wechatauto-replica 的 rhythm.py。该项目作者
自述：2026-09-21 真实触发微信风控（弹出验证码）之后才补上这个模块；
改造前每步固定 sleep(2.5)、读取无随机、单账号日写 500 次——三条全是
机器指纹。本项目的 scout 走「截图 + 模板匹配 + 坐标点击」，点击与按键
同样属于"写动作"，频率一样会被风控盯上，所以节奏层不是锦上添花。

档位表（环境变量 UIAC_RHYTHM 覆盖，默认 natural；非法值回退 natural
并在 stderr warn 一次）
----------------------------------------------------------------------
档位      nap 乘数      写间隔        窗口配额              冷却
off      原样返回不睡   0.0           空转（不落状态文件）   —
fast     1.0           0.2~0.5s      不限流                 —
natural  1.0~1.45      2.5~6.0s      6 次 / 120s 滑动窗口   30~75s
calm     1.0~2.0       6~14s         3 次 / 300s 滑动窗口   60~150s

设计决定与 rationale
--------------------
* nap 乘数恒 ≥1.0（只加长不缩短）：随机若能把等待缩得比调用方预期还短，
  下一步截图会早于界面渲染完成，拿到旧画面——那是错噪不是加速。
* 限流只针对"写动作"（点击/按键），读（截图/匹配）不限：风控盯的是
  行为频率，纯读取不改变任何状态。
* 配额按「最近 N 秒内的次数」滑动计算，而不是"每 N 秒重置一次计数"：
  后者会在窗口边界瞬间放过一批突发动作（整分钟开头连点 6 次）。
* 状态文件持久化（默认 <skill>/out/rhythm-state.json）：单账号日写
  500 次的教训是——配额必须跨进程、跨重启累计，否则分几批跑就能绕开
  限流。文件损坏/不存在时静默重置，限流器绝不抛异常拖垮主流程。
* 冷却语义 = "睡满一个冷却，再把窗口历史作废"：旧时间戳睡完仍在窗口内，
  不清掉会让下一次 before_write 瞬间又超限、连环睡。
* jitter_xy 默认 ±5px：来源影刀社区案例——每次都点同一像素是最典型的
  机器特征；控件内随机落点即可规避，又不改变点击语义。
* UIAC_RHYTHM_SEED（整数）存在时全部随机源用 random.Random(seed)：
  保证单测确定性；主线程不设就走系统熵源。

API 契约（签名固定，主线程直接 import）
--------------------------------------
nap(base) -> float                等待 base*乘数 秒，返回实际睡的秒数；
                                  off 档原样返回 base 且不睡（把"睡多少"
                                  的决定权交还调用方——off 是关闭节奏管理，
                                  不是跳过等待）
write_gap() -> float              按档位取一个写动作间隔并睡掉，返回秒数；
                                  off 返回 0.0
jitter_xy(x, y, radius=5)         控件内随机落点
WriteRateLimiter.before_write()   每次写动作前调用；超窗口配额则睡到冷却
                                  结束再返回，返回因限流睡掉的秒数
get_rhythm() / set_rhythm_for_test(r)   进程内单例与测试注入
"""
from __future__ import annotations

import json
import msvcrt          # Windows 文件字节锁：限流器读-改-写的互斥（仅 Windows）
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]

#: 合法档位（顺序即档位表顺序）；UIAC_RHYTHM 只能取这里面的值。
LEVELS = ("off", "fast", "natural", "calm")
DEFAULT_LEVEL = "natural"
ENV_LEVEL = "UIAC_RHYTHM"
ENV_SEED = "UIAC_RHYTHM_SEED"
#: 写动作时间戳的落点：要跨进程共享，所以放 skill 的 out/ 而不是临时目录。
DEFAULT_STATE_PATH = SKILL / "out" / "rhythm-state.json"


@dataclass(frozen=True)
class _LevelSpec:
    """一个档位的全部节奏参数。frozen：档位表是常量，运行时不许改。"""

    nap_mult: tuple[float, float]   # nap 乘数区间（恒定 ≥1.0，只加长）
    gap: tuple[float, float]        # 写动作间隔区间（秒）
    quota: int | None               # 窗口内写动作配额；None = 不限流/空转
    window: float                   # 滑动窗口长度（秒）
    cooldown: tuple[float, float]   # 超配额后的冷却区间（秒）


_LEVEL_SPECS: dict[str, _LevelSpec] = {
    # off/fast 的 nap_mult/gap 只是占位：这两个档位在方法里被特判，
    # 永远走不到查表分支（off 原样返回，fast 乘数固定 1.0）。
    "off":     _LevelSpec((1.0, 1.0), (0.0, 0.0), None, 0.0, (0.0, 0.0)),
    "fast":    _LevelSpec((1.0, 1.0), (0.2, 0.5), None, 0.0, (0.0, 0.0)),
    "natural": _LevelSpec((1.0, 1.45), (2.5, 6.0), 6, 120.0, (30.0, 75.0)),
    "calm":    _LevelSpec((1.0, 2.0), (6.0, 14.0), 3, 300.0, (60.0, 150.0)),
}

# 同一个坏档位整个进程只 warn 一次：调用方可能反复构造 Rhythm，
# 每建一次刷一行 stderr 会把日志淹了。
_WARNED_BAD_LEVELS: set[str] = set()


def resolve_level(level: str | None = None) -> str:
    """把档位名字规范化成合法值；level=None 表示读环境变量 UIAC_RHYTHM。

    非法值 → 回退 DEFAULT_LEVEL，并在 stderr 打一次 warn（按值去重）。
    空串/纯空白按"没设置"处理，不 warn（export UIAC_RHYTHM= 是常见误留）。
    """
    raw = level if level is not None else os.environ.get(ENV_LEVEL)
    if raw is None:
        return DEFAULT_LEVEL
    name = str(raw).strip().lower()
    if not name:
        return DEFAULT_LEVEL
    if name in LEVELS:
        return name
    if name not in _WARNED_BAD_LEVELS:
        _WARNED_BAD_LEVELS.add(name)
        print("rhythm: 未知档位 %r（合法值 %s），已回退 %r"
              % (name, "/".join(LEVELS), DEFAULT_LEVEL), file=sys.stderr)
    return DEFAULT_LEVEL


def _make_rng() -> random.Random:
    """全部随机源的唯一出口。

    UIAC_RHYTHM_SEED 是整数 → 用该种子造 Random（单测可复现）；没设或不是
    整数 → 系统熵源。种子脏不值得 warn（档位脏才 warn），静默退回即可，
    否则用户会被一行无关告警骚扰。
    """
    seed = os.environ.get(ENV_SEED)
    if seed is None or not str(seed).strip():
        return random.Random()
    try:
        return random.Random(int(str(seed).strip()))
    except ValueError:
        return random.Random()


class Rhythm:
    """一个档位下的节奏参数 + 随机源。nap / write_gap / jitter_xy 都吃它。"""

    def __init__(self, level: str | None = None, rng: random.Random | None = None):
        self.level = resolve_level(level)
        self._spec = _LEVEL_SPECS[self.level]
        self._rng = rng if rng is not None else _make_rng()

    def nap(self, base: float) -> float:
        """等待 base*乘数 秒，返回实际睡的秒数。

        乘数只加长不缩短（≥1.0）；off 档原样返回 base 且不睡。
        """
        if self.level == "off":
            return float(base)
        # max(1.0, ...) 是"只加长"的不变量防线：表里区间本就 ≥1.0，
        # 但将来若有人把区间改歪，这里保证不会把等待缩到比调用方预期还短。
        mult = max(1.0, self._rng.uniform(*self._spec.nap_mult))
        secs = float(base) * mult
        if secs > 0:
            time.sleep(secs)
        return secs

    def write_gap(self) -> float:
        """按档位取一个写动作间隔并睡掉，返回秒数；off 返回 0.0 不睡。"""
        if self.level == "off":
            return 0.0
        secs = self._rng.uniform(*self._spec.gap)
        if secs > 0:
            time.sleep(secs)
        return secs

    def jitter_xy(self, x: int, y: int, radius: int = 5) -> tuple[int, int]:
        """在 (x,y) 周围 ±radius 像素内随机取一个落点（默认 ±5px）。

        每次都点同一像素是最典型的机器特征（影刀社区案例）；控件内随机
        落点即可规避，又不改变点击语义。
        """
        r = int(radius)
        return (int(x) + self._rng.randint(-r, r),
                int(y) + self._rng.randint(-r, r))


_SINGLETON: Rhythm | None = None


def get_rhythm() -> Rhythm:
    """进程内单例：档位/随机源全程唯一，主流程只跟它打交道。"""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Rhythm()
    return _SINGLETON


def set_rhythm_for_test(r: Rhythm) -> Rhythm:
    """替换进程内单例（单测注入用）。返回被注入的对象，方便链式写法。"""
    global _SINGLETON
    _SINGLETON = r
    return r


def nap(base: float) -> float:
    """模块级入口：等价于 get_rhythm().nap(base)。"""
    return get_rhythm().nap(base)


def write_gap() -> float:
    """模块级入口：等价于 get_rhythm().write_gap()。"""
    return get_rhythm().write_gap()


def jitter_xy(x: int, y: int, radius: int = 5) -> tuple[int, int]:
    """模块级入口：等价于 get_rhythm().jitter_xy(x, y, radius)。"""
    return get_rhythm().jitter_xy(x, y, radius)


class WriteRateLimiter:
    """写动作（点击/按键）限流器：滑动窗口配额 + 超限冷却，状态落盘。

    状态文件是一个 JSON 数组 [unix_ts, ...]，记录每次放行的写动作；
    每次 before_write 都重新读文件——这是"跨进程生效"的关键，内存缓存
    会让第二个进程看不见第一个进程写下的记录。

    窗口/配额/冷却/state_path/随机源都可注入：单测把冷却换成
    (0.05, 0.1) 就能验证"真的睡了"而不必真睡 30~75 秒。
    """

    def __init__(self, state_path=None, level: str | None = None,
                 window: float | None = None, quota: int | None = None,
                 cooldown_range=None, rng: random.Random | None = None):
        self.state_path = (Path(state_path) if state_path is not None
                           else DEFAULT_STATE_PATH)
        # 不显式给档位时跟随进程内单例：UIAC_RHYTHM=calm 一设，全链路降速。
        self.level = resolve_level(level if level is not None else get_rhythm().level)
        spec = _LEVEL_SPECS[self.level]
        self.window = spec.window if window is None else float(window)
        self.quota = spec.quota if quota is None else int(quota)
        self.cooldown_range = (spec.cooldown if cooldown_range is None
                               else tuple(float(v) for v in cooldown_range))
        self._rng = rng if rng is not None else _make_rng()

    def _load(self) -> list[float]:
        """读状态文件；损坏/不存在/形状不对 → 静默按空历史处理。

        限流器是给主流程兜底的，绝不能因为一个坏 JSON 把点击流程炸飞。
        """
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [float(t) for t in data if isinstance(t, (int, float))]

    def _locked_update(self, mutate):
        """在文件锁保护下做「读 → mutate → 写」，返回 mutate 的返回值。

        为什么需要锁：旧实现是"读出全部 → 改 → 整体写回"，两个进程（或两个
        后台线程）同时 before_write 时后写者会覆盖先写者的记录
        （last-write-wins）——限流器少记一次，风控配额就漏一个。改为持锁
        读-改-写后，检查与记录是原子的。

        两个坑（都踩过）：
        ① msvcrt 的常量是 LK_LOCK / LK_NBLCK / LK_UNLCK——没有 LK_LK，
           写错会被 except 静默吞掉，整个限流器空转还不报错；
        ② 建文件也必须进锁内（用 O_CREAT|O_EXCL 保证只有一个进程建成）：
           否则"exists 检查 → 建文件"在锁外，别人的 write_text 会截断
           持锁方刚写下的内容。
        锁只包住"决策+落盘"这几毫秒；冷却睡眠在锁外，不会阻塞别人。
        """
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.state_path.exists():
                try:
                    fd = os.open(self.state_path,
                                 os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    try:
                        os.write(fd, b"[]")
                    finally:
                        os.close(fd)
                except FileExistsError:
                    pass          # 别人先建成了：锁内读到的就是最新内容
                except Exception:
                    pass
            with open(self.state_path, "r+", encoding="utf-8") as f:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    f.seek(0)
                    try:
                        data = json.loads(f.read() or "[]")
                    except Exception:
                        data = []
                    if not isinstance(data, list):
                        data = []
                    stamps = [float(t) for t in data
                              if isinstance(t, (int, float))]
                    result = mutate(stamps)
                    f.seek(0)
                    f.truncate()
                    f.write(json.dumps(result))
                    f.flush()
                    return result
                finally:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            return None

    def before_write(self) -> float:
        """每次写动作（点击/按键）前调用。返回因限流而睡掉的秒数。

        放行返回 0.0；超窗口配额则睡满一个冷却再返回。off/fast 档
        （quota=None）直接空转，连状态文件都不碰。
        """
        if self.quota is None:
            return 0.0
        now = time.time()
        box = {"cool": 0.0}

        def mutate(stamps):
            # 滑动窗口：只数"最近 window 秒内"的记录，旧的自动失效。
            recent = [t for t in stamps if now - t < self.window]
            if len(recent) < self.quota:
                recent.append(now)
                return recent
            box["cool"] = self._rng.uniform(*self.cooldown_range)
            # 冷却的语义就是"停够一段时间再继续"：睡完把窗口历史作废并记下
            # 本次。不清的话旧时间戳睡完仍在窗口内，下次调用又会瞬间超限。
            return [now]

        self._locked_update(mutate)
        cool = box.get("cool") or 0.0
        if cool > 0:
            time.sleep(cool)
        return cool


if __name__ == "__main__":
    # 用法: python rhythm.py —— 只打印当前档位与参数，不睡不点不截图，
    # 供人工核对 UIAC_RHYTHM / UIAC_RHYTHM_SEED 是否按预期生效。
    r = get_rhythm()
    spec = _LEVEL_SPECS[r.level]
    lim = WriteRateLimiter()
    print("档位=%s（env %s=%r）" % (r.level, ENV_LEVEL, os.environ.get(ENV_LEVEL)))
    print("nap 乘数=%s 写间隔=%s" % (spec.nap_mult, spec.gap))
    print("写配额=%s 窗口=%ss 冷却=%s" % (spec.quota, spec.window, spec.cooldown))
    print("状态文件=%s" % lim.state_path)
