from __future__ import annotations

import os
import sys
import traceback
from datetime import date

from .config import has_no_alert_criteria
from .models import RouteQuery
from .notifier import esc
from .storage import Storage
from .telegram import TelegramClient

HELP = (
    "<b>Comandos</b>\n"
    "/rutas — lista las rutas vigiladas\n"
    "/crear ORIG DEST IDA_DESDE..IDA_HASTA NOCHES TOPE [BAJA%] [--directo] [--pax N]\n"
    "    ej: <code>/crear EZE JFK 2026-11-01..2027-03-31 7-14 450 40</code>\n"
    "    solo ida: poné <code>-</code> en NOCHES\n"
    "/editar ID CAMPO VALOR — campos: nombre tope baja pax directo ida_desde ida_hasta noches\n"
    "    ej: <code>/editar 3 tope 400</code>\n"
    "/borrar ID — elimina (confirmá con <code>/borrar ID si</code>)\n"
    "/pausar ID   /activar ID"
)


class CommandError(Exception):
    """Error de uso: el mensaje va directo al usuario."""


# --- parsing helpers -------------------------------------------------------
def _date(s: str) -> str:
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise CommandError(f"fecha inválida: '{s}' (usá AAAA-MM-DD)")


def _date_range(s: str) -> tuple[str, str]:
    if ".." not in s:
        raise CommandError(f"ventana de ida inválida: '{s}' (usá AAAA-MM-DD..AAAA-MM-DD)")
    a, b = s.split("..", 1)
    lo, hi = _date(a), _date(b)
    if lo > hi:
        raise CommandError("IDA_DESDE no puede ser posterior a IDA_HASTA")
    return lo, hi


def _nights(s: str) -> tuple[int | None, int | None]:
    if s == "-":
        return None, None
    try:
        if "-" in s:
            lo, hi = (int(x) for x in s.split("-", 1))
        else:
            lo = hi = int(s)
    except ValueError:
        raise CommandError(f"NOCHES inválido: '{s}' (usá '7-21', '10' o '-')")
    if lo > hi or lo < 0:
        raise CommandError("NOCHES: el mínimo es mayor que el máximo")
    return lo, hi


def _price(s: str) -> float | None:
    if s == "-":
        return None
    try:
        v = float(s.replace(",", "."))
    except ValueError:
        raise CommandError(f"número inválido: '{s}'")
    if v <= 0:
        raise CommandError("el valor tiene que ser positivo")
    return v


def _airport(s: str) -> str:
    s = s.upper()
    if len(s) != 3 or not s.isalpha():
        raise CommandError(f"código de aeropuerto inválido: '{s}' (3 letras, ej EZE)")
    return s


def _route_line(r: RouteQuery, storage: Storage) -> str:
    if r.return_after_days:
        lo, hi = r.return_after_days
        nights = f"{lo} noches" if lo == hi else f"{lo}–{hi} noches"
    else:
        nights = "solo ida"
    crit = []
    if r.target_price is not None:
        crit.append(f"tope {r.currency} {r.target_price:.0f}")
    if r.drop_pct is not None:
        crit.append(f"baja {r.drop_pct:.0f}%")
    last = storage.last_price(r.key)
    last_txt = f" · último visto: {r.currency} {last:.0f}" if last is not None else ""
    if r.is_open_jaw:
        nights = f"vuelta {r.ret_origin}→{r.origin} entre {r.ret_range[0]} y {r.ret_range[1]}"
    return (
        f"<b>#{r.id}</b> · {esc(r.name)}\n"
        f"   {r.origin}→{r.dest} · ida {r.depart_range[0]}→{r.depart_range[1]} · {nights} · {esc(r.pax_label)}\n"
        f"   {esc(' · '.join(crit) or 'sin criterio de alerta')}{last_txt}"
    )


# --- comandos -------------------------------------------------------------
def cmd_help(args, storage) -> str:
    return HELP


def cmd_list(args, storage) -> str:
    routes = storage.list_routes(active_only=True)
    if not routes:
        return "No hay rutas activas. Creá una con /crear."
    return "📋 <b>Rutas vigiladas</b>\n\n" + "\n\n".join(_route_line(r, storage) for r in routes)


def cmd_create(args, storage) -> str:
    if len(args) < 5:
        raise CommandError("faltan datos.\n\n" + HELP)
    origin = _airport(args[0])
    dest = _airport(args[1])
    depart_from, depart_to = _date_range(args[2])
    return_min, return_max = _nights(args[3])
    target = _price(args[4])

    drop = None
    nonstop = 0
    adults = 1
    rest = list(args[5:])
    while rest:
        tok = rest.pop(0)
        if tok in ("--directo", "--nonstop"):
            nonstop = 1
        elif tok == "--pax":
            if not rest:
                raise CommandError("--pax necesita un número")
            adults = int(rest.pop(0))
        elif drop is None:
            drop = _price(tok)
            if drop > 100:
                raise CommandError("BAJA% tiene que estar entre 1 y 100")
        else:
            raise CommandError(f"no entiendo: '{tok}'")

    fields = dict(
        name=f"{origin}→{dest}", origin=origin, dest=dest,
        depart_from=depart_from, depart_to=depart_to,
        return_min=return_min, return_max=return_max,
        adults=adults, target_price=target, drop_pct=drop,
        nonstop=nonstop, currency="USD", active=1,
    )
    probe = RouteQuery(
        name="", origin=origin, dest=dest,
        depart_range=(date.fromisoformat(depart_from), date.fromisoformat(depart_to)),
        target_price=target, drop_pct=drop,
    )
    if has_no_alert_criteria(probe):
        raise CommandError("poné al menos TOPE o BAJA%, si no nunca avisa")

    new_id = storage.add_route(**fields)
    warn = "" if depart_from > date.today().isoformat() else "\n⚠️ la ventana de ida ya pasó"
    return f"✅ Ruta <b>#{new_id}</b> creada: {origin}→{dest}{warn}"


