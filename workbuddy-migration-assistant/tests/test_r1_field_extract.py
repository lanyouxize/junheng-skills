"""test_r1_field_extract.py — field-subtree extraction & deep-merge (v1.2.1).

Covers:
  - export side: extract_fields whitelist + exclude_fields blacklist
  - import side: per-key target-wins deep merge
  - on_missing / on_invalid policy
"""
import json
import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts import field_extract as FE  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


SAMPLE = json.loads(
    (SRC / "tests" / "app-config.sample.json").read_text(encoding="utf-8")
)
ASSET = {
    "extract_fields": ["personalization.customPrompt", "personalization.toneStyle"],
    "exclude_fields": ["sandboxSafetyEnabled"],
}


def test_export_extraction():
    sub = FE.extract_subtree(SAMPLE, ASSET["extract_fields"], ASSET["exclude_fields"])
    check("提取 personalization.customPrompt",
          sub.get("personalization", {}).get("customPrompt") == "你是一个严谨的助手")
    check("提取 personalization.toneStyle",
          sub.get("personalization", {}).get("toneStyle") == "formal")
    check("排除 sandboxSafetyEnabled", "sandboxSafetyEnabled" not in json.dumps(sub))
    check("不迁移 theme（非白名单）", "theme" not in json.dumps(sub))
    check("不迁移 model（非白名单）", "model" not in json.dumps(sub))


def test_import_deep_merge():
    with tempfile.TemporaryDirectory(prefix="wb_fe_") as td:
        td = Path(td)
        src = td / "app-config.json"
        dst = td / "target-app-config.json"
        src.write_text(json.dumps(SAMPLE), encoding="utf-8")
        # target has customPrompt already set (target-wins) + its own theme
        dst.write_text(json.dumps({
            "personalization": {"customPrompt": "目标端已有指令", "extra": "keep"},
            "theme": "light",
        }), encoding="utf-8")
        res = FE.merge_field_subtree(src, dst, ASSET, overwrite=False)
        out = json.loads(dst.read_text(encoding="utf-8"))
        check("merge action", res["action"] == "merged", res)
        check("target-wins customPrompt",
              out["personalization"]["customPrompt"] == "目标端已有指令")
        check("source 新增 toneStyle",
              out["personalization"].get("toneStyle") == "formal")
        check("目标端 extra 保留", out["personalization"].get("extra") == "keep")
        check("目标端 theme 保留", out.get("theme") == "light")
        check("sandboxSafetyEnabled 未混入", "sandboxSafetyEnabled" not in json.dumps(out))


def test_on_missing_and_invalid():
    with tempfile.TemporaryDirectory(prefix="wb_fe2_") as td:
        td = Path(td)
        missing = td / "missing.json"
        res = FE.extract_from_file(missing, ASSET)
        check("on_missing 返回 skip", res["action"] == "skip")
        bad = td / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        res2 = FE.extract_from_file(bad, ASSET)
        check("on_invalid 返回 warn-skip", res2["action"] == "warn-skip")


if __name__ == "__main__":
    test_export_extraction()
    test_import_deep_merge()
    test_on_missing_and_invalid()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
