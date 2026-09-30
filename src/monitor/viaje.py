"""Seguimiento de un viaje puntual (config/viaje.yaml), aparte de las rutas.

- Cada hora consulta en Google Flights cada tramo de solo ida, en su fecha
  ±flex días y en todos los aeropuertos indicados.
- Si el mejor precio de un tramo baja del mínimo visto hasta ahora, avisa al
  instante en el grupo de Telegram del viaje.
- Todos los días a la hora de reporte manda un resumen con la mejor forma de
  armar el viaje, comparado con ayer y con el precio de referencia, y links a
  Google Flights, Cheapflights, Expedia, Skyscanner, eDreams y CheapOair.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from html import escape as _h
from urllib.parse import urlencode

import yaml

from .storage import Storage

VIAJE_PATH = Path(__file__).resolve().parents[2] / "config" / "viaje.yaml"
ART = timezone(timedelta(hours=-3))  # Buenos Aires
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
BAJA_MINIMA = 0.01  # 1%: menos que eso es ruido

SCHEMA = """
CREATE TABLE IF NOT EXISTS viaje_precios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tramo TEXT NOT NULL, fecha TEXT NOT NULL, desde TEXT NOT NULL, hasta TEXT NOT NULL,
    precio REAL NOT NULL, aerolinea TEXT, escalas INTEGER,
    salida TEXT, llegada TEXT, mas_dias INTEGER, duracion INTEGER,
    chequeo TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_viaje ON viaje_precios(tramo, chequeo);
