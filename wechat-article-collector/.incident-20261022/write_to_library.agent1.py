#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write 模式：把采集层产出的 JSONL（24 列记录）写入「铭衍·元典」资料库数据表。

转发链：本模块 -> subprocess 调 library skill 的 space_api.py（统一 CLI）-> SpaceEngine Agent API：
  - space.workspace.node-info        解析智库节点 -> spaceId
  - space.workspace.list-nodes       在节点下按标题查找已存在的数据表（幂等建表）
  - space.database.create-database   不存在则一次建全 24 列（normalize.COLUMN_CONFIGS）
  - space.database.query-database    写前按 record_id 查重 + 写后存在性验证
  - space.database.batch-add-records 分批写入（默认 50/批，上限 100，批间小延迟）

关键坑（实测 library/_common.py）：space_api.py 出错时 stdout 输出 {"error": ...} 且
**退出码为 0**（error_exit 默认 code=0），因此成败必须解析 stdout JSON 的 error 键，
不能信退出码。

写入安全：
  - status=fail 行写库前剔除（逐条 warn，不静默）；
  - 写前按 record_id 查重，已存在跳过——重复执行不写重行（schema.md §3/§4）；
  - 写后对每批做存在性复查（entry.md §3 假成功防御）；
  - --dry-run 只做读操作（node-info/list-nodes/query-database）并打印将发送的 payload，零写入。

用法：
    python collect.py --yes write --in out/v1.jsonl --library-node <node_id> --dry-run
    python collect.py --yes write --in out/v1.jsonl --library-node <node_id>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from common import (
    EXIT_ENV,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ENV,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_WARN,
    emit_event,
    load_config,
    read_jsonl,
)
from normalize import COLUMN_CONFIGS, LIBRARY_STATUSES, to_property_values

_API_CALL_TIMEOUT = 60     # space_api.py 单次调用超时秒
_BATCH_DELAY_SECONDS = 0.5  # 批间小延迟（服务端 30 QPS/库）
_DEDUP_CHUNK = 100          # 查重 OR 过滤器的最大子条件数
_PENDING_DB_MARKER = "<create-database 后获得>"


class SpaceApiError(RuntimeError):
    """space_api.py 调用失败（HTTP/业务错误：stdout 带 error 键）。"""


