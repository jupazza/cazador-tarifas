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


def format_alert(route: RouteQuery, offer: Offer, decision: AlertDecision) -> str:
    if route.is_open_jaw and offer.return_date:
        trip = (f"📅 Ida {offer.depart_date} ({route.origin}→{route.dest}) · "
                f"Vuelta {offer.return_date} ({route.ret_origin}→{route.origin})")
    elif offer.return_date:
        trip = f"📅 Ida {offer.depart_date} · Vuelta {offer.return_date}"
    else:
        trip = f"📅 Ida {offer.depart_date} (solo ida)"
    total_pax = route.adults + route.children
    header = (
        f"🚨 <b>POSIBLE TARIFA ERROR: {esc(route.name)}</b>"
        if decision.looks_like_error_fare
        else f"✈️ <b>Oferta: {esc(route.name)}</b>"
    )
    lines = [
        header,
        "",
        f"💰 <b>{esc(offer.currency)} {offer.price:,.0f}</b>"
        + (f" total ({esc(offer.currency)} {offer.price / total_pax:,.0f} por persona)" if total_pax > 1 else "")
        + f"  ({esc(', '.join(decision.reasons))})",
        trip,
        f"🛫 {esc(offer.carrier)} · {esc(route.pax_label)}",
    ]
    if offer.outbound:
        label = "🧭 Vuelo" if not offer.return_date else "🧭 Ida"
        lines.append(f"{label}: {esc(format_leg(offer.outbound))}")
    else:
        stops = "directo" if offer.stops == 0 else f"{offer.stops} escala(s)"
        lines.append(f"🧭 {stops}")
    if decision.looks_like_error_fare:
        lines += ["", "⚡ <i>Si te sirve, reservá rápido: estas tarifas duran horas. "
                  "No compres hotel no reembolsable hasta que el pasaje esté emitido.</i>"]
    lines += ["", f"🔗 {google_flights_link(route, offer)}"]
    return "\n".join(lines)


class TelegramNotifier:
    """Envoltorio de TelegramClient para las alertas."""

    def __init__(self, client: TelegramClient | None = None) -> None:
        self._client = client or TelegramClient()

    def send(self, text: str) -> None:
        self._client.send_message(text)
