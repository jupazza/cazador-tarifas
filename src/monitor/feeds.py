"""Lector de feeds RSS de sitios que publican ofertas y tarifas error.

Complementa el barrido de precios: muchas tarifas error las detecta primero
gente que se dedica a eso (Promociones Aéreas, Secret Flying, Fly4free).
Este módulo lee sus feeds en cada corrida, filtra lo que sale de Buenos Aires
y sea realmente barato o diga "error", y avisa por Telegram.

La configuración está en config/feeds.yaml.
"""
from __future__ import annotations

import re
import sys
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import feedparser
import yaml

from .notifier import esc
from .storage import Storage

FEEDS_PATH = Path(__file__).resolve().parents[2] / "config" / "feeds.yaml"

# "U$D 913", "USD 1.040", "US$ 389", "$389 USD", "for only $389"
_PRICE_RE = re.compile(
    r"(?:u\$[sd]|usd|us\$|\$)\s*([0-9]{1,3}(?:[.,][0-9]{3})+|[0-9]{2,5})",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar palabras clave."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def contains(word: str, text: str) -> bool:
    """¿Aparece `word` como palabra completa en `text` (ya normalizado)?"""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalize(word)) + r"(?![a-z0-9])", text) is not None


def parse_usd_price(text: str) -> float | None:
    """Primer precio en dólares que aparezca en el texto, o None."""
    m = _PRICE_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass
class FeedItem:
    feed: str
    item_id: str
    title: str
    link: str
    summary: str = ""

    @property
    def text(self) -> str:
        return f"{self.title} {self.summary}"


@dataclass
class Verdict:
    alert: bool
    reason: str = ""
    is_error: bool = False


def classify(item: FeedItem, feed_cfg: dict, cfg: dict) -> Verdict:
    """Decide si un post del feed merece alerta."""
    text = normalize(item.text)
    title = normalize(item.title)

    if any(contains(w, title) for w in cfg.get("excluir", [])):
        return Verdict(False, "excluido")

    if not feed_cfg.get("todo_sale_de_buenos_aires", False):
        if not any(contains(w, text) for w in cfg.get("origen", [])):
            return Verdict(False, "no sale de Buenos Aires")

    if any(contains(w, text) for w in cfg.get("palabras_error", [])):
        return Verdict(True, "el post habla de tarifa error", is_error=True)

    if feed_cfg.get("avisar_todo_desde_buenos_aires", False):
        return Verdict(True, "oferta desde Buenos Aires")

    price = parse_usd_price(item.title) or parse_usd_price(item.summary)
    if price is None:
        return Verdict(False, "sin precio")

    for group in cfg.get("topes_por_destino", []):
        if any(contains(w, title) for w in group["destinos"]):
            cap = float(group["tope_usd"])
            if price <= cap:
                return Verdict(True, f"USD {price:.0f} ≤ tope {cap:.0f} ({group['nombre']})")
            return Verdict(False, f"USD {price:.0f} > tope {cap:.0f}")
    return Verdict(False, "destino no vigilado")


def load_config(path: Path = FEEDS_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fetch_items(feed_cfg: dict) -> list[FeedItem]:
    parsed = feedparser.parse(
        feed_cfg["url"],
        agent="Mozilla/5.0 (cazador-tarifas; uso personal)",
    )
    items = []
    for e in parsed.entries:
        item_id = e.get("id") or e.get("link") or e.get("title")
        if not item_id:
            continue
        items.append(
            FeedItem(
                feed=feed_cfg["nombre"],
                item_id=str(item_id),
                title=e.get("title", ""),
                link=e.get("link", ""),
                summary=re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:600],
            )
        )
    if not items and getattr(parsed, "bozo", False):
        print(f"[aviso] feed {feed_cfg['nombre']}: {parsed.get('bozo_exception')}", file=sys.stderr)
    return items


def format_feed_alert(item: FeedItem, verdict: Verdict) -> str:
    header = "🚨 <b>POSIBLE TARIFA ERROR</b>" if verdict.is_error else "📣 <b>Oferta publicada</b>"
    return (
        f"{header} · <i>{esc(item.feed)}</i>\n\n"
        f"{esc(item.title)}\n"
        f"<i>({esc(verdict.reason)})</i>\n\n"
        f"🔗 {esc(item.link)}"
    )


def check_feeds(storage: Storage, send, cfg: dict | None = None, fetch=fetch_items) -> int:
    """Lee todos los feeds y manda alertas nuevas. Devuelve cuántas mandó.

    La primera vez que ve un feed marca todo como leído sin avisar, para no
    inundarte con posts viejos.
    """
    cfg = cfg or load_config()
    sent = 0
    for feed_cfg in cfg.get("feeds", []):
        name = feed_cfg["nombre"]
        try:
            items = fetch(feed_cfg)
        except Exception:
            print(f"[error] feed {name}:\n{traceback.format_exc()}", file=sys.stderr)
            continue
        first_time = not storage.feed_has_history(name)
        new = [i for i in items if not storage.feed_seen(name, i.item_id)]
        for item in new:
            verdict = classify(item, feed_cfg, cfg)
            alerted = False
            if verdict.alert and not first_time:
                try:
                    send(format_feed_alert(item, verdict))
                    alerted = True
                    sent += 1
                except Exception as exc:
                    print(f"[aviso] no pude avisar '{item.title}': {exc}", file=sys.stderr)
                    continue  # no lo marco: se reintenta en la próxima corrida
            storage.mark_feed_item(name, item.item_id, alerted)
        estado = " (primera lectura: marcado como leído)" if first_time else ""
        print(f"[feeds] {name}: {len(items)} posts, {len(new)} nuevos{estado}")
    return sent
