"""NB-14: the OpenRouter embeddings adapter (request body, reading, errors)."""

import json
from dataclasses import replace
from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import (
    OpenRouterEmbeddings,
    parse_embeddings,
)
from app.settings import Settings
from app.settings_ai import AiSettings, AiTaskSettings
from app.shared.ai_tasks import AiTask

import httpx
import pytest
import respx

URL = "https://openrouter.ai/api/v1/embeddings"


def response(
    vectors: list[list[float]], *, cost: float | None = 2e-07
) -> dict[str, Any]:
    """The shape OpenRouter answers with (checked against a real call)."""
    usage: dict[str, Any] = {"prompt_tokens": 12, "total_tokens": 12}
    if cost is not None:
        usage["cost"] = cost
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": v, "index": i}
            for i, v in enumerate(vectors)
        ],
        "model": "Qwen/Qwen3-Embedding-4B",
        "provider": "DeepInfra",
        "usage": usage,
    }


async def no_sleep(seconds: float) -> None:
    """Retries do not wait in tests."""


def adapter(dims: int = 3, **task: Any) -> OpenRouterEmbeddings:
    """An adapter over a test key; vectors of `dims` numbers."""
    ai = AiSettings(tasks={AiTask.EMBEDDING: AiTaskSettings(dimensions=dims, **task)})
    gateway = OpenRouterGateway(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        app_url="https://sp.ihsu.uz",
        app_title="IHSP",
        timeout_seconds=5,
        sleep=no_sleep,
    )
    return OpenRouterEmbeddings(gateway, ai.profile(AiTask.EMBEDDING))


@respx.mock
async def test_documents_are_sent_with_the_model_the_size_and_the_privacy_routing() -> (
    None
):
    """The body carries the profile: model, dimensions, float encoding, deny."""
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=response([[1, 0, 0], [0, 1, 0]]))
    )

    batch = await adapter().embed(["first", "second"], kind="document")

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "model": "qwen/qwen3-embedding-4b",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 3,
        "provider": {"data_collection": "deny"},
    }
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"
    assert batch.vectors == [[1, 0, 0], [0, 1, 0]]
    assert batch.tokens == 12
    assert batch.cost_micro == 0  # 2e-07 USD rounds to 0 millionths


@respx.mock
async def test_only_questions_get_the_query_prefix() -> None:
    """Qwen3 reads a task line before a question, not before a passage."""
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=response([[1, 0, 0]]))
    )
    embeddings = adapter()

    await embeddings.embed(["why?"], kind="query")
    query_body = json.loads(route.calls.last.request.content)
    await embeddings.embed(["because."], kind="document")
    document_body = json.loads(route.calls.last.request.content)

    assert query_body["input"][0].startswith("Instruct: ")
    assert query_body["input"][0].endswith("Query: why?")
    assert document_body["input"] == ["because."]


@respx.mock
async def test_the_prefixes_come_from_the_task_settings() -> None:
    """An e5 style model: `query: ` and `passage: `; `none` clears the default."""
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=response([[1, 0, 0]]))
    )
    embeddings = adapter(
        model="intfloat/multilingual-e5-large",
        query_prefix="query: ",
        document_prefix="passage: ",
    )

    await embeddings.embed(["q"], kind="query")
    assert json.loads(route.calls.last.request.content)["input"] == ["query: q"]
    await embeddings.embed(["p"], kind="document")
    assert json.loads(route.calls.last.request.content)["input"] == ["passage: p"]
    assert adapter(query_prefix="none")._profile.query_prefix == ""


@respx.mock
async def test_vectors_are_returned_in_input_order_even_if_the_answer_is_shuffled() -> (
    None
):
    """The `index` field decides, not the position in `data`."""
    body = response([[1, 0, 0], [0, 1, 0]])
    body["data"].reverse()
    respx.post(URL).mock(return_value=httpx.Response(200, json=body))

    batch = await adapter().embed(["a", "b"], kind="document")

    assert batch.vectors == [[1, 0, 0], [0, 1, 0]]


@respx.mock
async def test_an_empty_input_makes_no_request() -> None:
    """Nothing to embed, nothing to pay."""
    route = respx.post(URL).mock(return_value=httpx.Response(500))

    batch = await adapter().embed([], kind="document")

    assert batch.vectors == [] and batch.tokens == 0
    assert not route.called


@respx.mock
async def test_a_server_error_is_retried_once_then_reported() -> None:
    """The gateway's retry and error mapping apply to embeddings too."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(502, json={"error": {"message": "bad gateway"}}),
            httpx.Response(200, json=response([[1, 0, 0]])),
        ]
    )

    batch = await adapter().embed(["x"], kind="document")

    assert route.call_count == 2
    assert batch.vectors == [[1, 0, 0]]


@respx.mock
async def test_a_provider_error_becomes_an_ai_provider_error() -> None:
    """A 400 (for example an empty string) is not retried."""
    respx.post(URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "too small"}})
    )

    with pytest.raises(AiProviderError):
        await adapter().embed(["x"], kind="document")


def test_a_vector_of_the_wrong_size_is_refused() -> None:
    """A model that ignores `dimensions` must not put 4096 numbers into 1024."""
    with pytest.raises(AiProviderError, match="vector size"):
        parse_embeddings(response([[1.0, 2.0]]), count=1, dims=3)


def test_a_missing_vector_is_refused() -> None:
    """Fewer vectors than texts."""
    with pytest.raises(AiProviderError, match="1 vectors for 2 texts"):
        parse_embeddings(response([[1.0, 2.0, 3.0]]), count=2, dims=3)


def test_the_cost_is_optional() -> None:
    """A provider that does not say what it charged leaves `cost_micro` empty."""
    batch = parse_embeddings(response([[1.0, 2.0, 3.0]], cost=None), count=1, dims=3)

    assert batch.cost_micro is None


def test_the_default_profile_is_the_documented_one() -> None:
    """Model, size 1024 (the column), batch of 32, private routing."""
    profile = Settings().ai_profile(AiTask.EMBEDDING)

    assert profile.model == "qwen/qwen3-embedding-4b"
    assert profile.dimensions == 1024
    assert profile.batch_size == 32
    assert profile.document_prefix == ""
    assert profile.provider() == {"data_collection": "deny"}
    assert replace(profile, dimensions=8).dimensions == 8
