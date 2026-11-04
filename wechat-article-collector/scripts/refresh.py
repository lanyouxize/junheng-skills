#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日自动刷新订阅文章：编排器（最佳档，collect.py mode=refresh）。

把已就绪的采集层（L1 url / L2 account / L3 desktop / exe）与写库层（云端去重增量
+ vault 双写）编排成「每日刷新」能力，并补齐六项用户要求：
  1. 定时任务调度（Windows 计划任务，每日固定时间触发，重启存活、无常驻进程）
  2. 从订阅源拉取最新文章（subscriptions.yaml 列出多源，逐源按 layer 采集）
  3. 去重与增量更新存储（复用 write_to_library 的规范化 URL 差减去重 + vault 幂等；
     稳定 --database-id 保证跨天增量，首跑建表后把 id 存 state.json）
  4. 失败重试与错误日志（每源独立 retry，指数退避；逐层 emit_event JSONL 落盘
     run-<ts>.jsonl + 人类可读 run-<ts>.log）
  5. 运行状态可监控（status.json 累计上次运行时间/成功数/失败源/退出码 + refresh status）
  6. 可配置 / 可手动触发 / 异常告警（subscriptions.yaml 配置；refresh run 手动；
     alerts.log 文件告警 + 可选 webhook POST，error/partial/零产出触发）

设计要点（与既有架构的边界）：
  - 编排器只做「外壳」，不重写任何采集/写库逻辑；每个采集层、写库层均以**子进程**
    隔离调用（collect.py <layer> / collect.py write），单源崩溃不连累整轮。
  - 子进程复用同一份 --config（即 subscriptions.yaml，其内含 library/vault/rate_limit
    覆盖），保证 base 配置一致。
  - 退出码沿用 common.EXIT_*；或略编排级语义。

子命令：
  run [--config X] [--yes] [--vault] [--classify-threshold F] [--since-days N] [--dry-run]
  status [--config X]
  install [--config X] [--time HH:MM] [--dry-run]
  uninstall [--config X]
  selfcheck
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    EXIT_COMPLIANCE,
    EXIT_ERROR,
    EXIT_ENV,
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
    new_id,
    now_iso,
)

try:
    import yaml  # 解析 subscriptions.yaml 的 refresh/subscriptions 块
except ImportError:  # common.load_config 同样依赖，缺失时仅报错在「用到配置」时
    yaml = None

_SCRIPT_DIR = Path(__file__).resolve().parent
_COLLECT_PY = str(_SCRIPT_DIR / "collect.py")

# 仅这些退出码值得重试（瞬时环境/网络/部分失败）；PARAM/COMPLIANCE 重试无意义。
_RETRYABLE = {EXIT_ERROR, EXIT_ENV, EXIT_PARTIAL}

_DEFAULT_OUTPUT_DIR = "out/refresh"
_DEFAULT_TASK_NAME = "WeChatArticleDailyRefresh"
_DEFAULT_SCHEDULE_TIME = "08:00"


# ------------------------------------------------------------------ 运行日志
class RunLogger:
    """并发安全的简单运行日志：编排层事件走 emit_event（stderr），同时落 run-<ts>.jsonl；
    子进程的原始 stderr/stdout 行转发到 stderr + 落盘，便于实时监看与事后审计。"""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self._f = open(log_path, "w", encoding="utf-8")

    def event(self, level: str, event: str, **fields: Any) -> None:
        emit_event(level, event, **fields)  # 机器可读事件 → stderr
        payload = {"ts": now_iso(), "level": level, "event": event, **fields}
        self._f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._f.flush()

    def forward(self, line: str) -> None:
        """转发子进程的一行输出（可能是 JSONL 事件，也可能是 [write] 进度行）。"""
        stripped = line.rstrip("\n")
        if not stripped:
            return
        print(stripped, file=sys.stderr, flush=True)
        self._f.write(stripped + "\n")
        self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except OSError:
            pass


