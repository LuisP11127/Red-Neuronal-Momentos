"""Red neuronal: aprende qué candidatas llegan a +50 % en 10 días.

**Datos.** La reconstrucción desde 2023 (``datos/reconstruccion/filas.csv.gz``) y las listas reales
(``datos/etiquetas.csv`` con ``datos/senales.csv``). Solo entran las filas con resultado final y señales
completas.

**Tramos por fecha**, sin mezclar días y con 10 días de separación entre uno y otro (lo que dura la
etiqueta), para que la red no vea nada del tramo con el que se la mide:

- entrenamiento: la reconstrucción hasta unos cinco meses antes de las listas reales;
- validación: la reconstrucción de esos cinco meses; aquí se elige la red y el umbral;
- prueba: las listas reales (y, para comparar, la reconstrucción de esos mismos días).

**Señales.** Las de ``senales.SENALES`` (menos ``EXCLUIDAS``) y tres más que dicen si hay libro, métricas y si es futuros. Cada
señal se pasa a su posición entre los valores del entrenamiento (de 0 a 1, por cuantiles), así los valores
extremos no pesan de más; un dato que falta queda en 0,5 y lo marca su indicador.

**Umbral.** La red muestra una moneda si su puntuación supera el umbral más bajo con el que, en la
validación, al menos 3 de cada 10 monedas llegaron a +50 %. Si ninguno lo consigue, no muestra nada.

**Comparación.** Una regresión logística con las mismas señales y elegir al azar (la proporción de
candidatas que llegan a +50 %).

El modelo se guarda en ``modelo/red.json`` (cuantiles y pesos) y la predicción se hace con numpy, así no
depende de la versión de scikit-learn. ``modelo/INFORME.md`` resume los resultados.

    python -m red_momentos.red
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from . import etiquetas, senales

PRECISION_MINIMA = 0.30  # 3 de cada 10
MINIMO_SOBRE_UMBRAL = 20  # filas de la validación sobre el umbral para fiarse de su precisión
SEPARACION = timedelta(days=etiquetas.VENTANA + 1)
VALIDACION = timedelta(days=150)
CUANTILES = 101
INDICADORES = ["tiene_libro", "tiene_metricas", "es_futuros"]
# Binance publica la banda de ±0,2 % del libro solo desde enero de 2026: en el entrenamiento casi siempre
# falta y en la validación casi nunca, así que la red aprendería la fecha y no la señal.
EXCLUIDAS = {"libro_deseq_02"}
ENTRADAS = [k for k in senales.SENALES if k not in EXCLUIDAS] + INDICADORES
CONFIGURACIONES = [  # se elige la que mejor ordena la validación
    {"hidden_layer_sizes": (32,), "alpha": 1e-3},
    {"hidden_layer_sizes": (64, 32), "alpha": 1e-3},
    {"hidden_layer_sizes": (64, 32), "alpha": 1e-2},
]
RECONSTRUCCION = Path("datos/reconstruccion/filas.csv.gz")
MODELO = Path("modelo/red.json")
INFORME = Path("modelo/INFORME.md")


@dataclass
class Datos:
    fechas: np.ndarray  # datetime64[D]
    monedas: np.ndarray
    x: np.ndarray  # señales en bruto (NaN si faltan)
    y: np.ndarray  # 1 si llegó a +50 %

    def __len__(self) -> int:
        return len(self.y)

    def tramo(self, desde: Optional[date] = None, hasta: Optional[date] = None) -> "Datos":
        filtro = np.ones(len(self), dtype=bool)
        if desde:
            filtro &= self.fechas >= np.datetime64(desde)
        if hasta:
            filtro &= self.fechas <= np.datetime64(hasta)
        return Datos(self.fechas[filtro], self.monedas[filtro], self.x[filtro], self.y[filtro])


def _valor(texto: str) -> float:
    return float(texto) if texto not in ("", None) else math.nan


def matriz(filas: list[dict]) -> np.ndarray:
    """Las entradas de la red (``ENTRADAS``) de cada fila con señales (strings del CSV)."""
    x = np.array([[_valor(f.get(k, "")) for k in senales.SENALES] for f in filas], dtype=float).reshape(-1, len(senales.SENALES))
    libro = [senales.SENALES.index(k) for k in senales.LIBRO if k not in EXCLUIDAS]
    tiene_libro = (~np.isnan(x[:, libro])).any(axis=1)
    tiene_metricas = (~np.isnan(x[:, [senales.SENALES.index(k) for k in senales.METRICAS]])).any(axis=1)
    es_futuros = np.array([f["mercado"] == "futures" for f in filas], dtype=bool)
    columnas = [senales.SENALES.index(k) for k in ENTRADAS if k not in INDICADORES]
    return np.hstack([x[:, columnas], np.column_stack([tiene_libro, tiene_metricas, es_futuros]).astype(float)])


def a_datos(filas: list[dict]) -> Datos:
    """Filas con ``estado`` y las señales (strings del CSV) → matrices. Solo las finales y completas."""
    utiles = [f for f in filas if f.get("estado") in etiquetas.FINALES and f.get("completa") == "1"]
    return Datos(np.array([f["fecha"] for f in utiles], dtype="datetime64[D]"),
                 np.array([f["moneda"] for f in utiles]), matriz(utiles),
                 np.array([f["estado"] == "llego" for f in utiles], dtype=float))


def leer_reconstruccion(ruta: Path = RECONSTRUCCION) -> Datos:
    with gzip.open(ruta, "rt", encoding="utf-8", newline="") as fh:
        return a_datos(list(csv.DictReader(fh)))


def leer_reales(etiquetas_csv: Path = etiquetas.SALIDA, senales_csv: Path = senales.SALIDA) -> Datos:
    sen = senales.leer_csv(senales_csv)
    filas = []
    for clave, fila in etiquetas.leer_csv(etiquetas_csv).items():
        if clave in sen:
            filas.append({**sen[clave], "estado": fila["estado"]})
    return a_datos(filas)


# --- Preparación de las señales ------------------------------------------------------------------------

@dataclass
class Cuantiles:
    puntos: np.ndarray  # (CUANTILES, señales)

    @classmethod
    def ajustar(cls, x: np.ndarray) -> "Cuantiles":
        niveles = np.linspace(0, 100, CUANTILES)
        puntos = np.zeros((CUANTILES, x.shape[1]))
        for j in range(x.shape[1]):
            columna = x[:, j][~np.isnan(x[:, j])]
            puntos[:, j] = np.percentile(columna, niveles) if len(columna) else 0.0
        return cls(puntos)

    def aplicar(self, x: np.ndarray) -> np.ndarray:
        resultado = np.full(x.shape, 0.5)
        destino = np.linspace(0, 1, CUANTILES)
        for j in range(x.shape[1]):
            columna = x[:, j]
            presentes = ~np.isnan(columna)
            puntos = self.puntos[:, j]
            if puntos[-1] > puntos[0]:
                # Con valores repetidos, el promedio de interpolar por la izquierda y por la derecha.
                izquierda = np.interp(columna[presentes], puntos, destino)
                derecha = 1 - np.interp(-columna[presentes], -puntos[::-1], destino)
                resultado[presentes, j] = (izquierda + derecha) / 2
            else:
                resultado[presentes, j] = 0.5
        return resultado


@dataclass
class Red:
    """La red ya entrenada, con lo necesario para predecir sin scikit-learn."""
    cuantiles: Cuantiles
    pesos: list[np.ndarray]
    sesgos: list[np.ndarray]
    umbral: Optional[float]
    entradas: list[str]

    def puntuar(self, x: np.ndarray) -> np.ndarray:
        a = self.cuantiles.aplicar(x)
        for w, b in zip(self.pesos[:-1], self.sesgos[:-1]):
            a = np.maximum(a @ w + b, 0)
        return 1 / (1 + np.exp(-(a @ self.pesos[-1] + self.sesgos[-1]).ravel()))

    def guardar(self, ruta: Path, extra: dict) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({
            "entradas": self.entradas, "umbral": self.umbral,
            "cuantiles": np.round(self.cuantiles.puntos, 8).tolist(),
            "pesos": [np.round(w, 8).tolist() for w in self.pesos],
            "sesgos": [np.round(b, 8).tolist() for b in self.sesgos], **extra,
        }, ensure_ascii=False))

    @classmethod
    def cargar(cls, ruta: Path = MODELO) -> "Red":
        d = json.loads(ruta.read_text())
        return cls(Cuantiles(np.array(d["cuantiles"])), [np.array(w) for w in d["pesos"]],
                   [np.array(b) for b in d["sesgos"]], d["umbral"], d["entradas"])


def entrenar_red(x: np.ndarray, y: np.ndarray, configuracion: dict, semilla: int = 0) -> Red:
    from sklearn.neural_network import MLPClassifier

    cuantiles = Cuantiles.ajustar(x)
    modelo = MLPClassifier(activation="relu", solver="adam", batch_size=512, learning_rate_init=1e-3,
                           max_iter=200, early_stopping=True, validation_fraction=0.1, n_iter_no_change=10,
                           random_state=semilla, **configuracion)
    modelo.fit(cuantiles.aplicar(x), y.astype(int))
    return Red(cuantiles, list(modelo.coefs_), list(modelo.intercepts_), None, ENTRADAS)


def entrenar_logistica(x: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import LogisticRegression

    cuantiles = Cuantiles.ajustar(x)
    modelo = LogisticRegression(max_iter=2000, C=1.0).fit(cuantiles.aplicar(x), y.astype(int))
    return lambda nuevas: modelo.predict_proba(cuantiles.aplicar(nuevas))[:, 1]


# --- Medidas --------------------------------------------------------------------------------------------

def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Probabilidad de que una que llegó puntúe más que una que no (0,5 = al azar)."""
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else math.nan


