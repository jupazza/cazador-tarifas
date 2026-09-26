"""Puntaje de una oferta (0–100) y contexto histórico para las alertas.

Imita las tarjetas tipo "MUY BUENA 84 · REVISAR": cuánto más barato está
contra lo habitual, si cruza el tope, si es un mínimo histórico, la tendencia
y si el agente todavía está "aprendiendo" la ruta.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Offer, RouteQuery
from .storage import Storage

# Con menos consultas que esto, la referencia "habitual" todavía es poco fiable.
MIN_CONSULTAS_CONFIABLE = 30


@dataclass
class Score:
    value: int
    label: str
    emoji: str
    habitual: float | None
    minimo: float | None
    vs_habitual_pct: float | None       # negativo = más barato que lo habitual
    tendencia: str                       # BAJANDO / SUBIENDO / ESTABLE / —
    historico: list[float] = field(default_factory=list)
    consultas: int = 0
    aprendiendo: bool = True
    nuevo_minimo: bool = False
    notas: list[str] = field(default_factory=list)


def _label(v: int) -> tuple[str, str]:
    if v >= 90:
        return "EXCEPCIONAL", "🔥"
    if v >= 75:
        return "MUY BUENA", "🟢"
    if v >= 60:
        return "BUENA", "🟡"
    return "NORMAL", "⚪"


def _tendencia(precios: list[float]) -> str:
    if len(precios) < 4:
        return "—"
    mitad = len(precios) // 2
    antes = sum(precios[:mitad]) / mitad
    ahora = sum(precios[mitad:]) / (len(precios) - mitad)
    if ahora < antes * 0.97:
        return "BAJANDO"
    if ahora > antes * 1.03:
        return "SUBIENDO"
    return "ESTABLE"


def score_offer(route: RouteQuery, offer: Offer, storage: Storage) -> Score:
    """Calcular ANTES de grabar la oferta, así no se compara consigo misma."""
    st = storage.route_stats(route.key, days=30)
    historico = storage.recent_prices(route.key, n=6)
    habitual = st["median"] if st else None
    minimo = st["min"] if st else None
    consultas = st["count"] if st else 0

    v = 50.0
    vs = None
    if habitual:
        vs = (offer.price / habitual - 1) * 100
        v += -vs * 1.5                      # cada 1% más barato suma 1,5 puntos
    if route.target_price and offer.price <= route.target_price:
        v += 20
    nuevo_min = minimo is not None and offer.price < minimo
    if nuevo_min:
        v += 8
    v = int(max(0, min(100, round(v))))

    notas = []
    if vs is not None and vs <= -30:
        notas.append("Precio inusualmente bajo para esta ruta")
    if nuevo_min:
        notas.append("Nuevo mínimo de los últimos 30 días")
    elif minimo and offer.price <= minimo * 1.05:
        notas.append(f"Cerca del mínimo ({(offer.price / minimo - 1) * 100:+.1f}% vs mínimo)")
    if route.target_price and offer.price <= route.target_price:
        notas.append("Por debajo de tu tope")

    label, emoji = _label(v)
    return Score(
        value=v, label=label, emoji=emoji, habitual=habitual, minimo=minimo,
        vs_habitual_pct=vs, tendencia=_tendencia(historico + [offer.price]),
        historico=historico, consultas=consultas,
        aprendiendo=consultas < MIN_CONSULTAS_CONFIABLE, nuevo_minimo=nuevo_min, notas=notas,
    )
