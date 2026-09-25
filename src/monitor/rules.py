from __future__ import annotations

import os
from dataclasses import dataclass

from .models import Offer, RouteQuery
from .storage import Storage

# A partir de este % de baja contra la mediana se marca como posible tarifa error.
ERROR_FARE_PCT = float(os.environ.get("UMBRAL_TARIFA_ERROR", "55"))


@dataclass
class AlertDecision:
    should_alert: bool
    reasons: list[str]
    baseline: float | None
    drop_pct: float | None = None

    @property
    def looks_like_error_fare(self) -> bool:
        return self.drop_pct is not None and self.drop_pct >= ERROR_FARE_PCT


def evaluate(route: RouteQuery, offer: Offer, storage: Storage) -> AlertDecision:
    """Decide si la oferta merece una alerta."""
    reasons: list[str] = []
    baseline = storage.median_last_days(offer.route_key, days=30)
    drop = (1 - offer.price / baseline) * 100 if baseline else None

    if route.target_price is not None and offer.price <= route.target_price:
        reasons.append(f"precio {offer.price:.0f} ≤ tope {route.target_price:.0f}")

    if route.drop_pct is not None and baseline is not None:
        threshold = baseline * (1 - route.drop_pct / 100)
        if offer.price <= threshold:
            reasons.append(f"{drop:.0f}% más barato que lo normal ({baseline:.0f})")

    if not reasons:
        return AlertDecision(False, [], baseline, drop)

    if storage.already_alerted(offer.route_key, offer.price):
        return AlertDecision(False, ["ya avisado hace poco"], baseline, drop)

    return AlertDecision(True, reasons, baseline, drop)
