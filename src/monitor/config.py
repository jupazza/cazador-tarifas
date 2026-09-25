from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

from .models import RouteQuery

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "routes.yaml"


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def has_no_alert_criteria(route: RouteQuery) -> bool:
    return route.target_price is None and route.drop_pct is None


def load_routes_from_yaml(path: Path = CONFIG_PATH) -> list[RouteQuery]:
    """Lê o routes.yaml. Usado só para semear a tabela `routes` na primeira
    execução (e nos testes); em runtime as rotas vêm do banco."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    currency = raw.get("currency", "USD")
    routes: list[RouteQuery] = []
    for r in raw["routes"]:
        rolling = r.get("rolling_days")
        dr = r.get("depart_range") or [date.today().isoformat(), date.today().isoformat()]
        rad = r.get("return_after_days")
        rr = r.get("return_range")
        routes.append(
            RouteQuery(
                name=r["name"],
                origin=r["origin"].upper(),
                dest=r["dest"].upper(),
                depart_range=(_as_date(dr[0]), _as_date(dr[1])),
                adults=int(r.get("adults", 1)),
                return_after_days=(int(rad[0]), int(rad[1])) if rad else None,
                target_price=r.get("target_price"),
                drop_pct=r.get("drop_pct"),
                nonstop=bool(r.get("nonstop", False)),
                currency=currency,
                children=int(r.get("children", 0)),
                ret_origin=r["return_from"].upper() if r.get("return_from") else None,
                ret_range=(_as_date(rr[0]), _as_date(rr[1])) if rr else None,
                rolling_days=int(rolling) if rolling else None,
            )
        )

    for route in routes:
        if has_no_alert_criteria(route):
            print(
                f"[aviso] la ruta '{route.name}' no tiene target_price ni drop_pct "
                f"— nunca va a avisar",
                file=sys.stderr,
            )
    return routes
