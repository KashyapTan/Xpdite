"""
Cloud LLM provider streaming integration with inline tool calling.

Handles streaming responses from Anthropic (Claude), OpenAI, and Google Gemini
with real-time token broadcasting and interleaved MCP tool execution. When a
model requests a tool call mid-stream, the tool is executed and the results are
fed back — the user sees the entire process (text → tool → text → tool → text)
as a continuous, transparent flow.

Same return signature as stream_ollama_chat for drop-in compatibility.
"""

import os
import base64
import json
from typing import List, Dict, Any, Optional, Set

from ..core.connection import broadcast_message
from ..core.state import app_state
from ..config import MAX_MCP_TOOL_ROUNDS, ANTHROPIC_THINKING_KEYWORDS, GEMINI_THINKING_KEYWORDS, CLOUD_MAX_TOKENS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_image_as_base64(path: str) -> Optional[str]:
    """Load an image file and return its base64-encoded content."""
    try:
        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"[Cloud] Failed to load image {path}: {e}")
        return None


def _guess_media_type(path: str) -> str:
    """Guess the MIME type from a file extension."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def _truncate_tool_result(result: str) -> str:
    """Truncate excessively large tool results."""
    from ..config import MAX_TOOL_RESULT_LENGTH
    result_str = str(result)
    if len(result_str) > MAX_TOOL_RESULT_LENGTH:
        print(f"[Cloud] Truncating large tool output ({len(result_str)} chars)")
        return result_str[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
    return result_str


# ---------------------------------------------------------------------------
# Anthropic (Claude) — native async streaming with tool calling
# ---------------------------------------------------------------------------


def _build_anthropic_messages(
    chat_history: List[Dict[str, Any]],
    user_query: str,
    image_paths: List[str],
) -> List[Dict[str, Any]]:
    """Convert chat history to Anthropic message format."""
    messages = []

    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            continue

        if role == "user" and msg.get("images"):
            blocks: list = []
            for img_path in msg["images"]:
                if os.path.exists(img_path):
                    b64 = _load_image_as_base64(img_path)
                    if b64:
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": _guess_media_type(img_path),
                                    "data": b64,
                                },
                            }
                        )
            blocks.append({"type": "text", "text": content})
            messages.append({"role": "user", "content": blocks})
        else:
            messages.append({"role": role, "content": content})

    # Add current user message
    existing_images = [p for p in image_paths if os.path.exists(p)]
    if existing_images:
        blocks = []
        for img_path in existing_images:
            b64 = _load_image_as_base64(img_path)
            if b64:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _guess_media_type(img_path),
                            "data": b64,
                        },
                    }
                )
        blocks.append({"type": "text", "text": user_query})
        messages.append({"role": "user", "content": blocks})
    else:
        messages.append({"role": "user", "content": user_query})

    return messages


async def _stream_anthropic(
    api_key: str,
    model: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from Anthropic's Claude API with interleaved tool calling.

    When the model requests tools, they are executed inline and results are fed
    back. Text is broadcast in real-time throughout, so the user sees the model's
    reasoning between tool calls.
    """
    import anthropic
    from ..mcp_integration.manager import mcp_manager
    from ..mcp_integration.terminal_executor import is_terminal_tool, execute_terminal_tool

    anthropic_msgs = _build_anthropic_messages(chat_history, user_query, image_paths)
    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    thinking_tokens: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    interleaved_blocks: List[Dict[str, Any]] = []
    current_round_text: list[str] = []

    # Get tools in Anthropic format
    tools = None
    if allowed_tool_names:
        all_tools = mcp_manager.get_anthropic_tools()
        if all_tools:
            tools = [t for t in all_tools if t["name"] in allowed_tool_names]
            if not tools:
                tools = None

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=300.0)

        if app_state.stop_streaming:
            return "", total_token_stats, tool_calls_list, None

        rounds = 0
        has_more = True

        while has_more and rounds < MAX_MCP_TOOL_ROUNDS:
            if app_state.stop_streaming:
                break

            ctx = app_state.current_request
            if ctx and ctx.cancelled:
                break

            rounds += 1

            create_kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": CLOUD_MAX_TOKENS,
                "messages": anthropic_msgs,
            }
            if system_prompt:
                create_kwargs["system"] = system_prompt

            # Add thinking support for extended-thinking capable models
            is_thinking_model = any(kw in model for kw in ANTHROPIC_THINKING_KEYWORDS)
            if is_thinking_model:
                create_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 10000,
                }

            if tools:
                create_kwargs["tools"] = tools

            async with client.messages.stream(**create_kwargs) as stream:
                async for event in stream:
                    if app_state.stop_streaming:
                        break

                    if event.type == "content_block_start":
                        block = event.content_block
                        if hasattr(block, "type"):
                            if block.type == "text" and thinking_tokens and not all_accumulated:
                                await broadcast_message("thinking_complete", "")

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "type"):
                            if delta.type == "thinking_delta":
                                thinking_tokens.append(delta.thinking)
                                await broadcast_message("thinking_chunk", delta.thinking)
                            elif delta.type == "text_delta":
                                if thinking_tokens and not all_accumulated:
                                    await broadcast_message("thinking_complete", "")
                                all_accumulated.append(delta.text)
                                current_round_text.append(delta.text)
                                await broadcast_message("response_chunk", delta.text)

                # Get final message for token stats and tool_use detection
                final_message = await stream.get_final_message()
                if final_message and hasattr(final_message, "usage"):
                    usage = final_message.usage
                    total_token_stats["prompt_eval_count"] += getattr(usage, "input_tokens", 0)
                    total_token_stats["eval_count"] += getattr(usage, "output_tokens", 0)

            # Check for tool_use blocks in the final message
            tool_use_blocks = [
                block for block in (final_message.content or [])
                if getattr(block, "type", None) == "tool_use"
            ]

            if tool_use_blocks:
                # Add assistant response to messages (includes text + tool_use blocks)
                anthropic_msgs.append({"role": "assistant", "content": final_message.content})

                if current_round_text:
                    interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})
                    current_round_text = []

                # Execute each tool
                tool_results = []
                for block in tool_use_blocks:
                    fn_name = getattr(block, "name", "")
                    fn_args = getattr(block, "input", None) or {}
                    tool_use_id = getattr(block, "id", "")
                    server_name = mcp_manager.get_tool_server_name(fn_name)

                    print(f"[Cloud/Anthropic] Tool call: {fn_name}({fn_args}) from '{server_name}'")

                    if app_state.stop_streaming:
                        break

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args,
                            "server": server_name, "status": "calling",
                        }),
                    )

                    if is_terminal_tool(fn_name, server_name):
                        result = await execute_terminal_tool(fn_name, fn_args, server_name)
                    else:
                        try:
                            result = await mcp_manager.call_tool(fn_name, dict(fn_args))
                        except Exception as e:
                            result = f"Error executing tool: {e}"

                    result_str = _truncate_tool_result(str(result))

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args, "result": result_str,
                            "server": server_name, "status": "complete",
                        }),
                    )

                    tool_calls_list.append({
                        "name": fn_name, "args": fn_args,
                        "result": result_str, "server": server_name,
                    })
                    interleaved_blocks.append({
                        "type": "tool_call", "name": fn_name,
                        "args": fn_args, "server": server_name,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_str,
                    })

                # Send tool results back for the next round
                anthropic_msgs.append({"role": "user", "content": tool_results})
            else:
                # No tool calls — response is complete
                has_more = False

        if thinking_tokens and not all_accumulated:
            await broadcast_message("thinking_complete", "")

        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))

        if tool_calls_list:
            print(f"[Cloud/Anthropic] Tool loop complete after {rounds} round(s)")
        # Flush any remaining text from the final (non-tool) round
        if current_round_text:
            interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})

        return "".join(all_accumulated), total_token_stats, tool_calls_list, interleaved_blocks or None

    except Exception as e:
        error_msg = f"LLM API error ({type(e).__name__})"
        print(f"[Cloud/Anthropic] Full error: {e}")
        await broadcast_message("error", error_msg)
        return "", {"prompt_eval_count": 0, "eval_count": 0}, tool_calls_list, None


