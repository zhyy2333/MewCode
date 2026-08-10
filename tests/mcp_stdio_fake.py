from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


def send(value) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


mode = sys.argv[1] if len(sys.argv) > 1 else "echo"
if mode in {"mcp", "mcp-parity"}:
    call_count = 0
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stdio-fake", "version": "1"},
                },
            })
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "tools": [{
                        "name": "echo.remote",
                        "description": "Echo a value",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    }]
                },
            })
        elif method == "tools/call":
            call_count += 1
            value = message.get("params", {}).get("arguments", {}).get("value", "")
            output = (
                f"ok:{value}"
                if mode == "mcp-parity"
                else f"{os.getpid()}:{call_count}:{value}"
            )
            send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "content": [{"type": "text", "text": output}]
                },
            })
elif mode == "invalid":
    sys.stdout.write("not-json\n")
    sys.stdout.flush()
    time.sleep(2)
elif mode == "oversize":
    sys.stdout.write("{" + "x" * (4 * 1024 * 1024 + 100) + "}\n")
    sys.stdout.flush()
    time.sleep(2)
elif mode == "hold":
    for _line in sys.stdin:
        pass
    time.sleep(60)
else:
    if mode == "stderr":
        sys.stderr.write("server-private-log\n" * 10000)
        sys.stderr.flush()
    for line in sys.stdin:
        message = json.loads(line)
        if mode == "inspect":
            send({
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"cwd": str(Path.cwd()), "env": os.environ.get("MCP_TEST_ENV")},
            })
        else:
            send(message)