# ------------------------------------------------------------------ 配置
def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_refresh_config(config_path: str | None) -> tuple[dict, dict, list]:
    """加载配置：基础 DEFAULT_CONFIG + subscriptions.yaml 的 library/vault/rate_limit
    覆盖；单独抽出 refresh 块与 subscriptions 列表。

    返回 (config, refresh_block, subscriptions_list)。config 用于子进程 collect.py 的
    --config 透传，refresh_block 控制调度/重试/告警，subscriptions 是订阅源清单。
    """
    config = load_config(None)  # 纯 DEFAULT_CONFIG
    refresh_block: dict = {}
    subscriptions: list = []
    if config_path:
        p = Path(config_path)
        if not p.is_file():
            emit_event(LEVEL_WARN, "refresh.config_missing", path=str(p))
        elif yaml is None:
            emit_event(LEVEL_ERROR, "refresh.yaml_missing",
                       hint="pip install pyyaml")
        else:
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                emit_event(LEVEL_ERROR, "refresh.config_parse_error",
                           path=str(p), error=str(exc))
                raw = {}
            if isinstance(raw, dict):
                for key in ("library", "vault", "rate_limit"):
                    if isinstance(raw.get(key), dict):
                        _deep_merge(config[key], raw[key])
                refresh_block = raw.get("refresh") or {}
                subscriptions = raw.get("subscriptions") or []
    return config, refresh_block, subscriptions


def _default_subs_path() -> str:
    """未显式给 --config 时，回退到技能根的 subscriptions.yaml。"""
    cand = _SCRIPT_DIR.parent / "subscriptions.yaml"
    return str(cand) if cand.is_file() else ""


def _resolve_config(args: argparse.Namespace) -> str:
    cfg = (getattr(args, "config", None) or "").strip()
    if cfg:
        return cfg
    return _default_subs_path()


def _output_dir(refresh_block: dict) -> Path:
    od = (refresh_block.get("output_dir") or _DEFAULT_OUTPUT_DIR).strip()
    # 解析为绝对路径：计划任务由系统以非预期 CWD 拉起，相对路径会失效
    return Path(od).resolve()


def _load_state(state_path: Path) -> dict:
    if state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ 采集层命令
def build_layer_command(py: str, src: dict, out_path: Path, config_path: str) -> list[str]:
    """按源的 layer 拼出 collect.py <layer> 子进程命令。

    已知 layer（url/account/exe）用显式参数；desktop/L3 与任何非常规参数走
    extra_args 透传字符串（保留引号由 shell 解析，简单场景够用）。"""
    layer = str(src.get("layer") or "").strip()
    cmd = [py, _COLLECT_PY, layer, "--yes", "--config", config_path, "--out", str(out_path)]
    if layer == "url":
        if src.get("urls"):
            cmd += ["--urls", str(src["urls"])]
        if src.get("urls_file"):
            cmd += ["--url-file", str(src["urls_file"])]
        if src.get("no_images"):
            cmd += ["--no-images"]
        if src.get("retries") is not None:
            cmd += ["--retries", str(src["retries"])]
    elif layer == "account":
        if not src.get("biz"):
            raise ValueError(f"源 {src.get('name')} layer=account 缺少必填 biz")
        cmd += ["--biz", str(src["biz"])]
        if src.get("cookie_file"):
            cmd += ["--cookie-file", str(src["cookie_file"])]
        if src.get("since"):
            cmd += ["--since", str(src["since"])]
        if src.get("until"):
            cmd += ["--until", str(src["until"])]
        if src.get("limit") is not None:
            cmd += ["--limit", str(src["limit"])]
        if src.get("keyword"):
            cmd += ["--keyword", str(src["keyword"])]
        if src.get("no_images"):
            cmd += ["--no-images"]
    elif layer == "exe":
        if src.get("exe"):
            cmd += ["--exe", str(src["exe"])]
        if src.get("target"):
            cmd += ["--target", str(src["target"])]
        if src.get("targets_file"):
            cmd += ["--targets-file", str(src["targets_file"])]
        if src.get("output_dir"):
            cmd += ["--output-dir", str(src["output_dir"])]
        if src.get("exe_args"):
            cmd += ["--exe-args", str(src["exe_args"])]
    elif layer == "desktop":
        # L3 参数较多且仅环境相关，统一走 extra_args 透传，避免硬编码漂移
        if src.get("plugin"):
            cmd += ["--plugin", str(src["plugin"])]
    else:
        raise ValueError(f"源 {src.get('name')} 未知 layer: {layer!r}（支持 url/account/exe/desktop）")
    if src.get("extra_args"):
        cmd += str(src["extra_args"]).split()
    return cmd


