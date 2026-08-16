"""A single seam for whatever real payment processor eventually gets wired
in (Stripe or otherwise — no decision has been made yet). Every checkout
view below calls get_gateway().charge(...) instead of touching a processor
SDK directly, so swapping StubGateway for a real one later is a one-line
change in get_gateway(), not a rewrite of the checkout views.

StubGateway always "succeeds" immediately — there's no real money movement
yet. Every reference it returns is prefixed `stub-` so stubbed charges are
unambiguous in the data once a real gateway starts writing real references
into the same payment_reference fields.
"""
import uuid
from dataclasses import dataclass


@dataclass
class PaymentResult:
    success: bool
    reference: str
    error: str = ''


class PaymentGateway:
    """Interface a real gateway (e.g. Stripe) would implement."""

    def charge(self, user, amount, description):
        raise NotImplementedError


class StubGateway(PaymentGateway):
    def charge(self, user, amount, description):
        return PaymentResult(success=True, reference=f'stub-{uuid.uuid4().hex[:16]}')


def get_gateway():
    # TODO: Integrate Stripe — return StripeGateway() here once a processor
    # is chosen; nothing above this function needs to change.
    return StubGateway()
