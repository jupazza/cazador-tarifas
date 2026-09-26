from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
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
from .scoring import score_offer
from .sources import get_source
from .storage import Storage
from .telegram import TelegramClient

# Rotación: en cada corrida (cada ~15 min) se consultan en Google Flights solo
# las rutas que hace más tiempo que no se miran, así cada ruta se revisa
# aproximadamente cada hora sin disparar muchas consultas juntas.
RUTAS_POR_CORRIDA = int(os.environ.get("RUTAS_POR_CORRIDA", "4"))
MINUTOS_ENTRE_CONSULTAS = float(os.environ.get("MINUTOS_ENTRE_CONSULTAS", "30"))


def pick_routes(storage: Storage, limit: int = RUTAS_POR_CORRIDA,
                min_minutes: float = MINUTOS_ENTRE_CONSULTAS) -> list:
    """Rutas activas con la consulta más vieja primero (nunca consultadas antes)."""
    candidates = []
    for r in storage.list_routes(active_only=True):
        mins = storage.minutes_since_checked(r.key)
        if mins >= min_minutes:
            candidates.append((mins, r))
    candidates.sort(key=lambda t: -t[0])
    return [r for _, r in candidates[:limit]]


def run_sweep(storage: Storage, dry_run: bool = False, source_name: str = "fastflights",
              routes: list | None = None) -> int:
    source = get_source(source_name)
    notifier = None  # se crea solo si hay algo que avisar
    delivery_broken = False  # si falla un envío, el resto solo se imprime

    if routes is None:
        routes = storage.list_routes(active_only=True)
    alerts = 0
    for route in routes:
        storage.mark_checked(route.key)
        # búsqueda + base de datos: si falla una ruta, siguen las demás
        try:
            offers = source.search(route)
            if not offers:
                print(f"[info] {route.name}: sin ofertas")
                continue
            cheapest = min(offers, key=lambda o: o.price)
            decision = evaluate(route, cheapest, storage)  # antes de grabar: la referencia no incluye este precio
            score = score_offer(route, cheapest, storage)
            storage.record(cheapest)
        except Exception:
            print(f"[error] {route.name}:\n{traceback.format_exc()}", file=sys.stderr)
            continue

        base = f"{decision.baseline:.0f}" if decision.baseline is not None else "sin historial"
        print(f"[info] {route.name}: más barato {cheapest.currency} {cheapest.price:.0f} (mediana 30 días: {base})")

        if decision.should_alert:
            try:
                verificado = source.verify(route, cheapest)
            except Exception:
                verificado = None
            msg = format_alert(route, cheapest, decision, score=score, verificado=verificado)
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


# --- modo continuo -----------------------------------------------------------
# GitHub dispara los cron muy de vez en cuando (a veces 5 veces por día), así que
# el bot corre en una sola ejecución larga que escucha Telegram en vivo, lee los
# feeds y va rotando rutas; al terminar, el workflow lo vuelve a lanzar.
FEEDS_CADA_MIN = float(os.environ.get("FEEDS_CADA_MIN", "5"))
BARRIDO_CADA_MIN = float(os.environ.get("BARRIDO_CADA_MIN", "10"))
GUARDAR_CADA_MIN = float(os.environ.get("GUARDAR_CADA_MIN", "30"))


def save_db() -> None:
    """Guarda data/history.db en el repo (solo dentro de GitHub Actions)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    cmds = [
        "git add -f data/history.db",
        "git -c user.name=cazador-bot -c user.email=cazador-bot@users.noreply.github.com "
        "commit -m 'chore: actualiza historial [skip ci]' || true",
        "git pull --rebase --autostash -q || true",
        "git push -q || true",
    ]
    for c in cmds:
        subprocess.run(c, shell=True, check=False)
    print("[guardar] historial guardado en el repo")


def run_loop(minutes: float, dry_run: bool = False, source_name: str = "fastflights",
             sleep=time.sleep, clock=time.time) -> None:
    load_dotenv()
    storage = Storage()
    storage.seed_routes(load_routes_from_yaml(CONFIG_PATH))
    end = clock() + minutes * 60
    last_feeds = last_sweep = last_save = -1e18
    print(f"[loop] modo continuo por {minutes:.0f} min")
    while clock() < end:
        # 1) Telegram: espera hasta 20 s por mensajes nuevos (respuesta casi instantánea)
        try:
            if os.environ.get("TELEGRAM_CHAT_ID") and not dry_run:
                n = poll_and_handle(storage, wait=20)
                if n:
                    print(f"[bot] {n} comando(s) procesado(s)")
            else:
                sleep(20)
        except Exception:
            print(f"[error] bot:\n{traceback.format_exc()}", file=sys.stderr)
            sleep(20)
        now = clock()
        # 2) feeds de ofertas
        if now - last_feeds >= FEEDS_CADA_MIN * 60:
            last_feeds = now
            try:
                n = check_feeds(storage, send=_telegram_sender(dry_run))
                if n:
                    print(f"[feeds] {n} alerta(s) enviada(s)")
            except Exception:
                print(f"[error] feeds:\n{traceback.format_exc()}", file=sys.stderr)
            if not dry_run:
                _weekly_heartbeat(storage)
        # 3) rotación de rutas en Google Flights
        if now - last_sweep >= BARRIDO_CADA_MIN * 60:
            last_sweep = now
            routes = pick_routes(storage)
            if routes:
                print(f"[info] consultando {len(routes)} ruta(s): {', '.join('#' + str(r.id) for r in routes)}")
                try:
                    run_sweep(storage, dry_run=dry_run, source_name=source_name, routes=routes)
                    storage.mark_sweep_done()
                except Exception:
                    print(f"[error] barrido:\n{traceback.format_exc()}", file=sys.stderr)
        # 4) guardar historial
        if now - last_save >= GUARDAR_CADA_MIN * 60:
            last_save = now
            save_db()
    save_db()
    print("[loop] fin del turno; el workflow lo relanza")


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
    routes = storage.list_routes(active_only=True) if force_sweep else pick_routes(storage)
    if not routes:
        print("[info] ninguna ruta toca consultar en esta corrida")
        return
    print(f"[info] consultando {len(routes)} ruta(s): {', '.join('#' + str(r.id) for r in routes)}")
    run_sweep(storage, dry_run=dry_run, source_name=source_name, routes=routes)
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
    p.add_argument("--loop", type=float, metavar="MIN", help="modo continuo durante MIN minutos")
    args = p.parse_args()
    if args.loop:
        run_loop(args.loop, dry_run=args.dry_run, source_name=args.source)
        return
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