def run_with_retry(cmd: list[str], src: dict, refresh_block: dict,
                   logger: RunLogger) -> tuple[int, int]:
    """带重试执行单条命令。返回 (最终退出码, 实际尝试次数)。

    仅对瞬时类退出码（ERROR/ENV/PARTIAL）重试；PARAM/COMPLIANCE 不重试。
    指数退避：backoff * 2**(attempt-1)。"""
    max_retries = int(refresh_block.get("max_retries", 2))
    backoff = float(refresh_block.get("retry_backoff_seconds", 30))
    name = src.get("name", "?")
    layer = src.get("layer", "?")
    attempt = 0
    last_code = EXIT_ERROR
    timeout = int(refresh_block.get("per_source_timeout", 600))
    while True:
        attempt += 1
        logger.event(LEVEL_INFO, "refresh.source_start", name=name, layer=layer, attempt=attempt)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.event(LEVEL_ERROR, "refresh.source_timeout", name=name, layer=layer,
                         attempt=attempt, timeout=timeout)
            last_code = EXIT_ERROR
            proc = None
        except OSError as exc:
            logger.event(LEVEL_ERROR, "refresh.source_spawn_failed", name=name,
                         layer=layer, error=str(exc))
            last_code = EXIT_ERROR
            proc = None
        if proc is not None:
            last_code = proc.returncode
            for line in (proc.stderr or "").splitlines():
                logger.forward(line)
            for line in (proc.stdout or "").splitlines():
                logger.forward(line)
        if last_code == EXIT_OK:
            logger.event(LEVEL_INFO, "refresh.source_ok", name=name, layer=layer, attempt=attempt)
            break
        if attempt > max_retries or last_code not in _RETRYABLE:
            logger.event(LEVEL_ERROR, "refresh.source_failed", name=name, layer=layer,
                         attempt=attempt, exit_code=last_code)
            break
        wait = backoff * (2 ** (attempt - 1))
        logger.event(LEVEL_WARN, "refresh.source_retry", name=name, layer=layer,
                     attempt=attempt, next_attempt=attempt + 1, backoff=int(wait),
                     exit_code=last_code)
        time.sleep(wait)
    return last_code, attempt


def count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def combine_outputs(files: list[Path], combined_path: Path) -> int:
    """合并多个源 JSONL 为单一 combined 文件（用于写库去重）。返回记录数。"""
    total = 0
    with combined_path.open("w", encoding="utf-8") as out:
        for f in files:
            if not f.is_file():
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.write(line + "\n")
                    total += 1
    return total


# ------------------------------------------------------------------ 写库层
def run_write(config: dict, combined: Path, database_id: str, vault: bool,
              threshold: float, refresh_block: dict, logger: RunLogger,
              config_path: str = "") -> tuple[int, int, str]:
    """调用 collect.py write 写库（去重增量 + 分类 + 可选 vault 双写）。

    返回 (退出码, 新增条数, 实际使用的 database_id)。首跑（database_id 为空）时
    建表并解析返回 id，供后续增量复用。

    关键：必须把 --config 透传给写库子进程，否则子进程只用纯 DEFAULT_CONFIG，
    读不到 subscriptions.yaml 里的 library.node_id / library.node_title，节点解析必失败。"""
    py = sys.executable
    cmd = [py, _COLLECT_PY, "write", "--yes", "--in", str(combined)]
    if config_path:
        cmd += ["--config", config_path]
    if database_id:
        cmd += ["--database-id", database_id]
    if vault:
        cmd += ["--vault"]
    if threshold is not None:
        cmd += ["--classify-threshold", str(threshold)]
    if refresh_block.get("import_media"):
        cmd += ["--import-media"]
    logger.event(LEVEL_INFO, "refresh.write_start", database_id=database_id or None,
                 creating=not bool(database_id))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        logger.event(LEVEL_ERROR, "refresh.write_timeout")
        return EXIT_ERROR, 0, database_id
    except OSError as exc:
        logger.event(LEVEL_ERROR, "refresh.write_spawn_failed", error=str(exc))
        return EXIT_ERROR, 0, database_id
    for line in (proc.stderr or "").splitlines():
        logger.forward(line)
    for line in (proc.stdout or "").splitlines():
        logger.forward(line)
        m = re.search(r"数据表已创建:\s*(\S+)", line)
        if m and not database_id:
            database_id = m.group(1)
    written = 0
    for line in (proc.stdout or "").splitlines():
        m = re.search(r"新增\s*(\d+)\s*条", line)
        if m:
            written = int(m.group(1))
    return proc.returncode, written, database_id


