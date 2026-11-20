from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter_ns

from app.clock import instant
from app.codec import canonical
from app.config import RULESET
from app.errors import DomainError
from app.modules.m7_archive.manifest import create
from app.pipeline import evaluate
from app.records import token
from .diff import diff_results
from .ops import apply

MAX_OPERATIONS = 100


def validate(body):
    if not isinstance(body, dict):
        raise DomainError("BAD_AMENDMENT", "补录格式错误")
    amendment = body.get("amendment")
    if not token(amendment):
        raise DomainError("AMENDMENT_ID_INVALID", "请输入补录单号")
    received_at = body.get("received_at")
    if received_at is not None:
        try:
            instant(received_at)
        except ValueError as error:
            raise DomainError("BAD_VALUE", "补录登记时间须带时区并精确到秒") from error
    operations = body.get("operations")
    if not isinstance(operations, list) or not operations:
        raise DomainError("OPERATIONS_EMPTY", "补录至少包含一条操作")
    if len(operations) > MAX_OPERATIONS:
        raise DomainError("ROW_LIMIT", "补录操作超过上限", 413)
    return amendment.strip(), received_at, operations


def handover_of(base, manifest, result, verdicts):
    checks = {
        "base_reconciled": base["result"]["reconcile"]["status"] == "MATCHED",
        "amended_reconciled": bool(result) and result["reconcile"]["status"] == "MATCHED",
        "same_ruleset": base["manifest"]["ruleset"] == RULESET
        and (manifest is None or manifest["ruleset"] == RULESET),
        "all_adopted": all(item["verdict"] == "adopted" for item in verdicts),
    }
    return {"ready": all(checks.values()), "checks": checks, "base_signature": base.get("signature")}


def outcome(ledger, record):
    if record["run"] is None:
        return None
    return ledger.read(record["run"])[1]["result"]


def amend(ledger, ident, body):
    amendment, received_at, operations = validate(body)
    try:
        request_hash = canonical({"base_run": ident, "body": body})
    except (ValueError, RecursionError) as error:
        raise DomainError("BAD_VALUE", "请检查补录数据格式") from error
    existing = ledger.get_amendment(amendment)
    if existing is not None:
        if existing["request"] != request_hash:
            raise DomainError("AMENDMENT_CONFLICT", "补录单号已被不同内容占用", 409)
        return {**existing["record"], "result": outcome(ledger, existing["record"]), "reused": True}
    source, base = ledger.read(ident)
    document, verdicts = apply(deepcopy(source), operations)
    adopted = [item for item in verdicts if item["verdict"] == "adopted"]
    manifest = result = diff = run_id = None
    if adopted:
        start = perf_counter_ns()
        result = evaluate(document)
        manifest = create(document, result, (perf_counter_ns() - start) // 1_000_000)
        run_id = manifest["id"]
        diff = diff_results(base["result"], result)
    record = {
        "amendment": amendment, "base_run": ident, "run": run_id, "batch": source["batch"],
        "received_at": received_at,
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "operations": verdicts, "adopted": len(adopted), "rejected": len(verdicts) - len(adopted),
        "diff": diff, "handover": handover_of(base, manifest, result, verdicts),
        "manifest": manifest,
    }
    snapshot = {"id": run_id, "manifest": manifest, "result": result} if adopted else None
    stored, reused = ledger.record_amendment(
        amendment, ident, run_id, request_hash, document if adopted else None, snapshot, record)
    return {**stored, "result": result, "reused": reused}
