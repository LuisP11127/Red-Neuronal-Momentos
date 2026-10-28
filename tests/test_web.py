import json
from datetime import datetime, timezone

from red_momentos import web


def escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_construir(tmp_path):
    listas = tmp_path / "listas"
    escribir(listas / "momento-a" / "2026-10-20.json", {"fecha": "2026-10-20", "monedas": [
        {"mercado": "futures", "simbolo": "1000PEPEUSDT", "base": "1000PEPE", "estrella": True},
        {"mercado": "spot", "simbolo": "SOLUSDT", "base": "SOL"}]})
    escribir(listas / "momento-b" / "estrellas.json", {"estrellas": {
        "2026-10-20|futures:ARBUSDT": {"activa": True, "hora": "x"},
        "2026-10-19|spot:SOLUSDT": {"activa": False, "hora": "x"}}})
    predicciones = tmp_path / "predicciones"
    escribir(predicciones / "2026-10-20.json", {
        "fecha": "2026-10-20", "vela_utc": "2026-10-21", "hora": "2026-10-22T00:31:00Z", "umbral": 0.4,
        "monedas": [{"moneda": "PEPE", "mercado": "futures", "simbolo": "1000PEPEUSDT", "listas": ["momento-a"],
                     "puntuacion": 0.5, "mostrar": True, "precio": 0.01, "senales": {"x": 1}}]})
    escribir(predicciones / "2026-10-19.json", {"fecha": "2026-10-19", "monedas": []})
    resultados_csv = tmp_path / "resultados.csv"
    resultados_csv.write_text("fecha,moneda,mercado,simbolo,mostrada,hora,precio,maximo,pct_maximo,minimo,pct_minimo,"
                              "dias_hasta_50,dias_vistos,estado\n"
                              "2026-10-20,PEPE,futures,1000PEPEUSDT,1,2026-10-22T00:31:00Z,0.01,0.01125,12.5,0.0095,-5,,3,pendiente\n"
                              "2026-10-20,SOL,spot,SOLUSDT,0,2026-10-22T00:31:00Z,100,103,3,,,,10,no_llego\n", encoding="utf-8")
    destino = tmp_path / "sitio"
    datos = web.construir(destino, predicciones, resultados_csv, tmp_path / "no-hay-modelo.json", listas,
                          ahora=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert [d["fecha"] for d in datos["dias"]] == ["2026-10-20", "2026-10-19"]  # la más reciente primero
    assert "senales" not in datos["dias"][0]["monedas"][0]
    assert datos["estrellas"] == ["2026-10-20|ARB", "2026-10-20|PEPE"]
    assert set(datos["resultados"]) == {"2026-10-20|PEPE"}  # solo las monedas predichas
    assert datos["resultados"]["2026-10-20|PEPE"] == {"estado": "pendiente", "referencia": "0.01", "pct_maximo": "12.5",
                                                     "pct_minimo": "-5", "dias_hasta_50": "", "dias_vistos": "3"}
    assert datos["modelo"] is None
    assert json.loads((destino / "datos.json").read_text(encoding="utf-8")) == datos
    assert "<title>Red-Neuronal-Momentos</title>" in (destino / "index.html").read_text(encoding="utf-8")
