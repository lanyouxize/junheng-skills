#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
犬猫营养基准换算工具（pet-nutrition-needs skill）

确定性换算，无第三方依赖。覆盖 NRC《犬猫营养需要》三种表达基准互转、
代谢体重指数、维持能量需要量(MER)估算、犬粮 ME 预测公式。

用法：
    python nutrient_calc.py --demo            # 跑内置自检 + 示例
    python nutrient_calc.py dm2kcal 12        # 12 g/kg DM(4000kcal) -> 每1000kcal
    python nutrient_calc.py kcal2dm 3         # 3 g/1000kcal -> g/kg DM
    python nutrient_calc.py metabw --dog 15   # 15kg 犬代谢体重
    python nutrient_calc.py mer --dog 15      # 15kg 犬维持 MER(kcal)
    python nutrient_calc.py me --protein 250 --fat 150 --nfe 400 --fibre 30
"""

import argparse
import sys

# NRC 假定：每千克 DM 含 4000 kcal ME
DM_KCAL_PER_KG = 4000.0


# ---------- 基准互换 ----------
def dm_to_per1000kcal(x_g_per_kg_dm: float) -> float:
    """每千克 DM(假定 4000 kcal ME) -> 每 1000 kcal ME 的克数。"""
    return x_g_per_kg_dm * (1000.0 / DM_KCAL_PER_KG)


def per1000kcal_to_dm(y_g_per_1000kcal: float) -> float:
    """每 1000 kcal ME -> 每千克 DM(假定 4000 kcal ME) 的克数。"""
    return y_g_per_1000kcal * (DM_KCAL_PER_KG / 1000.0)


def dog_metabolic_weight(bw_kg: float) -> float:
    """犬代谢体重 BW^0.75。"""
    return bw_kg ** 0.75


def cat_metabolic_weight(bw_kg: float, obese: bool = False) -> float:
    """猫代谢体重：BCS<=5 用 BW^0.67；BCS>5 用 BW^0.4。"""
    return bw_kg ** (0.4 if obese else 0.67)


# ---------- 能量 ----------
def dog_mer_maintenance(bw_kg: float, lifestyle: str = "active") -> float:
    """
    犬维持 MER (kcal/d) = 132 * BW^0.75，按生活方式修正：
      active   : 132 (实验活泼犬基准)
      pet      : ×0.85 (久坐宠物犬，−15%)
      senior   : ×0.68 (老年犬：132×0.8)
    返回 kcal/天。
    """
    base = 132.0 * dog_metabolic_weight(bw_kg)
    factor = {"active": 1.0, "pet": 0.85, "senior": 0.8 * 0.85}.get(lifestyle, 1.0)
    return base * factor


def cat_mer_maintenance(bw_kg: float, obese: bool = False) -> float:
    """猫维持 MER 近似：按 BW^0.67 以 250 kcal@4kg 为锚点缩放。"""
    ref = 250.0 / (4.0 ** 0.67)  # kcal per kg^0.67
    return ref * cat_metabolic_weight(bw_kg, obese=obese)


def dog_me_predict(protein_g, fat_g, nfe_g, fibre_g):
    """
    犬粮 ME 预测（NRC §3）：
      GE = 5.7*蛋白 + 9.4*脂肪 + 4.1*(NFE+纤维)
      能量消化率% = 91.2 - 1.43*粗纤维%
      DE = GE*消化率/100
      ME = DE - 1.04*蛋白
    输入：每 kg 日粮中各养分克数。
    返回 (GE, digest_pct, DE, ME) 单位 kcal/kg。
    """
    ge = 5.7 * protein_g + 9.4 * fat_g + 4.1 * (nfe_g + fibre_g)
    digest_pct = 91.2 - 1.43 * fibre_g
    de = ge * digest_pct / 100.0
    me = de - 1.04 * protein_g
    return ge, digest_pct, de, me


# ---------- 自检 ----------
def _self_test() -> None:
    # 基准互转应为逆运算
    assert abs(dm_to_per1000kcal(12.0) - 3.0) < 1e-9
    assert abs(per1000kcal_to_dm(3.0) - 12.0) < 1e-9
    # 15kg 犬代谢体重
    assert abs(dog_metabolic_weight(15.0) - 15.0 ** 0.75) < 1e-9
    # 15kg 活跃犬 MER ~ 132 * 7.62 = 1005 kcal（与原书 1000 kcal 示例吻合）
    assert abs(dog_mer_maintenance(15.0, "active") - 1005.6) < 1.0
    # 4kg 猫维持 MER 锚点应为 ~250
    assert abs(cat_mer_maintenance(4.0) - 250.0) < 1e-6
    # ME 预测：示例日粮
    ge, dig, de, me = dog_me_predict(250, 150, 400, 30)
    assert ge > 0 and me > 0 and 0 < dig < 100
    print("[OK] nutrient_calc self-test passed")


def _demo() -> None:
    _self_test()
    print("示例：")
    print(f"  犬钙幼 12 g/kg DM -> {dm_to_per1000kcal(12):.2f} g/1000kcal")
    print(f"  猫维持 250kcal@4kg -> 代谢体重 {cat_metabolic_weight(4.0):.3f}")
    print(f"  15kg 犬(pet) MER ≈ {dog_mer_maintenance(15,'pet'):.0f} kcal/d")
    ge, dig, de, me = dog_me_predict(250, 150, 400, 30)
    print(f"  示例犬粮 ME ≈ {me:.0f} kcal/kg (GE={ge:.0f}, 消化率={dig:.1f}%)")


def _cli() -> None:
    p = argparse.ArgumentParser(description="犬猫营养基准换算")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("dm2kcal"); s.add_argument("x", type=float)
    s = sub.add_parser("kcal2dm"); s.add_argument("y", type=float)
    s = sub.add_parser("metabw"); s.add_argument("--dog", type=float); s.add_argument("--cat", type=float); s.add_argument("--obese", action="store_true")
    s = sub.add_parser("mer"); s.add_argument("--dog", type=float); s.add_argument("--cat", type=float); s.add_argument("--lifestyle", default="active"); s.add_argument("--obese", action="store_true")
    s = sub.add_parser("me"); s.add_argument("--protein", type=float, required=True); s.add_argument("--fat", type=float, required=True); s.add_argument("--nfe", type=float, required=True); s.add_argument("--fibre", type=float, required=True)
    s = sub.add_parser("demo")

    a = p.parse_args()
    if a.cmd == "dm2kcal": print(dm_to_per1000kcal(a.x))
    elif a.cmd == "kcal2dm": print(per1000kcal_to_dm(a.y))
    elif a.cmd == "metabw":
        if a.dog is not None: print(f"dog BW^0.75 = {dog_metabolic_weight(a.dog):.4f}")
        if a.cat is not None: print(f"cat BW^0.67 = {cat_metabolic_weight(a.cat, a.obese):.4f}")
    elif a.cmd == "mer":
        if a.dog is not None: print(f"dog MER = {dog_mer_maintenance(a.dog, a.lifestyle):.1f} kcal/d")
        if a.cat is not None: print(f"cat MER = {cat_mer_maintenance(a.cat, a.obese):.1f} kcal/d")
    elif a.cmd == "me":
        ge, dig, de, me = dog_me_predict(a.protein, a.fat, a.nfe, a.fibre)
        print(f"GE={ge:.1f} digest%={dig:.2f} DE={de:.1f} ME={me:.1f} kcal/kg")
    elif a.cmd == "demo":
        _demo()


if __name__ == "__main__":
    _cli() if len(sys.argv) > 1 else _demo()
