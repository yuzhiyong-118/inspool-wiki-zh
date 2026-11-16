"""停服归并已结算调用；按 call_id 幂等，冲突拒绝，不改写历史计量。"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys

from .contracts import DeliveryError, canonical, read_json, sha256
from .evidence_store import atomic
from .runtime import load_config, status
from .runtime_guard import RuntimeGuard


CALL_FIELDS = {"callId", "startedAt", "sessionId", "turnId", "source", "usage"}


def _summary(position):
    return {key: value for key, value in position.items() if key != "countedCalls"}


def _record(value):
    if not isinstance(value, dict) or set(value) != CALL_FIELDS:
        raise DeliveryError("usage_import_fields", "导入调用字段不完整或含未知字段", "conflict")
    call_id = value["callId"]
    if (not isinstance(call_id, str) or not call_id or len(call_id) > 128
            or type(value["startedAt"]) not in (int, float)
            or not math.isfinite(value["startedAt"]) or value["startedAt"] < 0
            or any(not isinstance(value[key], str) for key in ("sessionId", "turnId", "source"))):
        raise DeliveryError("usage_import_identity", "导入调用身份或时间无效", "conflict")
    usage = value["usage"]
    if (not isinstance(usage, dict) or usage.get("call_id") != call_id
            or type(usage.get("total_tokens")) is not int or usage["total_tokens"] < 0
            or type(usage.get("estimated")) is not bool
            or not isinstance(usage.get("status"), str) or not usage["status"]):
        raise DeliveryError("usage_import_measurement", "导入计量缺少有效总量、估算性质或原状态", "conflict")
    raw = json.dumps(usage, ensure_ascii=False, allow_nan=False)
    return (call_id, value["startedAt"], value["sessionId"], value["turnId"], value["source"], raw)


def _same_ledger(row, expected):
    if row is None or tuple(row[:5]) != expected[:5]:
        return False
    try:
        return json.loads(row[5]) == json.loads(expected[5])
    except (ValueError, TypeError):
        return False


def import_calls(config_path, input_path, expected_sha256):
    config = load_config(config_path)
    live = status(config)
    if any(live.get("processes", {}).values()):
        raise DeliveryError("usage_import_running", "停服并备份后才能归并用量", "busy")
    source = Path(input_path).resolve(strict=True)
    source_bytes = source.read_bytes()
    actual_sha256 = sha256(source_bytes)
    if actual_sha256 != expected_sha256:
        raise DeliveryError("usage_import_source", "导入输入摘要与明确预期不符", "conflict")
    payload = read_json(source)
    calls = payload.get("calls") if isinstance(payload, dict) else None
    if not isinstance(calls, list) or not 1 <= len(calls) <= 64:
        raise DeliveryError("usage_import_calls", "一次导入须包含 1～64 条明确调用", "conflict")
    expected = [_record(call) for call in calls]
    ids = [row[0] for row in expected]
    if len(set(ids)) != len(ids):
        raise DeliveryError("usage_import_duplicate", "导入输入含重复 call_id", "conflict")

    guard = RuntimeGuard(config["guard"])
    if guard.budget.ledger == guard.database:
        raise DeliveryError("usage_import_paths", "账本与控制库必须独立", "conflict")
    if guard.budget.baseline.intersection(ids):
        raise DeliveryError("usage_import_baseline", "免计基线调用不得作为新增用量导入", "conflict")
    control_path = guard.database.resolve(strict=True)
    ledger_path = guard.budget.ledger.resolve(strict=True)
    imported, replayed = [], []
    with closing(sqlite3.connect(control_path.as_uri() + "?mode=rw", uri=True, timeout=2)) as db:
        try:
            db.execute("ATTACH DATABASE ? AS usage", (str(ledger_path),))
            db.execute("BEGIN IMMEDIATE")
            control = RuntimeGuard._read(db)
            unsettled = db.execute(
                "SELECT call_id FROM calls WHERE state IN ('active','metering_unknown')").fetchall()
            if unsettled:
                raise DeliveryError("usage_import_unsettled", "存在未结算调用；先按原身份对账", "conflict")
            guard.budget.floor = control.get("floor", {})
            before = guard.budget.position()
            if before.get("error"):
                raise DeliveryError("usage_import_unobservable", "导入前账本不可观察", "failed")
            for row in expected:
                call_id = row[0]
                ledger_row = db.execute(
                    "SELECT call_id,started_at,session_id,turn_id,source,usage_json "
                    "FROM usage.llm_calls WHERE call_id=?", (call_id,)).fetchone()
                control_row = db.execute(
                    "SELECT call_id,started,session_id,turn_id,source,state,finished FROM calls WHERE call_id=?",
                    (call_id,)).fetchone()
                if ledger_row is None and control_row is None:
                    imported.append(call_id)
                    continue
                same_control = (control_row is not None and tuple(control_row[:5]) == row[:5]
                                and control_row[5] in ("finished", "settled_after_restart")
                                and control_row[6] is not None)
                if not _same_ledger(ledger_row, row) or not same_control:
                    raise DeliveryError("usage_import_conflict",
                                        "相同 call_id 的审计事实冲突或只存在于单侧；拒绝覆盖", "conflict")
                replayed.append(call_id)
            for row in expected:
                if row[0] not in imported:
                    continue
                db.execute("INSERT INTO usage.llm_calls VALUES (?,?,?,?,?,?)", row)
                db.execute("INSERT INTO calls VALUES (?,?,?,'finished',?,?,?)",
                           (row[0], row[1], row[1], row[2], row[3], row[4]))
            guard.budget.floor = control.get("floor", {})
            rows = db.execute("SELECT call_id,usage_json FROM usage.llm_calls ORDER BY rowid").fetchall()
            after = guard.budget._position_from_rows(rows)
            if after.get("error"):
                raise DeliveryError("usage_import_unobservable", "导入后账本不可观察", "failed")
            increment = after["totalTokens"] - before["totalTokens"]
            expected_increment = sum(json.loads(row[5])["total_tokens"] for row in expected
                                     if row[0] in imported)
            if increment != expected_increment:
                raise DeliveryError("usage_import_increment", "实际归并增量与缺失调用不符", "failed")
            if imported:
                control.update(position=after, floor=after["countedCalls"])
                RuntimeGuard._write(db, control)
            db.commit()
            db.execute("DETACH DATABASE usage")
        except Exception:
            db.rollback()
            db.execute("DETACH DATABASE usage")
            raise

    receipt = {
        "schema": "learning-usage-import/1",
        "sourceSha256": actual_sha256,
        "callIds": ids,
        "imported": imported,
        "replayed": replayed,
        "incrementTokens": increment,
        "before": _summary(before),
        "after": _summary(after),
        "pauseAt": guard.budget.context["pauseAt"],
        "limit": guard.budget.context["limit"],
        "baselineCallIdsPreserved": True,
        "blockedPreserved": control.get("blocked"),
        "records": [{"callId": row[0], "startedAt": row[1], "sessionId": row[2],
                     "turnId": row[3], "source": row[4], "usage": json.loads(row[5])}
                    for row in expected],
    }
    receipt_path = Path(config["controlDir"]) / "usage-imports" / (actual_sha256 + ".json")
    if receipt_path.exists():
        prior = read_json(receipt_path)
        if any(prior.get(key) != receipt[key] for key in
               ("schema", "sourceSha256", "callIds", "records", "pauseAt", "limit")):
            raise DeliveryError("usage_import_receipt", "同输入已有不同导入回执；须先对账", "uncertain")
    else:
        atomic(receipt_path, canonical(receipt), immutable=True)
    return {"status": "succeeded", "receiptRef": str(receipt_path), **receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = import_calls(args.config, args.input, args.source_sha256)
        code = 0
    except (DeliveryError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        result = {"status": exc.status if isinstance(exc, DeliveryError) else "failed",
                  "errors": [{"code": exc.code if isinstance(exc, DeliveryError) else "usage_import_failure",
                              "message": str(exc)}]}
        code = 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