def elegir_umbral(y: np.ndarray, p: np.ndarray, precision: float = PRECISION_MINIMA,
                  minimo: int = MINIMO_SOBRE_UMBRAL) -> Optional[float]:
    """El umbral más bajo con el que, de las que lo superan (al menos ``minimo``), llega ``precision``."""
    orden = np.argsort(-p)
    aciertos = np.cumsum(y[orden])
    cuantas = np.arange(1, len(y) + 1)
    validos = np.flatnonzero((cuantas >= minimo) & (aciertos / cuantas >= precision))
    if not len(validos):
        return None
    k = validos[-1]
    # Empates: el umbral es la puntuación de la última que entra, y entran todas las que la igualan.
    return float(p[orden][k])


def resumen_umbral(datos: Datos, p: np.ndarray, umbral: Optional[float]) -> dict:
    if umbral is None:
        return {"mostradas": 0, "llegaron": 0, "precision": math.nan, "dias_con_lista": 0,
                "dias": int(len(np.unique(datos.fechas)))}
    sobre = p >= umbral
    return {"mostradas": int(sobre.sum()), "llegaron": int(datos.y[sobre].sum()),
            "precision": float(datos.y[sobre].mean()) if sobre.any() else math.nan,
            "dias_con_lista": int(len(np.unique(datos.fechas[sobre]))), "dias": int(len(np.unique(datos.fechas)))}


