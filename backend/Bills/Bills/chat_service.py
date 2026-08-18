"""Talks to OpenAI to answer chat questions about the user's bills/receipts, backed by a summary of their data."""
from __future__ import annotations

import json as std_json
import os
from collections import defaultdict

import requests
from django.db import transaction

from .models import BillDocument, ChatConversation, ChatMessage

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4.1-mini"
OPENAI_TIMEOUT_SECONDS = 60
CHAT_CONTEXT_LIMIT = 250
CHAT_RECENT_ITEMS_LIMIT = 50
CHAT_TOP_CATEGORY_LIMIT = 8


class ChatServiceError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def ensure_session_key(request) -> str:
    session_key = request.session.session_key
    if session_key:
        return session_key

    # Django doesn't hand out a session ID until something's actually saved to it.
    request.session.save()
    return request.session.session_key or ""


def get_or_create_conversation(session_key: str) -> ChatConversation:
    conversation, _ = ChatConversation.objects.get_or_create(session_key=session_key)
    return conversation


def _build_chat_context_payload() -> dict:
    """Puts together a summary of the user's bills/receipts (totals, categories, recent items) to hand to the AI model, since it can't look at the database itself."""
    documents = list(BillDocument.objects.order_by("-msg_date", "-id")[:CHAT_CONTEXT_LIMIT])

    category_totals = defaultdict(float)
    month_totals = defaultdict(float)
    document_type_counts = defaultdict(int)
    recent_items = []

    amount_total = 0.0
    amount_count = 0
    latest_msg_date = None

    for document in documents:
        document_type = document.document_type or "unknown"
        document_type_counts[document_type] += 1

        if document.msg_date and (latest_msg_date is None or document.msg_date > latest_msg_date):
            latest_msg_date = document.msg_date

        if len(recent_items) < CHAT_RECENT_ITEMS_LIMIT:
            recent_items.append(
                {
                    "id": document.id,
                    "document_type": document_type,
                    "subject": document.subject,
                    "sender": document.sender,
                    "category": document.category,
                    "amount_value": document.amount_value,
                    "amount_currency": document.amount_currency,
                    "msg_date": document.msg_date.isoformat() if document.msg_date else None,
                    "vendor": document.vendor,
                }
            )

        if document.amount_value is None:
            continue

        amount = float(document.amount_value)
        amount_total += amount
        amount_count += 1

        category = (document.category or "uncategorized").strip() or "uncategorized"
        category_totals[category] += amount

        if document.msg_date:
            month_key = document.msg_date.strftime("%Y-%m")
            month_totals[month_key] += amount

    top_categories = [
        {"category": category, "amount_total": round(total, 2)}
        for category, total in sorted(
            category_totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:CHAT_TOP_CATEGORY_LIMIT]
    ]

    monthly_totals = [
        {"month": month, "amount_total": round(total, 2)}
        for month, total in sorted(month_totals.items())[-12:]
    ]

    return {
        "documents_count": len(documents),
        "documents_with_amount": amount_count,
        "amount_total": round(amount_total, 2),
        "latest_msg_date": latest_msg_date.isoformat() if latest_msg_date else None,
        "document_type_counts": dict(document_type_counts),
        "top_categories": top_categories,
        "monthly_totals": monthly_totals,
        "recent_items": recent_items,
    }


def _build_chat_instructions(context_payload: dict) -> str:
    """Bundles the summary data into the model's instructions, so it answers from real numbers instead of guessing."""
    return (
        "You are a finance assistant inside a bills dashboard app. "
        "Answer in Hebrew by default, unless the user clearly asks in another language. "
        "Use only the data in CONTEXT_JSON for numeric claims. "
        "If data is missing, state that clearly.\n"
        f"CONTEXT_JSON={std_json.dumps(context_payload, ensure_ascii=False)}"
    )


