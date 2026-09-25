from .base import PriceSource
from .fake import FakeSource
from .fastflights import FastFlightsSource

SOURCES = {
    "fastflights": FastFlightsSource,   # Google Flights en vivo, sin registro (uso personal)
    "fake": FakeSource,                 # datos simulados para probar el circuito
}


def get_source(name: str) -> PriceSource:
    try:
        return SOURCES[name]()
    except KeyError:
        raise SystemExit(f"Fuente desconocida: {name}. Disponibles: {', '.join(SOURCES)}")