"""


@dataclass
class Vuelo:
    tramo: str
    fecha: date
    desde: str
    hasta: str
    precio: float          # total de todos los pasajeros
    aerolinea: str = ""
    escalas: int = 0
    salida: str = ""       # "21:10"
    llegada: str = ""
    mas_dias: int = 0      # llega +1, +2...
    duracion: int = 0      # minutos


# --- configuración ------------------------------------------------------------
def load_viaje(path: Path = VIAJE_PATH) -> dict | None:
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for t in cfg["tramos"]:
        t["fecha"] = _d(t["fecha"])
    for it in cfg.get("itinerarios", []):
        it["fechas"] = {k: _d(v) for k, v in it["fechas"].items()}
    return cfg


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def fechas_tramo(t: dict) -> list[date]:
    return [t["fecha"] + timedelta(days=i) for i in range(-t.get("flex", 0), t.get("flex", 0) + 1)]


def pasajes(cfg: dict) -> int:
    p = cfg["pasajeros"]
    return p["adultos"] + p.get("chicos", 0)


def chat_id(cfg: dict) -> str | None:
    return os.environ.get("TELEGRAM_VIAJE_CHAT_ID") or (str(cfg["chat_id"]) if cfg.get("chat_id") else None)


# --- búsqueda -------------------------------------------------------------------
def buscar_google(desde: str, hasta: str, dia: date, pax: int, moneda: str) -> list[Vuelo]:
    """Vuelos de solo ida en Google Flights (fast-flights). La librería falla
    con chicos, así que todos se cotizan como adultos (precio conservador)."""
    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    from fast_flights.exceptions import FlightsNotFound

    q = create_query(
        flights=[FlightQuery(date=dia.isoformat(), from_airport=desde, to_airport=hasta)],
        trip="one-way", seat="economy", passengers=Passengers(adults=pax),
        currency=moneda, language="es",
    )
    res = None
    for intento in range(3):
        try:
            res = get_flights(q)
            break
        except FlightsNotFound:
            return []
        except Exception as exc:
            if intento == 2:
                print(f"[aviso] viaje: falló {desde}-{hasta} {dia}: {exc}", file=sys.stderr)
                return []
            time.sleep(1.5 * (intento + 1))
    out = []
    for fl in res or []:
        if not fl.price or fl.price <= 0 or not fl.flights:
            continue
        a, b = fl.flights[0], fl.flights[-1]
        try:
            dep = datetime(*a.departure.date, *a.departure.time)
            arr = datetime(*b.arrival.date, *b.arrival.time)
            salida, llegada = dep.strftime("%H:%M"), arr.strftime("%H:%M")
            mas, dur = (arr.date() - dep.date()).days, sum(int(s.duration or 0) for s in fl.flights)
        except Exception:
            salida = llegada = ""
            mas = dur = 0
        out.append(Vuelo("", dia, desde, hasta, float(fl.price), ", ".join(fl.airlines or []),
                         len(fl.flights) - 1, salida, llegada, mas, dur))
    return out


def consultar(cfg: dict, buscar=buscar_google, pausa: float = 1.5) -> list[Vuelo]:
    """El vuelo más barato de cada tramo, fecha y par de aeropuertos."""
    pax, moneda = pasajes(cfg), cfg.get("moneda", "USD")
    mejores: list[Vuelo] = []
    for t in cfg["tramos"]:
        for dia in fechas_tramo(t):
            if dia <= date.today():
                continue
            for desde, hasta in t["pares"]:
                vuelos = buscar(desde, hasta, dia, pax, moneda)
                if pausa:
                    time.sleep(pausa)
                if vuelos:
                    v = min(vuelos, key=lambda x: x.precio)
                    v.tramo = t["id"]
                    mejores.append(v)
    return mejores


# --- base de datos ----------------------------------------------------------------
def _db(storage: Storage) -> None:
    storage.conn.executescript(SCHEMA)


def guardar(storage: Storage, vuelos: list[Vuelo], chequeo: str) -> None:
    _db(storage)
    storage.conn.executemany(
        "INSERT INTO viaje_precios (tramo, fecha, desde, hasta, precio, aerolinea, escalas, salida, "
        "llegada, mas_dias, duracion, chequeo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(v.tramo, v.fecha.isoformat(), v.desde, v.hasta, v.precio, v.aerolinea, v.escalas,
          v.salida, v.llegada, v.mas_dias, v.duracion, chequeo) for v in vuelos],
    )
    storage.conn.commit()


def ultimo_chequeo(storage: Storage) -> tuple[str | None, list[Vuelo]]:
    _db(storage)
    row = storage.conn.execute("SELECT MAX(chequeo) FROM viaje_precios").fetchone()
    if not row or not row[0]:
        return None, []
    rows = storage.conn.execute(
        "SELECT tramo, fecha, desde, hasta, precio, aerolinea, escalas, salida, llegada, mas_dias, duracion "
        "FROM viaje_precios WHERE chequeo=?", (row[0],)).fetchall()
    return row[0], [Vuelo(r[0], date.fromisoformat(r[1]), *r[2:]) for r in rows]


def minimo_historico(storage: Storage, tramo: str, antes_de: str | None = None) -> float | None:
    _db(storage)
    sql, args = "SELECT MIN(precio) FROM viaje_precios WHERE tramo=?", [tramo]
    if antes_de:
        sql += " AND chequeo<?"
        args.append(antes_de)
    row = storage.conn.execute(sql, args).fetchone()
    return row[0] if row else None


def mejor_por_tramo(vuelos: list[Vuelo]) -> dict[str, Vuelo]:
    out: dict[str, Vuelo] = {}
    for v in vuelos:
        if v.tramo not in out or v.precio < out[v.tramo].precio:
            out[v.tramo] = v
    return out


def mejor_por_fecha(vuelos: list[Vuelo], tramo: str) -> dict[date, Vuelo]:
    out: dict[date, Vuelo] = {}
    for v in vuelos:
        if v.tramo == tramo and (v.fecha not in out or v.precio < out[v.fecha].precio):
            out[v.fecha] = v
    return dict(sorted(out.items()))


# --- links ---------------------------------------------------------------------
SKY = {"NYC": "nyca", "ORL": "orla"}


def link_google(cfg: dict, tramos: list[tuple[str, str, date]]) -> str:
    from fast_flights import FlightQuery, Passengers, create_query

    p = cfg["pasajeros"]
    q = create_query(
        flights=[FlightQuery(date=d.isoformat(), from_airport=a, to_airport=b) for a, b, d in tramos],
        trip="one-way" if len(tramos) == 1 else "multi-city", seat="economy",
        passengers=Passengers(adults=p["adultos"], children=p.get("chicos", 0)),
        language="es-419", currency=cfg.get("moneda", "USD"),
    )
    return "https://www.google.com/travel/flights/search?" + urlencode(q.params())


def _kayak_pax(cfg: dict) -> str:
    p = cfg["pasajeros"]
    s = f"{p['adultos']}adults"
    if p.get("edades_chicos"):
        s += "/children-" + "-".join(str(e) for e in p["edades_chicos"])
    return s


def _expedia_pax(cfg: dict) -> str:
    p = cfg["pasajeros"]
    s = f"adults:{p['adultos']}"
    if p.get("edades_chicos"):
        s += f",children:{len(p['edades_chicos'])}[{';'.join(str(e) for e in p['edades_chicos'])}]"
    return s


def link_cheapflights(cfg: dict, tramos: list[tuple[str, str, date]], flex: int = 0) -> str:
    partes = []
    for a, b, d in tramos:
        partes.append(f"{a}-{b}/{d.isoformat()}" + (f"-flexible-{flex}days" if flex else ""))
    return "https://www.cheapflights.com/flight-search/" + "/".join(partes) + "/" + _kayak_pax(cfg) + "?sort=price_a"


def link_expedia(cfg: dict, tramos: list[tuple[str, str, date]]) -> str:
    legs = "&".join(f"leg{i}=from:{a},to:{b},departure:{d.month}/{d.day}/{d.year}TANYT"
                    for i, (a, b, d) in enumerate(tramos, 1))
    trip = "oneway" if len(tramos) == 1 else "multi"
    return (f"https://www.expedia.com/Flights-Search?trip={trip}&{legs}"
            f"&passengers={_expedia_pax(cfg)}&options=cabinclass:economy&mode=search")


def link_skyscanner(cfg: dict, a: str, b: str, d: date) -> str:
    p = cfg["pasajeros"]
    q = {"adultsv2": p["adultos"], "cabinclass": "economy", "rtn": 0, "currency": cfg.get("moneda", "USD")}
    if p.get("edades_chicos"):
        q["childrenv2"] = "|".join(str(e) for e in p["edades_chicos"])
    return (f"https://www.skyscanner.com.ar/transport/flights/{SKY.get(a, a.lower())}/"
            f"{SKY.get(b, b.lower())}/{d.strftime('%y%m%d')}/?" + urlencode(q))


LINK_EDREAMS = "https://www.edreams.com.ar/"
LINK_CHEAPOAIR = "https://www.cheapoair.com/"


def _a(url: str, texto: str) -> str:
    return f'<a href="{_h(url, quote=True)}">{texto}</a>'


def links_tramo(cfg: dict, t: dict, mejor: Vuelo | None) -> str:
    ca, cb = t["ciudades"]
    g = link_google(cfg, [(mejor.desde, mejor.hasta, mejor.fecha)]) if mejor else \
        link_google(cfg, [(t["pares"][0][0], t["pares"][0][1], t["fecha"])])
    partes = [
        _a(g, "Google Flights"),
        _a(link_cheapflights(cfg, [(ca, cb, t["fecha"])], flex=t.get("flex", 0)), f"Cheapflights ±{t.get('flex', 0)} días"),
        _a(link_expedia(cfg, [(ca, cb, t["fecha"])]), "Expedia"),
        _a(link_skyscanner(cfg, ca, cb, t["fecha"]), "Skyscanner"),
        _a(LINK_EDREAMS, "eDreams"),
        _a(LINK_CHEAPOAIR, "CheapOair"),
    ]
    return "🔗 " + " · ".join(partes)


# --- textos ---------------------------------------------------------------------
def _usd(v: float) -> str:
    return "USD " + f"{v:,.0f}".replace(",", ".")


def _dia(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def _detalle(v: Vuelo) -> str:
    esc = "directo" if v.escalas == 0 else f"{v.escalas} escala" + ("s" if v.escalas > 1 else "")
    horario = f"{v.desde} {v.salida} → {v.hasta} {v.llegada}" + (f" (+{v.mas_dias})" if v.mas_dias else "") \
        if v.salida else f"{v.desde} → {v.hasta}"
    return f"{_dia(v.fecha)} · {v.aerolinea or 's/d'} · {horario} · {esc}"


def _pct(nuevo: float, viejo: float) -> str:
    return f"{(nuevo / viejo - 1) * 100:+.1f}%".replace(".", ",")


def _itinerarios(cfg: dict, vuelos: list[Vuelo]) -> list[str]:
    lineas = []
    for it in cfg.get("itinerarios", []):
        total, piezas, faltan = 0.0, [], False
        for t in cfg["tramos"]:
            d = it["fechas"].get(t["id"])
            v = mejor_por_fecha(vuelos, t["id"]).get(d)
            if v is None:
                faltan = True
                break
            total += v.precio
            piezas.append((v.desde, v.hasta, d))
        nombre = it["nombre"]
        if faltan:
            lineas.append(f"• {nombre}: sin precio completo en esta consulta")
            continue
        ref = cfg.get("referencia", {}).get("precio")
        vs = f" ({_pct(total, ref)} vs referencia)" if ref else ""
        ciudades = [(t["ciudades"][0], t["ciudades"][1], it["fechas"][t["id"]]) for t in cfg["tramos"]]
        lineas.append(
            f"• {nombre}: <b>{_usd(total)}</b> sumando solos ida{vs}\n"
            f"  🔗 {_a(link_google(cfg, piezas), 'Google multidestino')} · "
            f"{_a(link_cheapflights(cfg, ciudades), 'Cheapflights multidestino')} · "
            f"{_a(link_expedia(cfg, ciudades), 'Expedia multidestino')}"
        )
    return lineas


def reporte(storage: Storage, cfg: dict, titulo: str = "Reporte diario") -> str:
    chequeo, vuelos = ultimo_chequeo(storage)
    if not vuelos:
        return f"🧳 <b>{cfg['nombre']}</b>\nTodavía no hay precios: la primera consulta está en curso."
    mejores = mejor_por_tramo(vuelos)
    previo = json.loads(storage.kv_get("viaje_reporte_previo") or "{}")
    n = pasajes(cfg)
    hora = datetime.fromisoformat(chequeo).replace(tzinfo=timezone.utc).astimezone(ART)
    L = [f"🧳 <b>{cfg['nombre']}</b> · {titulo}",
         f"👨‍👩‍👧‍👦 {cfg['pasajeros'].get('detalle', '')} · {n} pasajes · precios totales",
         f"🕒 Consulta de las {hora.strftime('%H:%M')} (Google Flights)"]

    total = sum(v.precio for v in mejores.values())
    completo = len(mejores) == len(cfg["tramos"])
    ref = cfg.get("referencia", {})
    L.append("")
    if completo:
        linea = f"💡 <b>Mejor forma hoy: {_usd(total)}</b> comprando los 3 tramos por separado"
        if ref.get("precio"):
            dif = total - ref["precio"]
            linea += (f"\n   {'🟢 ' + _usd(-dif) + ' menos' if dif < 0 else '🔴 ' + _usd(dif) + ' más'} "
                      f"que la referencia {_usd(ref['precio'])} ({ref.get('detalle', '')})")
        if previo.get("total"):
            linea += f"\n   Ayer: {_usd(previo['total'])} ({_pct(total, previo['total'])})"
        L.append(linea)

    for i, t in enumerate(cfg["tramos"], 1):
        v = mejores.get(t["id"])
        L.append("")
        rango = f"{_dia(fechas_tramo(t)[0])} al {_dia(fechas_tramo(t)[-1])}"
        L.append(f"✈️ <b>Tramo {i} · {t['nombre']}</b> ({rango})")
        if not v:
            L.append("   sin resultados en esta consulta")
        else:
            L.append(f"   Mejor: <b>{_usd(v.precio)}</b> ({_usd(v.precio / n)} c/u)")
            L.append(f"   {_detalle(v)}")
            extra = []
            if previo.get(t["id"]):
                extra.append(f"ayer {_usd(previo[t['id']])} ({_pct(v.precio, previo[t['id']])})")
            mh = minimo_historico(storage, t["id"])
            if mh:
                extra.append(f"mínimo visto {_usd(mh)}")
            if extra:
                L.append("   " + " · ".join(extra))
            por_dia = mejor_por_fecha(vuelos, t["id"])
            L.append("   Por día: " + " · ".join(f"{d.day:02d}/{d.month:02d} {_usd(x.precio).replace('USD ', '')}"
                                                  for d, x in por_dia.items()))
        L.append("   " + links_tramo(cfg, t, v))

    its = _itinerarios(cfg, vuelos)
    if its:
        L += ["", "🗺 <b>Tus itinerarios</b> (mismas fechas que las capturas)"] + its
    L += ["", "<i>El de 12 paga como adulto; Google cotiza también al de 8 como adulto, así que el "
              "precio real puede ser algo menor. El multidestino de una sola aerolínea a veces sale "
              "más barato que la suma: revisalo en los links multidestino.</i>"]
    return "\n".join(L)


def aviso_baja(cfg: dict, t: dict, i: int, v: Vuelo, antes: float, total: float | None) -> str:
    n = pasajes(cfg)
    L = [f"📉 <b>BAJÓ · Tramo {i} · {t['nombre']}</b>",
         f"<b>{_usd(v.precio)}</b> los {n} ({_usd(v.precio / n)} c/u) · antes el mínimo era {_usd(antes)} "
         f"({_pct(v.precio, antes)})",
         f"🗓 {_detalle(v)}"]
    ref = cfg.get("referencia", {}).get("precio")
    if total:
        L.append(f"🧮 Mejor combinación de los 3 tramos ahora: {_usd(total)}" +
                 (f" (referencia {_usd(ref)})" if ref else ""))
    L.append(links_tramo(cfg, t, v))
    return "\n".join(L)


# --- ciclo -----------------------------------------------------------------------
def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def chequear(storage: Storage, cfg: dict, send, buscar=buscar_google, pausa: float = 1.5,
             ahora: datetime | None = None) -> int:
    """Consulta todo, guarda y avisa las bajas. Devuelve cuántos avisos mandó."""
    chequeo = (ahora or _ahora_utc()).strftime("%Y-%m-%dT%H:%M:%S")
    vuelos = consultar(cfg, buscar=buscar, pausa=pausa)
    storage.kv_set("viaje_ultimo_chequeo", chequeo)
    if not vuelos:
        print("[viaje] la consulta no trajo precios", file=sys.stderr)
        return 0
    guardar(storage, vuelos, chequeo)
    mejores = mejor_por_tramo(vuelos)
    total = sum(v.precio for v in mejores.values()) if len(mejores) == len(cfg["tramos"]) else None
    avisos = 0
    for i, t in enumerate(cfg["tramos"], 1):
        v = mejores.get(t["id"])
        antes = minimo_historico(storage, t["id"], antes_de=chequeo)
        if v and antes and v.precio < antes * (1 - BAJA_MINIMA):
            send(aviso_baja(cfg, t, i, v, antes, total))
            avisos += 1
    print(f"[viaje] {len(vuelos)} precios · mejores: " +
          ", ".join(f"{k} {v.precio:.0f}" for k, v in sorted(mejores.items())) + f" · {avisos} aviso(s)")
    return avisos


def _guardar_previo(storage: Storage, cfg: dict) -> None:
    _, vuelos = ultimo_chequeo(storage)
    mejores = mejor_por_tramo(vuelos)
    d = {k: v.precio for k, v in mejores.items()}
    if len(mejores) == len(cfg["tramos"]):
        d["total"] = sum(d.values())
    storage.kv_set("viaje_reporte_previo", json.dumps(d))


def tick(storage: Storage, send=None, buscar=buscar_google, cfg: dict | None = None,
         ahora: datetime | None = None, pausa: float = 1.5) -> None:
    """Llamado seguido desde el modo continuo: hace lo que toque."""
    cfg = cfg or load_viaje()
    if not cfg:
        return
    ahora = ahora or _ahora_utc()
    destino = chat_id(cfg)
    if send is None:
        if not destino:
            send = lambda text: print("[viaje] (sin grupo configurado) " + text[:200])  # noqa: E731
        else:
            from .telegram import TelegramClient
            client = TelegramClient()
            send = lambda text: client.send_message(text, chat_id=destino)  # noqa: E731

    ultimo = storage.kv_get("viaje_ultimo_chequeo")
    cada = float(cfg.get("consultar_cada_min", 60))
    if not ultimo or (ahora - datetime.fromisoformat(ultimo).replace(tzinfo=timezone.utc)) >= timedelta(minutes=cada):
        try:
            chequear(storage, cfg, send, buscar=buscar, pausa=pausa, ahora=ahora)
        except Exception:
            print(f"[error] viaje:\n{traceback.format_exc()}", file=sys.stderr)

    if not destino:
        return
    # bienvenida: la primera vez que hay grupo configurado
    if storage.kv_get("viaje_bienvenida") != destino:
        try:
            send("👋 Este grupo es solo para el <b>" + cfg["nombre"] + "</b>.\n"
                 "Consulto cada hora, te aviso al instante si baja algún tramo y todos los días a las "
                 f"{cfg.get('hora_reporte', 10)}:00 te mando el resumen. Pedilo cuando quieras con /viaje.")
            # se marca ANTES de mandar: si algo falla, no se repite en cada vuelta
            storage.kv_set("viaje_bienvenida", destino)
            if ahora.astimezone(ART).hour >= int(cfg.get("hora_reporte", 10)):
                storage.kv_set("viaje_reporte_fecha", ahora.astimezone(ART).date().isoformat())
            send(reporte(storage, cfg, titulo="Primer reporte"))
            _guardar_previo(storage, cfg)
        except Exception:
            print(f"[error] viaje bienvenida:\n{traceback.format_exc()}", file=sys.stderr)
        return
    # reporte diario
    local = ahora.astimezone(ART)
    hoy = local.date().isoformat()
    if local.hour >= int(cfg.get("hora_reporte", 10)) and storage.kv_get("viaje_reporte_fecha") != hoy:
        try:
            storage.kv_set("viaje_reporte_fecha", hoy)  # antes de mandar: nunca repetir
            send(reporte(storage, cfg))
            _guardar_previo(storage, cfg)
        except Exception:
            print(f"[error] viaje reporte:\n{traceback.format_exc()}", file=sys.stderr)
