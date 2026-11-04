#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写库层：采集 JSONL -> 「铭衍·元典」数据表（collect.py mode=write，P0）。

契约：register(subparsers) / run(args) -> int（见 collect.py docstring）。
流程：读取 JSONL（status 词表 + validate_article 双闸过滤）-> 解析智库节点
-> create-database 一次建全 25 列（normalize.COLUMN_CONFIGS）-> query-database
按规范化 URL 全量分页去重 -> batch-add-records 分批写入（批间 sleep_polite）。

--import-media：把每条记录的 body_ref 正文 + images_ref 清单里的每张图（以及
media_ref）经 get-upload-credential -> PUT -> import-local-file 上传到库，收集
{record_id, kind, local_path, node_block_id, url} 映射写到 <in>.media-import-map.json；
上传完默认把正文 URL 回填到 body_url 列（body_ref 保留本地路径，二者互补；
--no-backfill-url 可关闭）。凭证有两套模式：drive 返回 confirmKey、cos 返回 cosKey，
两者都要转发（2026-10-24 实测）。中断后重跑按映射文件幂等跳过已传文件。

--dry-run：解析节点后即停止，打印 payload 预览，不调用任何写 API
（create-database / query-database / batch-add-records 均不触发）。

--database-id：复用已有数据表（跳过 create-database 与节点解析，直接去重+写入），
避免重复实跑在云端堆出多张同名表；不传则按 <prefix>-<UTC 时间戳> 新建。

space_api.py 转发约定（2026-10-22 实测，相对口头契约有两处修正）：
  1. `--stdin` 是 store_true 标志，payload 必须经 stdin 传入——作为 argv 元素
     会报 "unexpected argument"（已离线实测）；
  2. error_exit 默认退出码为 0，失败时 stdout 输出 {"error": ...}——成败必须
     解析 error 信封，不能只信 returncode。
顶层仅标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import locale
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    EXIT_COMPLIANCE,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_WARN,
    attest,
    emit_event,
    load_config,
    read_jsonl,
    sleep_polite,
)
from normalize import (  # noqa: E402
    COLUMN_CONFIGS,
    LIBRARY_STATUSES,
    canonicalize_url,
    to_property_values,
    validate_article,
)
import classify as classify_mod  # noqa: E402  分类筛选层（B3）：鉴汇3.0 打分+闸门

_TABLE_ROW_LIMIT = 10000   # 单表行数上限（平台限额，达限告警不静默）
_PAGE_SIZE = 1000          # query-database 去重分页大小
_BATCH_MIN, _BATCH_MAX = 50, 100  # batch_size 合法区间


def _decode(raw: bytes | None) -> str:
    """子进程输出解码：utf-8 优先，失败回退 locale（同机编码一致）。"""
    if not raw:
        return ""
    for encoding in ("utf-8", locale.getpreferredencoding() or "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ space API 转发
def run_space_api(config: dict[str, Any], api_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """经 library skill CLI 转发一次 space API 调用，返回响应 data 字典。

    payload 经 stdin 以 JSON 传给 space_api.py（见模块 docstring 实测约定）；
    returncode != 0、stdout 带 error 信封、或缺 data -> RuntimeError。
    """
    api_cli = str((config.get("library") or {}).get("api_cli") or "")
    if not api_cli:
        raise RuntimeError("config.library.api_cli 未配置（应指向 library skill 的 space_api.py）")
    try:
        proc = subprocess.run(
            [sys.executable, api_cli, api_name, "--stdin"],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"space api {api_name} 调用超时（>60s）") from exc
    except OSError as exc:
        raise RuntimeError(f"space api {api_name} 进程启动失败: {exc}") from exc
    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"space api {api_name} 退出码 {proc.returncode}: "
            f"{(stderr or stdout).strip()[:300]}")
    try:
        body = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"space api {api_name} 返回非 JSON: {(stdout or stderr).strip()[:200]!r}") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"space api {api_name} 响应不是对象: {str(body)[:200]}")
    if body.get("error"):
        raise RuntimeError(f"space api {api_name} 失败: {body['error']}")
    if "data" not in body:
        raise RuntimeError(f"space api {api_name} 响应缺少 data: {str(body)[:200]}")
    return body["data"]


