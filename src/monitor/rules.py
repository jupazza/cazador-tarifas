from __future__ import annotations

import os
from dataclasses import dataclass

from .models import Offer, RouteQuery
from .storage import Storage

# A partir de este % de baja contra la mediana se marca como posible tarifa error.
ERROR_FARE_PCT = float(os.environ.get("UMBRAL_TARIFA_ERROR", "55"))

# Aviso "cerca del mínimo": precio igual o menor al mínimo de los últimos 30 días,
# o hasta este % por encima. Si es menor, pasa a ser el nuevo mínimo.
CERCA_MINIMO_PCT = float(os.environ.get("CERCA_MINIMO_PCT", "5"))
# Consultas previas necesarias para que el mínimo signifique algo.
CERCA_MINIMO_CONSULTAS = int(os.environ.get("CERCA_MINIMO_CONSULTAS", "5"))
# Freno: como mucho 1 aviso "cerca del mínimo" por ruta cada N horas, salvo que
# aparezca un precio más bajo que el último avisado (ese llega siempre). 0 = sin freno.
CERCA_MINIMO_REPETIR_HORAS = float(os.environ.get("CERCA_MINIMO_REPETIR_HORAS", "24"))


@dataclass
class AlertDecision:
    should_alert: bool
    reasons: list[str]
    baseline: float | None
    drop_pct: float | None = None
    minimo: float | None = None        # mínimo de 30 días (si disparó "cerca del mínimo")
    nuevo_minimo: bool = False

    @property
    def cerca_minimo(self) -> bool:
        return self.minimo is not None

    @property
    def sobre_minimo_pct(self) -> float | None:
        return None if not self.minimo else (self._price / self.minimo - 1) * 100

    _price: float = 0.0

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

    fuerte = bool(reasons)  # tope o baja fuerte: se avisa con el control de repetidos de siempre

    minimo, nuevo = None, False
    stats = storage.route_stats(offer.route_key, days=30)
    if stats and stats["count"] >= CERCA_MINIMO_CONSULTAS:
        m = stats["min"]
        if offer.price <= m * (1 + CERCA_MINIMO_PCT / 100):
            minimo, nuevo = m, offer.price < m
            if nuevo:
                reasons.append(f"nuevo mínimo (antes {m:.0f})")
            elif offer.price == m:
                reasons.append(f"igual al mínimo ({m:.0f})")
            else:
                reasons.append(f"{(offer.price / m - 1) * 100:.1f}% sobre el mínimo ({m:.0f})")

    def dec(ok: bool, rs: list[str]) -> AlertDecision:
        return AlertDecision(ok, rs, baseline, drop, minimo=minimo, nuevo_minimo=nuevo, _price=offer.price)

    if not reasons:
        return dec(False, [])

    if storage.already_alerted(offer.route_key, offer.price):
        return dec(False, ["ya avisado hace poco"])

    if not fuerte and not nuevo and CERCA_MINIMO_REPETIR_HORAS > 0:
        ultimo = storage.lowest_alert_since(offer.route_key, hours=CERCA_MINIMO_REPETIR_HORAS)
        if ultimo is not None and offer.price >= ultimo * 0.99:
            return dec(False, ["cerca del mínimo, ya avisado en las últimas horas"])

    return dec(True, reasons)
