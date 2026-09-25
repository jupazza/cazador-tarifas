from __future__ import annotations

from datetime import date, timedelta


def sample_dates(start: date, end: date, max_samples: int = 4, rotation: int | None = None) -> list[date]:
    """Fechas dentro de [start, end] para consultar precios.

    Sin `rotation`: fechas equiespaciadas, incluyendo los extremos.
    Con `rotation` (un número que cambia en cada barrido): la grilla se corre
    un poco cada vez, así que con los días el agente termina mirando TODAS las
    fechas de la ventana y no siempre las mismas 3 o 4. Clave para cazar
    tarifas error, que suelen aparecer en fechas puntuales.
    """
    span = (end - start).days
    if span <= 0 or max_samples <= 1:
        return [start]
    if rotation is None:
        step = span / (max_samples - 1)
        picked = {start + timedelta(days=round(i * step)) for i in range(max_samples)}
        return sorted(picked)

    days = span + 1
    step = max(days // max_samples, 1)
    offset = rotation % days
    picked = {
        start + timedelta(days=(offset + i * step) % days)
        for i in range(max_samples)
    }
    return sorted(picked)
