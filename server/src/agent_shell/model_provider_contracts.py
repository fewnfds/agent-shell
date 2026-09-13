from __future__ import annotations

from typing import Annotated

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
    temperature: FiniteFloat | None = 1
    max_completion_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = 1
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = 0
    frequency_penalty: FiniteFloat | None = 0
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
    temperature: FiniteFloat | None = 1
    max_tokens: PositiveInteger | None = None
    top_p: FiniteFloat | None = 1
    stop_sequences: StopSequences | None = None
    presence_penalty: FiniteFloat | None = 0
    frequency_penalty: FiniteFloat | None = 0
    seed: StrictInteger | None = None
    timeout: PositiveFloat | None = None
    max_retries: NonNegativeInteger | None = None
    stream_usage: StrictBoolean | None = None
    streaming: StrictBoolean | None = None
    reasoning_effort: ShortText | None = None
    service_tier: ShortText | None = None
    logprobs: StrictBoolean | None = None
    top_logprobs: NonNegativeInteger | None = None


_SETTINGS_BY_PROVIDER: dict[str, type[ProviderSettings]] = {
    "openai": OpenAIProviderSettings,
    "deepseek": DeepSeekProviderSettings,
}


def validate_provider_settings(
    provider: str,
    value: dict[str, object],
) -> dict[str, object]:
    settings_type = _SETTINGS_BY_PROVIDER[provider]
    settings = settings_type.model_validate(value)
    return settings.model_dump(exclude_none=True)
