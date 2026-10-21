"""POST /chat — bounded, source-grounded works guide on EdgeOne Makers.

The existing compatible gateway and model environment are retained. The model
is initialized only when explicitly using model mode; extract mode makes no
model request. No raw model text reaches visitors before citation validation.
Conversation memory is bounded browser-supplied context, never factual evidence.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncGenerator

from .._guide import (
    COPY, GuideError, MODEL_INSTRUCTIONS, extract_answer, get_knowledge,
    is_injection, model_prompt, request_boundary, validate_model_answer, validate_request,
)
from .._logger import create_logger

logger = create_logger("works-guide")
MODEL_TIMEOUT_SECONDS = 45


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_model(prompt: str, cancel_signal: asyncio.Event | None, runtime_env: Any = None) -> str:
    # Lazy imports allow a useful, explicit unavailable state without credentials
    # and let free offline validation run without loading the SDK at all.
    from dotenv import load_dotenv
    load_dotenv()
    def env(name: str, default: str | None = None) -> str | None:
        if runtime_env is not None:
            try:
                value = runtime_env.get(name) if hasattr(runtime_env, "get") else getattr(runtime_env, name, None)
                if value:
                    return str(value)
            except (AttributeError, TypeError):
                pass
        return os.getenv(name, default)
    key = env("AI_GATEWAY_API_KEY")
    base_url = env("AI_GATEWAY_BASE_URL")
    if not key or not base_url:
        raise GuideError("config")

    from openai import AsyncOpenAI
    from openai.types.responses import ResponseTextDeltaEvent
    from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, RunConfig

    client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=40, max_retries=0)
    model = OpenAIChatCompletionsModel(
        model=env("AI_GATEWAY_MODEL", "@makers/deepseek-v4-flash"), openai_client=client,
    )
    agent = Agent(name="Public works guide", instructions=MODEL_INSTRUCTIONS, model=model,
                  model_settings=ModelSettings(max_tokens=2400, store=False), tools=[])
    result = None
    pending = None
    cancel_wait = None
    try:
        result = Runner.run_streamed(
            agent, input=prompt, max_turns=1,
            run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False),
        )
        events = result.stream_events().__aiter__()
        chunks: list[str] = []
        size = 0
        if cancel_signal:
            cancel_wait = asyncio.create_task(cancel_signal.wait())
        async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
            while True:
                if cancel_signal and cancel_signal.is_set():
                    raise asyncio.CancelledError()
                pending = asyncio.create_task(anext(events))
                wait_for = [pending] + ([cancel_wait] if cancel_wait else [])
                completed, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)
                if cancel_wait and cancel_wait in completed:
                    raise asyncio.CancelledError()
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    break
                finally:
                    pending = None
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    chunks.append(event.data.delta)
                    size += len(event.data.delta)
                    if size > 16000:
                        raise GuideError("invalid", reason="size")
        return "".join(chunks) or str(result.final_output or "")
    finally:
        # Cancel the actual upstream run as well as the frontend stream.
        if result is not None:
            result.cancel()
        for task in (pending, cancel_wait):
            if task:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        await client.close()


async def handler(context: Any) -> AsyncGenerator[str, None]:
    language = "en" if isinstance(context.request.body, dict) and context.request.body.get("language") == "en" else "zh"
    stopped = False
    signal = getattr(context.request, "signal", None)
    try:
        message, language, site, mode, history = validate_request(context.request.body)
        yield sse_event("answer_meta", {"mode": mode})
        if signal and signal.is_set():
            stopped = True
            return
        if is_injection(message):
            answer, used = COPY[language]["blocked"], []
        elif request_boundary(message) == "private":
            answer, used = COPY[language]["unknown"], []
        elif request_boundary(message) == "unseen":
            answer, used = COPY[language]["unseen"], []
        else:
            knowledge = get_knowledge()
            evidence = knowledge.retrieve(message, history, site, language)
            if not evidence:
                answer, used = COPY[language]["unknown"], []
            elif mode == "extract":
                answer, used = extract_answer(message, evidence, language)
            else:
                raw = await _run_model(model_prompt(message, history, evidence, language), signal, getattr(context, "env", None))
                answer, used = validate_model_answer(raw, evidence, language)
        if signal and signal.is_set():
            stopped = True
            return
        yield sse_event("sources", {"sources": [e.card() for e in used]})
        for offset in range(0, len(answer), 48):
            if signal and signal.is_set():
                stopped = True
                break
            yield sse_event("text_delta", {"delta": answer[offset:offset + 48]})
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        stopped = True
    except GuideError as exc:
        if exc.code == "invalid":
            logger.error("answer_rejected", exc.reason)
        yield sse_event("error", {"code": exc.code, "message": COPY[language].get(exc.code, COPY[language]["upstream"]),
                                  "retryable": exc.retryable})
    except Exception as exc:
        # Never print source/user text, credentials, upstream bodies or raw errors.
        logger.error("request_failed", type(exc).__name__)
        yield sse_event("error", {"code": "upstream", "message": COPY[language]["upstream"], "retryable": True})
    finally:
        yield sse_event("done", {"stopped": stopped})
