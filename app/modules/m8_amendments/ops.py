from app.clock import instant
from app.modules.m1_orders.revisions import parse as parse_revision
from app.modules.m4_capacity.trips import parse as parse_trip
from app.modules.m5_allocation.stock import parse as parse_stock
from app.records import entry, integer, token


def reject(index, kind, code, detail, target=None):
    return {"index": index, "op": kind, "verdict": "rejected", "code": code,
            "detail": detail, "target": target}


def adopt(index, kind, target, summary):
    return {"index": index, "op": kind, "verdict": "adopted", "target": target, "summary": summary}


def revise_order(document, index, operation, cutoff):
    row = operation.get("row")
    if not isinstance(row, dict):
        return reject(index, "revise_order", "ORDER_SCHEMA", "补录缺少改签行")
    if not token(row.get("order")):
        return reject(index, "revise_order", "ORDER_ID_INVALID", "订单号缺失")
    try:
        parsed = parse_revision(entry("orders", 0, row))
    except ValueError:
        return reject(index, "revise_order", "ORDER_SCHEMA", "改签字段或时间无效", row.get("order"))
    target = row["order"]
    if parsed["t"] > cutoff:
        return reject(index, "revise_order", "FUTURE_REVISION", "改签晚于调度截点，请开新批次", target)
    document["orders"].append(row)
    return adopt(index, "revise_order", target, f"{target} 改签至版本 {parsed['revision']}")


def update_trip(document, index, operation, cutoff):
    row = operation.get("row")
    if not isinstance(row, dict):
        return reject(index, "update_trip", "TRIP_SCHEMA", "补录缺少车次行")
    try:
        parsed = parse_trip(entry("trips", 0, row))
    except ValueError:
        return reject(index, "update_trip", "TRIP_SCHEMA", "车次、容量或到站序列无效", row.get("truck"))
    truck = parsed["truck"]
    if parsed["departure"] < cutoff:
        return reject(index, "update_trip", "DEPARTED", "车辆已在批次截点前出发", truck)
    replaced = any(trip.get("truck") == truck for trip in document["trips"])
    document["trips"] = [trip for trip in document["trips"] if trip.get("truck") != truck]
    document["trips"].append(row)
    return adopt(index, "update_trip", truck, f"{truck} 班次已{'更新' if replaced else '补登'}")


def return_stock(document, index, operation, cutoff):
    if "row" in operation:
        row = operation["row"]
        if not isinstance(row, dict):
            return reject(index, "return_stock", "STOCK_SCHEMA", "补录库存行无效")
        lot = row.get("lot")
        if not token(lot):
            return reject(index, "return_stock", "STOCK_ID_INVALID", "缺少批号，无法核量")
        try:
            parse_stock(entry("stock", 0, row))
        except ValueError:
            return reject(index, "return_stock", "STOCK_SCHEMA", "批次餐品、时间或份数无效", lot)
        if any(item.get("lot") == lot for item in document["stock"]):
            return reject(index, "return_stock", "STOCK_DUPLICATE", "批号已存在，请按退回份数加量", lot)
        document["stock"].append(row)
        return adopt(index, "return_stock", lot, f"新批号 {lot} 登记 {row['qty']} 份")
    lot, qty = operation.get("lot"), operation.get("qty")
    if not token(lot) or not integer(qty, 1, 100_000):
        return reject(index, "return_stock", "STOCK_SCHEMA", "退回批号或份数无效", lot)
    rows = [item for item in document["stock"] if item.get("lot") == lot]
    if not rows:
        return reject(index, "return_stock", "UNKNOWN_LOT", "批号不存在，请用完整库存行补登", lot)
    parsed = []
    for item in rows:
        try:
            parsed.append(parse_stock(entry("stock", 0, item)))
        except ValueError:
            return reject(index, "return_stock", "STOCK_SCHEMA", "原批号记录无效，请先厘清", lot)
    if len({(row["qty"], row["kind"], row["meal"], row["ready"], row["expires"]) for row in parsed}) != 1:
        return reject(index, "return_stock", "STOCK_CONFLICT", "批号存在互斥记录，请先厘清", lot)
    facts = parsed[0]
    if facts["expires"] <= cutoff:
        return reject(index, "return_stock", "STOCK_EXPIRED", "批号已过调度截点有效期", lot)
    merged = {**rows[0], "qty": facts["qty"] + qty}
    document["stock"] = [item for item in document["stock"] if item.get("lot") != lot]
    document["stock"].append(merged)
    return adopt(index, "return_stock", lot, f"{lot} 退回 {qty} 份，申报 {facts['qty']}→{facts['qty'] + qty}")


HANDLERS = {"revise_order": revise_order, "update_trip": update_trip, "return_stock": return_stock}


def apply(document, operations):
    cutoff = instant(document["at"])
    verdicts = []
    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            verdicts.append(reject(index, None, "OPERATION_SCHEMA", "补录操作格式错误"))
            continue
        handler = HANDLERS.get(operation.get("op"))
        if handler is None:
            verdicts.append(reject(index, operation.get("op"), "UNKNOWN_OPERATION", "未知补录类型"))
            continue
        verdicts.append(handler(document, index, operation, cutoff))
    return document, verdicts
