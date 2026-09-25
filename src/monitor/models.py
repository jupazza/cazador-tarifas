from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class RouteQuery:
    """Uma rota a monitorar. Vem da tabela `routes` (ou do routes.yaml no seed)."""

    name: str
    origin: str
    dest: str
    depart_range: tuple[date, date]
    adults: int = 1
    return_after_days: tuple[int, int] | None = None
    target_price: float | None = None
    drop_pct: float | None = None
    nonstop: bool = False
    currency: str = "USD"
    id: int | None = None
    active: bool = True
    children: int = 0
    # Multidestino (open jaw): la vuelta sale de otra ciudad, en otra ventana de fechas
    ret_origin: str | None = None
    ret_range: tuple[date, date] | None = None
    # Ventana móvil: si está, la ida se busca entre hoy+7 y hoy+rolling_days
    # (no vence nunca; ignora depart_range)
    rolling_days: int | None = None

    @property
    def effective_depart_range(self) -> tuple[date, date]:
        if self.rolling_days:
            today = date.today()
            return (today + timedelta(days=7), today + timedelta(days=self.rolling_days))
        return self.depart_range

    @property
    def is_open_jaw(self) -> bool:
        return self.ret_origin is not None and self.ret_range is not None

    @property
    def pax_label(self) -> str:
        a = f"{self.adults} adulto" + ("s" if self.adults != 1 else "")
        if self.children:
            a += f" + {self.children} chico" + ("s" if self.children != 1 else "")
        return a

    @property
    def key(self) -> str:
        """Identificador estável da rota (usado no histórico e no dedupe).

        Com id no banco a chave é `r<id>`, então editar alvo/nome/datas preserva
        o histórico. Sem id (rota só do YAML / testes) cai na string derivada.
        """
        if self.id is not None:
            return f"r{self.id}"
        rt = "ow" if self.return_after_days is None else f"{self.return_after_days[0]}-{self.return_after_days[1]}"
        return f"{self.origin}-{self.dest}-{rt}-{self.adults}p"


@dataclass
class FlightLeg:
    """Itinerário detalhado de um trecho (voo + conexões).

    `airports` tem N+1 aeroportos para N segmentos: `["GRU","LHR","IST"]` para
    2 segmentos. `layover_minutes` tem N-1 valores (tempo de conexão entre
    segmentos consecutivos). `total_minutes` é porta-a-porta (inclui conexão).
    """

    airports: list[str]
    seg_minutes: list[int]
    layover_minutes: list[int]
    total_minutes: int

    @property
    def stops(self) -> int:
        return max(len(self.airports) - 2, 0)


@dataclass
class Offer:
    """Uma oferta de passagem concreta retornada por uma fonte."""

    route_key: str
    price: float
    currency: str
    depart_date: date
    return_date: date | None
    carrier: str
    stops: int
    deep_link: str | None = None
    raw: dict = field(default_factory=dict)
    outbound: FlightLeg | None = None  # detalhe do trecho de ida, quando a fonte fornece
