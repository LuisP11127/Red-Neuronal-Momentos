"""Etiqueta de cada candidata: ¿llegó a +50 % en los 10 días siguientes?

Regla: el máximo de las 10 velas diarias siguientes llega a +50 % sobre el precio de referencia.

El precio de referencia es el **cierre de la vela del día de la lista** (00:00 UTC del día siguiente,
19:00 en Lima), el momento en que la red da su lista. La red ve la vela completa, así que la subida se
cuenta desde su cierre: desde el precio del escaneo contaría como acierto una subida que ya había pasado
cuando la red decide.

Cada candidata es una moneda de Momento-A o Momento-B en un día («No repetidas»; futuros si salió en
futuros). Las columnas ``explosion_mismo_dia`` y ``explosiones_despues`` dicen si la moneda salió en
Scanner-pump ese día o en los 10 siguientes, para comparar.

    python -m red_momentos.etiquetas [--salida datos/etiquetas.csv] [--resumen RESUMEN.md]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

from . import listas
from .binance import Binance, Vela
from .fechas import ultima_vela_cerrada, vela_utc

VENTANA = 10  # días
OBJETIVO = 50.0  # %
SALIDA = Path("datos/etiquetas.csv")

COLUMNAS = ["fecha", "moneda", "mercado", "simbolo", "listas", "vela_utc", "cierre", "maximo", "pct_maximo",
            "minimo", "pct_minimo", "dias_hasta_50", "velas", "estado", "explosion_mismo_dia",
            "explosiones_despues"]
# llego: tocó +50 % · no_llego: pasaron los 10 días sin tocarlo · pendiente: aún no pasaron los 10 días
# (o la vela del día no ha cerrado) · sin_datos: Binance no tiene la vela del día de la lista.
FINALES = ("llego", "no_llego")


@dataclass
class Resultado:
    cierre: Optional[float] = None
    maximo: Optional[float] = None
    minimo: Optional[float] = None
    dias_hasta_50: Optional[int] = None
    velas: int = 0
    estado: str = "pendiente"

    def pct(self, precio: Optional[float]) -> Optional[float]:
        return None if precio is None or not self.cierre else (precio / self.cierre - 1) * 100


def etiquetar(fecha: date, velas: dict[date, Vela], cubierto_hasta: date) -> Resultado:
    """Aplica la regla a la candidata de un día con las velas diarias de su par."""
    inicio = vela_utc(fecha)
    referencia = velas.get(inicio)
    if referencia is None:
        return Resultado(estado="pendiente" if inicio > cubierto_hasta else "sin_datos")

    r = Resultado(cierre=referencia.close)
    meta = referencia.close * (1 + OBJETIVO / 100)
    for k in range(1, VENTANA + 1):
        dia = inicio + timedelta(days=k)
        if dia > cubierto_hasta:
            break
        vela = velas.get(dia)
        if vela is None:  # el par dejó de cotizar
            continue
        r.velas += 1
        r.maximo = vela.high if r.maximo is None else max(r.maximo, vela.high)
        r.minimo = vela.low if r.minimo is None else min(r.minimo, vela.low)
        if r.dias_hasta_50 is None and vela.high >= meta:
            r.dias_hasta_50 = k
    if r.dias_hasta_50 is not None:
        r.estado = "llego"
    elif inicio + timedelta(days=VENTANA) <= cubierto_hasta:
        r.estado = "no_llego"
    return r


def _num(valor: Optional[float], decimales: Optional[int] = None) -> str:
    if valor is None:
        return ""
    return f"{valor:.{decimales}f}" if decimales is not None else f"{valor:.10g}"


def leer_csv(ruta: Path) -> dict[tuple[str, str], dict]:
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8", newline="") as fh:
        return {(fila["fecha"], fila["moneda"]): fila for fila in csv.DictReader(fh)}


def calcular(candidatas: list[listas.Candidata], explosiones: dict[str, set[date]], binance: Binance,
             anteriores: dict[tuple[str, str], dict], hoy: date, hilos: int = 8) -> list[dict]:
    """Filas del CSV. Las etiquetas ya cerradas de ``anteriores`` se reutilizan sin pedir velas."""
    filas: dict[tuple[str, str], dict] = {}
    por_par: dict[tuple[str, str], list[listas.Candidata]] = defaultdict(list)
    for c in candidatas:
        previa = anteriores.get((c.fecha.isoformat(), c.moneda))
        # Con un día de margen: con data.binance.vision la última vela tarda unas horas en publicarse.
        cerrada = vela_utc(c.fecha) + timedelta(days=VENTANA) < hoy
        if (previa and cerrada and previa["estado"] in FINALES
                and (previa["mercado"], previa["simbolo"]) == (c.mercado, c.simbolo)):
            filas[(c.fecha.isoformat(), c.moneda)] = {k: previa.get(k, "") for k in COLUMNAS}
        elif vela_utc(c.fecha) <= hoy:
            por_par[(c.mercado, c.simbolo)].append(c)
        else:
            filas[(c.fecha.isoformat(), c.moneda)] = _fila(c, Resultado())  # la vela del día sigue abierta

    def descargar(par: tuple[str, str]) -> tuple[tuple[str, str], dict[date, Vela], date]:
        mercado, simbolo = par
        dias = [vela_utc(c.fecha) for c in por_par[par]]
        velas, cubierto = binance.velas_diarias(mercado, simbolo, min(dias),
                                                min(max(dias) + timedelta(days=VENTANA), hoy))
        return par, {v.dia: v for v in velas}, cubierto

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for par, velas, cubierto in pool.map(descargar, sorted(por_par)):
            for c in por_par[par]:
                filas[(c.fecha.isoformat(), c.moneda)] = _fila(c, etiquetar(c.fecha, velas, cubierto))

    # Las listas y la comparación con Scanner-pump se rehacen siempre (las listas pueden cambiar).
    for c in candidatas:
        fila = filas[(c.fecha.isoformat(), c.moneda)]
        fila["listas"] = " ".join(c.listas)
        dias = explosiones.get(c.moneda, set())
        fila["explosion_mismo_dia"] = "1" if c.fecha in dias else "0"
        fila["explosiones_despues"] = " ".join(
            d.isoformat() for d in sorted(dias) if c.fecha < d <= c.fecha + timedelta(days=VENTANA))
    return [filas[k] for k in sorted(filas)]


def _fila(c: listas.Candidata, r: Resultado) -> dict:
    return {
        "fecha": c.fecha.isoformat(), "moneda": c.moneda, "mercado": c.mercado, "simbolo": c.simbolo,
        "listas": " ".join(c.listas), "vela_utc": vela_utc(c.fecha).isoformat(),
        "cierre": _num(r.cierre), "maximo": _num(r.maximo), "pct_maximo": _num(r.pct(r.maximo), 2),
        "minimo": _num(r.minimo), "pct_minimo": _num(r.pct(r.minimo), 2),
        "dias_hasta_50": "" if r.dias_hasta_50 is None else str(r.dias_hasta_50),
        "velas": str(r.velas), "estado": r.estado, "explosion_mismo_dia": "0", "explosiones_despues": "",
    }


def escribir_csv(ruta: Path, filas: Iterable[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)


def resumen(filas: list[dict]) -> str:
    """Tabla en Markdown: cuántas candidatas llegaron a +50 %, por lista."""
    grupos = {
        "Todas": filas,
        "Solo Momento-A": [f for f in filas if f["listas"] == "momento-a"],
        "Solo Momento-B": [f for f in filas if f["listas"] == "momento-b"],
        "En las dos": [f for f in filas if f["listas"] == "momento-a momento-b"],
    }
    lineas = [f"Regla: el máximo de las {VENTANA} velas diarias siguientes llega a +{OBJETIVO:g} % sobre el "
              "cierre de la vela del día de la lista.", "",
              "| Candidatas | Total | Con resultado | Llegaron a +50 % | % | Pendientes | Sin datos |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for nombre, grupo in grupos.items():
        finales = [f for f in grupo if f["estado"] in FINALES]
        llegaron = sum(f["estado"] == "llego" for f in finales)
        pct = f"{llegaron / len(finales) * 100:.1f}" if finales else "—"
        lineas.append(f"| {nombre} | {len(grupo)} | {len(finales)} | {llegaron} | {pct} | "
                      f"{sum(f['estado'] == 'pendiente' for f in grupo)} | "
                      f"{sum(f['estado'] == 'sin_datos' for f in grupo)} |")

    llegaron = [f for f in filas if f["estado"] == "llego"]
    if llegaron:
        con_explosion = sum(bool(f["explosiones_despues"]) for f in llegaron)
        lineas += ["", f"De las {len(llegaron)} que llegaron a +50 %, {con_explosion} salieron después en "
                       f"Scanner-pump (vela de +10 % o más en los {VENTANA} días siguientes)."]
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Etiqueta las candidatas: ¿llegaron a +50 % en 10 días?")
    parser.add_argument("--listas", type=Path, default=listas.RAIZ_LISTAS)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--resumen", type=Path, help="añade el resumen en Markdown a este archivo")
    parser.add_argument("--hilos", type=int, default=8)
    args = parser.parse_args(argv)

    binance = Binance()
    filas = calcular(listas.candidatas(args.listas), listas.explosiones(args.listas), binance,
                     leer_csv(args.salida), ultima_vela_cerrada(), args.hilos)
    escribir_csv(args.salida, filas)
    texto = resumen(filas)
    print(texto)
    for aviso in binance.avisos:
        print(f"Aviso: {aviso}", file=sys.stderr)
    if args.resumen:
        with args.resumen.open("a", encoding="utf-8") as fh:
            fh.write("## Etiquetas\n\n" + texto + "".join(f"\n> {a}\n" for a in binance.avisos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
