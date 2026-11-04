#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""桥接服务健康检查：确认 3000(workbuddy_to_api) 就绪（同机运行网关时一并检查 8000），
并打印网关侧可看到的免费模型数量（永久/限时）。"""
import json
import os
import time
import urllib.error
import urllib.request

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过本机代理


def status(url: str, auth: str | None = None, ok_codes=(200, 401)) -> int | None:
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    try:
        with OP.open(urllib.request.Request(url, headers=headers), timeout=3) as r:
            return r.status if r.status in ok_codes else None
    except Exception:
        return None


def wait(url: str, auth=None, label="", tries=40) -> bool:
    for i in range(tries):
        if status(url, auth) is not None:
            print(f"  [OK] {label} 已就绪")
            return True
        time.sleep(1)
    print(f"  [!!] {label} 未就绪（请检查对应日志）")
    return False


def main() -> None:
    print("等待 workbuddy_to_api (3000) ...")
    wait("http://127.0.0.1:3000/health", label="workbuddy_to_api :3000")

    print("等待 LLM 网关 (8000) ...")
    # /v1/models 未鉴权返回 401 也算 UP
    wait("http://127.0.0.1:8000/v1/models", auth="x", label="LLM 网关 :8000")

    # 统计网关侧免费模型（永久/限时）
    try:
        mj = os.path.join(os.path.expanduser("~"), ".workbuddy", "models.json")
        if os.path.exists(mj):
            data = json.load(open(mj, encoding="utf-8"))
            wb = [m for m in data if str(m.get("id", "")).startswith("wb-")]
            perm = [m for m in wb if "免费-永久" in (m.get("name") or "")]
            lim = [m for m in wb if "免费-限时" in (m.get("name") or "")]
            print(f"\nmodels.json 中免费模型：共 {len(wb)} 个（永久 {len(perm)} / 限时 {len(lim)}）")
    except Exception as e:
        print("统计免费模型失败:", e)


if __name__ == "__main__":
    main()
