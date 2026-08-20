from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any

from mewcode.agent import AgentInboundBatch
from mewcode.providers import ChatMessage, MessageKind

from .mailbox import TeamMailboxService
from .models import TeamActor, TeamMessage

MAX_INBOUND_BATCH_BYTES = 32 * 1024
MAX_INBOUND_BODY_BYTES = 8 * 1024
MAX_PAYLOAD_DEPTH = 5


def render_inbound_batch(
    messages: Sequence[TeamMessage],
    *,
    max_batch_bytes: int = MAX_INBOUND_BATCH_BYTES,
) -> AgentInboundBatch | None:
    """Render mailbox records as bounded, untrusted user-role context."""
    if max_batch_bytes < 512:
        raise ValueError("max_batch_bytes is too small")
    rendered: list[ChatMessage] = []
    selected_ids: list[str] = []
    used = 0
    for item in messages:
        body = _truncate_utf8(item.body, MAX_INBOUND_BODY_BYTES)
        content = {
            "boundary": "untrusted_team_peer_message",
            "message_id": item.message_id,
            "sender_id": item.sender_id,
            "summary": item.summary,
            "protocol": item.protocol.value,
            "body": body,
            "payload": _safe_json(item.payload),
        }
        encoded_size = len(
            json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if rendered and used + encoded_size > max_batch_bytes:
            break
        if encoded_size > max_batch_bytes:
            content["body"] = _truncate_utf8(body, max(0, max_batch_bytes // 4))
            content["payload"] = {"truncated": True}
        rendered.append(ChatMessage("user", content, MessageKind.TEAM_INBOUND))
        selected_ids.append(item.message_id)
        used += encoded_size
    if not rendered:
        return None
    digest = hashlib.sha256("\x00".join(selected_ids).encode("utf-8")).hexdigest()[:32]
    return AgentInboundBatch(digest, tuple(rendered), tuple(selected_ids))


class _MailboxInboundSource:
    def __init__(
        self,
        mailbox: TeamMailboxService,
        actor: TeamActor,
        *,
        page_limit: int = 100,
        max_batch_bytes: int = MAX_INBOUND_BATCH_BYTES,
    ) -> None:
        self._mailbox = mailbox
        self._actor = actor
        self._page_limit = page_limit
        self._max_batch_bytes = max_batch_bytes

    async def poll(
        self,
        committed_ids: frozenset[str],
    ) -> AgentInboundBatch | None:
        page = self._mailbox.list(
            self._actor,
            unread_only=True,
            limit=self._page_limit,
        )
        repair_ids = tuple(
            item.message_id
            for item in page.messages
            if item.message_id in committed_ids
        )
        if repair_ids:
            await self._mailbox.mark_read(self._actor, repair_ids)
        fresh = tuple(
            item for item in page.messages if item.message_id not in committed_ids
        )
        return render_inbound_batch(fresh, max_batch_bytes=self._max_batch_bytes)

    async def acknowledge(self, batch: AgentInboundBatch) -> None:
        await self._mailbox.mark_read(self._actor, batch.mailbox_message_ids)


class LeadInboundSource(_MailboxInboundSource):
    pass


class MemberInboundSource(_MailboxInboundSource):
    pass


def _truncate_utf8(value: str, limit: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= limit:
        return value
    marker = "\n[truncated]"
    room = max(0, limit - len(marker.encode("utf-8")))
    return raw[:room].decode("utf-8", errors="ignore") + marker


def _safe_json(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_PAYLOAD_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str):
            return _truncate_utf8(value, 2048)
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                result["truncated"] = True
                break
            if isinstance(key, str):
                result[key[:128]] = _safe_json(item, depth + 1)
        return result
    if isinstance(value, (tuple, list)):
        return [_safe_json(item, depth + 1) for item in value[:32]]
    return f"[{type(value).__name__} omitted]"
