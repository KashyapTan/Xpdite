"""
Test script for the MCP ↔ Ollama bridge.
=========================================
Run this from the project root:

    cd <project_root>
    python -m mcp_servers.test_demo

This will:
1. Launch the demo MCP server (add two numbers)
2. Connect it to Ollama via the bridge
3. Ask Ollama to add two numbers
4. Ollama will call the MCP tool, get the result, and respond

PREREQUISITES:
  - Ollama running locally with a tool-capable model pulled
    (e.g., `ollama pull qwen3:8b` or `ollama pull llama3.1`)
  - MCP SDK installed: `pip install "mcp[cli]"`
  - The `ollama` Python package: `pip install ollama`

By default this script uses `qwen3:8b`. Override it with the
`OLLAMA_MCP_DEMO_MODEL` environment variable if you want to test a different
tool-capable model. Run `ollama list` to see your available models.
"""

import asyncio
import sys
import os


async def main():
    # Add project root to path so imports work
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from mcp_servers.client.ollama_bridge import McpOllamaBridge

    # ── 1. Choose your Ollama model ────────────────────────────────────
    # Change this to whatever tool-capable model you have.
    # Vision models (qwen3-vl) typically DON'T support tool calling.
    # gemma3:12b supports tool calling and you already have it pulled.
    MODEL = os.environ.get("OLLAMA_MCP_DEMO_MODEL", "qwen3:8b")
    
    print("=" * 60)
    print("  MCP ↔ Ollama Bridge — Demo Test")
    print("=" * 60)
    print(f"\nUsing Ollama model: {MODEL}")
    print("Connecting to demo MCP server...\n")
    
    # ── 2. Create the bridge and connect to the demo MCP server ────────
    bridge = McpOllamaBridge(model=MODEL)
    
    # The server.py path — relative to where you run the script from
    demo_server_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "servers", "demo", "server.py"
    )
    
    await bridge.connect_server(
        server_name="demo",
        command=sys.executable,  # Use the same Python interpreter
        args=[demo_server_path],
    )
    
    # ── 3. Ask Ollama a question that requires the tool ────────────────
    print("\n" + "-" * 60)
    question = "What is 42 + 58?"
    print(f"You: {question}")
    print("-" * 60)
    
    response = await bridge.chat(question)
    
    print(f"\nOllama: {response}")
    
    # ── 4. Try a follow-up (demonstrates multi-turn) ───────────────────
    print("\n" + "-" * 60)
    question2 = "Now add 100 to that result."
    print(f"You: {question2}")
    print("-" * 60)
    
    response2 = await bridge.chat(question2)
    
    print(f"\nOllama: {response2}")
    
    # ── 5. Clean up ────────────────────────────────────────────────────
    await bridge.cleanup()
    print("\n✅ Done! The bridge is working.")


if __name__ == "__main__":
    asyncio.run(main())
