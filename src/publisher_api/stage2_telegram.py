from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def approval_message(preview: dict[str, Any]) -> str:
    title = preview.get("draft_title") or "Untitled draft"
    return (
        "Approval required\n\n"
        f"Draft: {title}\n"
        f"Revision: {preview['revision_number']}\n"
        f"Characters: {preview['text_length']}\n"
        f"SHA-256: {preview['revision_sha256_prefix']}…\n"
        f"Expires: {preview['expires_at']}\n\n"
        f"{preview['exact_text']}\n\n"
        "Publishing starts immediately after approval."
    )


def result_message(status: str, *, timestamp: datetime, identifier_present: bool) -> str:
    if status == "PUBLISHED":
        return (
            f"PUBLISHED\nTimestamp: {timestamp.isoformat()}\n"
            f"Post identifier received: {'YES' if identifier_present else 'NO'}"
        )
    if status == "PUBLISH_UNCERTAIN":
        return (
            "PUBLISH_UNCERTAIN\nAutomatic retry is forbidden. Check the LinkedIn profile manually."
        )
    return f"{status}\nNo automatic retry is available."


@dataclass
class FakeTelegramGateway:
    fail_send: bool = False
    calls: list[dict[str, object]] = field(default_factory=list)

    def send(self, *, text: str, callback_actions: list[str]) -> str:
        self.calls.append(
            {
                "operation": "send",
                "text_length": len(text),
                "callback_actions": list(callback_actions),
            }
        )
        if self.fail_send:
            raise RuntimeError("Synthetic Telegram delivery failure")
        return "fake-message-1"

    def edit(self, *, message_id: str, text: str) -> None:
        self.calls.append(
            {
                "operation": "edit",
                "message_id_present": bool(message_id),
                "text_length": len(text),
            }
        )

    def acknowledge_callback(self) -> None:
        self.calls.append({"operation": "acknowledge_callback"})
