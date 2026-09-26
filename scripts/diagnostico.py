"""Prueba qué páginas de promociones de aerolíneas se pueden leer desde GitHub."""
import re

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
PAGINAS = {
    "Aerolíneas (descuentos)": "https://www.aerolineas.com.ar/viaja-con-descuento",
    "Aerolíneas (hot sale)": "https://www.aerolineas.com.ar/hotsale",
    "LATAM": "https://www.latamairlines.com/ar/es/ofertas/ofertas-latam",
    "Iberia": "https://www.iberia.com/ar/ofertas/vuelos/viajar/",
    "Air Europa": "https://www.aireuropa.com/ar/es/vuelos/ofertas",
    "Copa": "https://www.copaair.com/es-ar/ofertas/",
    "JetSMART": "https://jetsmart.com/ar/es/ofertas",
    "Flybondi": "https://flybondi.com/ar/ofertas",
    "GOL": "https://www.voegol.com.br/es-ar/ofertas",
    "American": "https://www.aa.com/i18n/travel-info/special-offers/special-offers.jsp",
    "Turkish": "https://www.turkishairlines.com/es-ar/flights/special-offers/",
    "Emirates": "https://www.emirates.com/ar/spanish/special-offers/",
    "Air France": "https://wwws.airfrance.com.ar/es/ofertas",
    "Ethiopian": "https://www.ethiopianairlines.com/ar/offers",
}
PRECIO = re.compile(r"(?:USD|U\$[SD]|US\$|ARS|\$)\s?[\d.,]{2,}", re.I)

for nombre, url in PAGINAS.items():
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"}, timeout=25)
        html = r.text
        texto = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        texto = re.sub(r"<[^>]+>", "\n", texto)
        lineas = [l.strip() for l in texto.split("\n") if len(l.strip()) > 3]
        precios = [l for l in lineas if PRECIO.search(l)]
        titulo = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        print(f"{nombre}: HTTP {r.status_code} · {len(html)} bytes · {len(lineas)} líneas de texto · "
              f"{len(precios)} con precio · título={titulo.group(1).strip()[:60] if titulo else '-'}")
        for l in precios[:3]:
            print(f"      ej: {l[:100]}")
    except Exception as e:
        print(f"{nombre}: ERROR {type(e).__name__}: {e}")
