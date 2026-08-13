from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
import asyncio
from dataclasses import replace
import uuid

from mewcode.prompting import PromptPackage
from mewcode.providers.base import (
    ChatMessage,
    LLMProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderEvent,
    ProviderFinished,
    ProviderTextDelta,
    ProviderToolCall,
)
from mewcode.tools import ToolExecution

from .events import make_event
from .models import HookEvent
from .runtime import HookRuntime


class HookedProvider:
    def __init__(
        self,
        provider: LLMProvider,
        runtime: HookRuntime,
        profile_name: str,
    ) -> None:
        self._provider = provider
        self._runtime = runtime
        self.profile_name = profile_name

    async def stream_reply(self, request: ModelRequest) -> AsyncIterator[ProviderEvent]:
        message_id = uuid.uuid4().hex
        scope = self._runtime.scope
        base = {
            "id": message_id,
            "component": str(scope.get("component", "agent")),
            "profile": self.profile_name,
            "run_id": scope.get("run_id"),
            "iteration": scope.get("iteration"),
            "message_count": len(request.messages),
            "tool_count": len(request.tools.list()) if request.tools is not None else 0,
            "max_output_tokens": request.max_output_tokens,
        }
        before = make_event(
            HookEvent.MESSAGE_BEFORE,
            workspace=self._runtime.workspace,
            session_id=self._runtime.session_id,
            resumed=self._runtime.resumed,
            values={
                "turn": {"id": scope.get("turn_id"), "mode": scope.get("mode")},
                "message": base,
            },
        )
        await self._runtime.dispatch(before)
        prompts = self._runtime.consume_prompt_context()
        actual_request = request
        if prompts:
            section = "## Hook Context\n\n" + "\n\n".join(prompts)
            dynamic = request.prompt.dynamic_system
            combined = f"{dynamic}\n\n{section}" if dynamic else section
            actual_request = replace(
                request,
                prompt=PromptPackage(request.prompt.stable_system, combined),
            )
        response_parts: list[str] = []
        response_chars = 0
        finish_reason: str | None = None
        status = "success"
        error_kind: str | None = None
        try:
            async for provider_event in self._provider.stream_reply(actual_request):
                if isinstance(provider_event, ProviderTextDelta) and response_chars < 4096:
                    remaining = 4096 - response_chars
                    response_parts.append(provider_event.text[:remaining])
                    response_chars += len(provider_event.text[:remaining])
                elif isinstance(provider_event, ProviderFinished):
                    finish_reason = provider_event.reason.value
                yield provider_event
        except asyncio.CancelledError:
            status = "cancelled"
            error_kind = "CancelledError"
            raise
        except BaseException as exc:
            status = "failure"
            error_kind = type(exc).__name__
            await self._runtime.system_error("provider", exc)
            raise
        finally:
            after_values = dict(base)
            after_values.update(
                {
                    "status": status,
                    "finish_reason": finish_reason,
                    "response_summary": "".join(response_parts),
                    "error": error_kind,
                }
            )
            after = make_event(
                HookEvent.MESSAGE_AFTER,
                workspace=self._runtime.workspace,
                session_id=self._runtime.session_id,
                resumed=self._runtime.resumed,
                values={
                    "turn": {"id": scope.get("turn_id"), "mode": scope.get("mode")},
                    "message": after_values,
                },
            )
            await self._runtime.dispatch(after)

    def assistant_messages(
        self, response: ModelResponse, group_id: str | None = None
    ) -> list[ChatMessage]:
        return self._provider.assistant_messages(response, group_id)

    def tool_result_messages(
        self,
        executions: Sequence[ToolExecution],
        group_id: str | None = None,
    ) -> list[ChatMessage]:
        return self._provider.tool_result_messages(executions, group_id)
