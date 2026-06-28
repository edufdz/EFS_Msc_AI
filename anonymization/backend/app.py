import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ner_pass import get_analyzer
from pipeline import anonymize

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".txt", ".json"}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    replacement_counts: dict[str, int]
    total_replacements: int


class PreviewResponse(BaseModel):
    original_text: str
    anonymized_text: str
    replacement_counts: dict[str, int]
    total_replacements: int


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# App lifecycle — eagerly load spaCy model
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_analyzer()  # warm up the NER model
    yield


app = FastAPI(title="Anonymization API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_extension(filename: str | None) -> str:
    if not filename:
        return ".txt"
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".txt"


async def _read_file(file: UploadFile) -> str:
    ext = _get_extension(file.filename)
    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=422, detail="File exceeds 10 MB limit")
    # Try UTF-8, fall back to latin-1
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    if ext == ".json":
        text = _extract_text_from_json(text)

    return text


def _extract_text_from_json(raw_json: str) -> str:
    """Extract conversation text from JSON. Supports common formats:
    - TechRepair/Supabase export: {conversations: [{messages: [{text_body, direction}]}]}
    - Array of message objects with 'content'/'text'/'message' field
    - Object with 'messages'/'conversation'/'turns' array
    - Plain string value
    """
    data = json.loads(raw_json)

    # If it's already a string, return as-is
    if isinstance(data, str):
        return data

    # TechRepair/Supabase multi-conversation export
    if isinstance(data, dict) and "conversations" in data and isinstance(data["conversations"], list):
        return _extract_multi_conversation(data["conversations"])

    # Find the messages array
    messages = None
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        for key in ("messages", "conversation", "turns", "data", "chat"):
            if key in data and isinstance(data[key], list):
                messages = data[key]
                break
        if messages is None:
            # Fallback: serialize the whole thing as text
            return json.dumps(data, ensure_ascii=False, indent=2)

    # Extract text from each message object
    return _extract_messages(messages)


def _extract_multi_conversation(conversations: list) -> str:
    """Extract text from a multi-conversation export."""
    all_lines = []
    for conv in conversations:
        if not isinstance(conv, dict):
            continue
        # Add conversation header with metadata
        conv_id = conv.get("id", "unknown")
        customer = conv.get("customer_name", "")
        phone = conv.get("phone_number", "")
        summary = conv.get("conversation_summary", "")

        all_lines.append(f"--- Conversation {conv_id} ---")
        if customer:
            all_lines.append(f"Customer: {customer}")
        if phone:
            all_lines.append(f"Phone: {phone}")
        if summary:
            all_lines.append(f"Summary: {summary}")
        all_lines.append("")

        # Extract messages
        messages = conv.get("messages", [])
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            direction = msg.get("direction", msg.get("source", ""))
            text = msg.get("text_body", msg.get("content", msg.get("text", msg.get("body", ""))))
            if not text:
                continue
            role = "Cliente" if direction in ("inbound", "customer") else "Agente"
            all_lines.append(f"{role}: {text}")
        all_lines.append("")

    return "\n".join(all_lines)


def _extract_messages(messages: list) -> str:
    """Extract text from a flat messages array."""
    lines = []
    for msg in messages:
        if isinstance(msg, str):
            lines.append(msg)
        elif isinstance(msg, dict):
            role = msg.get("role", msg.get("sender", msg.get("from", msg.get("direction", ""))))
            content = msg.get("content", msg.get("text", msg.get("message", msg.get("body", msg.get("text_body", "")))))
            if role and content:
                lines.append(f"{role}: {content}")
            elif content:
                lines.append(str(content))
            else:
                lines.append(json.dumps(msg, ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@app.post("/api/anonymize", response_model=AnonymizeResponse)
async def anonymize_file(file: UploadFile, config: str = Form(default=None)):
    text = await _read_file(file)
    result = anonymize(text)
    total = sum(result.replacement_counts.values())
    return AnonymizeResponse(
        anonymized_text=result.anonymized_text,
        replacement_counts=result.replacement_counts,
        total_replacements=total,
    )


@app.post("/api/anonymize/preview", response_model=PreviewResponse)
async def preview_file(file: UploadFile, config: str = Form(default=None)):
    text = await _read_file(file)
    result = anonymize(text)
    total = sum(result.replacement_counts.values())
    return PreviewResponse(
        original_text=text,
        anonymized_text=result.anonymized_text,
        replacement_counts=result.replacement_counts,
        total_replacements=total,
    )