def _space_api(config: dict[str, Any], api_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """space API 统一入口（薄封装，便于自测注入 stub / monkeypatch）。"""
    return run_space_api(config, api_name, payload)


# ------------------------------------------------------------------ 响应形态防御性提取
def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "nodes", "items", "list", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_records(data: Any) -> list[dict]:
    return [item for item in _as_list(data) if isinstance(item, dict)]


def _next_cursor(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("nextCursor", "startCursor", "nextPageCursor", "cursor"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _record_url(row: dict) -> str:
    """从查询行提取 url（兼容 PropertyValue oneof 与裸字符串）。"""
    value = row.get("url")
    if isinstance(value, dict):
        value = value.get("text") or value.get("url") or ""
    elif isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _node_field(node: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = node.get(key)
        if value:
            return str(value).strip()
    return ""


# ------------------------------------------------------------------ 节点 / 表名 / 批次
def _resolve_node_id(config: dict[str, Any], args: argparse.Namespace) -> tuple[str, str]:
    """解析智库节点 id：--library-node > config.library.node_id > search-nodes 按名称。"""
    explicit = (getattr(args, "library_node", "") or "").strip()
    if explicit:
        return explicit, ""
    lib_cfg = config.get("library") or {}
    configured = str(lib_cfg.get("node_id") or "").strip()
    if configured:
        return configured, ""
    node_title = ((getattr(args, "node_title", "") or "").strip()
                  or str(lib_cfg.get("node_title") or "").strip())
    if not node_title:
        return "", "未提供 --library-node / config.library.node_id，且无 node_title 可回退解析"
    try:
        data = _space_api(config, "space.searcher.search-nodes",
                          {"query": node_title, "size": 10})
    except RuntimeError as exc:
        return "", f"search-nodes 调用失败: {exc}"
    nodes = _extract_records(data)
    for node in nodes:
        if _node_field(node, ("name", "title")) == node_title:
            found = _node_field(node, ("nodeId", "node_id", "id"))
            if found:
                return found, ""
    for node in nodes:  # 名称未精确命中：取首个带 id 的结果并告警
        found = _node_field(node, ("nodeId", "node_id", "id"))
        if found:
            emit_event(LEVEL_WARN, "write.node_fuzzy", expected=node_title,
                       got=_node_field(node, ("name", "title")), node_id=found)
            return found, ""
    return "", f"search-nodes 未找到节点（query={node_title!r}, results={len(nodes)}）"


def _default_db_name(lib_cfg: dict[str, Any]) -> str:
    prefix = str(lib_cfg.get("database_name_prefix") or "公众号采集归档")
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"


def _clamp_batch(value: Any, lib_cfg: dict[str, Any]) -> int:
    raw = value if value is not None else lib_cfg.get("batch_size", 50)
    try:
        size = int(raw)
    except (TypeError, ValueError):
        size = 50
    if size < _BATCH_MIN:
        emit_event(LEVEL_WARN, "write.batch_size_clamped", requested=size, used=_BATCH_MIN)
        return _BATCH_MIN
    if size > _BATCH_MAX:
        emit_event(LEVEL_WARN, "write.batch_size_clamped", requested=size, used=_BATCH_MAX)
        return _BATCH_MAX
    return size


def _url_key(record: dict) -> str:
    return canonicalize_url(record.get("url", "")) or str(record.get("url") or "")


def _fetch_existing_index(config: dict[str, Any], database_id: str,
                          full: bool = False) -> dict[str, dict]:
    """分页拉全量行，返回 {规范化 url: 原始行}；上限 _TABLE_ROW_LIMIT。

    行里带服务端 `_id`（batch-update-records 的 recordId 就是它，与我们自己的
    `record_id` 列是两回事）。full=True 时拉全部字段（覆盖写要拿旧值判断
    「哪些字段需要清空」），否则只取 url 最小集——实测两种情况下 `_id` 都返回。
    """
    index: dict[str, dict] = {}
    cursor: str | None = None
    while len(index) < _TABLE_ROW_LIMIT:
        payload: dict[str, Any] = {
            "databaseId": database_id,
            "pageSize": _PAGE_SIZE,
        }
        if not full:
            payload["fields"] = ["url"]
        if cursor:
            payload["startCursor"] = cursor
        data = _space_api(config, "space.database.query-database", payload)
        rows = _extract_records(data)
        if not rows:
            break
        for row in rows:
            raw = _record_url(row)
            if raw:
                index[canonicalize_url(raw) or raw] = row
        cursor = _next_cursor(data)
        if not cursor:
            break
    if len(index) >= _TABLE_ROW_LIMIT:
        emit_event(LEVEL_WARN, "write.dedup_truncated", fetched=len(index), limit=_TABLE_ROW_LIMIT)
    return index


def _fetch_existing_urls(config: dict[str, Any], database_id: str) -> set[str]:
    """分页拉全量 url 集合（规范化后比较）；上限 _TABLE_ROW_LIMIT。"""
    return set(_fetch_existing_index(config, database_id))


# ------------------------------------------------------------ 覆盖写（upsert）
# batch-update-records 元素形状（2026-10-24 实测反推；manifest 只给 `[]BatchUpdateRecord`
# 未给类型定义，故用服务端报错逐层逼出）：
#   {"recordId": <服务端 _id>, "properties": {字段名: {"text"/"number"/"date"/"select": 值}}}
# 实测要点：
#   ① 键名是 recordId / properties（不是 fields / values——后两者报 "properties is empty"）；
#   ② properties 为空时报 "properties is empty, at least one field is required"；
#   ③ 传不存在的 recordId 会整请求硬失败（code=50000 failedIDs），故只能传真实 _id；
#   ④ 清空字段用 {"text": ""}（实测有效）——与 to_property_values 的「空值省略」不同；
#   ⑤ 回报是逐条 results 信封，单条 schema 问题时整批仍 200，必须逐条解析 success。
_UPDATABLE_FIELDS = (
    "record_id", "title", "account", "account_id", "author", "publish_time",
    "collected_at", "media_type", "collect_layer", "status", "url", "cover_url",
    # 注意：body_url 不在本集合内——它不是采集字段，只由 --import-media 回填写入。
    # 若放进来，新采集记录没有该字段 ⇒ 覆盖更新时会被判为「空值需清空」，把已归档的
    # 库内正文链接抹掉（实测会踩）。故它只能由回填路径写，永不自动清空。
    "video_url", "digest", "body_ref", "images_ref", "videos_ref", "keyword_tags",
    "license", "extractor", "fidelity",
    # 分类筛选层（B3）：覆盖更新时也要能刷新分类结论
    "topic_l1", "topic_l2", "industry", "applicability",
    "classify_conf", "classify_basis", "classify_source",
)


def _update_properties(record: dict[str, Any], old_row: dict[str, Any],
                       fields: tuple[str, ...] | None = None) -> dict[str, Any]:
    """构造覆盖写的 properties：新值覆盖 + 新记录里为空的字段显式清空。

    to_property_values 会省略空串（oneof 禁写 null），直接拿它做更新会出现
    「新记录 author 为空、库里旧值 '湖南' 却被原样保留」。所以这里对「旧行有值、
    新记录无值」的字段补 {"text": ""} 显式清空，才是真正的覆盖语义。

    fields 非空时只碰这些列（--update-fields 部分更新）：未列出的列既不覆盖
    也不清空，原样保留。
    """
    wanted = set(fields) if fields else None
    props = to_property_values(record)
    if wanted is not None:
        props = {key: value for key, value in props.items() if key in wanted}
    for field in _UPDATABLE_FIELDS:
        if wanted is not None and field not in wanted:
            continue
        if field in props:
            continue
        if old_row.get(field):
            props[field] = {"text": ""}
    return props


def _parse_update_fields(raw: str, valid_names: set[str]) -> tuple[list[str], str]:
    """解析 --update-fields（逗号分隔列名）；返回 (字段列表, 错误信息)。

    列名必须命中建表时的 25 列，拼错就报 EXIT_PARAM——静默忽略会让用户以为
    更新了其实没更新，比直接报错更糟。
    """
    raw = (raw or "").strip()
    if not raw:
        return [], ""
    fields: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        if name not in valid_names:
            return [], f"未知列名: {name}"
        if name not in fields:
            fields.append(name)
    if not fields:
        return [], "--update-fields 未解析出有效列名"
    return fields, ""


def _batch_update_records(config: dict[str, Any], database_id: str,
                          pairs: list[tuple[str, dict]], batch_size: int) -> tuple[int, int]:
    """分批调用 batch-update-records；pairs = [(服务端 _id, properties)]。

    返回 (成功条数, 失败条数)。逐条解析 results 信封归因，不只看有没有抛异常。
    """
    updated = 0
    failed = 0
    total = (len(pairs) + batch_size - 1) // batch_size
    for index, start in enumerate(range(0, len(pairs), batch_size)):
        chunk = pairs[start:start + batch_size]
        if index:
            sleep_polite(config)
        try:
            data = _space_api(config, "space.database.batch-update-records", {
                "databaseId": database_id,
                "records": [{"recordId": rid, "properties": props} for rid, props in chunk],
            })
        except RuntimeError as exc:
            failed += len(chunk)
            emit_event(LEVEL_ERROR, "write.update_batch_failed", index=index + 1,
                       size=len(chunk), error=str(exc))
            continue
        by_index = {row.get("index"): row for row in (data.get("results") or [])
                    if isinstance(row, dict)}
        for offset, (rid, _props) in enumerate(chunk):
            row = by_index.get(offset)
            if row and row.get("success"):
                updated += 1
                emit_event(LEVEL_INFO, "write.updated", record_id=rid)
            else:
                failed += 1
                emit_event(LEVEL_ERROR, "write.update_failed", record_id=rid,
                           error=str((row or {}).get("error") or "响应缺少对应 results 项"))
        print(f"[write] 更新批次 {index + 1}/{total}: {len(chunk)} 条", flush=True)
    return updated, failed


# ------------------------------------------------------------------ 媒体上传
def _upload_one(config: dict[str, Any], local: Path, parent_id: str) -> dict[str, Any]:
    """单个文件上传流：get-upload-credential -> PUT -> import-local-file。"""
    file_size = local.stat().st_size
    cred_payload: dict[str, Any] = {"fileName": local.name, "fileSize": file_size}
    if parent_id:
        cred_payload["parentId"] = parent_id
    cred = _space_api(config, "space.importer.get-upload-credential", cred_payload)
    upload_url = str(cred.get("uploadUrl") or "")
    if not upload_url:
        raise RuntimeError("get-upload-credential 未返回 uploadUrl")
    headers = {
        str(key): str(value)
        for key, value in (cred.get("headers") or {}).items()
        if str(key).lower() not in ("content-length", "host")
    }
    request = urllib.request.Request(upload_url, data=local.read_bytes(),
                                     method="PUT", headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        response.read()
    payload: dict[str, Any] = {
        "fileName": local.name,
        "fileSize": file_size,
        "title": local.stem,
    }
    if parent_id:
        payload["parentId"] = parent_id
    # 凭证有两套模式（2026-10-24 实测）：uploadType=drive 返回 confirmKey+headers，
    # uploadType=cos 只返回 cosKey（没有 confirmKey）。只转发 confirmKey 会让 cos
    # 模式两手空空，服务端报「cos_key、confirm_key 与文件字节不能同时为空」。
    if cred.get("cosKey"):
        payload["cosKey"] = cred["cosKey"]
    if cred.get("confirmKey"):
        payload["confirmKey"] = cred["confirmKey"]
    if cred.get("taskId"):
        payload["taskId"] = cred["taskId"]
    return _space_api(config, "space.importer.import-local-file", payload)


def _sha256(local: Path) -> str:
    """文件内容哈希，用于跨目录幂等判定（重采换了目录也能认出同一张图）。"""
    digest = hashlib.sha256()
    digest.update(local.read_bytes())
    return digest.hexdigest()


def _media_files(record: dict[str, Any]) -> list[tuple[str, Path]]:
    """收集一条记录要上传的本地文件：正文 HTML + 图片清单里的每张图。

    images_ref 是 {"images":[{"url","local_path"}], "videos":[...]} 清单，真正的
    图片落在 local_path 指向的文件里。只传清单 json 不传图不算「自包含归档」，
    故这里把清单展开成逐张图片一并上传。
    """
    files: list[tuple[str, Path]] = []
    for kind, ref in (("body", record.get("body_ref")), ("media", record.get("media_ref"))):
        if ref:
            files.append((kind, Path(str(ref))))
    manifest = record.get("images_ref")
    if manifest:
        try:
            data = json.loads(Path(str(manifest)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            for item in data.get("images") or []:
                local = str((item or {}).get("local_path") or "").strip()
                if local:
                    files.append(("image", Path(local)))
    return files


def _default_media_map(in_path: Path, database_id: str) -> str:
    """归档索引默认路径——**按数据表共享**，而非按输入文件名。

    早先是 `<in>.media-import-map.json`：换一个 --in（新批次采集）就等于丢掉全部
    历史归档记录，同一批已上传的图会被再传一遍，在库里堆出重复副本。改为按
    database 共享一份索引后，任意批次重采都能认出「这张图已经传过了」。
    复用表（--database-id）时才有稳定 id，否则退回按输入文件名。
    """
    if database_id:
        return str(in_path.parent / f"media-archive-{database_id}.json")
    return str(in_path) + ".media-import-map.json"


def _import_media(config: dict[str, Any], node_id: str,
                  records: list[dict], map_path: Path) -> tuple[int, int, str]:
    """上传正文/媒体/图片并输出映射；单文件失败不中断整体。

    幂等：按「内容」而非路径判定——映射里已有相同 (record_id, kind, sha256) 就跳过。
    重采会落到新的 media 目录（如 e2e_test.media），若按 local_path 判定会把同一批
    已上传的图再传一遍，在库里堆出重复副本；按内容哈希则能正确识别「还是那张图」。
    旧映射条目没有 sha256 字段，退回按 local_path 判定，兼容不失效。
    """
    map_path = str(map_path)
    done: set[tuple[Any, Any, Any]] = set()
    previous: list[dict] = []
    if Path(map_path).is_file():
        try:
            loaded = json.loads(Path(map_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, list):
            previous = loaded
            for item in loaded:
                if not isinstance(item, dict):
                    continue
                key = item.get("sha256") or item.get("local_path")
                done.add((item.get("record_id"), item.get("kind"), key))

    entries: list[dict[str, Any]] = []
    ok_count = fail_count = 0
    skipped = 0
    for record in records:
        record_id = record.get("record_id")
        for kind, local in _media_files(record):
            if not local.is_file():
                emit_event(LEVEL_WARN, "write.media_missing", record_id=record_id,
                           kind=kind, path=str(local))
                fail_count += 1
                continue
            digest = _sha256(local)
            if (record_id, kind, digest) in done or (record_id, kind, str(local)) in done:
                skipped += 1
                continue
            try:
                result = _upload_one(config, local, node_id)
            except Exception as exc:  # 单文件失败记 partial，不中断
                emit_event(LEVEL_WARN, "write.media_failed", record_id=record_id,
                           kind=kind, path=str(local), error=str(exc))
                fail_count += 1
                continue
            entries.append({
                "record_id": record_id,
                "kind": kind,
                "local_path": str(local),
                "sha256": digest,
                "node_block_id": result.get("nodeBlockId"),
                "url": result.get("url"),
            })
            ok_count += 1
    Path(map_path).write_text(json.dumps(previous + entries, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    emit_event(LEVEL_INFO, "write.media_import_done", ok=ok_count, fail=fail_count,
               skipped=skipped, map=map_path)
    return ok_count, fail_count, map_path


def _backfill_body_url(config: dict[str, Any], database_id: str,
                       records: list[dict], entries: list[dict],
                       batch_size: int) -> tuple[int, int]:
    """把上传得到的正文 URL 回写到 body_url 列（body_ref 保留本地路径）。

    这是「自包含归档」的最后一环：文件进了库，行里还要能跳到它。需要服务端
    `_id`，故重新查一次索引（新建记录此时已入库，能和已有记录一视同仁）。
    """
    body_urls = {
        entry.get("record_id"): entry.get("url")
        for entry in entries
        if isinstance(entry, dict) and entry.get("kind") == "body" and entry.get("url")
    }
    if not body_urls:
        return 0, 0
    try:
        index = _fetch_existing_index(config, database_id)
    except RuntimeError as exc:
        emit_event(LEVEL_WARN, "write.backfill_index_failed", error=str(exc))
        return 0, 0
    pairs: list[tuple[str, dict]] = []
    for record in records:
        url = body_urls.get(record.get("record_id"))
        if not url:
            continue
        server_id = str((index.get(_url_key(record)) or {}).get("_id") or "").strip()
        if not server_id:
            continue
        pairs.append((server_id, {"body_url": {"text": url}}))
    if not pairs:
        return 0, 0
    return _batch_update_records(config, database_id, pairs, batch_size)


# ------------------------------------------------------------------ dry-run
def _dry_run_report(*, node_id: str, db_name: str, properties: list[dict],
                    valid: list[dict], pending: list[dict], batch_size: int,
                    status_skipped: int, invalid: int, dup_in_input: int,
                    import_media: bool, database_id: str = "",
                    classify_stats: dict | None = None) -> int:
    sample = [to_property_values(record) for record in pending[:2]]
    media_plan: list[dict[str, Any]] = []
    if import_media:
        for record in pending:
            for kind, ref in (("body", record.get("body_ref")), ("media", record.get("media_ref"))):
                if ref:
                    media_plan.append({"record_id": record.get("record_id"),
                                       "kind": kind, "path": str(ref)})
    print("[write] DRY-RUN：不创建数据表、不写入记录、不上传媒体", flush=True)
    if database_id:
        print(f"[write] 数据表         : 复用表 {database_id}（跳过 create-database）", flush=True)
    else:
        print(f"[write] 节点(nodeId)   : {node_id}", flush=True)
        print(f"[write] 数据表名       : {db_name}", flush=True)
    print(f"[write] properties    : {len(properties)} 列"
          f"（前 3：{', '.join(p['name'] for p in properties[:3])} ...）", flush=True)
    print(f"[write] 待写记录       : {len(valid)} 条"
          f"（status 词表跳过 {status_skipped}，校验失败 {invalid}）", flush=True)
    if classify_stats:
        print(f"[write] 分类筛选       : 自动 {classify_stats.get('auto', 0)} / "
              f"待核 {classify_stats.get('auto_check', 0)} / "
              f"待归类 {classify_stats.get('draft', 0)} / "
              f"离域拦截 {classify_stats.get('off_domain', 0)}", flush=True)
    print(f"[write] 去重后         : {len(pending)} 条（输入内重复 {dup_in_input}）", flush=True)
    print(f"[write] 批大小         : {batch_size}", flush=True)
    if import_media:
        print(f"[write] 拟上传媒体     : {len(media_plan)} 个文件", flush=True)
    print("[write] to_property_values 示例（前 2 条）:", flush=True)
    for index, values in enumerate(sample, 1):
        print(f"[write]   #{index} {json.dumps(values, ensure_ascii=False)}", flush=True)
    emit_event(LEVEL_INFO, "write.dry_run", node_id=node_id, database_name=db_name,
               database_id=database_id or None, reuse=bool(database_id),
               properties=len(properties),
               property_names=[p["name"] for p in properties[:3]],
               valid=len(valid), pending=len(pending), status_skipped=status_skipped,
               invalid=invalid, dup_in_input=dup_in_input, batch_size=batch_size,
               classify=classify_stats or None,
               sample=sample, media_plan=media_plan or None)
    return EXIT_OK


# ------------------------------------------------------------------ 入口
def register(subparsers) -> None:
    parser = subparsers.add_parser("write", help="写库：采集 JSONL -> 资料库数据表（建表+去重+分批写入）")
    # --config/--yes 同时在子命令层可写（collect.py 顶层已定义，此处 SUPPRESS 不覆盖）
    parser.add_argument("--config", default=argparse.SUPPRESS, help="YAML 配置路径")
    parser.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="合规闸：确认已获授权")
    parser.add_argument("--in", dest="in_path", required=True,
                        help="采集产出的 JSONL 路径（必填）")
    parser.add_argument("--library-node", default="",
                        help="智库节点 id（优先于 config.library.node_id）")
    parser.add_argument("--node-title", default="",
                        help="节点名称（回退解析用，默认 config.library.node_title）")
    parser.add_argument("--space", default="",
                        help="空间名称（保留参数：MVP 未用于 API 调用）")
    parser.add_argument("--database-name", default="",
                        help="数据表名（默认 <database_name_prefix>-<UTC yyyymmddTHHMMSS>）")
    parser.add_argument("--database-id", default="",
                        help="复用已有数据表（跳过 create-database 与节点解析）；不传则新建表")
    parser.add_argument("--batch-size", type=int, default=None,
                        help=f"每批写入条数（默认 config，合法区间 {_BATCH_MIN}-{_BATCH_MAX}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将发送的 payload，不调任何写 API")
    parser.add_argument("--update-existing", action="store_true",
                        help="URL 已存在时按新记录覆盖更新（batch-update-records）；"
                             "默认只跳过。新记录为空的字段会被显式清空")
    parser.add_argument("--update-fields", default="",
                        help="只更新指定列（逗号分隔，如 author,digest）；隐含"
                             "--update-existing，未列出的列原样不动（不覆盖也不清空）")
    parser.add_argument("--import-media", action="store_true",
                        help="上传正文/媒体/图片到库并输出映射；默认把正文 URL 回填 body_url")
    parser.add_argument("--no-backfill-url", action="store_true",
                        help="上传后不回填 body_url 列（默认会回填，使记录能跳转库内归档）")
    parser.add_argument("--no-classify", action="store_true",
                        help="跳过分类筛选（不推荐：离域文章也会被写进库）")
    parser.add_argument("--vault", action="store_true",
                        help="B4 双写：写云端同时双写本地 vault（默认关；config vault.enabled=true 可常驻开启）")
    parser.add_argument("--classify-threshold", type=float, default=0.85,
                        help="自动采纳置信度下限（默认 0.85，与鉴汇3.0 一致）")
    parser.add_argument("--media-map", default="",
                        help="归档索引路径（默认按数据表共享 out/media-archive-<database-id>.json，"
                             "跨批次自动去重；显式指定可覆盖）")
    parser.set_defaults(func=run)


def _do_vault_dual_write(config: dict[str, Any], args: argparse.Namespace,
                         records: list[dict], in_path: str) -> None:
    """B4 vault 双写（常驻流水线的一部分）。best-effort：任何异常仅告警，绝不阻断云端写库。

    复用 B3 已算好的分类结论（record 上的 topic_l1/l2/conf/source），不重算。
    """
    vault_cfg = config.get("vault") or {}
    vault_enabled = bool(getattr(args, "vault", False)) or bool(vault_cfg.get("enabled"))
    if not vault_enabled:
        return
    vault_root = str(vault_cfg.get("root") or "").strip()
    if not vault_root:
        emit_event(LEVEL_WARN, "write.vault_skipped", reason="vault.root 未配置")
        print("[write] vault 双写跳过: vault.root 未配置", flush=True)
        return
    # 显式 --vault 即真实落盘；仅 config 常驻开启时受 auto_apply 约束
    apply = bool(getattr(args, "vault", False)) or bool(vault_cfg.get("auto_apply", True))
    try:
        from vault_writer import sync as vault_sync  # 局部导入：未启用双写时不付出导入成本
        vok, vskip, voff = vault_sync(
            records=records,
            vault_root=vault_root,
            in_path=in_path,
            apply=apply,
            ruleset=None,  # B3 已分类，直接复用 record 上的 topic_l1/l2/conf/source
            source_tool="wechat-article-collector/write_to_library.py",
        )
        emit_event(LEVEL_INFO, "write.vault_dual_write", ok=vok, skipped=vskip, off_domain=voff)
        print(f"[write] vault 双写: 新增 {vok} 条，跳过 {vskip} 条，离域 {voff} 条", flush=True)
    except Exception as exc:  # 双写失败不能影响已成功的云端写库
        emit_event(LEVEL_WARN, "write.vault_failed", error=str(exc))
        print(f"[write] vault 双写失败（不影响云端写库）: {exc}", flush=True)


def run(args: argparse.Namespace) -> int:
    config = load_config(getattr(args, "config", None))
    lib_cfg = config.get("library") or {}

    in_path = Path(str(getattr(args, "in_path", "") or ""))
    if not in_path.is_file():
        emit_event(LEVEL_PARAM, "write.input_missing", path=str(in_path))
        return EXIT_PARAM

    # 1. 读取 + 双闸过滤（status 词表 + validate_article）
    raw_records = list(read_jsonl(str(in_path)))
    status_skipped = 0
    candidates: list[dict] = []
    for record in raw_records:
        if record.get("status") not in LIBRARY_STATUSES:
            status_skipped += 1
            emit_event(LEVEL_WARN, "write.skip_status", record_id=record.get("record_id"),
                       status=record.get("status"))
            continue
        candidates.append(record)
    valid: list[dict] = []
    invalid = 0
    for record in candidates:
        status, reasons = validate_article(record)
        if status == "fail":
            invalid += 1
            emit_event(LEVEL_WARN, "write.skip_invalid", record_id=record.get("record_id"),
                       reasons=reasons)
            continue
        if status == "partial" and record.get("status") != "partial":
            record["status"] = "partial"
            emit_event(LEVEL_INFO, "write.status_partial", record_id=record.get("record_id"),
                       reasons=reasons)
        valid.append(record)
    if not valid:
        emit_event(LEVEL_PARAM, "write.no_valid_records", input=str(in_path),
                   total=len(raw_records), status_skipped=status_skipped, invalid=invalid)
        return EXIT_PARAM

    # 1.5 分类筛选（B3）：把鉴汇3.0 判据接进写库前。
    # 离域(OUT) -> 不写库但记事件与原因（绝不静默丢弃）；tier0 -> 照写但标 draft
    # （待归类，可回溯）；tier1/2 -> 带分类落库。规则缺失时降级为不分类并告警，
    # 不让一次规则文件缺失把整条写库链路打挂。
    classify_stats: dict[str, int] = {"auto": 0, "auto_check": 0, "draft": 0, "off_domain": 0}
    if not getattr(args, "no_classify", False):
        try:
            ruleset = classify_mod.load_rules()
        except (OSError, ValueError) as exc:
            emit_event(LEVEL_WARN, "write.classify_unavailable", error=str(exc))
            ruleset = None
        if ruleset:
            threshold = float(getattr(args, "classify_threshold", 0.85))
            kept_records: list[dict] = []
            for record in valid:
                res = classify_mod.classify_article(record, ruleset, threshold)
                record.update({
                    "topic_l1": res["l1"], "topic_l2": res["l2"],
                    "industry": res["industry"], "applicability": res["applicability"],
                    "classify_conf": res["confidence"], "classify_basis": res["basis"],
                    "classify_source": res["classify_source"],
                })
                if not record.get("keyword_tags"):
                    record["keyword_tags"] = res["tags"]
                if res["tier"] is None:
                    classify_stats["off_domain"] += 1
                    emit_event(LEVEL_INFO, "write.skip_off_domain",
                               record_id=record.get("record_id"),
                               term=res["off_domain"], basis=res["basis"])
                    print(f"[write] 离域拦截: {(record.get('title') or '')[:30]}"
                          f" ← {res['off_domain']}", flush=True)
                    continue
                key = "auto" if res["tier"] == 1 else "auto_check" if res["tier"] == 2 else "draft"
                classify_stats[key] += 1
                kept_records.append(record)
            valid = kept_records
    else:
        emit_event(LEVEL_WARN, "write.classify_disabled")

    if not valid:
        emit_event(LEVEL_INFO, "write.all_filtered",
                   off_domain=classify_stats["off_domain"], total=len(raw_records))
        print(f"[write] 全部被筛掉（离域 {classify_stats['off_domain']} 条），无记录写入",
              flush=True)
        return EXIT_OK

    # 2. 解析节点（复用已有表时跳过：复用模式不需要 parentId，而节点 id 最难获取）
    database_id = str(getattr(args, "database_id", "") or "").strip()
    node_id = ""
    if not database_id:
        node_id, reason = _resolve_node_id(config, args)
        if not node_id:
            emit_event(LEVEL_PARAM, "write.node_unresolved", reason=reason)
            return EXIT_PARAM

    db_name = (getattr(args, "database_name", "") or "").strip() or _default_db_name(lib_cfg)
    batch_size = _clamp_batch(getattr(args, "batch_size", None), lib_cfg)
    properties = [{"name": name, "config": cfg} for name, cfg in COLUMN_CONFIGS]

    # 输入内按规范化 URL 去重（保留首条）
    seen_urls: set[str] = set()
    pending: list[dict] = []
    dup_in_input = 0
    for record in valid:
        key = _url_key(record)
        if key in seen_urls:
            dup_in_input += 1
            emit_event(LEVEL_WARN, "write.skip_dup_input", record_id=record.get("record_id"),
                       url=key)
            continue
        seen_urls.add(key)
        pending.append(record)

    if getattr(args, "dry_run", False):
        return _dry_run_report(node_id=node_id, db_name=db_name, properties=properties,
                               valid=valid, pending=pending, batch_size=batch_size,
                               status_skipped=status_skipped, invalid=invalid,
                               dup_in_input=dup_in_input,
                               import_media=bool(getattr(args, "import_media", False)),
                               database_id=database_id, classify_stats=classify_stats)

    # 3. 建表（一次建全 25 列）或复用已有表（--database-id）
    db_url = ""
    if database_id:
        emit_event(LEVEL_INFO, "write.database_reused", database_id=database_id)
        print(f"[write] 复用已有数据表: {database_id}", flush=True)
    else:
        try:
            created = _space_api(config, "space.database.create-database", {
                "title": db_name,
                "parentId": node_id,
                "properties": properties,
            })
        except RuntimeError as exc:
            emit_event(LEVEL_ERROR, "write.create_database_failed", error=str(exc),
                       database_name=db_name)
            return EXIT_ERROR
        database_id = str(created.get("id") or created.get("databaseId") or "").strip()
        if not database_id:
            emit_event(LEVEL_ERROR, "write.create_database_failed",
                       reason="响应缺少 databaseId", response=str(created)[:200])
            return EXIT_ERROR
        db_url = str(created.get("url") or "")
        print(f"[write] 数据表已创建: {database_id} {db_url}".rstrip(), flush=True)
        emit_event(LEVEL_INFO, "write.database_created", database_id=database_id,
                   title=db_name, url=db_url, columns=len(properties))

    # 4. 与服务端全量 url 差减去重（--update-existing / --update-fields 时改为覆盖更新）
    update_mode = bool(getattr(args, "update_existing", False))
    update_fields: list[str] = []
    raw_fields = str(getattr(args, "update_fields", "") or "").strip()
    if raw_fields:
        update_fields, err = _parse_update_fields(
            raw_fields, {name for name, _cfg in COLUMN_CONFIGS})
        if err:
            emit_event(LEVEL_PARAM, "write.update_fields_invalid",
                       value=raw_fields, reason=err)
            return EXIT_PARAM
        update_mode = True  # --update-fields 隐含覆盖更新
        print(f"[write] 部分更新: 仅作用于列 {', '.join(update_fields)}", flush=True)
    try:
        existing = _fetch_existing_index(config, database_id, full=update_mode)
    except RuntimeError as exc:
        emit_event(LEVEL_ERROR, "write.dedup_failed", error=str(exc), database_id=database_id)
        return EXIT_ERROR
    dups = [record for record in pending if _url_key(record) in existing]
    to_write = [record for record in pending if _url_key(record) not in existing]
    dup_skipped = len(dups)

    updated = 0
    update_failed = 0
    if dups and update_mode:
        field_filter = tuple(update_fields) or None
        pairs: list[tuple[str, dict]] = []
        for record in dups:
            old_row = existing[_url_key(record)]
            server_id = str(old_row.get("_id") or "").strip()
            if not server_id:
                update_failed += 1
                emit_event(LEVEL_ERROR, "write.update_failed",
                           record_id=record.get("record_id"), error="旧行缺少服务端 _id")
                continue
            pairs.append((server_id, _update_properties(record, old_row, field_filter)))
        if pairs:
            updated, update_failed = _batch_update_records(config, database_id,
                                                           pairs, batch_size)
            print(f"[write] 覆盖更新: 成功 {updated} 条，失败 {update_failed} 条", flush=True)
    elif dup_skipped:
        emit_event(LEVEL_INFO, "write.skip_dup", count=dup_skipped, database_id=database_id)
        print(f"[write] 去重跳过: {dup_skipped} 条 URL 已存在"
              f"（加 --update-existing 可覆盖更新）", flush=True)

    # 5. 媒体上传（可选；不回填记录）——新增与被覆盖更新的记录都要传，
    #    否则「全是已存在记录」时 --import-media 会空跑。
    media_fail = 0
    media_map_path = ""
    targets: list[dict] = []
    if getattr(args, "import_media", False):
        targets = list(to_write) + (list(dups) if update_mode else [])
        if targets:
            if not node_id:
                # 复用表模式跳过了节点解析，但上传要挂到智库节点下，否则落到空间根目录
                node_id, reason = _resolve_node_id(config, args)
                if not node_id:
                    emit_event(LEVEL_WARN, "write.media_parent_unresolved", reason=reason)
            media_map = Path(str(getattr(args, "media_map", "") or "").strip()
                             or _default_media_map(in_path, database_id))
            if media_map.parent != Path(""):
                media_map.parent.mkdir(parents=True, exist_ok=True)
            _, media_fail, media_map_path = _import_media(config, node_id, targets, media_map)
            print(f"[write] 媒体导入映射: {media_map_path}", flush=True)
            # 注意：body_url 回填不能在这里做——此时「新增记录」还没写入服务端，
            # 拿不到 _id，回填会静默失效（实测踩过）。统一推迟到写入之后（步骤 7）。

    def _do_backfill() -> None:
        """回填 body_url 到已入库的记录（新增的必须先写入才有 _id）。"""
        nonlocal update_failed
        if not (media_map_path and targets) or getattr(args, "no_backfill_url", False):
            return
        try:
            entries = json.loads(Path(media_map_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = []
        if not (isinstance(entries, list) and entries):
            return
        url_ok, url_fail = _backfill_body_url(
            config, database_id, targets, entries, batch_size)
        if url_ok or url_fail:
            print(f"[write] body_url 回填: 成功 {url_ok} 条，失败 {url_fail} 条", flush=True)
            update_failed += url_fail

    if not to_write:
        # 全是已存在记录（没有新增）时不会走到步骤 7，必须在这里也回填一次
        _do_backfill()
        emit_event(LEVEL_INFO, "write.done", database_id=database_id, written=0,
                   updated=updated, update_failed=update_failed,
                   skipped_dup=dup_skipped, skipped_invalid=invalid,
                   status_skipped=status_skipped, media_failed=media_fail)
        print(f"[write] 没有需要新增的记录（覆盖更新 {updated} 条）", flush=True)
        if invalid or update_failed or media_fail:
            return EXIT_PARTIAL
        return EXIT_OK
    if len(to_write) > _TABLE_ROW_LIMIT:
        emit_event(LEVEL_WARN, "write.table_limit", count=len(to_write),
                   limit=_TABLE_ROW_LIMIT)

    # 5. 分批写入（单批失败即中止，不静默）
    written = 0
    total_batches = (len(to_write) + batch_size - 1) // batch_size
    for index, start in enumerate(range(0, len(to_write), batch_size)):
        batch = to_write[start:start + batch_size]
        payload = {
            "databaseId": database_id,
            "records": [to_property_values(record) for record in batch],
        }
        if index:
            sleep_polite(config)
        try:
            _space_api(config, "space.database.batch-add-records", payload)
        except RuntimeError as exc:
            emit_event(LEVEL_ERROR, "write.batch_failed", index=index + 1,
                       size=len(batch), error=str(exc))
            return EXIT_ERROR
        written += len(batch)
        print(f"[write] 批次 {index + 1}/{total_batches}: 写入 {len(batch)} 条", flush=True)

    # 6. vault 双写（B4，常驻流水线，best-effort：失败不影响云端写库）
    _do_vault_dual_write(config, args, to_write, str(in_path))

    # 7. 回填 body_url（自包含归档的最后一环）
    #    必须在写入之后：新记录此刻才有服务端 _id，否则回填静默失效。
    _do_backfill()

    emit_event(LEVEL_INFO, "write.done", database_id=database_id, written=written,
               updated=updated, update_failed=update_failed,
               skipped_dup=dup_skipped, skipped_invalid=invalid,
               status_skipped=status_skipped, media_failed=media_fail)
    print(f"[write] 完成: 新增 {written} 条、覆盖更新 {updated} 条"
          f"（去重跳过 {dup_skipped}，校验失败 {invalid}，fail 行 {status_skipped}）",
          flush=True)
    if media_fail or update_failed:
        return EXIT_PARTIAL
    if invalid:
        return EXIT_PARTIAL
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None,
                        help="YAML 配置路径（默认内置 DEFAULT_CONFIG，可复制 config.example.yaml）")
    common.add_argument("--yes", action="store_true",
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser = argparse.ArgumentParser(prog="write_to_library.py", description=__doc__,
                                     parents=[common])
    register(parser.add_subparsers(dest="mode", metavar="<mode>"))
    parser.set_defaults(func=None)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_PARAM
    if not attest(args):
        return EXIT_COMPLIANCE
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
