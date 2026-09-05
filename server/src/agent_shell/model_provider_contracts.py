from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
StrictInteger = Annotated[int, Field(strict=True)]
PositiveInteger = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
StrictBoolean = Annotated[bool, Field(strict=True)]
ShortText = Annotated[str, Field(min_length=1)]
StopSequences = list[Annotated[str, Field(min_length=1)]]


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenAIProviderSettings(ProviderSettings):
    use_responses_api: StrictBoolean | None = None
    temperature: FiniteFloat | None = None
    max_completion_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = None
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = None
    frequency_penalty: FiniteFloat | None = None
    seed: StrictInteger | None = None
    timeout: PositiveFloat | None = None
    max_retries: NonNegativeInteger | None = None
    stream_usage: StrictBoolean | None = None
    streaming: StrictBoolean | None = None
    reasoning_effort: ShortText | None = None
    service_tier: ShortText | None = None
    logprobs: StrictBoolean | None = None
    top_logprobs: NonNegativeInteger | None = None


class DeepSeekProviderSettings(ProviderSettings):
    temperature: FiniteFloat | None = None
    max_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = None
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = None
    frequency_penalty: FiniteFloat | None = None
    seed: StrictInteger | None = None
    timeout: PositiveFloat | None = None
    max_retries: NonNegativeInteger | None = None
    stream_usage: StrictBoolean | None = None
    streaming: StrictBoolean | None = None
    reasoning_effort: ShortText | None = None
    service_tier: ShortText | None = None
    logprobs: StrictBoolean | None = None
    top_logprobs: NonNegativeInteger | None = None


class XAIProviderSettings(DeepSeekProviderSettings):
    pass


class AnthropicProviderSettings(ProviderSettings):
    temperature: FiniteFloat | None = None
    max_tokens_to_sample: PositiveInteger | None = None
    top_p: FiniteFloat | None = None
    stop: StopSequences | None = None
    timeout: PositiveFloat | None = None
    max_retries: NonNegativeInteger | None = None
    stream_usage: StrictBoolean | None = None
    streaming: StrictBoolean | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class GoogleGenAIProviderSettings(ProviderSettings):
    temperature: FiniteFloat | None = None
    max_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = None
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = None
    frequency_penalty: FiniteFloat | None = None
    seed: StrictInteger | None = None
    request_timeout: PositiveFloat | None = None
    retries: NonNegativeInteger | None = None
    streaming: StrictBoolean | None = None
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None
    thinking_budget: NonNegativeInteger | None = None
    include_thoughts: StrictBoolean | None = None


class GoogleVertexAIProviderSettings(ProviderSettings):
    temperature: FiniteFloat | None = None
    max_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = None
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = None
    frequency_penalty: FiniteFloat | None = None
    seed: StrictInteger | None = None
    timeout: PositiveFloat | None = None
    max_retries: NonNegativeInteger | None = None
    streaming: StrictBoolean | None = None
    logprobs: StrictBoolean | NonNegativeInteger | None = None
    thinking_budget: NonNegativeInteger | None = None
    include_thoughts: StrictBoolean | None = None


_SETTINGS_BY_PROVIDER: dict[str, type[ProviderSettings]] = {
    "openai": OpenAIProviderSettings,
    "anthropic": AnthropicProviderSettings,
    "google_vertexai": GoogleVertexAIProviderSettings,
    "google_genai": GoogleGenAIProviderSettings,
    "deepseek": DeepSeekProviderSettings,
    "xai": XAIProviderSettings,
}


def validate_provider_settings(
    provider: str,
    value: dict[str, object],
) -> dict[str, object]:
    settings_type = _SETTINGS_BY_PROVIDER[provider]
    settings = settings_type.model_validate(value)
    return settings.model_dump(exclude_none=True)