def mejor_del_dia(datos: Datos, p: np.ndarray) -> float:
    """De la moneda mejor puntuada de cada día, qué parte llegó a +50 %."""
    aciertos = []
    for dia in np.unique(datos.fechas):
        del_dia = datos.fechas == dia
        aciertos.append(datos.y[del_dia][np.argmax(p[del_dia])])
    return float(np.mean(aciertos)) if aciertos else math.nan


def importancias(red: Red, datos: Datos, repeticiones: int = 3, semilla: int = 0) -> list[tuple[str, float]]:
    """Cuánto baja el AUC de la validación al desordenar cada señal (más = la red se apoya más en ella)."""
    rng = np.random.default_rng(semilla)
    base = auc(datos.y, red.puntuar(datos.x))
    resultado = []
    for j, nombre in enumerate(red.entradas):
        caidas = []
        for _ in range(repeticiones):
            x = datos.x.copy()
            x[:, j] = x[rng.permutation(len(x)), j]
            caidas.append(base - auc(datos.y, red.puntuar(x)))
        resultado.append((nombre, float(np.mean(caidas))))
    return sorted(resultado, key=lambda t: -t[1])


# --- Entrenamiento completo ------------------------------------------------------------------------------

def tramos(reconstruccion: Datos, reales: Datos) -> dict[str, tuple[date, date]]:
    inicio_prueba = (reales.fechas.min().astype(date) if len(reales)
                     else reconstruccion.fechas.max().astype(date) - VALIDACION)
    fin_validacion = inicio_prueba - SEPARACION
    inicio_validacion = fin_validacion - VALIDACION
    fin_entrenamiento = inicio_validacion - SEPARACION
    return {"entrenamiento": (reconstruccion.fechas.min().astype(date), fin_entrenamiento),
            "validacion": (inicio_validacion, fin_validacion),
            "prueba": (inicio_prueba, max(reconstruccion.fechas.max().astype(date),
                                          reales.fechas.max().astype(date) if len(reales) else inicio_prueba))}


