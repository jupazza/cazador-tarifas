from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timedelta

from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound

from ..dates import sample_dates
from ..models import FlightLeg, Offer, RouteQuery
from .base import PriceSource


def _to_datetime(simple_dt) -> datetime:
    y, m, d = simple_dt.date
    h, mi = simple_dt.time
    return datetime(y, m, d, h, mi)


def _build_leg(segments) -> FlightLeg | None:
    """Arma el FlightLeg con los segmentos de UN tramo (ida o vuelta)."""
    if not segments:
        return None
    try:
        airports = [segments[0].from_airport.code] + [s.to_airport.code for s in segments]
        seg_minutes = [int(s.duration) for s in segments]
        layover_minutes = [
            int((_to_datetime(segments[i + 1].departure) - _to_datetime(segments[i].arrival)).total_seconds() // 60)
            for i in range(len(segments) - 1)
        ]
        total_minutes = int(
            (_to_datetime(segments[-1].arrival) - _to_datetime(segments[0].departure)).total_seconds() // 60
        )
    except (AttributeError, TypeError, ValueError):
        return None  # horarios incompletos: sigue sin el detalle
    return FlightLeg(airports=airports, seg_minutes=seg_minutes, layover_minutes=layover_minutes, total_minutes=total_minutes)


class FastFlightsSource(PriceSource):
    """Precios en vivo de Google Flights con la librería `fast-flights`.

    No oficial: puede romperse si Google cambia su web. Solo uso personal.
    No requiere clave ni registro.
    """

    name = "fastflights"

    def __init__(self, language: str = "es", pause_s: float = 1.5) -> None:
        self.language = language
        self.pause_s = pause_s

    def search(self, route: RouteQuery) -> list[Offer]:
        offers: list[Offer] = []
        max_stops = 0 if route.nonstop else None

        # nunca buscar fechas pasadas ni demasiado cercanas
        start = max(route.depart_range[0], date.today() + timedelta(days=3))
        end = route.depart_range[1]
        if start > end:
            print(f"[aviso] {route.name}: la ventana de ida ya pasó — editala con /editar", file=sys.stderr)
            return offers
        samples = int(os.environ.get("FECHAS_POR_RUTA", "3"))
        # rota la grilla de fechas en cada barrido (cambia cada 3 h)
        rotation = int(time.time() // (3 * 3600)) + (route.id or 0)

        for dep in sample_dates(start, end, max_samples=samples, rotation=rotation):
            legs = [
                FlightQuery(
                    date=dep.isoformat(),
                    from_airport=route.origin,
                    to_airport=route.dest,
                    max_stops=max_stops,
                )
            ]
            trip = "one-way"
            ret: date | None = None
            if route.return_after_days:
                # una sola duración de viaje (punto medio del rango),
                # para no multiplicar la cantidad de búsquedas
                lo, hi = route.return_after_days
                ret = dep + timedelta(days=(lo + hi) // 2)
                legs.append(
                    FlightQuery(
                        date=ret.isoformat(),
                        from_airport=route.dest,
                        to_airport=route.origin,
                        max_stops=max_stops,
                    )
                )
                trip = "round-trip"

            query = create_query(
                flights=legs,
                trip=trip,
                seat="economy",
                passengers=Passengers(adults=max(route.adults, 1)),
                currency=route.currency,
                language=self.language,
            )

            results = self._fetch(query, f"{route.name} {dep}")
            if results is None:
                continue

            for fl in results:
                if not fl.price or fl.price <= 0 or not fl.flights:
                    continue  # "precio no disponible"
                offers.append(
                    Offer(
                        route_key=route.key,
                        price=float(fl.price),
                        currency=route.currency,
                        depart_date=dep,
                        return_date=ret,
                        carrier=", ".join(fl.airlines) if fl.airlines else str(fl.type),
                        stops=max(len(fl.flights) - 1, 0),  # escalas del tramo de ida
                        outbound=_build_leg(fl.flights),
                    )
                )

            time.sleep(self.pause_s)  # no saturar a Google

        return offers

    def _fetch(self, query, label: str):
        """get_flights con reintentos: el parser de la librería a veces falla
        con respuestas de Google; casi siempre es transitorio."""
        for attempt in range(3):
            try:
                return get_flights(query)
            except FlightsNotFound:
                return None
            except Exception as exc:  # parser frágil de fast-flights
                if attempt == 2:
                    print(f"[aviso] fastflights falló en {label}: {exc}", file=sys.stderr)
                    return None
                time.sleep(1.5 * (attempt + 1))
