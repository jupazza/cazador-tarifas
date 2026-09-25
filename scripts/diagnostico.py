"""Prueba variantes de búsqueda en Google Flights para encontrar qué falla."""
from fast_flights import FlightQuery, Passengers, create_query, get_flights


def probar(nombre, legs, trip, pax):
    q = create_query(flights=[FlightQuery(date=d, from_airport=a, to_airport=b) for a, b, d in legs],
                     trip=trip, seat="economy", passengers=pax, currency="USD", language="es")
    try:
        res = get_flights(q)
        precios = sorted(f.price for f in res if f.price)
        print(f"OK   {nombre}: {len(res)} resultados, más barato {precios[:1]}")
    except Exception as e:
        print(f"FALLA {nombre}: {type(e).__name__}: {e}")


ny = [("EZE", "JFK", "2027-07-14"), ("JFK", "EZE", "2027-08-06")]
probar("NY jul27 ida+vuelta 1 adulto", ny, "round-trip", Passengers(adults=1))
probar("NY jul27 ida+vuelta 2 adultos", ny, "round-trip", Passengers(adults=2))
probar("NY jul27 ida+vuelta 2a+2 chicos", ny, "round-trip", Passengers(adults=2, children=2))
probar("NY jul27 ida+vuelta 4 adultos", ny, "round-trip", Passengers(adults=4))
probar("NY ene27 ida+vuelta 1 adulto", [("EZE", "JFK", "2027-01-14"), ("JFK", "EZE", "2027-01-24")], "round-trip", Passengers(adults=1))
probar("NY jul27 solo ida 1 adulto", ny[:1], "one-way", Passengers(adults=1))
oj = [("EZE", "JFK", "2027-07-14"), ("MIA", "EZE", "2027-08-06")]
probar("Multidestino jul27 1 adulto", oj, "multi-city", Passengers(adults=1))
probar("Multidestino jul27 4 adultos", oj, "multi-city", Passengers(adults=4))
probar("Multidestino ene27 1 adulto", [("EZE", "JFK", "2027-01-14"), ("MIA", "EZE", "2027-01-28")], "multi-city", Passengers(adults=1))
probar("Tokio dic26 1 adulto", [("EZE", "NRT", "2026-12-12"), ("NRT", "EZE", "2027-01-06")], "round-trip", Passengers(adults=1))
probar("Tokio dic26 4 adultos", [("EZE", "NRT", "2026-12-12"), ("NRT", "EZE", "2027-01-06")], "round-trip", Passengers(adults=4))
