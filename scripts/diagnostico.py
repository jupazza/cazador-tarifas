"""Prueba qué feeds de sitios de ofertas se pueden leer desde GitHub."""
import feedparser
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
CANDIDATOS = {
    "2 Turismocity": ["https://www.turismocity.com.ar/promociones_aereas/rss",
                      "https://www.turismocity.com.ar/promociones_aereas/feed",
                      "https://www.turismocity.com.ar/rss"],
    "3 Aerofertas": ["https://www.aerofertas.com/feed/", "https://www.aerofertas.com/rss"],
    "8 Travel-Dealz": ["https://travel-dealz.com/feed/", "https://travel-dealz.com/tag/error-fares/feed/"],
    "9 ErrorFareAlerts": ["https://errorfarealerts.com/feed/", "https://errorfarealerts.com/?feed=rss2"],
    "10 Airfarewatchdog": ["https://www.airfarewatchdog.com/blog/feed/", "https://www.airfarewatchdog.com/rss/",
                           "https://www.airfarewatchdog.com/feed/"],
    "11 Melhores Destinos": ["https://www.melhoresdestinos.com.br/feed", "https://www.melhoresdestinos.com.br/feed/"],
    "12 Passagens Imperdíveis": ["https://passagensimperdiveis.com.br/feed/"],
    "Secret Flying (reintento)": ["https://www.secretflying.com/feed/",
                                  "https://www.secretflying.com/posts/category/error-fare/feed/"],
}

for nombre, urls in CANDIDATOS.items():
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"}, timeout=25)
            d = feedparser.parse(r.content)
            n = len(d.entries)
            ej = " | ".join(e.get("title", "")[:70] for e in d.entries[:2])
            print(f"{'OK ' if n else '-- '} {nombre}: {url} · HTTP {r.status_code} · {n} posts · {ej}")
            if n:
                break
        except Exception as e:
            print(f"ERR {nombre}: {url} · {type(e).__name__}: {e}")
