"""A diagnosis agent backed by the Anthropic Messages API.

The SDK is an optional dependency and is imported lazily, so Mender's own test
suite — and every deterministic path through the repair loop — runs without it
installed and without an API key present.

Install it with ``uv sync --extra agent``, and set ``ANTHROPIC_API_KEY`` or sign
in with ``ant auth login``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, Field

from mender.diagnose.agent import (
    Diagnosis,
    DiagnosisRequest,
    ProposedEdit,
    RegressionTest,
)
from mender.diagnose.prompt import SYSTEM_PROMPT, build_user_message

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from anthropic import Anthropic

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 32_000
DEFAULT_EFFORT: Effort = "high"

PRICE_PER_INPUT_TOKEN = 5.00 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 25.00 / 1_000_000
"""Claude Opus 5 list pricing, in US dollars per token.

Used to report what a repair cost in the evidence package. Override both when
pointing the agent at a different model.
"""


class AgentError(RuntimeError):
    """Raised when the agent layer cannot run at all."""


class _Edit(BaseModel):
    """One file the model wants to write, in full."""

    path: str
    content: str


class _RegressionTest(BaseModel):
    """The test the model wrote to prove its fix."""

    path: str
    content: str
    test_id: str
    rationale: str


class _Response(BaseModel):
    """The structured answer the model is required to return."""

    root_cause: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    edits: list[_Edit] = Field(default_factory=list)
    regression_test: _RegressionTest | None = None
    notes: str = ""


class AnthropicAgent:
    """Diagnoses a reproduced failure using a Claude model."""

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: Effort = DEFAULT_EFFORT,
        client: Anthropic | None = None,
        input_price: float = PRICE_PER_INPUT_TOKEN,
        output_price: float = PRICE_PER_OUTPUT_TOKEN,
    ) -> None:
        """Configure the model and, optionally, an existing client.

        Args:
            model: The Claude model ID to diagnose with.
            max_tokens: Output cap. Whole files come back here, so this is
                generous by default.
            effort: Thinking depth — ``low`` through ``max``.
            client: A pre-built ``anthropic.Anthropic``. Constructed on first
                use when omitted, which is what defers the import and the
                credential lookup.
            input_price: Dollars per input token, for cost reporting.
            output_price: Dollars per output token, for cost reporting.
        """
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.input_price = input_price
        self.output_price = output_price
        self._client = client

    def diagnose(self, request: DiagnosisRequest) -> Diagnosis:
        """Ask the model for a root cause and a minimal patch.

        Args:
            request: The assembled diagnosis packet.

        Returns:
            The model's diagnosis. A refusal, or an answer the schema rejects,
            comes back as a zero-edit diagnosis rather than an exception: an
            unusable answer is an abstention, which the loop already handles.

        Raises:
            AgentError: If the SDK is missing or the API call itself fails.
        """
        client = self._ensure_client()
        anthropic = _import_sdk()

        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": build_user_message(request)}],
                output_format=_Response,
            )
        except anthropic.APIError as exc:  # pragma: no cover - network path
            raise AgentError(f"The Anthropic API call failed: {exc}") from exc

        cost = self._cost(response)

        if response.stop_reason == "refusal":
            return Diagnosis(
                root_cause=(
                    "The model declined to answer. This most often means the log "
                    "contents tripped a safety classifier; a human should read the "
                    "run directly."
                ),
                confidence=0.0,
                agent=self.name,
                cost_usd=cost,
            )

        parsed: _Response | None = response.parsed_output
        if parsed is None:  # pragma: no cover - schema is enforced server-side
            return Diagnosis(
                root_cause="The model returned no parseable diagnosis.",
                confidence=0.0,
                agent=self.name,
                cost_usd=cost,
            )

        return Diagnosis(
            root_cause=parsed.root_cause,
            confidence=parsed.confidence,
            edits=[ProposedEdit(path=e.path, content=e.content) for e in parsed.edits],
            regression_test=(
                RegressionTest(
                    path=parsed.regression_test.path,
                    content=parsed.regression_test.content,
                    test_id=parsed.regression_test.test_id,
                    rationale=parsed.regression_test.rationale,
                )
                if parsed.regression_test is not None
                else None
            ),
            agent=self.name,
            cost_usd=cost,
            notes=parsed.notes,
        )

    def _ensure_client(self) -> Anthropic:
        """Return the client, building one on first use."""
        if self._client is None:
            self._client = _import_sdk().Anthropic()
        return self._client

    def _cost(self, response: Any) -> float:  # noqa: ANN401
        """Price one exchange from its reported token usage."""
        usage = getattr(response, "usage", None)
        if usage is None:  # pragma: no cover - defensive
            return 0.0
        inputs = getattr(usage, "input_tokens", 0) or 0
        outputs = getattr(usage, "output_tokens", 0) or 0
        return round(inputs * self.input_price + outputs * self.output_price, 6)


def _import_sdk() -> Any:  # noqa: ANN401
    """Import the Anthropic SDK, with an actionable message when it is absent."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise AgentError(
            "The Anthropic SDK is not installed. Run `uv sync --extra agent`, or "
            "use the heuristic agent with --agent heuristic."
        ) from exc
    return anthropic
