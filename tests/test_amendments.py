from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import create_app

REVISE = {"op": "revise_order", "row": {
    "order": "团-001", "revision": 2, "supersedes": 1, "issued": "2026-11-20T09:20:00+08:00",
    "station": "北门诊厅", "wave": "晨线", "qty": 18, "meal": "菌菇素", "locked": False, "status": "active"}}
RETURN = {"op": "return_stock", "lot": "备-01", "qty": 5}
LATE_TRIP = {"op": "update_trip", "row": {
    "truck": "柿-04", "wave": "午线", "capacity": 28, "departure": "2026-11-20T11:16:00+08:00",
    "stops": [{"station": "创客园", "eta": "2026-11-20T11:44:00+08:00"},
              {"station": "运动馆", "eta": "2026-11-20T12:05:00+08:00"}]}}


def start(client, sample="clean"):
    response = client.post("/api/runs", json={"sample": sample})
    assert response.status_code == 200, response.text
    return response.json()


def amend(client, ident, operations, amendment="补录-001", **extra):
    body = {"amendment": amendment, "operations": operations, **extra}
    return client.post(f"/api/runs/{ident}/amendments", json=body)


def test_amendment_forms_new_conclusion_with_diff(client):
    base = start(client)
    response = amend(client, base["id"], [REVISE, RETURN])
    assert response.status_code == 200, response.text
    record = response.json()
    assert not record["reused"] and record["adopted"] == 2 and record["rejected"] == 0
    assert record["run"] and record["run"] != base["id"] and record["base_run"] == base["id"]
    assert all(item["verdict"] == "adopted" for item in record["operations"])
    order = next(row for row in record["diff"]["orders"] if row["order"] == "团-001")
    assert (order["before"]["meal"], order["after"]["meal"]) == ("家常荤", "菌菇素")
    lot = next(row for row in record["diff"]["lots"] if row["lot"] == "备-01")
    assert (lot["before"]["qty"], lot["after"]["qty"]) == (25, 30)
    totals = record["diff"]["totals"]
    assert totals["before"]["spare"]["declared"] == 63 and totals["after"]["spare"]["declared"] == 68
    assert totals["before"]["spare"]["used"] == 0 and totals["after"]["spare"]["used"] == 13
    assert record["handover"]["ready"] and record["result"]["reconcile"]["status"] == "MATCHED"


def test_late_vehicle_update_replans(client):
    base = start(client, "dirty")
    record = amend(client, base["id"], [LATE_TRIP], "补录-晚到").json()
    vehicle = next(row for row in record["diff"]["vehicles"] if row["truck"] == "柿-04")
    assert (vehicle["before"]["loaded"], vehicle["after"]["loaded"]) == (0, 12)
    totals = record["diff"]["totals"]
    assert (totals["before"]["shipped"], totals["after"]["shipped"]) == (158, 170)
    assert (totals["before"]["short"], totals["after"]["short"]) == (42, 30)
    assert totals["after"]["status"] == "MATCHED" and record["handover"]["ready"]


def test_base_signoff_stays_traceable(client):
    base = start(client)
    client.post(f'/api/runs/{base["id"]}/sign',
                json={"reviewer": "周洁", "digest": base["manifest"]["digest"]})
    record = amend(client, base["id"], [RETURN]).json()
    assert record["handover"]["base_signature"]["reviewer"] == "周洁"
    old = client.get(f'/api/runs/{base["id"]}').json()
    assert old["manifest"]["digest"] == base["manifest"]["digest"]
    assert old["signature"]["reviewer"] == "周洁"
    assert old["lineage"]["superseded_by"] == [{"amendment": "补录-001", "run": record["run"]}]
    new = client.get(f'/api/runs/{record["run"]}').json()
    assert new["lineage"]["amendment"] == "补录-001" and new["lineage"]["supersedes"] == base["id"]
    listed = client.get(f'/api/runs/{base["id"]}/amendments').json()["amendments"]
    assert [item["amendment"] for item in listed] == ["补录-001"]


