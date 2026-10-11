from dataclasses import dataclass
from typing import Literal, Protocol


class PaymentProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PaymentRequest:
    reference: str
    amount_ugx: int
    currency: str
    phone: str
    callback_url: str
    email: str | None = None


@dataclass(frozen=True)
class PaymentInitiation:
    provider_reference: str
    checkout_url: str | None = None
    provider_payload: dict | None = None


class PaymentProvider(Protocol):
    name: str

    def initiate(self, request: PaymentRequest) -> PaymentInitiation: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool: ...


@dataclass(frozen=True)
class PaymentReconciliationRequest:
    attempt_reference: str
    provider_reference: str | None


@dataclass(frozen=True)
class PaymentReconciliationResult:
    outcome: Literal["SUCCESSFUL", "FAILED", "UNRESOLVED"]
    authoritative: bool
    evidence: dict
    provider_reference: str | None = None


class PaymentReconciliationProvider(Protocol):
    def reconcile(
        self,
        request: PaymentReconciliationRequest,
    ) -> PaymentReconciliationResult: ...


class PaymentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, PaymentProvider] = {}

    def register(self, method: str, provider: PaymentProvider) -> None:
        self._providers[method] = provider

    def get(self, method: str) -> PaymentProvider:
        provider = self._providers.get(method)
        if provider is None:
            raise PaymentProviderUnavailable(f"No payment provider is configured for {method}.")
        return provider


payment_providers = PaymentProviderRegistry()
