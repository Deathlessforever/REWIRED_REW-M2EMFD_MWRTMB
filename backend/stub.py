"""Disposable canned API for frontend development; never verifies payments."""

import copy
import csv
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile

from backend.messages import command_for, reminders_reply, statement_reply

app = FastAPI(title="ChitMirror stub")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CHITMIRROR_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(","), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
EXAMPLES = json.loads((FIXTURES / "result_examples.json").read_text(encoding="utf-8"))
FOREMAN_STATE = json.loads((FIXTURES / "state_foreman.json").read_text(encoding="utf-8"))
with (FIXTURES / "financial_schedule.csv").open(encoding="utf-8", newline="") as file:
    SCHEDULE = {int(row["month"]): row for row in csv.DictReader(file)}


def error(code, message, status):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error("invalid_request", "Invalid request.", 422)


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(min_length=1)


class Review(Actor):
    item_id: str = Field(min_length=1)
    decision: str
    reason: str


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str = Field(min_length=1)
    text: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/message")
async def message(request: Request):
    image = None
    try:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type == "application/json":
            payload = Message.model_validate(await request.json())
        elif content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
            form = await request.form()
            if set(form.keys()) - {"sender", "text", "image"}:
                raise ValueError("Unexpected form field")
            image = form.get("image")
            if image is not None and not isinstance(image, UploadFile):
                raise ValueError("Invalid image")
            payload = Message.model_validate({"sender": form.get("sender"), "text": form.get("text", "")})
        else:
            raise ValueError("Unsupported content type")
    except (ValueError, ValidationError):
        return error("invalid_request", "Invalid message request.", 422)
    if not payload.sender.strip() or (not payload.text.strip() and image is None):
        return error("invalid_request", "Text or image is required.", 422)
    if image and image.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        return error("invalid_request", "Unsupported image type.", 422)
    bubbles = EXAMPLES["message_response"][0]["bubbles"]
    # Deterministic selectors give frontend teams every card without real verification.
    choices = {bubble["status"]: bubble for bubble in bubbles if bubble["type"] == "result_card"}
    key = payload.text.strip().removeprefix("stub:")
    if key in choices:
        return {"bubbles": [choices[key]]}
    if key == "review_request":
        return {"bubbles": [next(b for b in bubbles if b["type"] == "review_request")]}
    if key == "reminder":
        return {"bubbles": [next(b for b in bubbles if b["type"] == "reminder")]}
    command = command_for(payload.text) if image is None and payload.sender != "foreman" else None
    if command:
        member_state = state(role="member", member_id=payload.sender)
        if isinstance(member_state, JSONResponse):
            return member_state
        if command == "statement":
            return {"bubbles": [statement_reply(member_state, payload.sender)]}
        if command == "reminders":
            return {"bubbles": reminders_reply(member_state, payload.sender)}
        latest = next((entry for entry in reversed(member_state["ledger"]) if entry["member_id"] == payload.sender), None)
        details = f"month {latest['month']}, status: {latest['status']}, amount: {latest['amount_paise']} paise" if latest else "no payment recorded"
        return {"bubbles": [{"type": "text", "text": f"Dues for {payload.sender}: {details}. Synthetic fixture only."}]}
    return {"bubbles": [bubbles[0]]}


@app.post("/review")
def review(payload: Review):
    if payload.actor != "foreman" or payload.decision not in {"approve", "reject"} or not payload.reason.strip():
        return error("invalid_request", "Foreman, valid decision and reason are required.", 422)
    return {"item_id": payload.item_id, "decision": payload.decision}


@app.get("/state")
def state(role: str, member_id: str | None = None):
    if role not in {"foreman", "member"} or (role == "member" and not member_id):
        return error("invalid_request", "Valid role and member ID are required.", 422)
    result = copy.deepcopy(FOREMAN_STATE)
    if role == "member":
        if member_id not in {member["id"] for member in result["members"]}:
            return error("invalid_request", "Member not found.", 422)
        result.update(flags=[], overdue=[], audit_log=[], private_bubbles=[])
        result["statement"] = [
            {"month": entry["month"], "instalment_paise": entry["amount_paise"],
             "dividend_paise": int(SCHEDULE[entry["month"]]["dividend_per_member_paise"]),
             "late_fee_paise": 0,
             "prize_paise": int(SCHEDULE[entry["month"]]["prize_paise"]) if SCHEDULE[entry["month"]]["winner_member_id"] == member_id else 0,
             "status": entry["status"]}
            for entry in result["ledger"] if entry["member_id"] == member_id
        ]
    else:
        result.update(statement=[], private_bubbles=[])
    return result


@app.post("/reminders/send")
def reminders(payload: Actor):
    if payload.actor != "foreman":
        return error("invalid_request", "Foreman required.", 422)
    return EXAMPLES["reminders_response"][0]


@app.post("/demo/load")
def demo_load(payload: Actor):
    if payload.actor != "foreman":
        return error("invalid_request", "Foreman required.", 422)
    return EXAMPLES["demo_load_response"][0]
