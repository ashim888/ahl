"""A single seam for whatever real payment processor eventually gets wired
in — local Nepali gateways (eSewa, Khalti, Fonepay, ConnectIPS, CityPay;
see ROADMAP.md's Phase 7). Every checkout view calls charge_safely(...)
(not gateway.charge(...) directly) instead of touching a processor SDK, so
swapping StubGateway for a real one later is a one-line change in
get_gateway(), not a rewrite of the checkout views.

StubGateway always "succeeds" immediately — there's no real money movement
yet. Every reference it returns is prefixed `stub-` so stubbed charges are
unambiguous in the data once a real gateway starts writing real references
into the same payment_reference fields.
"""
import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PaymentResult:
    success: bool
    reference: str
    error: str = ''


class PaymentGateway:
    """Interface a real gateway would implement."""

    def charge(self, user, amount, description):
        raise NotImplementedError


class StubGateway(PaymentGateway):
    def charge(self, user, amount, description):
        return PaymentResult(success=True, reference=f'stub-{uuid.uuid4().hex[:16]}')


def get_gateway():
    # TODO: Integrate a real gateway — return e.g. EsewaGateway() here once
    # one is chosen; nothing above this function needs to change.
    return StubGateway()


def charge_safely(user, amount, description):
    """Every checkout view calls this, not get_gateway().charge(...)
    directly. StubGateway.charge() can't raise, but a real gateway's SDK
    call is a network request that can — timeouts, connection resets,
    provider outages. Every checkout view already has a correct, tested
    "declined" path (result.success is False -> messages.error(...), no
    record created) for when a gateway cleanly reports failure; without
    this, an exception instead of a clean decline would 500 the request
    rather than falling into that same, already-handled path.
    """
    try:
        return get_gateway().charge(user, amount, description)
    except Exception:
        logger.exception('Payment gateway charge failed for %s (%s)', user, description)
        return PaymentResult(success=False, reference='', error='Payment failed — please try again.')