class SpaceApi:
    """library skill space_api.py 的 subprocess 转发器（只依赖其 stdout JSON 协议）。"""

    def __init__(self, api_cli: str, timeout: int = _API_CALL_TIMEOUT) -> None:
        self.api_cli = api_cli
        self.timeout = timeout

    def call(self, api: str, **flags: object) -> dict:
        """调用一个 API，返回 data 字典；失败抛 SpaceApiError。"""
        cmd = [sys.executable, self.api_cli, api]
        for key, value in flags.items():
            if value is None or value is False:
                continue
            flag = "--" + key.replace("_", "-")
            if value is True:
                cmd.append(flag)
            elif isinstance(value, (dict, list)):
                cmd += [flag, json.dumps(value, ensure_ascii=False)]
            else:
                cmd += [flag, str(value)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SpaceApiError(f"{api} 调用超时（>{self.timeout}s）") from exc
        except OSError as exc:
            raise SpaceApiError(f"{api} 进程启动失败: {exc}") from exc
        try:
            payload = json.loads((proc.stdout or "").strip() or "{}")
        except json.JSONDecodeError as exc:
            raise SpaceApiError(
                f"{api} 输出不是 JSON: stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise SpaceApiError(f"{api} 输出不是对象: {payload!r}")
        if "error" in payload:
            # space_api.py 的 error_exit 退出码恒为 0，只能靠 error 键识别失败
            raise SpaceApiError(f"{api} 失败: {payload['error']}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------ 参数注册
def register(subparsers: argparse._SubParsersAction) -> None:
    """注册子命令 "write"。"""
    parser = subparsers.add_parser(
        "write",
        help="写库：采集 JSONL -> 「铭衍·元典」数据表（space_api.py 转发）",
        description="把 24 列 JSONL 记录写入资料库数据表：幂等建表、record_id 查重、分批写入、写后验证。",
    )
    parser.add_argument("--in", dest="input", default="", help="采集层产出的 JSONL 路径（必填）")
    parser.add_argument("--library-node", default="", help="智库父节点 id（默认 config.library.node_id）")
    parser.add_argument("--database-name", default="", help="数据表标题（默认 config.library.database_name_prefix）")
    parser.add_argument("--database-id", default="", help="直接指定已存在的数据表 id（跳过查找/建表）")
    parser.add_argument(
        "--api-cli", default="",
        help="space_api.py 路径（默认 config.library.api_cli；自测可指向 stub）",
    )
    parser.add_argument("--batch-size", type=int, default=0, help="每批记录数（默认 50，上限 100）")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只读解析 + 打印将发送的 payload（create-database / batch-add-records），不写入",
    )
    parser.set_defaults(func=run)


# ------------------------------------------------------------------ 主流程
def run(args: argparse.Namespace) -> int:
    """执行写库，返回退出码。"""
    in_path = (getattr(args, "input", "") or "").strip()
    if not in_path:
        emit_event(LEVEL_PARAM, "write.no_input", reason="--in 必填（采集层产出的 JSONL 路径）")
        return EXIT_PARAM
    if not Path(in_path).is_file():
        emit_event(LEVEL_PARAM, "write.input_missing", path=in_path)
        return EXIT_PARAM

    config = load_config(getattr(args, "config", ""))
    library_cfg = config.get("library") or {}

    api_cli = (getattr(args, "api_cli", "") or "").strip() or str(library_cfg.get("api_cli") or "")
    if not api_cli or not Path(api_cli).is_file():
        emit_event(
            LEVEL_ENV, "write.api_cli_missing", api_cli=api_cli,
            hint="config.library.api_cli 应指向 library skill 的 space_api.py",
        )
        return EXIT_ENV
    api = SpaceApi(api_cli)

    # 1) 读取 + 过滤：fail 行剔除（逐条 warn，不静默）；无 record_id 行无法查重，同样剔除
    records = list(read_jsonl(in_path))
    writable: list[dict] = []
    skipped_fail = 0
    for record in records:
        status = record.get("status")
        if status not in LIBRARY_STATUSES:
            skipped_fail += 1
            emit_event(
                LEVEL_WARN, "write.skip_fail",
                url=record.get("url", ""), record_id=record.get("record_id"),
                status=status, fail_reason=record.get("fail_reason", ""),
            )
            continue
        if not (record.get("record_id") or "").strip():
            skipped_fail += 1
            emit_event(
                LEVEL_WARN, "write.skip_no_record_id",
                url=record.get("url", ""), reason="缺少 record_id，无法幂等查重",
            )
            continue
        writable.append(record)

    # 2) 输入内按 record_id 去重（保留首条）
    seen: set[str] = set()
    deduped: list[dict] = []
    for record in writable:
        rid = record["record_id"]
        if rid in seen:
            emit_event(LEVEL_INFO, "write.skip_dup_input", record_id=rid, url=record.get("url", ""))
            continue
        seen.add(rid)
        deduped.append(record)

    if not deduped:
        emit_event(
            LEVEL_WARN, "write.nothing_to_write",
            total=len(records), skipped_fail=skipped_fail,
        )
        return EXIT_PARTIAL

    dry_run = bool(getattr(args, "dry_run", False))
    node_id = (getattr(args, "library_node", "") or "").strip() or str(library_cfg.get("node_id") or "")
    database_name = (
        (getattr(args, "database_name", "") or "").strip()
        or str(library_cfg.get("database_name_prefix") or "公众号采集归档")
    )
    batch_size = int(getattr(args, "batch_size", 0) or library_cfg.get("batch_size") or 50)
    batch_size = min(max(batch_size, 1), 100)

    # 3) 解析目标表（读操作；dry-run 同样执行但不发 create）
    try:
        database_id, create_payload = _resolve_database(api, args, config, node_id, database_name)
    except SpaceApiError as exc:
        emit_event(LEVEL_ERROR, "write.resolve_failed", error=str(exc))
        return EXIT_ERROR

    if database_id is None:
        # 表不存在：dry-run 只打印建表 payload；实跑才创建
        _print_payload("space.database.create-database", create_payload or {})
        if dry_run:
            database_id = _PENDING_DB_MARKER
            emit_event(
                LEVEL_INFO, "write.would_create_database",
                title=database_name, properties=len(COLUMN_CONFIGS),
            )
        else:
            try:
                data = api.call("space.database.create-database", **(create_payload or {}))
            except SpaceApiError as exc:
                emit_event(LEVEL_ERROR, "write.create_database_failed", error=str(exc))
                return EXIT_ERROR
            database_id = str(data.get("database_id") or data.get("id") or "")
            if not database_id:
                emit_event(LEVEL_ERROR, "write.create_database_no_id", response=data)
                return EXIT_ERROR
            emit_event(
                LEVEL_INFO, "write.database_created",
                database_id=database_id, title=database_name, columns=len(COLUMN_CONFIGS),
            )

    # 4) 写前查重（record_id equals；新表/待建表无行可查）
    existing: set[str] = set()
    if database_id != _PENDING_DB_MARKER:
        try:
            existing = _query_existing_ids(api, database_id, [r["record_id"] for r in deduped])
        except SpaceApiError as exc:
            # 读基线失败即中止（mutation 安全：不盲写）
            emit_event(LEVEL_ERROR, "write.dedup_query_failed", error=str(exc))
            return EXIT_ERROR
    to_write = [r for r in deduped if r["record_id"] not in existing]
    skipped_dup = len(deduped) - len(to_write)
    for record in deduped:
        if record["record_id"] in existing:
            emit_event(LEVEL_INFO, "write.skip_exists", record_id=record["record_id"], url=record.get("url", ""))

    if not to_write:
        emit_event(
            LEVEL_INFO, "write.done",
            total=len(records), written=0, skipped_dup=skipped_dup,
            skipped_fail=skipped_fail, failed=0, unverified=0,
        )
        return EXIT_OK  # 幂等重跑：全部已存在

    # 5) 分批写入（dry-run 只打印 payload）
    written = failed = unverified = 0
    total_batches = (len(to_write) + batch_size - 1) // batch_size
    for index, start in enumerate(range(0, len(to_write), batch_size)):
        batch = to_write[start:start + batch_size]
        payload = {
            "databaseId": database_id,
            "records": [to_property_values(record) for record in batch],
        }
        if dry_run:
            _print_payload("space.database.batch-add-records", payload)
            continue
        try:
            data = api.call("space.database.batch-add-records", **payload)
        except SpaceApiError as exc:
            failed += len(batch)
            emit_event(
                LEVEL_ERROR, "write.batch_failed",
                batch_index=index, batch_size=len(batch), error=str(exc),
            )
            continue
        ok_ids: list[str] = []
        for position, result in enumerate(data.get("results") or []):
            rid = batch[position]["record_id"] if position < len(batch) else ""
            if result.get("success"):
                written += 1
                ok_ids.append(rid)
            else:
                failed += 1
                emit_event(
                    LEVEL_WARN, "write.record_failed",
                    record_id=rid, error=str(result.get("error") or ""),
                )
        # 假成功防御：写后复查本批 record_id 是否真的可查见
        if ok_ids:
            missing = _verify_written(api, database_id, ok_ids)
            if missing:
                unverified += len(missing)
                emit_event(LEVEL_WARN, "write.unverified", record_ids=missing)
        if index + 1 < total_batches:
            time.sleep(_BATCH_DELAY_SECONDS)

    if dry_run:
        emit_event(
            LEVEL_INFO, "write.done",
            total=len(records), dry_run=True, would_write=len(to_write),
            skipped_dup=skipped_dup, skipped_fail=skipped_fail,
        )
        return EXIT_OK

    emit_event(
        LEVEL_INFO, "write.done",
        total=len(records), written=written, skipped_dup=skipped_dup,
        skipped_fail=skipped_fail, failed=failed, unverified=unverified,
    )
    if failed or unverified:
        return EXIT_PARTIAL
    return EXIT_OK


def _resolve_database(
    api: SpaceApi, args: argparse.Namespace, config: dict, node_id: str, database_name: str,
) -> tuple[str | None, dict | None]:
    """定位目标数据表。返回 (database_id, None) 或 (None, create_payload) 表示需要建表。"""
    library_cfg = config.get("library") or {}
    explicit = (getattr(args, "database_id", "") or "").strip() or str(library_cfg.get("database_id") or "")
    if explicit:
        data = api.call("space.database.get-database", database_id=explicit)
        if data.get("id") or data.get("database_id") or data.get("title"):
            return explicit, None
        raise SpaceApiError(f"get-database 未返回表信息: {explicit}")

    if not node_id:
        raise SpaceApiError("缺少 --library-node / config.library.node_id，无法定位或创建数据表")

    node = api.call("space.workspace.node-info", node_id=node_id).get("node") or {}
    space_id = str(node.get("spaceId") or "")
    if not space_id:
        raise SpaceApiError(f"node-info 未返回 spaceId（node={node_id}）")

    # 分页扫描节点子项，找同名数据表（kind 含 database；kind 缺失时按标题兜底）
    offset = 0
    while True:
        data = api.call(
            "space.workspace.list-nodes",
            space_id=space_id, parent_node_id=node_id, limit=100, offset=offset,
        )
        for item in data.get("nodes") or []:
            title = str(item.get("title") or "")
            kind = str(item.get("kind") or "").lower()
            if title == database_name and (not kind or "database" in kind or "db" in kind):
                found = str(item.get("id") or "")
                if found:
                    emit_event(
                        LEVEL_INFO, "write.database_found",
                        database_id=found, title=title, kind=kind,
                    )
                    return found, None
        if not data.get("hasMore"):
            break
        offset += int(data.get("limit") or 100)

    properties = [{"name": name, "config": cfg} for name, cfg in COLUMN_CONFIGS]
    return None, {
        "spaceId": space_id,
        "parentId": node_id,
        "title": database_name,
        "properties": properties,
    }


def _record_id_filter(record_ids: list[str]) -> dict:
    """record_id equals 的 OR 过滤器（单个条件时退化为叶子节点）。"""
    leaves = [
        {"property": {"property": "record_id", "text": {"equals": rid}}}
        for rid in record_ids
    ]
    if len(leaves) == 1:
        return leaves[0]
    return {"or": leaves}


def _query_existing_ids(api: SpaceApi, database_id: str, record_ids: list) -> set[str]:
    """分批查询已存在的 record_id 集合。查询失败抛 SpaceApiError。"""
    ids = [str(rid) for rid in record_ids if rid]
    existing: set[str] = set()
    for start in range(0, len(ids), _DEDUP_CHUNK):
        chunk = ids[start:start + _DEDUP_CHUNK]
        data = api.call(
            "space.database.query-database",
            database_id=database_id,
            filter=_record_id_filter(chunk),
            fields=["record_id"],
            page_size=100,
        )
        for row in data.get("results") or []:
            rid = row.get("record_id")
            if rid:
                existing.add(str(rid))
    return existing


def _verify_written(api: SpaceApi, database_id: str, record_ids: list[str]) -> list[str]:
    """写后存在性复查；查询本身失败仅告警，不误报缺失。"""
    try:
        existing = _query_existing_ids(api, database_id, record_ids)
    except SpaceApiError as exc:
        emit_event(LEVEL_WARN, "write.verify_query_failed", error=str(exc))
        return []
    return [rid for rid in record_ids if rid not in existing]


def _print_payload(api_name: str, payload: dict) -> None:
    """dry-run：把将发送的 payload 原样打印到 stdout（数据出口）。"""
    print(json.dumps({"api": api_name, "payload": payload}, ensure_ascii=False), flush=True)


# ------------------------------------------------------------------ 独立入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="write_to_library.py",
        description="write 模式：采集 JSONL -> 「铭衍·元典」数据表（space_api.py 转发）",
    )
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")
    register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "mode", None):
        parser.print_help()
        return EXIT_PARAM
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_PARAM
    return int(handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