def _extract_openai_text(response_payload: dict) -> str:
    """OpenAI's reply can come in a couple different shapes — this handles both, and falls back to any refusal message the model gave."""
    direct_text = response_payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    chunks = []
    for output_item in response_payload.get("output") or []:
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content") or []:
            if not isinstance(content_item, dict):
                continue

            if content_item.get("type") == "output_text":
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())

            if content_item.get("type") == "refusal":
                refusal_text = content_item.get("refusal")
                if isinstance(refusal_text, str) and refusal_text.strip():
                    chunks.append(refusal_text.strip())

    return "\n".join(chunks).strip()


def _extract_openai_error(response_payload: dict) -> str:
    error_payload = response_payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    if isinstance(error_payload, str) and error_payload.strip():
        return error_payload.strip()

    return "OpenAI API request failed"


def _send_openai_request(*, message: str, instructions: str, model: str, previous_response_id: str) -> dict:
    """Sends the message to OpenAI and returns its reply, turning any network/response problem into a clean error."""
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ChatServiceError("OPENAI_API_KEY is not configured on the server", status_code=500)

    openai_request_payload = {
        "model": model,
        "instructions": instructions,
        "input": message,
    }
    if previous_response_id:
        openai_request_payload["previous_response_id"] = previous_response_id

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    project_id = (os.getenv("OPENAI_PROJECT_ID") or "").strip()
    if project_id:
        headers["OpenAI-Project"] = project_id

    organization_id = (os.getenv("OPENAI_ORGANIZATION_ID") or "").strip()
    if organization_id:
        headers["OpenAI-Organization"] = organization_id

    try:
        openai_response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=openai_request_payload,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ChatServiceError(f"Failed to reach OpenAI API: {exc}", status_code=502) from exc

    try:
        response_payload = openai_response.json()
    except ValueError as exc:
        raise ChatServiceError("Invalid JSON response from OpenAI API", status_code=502) from exc

    if openai_response.status_code >= 400:
        raise ChatServiceError(
            _extract_openai_error(response_payload),
            status_code=502,
        )

    return response_payload


def handle_chat_message(
    *,
    conversation: ChatConversation,
    message: str,
    previous_response_id: str | None = None,
) -> dict:
    """Saves the user's message, asks OpenAI for a reply using their bill/receipt summary as context, saves that reply, and returns it."""
    message_text = (message or "").strip()
    if not message_text:
        raise ChatServiceError("message is required", status_code=400)

    ChatMessage.objects.create(
        conversation=conversation,
        role=ChatMessage.Role.USER,
        text=message_text,
    )

    context_payload = _build_chat_context_payload()
    instructions = _build_chat_instructions(context_payload)
    model = (os.getenv("OPENAI_CHAT_MODEL") or DEFAULT_OPENAI_CHAT_MODEL).strip()
    # Prefer the ID the frontend just sent; otherwise carry on from the last one we saved.
    effective_previous_response_id = (
        (previous_response_id or "").strip() or (conversation.previous_response_id or "")
    )

    response_payload = _send_openai_request(
        message=message_text,
        instructions=instructions,
        model=model,
        previous_response_id=effective_previous_response_id,
    )

    answer = _extract_openai_text(response_payload)
    if not answer:
        answer = "No textual response was returned from the model."

    response_id = response_payload.get("id")
    model_name = response_payload.get("model") or model

    with transaction.atomic():
        update_fields = []

        if response_id and response_id != conversation.previous_response_id:
            conversation.previous_response_id = response_id
            update_fields.append("previous_response_id")

        if model_name and model_name != conversation.model_name:
            conversation.model_name = model_name
            update_fields.append("model_name")

        if update_fields:
            conversation.save(update_fields=[*update_fields, "updated_at"])

        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.Role.ASSISTANT,
            text=answer,
            openai_response_id=response_id,
            metadata={
                "model": model_name,
            },
        )

    return {
        "ok": True,
        "answer": answer,
        "response_id": response_id,
        "model": model_name,
    }
