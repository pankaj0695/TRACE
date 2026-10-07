import asyncio
import json
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve pydantic's $defs/$ref so the schema is self-contained for the API."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


class LLMClient(Protocol):
    name: str

    async def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class GeminiInteractionsClient:
    """Gemini via the Interactions API with JSON-schema constrained output and a model fallback chain."""

    def __init__(self, api_key: str, models: list[str], timeout_s: float):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._models = models
        self._timeout_s = timeout_s
        self.name = models[0]

    async def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        errors, schema = [], inline_refs(schema)
        for model in self._models:
            try:
                interaction = await asyncio.wait_for(
                    self._client.aio.interactions.create(
                        model=model,
                        system_instruction=system,
                        input=prompt,
                        response_format={"type": "text", "mime_type": "application/json", "schema": schema},
                        generation_config={"temperature": 0.2},
                        store=False,
                    ),
                    timeout=self._timeout_s,
                )
                self.name = model
                return json.loads(interaction.output_text)
            except Exception as exc:  # rate limits, timeouts, malformed JSON → try next model
                log.warning("Gemini model %s failed: %s", model, exc)
                errors.append(f"{model}: {exc}")
        raise LLMUnavailable("; ".join(errors))


class DisabledLLM:
    name = "disabled"

    async def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        raise LLMUnavailable("GEMINI_API_KEY is not configured")


def create_llm(api_key: str | None, model: str, fallback_model: str, timeout_s: float) -> LLMClient:
    if not api_key:
        return DisabledLLM()
    return GeminiInteractionsClient(api_key, [m for m in (model, fallback_model) if m], timeout_s)
