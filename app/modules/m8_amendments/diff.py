def pick_order(row):
    if row is None:
        return None
    return {"meal": row.get("meal"), "qty": row["qty"], "shipped": row["shipped"],
            "short": row["short"], "disputed": row["disputed"], "code": row.get("code")}


def pick_vehicle(row):
    if row is None:
        return None
    return {"capacity": row["capacity"], "loaded": row["loaded"], "remaining": row["remaining"]}


def pick_lot(row):
    if row is None:
        return None
    return {"meal": row.get("meal"), "kind": row.get("kind"), "qty": row["qty"],
            "loaded": row["loaded"], "left": row["left"], "status": row["status"]}


def changed(before_rows, after_rows, key, pick):
    before = {row[key]: row for row in before_rows}
    after = {row[key]: row for row in after_rows}
    output = []
    for ident in sorted(set(before) | set(after)):
        old, new = pick(before.get(ident)), pick(after.get(ident))
        if old != new:
            output.append({key: ident, "before": old, "after": new})
    return output


def diff_results(before, after):
    totals = {}
    for label, result in (("before", before), ("after", after)):
        totals[label] = {**result["reconcile"]["totals"], "status": result["reconcile"]["status"]}
    return {
        "orders": changed(before["allocation"]["rows"], after["allocation"]["rows"], "order", pick_order),
        "vehicles": changed(before["allocation"]["vehicles"], after["allocation"]["vehicles"], "truck", pick_vehicle),
        "lots": changed(before["allocation"]["stock"], after["allocation"]["stock"], "lot", pick_lot),
        "totals": totals,
    }
