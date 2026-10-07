"""Batch-scan monitored listings so the console starts populated.

LLM reports are off by default to stay inside the Gemini free-tier quota; pass --llm to enable.
Usage (from backend/): python -m scripts.scan_all --limit 100
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.container import build_container  # noqa: E402
from app.core.config import get_settings  # noqa: E402


async def main(limit: int, use_llm: bool) -> None:
    settings = get_settings()
    if not use_llm:
        settings = settings.model_copy(update={"gemini_api_key": None})
    container = build_container(settings)
    items, _ = container.products.search("", "unscanned", "spike", limit, 0)
    for i, item in enumerate(items, 1):
        analysis = await container.analysis.run(item["product"].id)
        a = analysis.assessment
        print(f"[{i}/{len(items)}] {a.risk_score:5.1f} {a.tier.value:<8} {analysis.product.title[:70]}", flush=True)
    container.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.limit, args.llm))
