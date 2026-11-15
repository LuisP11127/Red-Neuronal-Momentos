"""Compara arquitecturas de redes neuronales con la misma medida que usa la red para elegir su modelo.

    pip install torch --index-url https://download.pytorch.org/whl/cpu
    python analisis/arquitecturas.py --cache cache/velas-1d --salida arquitecturas.json

Cada arquitectura se entrena en los 6 cortes de 90 días de ``red_momentos.red`` (solo con lo anterior a cada corte,
con 11 días de separación) y se mide por lo que se ve: de las 3 mejor puntuadas de cada día, qué parte llegó a
+50 %. Después, la prueba con las listas reales. Todas usan los mismos pesos por racha y, las que trabajan con las
señales, las mismas entradas pasadas por cuantiles.

Hay dos familias:

- **Sobre las señales** (una fila por moneda y día): perceptrones de distinto tamaño, con normalización por lotes y
  *dropout*, una red residual y un transformador de señales (FT-Transformer).
- **Sobre las velas** (las 30 velas diarias anteriores, sin señales calculadas a mano): una red recurrente (GRU) y
  una convolucional, solas y unidas a las señales.

Las velas salen de la caché de la reconstrucción (``cache/velas-1d``); las que falten se piden a Binance.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from red_momentos import etiquetas, red, senales  # noqa: E402
from red_momentos.binance import Binance  # noqa: E402
from red_momentos.fechas import dia_de_ms  # noqa: E402

LARGO = 30  # velas diarias que ve una red de velas
CANALES = 7
EPOCAS = 12
LOTE = 512


# --- Datos ------------------------------------------------------------------------------------------------

def leer_filas(reconstruccion: Path) -> list[dict]:
    """Las filas con resultado de la reconstrucción y de las listas reales (si un día y moneda está en las dos, la
    real), con las mismas reglas que ``red.a_datos``."""
    with gzip.open(reconstruccion, "rt", encoding="utf-8", newline="") as fh:
        recon = list(csv.DictReader(fh))
    sen = senales.leer_csv(senales.SALIDA)
    reales = []
    for clave, fila in etiquetas.leer_csv(etiquetas.SALIDA).items():
        if clave in sen:
            reales.append({**sen[clave], "estado": fila["estado"], "pct_minimo": fila.get("pct_minimo", "")})
        elif fila["estado"] == "pendiente":
            reales.append({"fecha": fila["fecha"], "moneda": fila["moneda"], "estado": "pendiente"})

    def utiles(filas: list[dict], real: bool) -> list[dict]:
        abiertos = {f["fecha"] for f in filas if f.get("estado") == "pendiente"}
        return [{**f, "real": real} for f in filas if f["fecha"] not in abiertos
                and f.get("estado") in etiquetas.FINALES and f.get("completa") == "1"]

    reales = utiles(reales, True)
    vistas = {(f["fecha"], f["moneda"]) for f in reales}
    return [f for f in utiles(recon, False) if (f["fecha"], f["moneda"]) not in vistas] + reales


class Velas:
    """Velas diarias de cada par: de la caché y, lo que falte hasta ``hasta``, de Binance."""

    def __init__(self, cache: Path, hasta: date) -> None:
        self.cache, self.hasta, self.binance, self.pares = cache, hasta, Binance(), {}

    def de(self, mercado: str, simbolo: str, necesita: date) -> tuple[dict, np.ndarray]:
        clave = (mercado, simbolo)
        if clave not in self.pares:
            ruta = self.cache / mercado / f"{simbolo}.csv"
            filas = []
            if ruta.exists():
                with ruta.open(encoding="utf-8", newline="") as fh:
                    filas = [(dia_de_ms(int(f[0])), float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[6]),
                              float(f[9])) for f in csv.reader(fh)]
            self.pares[clave] = filas
        filas = self.pares[clave]
        if not filas or filas[-1][0] < necesita:  # la caché se quedó corta: el resto, de Binance
            desde = filas[-1][0] + timedelta(days=1) if filas else necesita - timedelta(days=LARGO + 5)
            nuevas, _ = self.binance.velas_diarias(mercado, simbolo, desde, self.hasta)
            filas.extend((v.dia, v.open, v.high, v.low, v.close, v.volumen_usdt, v.compra_taker_usdt) for v in nuevas)
            if not filas or filas[-1][0] < necesita:
                filas.append((date.max, 0, 0, 0, 0, 0, 0))  # no hay más: no se vuelve a pedir
        indice = {f[0]: i for i, f in enumerate(filas)}
        return indice, np.array([f[1:] for f in filas], dtype=float).reshape(-1, 6)


def secuencias(filas: list[dict], velas: Velas) -> np.ndarray:
    """Para cada fila, las ``LARGO`` velas diarias hasta la del día de la lista (la que abre el día UTC siguiente),
    como canales sin escala: variación del cierre, rango, cuerpo, mecha superior, volumen frente a la media de la
    ventana, compras agresivas y distancia al último cierre. Un último canal dice si la vela existe."""
    x = np.zeros((len(filas), LARGO, CANALES + 1), dtype=np.float32)
    for n, f in enumerate(filas):
        dia = date.fromisoformat(f["fecha"]) + timedelta(days=1)
        indice, v = velas.de(f["mercado"], f["simbolo"], dia)
        fin = indice.get(dia)
        if fin is None:
            continue
        w = v[max(0, fin - LARGO + 1):fin + 1]
        o, h, l, c, vol, taker = w.T
        previo = np.concatenate([[v[fin - len(w), 3] if fin - len(w) >= 0 else o[0]], c[:-1]])
        with np.errstate(divide="ignore", invalid="ignore"):
            canales = np.stack([
                np.log(c / previo), np.log(h / l), np.log(c / o), (h - np.maximum(o, c)) / (h - l),
                np.log(vol / vol.mean()), taker / vol - 0.5, np.log(c / c[-1])], axis=1)
        canales = np.clip(np.nan_to_num(canales, nan=0.0, posinf=5.0, neginf=-5.0), -5, 5)
        x[n, LARGO - len(w):, :CANALES] = canales
        x[n, LARGO - len(w):, CANALES] = 1
    return x


# --- Arquitecturas ----------------------------------------------------------------------------------------

class Perceptron(nn.Module):
    def __init__(self, entradas: int, capas: tuple[int, ...], dropout: float = 0.0, norma: bool = False) -> None:
        super().__init__()
        bloques, ancho = [], entradas
        for n in capas:
            bloques += [nn.Linear(ancho, n)] + ([nn.BatchNorm1d(n)] if norma else []) + [nn.ReLU()]
            bloques += [nn.Dropout(dropout)] if dropout else []
            ancho = n
        self.cuerpo, self.salida = nn.Sequential(*bloques), nn.Linear(ancho, 1)

    def forward(self, tabla, velas):
        return self.salida(self.cuerpo(tabla)).squeeze(1)


class Residual(nn.Module):
    """Bloques con atajo (ResNet para tablas): cada uno corrige lo que lleva el anterior."""

    def __init__(self, entradas: int, ancho: int = 128, bloques: int = 3, dropout: float = 0.2) -> None:
        super().__init__()
        self.entrada = nn.Linear(entradas, ancho)
        self.bloques = nn.ModuleList(nn.Sequential(
            nn.BatchNorm1d(ancho), nn.Linear(ancho, ancho), nn.ReLU(), nn.Dropout(dropout), nn.Linear(ancho, ancho))
            for _ in range(bloques))
        self.salida = nn.Sequential(nn.BatchNorm1d(ancho), nn.ReLU(), nn.Linear(ancho, 1))

    def forward(self, tabla, velas):
        z = self.entrada(tabla)
        for bloque in self.bloques:
            z = z + bloque(z)
        return self.salida(z).squeeze(1)


class TransformadorSenales(nn.Module):
    """FT-Transformer: cada señal es una ficha y la atención mira cómo se combinan."""

    def __init__(self, entradas: int, ancho: int = 32, capas: int = 2, cabezas: int = 4, dropout: float = 0.1) -> None:
        super().__init__()
        self.peso = nn.Parameter(torch.randn(entradas, ancho) * 0.1)
        self.sesgo = nn.Parameter(torch.zeros(entradas, ancho))
        self.cls = nn.Parameter(torch.zeros(1, 1, ancho))
        capa = nn.TransformerEncoderLayer(ancho, cabezas, ancho * 2, dropout, batch_first=True, norm_first=True)
        self.atencion = nn.TransformerEncoder(capa, capas, enable_nested_tensor=False)
        self.salida = nn.Sequential(nn.LayerNorm(ancho), nn.ReLU(), nn.Linear(ancho, 1))

    def forward(self, tabla, velas):
        fichas = tabla.unsqueeze(2) * self.peso + self.sesgo
        z = self.atencion(torch.cat([self.cls.expand(len(tabla), -1, -1), fichas], dim=1))
        return self.salida(z[:, 0]).squeeze(1)


class Recurrente(nn.Module):
    """GRU sobre las velas; con ``tabla`` > 0, unida a un perceptrón de las señales."""

    def __init__(self, tabla: int = 0, ancho: int = 48, dropout: float = 0.2) -> None:
        super().__init__()
        self.gru = nn.GRU(CANALES + 1, ancho, batch_first=True)
        self.tabla = nn.Sequential(nn.Linear(tabla, 64), nn.ReLU()) if tabla else None
        self.salida = nn.Sequential(nn.Dropout(dropout), nn.Linear(ancho + (64 if tabla else 0), 32), nn.ReLU(),
                                    nn.Linear(32, 1))

    def forward(self, tabla, velas):
        z = self.gru(velas)[1][-1]
        if self.tabla is not None:
            z = torch.cat([z, self.tabla(tabla)], dim=1)
        return self.salida(z).squeeze(1)


class Convolucional(nn.Module):
    """Convoluciones 1D sobre las velas (patrones de pocos días), resumidas con el máximo y la media."""

    def __init__(self, tabla: int = 0, ancho: int = 32, dropout: float = 0.2) -> None:
        super().__init__()
        self.conv = nn.Sequential(nn.Conv1d(CANALES + 1, ancho, 3, padding=1), nn.ReLU(),
                                  nn.Conv1d(ancho, ancho, 3, padding=1), nn.ReLU(),
                                  nn.Conv1d(ancho, ancho, 5, padding=2), nn.ReLU())
        self.tabla = nn.Sequential(nn.Linear(tabla, 64), nn.ReLU()) if tabla else None
        self.salida = nn.Sequential(nn.Dropout(dropout), nn.Linear(ancho * 2 + (64 if tabla else 0), 32), nn.ReLU(),
                                    nn.Linear(32, 1))

    def forward(self, tabla, velas):
        z = self.conv(velas.transpose(1, 2))
        z = torch.cat([z.amax(dim=2), z.mean(dim=2)], dim=1)
        if self.tabla is not None:
            z = torch.cat([z, self.tabla(tabla)], dim=1)
        return self.salida(z).squeeze(1)


# nombre: (descripción, constructor(entradas), decaimiento de pesos, semillas)
ARQUITECTURAS = {
    "mlp_32": ("Perceptrón de 1 capa (32)", lambda n: Perceptron(n, (32,)), 1e-4, 3),
    "mlp_64_32": ("Perceptrón de 2 capas (64 y 32): la forma de la red actual", lambda n: Perceptron(n, (64, 32)), 1e-4, 3),
    "mlp_256_128": ("Perceptrón ancho (256 y 128)", lambda n: Perceptron(n, (256, 128)), 1e-4, 3),
    "mlp_128_64_32_16": ("Perceptrón profundo (128, 64, 32 y 16)", lambda n: Perceptron(n, (128, 64, 32, 16)), 1e-4, 3),
    "mlp_norma_dropout": ("Perceptrón (128 y 64) con normalización por lotes y dropout",
                          lambda n: Perceptron(n, (128, 64), 0.3, True), 1e-4, 3),
    "residual": ("Red residual (3 bloques de 128)", lambda n: Residual(n), 1e-4, 3),
    "transformador": ("Transformador de señales (FT-Transformer, 2 capas)", lambda n: TransformadorSenales(n), 1e-4, 1),
    "gru_velas": ("Recurrente (GRU) solo con las 30 velas", lambda n: Recurrente(), 1e-4, 3),
    "cnn_velas": ("Convolucional solo con las 30 velas", lambda n: Convolucional(), 1e-4, 3),
    "gru_senales": ("Recurrente (GRU) con las velas + señales", lambda n: Recurrente(n), 1e-4, 3),
    "cnn_senales": ("Convolucional con las velas + señales", lambda n: Convolucional(n), 1e-4, 3),
}
CLASICOS = {"logistica": "Regresión logística (la elegida ahora)", "arboles": "Árboles de gradiente",
            "red": "Red actual de scikit-learn (64 y 32, 3 semillas)"}


def entrenar(constructor, entradas: int, tabla, velas, y, pesos, decaimiento: float, semilla: int) -> nn.Module:
    torch.manual_seed(semilla)  # fija los pesos iniciales y el orden de los lotes
    modelo = constructor(entradas)
    optimizador = torch.optim.AdamW(modelo.parameters(), lr=1e-3, weight_decay=decaimiento)
    n = len(y)
    modelo.train()
    for _ in range(EPOCAS):
        orden = torch.randperm(n)
        for i in range(0, n - 1, LOTE):  # un lote de una sola fila rompe la normalización por lotes
            lote = orden[i:i + LOTE]
            if len(lote) < 2:
                continue
            perdida = nn.functional.binary_cross_entropy_with_logits(modelo(tabla[lote], velas[lote]), y[lote],
                                                                     weight=pesos[lote])
            optimizador.zero_grad()
            perdida.backward()
            optimizador.step()
    return modelo


@torch.no_grad()
def puntuar(modelo: nn.Module, tabla, velas) -> np.ndarray:
    modelo.eval()
    return torch.cat([torch.sigmoid(modelo(tabla[i:i + 4096], velas[i:i + 4096]))
                      for i in range(0, len(tabla), 4096)]).numpy()


# --- Medida -----------------------------------------------------------------------------------------------

def medir(fechas: np.ndarray, y: np.ndarray, p: np.ndarray) -> dict:
    elegidas = red.elegidas_por_dia(fechas, p)
    primera = red.elegidas_por_dia(fechas, p, 1)
    return {"auc": red.auc(y, p), "precision": float(y[elegidas].mean()), "primera": float(y[primera].mean()),
            "mostradas": int(elegidas.sum()), "llegaron": int(y[elegidas].sum()),
            "intervalo": red.intervalo(fechas, y, elegidas)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara arquitecturas de redes neuronales en los cortes de la red.")
    parser.add_argument("--reconstruccion", type=Path, default=red.RECONSTRUCCION)
    parser.add_argument("--cache", type=Path, default=Path("cache/velas-1d"))
    parser.add_argument("--salida", type=Path, default=Path("arquitecturas.json"))
    parser.add_argument("--solo", nargs="*", help="nombres de las arquitecturas a medir (por defecto, todas)")
    args = parser.parse_args()

    filas = leer_filas(args.reconstruccion)
    fechas = np.array([f["fecha"] for f in filas], dtype="datetime64[D]")
    monedas = np.array([f["moneda"] for f in filas])
    real = np.array([f["real"] for f in filas])
    y = np.array([f["estado"] == "llego" for f in filas], dtype=float)
    x = red.matriz(filas)
    print(f"{len(filas)} filas ({int(real.sum())} de listas reales); llegaron {int(y.sum())}", file=sys.stderr)
    t0 = time.time()
    velas_np = secuencias(filas, Velas(args.cache, fechas.max().astype(date) + timedelta(days=1)))
    print(f"Velas: {time.time() - t0:.0f} s; filas sin velas: {int((velas_np[:, -1, CANALES] == 0).sum())}", file=sys.stderr)

    # Los mismos tramos que red.entrenar: 6 cortes antes de la prueba y la prueba con las listas reales.
    todo = red.Datos(fechas, monedas, x, y)
    t = red.tramos(todo.filtrar(~real), todo.filtrar(real))
    inicio_prueba, fin_prueba = t["prueba"]
    antes = lambda dia: fechas <= np.datetime64(dia, "D") - red.SEPARACION
    previo = antes(inicio_prueba)
    tramos = [(f"{a} a {b}", previo & antes(a), previo & (fechas >= np.datetime64(a, "D")) & (fechas <= np.datetime64(b, "D")))
              for a, b in t["cortes"]]
    tramos.append(("prueba: listas reales", previo,
                   real & (fechas >= np.datetime64(inicio_prueba, "D")) & (fechas <= np.datetime64(fin_prueba, "D"))))

    resultados = json.loads(args.salida.read_text()) if args.salida.exists() else {}
    nombres = args.solo or list(CLASICOS) + list(ARQUITECTURAS)
    for nombre in nombres:
        if nombre in resultados:
            continue
        t0 = time.time()
        por_tramo = []
        for etiqueta, entreno, ventana in tramos:
            cuantiles = red.Cuantiles.ajustar(x[entreno])
            e_entreno, e_ventana = cuantiles.aplicar(x[entreno]), cuantiles.aplicar(x[ventana])
            pesos = red.pesos_por_racha(fechas[entreno], monedas[entreno])
            if nombre in CLASICOS:
                p = red.ajustar(e_entreno, y[entreno], red.CANDIDATOS[nombre], pesos).puntuar(e_ventana)
                semillas = [p]
            else:
                _, constructor, decaimiento, cuantas = ARQUITECTURAS[nombre]
                tensores = [torch.tensor(a, dtype=torch.float32) for a in
                            (e_entreno, velas_np[entreno], y[entreno], pesos, e_ventana, velas_np[ventana])]
                semillas = [puntuar(entrenar(constructor, x.shape[1], *tensores[:4], decaimiento, s), *tensores[4:])
                            for s in range(cuantas)]
                p = np.mean(semillas, axis=0)
            m = medir(fechas[ventana], y[ventana], p)
            m["por_semilla"] = [medir(fechas[ventana], y[ventana], s)["precision"] for s in semillas]
            por_tramo.append({"tramo": etiqueta, "base": float(y[ventana].mean()), **m})
            print(f"  {nombre} {etiqueta}: 3 mejores {m['precision']:.3f}, AUC {m['auc']:.3f}", file=sys.stderr, flush=True)
        cortes = por_tramo[:-1]
        resultados[nombre] = {
            "descripcion": CLASICOS.get(nombre) or ARQUITECTURAS[nombre][0], "tramos": por_tramo,
            "precision": float(np.mean([c["precision"] for c in cortes])),
            "primera": float(np.mean([c["primera"] for c in cortes])), "auc": float(np.mean([c["auc"] for c in cortes])),
            "precision_semillas": float(np.mean([np.mean(c["por_semilla"]) for c in cortes])),
            "desviacion_semillas": float(np.mean([np.std(c["por_semilla"]) for c in cortes])),
            "segundos": round(time.time() - t0),
        }
        args.salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
        r = resultados[nombre]
        print(f"{nombre}: 3 mejores {r['precision']:.3f}, AUC {r['auc']:.3f} ({r['segundos']} s)", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