# ------------------------------------------------------------------ 告警
def eval_alert(refresh_block: dict, final_exit: int, total_records: int,
               source_results: list[dict]) -> tuple[bool, list[str]]:
    """评估是否触发告警。返回 (是否触发, 触发原因列表)。"""
    alert_cfg = refresh_block.get("alert") or {}
    if not alert_cfg.get("enabled", True):
        return False, []
    on = set(alert_cfg.get("on", ["error", "partial", "zero_yield"]))
    reasons: list[str] = []
    if final_exit == EXIT_ERROR and "error" in on:
        reasons.append("exit_error")
    if final_exit == EXIT_PARTIAL and "partial" in on:
        reasons.append("partial")
    if total_records == 0 and "zero_yield" in on:
        reasons.append("zero_yield")
    if any(s.get("exit_code") not in (EXIT_OK,) for s in source_results) and "source_failed" in on:
        reasons.append("source_failed")
    return bool(reasons), reasons


def send_alert(refresh_block: dict, status: dict, reasons: list[str], logger: RunLogger) -> bool:
    """写出 alerts.log（始终）+ 可选 webhook POST。返回是否成功写出文件告警。"""
    alert_cfg = refresh_block.get("alert") or {}
    output_dir = _output_dir(refresh_block)
    output_dir.mkdir(parents=True, exist_ok=True)
    alerts_log = output_dir / "alerts.log"
    entry = {
        "ts": now_iso(),
        "reasons": reasons,
        "run_id": status.get("run_id"),
        "exit_code": status.get("exit_code"),
        "total_fetched": status.get("total_fetched"),
        "database_id": status.get("database_id"),
        "sources": status.get("sources"),
    }
    with alerts_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.event(LEVEL_WARN, "refresh.alert_logged", reasons=reasons, path=str(alerts_log))
    webhook = str(alert_cfg.get("webhook_url") or "").strip()
    if webhook:
        try:
            import urllib.request
            req = urllib.request.Request(
                webhook,
                data=json.dumps(entry, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                logger.event(LEVEL_INFO, "refresh.alert_webhook_sent",
                            status=resp.status, reasons=reasons)
        except Exception as exc:  # noqa: BLE001
            logger.event(LEVEL_WARN, "refresh.alert_webhook_failed",
                        error=str(exc), reasons=reasons)
    return True


# ------------------------------------------------------------------ run
def cmd_run(args: argparse.Namespace) -> int:
    if not attest(args):
        return EXIT_COMPLIANCE
    config_path = _resolve_config(args)
    config, refresh_block, subscriptions = load_refresh_config(config_path)
    if not subscriptions:
        emit_event(LEVEL_PARAM, "refresh.no_subscriptions",
                   hint="在 subscriptions.yaml 配置 subscriptions: 列表，或 --config 指向正确文件")
        return EXIT_PARAM

    # --since-days N：自动给所有 account 源注入/覆盖 since（today - N 天）
    since_days = getattr(args, "since_days", None)
    if since_days is not None:
        try:
            n_days = int(since_days)
        except (TypeError, ValueError):
            emit_event(LEVEL_PARAM, "refresh.bad_since_days", value=since_days)
            return EXIT_PARAM
        since_date = (datetime.now() - timedelta(days=n_days)).strftime("%Y-%m-%d")
        injected = 0
        for src in subscriptions:
            if str(src.get("layer") or "").strip() == "account":
                src["since"] = since_date
                injected += 1
        emit_event(LEVEL_INFO, "refresh.since_days_applied",
                   days=n_days, since=since_date, account_sources=injected)

    output_dir = _output_dir(refresh_block)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime_stamp()
    run_log = output_dir / f"run-{ts}.jsonl"
    logger = RunLogger(run_log)
    state_path = output_dir / "state.json"
    state = _load_state(state_path)

    dry_run = bool(getattr(args, "dry_run", False))
    vault = bool(getattr(args, "vault", False)) or bool((config.get("vault") or {}).get("enabled"))
    threshold = float(getattr(args, "classify_threshold", 0.85) or 0.85)

    database_id = (str(refresh_block.get("database_id") or "")
                   or str((config.get("library") or {}).get("database_id") or "")
                   or str(state.get("database_id") or ""))

    logger.event(LEVEL_INFO, "refresh.run_start", run_id=new_id()[:8],
                 sources=len(subscriptions), output_dir=str(output_dir),
                 database_id=database_id or None, dry_run=dry_run)

    if dry_run:
        # 仅构建并打印各源命令 + 写库命令，不执行（验证编排接线）
        for src in subscriptions:
            if not src.get("enabled", True):
                logger.event(LEVEL_INFO, "refresh.source_skipped_disabled", name=src.get("name"))
                continue
            try:
                cmd = build_layer_command(sys.executable, src,
                                          output_dir / f"src-{slug(src.get('name','x'))}-{ts}.jsonl",
                                          config_path or _COLLECT_PY)
            except ValueError as exc:
                logger.event(LEVEL_ERROR, "refresh.build_cmd_failed", error=str(exc))
                continue
            logger.event(LEVEL_INFO, "refresh.dry_cmd", name=src.get("name"),
                         cmd=" ".join(cmd))
        logger.event(LEVEL_INFO, "refresh.dry_done", note="未执行任何采集/写库")
        logger.close()
        return EXIT_OK

    # 1) 逐源采集（子进程隔离 + 重试）
    source_results: list[dict] = []
    collected_files: list[Path] = []
    for src in subscriptions:
        if not src.get("enabled", True):
            logger.event(LEVEL_INFO, "refresh.source_skipped_disabled", name=src.get("name"))
            continue
        name = src.get("name", "?")
        out_path = output_dir / f"src-{slug(name)}-{ts}.jsonl"
        try:
            cmd = build_layer_command(sys.executable, src, out_path, config_path or _COLLECT_PY)
        except ValueError as exc:
            logger.event(LEVEL_ERROR, "refresh.build_cmd_failed", name=name, error=str(exc))
            source_results.append({"name": name, "layer": src.get("layer"),
                                   "exit_code": EXIT_PARAM, "records": 0, "attempts": 0})
            continue
        exit_code, attempts = run_with_retry(cmd, src, refresh_block, logger)
        records = count_jsonl(out_path)
        source_results.append({"name": name, "layer": src.get("layer"),
                               "exit_code": exit_code, "records": records, "attempts": attempts})
        if exit_code == EXIT_OK and records > 0:
            collected_files.append(out_path)

    # 2) 合并
    combined = output_dir / f"combined-{ts}.jsonl"
    total_records = combine_outputs(collected_files, combined)
    logger.event(LEVEL_INFO, "refresh.combined", total=total_records,
                 sources_with_data=len(collected_files))

    # 3) 写库（去重增量 + 分类 + vault 双写）
    written = 0
    if total_records == 0:
        logger.event(LEVEL_WARN, "refresh.zero_yield", note="本轮无任何新记录写入（可能无新文章）")
        write_code = EXIT_OK
    else:
        write_exit, written, database_id = run_write(
            config, combined, database_id, vault, threshold, refresh_block, logger,
            config_path or "")
        if database_id and not state.get("database_id"):
            state["database_id"] = database_id
            _save_state(state_path, state)
            logger.event(LEVEL_INFO, "refresh.state_saved", database_id=database_id)
        write_code = write_exit

    # 4) 汇总退出码
    source_failed = any(s["exit_code"] not in (EXIT_OK,) for s in source_results)
    if write_code == EXIT_ERROR:
        final_exit = EXIT_ERROR
    elif write_code == EXIT_PARTIAL or source_failed:
        final_exit = EXIT_PARTIAL
    else:
        final_exit = EXIT_OK

    # 5) 状态文件
    status = {
        "run_id": new_id(),
        "started_at": logger_started(),
        "finished_at": now_iso(),
        "exit_code": final_exit,
        "total_fetched": total_records,
        "written": written,
        "database_id": database_id or None,
        "sources": source_results,
        "run_log": str(run_log),
    }
    status_path = output_dir / "status.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 告警
    triggered, reasons = eval_alert(refresh_block, final_exit, total_records, source_results)
    if triggered:
        send_alert(refresh_block, status, reasons, logger)

    logger.event(LEVEL_INFO, "refresh.run_done", exit_code=final_exit,
                 total_fetched=total_records, written=written,
                 alerted=triggered, reasons=reasons, status=str(status_path))
    logger.close()
    return final_exit


# ------------------------------------------------------------------ status
def cmd_status(args: argparse.Namespace) -> int:
    _, refresh_block, _ = load_refresh_config(_resolve_config(args))
    output_dir = _output_dir(refresh_block)
    status_path = output_dir / "status.json"
    if not status_path.is_file():
        emit_event(LEVEL_INFO, "refresh.status_none", path=str(status_path))
        print("尚无运行记录（先执行 collect.py refresh run）。", flush=True)
        return EXIT_OK
    status = json.loads(status_path.read_text(encoding="utf-8"))
    print("=== 上次运行状态 ===", flush=True)
    print(f"  运行ID     : {status.get('run_id')}", flush=True)
    print(f"  完成时间   : {status.get('finished_at')}", flush=True)
    print(f"  退出码     : {status.get('exit_code')}", flush=True)
    print(f"  拉取记录   : {status.get('total_fetched')}", flush=True)
    print(f"  写入记录   : {status.get('written')}", flush=True)
    print(f"  数据表ID   : {status.get('database_id')}", flush=True)
    print(f"  运行日志   : {status.get('run_log')}", flush=True)
    print("  各源:", flush=True)
    for s in status.get("sources") or []:
        print(f"    - {s.get('name')} [{s.get('layer')}] 退出={s.get('exit_code')} "
              f"记录={s.get('records')} 尝试={s.get('attempts')}", flush=True)
    return EXIT_OK


# ------------------------------------------------------------------ 调度（Windows 计划任务）
def _build_bat(collect_py: str, config_path: str, output_dir: Path) -> Path:
    """生成 run-refresh.bat（绝对路径，规避 schtasks 嵌套引号问题）。"""
    output_dir = output_dir.resolve()
    bat_path = output_dir / "run-refresh.bat"
    py = sys.executable
    cfg = Path(config_path).resolve()
    out = output_dir.resolve()
    lines = [
        "@echo off",
        f'"{py}" "{collect_py}" refresh run --yes --config "{cfg}" >> "{out / "last-run.log"}" 2>&1',
    ]
    bat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bat_path


def cmd_install(args: argparse.Namespace) -> int:
    config_path = _resolve_config(args)
    _, refresh_block, _ = load_refresh_config(config_path)
    sched = refresh_block.get("schedule") or {}
    task_name = str(sched.get("task_name") or _DEFAULT_TASK_NAME)
    sched_time = str(getattr(args, "time", None) or sched.get("time") or _DEFAULT_SCHEDULE_TIME)
    output_dir = _output_dir(refresh_block)
    output_dir.mkdir(parents=True, exist_ok=True)
    bat_path = _build_bat(_COLLECT_PY, config_path, output_dir)
    emit_event(LEVEL_INFO, "refresh.install_bat", bat=str(bat_path), task=task_name, time=sched_time)

    dry = bool(getattr(args, "dry_run", False))
    schtasks_cmd = [
        "schtasks", "/Create", "/TN", task_name, "/SC", "DAILY",
        "/ST", sched_time, "/TR", str(bat_path), "/F",
    ]
    print(f"[refresh] 计划任务命令：{' '.join(schtasks_cmd)}", flush=True)
    if dry:
        emit_event(LEVEL_INFO, "refresh.install_dry", note="未实际注册，仅生成 bat 与命令")
        print(f"[refresh] 已生成 {bat_path}（dry-run，未注册计划任务）", flush=True)
        return EXIT_OK
    try:
        proc = subprocess.run(schtasks_cmd, capture_output=True, text=True, timeout=60)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "refresh.install_failed", error=str(exc),
                   hint="需要管理员权限运行以注册计划任务")
        return EXIT_ERROR
    print(proc.stdout, file=sys.stderr, flush=True)
    if proc.returncode != 0:
        emit_event(LEVEL_ERROR, "refresh.install_failed", code=proc.returncode,
                   stderr=(proc.stderr or "").strip()[:300])
        return EXIT_ERROR
    emit_event(LEVEL_INFO, "refresh.install_ok", task=task_name, time=sched_time)
    print(f"[refresh] 已注册每日 {sched_time} 触发的计划任务：{task_name}", flush=True)
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace) -> int:
    _, refresh_block, _ = load_refresh_config(_resolve_config(args))
    sched = refresh_block.get("schedule") or {}
    task_name = str(sched.get("task_name") or _DEFAULT_TASK_NAME)
    try:
        proc = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True, timeout=60)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "refresh.uninstall_failed", error=str(exc))
        return EXIT_ERROR
    if proc.returncode != 0:
        emit_event(LEVEL_ERROR, "refresh.uninstall_failed", code=proc.returncode,
                   stderr=(proc.stderr or "").strip()[:300])
        return EXIT_ERROR
    emit_event(LEVEL_INFO, "refresh.uninstall_ok", task=task_name)
    print(f"[refresh] 已注销计划任务：{task_name}", flush=True)
    return EXIT_OK


