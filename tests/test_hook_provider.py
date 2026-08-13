from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.hooks.models import (
    CommandHookAction,
    HookCatalog,
    HookEvent,
    HookRule,
    HookRuleKey,
    HookSource,
    PromptHookAction,
)
from mewcode.hooks.provider import HookedProvider
from mewcode.hooks.runtime import HookRuntime
from mewcode.prompting import PromptPackage
from mewcode.providers import (
    CaptureOnlyRequestBoundary,
    ModelRequest,
    ProviderError,
    ProviderTextDelta,
    RequestBoundaryProvider,
    RequestSnapshotSlot,
    bind_request_boundary,
)
from fakes import ScriptedAsyncProvider, collect_async


class NoopExecutor:
    async def execute(self, rule, envelope, *, expects_decision):
        raise AssertionError("prompt rules do not call the external executor")

    async def close(self):
        return None


def _runtime(tmp_path: Path) -> HookRuntime:
    rules = (
        HookRule(HookRuleKey(HookSource.USER, Path("h"), 0), HookEvent.MESSAGE_BEFORE, None, PromptHookAction("injected")),
    )
    return HookRuntime(
        HookCatalog(rules, MappingProxyType({HookEvent.MESSAGE_BEFORE: rules})),
        NoopExecutor(),
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )


def test_before_prompt_is_injected_into_current_request(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[ProviderTextDelta("ok")]])
    hooked = HookedProvider(provider, _runtime(tmp_path), "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())
    events = asyncio.run(collect_async(hooked.stream_reply(request)))
    assert events
    assert provider.calls[0].prompt.stable_system == "stable"
    assert "## Hook Context" in provider.calls[0].prompt.dynamic_system
    assert "injected" in provider.calls[0].prompt.dynamic_system
    assert request.prompt.dynamic_system == "dynamic"


def test_request_boundary_observes_hook_injection(tmp_path: Path) -> None:
    inner = ScriptedAsyncProvider([[ProviderTextDelta("ok")]])
    hooked = HookedProvider(RequestBoundaryProvider(inner), _runtime(tmp_path), "main")
    slot = RequestSnapshotSlot()

    with bind_request_boundary(CaptureOnlyRequestBoundary(slot)):
        asyncio.run(
            collect_async(
                hooked.stream_reply(ModelRequest(PromptPackage("stable", "dynamic"), ()))
            )
        )

    assert slot.request is inner.calls[0]
    assert "## Hook Context" in slot.request.prompt.dynamic_system
    assert "injected" in slot.request.prompt.dynamic_system


def test_subagent_provider_consumes_only_its_partition_and_defers_fork_prefix(
    tmp_path: Path,
) -> None:
    inner = ScriptedAsyncProvider(
        [[ProviderTextDelta("first")], [ProviderTextDelta("second")]]
    )
    runtime = _runtime(tmp_path)
    hooked = HookedProvider(inner, runtime, "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())

    async def scenario() -> None:
        with runtime.bind_scope(
            subagent_task_id="task-a",
            parent_run_id="parent",
            component="subagent",
            preserve_fork_prefix=True,
        ):
            await collect_async(hooked.stream_reply(request))
            await collect_async(hooked.stream_reply(request))

    asyncio.run(scenario())

    assert "## Hook Context" not in inner.calls[0].prompt.dynamic_system
    assert "## Hook Context" in inner.calls[1].prompt.dynamic_system
    assert runtime.consume_prompt_context() == ()
    assert runtime.consume_prompt_context("task-a") == ()


def test_empty_runtime_passes_original_request_object(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[]])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    request = ModelRequest(PromptPackage("stable", "dynamic"), ())
    asyncio.run(collect_async(hooked.stream_reply(request)))
    assert provider.calls[0] is request


def test_provider_error_propagates(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([ProviderError("failed")])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    with pytest.raises(ProviderError):
        asyncio.run(collect_async(hooked.stream_reply(ModelRequest(PromptPackage("", ""), ()))))


def test_provider_failure_emits_one_system_error_and_paired_after(tmp_path: Path) -> None:
    class Executor:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def execute(self, rule, envelope, *, expects_decision):
            import json

            event = json.loads(envelope.encoded)["event"]
            self.events.append(event)
            if event == "system.error":
                raise RuntimeError("Hook failure must not recurse")
            from mewcode.hooks import HookActionOutcome, HookOutcomeKind

            return HookActionOutcome(HookOutcomeKind.SUCCESS)

        async def close(self):
            return None

    rules = tuple(
        HookRule(
            HookRuleKey(HookSource.USER, Path("h"), index),
            event,
            None,
            CommandHookAction("ignored"),
        )
        for index, event in enumerate((HookEvent.SYSTEM_ERROR, HookEvent.MESSAGE_AFTER))
    )
    executor = Executor()
    runtime = HookRuntime(
        HookCatalog(
            rules,
            MappingProxyType(
                {event: tuple(rule for rule in rules if rule.event is event) for event in (HookEvent.SYSTEM_ERROR, HookEvent.MESSAGE_AFTER)}
            ),
        ),
        executor,
        workspace=tmp_path,
        session_id="s",
        project_trusted=True,
    )
    hooked = HookedProvider(
        ScriptedAsyncProvider([ProviderError("failed")]), runtime, "main"
    )
    with pytest.raises(ProviderError):
        asyncio.run(
            collect_async(
                hooked.stream_reply(ModelRequest(PromptPackage("", ""), ()))
            )
        )
    assert executor.events == ["system.error", "message.after"]


def test_delegate_message_conversion(tmp_path: Path) -> None:
    provider = ScriptedAsyncProvider([[]])
    hooked = HookedProvider(provider, HookRuntime.empty(tmp_path, "s"), "main")
    delegated = hooked.tool_result_messages([], "g")
    assert delegated == provider.tool_result_messages([], "g")