# ---------------------------------------------------------------------------
# OpenAI — native async streaming
# ---------------------------------------------------------------------------


def _build_openai_messages(
    chat_history: List[Dict[str, Any]],
    user_query: str,
    image_paths: List[str],
) -> List[Dict[str, Any]]:
    """Convert chat history to OpenAI message format."""
    messages = []

    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            continue

        if role == "user" and msg.get("images"):
            parts: list = []
            for img_path in msg["images"]:
                if os.path.exists(img_path):
                    b64 = _load_image_as_base64(img_path)
                    if b64:
                        media_type = _guess_media_type(img_path)
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{b64}",
                                },
                            }
                        )
            parts.append({"type": "text", "text": content})
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": role, "content": content})

    # Current user message
    existing_images = [p for p in image_paths if os.path.exists(p)]
    if existing_images:
        parts = []
        for img_path in existing_images:
            b64 = _load_image_as_base64(img_path)
            if b64:
                media_type = _guess_media_type(img_path)
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                        },
                    }
                )
        parts.append({"type": "text", "text": user_query})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_query})

    return messages


async def _stream_openai(
    api_key: str,
    model: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from OpenAI's API with interleaved tool calling.

    Tool call deltas are accumulated during streaming. After the stream ends
    with finish_reason="tool_calls", the tools are executed and results fed
    back for the next streaming round. Text is broadcast continuously.
    """
    from openai import AsyncOpenAI
    from ..mcp_integration.manager import mcp_manager
    from ..mcp_integration.terminal_executor import is_terminal_tool, execute_terminal_tool

    openai_msgs = _build_openai_messages(chat_history, user_query, image_paths)
    if system_prompt:
        openai_msgs.insert(0, {"role": "system", "content": system_prompt})

    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    thinking_tokens: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    interleaved_blocks: List[Dict[str, Any]] = []
    current_round_text: list[str] = []

    # Get tools in OpenAI format
    tools = None
    if allowed_tool_names:
        all_tools = mcp_manager.get_openai_tools()
        if all_tools:
            tools = [t for t in all_tools if t["function"]["name"] in allowed_tool_names]
            if not tools:
                tools = None

    try:
        client = AsyncOpenAI(api_key=api_key, timeout=300.0)

        if app_state.stop_streaming:
            return "", total_token_stats, tool_calls_list, None

        rounds = 0
        has_more = True

        while has_more and rounds < MAX_MCP_TOOL_ROUNDS:
            if app_state.stop_streaming:
                break

            ctx = app_state.current_request
            if ctx and ctx.cancelled:
                break

            rounds += 1

            create_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": openai_msgs,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                create_kwargs["tools"] = tools

            stream = await client.chat.completions.create(**create_kwargs)

            # Accumulate tool call deltas during streaming
            pending_tool_calls: Dict[int, Dict[str, str]] = {}
            finish_reason = None

            async for chunk in stream:
                if app_state.stop_streaming:
                    break

                # Usage-only final chunk
                if not chunk.choices and hasattr(chunk, "usage") and chunk.usage:
                    total_token_stats["prompt_eval_count"] += chunk.usage.prompt_tokens or 0
                    total_token_stats["eval_count"] += chunk.usage.completion_tokens or 0
                    continue

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason or finish_reason

                # Handle reasoning/thinking content (o1, o3 models)
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    thinking_tokens.append(reasoning)
                    await broadcast_message("thinking_chunk", reasoning)

                # Handle regular text content
                if delta.content:
                    if thinking_tokens and not all_accumulated:
                        await broadcast_message("thinking_complete", "")
                    all_accumulated.append(delta.content)
                    current_round_text.append(delta.content)
                    await broadcast_message("response_chunk", delta.content)

                # Accumulate tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in pending_tool_calls:
                            pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            pending_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                pending_tool_calls[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                pending_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            # After stream: check if tool calls were made
            if finish_reason == "tool_calls" and pending_tool_calls:
                # Build assistant message with tool calls
                assistant_tool_calls = []
                for idx in sorted(pending_tool_calls.keys()):
                    tc = pending_tool_calls[idx]
                    assistant_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })

                openai_msgs.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_tool_calls,
                })

                if current_round_text:
                    interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})
                    current_round_text = []

                # Execute each tool
                for tc_info in assistant_tool_calls:
                    fn_name = tc_info["function"]["name"]
                    try:
                        fn_args = json.loads(tc_info["function"]["arguments"]) if tc_info["function"]["arguments"] else {}
                    except json.JSONDecodeError:
                        fn_args = {}

                    server_name = mcp_manager.get_tool_server_name(fn_name)

                    print(f"[Cloud/OpenAI] Tool call: {fn_name}({fn_args}) from '{server_name}'")

                    if app_state.stop_streaming:
                        break

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args,
                            "server": server_name, "status": "calling",
                        }),
                    )

                    if is_terminal_tool(fn_name, server_name):
                        result = await execute_terminal_tool(fn_name, fn_args, server_name)
                    else:
                        try:
                            result = await mcp_manager.call_tool(fn_name, dict(fn_args))
                        except Exception as e:
                            result = f"Error executing tool: {e}"

                    result_str = _truncate_tool_result(str(result))

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args, "result": result_str,
                            "server": server_name, "status": "complete",
                        }),
                    )

                    tool_calls_list.append({
                        "name": fn_name, "args": fn_args,
                        "result": result_str, "server": server_name,
                    })
                    interleaved_blocks.append({
                        "type": "tool_call", "name": fn_name,
                        "args": fn_args, "server": server_name,
                    })

                    openai_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc_info["id"],
                        "content": result_str,
                    })
            else:
                # No tool calls — response is complete
                has_more = False

        if thinking_tokens and not all_accumulated:
            await broadcast_message("thinking_complete", "")

        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))

        if tool_calls_list:
            print(f"[Cloud/OpenAI] Tool loop complete after {rounds} round(s)")
        if current_round_text:
            interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})

        return "".join(all_accumulated), total_token_stats, tool_calls_list, interleaved_blocks or None

    except Exception as e:
        error_msg = f"LLM API error ({type(e).__name__})"
        print(f"[Cloud/OpenAI] Full error: {e}")
        await broadcast_message("error", error_msg)
        return "", {"prompt_eval_count": 0, "eval_count": 0}, tool_calls_list, None


# ---------------------------------------------------------------------------
# Gemini — native async streaming
# ---------------------------------------------------------------------------


def _build_gemini_contents(
    chat_history: List[Dict[str, Any]],
    user_query: str,
    image_paths: List[str],
) -> list:
    """Convert chat history to Gemini content format."""
    from google.genai import types

    contents = []

    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            continue

        # Gemini uses "user" and "model" roles
        gemini_role = "model" if role == "assistant" else "user"

        if role == "user" and msg.get("images"):
            parts = []
            for img_path in msg["images"]:
                if os.path.exists(img_path):
                    b64 = _load_image_as_base64(img_path)
                    if b64:
                        media_type = _guess_media_type(img_path)
                        parts.append(
                            types.Part.from_bytes(
                                data=base64.standard_b64decode(b64),
                                mime_type=media_type,
                            )
                        )
            parts.append(types.Part.from_text(text=content))
            contents.append(types.Content(role=gemini_role, parts=parts))
        else:
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part.from_text(text=content)],
                )
            )

    # Current user message
    existing_images = [p for p in image_paths if os.path.exists(p)]
    if existing_images:
        parts = []
        for img_path in existing_images:
            b64 = _load_image_as_base64(img_path)
            if b64:
                media_type = _guess_media_type(img_path)
                parts.append(
                    types.Part.from_bytes(
                        data=base64.standard_b64decode(b64),
                        mime_type=media_type,
                    )
                )
        parts.append(types.Part.from_text(text=user_query))
        contents.append(types.Content(role="user", parts=parts))
    else:
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_query)],
            )
        )

    return contents


async def _stream_gemini(
    api_key: str,
    model: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from Google's Gemini API with interleaved tool calling.

    Streams text in real-time. When function_call parts appear, tools are
    executed and results fed back via function_response for the next round.
    """
    from google import genai
    from google.genai import types
    from ..mcp_integration.manager import mcp_manager
    from ..mcp_integration.terminal_executor import is_terminal_tool, execute_terminal_tool

    contents = _build_gemini_contents(chat_history, user_query, image_paths)
    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    thinking_tokens: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    interleaved_blocks: List[Dict[str, Any]] = []
    current_round_text: list[str] = []

    # Get tools in Gemini format
    gemini_tools = None
    if allowed_tool_names:
        gemini_tools_list = mcp_manager.get_gemini_tools()
        if gemini_tools_list:
            filtered_declarations = []
            for tool in gemini_tools_list:
                if hasattr(tool, "function_declarations") and tool.function_declarations:
                    for fd in tool.function_declarations:
                        if fd.name in allowed_tool_names:
                            filtered_declarations.append(fd)
            if filtered_declarations:
                gemini_tools = [types.Tool(function_declarations=filtered_declarations)]

    try:
        client = genai.Client(api_key=api_key)

        if app_state.stop_streaming:
            return "", total_token_stats, tool_calls_list, None

        config_kwargs: Dict[str, Any] = {}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        # Enable thinking for capable models
        is_thinking_model = any(kw in model for kw in GEMINI_THINKING_KEYWORDS)
        if is_thinking_model:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=10000,
            )

        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        generate_config = (
            types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
        )

        rounds = 0
        has_more = True

        while has_more and rounds < MAX_MCP_TOOL_ROUNDS:
            if app_state.stop_streaming:
                break

            ctx = app_state.current_request
            if ctx and ctx.cancelled:
                break

            rounds += 1

            # Collect function calls and parts from this round
            round_fn_calls: List[Dict[str, Any]] = []
            round_parts: list = []
            round_has_thinking = False
            round_has_text = False

            async for chunk in await client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_config,
            ):
                if app_state.stop_streaming:
                    break

                if not chunk.candidates:
                    # Check for usage metadata
                    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                        um = chunk.usage_metadata
                        total_token_stats["prompt_eval_count"] = (
                            getattr(um, "prompt_token_count", 0) or 0
                        )
                        total_token_stats["eval_count"] = (
                            getattr(um, "candidates_token_count", 0) or 0
                        )
                    continue

                candidate = chunk.candidates[0]
                if not candidate.content or not candidate.content.parts:
                    continue

                for part in candidate.content.parts:
                    # Handle thinking parts
                    if hasattr(part, "thought") and part.thought:
                        text_val = part.text or ""
                        thinking_tokens.append(text_val)
                        round_has_thinking = True
                        await broadcast_message("thinking_chunk", text_val)
                        round_parts.append(part)
                    elif hasattr(part, "function_call") and part.function_call:
                        # Collect function calls for execution after stream
                        fc = part.function_call
                        round_fn_calls.append({
                            "name": fc.name,
                            "args": dict(fc.args) if fc.args else {},
                        })
                        round_parts.append(part)
                    elif hasattr(part, "text") and part.text:
                        if thinking_tokens and not all_accumulated:
                            await broadcast_message("thinking_complete", "")
                        all_accumulated.append(part.text)
                        current_round_text.append(part.text)
                        round_has_text = True
                        await broadcast_message("response_chunk", part.text)
                        round_parts.append(part)

                # Check usage metadata on each chunk
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    um = chunk.usage_metadata
                    total_token_stats["prompt_eval_count"] = (
                        getattr(um, "prompt_token_count", 0) or 0
                    )
                    total_token_stats["eval_count"] = (
                        getattr(um, "candidates_token_count", 0) or 0
                    )

            if round_fn_calls:
                # Finalize thinking before tool execution so the UI
                # properly renders the thinking section during tool use
                if round_has_thinking and not round_has_text:
                    await broadcast_message("thinking_complete", "")

                # Add model's response (text + function calls) to contents
                if round_parts:
                    contents.append(types.Content(role="model", parts=round_parts))

                if current_round_text:
                    interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})
                    current_round_text = []

                # Execute each function call
                fn_response_parts = []
                for fc_data in round_fn_calls:
                    fn_name = fc_data["name"]
                    fn_args = fc_data["args"]
                    server_name = mcp_manager.get_tool_server_name(fn_name)

                    print(f"[Cloud/Gemini] Tool call: {fn_name}({fn_args}) from '{server_name}'")

                    if app_state.stop_streaming:
                        break

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args,
                            "server": server_name, "status": "calling",
                        }),
                    )

                    if is_terminal_tool(fn_name, server_name):
                        result = await execute_terminal_tool(fn_name, fn_args, server_name)
                    else:
                        try:
                            result = await mcp_manager.call_tool(fn_name, dict(fn_args))
                        except Exception as e:
                            result = f"Error executing tool: {e}"

                    result_str = _truncate_tool_result(str(result))

                    await broadcast_message(
                        "tool_call",
                        json.dumps({
                            "name": fn_name, "args": fn_args, "result": result_str,
                            "server": server_name, "status": "complete",
                        }),
                    )

                    tool_calls_list.append({
                        "name": fn_name, "args": fn_args,
                        "result": result_str, "server": server_name,
                    })
                    interleaved_blocks.append({
                        "type": "tool_call", "name": fn_name,
                        "args": fn_args, "server": server_name,
                    })

                    fn_response_parts.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response={"result": result_str},
                        )
                    )

                # Add function responses for the next round
                contents.append(types.Content(role="user", parts=fn_response_parts))
            else:
                # No function calls — response is complete
                has_more = False

        if thinking_tokens and not all_accumulated:
            await broadcast_message("thinking_complete", "")

        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))

        if tool_calls_list:
            print(f"[Cloud/Gemini] Tool loop complete after {rounds} round(s)")
        if current_round_text:
            interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})

        return "".join(all_accumulated), total_token_stats, tool_calls_list, interleaved_blocks or None

    except Exception as e:
        error_msg = f"LLM API error ({type(e).__name__})"
        print(f"[Cloud/Gemini] Full error: {e}")
        await broadcast_message("error", error_msg)
        return "", {"prompt_eval_count": 0, "eval_count": 0}, tool_calls_list, None


# ---------------------------------------------------------------------------
# Public API — called by the router
# ---------------------------------------------------------------------------


async def stream_cloud_chat(
    provider: str,
    model: str,
    api_key: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from a cloud LLM provider with inline tool calling.

    Returns:
        (response_text, token_stats, tool_calls_list, interleaved_blocks)

    Each provider handles tool execution inline during streaming — the user
    sees text and tool calls interleaved in real-time.
    """
    if provider == "anthropic":
        return await _stream_anthropic(
            api_key, model, user_query, image_paths, chat_history,
            allowed_tool_names, system_prompt
        )
    elif provider == "openai":
        return await _stream_openai(
            api_key, model, user_query, image_paths, chat_history,
            allowed_tool_names, system_prompt
        )
    elif provider == "gemini":
        return await _stream_gemini(
            api_key, model, user_query, image_paths, chat_history,
            allowed_tool_names, system_prompt
        )
    else:
        raise ValueError(f"Unknown cloud provider: {provider}")

# Note: stream_cloud_chat now returns a 4-tuple:
#   (response_text, token_stats, tool_calls_list, interleaved_blocks | None)
