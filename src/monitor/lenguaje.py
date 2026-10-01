"""Mensajes en castellano común para agregar o sacar rutas desde Telegram.

Ejemplos que entiende:
    "Agregá el seguimiento de Buenos Aires - Punta Cana del 20/12/2026 al 27/12/2026"
    "sumá EZE MIA del 10/01/2027 al 20/01/2027 para 4, tope 2000, directo"
    "agregá Buenos Aires a Madrid ida 05/03/2027 vuelta 20/03/2027, 2 adultos y 2 chicos, ±3 días"
    "sacá la ruta 18"   /   "borrá la de Punta Cana"

Nunca cambia nada sin confirmar: arma la ruta, la muestra y espera un "sí".
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from .notifier import esc
from .storage import Storage

# --- ciudades -------------------------------------------------------------------
# nombre (sin acentos, minúsculas) -> (código para buscar, nombre lindo)
CIUDADES: dict[str, tuple[str, str]] = {
    "buenos aires": ("EZE", "Buenos Aires"), "bs as": ("EZE", "Buenos Aires"), "bsas": ("EZE", "Buenos Aires"),
    "ezeiza": ("EZE", "Buenos Aires"), "aeroparque": ("AEP", "Buenos Aires (Aeroparque)"),
    "cordoba": ("COR", "Córdoba"), "rosario": ("ROS", "Rosario"), "mendoza": ("MDZ", "Mendoza"),
    "bariloche": ("BRC", "Bariloche"), "ushuaia": ("USH", "Ushuaia"), "salta": ("SLA", "Salta"),
    "iguazu": ("IGR", "Iguazú"), "el calafate": ("FTE", "El Calafate"), "mar del plata": ("MDQ", "Mar del Plata"),
    "montevideo": ("MVD", "Montevideo"), "punta del este": ("PDP", "Punta del Este"),
    "santiago de chile": ("SCL", "Santiago de Chile"), "santiago": ("SCL", "Santiago de Chile"),
    "lima": ("LIM", "Lima"), "cusco": ("CUZ", "Cusco"), "bogota": ("BOG", "Bogotá"),
    "cartagena": ("CTG", "Cartagena"), "medellin": ("MDE", "Medellín"), "san andres": ("ADZ", "San Andrés"),
    "panama": ("PTY", "Panamá"), "asuncion": ("ASU", "Asunción"), "quito": ("UIO", "Quito"),
    "rio de janeiro": ("GIG", "Río de Janeiro"), "rio": ("GIG", "Río de Janeiro"),
    "sao paulo": ("GRU", "San Pablo"), "san pablo": ("GRU", "San Pablo"),
    "florianopolis": ("FLN", "Florianópolis"), "floripa": ("FLN", "Florianópolis"),
    "salvador": ("SSA", "Salvador de Bahía"), "bahia": ("SSA", "Salvador de Bahía"),
    "porto alegre": ("POA", "Porto Alegre"), "recife": ("REC", "Recife"), "natal": ("NAT", "Natal"),
    "maceio": ("MCZ", "Maceió"), "fortaleza": ("FOR", "Fortaleza"), "porto seguro": ("BPS", "Porto Seguro"),
    "punta cana": ("PUJ", "Punta Cana"), "cancun": ("CUN", "Cancún"), "playa del carmen": ("CUN", "Cancún"),
    "ciudad de mexico": ("MEX", "Ciudad de México"), "mexico": ("MEX", "Ciudad de México"),
    "la habana": ("HAV", "La Habana"), "habana": ("HAV", "La Habana"), "varadero": ("VRA", "Varadero"),
    "aruba": ("AUA", "Aruba"), "curazao": ("CUR", "Curazao"), "montego bay": ("MBJ", "Jamaica"),
    "jamaica": ("MBJ", "Jamaica"), "san juan": ("SJU", "San Juan (Puerto Rico)"),
    "miami": ("MIA", "Miami"), "orlando": ("MCO", "Orlando"), "nueva york": ("JFK", "Nueva York"),
    "new york": ("JFK", "Nueva York"), "ny": ("JFK", "Nueva York"), "los angeles": ("LAX", "Los Ángeles"),
    "las vegas": ("LAS", "Las Vegas"), "san francisco": ("SFO", "San Francisco"), "chicago": ("ORD", "Chicago"),
    "washington": ("IAD", "Washington"), "boston": ("BOS", "Boston"), "houston": ("IAH", "Houston"),
    "dallas": ("DFW", "Dallas"), "atlanta": ("ATL", "Atlanta"), "fort lauderdale": ("FLL", "Fort Lauderdale"),
    "toronto": ("YYZ", "Toronto"), "montreal": ("YUL", "Montreal"),
    "madrid": ("MAD", "Madrid"), "barcelona": ("BCN", "Barcelona"), "roma": ("FCO", "Roma"),
    "milan": ("MXP", "Milán"), "paris": ("CDG", "París"), "londres": ("LHR", "Londres"),
    "lisboa": ("LIS", "Lisboa"), "oporto": ("OPO", "Oporto"), "amsterdam": ("AMS", "Ámsterdam"),
    "frankfurt": ("FRA", "Fráncfort"), "berlin": ("BER", "Berlín"), "munich": ("MUC", "Múnich"),
    "zurich": ("ZRH", "Zúrich"), "viena": ("VIE", "Viena"), "praga": ("PRG", "Praga"),
    "atenas": ("ATH", "Atenas"), "estambul": ("IST", "Estambul"), "dublin": ("DUB", "Dublín"),
    "bruselas": ("BRU", "Bruselas"), "venecia": ("VCE", "Venecia"), "florencia": ("FLR", "Florencia"),
    "napoles": ("NAP", "Nápoles"), "sevilla": ("SVQ", "Sevilla"), "malaga": ("AGP", "Málaga"),
    "palma de mallorca": ("PMI", "Palma de Mallorca"), "mallorca": ("PMI", "Palma de Mallorca"),
    "ibiza": ("IBZ", "Ibiza"), "tenerife": ("TFS", "Tenerife"),
    "tokio": ("NRT", "Tokio"), "tokyo": ("NRT", "Tokio"), "dubai": ("DXB", "Dubái"), "doha": ("DOH", "Doha"),
    "bangkok": ("BKK", "Bangkok"), "singapur": ("SIN", "Singapur"), "sidney": ("SYD", "Sídney"),
    "sydney": ("SYD", "Sídney"), "seul": ("ICN", "Seúl"), "pekin": ("PEK", "Pekín"),
}
NOMBRE_DE_CODIGO = {code: nombre for code, nombre in CIUDADES.values()}
NOMBRE_DE_CODIGO.update({"EZE": "Buenos Aires", "AEP": "Buenos Aires", "JFK": "Nueva York", "EWR": "Nueva York",
                         "LGA": "Nueva York", "NRT": "Tokio (Narita)", "HND": "Tokio (Haneda)"})

PALABRAS_AGREGAR = ("agrega", "agregar", "agregame", "suma", "sumar", "sumame", "anadi", "anade", "anadir",
                    "segui", "seguir", "vigila", "vigilar", "nueva ruta", "carga", "cargar", "busca", "buscame",
                    "quiero seguir", "seguimiento")
PALABRAS_SACAR = ("saca", "sacar", "sacame", "borra", "borrar", "borrame", "elimina", "eliminar",
                  "quita", "quitar", "deja de seguir", "dejar de seguir", "no sigas")
SI = {"si", "sí", "s", "dale", "ok", "okey", "oka", "confirmo", "confirmar", "de una", "listo", "va", "agregala",
      "borrala", "sacala", "si dale", "dale si", "perfecto", "correcto"}
NO = {"no", "n", "cancelar", "cancela", "cancelá", "nada", "deja", "dejá", "olvidalo", "no gracias"}

PENDIENTE_MIN = 60  # una propuesta sin respuesta vence en 1 hora


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def _tiene(texto: str, palabras) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", texto) for p in palabras)


# --- interpretar -----------------------------------------------------------------
class NoEntendi(Exception):
    pass


def _ciudades(original: str) -> list[tuple[int, str, str]]:
    """Ciudades o códigos IATA en el orden en que aparecen: (posición, código, nombre)."""
    t = _norm(original)
    t = re.sub(r"[-–—→>/,]", " ", t)
    t = re.sub(r"\s+", " ", t)
    encontrados: list[tuple[int, int, str, str]] = []
    for nombre in sorted(CIUDADES, key=len, reverse=True):
        for m in re.finditer(rf"(?<![a-z]){re.escape(nombre)}(?![a-z])", t):
            if any(a <= m.start() < b for a, b, _, _ in encontrados):
                continue  # ya cubierto por un nombre más largo ("santiago de chile")
            code, lindo = CIUDADES[nombre]
            encontrados.append((m.start(), m.end(), code, lindo))
    # códigos de aeropuerto escritos en mayúsculas (EZE, MIA...)
    for m in re.finditer(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])", original):
        code = m.group(1)
        if code in {"USD", "ARS", "EUR", "DIA", "SIN"} and code not in NOMBRE_DE_CODIGO:
            continue
        pos = len(_norm(original[: m.start()]))
        if not any(a <= pos < b for a, b, _, _ in encontrados):
            encontrados.append((pos, pos + 3, code, NOMBRE_DE_CODIGO.get(code, code)))
    encontrados.sort()
    return [(a, c, n) for a, _, c, n in encontrados]


def _fechas(t: str, hoy: date) -> list[date]:
    out = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?!\d)", t):
        d, mth, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y is None:
            year = hoy.year
            try:
                cand = date(year, mth, d)
            except ValueError:
                raise NoEntendi(f"la fecha {m.group(0)} no existe")
            if cand < hoy:
                cand = date(year + 1, mth, d)
            out.append(cand)
            continue
        year = int(y) + (2000 if len(y) == 2 else 0)
        try:
            out.append(date(year, mth, d))
        except ValueError:
            raise NoEntendi(f"la fecha {m.group(0)} no existe")
    return out


def interpretar_alta(texto: str, hoy: date | None = None) -> dict:
    """Devuelve los campos de la ruta nueva, o lanza NoEntendi con el motivo."""
    hoy = hoy or date.today()
    t = _norm(texto)
    ciudades = _ciudades(texto)
    if len(ciudades) < 2:
        if len(ciudades) == 1:
            raise NoEntendi(f"reconocí solo una ciudad ({ciudades[0][2]}). Decime origen y destino, "
                            "o usá el código de aeropuerto (ej: EZE PUJ)")
        raise NoEntendi("no reconocí las ciudades. Probá con el nombre o el código de aeropuerto (ej: EZE PUJ)")
    (_, origen, n_origen), (_, destino, n_destino) = ciudades[0], ciudades[1]
    if origen == destino:
        raise NoEntendi("el origen y el destino son la misma ciudad")

    fechas = _fechas(t, hoy)
    if not fechas:
        raise NoEntendi("no encontré fechas. Escribilas así: del 20/12/2026 al 27/12/2026")
    ida = fechas[0]
    vuelta = fechas[1] if len(fechas) > 1 else None
    solo_ida = vuelta is None or _tiene(t, ("solo ida", "sólo ida", "one way"))
    if solo_ida:
        vuelta = None
    if ida <= hoy:
        raise NoEntendi(f"la ida ({ida:%d/%m/%Y}) ya pasó")
    if vuelta and vuelta <= ida:
        raise NoEntendi(f"la vuelta ({vuelta:%d/%m/%Y}) es antes de la ida ({ida:%d/%m/%Y})")

    flex = 0
    m = re.search(r"(?:±|\+-|\+/-|mas o menos|más o menos)\s*(\d{1,2})\s*dias?", t) or \
        re.search(r"(\d{1,2})\s*dias?\s*(?:antes o despues|antes y despues|de flexibilidad|flexibles?)", t)
    if m:
        flex = int(m.group(1))
    if _tiene(t, ("fechas exactas", "exacto", "exactas", "exactamente")):
        flex = 0

    adultos, chicos = 1, 0
    m_ad = re.search(r"(\d+)\s*adult", t)
    m_ch = re.search(r"(\d+)\s*(?:chicos?|ninos?|ninas?|menores?|nenes?|hijos?)", t)
    m_pa = re.search(r"para\s*(\d+)(?![\d/.\-])(?!\s*(?:dias?|noches?))", t) or re.search(r"(\d+)\s*(?:personas|pasajeros|pax)", t)
    if m_ad:
        adultos = int(m_ad.group(1))
    if m_ch:
        chicos = int(m_ch.group(1))
    if not m_ad and not m_ch and m_pa:
        adultos = int(m_pa.group(1))
    if not 1 <= adultos + chicos <= 9:
        raise NoEntendi("la cantidad de pasajeros tiene que ser entre 1 y 9")

    tope = None
    m = re.search(r"(?:tope|hasta|maximo|menos de|por debajo de)\s*(?:de\s*)?(?:usd|u\$s|us\$|\$)?\s*(\d[\d.,]*)(?![\d/])", t)
    if m:
        tope = float(m.group(1).replace(".", "").replace(",", ""))
    baja = 30.0
    m = re.search(r"baj[ae]\s*(?:un\s*)?(\d{1,2})\s*%", t)
    if m:
        baja = float(m.group(1))
    directo = _tiene(t, ("directo", "directos", "sin escalas", "sin escala"))

    noches = (vuelta - ida).days if vuelta else None
    rango = f"{ida:%d/%m}" + (f"–{vuelta:%d/%m}" if vuelta else "")
    nombre = f"{n_origen} → {n_destino} · {rango}"
    return {
        "name": nombre, "origin": origen, "dest": destino,
        "depart_from": (ida - timedelta(days=flex)).isoformat(),
        "depart_to": (ida + timedelta(days=flex)).isoformat(),
        "return_min": noches, "return_max": noches,
        "adults": adultos, "children": chicos,
        "target_price": tope, "drop_pct": baja, "nonstop": int(directo),
        "currency": "USD", "active": 1,
        "_ida": ida.isoformat(), "_vuelta": vuelta.isoformat() if vuelta else None, "_flex": flex,
        "_n_origen": n_origen, "_n_destino": n_destino,
    }


def describir_alta(c: dict) -> str:
    ida = date.fromisoformat(c["_ida"])
    vuelta = date.fromisoformat(c["_vuelta"]) if c["_vuelta"] else None
    pax = f"{c['adults']} adulto" + ("s" if c["adults"] != 1 else "")
    if c["children"]:
        pax += f" + {c['children']} chico" + ("s" if c["children"] != 1 else "")
    flex = f" (±{c['_flex']} días)" if c["_flex"] else " (fecha exacta)"
    L = [
        "🆕 <b>¿Agrego esta ruta?</b>",
        f"✈️ <b>{esc(c['_n_origen'])} ({c['origin']}) → {esc(c['_n_destino'])} ({c['dest']})</b>",
        f"🛫 Ida: {ida:%d/%m/%Y}{flex}",
        (f"🛬 Vuelta: {vuelta:%d/%m/%Y} · {c['return_min']} noches" if vuelta else "🛬 Solo ida"),
        f"👥 {pax}" + ("  ·  <i>si viajan más, decime \"para 4\" o \"2 adultos y 2 chicos\"</i>"
                      if c["adults"] + c["children"] == 1 else ""),
        "🎯 Aviso: " + (f"si cuesta USD {c['target_price']:,.0f} o menos (total), " if c["target_price"] else "")
        + f"si baja {c['drop_pct']:.0f}% de lo normal y si queda en el mínimo"
        + (" · solo directos" if c["nonstop"] else ""),
        "",
        "Respondé <b>SÍ</b> para agregarla o <b>NO</b> para cancelar. Si algo está mal, mandámelo de nuevo corregido.",
    ]
    return "\n".join(L)


def interpretar_baja(texto: str, storage: Storage) -> list:
    """Rutas activas a las que se refiere el mensaje."""
    t = _norm(texto)
    rutas = storage.list_routes(active_only=True)
    ids = [int(x) for x in re.findall(r"(?:#|ruta\s*|numero\s*|nro\.?\s*|n°\s*|la\s+)(\d{1,4})(?!\d|/)", t)]
    if not ids:
        ids = [int(x) for x in re.findall(r"(?<![\d/])(\d{1,4})(?![\d/])", t)]
    if ids:
        return [r for r in rutas if r.id in ids]
    codigos = {c for _, c, _ in _ciudades(texto)}
    codigos.discard("EZE")  # "Buenos Aires" está en casi todas: decide el destino
    if not codigos:
        return []
    ny = {"JFK", "EWR", "LGA"}
    out = []
    for r in rutas:
        cods = {r.origin, r.dest} | ({r.ret_origin} if r.ret_origin else set())
        if ny & cods:
            cods |= ny
        if r.dest == "NRT" or r.dest == "HND":
            cods |= {"NRT", "HND"}
        if codigos <= cods:
            out.append(r)
    return out


# --- conversación ------------------------------------------------------------------
def _clave(chat_id) -> str:
    return f"pendiente_{chat_id}"


def _guardar_pendiente(storage: Storage, chat_id, accion: str, datos) -> None:
    vence = (datetime.now(timezone.utc) + timedelta(minutes=PENDIENTE_MIN)).isoformat()
    storage.kv_set(_clave(chat_id), json.dumps({"accion": accion, "datos": datos, "vence": vence}))


def _leer_pendiente(storage: Storage, chat_id) -> dict | None:
    raw = storage.kv_get(_clave(chat_id))
    if not raw:
        return None
    p = json.loads(raw)
    if not p or datetime.fromisoformat(p["vence"]) < datetime.now(timezone.utc):
        return None
    return p


def _borrar_pendiente(storage: Storage, chat_id) -> None:
    storage.kv_set(_clave(chat_id), "null")


AYUDA = ("Podés escribirme, por ejemplo:\n"
         "• <i>Agregá Buenos Aires - Punta Cana del 20/12/2026 al 27/12/2026 para 4</i>\n"
         "• <i>Sumá EZE MIA ida 10/01/2027 vuelta 20/01/2027, 2 adultos y 2 chicos, tope 2000, ±2 días</i>\n"
         "• <i>Sacá la ruta 18</i>  ·  <i>Borrá la de Punta Cana</i>\n"
         "Siempre te pido confirmación antes de cambiar algo. /rutas muestra todas.")


def responder(texto: str, storage: Storage, chat_id) -> str:
    """Respuesta a un mensaje sin barra."""
    t = _norm(texto).strip(" .!¡¿?")
    pendiente = _leer_pendiente(storage, chat_id)

    if pendiente and t in SI:
        _borrar_pendiente(storage, chat_id)
        if pendiente["accion"] == "alta":
            campos = {k: v for k, v in pendiente["datos"].items() if not k.startswith("_")}
            nuevo = storage.add_route(**campos)
            return (f"✅ Listo: ruta <b>#{nuevo}</b> agregada ({esc(campos['name'])}).\n"
                    "La primera consulta de precios sale en los próximos minutos; la ves con /rutas.")
        if pendiente["accion"] == "baja":
            rid = pendiente["datos"]["id"]
            storage.set_route_active(rid, False)
            return f"🗑️ Listo: ruta <b>#{rid}</b> ({esc(pendiente['datos']['nombre'])}) ya no se sigue."
    if pendiente and t in NO:
        _borrar_pendiente(storage, chat_id)
        return "👌 Cancelado, no cambié nada."

    if _tiene(t, PALABRAS_SACAR):
        rutas = interpretar_baja(texto, storage)
        if not rutas:
            return "No encontré esa ruta entre las activas. Mirá los números con /rutas y decime, por ejemplo, <i>sacá la ruta 18</i>."
        if len(rutas) > 1:
            lista = "\n".join(f"• <b>#{r.id}</b> {esc(r.name)}" for r in rutas)
            return f"Encontré varias:\n{lista}\n\n¿Cuál saco? Decime, por ejemplo, <i>sacá la ruta {rutas[0].id}</i>."
        r = rutas[0]
        _guardar_pendiente(storage, chat_id, "baja", {"id": r.id, "nombre": r.name})
        return (f"🗑️ <b>¿Dejo de seguir la ruta #{r.id}?</b>\n{esc(r.name)} ({r.origin} → {r.dest})\n\n"
                "Respondé <b>SÍ</b> para sacarla o <b>NO</b> para cancelar.")

    if _tiene(t, PALABRAS_AGREGAR) or (len(_ciudades(texto)) >= 2 and re.search(r"\d{1,2}/\d{1,2}", t)):
        try:
            campos = interpretar_alta(texto)
        except NoEntendi as e:
            return f"🤔 No pude armar la ruta: {esc(str(e))}.\n\n{AYUDA}"
        _guardar_pendiente(storage, chat_id, "alta", campos)
        return describir_alta(campos)

    if pendiente and pendiente["accion"] in ("alta", "baja"):
        return "Tengo una propuesta esperando: respondé <b>SÍ</b> o <b>NO</b>."
    return "🤔 No te entendí.\n\n" + AYUDA
