from fastapi import APIRouter, Request

from . import service

router = APIRouter(prefix="/api/runs")


@router.post("/{ident}/amendments")
def amend(ident: str, body: dict, request: Request):
    return service.amend(request.app.state.ledger, ident, body)


@router.get("/{ident}/amendments")
def amendments(ident: str, request: Request):
    ledger = request.app.state.ledger
    ledger.read(ident)
    return {"amendments": ledger.amendments_for(ident)}
