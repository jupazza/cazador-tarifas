from __future__ import annotations

import html
from urllib.parse import urlencode

from .models import FlightLeg, Offer, RouteQuery
from .rules import AlertDecision
from .telegram import TelegramClient


def esc(value: object) -> str:
    """Escapa texto para el modo HTML de Telegram."""
    return html.escape(str(value), quote=False)


# alias interno
_esc = esc


def google_flights_link(route: RouteQuery, offer: Offer) -> str:
    q = f"Flights from {route.origin} to {route.dest} on {offer.depart_date}"
    if route.is_open_jaw and offer.return_date:
        q = (f"Multi-city flights {route.origin} to {route.dest} on {offer.depart_date}, "
             f"{route.ret_origin} to {route.origin} on {offer.return_date}")
    elif offer.return_date:
        q += f" returning {offer.return_date}"
    if route.adults + route.children > 1:
        q += f" for {route.adults} adults" + (f" and {route.children} children" if route.children else "")
    return "https://www.google.com/travel/flights?" + urlencode({"q": q, "curr": offer.currency, "hl": "es-419"})


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


def format_leg(leg: FlightLeg) -> str:
    """'EZE –11h20→ MAD [escala 1h50] –2h→ FCO · 15h10 en total'."""
    if leg.stops == 0:
        return f"{leg.airports[0]} → {leg.airports[-1]} · {format_duration(leg.total_minutes)} (directo)"
    bits = [leg.airports[0]]
    for i, seg_min in enumerate(leg.seg_minutes):
        bits.append(f"–{format_duration(seg_min)}→")
        bits.append(leg.airports[i + 1])
        if i < len(leg.layover_minutes):
            bits.append(f"[escala {format_duration(leg.layover_minutes[i])}]")
    return " ".join(bits) + f" · {format_duration(leg.total_minutes)} en total"


CIUDADES = {
    "EZE": "BUE", "AEP": "BUE", "JFK": "Nueva York", "EWR": "Nueva York", "LGA": "Nueva York",
    "MIA": "Miami", "MCO": "Orlando", "PUJ": "Punta Cana", "CUN": "Cancún", "MAD": "Madrid",
    "BCN": "Barcelona", "FCO": "Roma", "CDG": "París", "LIS": "Lisboa", "GIG": "Río",
    "FLN": "Florianópolis", "NRT": "Tokio (Narita)", "HND": "Tokio (Haneda)",
}


def ciudad(code: str) -> str:
    return CIUDADES.get(code, code)


def _usd(v: float, cur: str = "USD") -> str:
    return f"{cur} {v:,.0f}".replace(",", ".")


def format_alert(route: RouteQuery, offer: Offer, decision: AlertDecision, score=None, verificado=None) -> str:
    cur = offer.currency
    pax = route.adults + route.children
    if route.is_open_jaw:
        tipo = "MULTIDESTINO"
        fechas = f"{offer.depart_date} → {offer.return_date} (vuelta desde {ciudad(route.ret_origin)})"
    elif offer.return_date:
        tipo = "IDA Y VUELTA"
        fechas = f"{offer.depart_date} → {offer.return_date}"
    else:
        tipo = "SOLO IDA"
        fechas = f"{offer.depart_date}"

    if decision.looks_like_error_fare:
        header = f"🚨 <b>POSIBLE TARIFA ERROR</b>\n✈️ <b>{ciudad(route.origin)} → {esc(ciudad(route.dest))} · {_usd(offer.price, cur)}</b>"
    else:
        header = f"✈️ <b>{ciudad(route.origin)} → {esc(ciudad(route.dest))} · {_usd(offer.price, cur)}</b>"
    lines = [header, f"<i>{esc(route.name)}</i>"]

    if score is not None:
        accion = "REVISAR YA" if score.value >= 75 else "REVISAR"
        lines.append(f"{score.emoji} <b>{score.label} {score.value}</b> · {accion}")
    lines.append(f"🗓 {tipo} · {esc(fechas)} · {esc(offer.carrier)}")

    pp = f" ({_usd(offer.price / pax, cur)} c/u, {esc(route.pax_label)})" if pax > 1 else ""
    if verificado is True:
        estado = "✅ precio verificado (se volvió a consultar)"
    elif verificado is False:
        estado = "⚠️ al reconsultar ya no apareció: puede haber desaparecido"
    else:
        estado = "precio sin verificar"
    lines.append(f"🔎 Detectado {_usd(offer.price, cur)}{pp} · {estado}")

    if score is not None:
        partes = [f"{score.consultas} consultas"]
        if score.habitual:
            partes.append(f"habitual {_usd(score.habitual, cur)}")
        if score.minimo:
            partes.append(f"mínimo {_usd(score.minimo, cur)}")
        if score.vs_habitual_pct is not None:
            partes.append(f"{score.vs_habitual_pct:+.1f}% vs habitual")
        tend = {"BAJANDO": "↘️ BAJANDO", "SUBIENDO": "↗️ SUBIENDO", "ESTABLE": "→ ESTABLE"}.get(score.tendencia)
        if tend:
            partes.append(tend)
        lines.append("📊 " + " · ".join(partes))
        if score.historico:
            hist = " → ".join(_usd(p, cur) for p in score.historico + [offer.price])
            lines.append(f"📈 Histórico: {hist}")
        for nota in score.notas:
            lines.append(f"💬 {esc(nota)}")
        if score.aprendiendo:
            lines.append(f"🧠 APRENDIENDO · {score.consultas} consultas acumuladas (la referencia se afina con el tiempo)")
    else:
        lines.append(f"💬 {esc(', '.join(decision.reasons))}")

    if offer.outbound:
        lines.append(f"🧭 Ida: {esc(format_leg(offer.outbound))}")
    else:
        lines.append("🧭 directo" if offer.stops == 0 else f"🧭 {offer.stops} escala(s)")
    if pax > 1 and route.children:
        lines.append("<i>Chicos cotizados como adultos: el precio real puede ser algo menor.</i>")
    if decision.looks_like_error_fare:
        lines.append("⚡ <i>Si te sirve, reservá rápido: estas tarifas duran horas. "
                     "No compres hotel no reembolsable hasta que el pasaje esté emitido.</i>")
    lines += ["", f"🔗 {google_flights_link(route, offer)}"]
    return "\n".join(lines)


class TelegramNotifier:
    """Envoltorio de TelegramClient para las alertas."""

    def __init__(self, client: TelegramClient | None = None) -> None:
        self._client = client or TelegramClient()

    def send(self, text: str) -> None:
        self._client.send_message(text)
