"""Claude client with per-task model routing and cost tracking.

Cheap, high-volume work (parsing job descriptions, fit scoring, verification,
form answers) goes to Haiku. Only resume tailoring goes to Sonnet.
"""

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from . import db

FAST_MODEL = os.environ.get("JOBAGENT_FAST_MODEL", "claude-haiku-5-5")
QUALITY_MODEL = os.environ.get("JOBAGENT_QUALITY_MODEL", "claude-sonnet-5-5")

# task -> (model, effort). Lower effort means less thinking, so fewer output tokens.
TASKS = {
    "parse_job": (FAST_MODEL, "low"),
    "fit_score": (FAST_MODEL, "low"),
    "verify": (FAST_MODEL, "medium"),
    "form_answer": (FAST_MODEL, "medium"),  # low effort gave answers that contradicted its own reasoning
    "fix_summary": (FAST_MODEL, "low"),
    "tailor": (QUALITY_MODEL, "medium"),
    "build_profile": (QUALITY_MODEL, "medium"),  # one-off; the profile must be accurate
}

# USD per 1M tokens (input, output). Haiku price is for prompts up to 100K tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
}

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class LLMRefusal(Exception):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
                "(see README.md, 'Get your API key')."
            )
        _client = anthropic.Anthropic()
    return _client


def estimate_cost(model: str, usage) -> float:
    price_in, price_out = PRICES.get(model, PRICES[QUALITY_MODEL])
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0
    return (
        usage.input_tokens * price_in
        + cache_write * price_in * 1.25
        + cache_read * price_in * 0.1
        + usage.output_tokens * price_out
    ) / 1_000_000


def structured(task: str, system: str, user: str, schema: type[T], max_tokens: int = 16000) -> T:
    """Run one task and return the response parsed into `schema`.

    The system prompt is marked for caching, so keep it identical across calls
    (put the profile there, and the per-job text in `user`).
    """
    model, effort = TASKS[task]
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
    )
    if model == QUALITY_MODEL:
        # Sonnet supports server-side fallback on a safety decline; Haiku does not.
        api = client().beta.messages
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    else:
        api = client().messages
    if max_tokens > 16000:  # long outputs stream to avoid HTTP timeouts
        with api.stream(**kwargs) as stream:
            response = stream.get_final_message()
    else:
        response = api.parse(**kwargs)

    db.log_usage(
        task=task,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read=response.usage.cache_read_input_tokens or 0,
        cache_write=response.usage.cache_creation_input_tokens or 0,
        cost=estimate_cost(response.model, response.usage),
    )

    if response.stop_reason == "refusal":
        raise LLMRefusal(f"{task}: model declined the request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"{task}: hit max_tokens={max_tokens}; raise it")
    if response.parsed_output is None:
        raise RuntimeError(f"{task}: response did not match the schema")
    return response.parsed_output
