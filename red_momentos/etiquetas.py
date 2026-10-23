"""Etiqueta de cada candidata: ¿llegó a +50 % en los 10 días siguientes?

Regla: el máximo de los 10 días siguientes llega a +50 % sobre el precio de referencia.

El precio de referencia es el de las **19:30 en Lima (00:30 UTC)** después del cierre de la vela del día de
la lista, la hora a la que la red da su lista: la apertura de la vela de 30 minutos que empieza a esa hora.
Los 10 días van de ahí a las 19:30 del décimo día y se miden con velas de 30 minutos.

Cada candidata es una moneda de Momento-A o Momento-B en un día («No repetidas»; futuros si salió en
futuros). Las columnas ``explosion_mismo_dia`` y ``explosiones_despues`` dicen si la moneda salió en
Scanner-pump ese día o en los 10 siguientes, para comparar.

    python -m red_momentos.etiquetas [--salida datos/etiquetas.csv] [--resumen RESUMEN.md]
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

from . import listas
from .binance import DURACION, Binance, Vela
from .fechas import ms, vela_utc

VENTANA = 10  # días
OBJETIVO = 50.0  # %
INTERVALO = "30m"
PASO = DURACION[INTERVALO]
DIA_MS = DURACION["1d"]
SALIDA = Path("datos/etiquetas.csv")

COLUMNAS = ["fecha", "moneda", "mercado", "simbolo", "listas", "vela_utc", "referencia", "maximo", "pct_maximo",
            "minimo", "pct_minimo", "dias_hasta_50", "dias_vistos", "estado", "explosion_mismo_dia",
            "explosiones_despues"]
# llego: tocó +50 % · no_llego: pasaron los 10 días sin tocarlo · pendiente: aún no pasaron los 10 días
# (o aún no son las 19:30 del día) · sin_datos: Binance no tiene el precio de las 19:30 de ese día.
FINALES = ("llego", "no_llego")


def referencia_ms(fecha: date) -> int:
    """Las 00:30 UTC (19:30 en Lima) en que se mide el precio de referencia de un día de las listas."""
    return ms(vela_utc(fecha)) + DIA_MS + PASO


@dataclass
class Resultado:
    referencia: Optional[float] = None
    maximo: Optional[float] = None
    minimo: Optional[float] = None
    dias_hasta_50: Optional[int] = None
    dias_vistos: int = 0  # días de la ventana ya transcurridos con datos
    estado: str = "pendiente"

    def pct(self, precio: Optional[float]) -> Optional[float]:
        return None if precio is None or not self.referencia else (precio / self.referencia - 1) * 100


def etiquetar(fecha: date, velas: dict[int, Vela], cubierto: int) -> Resultado:
    """Aplica la regla a la candidata de un día con las velas de 30 minutos de su par (por apertura).

    ``cubierto`` es hasta dónde llegan los datos (milisegundos UTC).
    """
    inicio = referencia_ms(fecha)
    fin = inicio + VENTANA * DIA_MS
    primera = velas.get(inicio)
    if primera is None:
        return Resultado(estado="pendiente" if inicio > cubierto else "sin_datos")

    r = Resultado(referencia=primera.open)
    meta = primera.open * (1 + OBJETIVO / 100)
    for apertura in range(inicio, min(fin, cubierto + 1), PASO):
        vela = velas.get(apertura)
        if vela is None:  # hueco en los datos o el par dejó de cotizar
            continue
        r.maximo = vela.high if r.maximo is None else max(r.maximo, vela.high)
        r.minimo = vela.low if r.minimo is None else min(r.minimo, vela.low)
        if r.dias_hasta_50 is None and vela.high >= meta:
            r.dias_hasta_50 = (apertura - inicio) // DIA_MS + 1
    r.dias_vistos = min(VENTANA, max(0, (min(cubierto + PASO, fin) - inicio) // DIA_MS))
    if r.dias_hasta_50 is not None:
        r.estado = "llego"
    elif fin - PASO <= cubierto:
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
             anteriores: dict[tuple[str, str], dict], ahora: int, hilos: int = 8) -> list[dict]:
    """Filas del CSV. Las etiquetas ya cerradas de ``anteriores`` se reutilizan sin pedir velas.

    ``ahora`` va en milisegundos UTC.
    """
    filas: dict[tuple[str, str], dict] = {}
    por_par: dict[tuple[str, str], list[listas.Candidata]] = defaultdict(list)
    for c in candidatas:
        clave = (c.fecha.isoformat(), c.moneda)
        previa = anteriores.get(clave)
        inicio = referencia_ms(c.fecha)
        # Con un día de margen: con data.binance.vision el último día tarda unas horas en publicarse.
        cerrada = inicio + (VENTANA + 1) * DIA_MS <= ahora
        if (previa and cerrada and previa.get("estado") in FINALES and previa.get("referencia")
                and (previa["mercado"], previa["simbolo"]) == (c.mercado, c.simbolo)):
            filas[clave] = {k: previa.get(k, "") for k in COLUMNAS}
        elif inicio <= ahora:
            por_par[(c.mercado, c.simbolo)].append(c)
        else:
            filas[clave] = _fila(c, Resultado())  # todavía no son las 19:30 de ese día

    def descargar(par: tuple[str, str]) -> tuple[tuple[str, str], dict[int, Vela], int]:
        mercado, simbolo = par
        inicios = [referencia_ms(c.fecha) for c in por_par[par]]
        hasta = min(max(inicios) + VENTANA * DIA_MS - PASO, ahora - ahora % PASO)
        velas, cubierto = binance.velas(mercado, simbolo, INTERVALO, min(inicios), hasta)
        return par, {v.apertura: v for v in velas}, cubierto

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
        "referencia": _num(r.referencia), "maximo": _num(r.maximo), "pct_maximo": _num(r.pct(r.maximo), 2),
        "minimo": _num(r.minimo), "pct_minimo": _num(r.pct(r.minimo), 2),
        "dias_hasta_50": "" if r.dias_hasta_50 is None else str(r.dias_hasta_50),
        "dias_vistos": str(r.dias_vistos), "estado": r.estado, "explosion_mismo_dia": "0",
        "explosiones_despues": "",
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
    lineas = [f"Regla: el máximo de los {VENTANA} días siguientes llega a +{OBJETIVO:g} % sobre el precio de "
              "las 19:30 (hora Lima) después del cierre de la vela del día de la lista.", "",
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
        lineas += ["", f"Las {len(llegaron)} filas que llegaron a +50 % son "
                       f"{len({f['moneda'] for f in llegaron})} monedas distintas."]
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
                     leer_csv(args.salida), int(time.time() * 1000), args.hilos)
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
