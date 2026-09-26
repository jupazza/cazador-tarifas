"""Prueba qué feeds de sitios de ofertas se pueden leer desde GitHub."""
import feedparser
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
CANDIDATOS = {
    "12 Passagens Imperdíveis": ["https://passagensimperdiveis.com.br/feed", "https://passagensimperdiveis.com.br/?feed=rss2",
                                 "https://passagensimperdiveis.com.br/rss", "https://www.passagensimperdiveis.com.br/feed/"],
    "9 ErrorFareAlerts": ["https://errorfarealerts.com/en/feed/", "https://errorfarealerts.com/feed/atom/",
                          "https://errorfarealerts.com/?lang=en&feed=rss2"],
    "10 Airfarewatchdog": ["https://www.airfarewatchdog.com/blog/rss/", "https://blog.airfarewatchdog.com/feed/",
                           "https://www.airfarewatchdog.com/blog/feed/?format=rss"],
    "2 Turismocity (móvil)": ["https://m.turismocity.com.ar/promociones_aereas/rss"],
    "Secret Flying (Argentina)": ["https://www.secretflying.com/posts/category/argentina/feed/",
                                  "https://www.secretflying.com/feed/?paged=1"],
    "Travel-Dealz (errores)": ["https://travel-dealz.com/tag/error-fares/feed/"],
    "Melhores Destinos (erro)": ["https://www.melhoresdestinos.com.br/tag/erro-tarifario/feed"],
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
