from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Offer, RouteQuery


class PriceSource(ABC):
    """Interface de uma fonte de preços. Troque a Amadeus por outra
    implementando só este método."""

    name: str = "base"

    @abstractmethod
    def search(self, route: RouteQuery) -> list[Offer]:
        """Retorna as ofertas encontradas para a rota (pode ser lista vazia)."""
        raise NotImplementedError

    def verify(self, route: RouteQuery, offer: Offer) -> bool | None:
        """Vuelve a consultar las mismas fechas. True = sigue disponible,
        False = ya no está, None = no se pudo verificar."""
        return None
