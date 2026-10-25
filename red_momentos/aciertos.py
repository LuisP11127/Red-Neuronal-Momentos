"""Resultado de cada lista de la red, medido desde la hora en que de verdad se calculó.

GitHub lanza el workflow Diario con retraso (a veces más de cuatro horas después de las 19:30), así que la
lista de cada día sale cuando sale. Para no contar como acierto una subida que pasó antes de que la red diera
su lista, el seguimiento de la red se mide desde la hora y el precio que guardó cada predicción
(``predicciones/AAAA-MM-DD.json``), no desde las 19:30:

el máximo de los 10 días siguientes a la hora de la predicción llega a +50 % sobre su precio.

Se mide con velas de 15 minutos, desde la primera que abre después de esa hora. Se calcula para todas las
candidatas de cada predicción (no solo las que mostró la red), para comparar con la misma regla. Las
etiquetas con las que se entrena la red siguen siendo las de ``datos/etiquetas.csv`` (19:30), porque ahí las
señales también son de las 19:30.

    python -m red_momentos.aciertos
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import etiquetas
from .binance import DURACION, Binance, Vela

CARPETA = Path("predicciones")
SALIDA = CARPETA / "resultados.csv"
INTERVALO = "15m"
PASO = DURACION[INTERVALO]
DIA_MS = DURACION["1d"]
VENTANA = etiquetas.VENTANA
COLUMNAS = ["fecha", "moneda", "mercado", "simbolo", "mostrada", "hora", "precio", "maximo", "pct_maximo", "minimo",
            "pct_minimo", "dias_hasta_50", "dias_vistos", "estado"]


def hora_ms(texto: str) -> int:
    return int(datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp() * 1000)


def evaluar(precio: float, desde: int, velas: dict[int, Vela], cubierto: int) -> etiquetas.Resultado:
    """La regla desde el instante ``desde`` (milisegundos) con el precio de ese momento.

    ``velas``: las de 15 minutos del par, por apertura; ``cubierto``: hasta dónde llegan los datos.
    """
    inicio = -(-desde // PASO) * PASO  # la primera vela que abre en ese instante o después
    fin = desde + VENTANA * DIA_MS
    ultima = (fin - 1) // PASO * PASO  # la última vela que abre antes de que terminen los 10 días
    r = etiquetas.Resultado(referencia=precio)
    meta = precio * (1 + etiquetas.OBJETIVO / 100)
    for apertura in range(inicio, min(ultima, cubierto) + 1, PASO):
        vela = velas.get(apertura)
        if vela is None:
            continue
        r.maximo = vela.high if r.maximo is None else max(r.maximo, vela.high)
        r.minimo = vela.low if r.minimo is None else min(r.minimo, vela.low)
        if r.dias_hasta_50 is None and vela.high >= meta:
            r.dias_hasta_50 = (apertura - desde) // DIA_MS + 1
    r.dias_vistos = min(VENTANA, max(0, (min(cubierto + PASO, fin) - desde) // DIA_MS))
    if r.dias_hasta_50 is not None:
        r.estado = "llego"
    elif ultima <= cubierto:
        r.estado = "no_llego"
    return r


def leer_predicciones(carpeta: Path = CARPETA) -> list[dict]:
    """Las candidatas de todas las predicciones, con la hora y el precio de su lista."""
    filas = []
    for ruta in sorted(carpeta.glob("????-??-??.json")):
        p = json.loads(ruta.read_text(encoding="utf-8"))
        for m in p.get("monedas", []):
            if m.get("precio"):
                filas.append({"fecha": p["fecha"], "moneda": m["moneda"], "mercado": m["mercado"], "simbolo": m["simbolo"],
                              "mostrada": "1" if m.get("mostrar") else "0", "hora": p["hora"], "precio": m["precio"]})
    return filas


def leer_csv(ruta: Path) -> dict[tuple[str, str], dict]:
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8", newline="") as fh:
        return {(f["fecha"], f["moneda"]): f for f in csv.DictReader(fh)}


def calcular(candidatas: list[dict], binance: Binance, anteriores: dict[tuple[str, str], dict], ahora: int,
             hilos: int = 8) -> list[dict]:
    """Filas de ``resultados.csv``. Las que ya terminaron (con un día de margen) no se vuelven a calcular."""
    filas: dict[tuple[str, str], dict] = {}
    por_par: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in candidatas:
        clave = (c["fecha"], c["moneda"])
        desde = hora_ms(c["hora"])
        previa = anteriores.get(clave)
        if (previa and previa.get("estado") in etiquetas.FINALES and previa.get("hora") == c["hora"]
                and desde + (VENTANA + 1) * DIA_MS <= ahora):
            filas[clave] = {**previa, "mostrada": c["mostrada"]}
        else:
            por_par[(c["mercado"], c["simbolo"])].append(c)

    def descargar(par: tuple[str, str]) -> tuple[tuple[str, str], dict[int, Vela], int]:
        desdes = [hora_ms(c["hora"]) for c in por_par[par]]
        inicio = -(-min(desdes) // PASO) * PASO
        hasta = min(max(desdes) + VENTANA * DIA_MS - 1, ahora) // PASO * PASO
        if hasta < inicio:
            return par, {}, inicio - 1
        velas, cubierto = binance.velas(par[0], par[1], INTERVALO, inicio, hasta)
        return par, {v.apertura: v for v in velas}, cubierto

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for par, velas, cubierto in pool.map(descargar, sorted(por_par)):
            for c in por_par[par]:
                r = evaluar(float(c["precio"]), hora_ms(c["hora"]), velas, cubierto)
                filas[(c["fecha"], c["moneda"])] = {
                    **{k: str(c[k]) for k in ("fecha", "moneda", "mercado", "simbolo", "mostrada", "hora")},
                    "precio": etiquetas._num(r.referencia), "maximo": etiquetas._num(r.maximo),
                    "pct_maximo": etiquetas._num(r.pct(r.maximo), 2), "minimo": etiquetas._num(r.minimo),
                    "pct_minimo": etiquetas._num(r.pct(r.minimo), 2),
                    "dias_hasta_50": "" if r.dias_hasta_50 is None else str(r.dias_hasta_50),
                    "dias_vistos": str(r.dias_vistos), "estado": r.estado,
                }
    return [filas[k] for k in sorted(filas)]


def escribir_csv(ruta: Path, filas: Iterable[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)


def resumen(filas: list[dict]) -> str:
    finales = [f for f in filas if f["estado"] in etiquetas.FINALES]
    mostradas = [f for f in finales if f["mostrada"] == "1"]
    texto = (f"Candidatas con resultado: {len(finales)}; llegaron a +50 %: "
             f"{sum(f['estado'] == 'llego' for f in finales)}. Mostradas por la red con resultado: {len(mostradas)}; "
             f"llegaron: {sum(f['estado'] == 'llego' for f in mostradas)}.")
    return texto


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Resultado de cada predicción desde la hora en que se calculó.")
    parser.add_argument("--carpeta", type=Path, default=CARPETA)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--hilos", type=int, default=8)
    args = parser.parse_args(argv)

    candidatas = leer_predicciones(args.carpeta)
    if not candidatas:
        print("Todavía no hay predicciones.")
        return 0
    binance = Binance()
    filas = calcular(candidatas, binance, leer_csv(args.salida), int(time.time() * 1000), args.hilos)
    escribir_csv(args.salida, filas)
    print(resumen(filas))
    for aviso in binance.avisos:
        print(f"Aviso: {aviso}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
