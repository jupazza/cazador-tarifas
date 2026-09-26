# Cazador de tarifas

Agente personal que busca pasajes desde Buenos Aires mucho más baratos de lo
normal (incluidas tarifas error) y avisa por **Telegram**. Corre gratis en
**GitHub Actions**, aunque la computadora esté apagada.

Basado en [pedrivas/flight-price-monitor](https://github.com/pedrivas/flight-price-monitor)
(licencia MIT), adaptado a Buenos Aires, dólares y castellano, con lectura de
feeds de ofertas agregada.

## Cómo funciona

Cada 15 minutos GitHub corre el agente, que hace tres cosas:

1. **Comandos de Telegram:** lee lo que le escribiste al bot (`/rutas`, `/crear`, etc.).
2. **Feeds de ofertas:** lee Promociones Aéreas, Secret Flying y Fly4free.
   Avisa si un post sale de Buenos Aires y dice "tarifa error" o si el precio
   está por debajo del tope de ese destino (`config/feeds.yaml`).
3. **Precios propios (rotación):** en cada corrida consulta Google Flights para
   las 5 rutas que hace más tiempo que no se miran (cada ruta, aprox. cada hora),
   en 2 fechas que van rotando dentro de la ventana. Avisa si el precio:
   - es igual o menor al **tope** de la ruta, o
   - está un **X% por debajo** de la mediana de los últimos 30 días.

   Si la baja supera el 55%, la alerta llega marcada como **🚨 POSIBLE TARIFA ERROR**.

Todo el historial se guarda en `data/history.db` dentro del repo.

## Comandos del bot

| Comando | Qué hace |
|---|---|
| `/rutas` | Lista las rutas vigiladas con el último precio visto |
| `/crear EZE JFK 2026-11-01..2027-03-31 7-14 450 40` | Nueva ruta: origen, destino, ventana de ida, noches, tope USD, baja % |
| `/crear EZE MIA 2026-12-01..2027-02-28 - 250` | Solo ida (`-` en noches) |
| `/editar 3 tope 400` | Cambia un campo: `nombre tope baja pax directo ida_desde ida_hasta noches` |
| `/pausar 3` · `/activar 3` | Pausa o reactiva una ruta |
| `/borrar 3` | Borra (pide confirmar con `/borrar 3 si`) |
| `/ayuda` | Muestra la ayuda |

Los comandos se procesan en la corrida siguiente (hasta 1 hora). Para algo
inmediato: pestaña **Actions → cazador-tarifas → Run workflow**.

## Puesta en marcha

1. Crear el bot con **@BotFather** en Telegram y mandarle "hola".
2. En el repo: **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = el token que dio BotFather
3. **Actions → obtener-chat-id → Run workflow**. En el log aparece `chat_id=...`.
4. Agregar el secret `TELEGRAM_CHAT_ID` con ese número.
5. **Actions → cazador-tarifas → Run workflow** con "forzar barrido" tildado para la primera prueba.

## Ajustes opcionales

En **Settings → Secrets and variables → Actions → Variables**:

| Variable | Default | Qué cambia |
|---|---|---|
| `RUTAS_POR_CORRIDA` | 5 | Rutas consultadas en Google Flights en cada corrida |
| `FECHAS_POR_RUTA` | 2 | Fechas probadas por ruta en cada consulta |

El repo es público, así que los minutos de GitHub Actions son ilimitados.

## Límites

- `fast-flights` no es una API oficial: si Google cambia su web o bloquea las
  consultas, deja de traer precios. El resumen semanal de los lunes avisa si
  no registró precios.
- Las aerolíneas pueden cancelar tarifas error. No reservar nada no
  reembolsable hasta que el pasaje esté emitido.

## Correr en tu PC (opcional)

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # completar los datos de Telegram
export PYTHONPATH=src
python -m pytest -q                                   # tests
python -m monitor.main --dry-run --sweep-now          # prueba real sin mandar nada
```