def entrenar(reconstruccion: Datos, reales: Datos) -> tuple[Red, dict]:
    t = tramos(reconstruccion, reales)
    entreno = reconstruccion.tramo(*t["entrenamiento"])
    valid = reconstruccion.tramo(*t["validacion"])
    prueba_recon = reconstruccion.tramo(*t["prueba"])

    candidatas = []
    for configuracion in CONFIGURACIONES:
        red = entrenar_red(entreno.x, entreno.y, configuracion)
        candidatas.append((auc(valid.y, red.puntuar(valid.x)), configuracion, red))
    auc_valid, configuracion, red = max(candidatas, key=lambda c: c[0])
    p_valid = red.puntuar(valid.x)
    red.umbral = elegir_umbral(valid.y, p_valid)
    logistica = entrenar_logistica(entreno.x, entreno.y)

    informe: dict = {"tramos": {k: [a.isoformat(), b.isoformat()] for k, (a, b) in t.items()},
                     "configuracion": {k: list(v) if isinstance(v, tuple) else v for k, v in configuracion.items()},
                     "configuraciones_probadas": [{"configuracion": str(c), "auc_validacion": round(a, 4)}
                                                  for a, c, _ in candidatas],
                     "umbral": red.umbral, "precision_minima": PRECISION_MINIMA, "evaluacion": {}}
    for nombre, datos in (("entrenamiento", entreno), ("validacion", valid), ("prueba: reconstrucción", prueba_recon),
                          ("prueba: listas reales", reales)):
        if not len(datos):
            continue
        p = red.puntuar(datos.x)
        informe["evaluacion"][nombre] = {
            "filas": len(datos), "llegaron": int(datos.y.sum()), "base": float(datos.y.mean()),
            "monedas_que_llegaron": int(len(np.unique(datos.monedas[datos.y == 1]))),
            "auc_red": auc(datos.y, p), "auc_logistica": auc(datos.y, logistica(datos.x)),
            "mejor_del_dia_red": mejor_del_dia(datos, p), "mejor_del_dia_logistica": mejor_del_dia(datos, logistica(datos.x)),
            "umbral": resumen_umbral(datos, p, red.umbral),
        }
    informe["importancias"] = [[n, round(v, 4)] for n, v in importancias(red, valid)[:15]]
    return red, informe


def _pct(v: float) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.1f} %"


def _num(v: float) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.3f}"


def informe_markdown(informe: dict) -> str:
    t = informe["tramos"]
    lineas = ["# Informe de la red", "",
              f"- Entrenamiento: {t['entrenamiento'][0]} a {t['entrenamiento'][1]} (reconstrucción).",
              f"- Validación: {t['validacion'][0]} a {t['validacion'][1]} (reconstrucción).",
              f"- Prueba: desde {t['prueba'][0]} (listas reales y, para comparar, la reconstrucción de esos días).",
              f"- Red elegida: capas {informe['configuracion']['hidden_layer_sizes']}, "
              f"alpha {informe['configuracion']['alpha']}.",
              "- Umbral: " + (f"{informe['umbral']:.3f} (al menos 3 de cada 10 llegaron en la validación)."
                              if informe["umbral"] is not None else
                              "ninguno: en la validación ningún umbral llegó a 3 de cada 10, así que la red no "
                              "muestra monedas."), "",
              "| Tramo | Filas | Llegaron | Al azar | AUC red | AUC logística | Mejor del día (red) | "
              "Mostradas | Llegaron de las mostradas | Días con lista |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for nombre, e in informe["evaluacion"].items():
        u = e["umbral"]
        lineas.append(f"| {nombre} | {e['filas']} | {e['llegaron']} ({e['monedas_que_llegaron']} monedas) | "
                      f"{_pct(e['base'])} | {_num(e['auc_red'])} | {_num(e['auc_logistica'])} | "
                      f"{_pct(e['mejor_del_dia_red'])} | {u['mostradas']} | "
                      f"{u['llegaron']} ({_pct(u['precision'])}) | {u['dias_con_lista']} de {u['dias']} |")
    lineas += ["", "AUC: probabilidad de que una moneda que llegó a +50 % puntúe más que una que no (0,5 = al azar).",
               "Mejor del día: de la moneda mejor puntuada de cada día, qué parte llegó.", "",
               "## Señales en las que más se apoya la red", "",
               "Cuánto baja el AUC de la validación al desordenar cada señal.", "",
               "| Señal | Caída del AUC |", "|---|---:|"]
    lineas += [f"| `{n}` | {v:.4f} |" for n, v in informe["importancias"]]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Entrena la red y escribe modelo/red.json y modelo/INFORME.md.")
    parser.add_argument("--reconstruccion", type=Path, default=RECONSTRUCCION)
    parser.add_argument("--modelo", type=Path, default=MODELO)
    parser.add_argument("--informe", type=Path, default=INFORME)
    args = parser.parse_args(argv)

    reconstruccion = leer_reconstruccion(args.reconstruccion)
    reales = leer_reales()
    print(f"Reconstrucción: {len(reconstruccion)} filas; listas reales: {len(reales)}", file=sys.stderr)
    red, informe = entrenar(reconstruccion, reales)
    red.guardar(args.modelo, {"informe": informe})
    texto = informe_markdown(informe)
    args.informe.parent.mkdir(parents=True, exist_ok=True)
    args.informe.write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
