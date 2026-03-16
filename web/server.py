#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import (
    AWS_REGION,
    MODEL_ID,
    MAX_TOKENS,
    TEMPERATURE,
    ORCHESTRATOR_SYSTEM_PROMPT,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("benefits-web")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="BenefitsNavigator")

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "benefits_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.on_event("startup")
async def _startup_init_vector_store():
    """Pre-load the vector store with embeddings on server startup."""
    loop = asyncio.get_event_loop()
    try:
        from tools.vector_store import initialize
        await loop.run_in_executor(None, initialize)
        log.info("Vector store initialized on startup.")
    except Exception as e:
        log.warning("Vector store init skipped (will use keyword fallback): %s", e)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Track uploaded files: file_id -> {path, filename, content_type}
_uploaded_files: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept a file upload, save it, return a file_id."""
    allowed = {".pdf", ".png", ".jpg", ".jpeg"}
    ext = Path(file.filename or "file").suffix.lower()
    if ext not in allowed:
        return {"error": f"Unsupported file type: {ext}. Allowed: {', '.join(allowed)}"}

    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{ext}"

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB limit
        return {"error": "File too large. Maximum size is 20 MB."}

    with open(save_path, "wb") as f:
        f.write(content)

    _uploaded_files[file_id] = {
        "path": str(save_path),
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
    }

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": len(content),
    }


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def _create_agent():
    """Create a fresh Strands orchestrator agent."""
    from strands import Agent
    from strands.models import BedrockModel
    from tools import (
        intake_interview,
        check_eligibility,
        create_action_plan,
        search_benefits_kb,
        analyze_document,
        suggest_followup,
    )

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        streaming=False,
    )

    agent = Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[
            intake_interview,
            check_eligibility,
            create_action_plan,
            search_benefits_kb,
            analyze_document,
            suggest_followup,
        ],
    )
    return agent


# ---------------------------------------------------------------------------
# Extract tool results from agent.messages
# ---------------------------------------------------------------------------

def _extract_tool_results(agent) -> tuple[dict | None, dict | None]:
    """Walk agent.messages to find the latest toolResult blocks.

    The Strands SDK appends tool results to agent.messages as user-role
    messages with content blocks like:
        {"toolResult": {"content": [{"text": "..."}], "status": "success", ...}}

    Returns (eligibility_data, profile_data).
    """
    eligibility_data = None
    profile_data = None

    messages = getattr(agent, "messages", None)
    if not messages:
        return None, None

    # Walk messages in reverse to find the most recent tool results
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            tool_result = block.get("toolResult")
            if not tool_result:
                continue
            if tool_result.get("status") != "success":
                continue

            # Extract text from the toolResult content
            text = ""
            for content_item in tool_result.get("content", []):
                if "text" in content_item:
                    text = content_item["text"]
                    break

            if not text:
                continue

            # Try to parse as JSON
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue

            # Check if this is eligibility data
            if not eligibility_data and "likely_eligible" in data:
                eligibility_data = data
                log.info("Found eligibility data in agent messages (%d programs)", data.get("total_programs_checked", 0))

            # Check if this is profile data
            if not profile_data and any(k in data for k in ("household_size", "annual_income", "state", "employment_status")):
                # Make sure it's not the eligibility result (which also may contain these if embedded)
                if "likely_eligible" not in data:
                    profile_data = data
                    log.info("Found profile data in agent messages")

            # Stop once we have both
            if eligibility_data and profile_data:
                return eligibility_data, profile_data

    return eligibility_data, profile_data


def _invoke_agent(agent, message: str) -> tuple[str, dict | None, dict | None]:
    """Call the agent synchronously (intended to run in a thread).

    Returns (response_text, eligibility_data_or_None, profile_data_or_None).
    """
    # Record how many messages exist before the call so we only scan new ones
    msgs_before = len(getattr(agent, "messages", []))

    result = agent(message)
    response_text = str(result)

    # Extract tool results from new messages appended during this call
    eligibility_data, profile_data = _extract_tool_results(agent)

    log.info(
        "Agent call done. eligibility=%s, profile=%s, response_len=%d",
        eligibility_data is not None,
        profile_data is not None,
        len(response_text),
    )

    return response_text, eligibility_data, profile_data


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()

    # Per-connection session state
    agent = None
    citizen_profile: dict = {}
    programs: list[dict] = []
    loop = asyncio.get_event_loop()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "text": "Invalid JSON"})
                continue

            if data.get("type") != "message":
                continue

            user_text = data.get("text", "").strip()
            file_ids = data.get("file_ids", [])

            if not user_text and not file_ids:
                continue

            # Lazy-init agent on first message
            if agent is None:
                try:
                    await ws.send_json({"type": "typing", "active": True})
                    agent = await loop.run_in_executor(None, _create_agent)
                except Exception as e:
                    await ws.send_json({
                        "type": "agent_message",
                        "text": _format_init_error(e),
                    })
                    await ws.send_json({"type": "typing", "active": False})
                    continue

            # Build prompt with file context
            prompt_parts = []
            doc_filenames = []

            for fid in file_ids:
                finfo = _uploaded_files.get(fid)
                if finfo:
                    doc_filenames.append(finfo["filename"])
                    prompt_parts.append(
                        f"[The user uploaded a document: \"{finfo['filename']}\" "
                        f"(saved at {finfo['path']}). Please use the analyze_document "
                        f"tool to read it and extract relevant information.]"
                    )

            if user_text:
                prompt_parts.append(user_text)

            full_prompt = "\n\n".join(prompt_parts)

            # Send typing indicator
            await ws.send_json({"type": "typing", "active": True})

            eligibility_data = None
            profile_data = None
            try:
                response_text, eligibility_data, profile_data = await loop.run_in_executor(
                    None, _invoke_agent, agent, full_prompt
                )
            except Exception as e:
                response_text = f"I'm sorry, I encountered an error: {str(e)}"

            await ws.send_json({"type": "typing", "active": False})

            # --- Update session profile ---
            if profile_data:
                citizen_profile.update(
                    {k: v for k, v in profile_data.items() if v is not None}
                )
                await ws.send_json({
                    "type": "profile_update",
                    "profile": citizen_profile,
                })

            # --- Send benefits from tool results found in agent.messages ---
            if eligibility_data:
                programs = _flatten_benefits(eligibility_data)
                log.info("Sending benefits_update with %d programs", len(programs))
                await ws.send_json({
                    "type": "benefits_update",
                    "programs": programs,
                })

            # --- Fallback: if tool results weren't found but agent discussed
            #     eligibility, run the rules engine directly ---
            if not eligibility_data and citizen_profile and _response_mentions_eligibility(response_text):
                log.info("Fallback: running eligibility directly with stored profile")
                fallback_programs = await loop.run_in_executor(
                    None, _run_eligibility_directly, citizen_profile
                )
                if fallback_programs:
                    programs = fallback_programs
                    await ws.send_json({
                        "type": "benefits_update",
                        "programs": programs,
                    })

            # Send agent message (after benefits so panel updates first)
            await ws.send_json({
                "type": "agent_message",
                "text": response_text,
                "documents": doc_filenames,
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("WebSocket error: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ELIGIBILITY_KEYWORDS = [
    "snap", "medicaid", "medi-cal", "calfresh", "calworks", "chip",
    "wic", "liheap", "section 8", "eitc", "pell grant", "tanf",
    "ssi", "lifeline", "capi", "care",
    "likely eligible", "may qualify", "not eligible",
    "eligibility", "you may qualify", "you might qualify",
]


def _response_mentions_eligibility(text: str) -> bool:
    """Check if the agent response discusses eligibility results."""
    lower = text.lower()
    matches = sum(1 for kw in _ELIGIBILITY_KEYWORDS if kw in lower)
    return matches >= 3


def _run_eligibility_directly(profile: dict) -> list[dict] | None:
    try:
        from tools.rules_engine import check_program_eligibility
        from tools.eligibility import _load_programs

        state = profile.get("state")
        all_programs = _load_programs(state)

        likely, possibly, not_elig = [], [], []
        for program in all_programs:
            result = check_program_eligibility(profile, program)
            entry = {
                "program_name": program["name"],
                "short_name": program.get("short_name", program["name"]),
                "category": program.get("category", "other"),
                "confidence": result["confidence"],
                "reason": result["reason"],
                "estimated_benefit": result["estimated_benefit"],
                "application_url": program.get("application_url", ""),
            }
            if result["eligible"] and result["confidence"] == "high":
                likely.append(entry)
            elif result["eligible"]:
                possibly.append(entry)
            else:
                not_elig.append(entry)

        raw = {
            "likely_eligible": likely,
            "possibly_eligible": possibly,
            "not_eligible": not_elig,
        }
        return _flatten_benefits(raw)
    except Exception:
        log.exception("Fallback eligibility failed")
        return None


def _flatten_benefits(data: dict) -> list[dict]:
    programs = []

    for status_label, group_key in [
        ("likely", "likely_eligible"),
        ("possible", "possibly_eligible"),
        ("not_eligible", "not_eligible"),
    ]:
        for prog in data.get(group_key, []):
            programs.append({
                "name": prog.get("short_name") or prog.get("program_name", "Unknown"),
                "category": prog.get("category", "other"),
                "benefit": prog.get("estimated_benefit", ""),
                "confidence": prog.get("confidence", "low"),
                "reason": prog.get("reason", ""),
                "apply_url": prog.get("application_url", ""),
                "status": status_label,
            })

    return programs


def _format_init_error(e: Exception) -> str:
    msg = str(e)
    if "credentials" in msg.lower() or "ExpiredToken" in msg:
        return (
            "**AWS credentials not found or expired.**\n\n"
            "Please configure your AWS credentials:\n"
            "```\naws configure\n```\n"
            "Or set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables."
        )
    if "AccessDenied" in msg:
        return (
            "**Access denied to Amazon Nova 2 Lite.**\n\n"
            "Please enable the model in the AWS Bedrock console:\n"
            "1. Go to Amazon Bedrock → Model access\n"
            "2. Enable **Amazon Nova 2 Lite**\n"
            f"3. Make sure you're in the `{AWS_REGION}` region"
        )
    return f"**Failed to initialize the AI agent:** {msg}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  BenefitsNavigator Web UI")
    print(f"  http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
