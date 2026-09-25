from __future__ import annotations

import argparse
import os
import sys
import traceback

from dotenv import load_dotenv

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # la consola de Windows usa cp1252
    except (AttributeError, ValueError):
        pass

from .bot import handle_message, poll_and_handle
from .config import CONFIG_PATH, load_routes_from_yaml
from .feeds import check_feeds
from .notifier import TelegramNotifier, esc, format_alert
from .rules import evaluate
from .sources import get_source
from .storage import Storage
from .telegram import TelegramClient

# Cada cuántas horas se consultan precios en Google Flights (las corridas
# intermedias solo leen los feeds y los comandos de Telegram).
SWEEP_INTERVAL_H = float(os.environ.get("HORAS_ENTRE_BARRIDOS", "3"))


def run_sweep(storage: Storage, dry_run: bool = False, source_name: str = "fastflights") -> int:
    source = get_source(source_name)
    notifier = None  # se crea solo si hay algo que avisar
    delivery_broken = False  # si falla un envío, el resto solo se imprime

    routes = storage.list_routes(active_only=True)
    alerts = 0
    for route in routes:
        # búsqueda + base de datos: si falla una ruta, siguen las demás
        try:
            offers = source.search(route)
            if not offers:
                print(f"[info] {route.name}: sin ofertas")
                continue
            cheapest = min(offers, key=lambda o: o.price)
            decision = evaluate(route, cheapest, storage)  # antes de grabar: la referencia no incluye este precio
            storage.record(cheapest)
        except Exception:
            print(f"[error] {route.name}:\n{traceback.format_exc()}", file=sys.stderr)
            continue

        base = f"{decision.baseline:.0f}" if decision.baseline is not None else "sin historial"
        print(f"[info] {route.name}: más barato {cheapest.currency} {cheapest.price:.0f} (mediana 30 días: {base})")

        if decision.should_alert:
            msg = format_alert(route, cheapest, decision)
            if dry_run or delivery_broken:
                print("---- ALERTA (no enviada) ----\n" + msg + "\n------------------------------")
            else:
                try:
                    notifier = notifier or TelegramNotifier()
                    notifier.send(msg)
                    storage.mark_alerted(cheapest.route_key, cheapest.price)
                except Exception as exc:
                    delivery_broken = True
                    print(f"[aviso] alerta no enviada ({exc}):\n{msg}", file=sys.stderr)
            alerts += 1

    print(f"[fin] {len(routes)} rutas, {alerts} alerta(s)")
    return alerts


def _telegram_sender(dry_run: bool):
    """Función que manda un texto a Telegram (o lo imprime en modo prueba)."""
    if dry_run:
        return lambda text: print("---- ALERTA FEED (no enviada) ----\n" + text)
    client = {}

    def send(text: str) -> None:
        client.setdefault("c", TelegramClient()).send_message(text)

    return send


def _weekly_heartbeat(storage: Storage) -> None:
    """Los lunes manda un 'sigo vivo' con lo que hizo en la semana, así te
    enterás si alguna fuente dejó de funcionar."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    week = now.strftime("%G-W%V")
    if now.weekday() != 0 or now.hour < 12 or storage.kv_get("heartbeat_week") == week:
        return
    precios = storage.count_since("price_history", "seen_at", 7)
    posts = storage.count_since("feed_seen", "seen_at", 7)
    rutas = len(storage.list_routes(active_only=True))
    aviso = "\n⚠️ <b>No registré precios esta semana</b>: puede que Google esté bloqueando las consultas." if precios == 0 else ""
    msg = (
        "🟢 <b>Sigo vivo</b> · resumen de la semana\n"
        f"• {rutas} rutas vigiladas\n"
        f"• {precios} precios registrados\n"
        f"• {posts} posts nuevos leídos en los feeds{aviso}"
    )
    try:
        TelegramClient().send_message(msg)
        storage.kv_set("heartbeat_week", week)
    except Exception as exc:
        print(f"[aviso] no pude mandar el resumen semanal ({exc})", file=sys.stderr)


def run_command(storage: Storage, command: str, dry_run: bool = False) -> str:
    """Ejecuta un comando del bot directo (--command / workflow_dispatch),
    sin pasar por Telegram. Si puede, repite la respuesta en el chat."""
    command = command.strip()
    if command and not command.startswith("/"):
        command = "/" + command  # acepta 'borrar 3' sin la barra
    reply = handle_message(command, storage) or "(sin respuesta)"
    print(reply)
    if not dry_run:
        try:
            TelegramClient().send_message(f"↩️ <code>{esc(command)}</code>\n{reply}")
        except Exception as exc:
            print(f"[aviso] no pude responder en Telegram ({exc})", file=sys.stderr)
    return reply


def tick(
    dry_run: bool = False,
    source_name: str = "fastflights",
    force_sweep: bool = False,
    skip_bot: bool = False,
    skip_sweep: bool = False,
    command: str | None = None,
    skip_feeds: bool = False,
) -> None:
    load_dotenv()
    storage = Storage()
    storage.seed_routes(load_routes_from_yaml(CONFIG_PATH))

    if command:
        run_command(storage, command, dry_run=dry_run)
        return

    if not skip_bot:
        try:
            n = poll_and_handle(storage)
            if n:
                print(f"[bot] {n} comando(s) procesado(s)")
        except Exception:
            print(f"[error] bot:\n{traceback.format_exc()}", file=sys.stderr)  # nunca frena el barrido

    if not skip_feeds:
        try:
            n = check_feeds(storage, send=_telegram_sender(dry_run))
            if n:
                print(f"[feeds] {n} alerta(s) enviada(s)")
        except Exception:
            print(f"[error] feeds:\n{traceback.format_exc()}", file=sys.stderr)

    if not dry_run:
        _weekly_heartbeat(storage)

    if skip_sweep:
        return
    due = force_sweep or storage.hours_since_last_sweep() >= SWEEP_INTERVAL_H
    if not due:
        print(f"[info] barrido salteado ({storage.hours_since_last_sweep():.1f} h desde el último)")
        return
    run_sweep(storage, dry_run=dry_run, source_name=source_name)
    storage.mark_sweep_done()


def main() -> None:
    p = argparse.ArgumentParser(description="Cazador de tarifas aéreas baratas")
    p.add_argument("--dry-run", action="store_true", help="no manda alertas a Telegram")
    p.add_argument("--source", default=os.environ.get("PRICE_SOURCE", "fastflights"))
    p.add_argument("--sweep-now", action="store_true", help="fuerza el barrido de precios ahora")
    p.add_argument("--no-bot", action="store_true", help="no procesa comandos de Telegram")
    p.add_argument("--bot-only", action="store_true", help="solo procesa comandos, sin barrido")
    p.add_argument("--command", help="ejecuta un comando del bot (ej: '/borrar 3') y sale")
    p.add_argument("--no-feeds", action="store_true", help="no lee los feeds RSS")
    args = p.parse_args()
    tick(
        dry_run=args.dry_run,
        source_name=args.source,
        force_sweep=args.sweep_now,
        skip_bot=args.no_bot,
        skip_sweep=args.bot_only,
        command=args.command,
        skip_feeds=args.no_feeds,
    )


if __name__ == "__main__":
    main()
