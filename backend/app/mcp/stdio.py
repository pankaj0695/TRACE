"""MCP over stdio for local clients (e.g. Claude Desktop):  python -m app.mcp.stdio

Newline-delimited JSON-RPC on stdin/stdout; all logging goes to stderr so the protocol stream stays clean.
Authentication is the local OS user: the principal is `stdio-local` with TRACE_MCP_STDIO_ROLE (default analyst).
"""

import asyncio
import json
import logging
import sys

from app.container import DatasetMissing, build_container
from app.core.config import get_settings
from app.mcp.governance import Principal
from app.mcp.server import PARSE_ERROR, Conn, MCPRuntime, _err
from app.mcp.tools import build_registry

log = logging.getLogger("trace.mcp.stdio")


async def serve(readline, write_line) -> None:
    settings = get_settings()
    container = await asyncio.to_thread(build_container, settings)
    runtime = MCPRuntime(container, build_registry())
    lock = asyncio.Lock()

    async def send(message) -> None:
        async with lock:
            write_line(json.dumps(message, default=str))

    conn = Conn(principal=Principal("stdio-local", settings.mcp_stdio_role, "stdio"), transport="stdio", notify=send)
    pending: set[asyncio.Task] = set()

    async def process(line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return await send(_err(None, PARSE_ERROR, "Parse error"))
        response = await runtime.handle_payload(payload, conn)
        if response is not None:
            await send(response)

    try:
        while line := await readline():
            if line.strip():
                task = asyncio.create_task(process(line.decode("utf-8", "replace")))
                pending.add(task)
                task.add_done_callback(pending.discard)
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        container.close()


async def _main() -> None:
    # A worker thread reads stdin: works on Windows too, where pipes/console handles can't join the event loop.
    async def readline() -> bytes:
        return await asyncio.to_thread(sys.stdin.buffer.readline)

    def write_line(text: str) -> None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    await serve(readline, write_line)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(_main())
    except DatasetMissing as exc:
        log.error("%s", exc)
        sys.exit(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