def test_idempotent_replay_no_duplicate_conclusion(client):
    base = start(client)
    first = amend(client, base["id"], [RETURN]).json()
    second = amend(client, base["id"], [RETURN]).json()
    assert not first["reused"] and second["reused"]
    assert second["run"] == first["run"] and second["manifest"] == first["manifest"]
    assert len(client.get("/api/runs").json()["runs"]) == 2
    spare = second["result"]["reconcile"]["totals"]["spare"]
    assert spare["declared"] == 68 and spare["left"] == 68  # 退回只入账一次


def test_concurrent_retry_records_one_amendment(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    with TestClient(create_app(path)) as client:
        base = start(client)
        with ThreadPoolExecutor(max_workers=4) as executor:
            records = list(executor.map(
                lambda _: amend(client, base["id"], [RETURN]).json(), range(4)))
        assert sum(not item["reused"] for item in records) == 1
        assert len({item["run"] for item in records}) == 1
        assert len(client.get(f'/api/runs/{base["id"]}/amendments').json()["amendments"]) == 1
        assert len(client.get("/api/runs").json()["runs"]) == 2


def test_same_id_with_different_content_conflicts(client):
    base = start(client)
    assert amend(client, base["id"], [RETURN]).status_code == 200
    conflict = amend(client, base["id"], [REVISE])
    assert conflict.status_code == 409 and conflict.json()["code"] == "AMENDMENT_CONFLICT"
    other = amend(client, start(client, "dirty")["id"], [RETURN])
    assert other.status_code == 409 and other.json()["code"] == "AMENDMENT_CONFLICT"


def test_same_content_under_new_id_reuses_run(client):
    base = start(client)
    first = amend(client, base["id"], [REVISE], "补录-甲").json()
    second = amend(client, base["id"], [REVISE], "补录-乙").json()
    assert not second["reused"] and second["run"] == first["run"]
    assert len(client.get("/api/runs").json()["runs"]) == 2


def test_rejected_operations_still_form_traceable_conclusion(client):
    base = start(client)
    future = {"op": "revise_order", "row": {**REVISE["row"], "issued": "2026-11-20T10:00:00+08:00"}}
    record = amend(client, base["id"], [RETURN, future, {"op": "return_stock", "lot": "备-99", "qty": 5}]).json()
    assert (record["adopted"], record["rejected"]) == (1, 2)
    verdicts = {item["code"] for item in record["operations"] if item["verdict"] == "rejected"}
    assert verdicts == {"FUTURE_REVISION", "UNKNOWN_LOT"}
    assert record["run"] and not record["handover"]["ready"]
    assert not record["handover"]["checks"]["all_adopted"]
    assert [row["lot"] for row in record["diff"]["lots"]] == ["备-01"]


def test_all_rejected_forms_no_conclusion(client):
    base = start(client)
    record = amend(client, base["id"], [{"op": "return_stock", "lot": "备-99", "qty": 5}]).json()
    assert record["adopted"] == 0 and record["run"] is None and record["diff"] is None
    assert record["result"] is None and not record["handover"]["ready"]
    assert len(client.get("/api/runs").json()["runs"]) == 1
    again = amend(client, base["id"], [{"op": "return_stock", "lot": "备-99", "qty": 5}]).json()
    assert again["reused"] and again["run"] is None


def test_operation_adjudication_rules(client, dirty):
    base = start(client, "dirty")
    departed = {"op": "update_trip", "row": {**LATE_TRIP["row"], "departure": "2026-11-20T09:00:00+08:00"}}
    operations = [departed,
                  {"op": "return_stock", "lot": "备-08", "qty": 5},
                  {"op": "return_stock", "lot": "备-06", "qty": 5},
                  {"op": "return_stock", "row": {"lot": "备-01", "meal": "粗粮荤", "qty": 5, "kind": "spare",
                                                 "ready": "2026-11-20T07:50:00+08:00",
                                                 "expires": "2026-11-20T14:00:00+08:00"}},
                  {"op": "revise_order", "row": {**REVISE["row"], "order": None}},
                  {"op": "teleport"}, "不是操作"]
    record = amend(client, base["id"], operations).json()
    codes = [item["code"] for item in record["operations"]]
    assert codes == ["DEPARTED", "STOCK_CONFLICT", "STOCK_EXPIRED",
                     "STOCK_DUPLICATE", "ORDER_ID_INVALID", "UNKNOWN_OPERATION", "OPERATION_SCHEMA"]
    assert record["run"] is None


def test_new_lot_registration(client):
    base = start(client)
    new_lot = {"op": "return_stock", "row": {"lot": "备-09", "meal": "粗粮荤", "qty": 5, "kind": "spare",
                                             "ready": "2026-11-20T07:50:00+08:00",
                                             "expires": "2026-11-20T14:00:00+08:00"}}
    record = amend(client, base["id"], [new_lot]).json()
    assert record["adopted"] == 1 and record["handover"]["ready"]
    spare = record["result"]["reconcile"]["totals"]["spare"]
    assert spare["declared"] == 68 and spare["left"] == 68


def test_sign_blocked_until_handover_ready(client):
    base = start(client)
    record = amend(client, base["id"], [RETURN, {"op": "return_stock", "lot": "备-99", "qty": 5}]).json()
    response = client.post(f'/api/runs/{record["run"]}/sign',
                           json={"reviewer": "李颖", "digest": record["manifest"]["digest"]})
    assert response.status_code == 409 and response.json()["code"] == "HANDOVER_BLOCKED"


def test_handover_sign_flow(client):
    base = start(client)
    client.post(f'/api/runs/{base["id"]}/sign',
                json={"reviewer": "周洁", "digest": base["manifest"]["digest"]})
    record = amend(client, base["id"], [RETURN]).json()
    assert record["handover"]["ready"]
    receipt = client.post(f'/api/runs/{record["run"]}/sign',
                          json={"reviewer": "李颖", "digest": record["manifest"]["digest"]})
    assert receipt.status_code == 200 and receipt.json()["balance"] == "MATCHED"


def test_amendment_chain(client):
    first = amend(client, start(client)["id"], [REVISE], "补录-01").json()
    second = amend(client, first["run"], [RETURN], "补录-02").json()
    assert second["base_run"] == first["run"] and second["run"] != first["run"]
    lineage = client.get(f'/api/runs/{second["run"]}').json()["lineage"]
    assert lineage["amendment"] == "补录-02" and lineage["supersedes"] == first["run"]
    spare = second["result"]["reconcile"]["totals"]["spare"]
    assert spare["declared"] == 68 and spare["used"] == 13


def test_amended_run_export_and_rerun(client, clean):
    base = start(client)
    record = amend(client, base["id"], [REVISE]).json()
    evidence = client.get(f'/api/runs/{record["run"]}/export').json()
    assert len(evidence["source"]["orders"]) == len(clean["orders"]) + 1
    assert evidence["source"]["orders"][-1]["revision"] == 2
    assert evidence["lineage"]["supersedes"] == base["id"]
    rerun = client.post(f'/api/runs/{record["run"]}/rerun').json()
    assert rerun["reused"] and rerun["manifest"]["digest"] == record["manifest"]["digest"]


def test_amendment_requires_existing_run(client):
    response = amend(client, "missing", [RETURN])
    assert response.status_code == 404 and response.json()["code"] == "RUN_NOT_FOUND"


def test_amendment_body_validation(client):
    base = start(client)
    assert amend(client, base["id"], [RETURN], amendment="").json()["code"] == "AMENDMENT_ID_INVALID"
    assert amend(client, base["id"], []).json()["code"] == "OPERATIONS_EMPTY"
    assert amend(client, base["id"], "不是数组").json()["code"] == "OPERATIONS_EMPTY"
    assert amend(client, base["id"], [RETURN], received_at="昨晚").json()["code"] == "BAD_VALUE"
    too_many = amend(client, base["id"], [RETURN] * 101)
    assert too_many.status_code == 413 and too_many.json()["code"] == "ROW_LIMIT"
    assert len(client.get("/api/runs").json()["runs"]) == 1