_EDIT_FIELDS = {
    "nombre": "name", "tope": "target_price", "baja": "drop_pct", "pax": "adults",
    "directo": "nonstop", "ida_desde": "depart_from", "ida_hasta": "depart_to",
}


def cmd_edit(args, storage) -> str:
    if len(args) < 3:
        raise CommandError("uso: /editar ID CAMPO VALOR")
    route_id = _int_id(args[0])
    field = args[1].lower()
    value_raw = " ".join(args[2:])
    if storage.get_route(route_id) is None:
        raise CommandError(f"la ruta #{route_id} no existe")

    if field == "noches":
        lo, hi = _nights(value_raw)
        storage.update_route(route_id, return_min=lo, return_max=hi)
    elif field == "directo":
        storage.update_route(route_id, nonstop=1 if _flag(value_raw) else 0)
    elif field in ("tope", "baja"):
        v = _price(value_raw)
        if field == "baja" and v is not None and v > 100:
            raise CommandError("BAJA% tiene que estar entre 1 y 100")
        storage.update_route(route_id, **{_EDIT_FIELDS[field]: v})
    elif field == "pax":
        storage.update_route(route_id, adults=int(value_raw))
    elif field in ("ida_desde", "ida_hasta"):
        storage.update_route(route_id, **{_EDIT_FIELDS[field]: _date(value_raw)})
    elif field == "nombre":
        storage.update_route(route_id, name=value_raw)
    else:
        raise CommandError(f"campo desconocido: '{field}'\ncampos: {', '.join(_EDIT_FIELDS)}, noches")

    return f"✏️ #{route_id} actualizada.\n\n{_route_line(storage.get_route(route_id), storage)}"


def cmd_delete(args, storage) -> str:
    if not args:
        raise CommandError("uso: /borrar ID")
    route_id = _int_id(args[0])
    route = storage.get_route(route_id)
    if route is None or not route.active:
        raise CommandError(f"la ruta #{route_id} no existe o ya fue borrada")
    if len(args) < 2 or args[1].lower() not in ("si", "sí"):
        return f"¿Borrar <b>#{route_id}</b> ({esc(route.name)})? Confirmá: <code>/borrar {route_id} si</code>"
    storage.set_route_active(route_id, False)
    return f"🗑️ Ruta #{route_id} borrada."


def cmd_pause(args, storage) -> str:
    return _toggle(args, storage, active=False, verb="pausada")


def cmd_activate(args, storage) -> str:
    return _toggle(args, storage, active=True, verb="reactivada")


def _toggle(args, storage, active: bool, verb: str) -> str:
    if not args:
        raise CommandError("falta el ID")
    route_id = _int_id(args[0])
    if not storage.set_route_active(route_id, active):
        raise CommandError(f"la ruta #{route_id} no existe")
    return f"#{route_id} {verb}."


def _int_id(s: str) -> int:
    try:
        return int(s.lstrip("#"))
    except ValueError:
        raise CommandError(f"ID inválido: '{s}'")


def _flag(s: str) -> bool:
    return s.strip().lower() in ("si", "sí", "true", "1", "yes", "on")


COMMANDS = {
    "start": cmd_help, "help": cmd_help, "ayuda": cmd_help,
    "rutas": cmd_list, "listar": cmd_list, "list": cmd_list,
    "crear": cmd_create, "nueva": cmd_create,
    "editar": cmd_edit,
    "borrar": cmd_delete, "eliminar": cmd_delete,
    "pausar": cmd_pause, "activar": cmd_activate,
}


def handle_message(text: str, storage: Storage) -> str:
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return ""
    cmd = parts[0].split("@", 1)[0].lstrip("/").lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        return f"Comando desconocido: /{esc(cmd)}\n\n{HELP}"
    try:
        return handler(parts[1:], storage)
    except CommandError as exc:
        return f"⚠️ {exc}"


def _allowed_chat_ids() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID", "")
    ids = {int(x) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}
    return ids


def poll_and_handle(storage: Storage, telegram: TelegramClient | None = None) -> int:
    """Lee comandos nuevos de Telegram, los ejecuta y responde. Devuelve cuántos trató."""
    allowed = _allowed_chat_ids()
    if not allowed:
        # Sin TELEGRAM_CHAT_ID no se leen comandos: así no se "consume" el
        # primer mensaje (lo necesita obtener-chat-id) ni se aceptan extraños.
        print("[aviso] falta TELEGRAM_CHAT_ID: no leo comandos de Telegram", file=sys.stderr)
        return 0
    telegram = telegram or TelegramClient()
    last = storage.kv_get("telegram_offset")
    offset = int(last) + 1 if last else None

    handled = 0
    max_id: int | None = None
    for update in telegram.get_updates(offset=offset):
        max_id = update["update_id"]
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            continue
        chat_id = msg["chat"]["id"]
        if allowed and chat_id not in allowed:
            continue
        try:
            reply = handle_message(msg["text"], storage)
        except Exception:
            traceback.print_exc()
            reply = "⚠️ error interno al procesar el comando"
        if reply:
            telegram.send_message(reply, chat_id=chat_id)
            handled += 1

    if max_id is not None:
        storage.kv_set("telegram_offset", str(max_id))
    return handled