# ------------------------------------------------------------------ 工具
def datetime_stamp() -> str:
    from datetime import datetime as _dt
    return _dt.now().strftime("%Y%m%dT%H%M%S")


_STARTED_AT = now_iso()


def logger_started() -> str:
    return _STARTED_AT


def slug(text: str) -> str:
    """把源名变成文件名安全片段（保留中文，去掉空格/特殊符）。"""
    out = re.sub(r"[^\w一-鿿-]", "_", text or "x")
    return out[:40] or "x"


# ------------------------------------------------------------------ selfcheck
def cmd_selfcheck(args: argparse.Namespace) -> int:
    """离线自测：不联网，验证重试/合并/告警/状态核心逻辑（实时 WeChat 采集需真环境，不在本范围）。"""
    py = sys.executable
    tmp = Path(_SCRIPT_DIR.parent / "out" / "selfcheck")
    tmp.mkdir(parents=True, exist_ok=True)
    # 清理旧产物
    for f in tmp.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass

    failures: list[str] = []

    # 1) 重试：stub 失败 2 次后成功 → 期望 attempts==3, code==0
    stub = tmp / "stub.py"
    stub.write_text(
        "import sys, os\n"
        "cfile, fails, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
        "n = int(open(cfile).read()) if os.path.exists(cfile) else 0\n"
        "if n < fails:\n"
        "    open(cfile,'w').write(str(n+1)); sys.exit(3)\n"
        "open(cfile,'w').write(str(n+1)); open(out,'w').write('{\"x\":1}\\n'); sys.exit(0)\n",
        encoding="utf-8",
    )
    counter = tmp / "counter.txt"
    if counter.exists():
        counter.unlink()
    src = {"name": "stub", "layer": "url"}
    rb = {"max_retries": 2, "retry_backoff_seconds": 0.01}
    lg = RunLogger(tmp / "sc.jsonl")
    code, attempts = run_with_retry(
        [py, str(stub), str(counter), "2", str(tmp / "out.jsonl")], src, rb, lg)
    lg.close()
    if code != EXIT_OK or attempts != 3:
        failures.append(f"重试逻辑: 期望 code=0 attempts=3，实际 code={code} attempts={attempts}")

    # 2) 合并：两个 JSONL → 计数正确
    f1 = tmp / "a.jsonl"; f2 = tmp / "b.jsonl"
    f1.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    f2.write_text('{"b":1}\n', encoding="utf-8")
    combined = tmp / "c.jsonl"
    n = combine_outputs([f1, f2], combined)
    if n != 3:
        failures.append(f"合并计数: 期望 3，实际 {n}")

    # 3) 告警评估
    trig, reasons = eval_alert({"alert": {"enabled": True, "on": ["error", "partial", "zero_yield"]}},
                               EXIT_ERROR, 0, [])
    if not trig or "exit_error" not in reasons or "zero_yield" not in reasons:
        failures.append(f"告警评估: 期望触发 error+zero_yield，实际 trig={trig} reasons={reasons}")
    # 关闭时不应触发
    trig2, _ = eval_alert({"alert": {"enabled": False}}, EXIT_ERROR, 0, [])
    if trig2:
        failures.append("告警评估: 关闭后仍触发")

    # 4) alerts.log 写出
    aout = tmp / "alerts.log"
    if aout.exists():
        aout.unlink()
    sc_status = {"run_id": "x", "exit_code": EXIT_ERROR, "total_fetched": 0,
                 "database_id": None, "sources": []}
    lg2 = RunLogger(tmp / "sc2.jsonl")
    send_alert({"alert": {"enabled": True}, "output_dir": str(tmp)}, sc_status, ["exit_error"], lg2)
    lg2.close()
    if not aout.is_file():
        failures.append("告警文件: alerts.log 未生成")

    # 5) build_layer_command 基本拼装（account 缺 biz 应报错）
    try:
        build_layer_command(py, {"name": "bad", "layer": "account"}, combined, _COLLECT_PY)
        failures.append("命令拼装: account 缺 biz 未抛错")
    except ValueError:
        pass
    # url 正常拼装
    try:
        cmd = build_layer_command(py, {"name": "u", "layer": "url",
                                       "urls": "http://x"}, combined, _COLLECT_PY)
        if "--urls" not in cmd:
            failures.append("命令拼装: url 未含 --urls")
    except ValueError as exc:
        failures.append(f"命令拼装: url 异常 {exc}")

    if failures:
        print("[selfcheck] FAIL", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return EXIT_ERROR
    print("[selfcheck] PASS：重试/合并/告警/状态/命令拼装 全部通过", flush=True)
    return EXIT_OK


# ------------------------------------------------------------------ 入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect.py refresh", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", metavar="<cmd>")

    p_run = sub.add_parser("run", help="执行一次刷新（采集+写库+状态+告警）")
    p_run.add_argument("--config", default=None, help="subscriptions.yaml 路径（默认技能根）")
    p_run.add_argument("--yes", action="store_true", help="合规闸：确认已获授权")
    p_run.add_argument("--vault", action="store_true", help="强制开启 vault 双写（覆盖配置）")
    p_run.add_argument("--classify-threshold", type=float, default=0.85, help="分类采纳阈值")
    p_run.add_argument("--since-days", type=int, default=None,
                       help="快捷参数：自动给所有 account 源注入 --since（N 天前的日期，"
                            "免去逐个手填；会覆盖源配置中的 since 字段）")
    p_run.add_argument("--dry-run", action="store_true",
                       help="仅构建并打印各源/写库命令，不执行任何采集或写库")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="查看上次运行状态（status.json）")
    p_status.add_argument("--config", default=None, help="subscriptions.yaml 路径")
    p_status.add_argument("--yes", action="store_true", help="合规闸（兼容透传）")
    p_status.set_defaults(func=cmd_status)

    p_install = sub.add_parser("install", help="注册 Windows 计划任务（每日固定时间）")
    p_install.add_argument("--config", default=None, help="subscriptions.yaml 路径")
    p_install.add_argument("--time", default=None, help="触发时间 HH:MM（默认 08:00）")
    p_install.add_argument("--dry-run", action="store_true",
                           help="仅生成 bat 与 schtasks 命令，不实际注册")
    p_install.add_argument("--yes", action="store_true", help="合规闸（兼容透传）")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="注销 Windows 计划任务")
    p_uninstall.add_argument("--config", default=None, help="subscriptions.yaml 路径")
    p_uninstall.add_argument("--yes", action="store_true", help="合规闸（兼容透传）")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_sc = sub.add_parser("selfcheck", help="离线自测（不联网验证核心逻辑）")
    p_sc.add_argument("--yes", action="store_true", help="合规闸（兼容透传）")
    p_sc.set_defaults(func=cmd_selfcheck)

    parser.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_PARAM
    return int(args.func(args) or 0)


def register(subparsers) -> None:
    """挂入 collect.py 成为 refresh 模式（其余参数以 REMAINDER 透传给本模块 main）。"""
    parser = subparsers.add_parser(
        "refresh",
        help="每日自动刷新订阅文章：编排采集+写库+调度+状态/告警",
        description="每日自动刷新订阅文章能力入口（run/status/install/uninstall/selfcheck）。",
    )
    parser.add_argument(
        "rest", nargs=argparse.REMAINDER,
        help="子命令及其参数：run | status | install | uninstall | selfcheck "
             "（如 collect.py refresh run --yes --config subscriptions.yaml）")
    parser.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> int:
    # collect.py 顶层可能已吞掉 --config/--yes（同一 SUPPRESS 契约），这里补回给 refresh.main
    rest = list(getattr(args, "rest", []) or [])
    cfg = getattr(args, "config", None)
    if cfg:
        rest = ["--config", str(cfg)] + rest
    if getattr(args, "yes", False):
        rest = ["--yes"] + rest
    return main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
