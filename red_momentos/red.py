"""Red neuronal: aprende qué candidatas llegan a +50 % en 10 días, y cuáles caen −20 % sin llegar.

**Datos.** La reconstrucción desde 2023 (``datos/reconstruccion/filas.csv.gz``) y las listas reales
(``datos/etiquetas.csv`` con ``datos/senales.csv``). Solo entran las filas con resultado final y señales
completas de los días cuyos 10 días ya terminaron: en un día que todavía tiene candidatas pendientes, las únicas
con resultado son las que ya llegaron a +50 %, y contarlas haría creer que llegaron más de las que de verdad
llegan.

**Qué muestra.** Las ``POR_DIA`` (3) candidatas mejor puntuadas de cada día. No usa un umbral fijo: la
puntuación de una red entrenada con otros datos cambia de escala y un umbral elegido con una red dejaba sin
lista a la otra (del 21 de octubre al 4 de noviembre de 2026 no mostró ninguna moneda).

**Cortes en el tiempo.** Cada modelo candidato se entrena con todo lo anterior a cada corte (con 11 días de
separación, lo que dura la etiqueta) y se mide en los 90 días siguientes, en ``CORTES`` (6) cortes antes de la
prueba. Se queda el que más acierta con las 3 mejores de cada día (media de los cortes), que es lo que se ve en
la web; el AUC solo desempata.

**Prueba.** Los últimos 90 días, o desde el inicio de las listas reales mientras lleven menos; se mide con las
listas reales (y, para comparar, con la reconstrucción de esos días), con el modelo entrenado solo con lo
anterior. Cada cifra lleva su margen (intervalo del 90 % remuestreando días).

**Modelos candidatos.** Un perceptrón multicapa (64 y 32 neuronas, media de 3 redes con distinta semilla),
una regresión logística y árboles de gradiente (``HistGradientBoostingClassifier``). Con las mismas señales.

**Señales.** Las de ``senales.SENALES`` (menos ``EXCLUIDAS``) y tres más que dicen si hay libro, métricas y si
es futuros. Cada señal se pasa a su posición entre los valores del entrenamiento (de 0 a 1, por cuantiles), así
los valores extremos no pesan de más; un dato que falta queda en 0,5 y lo marca su indicador. La posición de cada
moneda entre las candidatas de su día se probó y no mejoró las 3 mejores (``analisis/mejoras-de-la-red.md``).

**Pesos.** Una moneda que sale muchos días seguidos en las listas es casi siempre la misma subida (o la misma
caída) contada varias veces. Cada fila pesa ``1/√n``, con ``n`` los días de su racha (días seguidos de la misma
moneda en las listas, con huecos de hasta 2 días).

**Riesgo.** Un segundo modelo, del mismo tipo, aprende qué candidatas caen −20 % en los 10 días sin llegar a
+50 %. Las mismas señales que anuncian subidas anuncian caídas: de las 3 mejores de cada día, ~4 de cada 10
caían −20 % sin llegar. El riesgo se muestra al lado de cada moneda, pero no cambia el orden
(``RIESGO_PESO`` = 0): en los cortes, ordenar por ``puntuación × (1 − riesgo)`` bajaba las caídas de las 3
mejores del 40 al 38 % y también las que llegaban, del 18,8 al 17,6 % (``analisis/mejoras-de-la-red.md``).

**Modelo final.** Elegido el tipo, el que se usa cada día se entrena con todo lo que ya tiene resultado
(también la prueba), así aprende de los últimos resultados. Las cifras del informe son las de los modelos que no
habían visto esos días.

El modelo se guarda en ``modelo/red.json`` (cuantiles, pesos y árboles) y la predicción se hace con numpy, así
no depende de la versión de scikit-learn. ``modelo/INFORME.md`` resume los resultados.

    python -m red_momentos.red
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import etiquetas, senales

POR_DIA = 3  # monedas que muestra cada día
CAIDA = -20.0  # % del mínimo que cuenta como caída
RIESGO_PESO = 0.0  # cuánto baja el orden el riesgo: puntuación × (1 − RIESGO_PESO × riesgo)
SEPARACION = np.timedelta64(etiquetas.VENTANA + 1, "D")
CORTES = 6
VENTANA_CORTE = np.timedelta64(90, "D")
PRUEBA = np.timedelta64(90, "D")
CUANTILES = 101
RACHA_HUECO = 2  # días sin salir que todavía cuentan como la misma racha
INTERVALO = 0.90
REMUESTREOS = 1000
INDICADORES = ["tiene_libro", "tiene_metricas", "es_futuros"]
# Binance publica la banda de ±0,2 % del libro solo desde enero de 2026: en el entrenamiento casi siempre
# falta y en la validación casi nunca, así que la red aprendería la fecha y no la señal.
EXCLUIDAS = {"libro_deseq_02"}
ENTRADAS = [k for k in senales.SENALES if k not in EXCLUIDAS] + INDICADORES
CANDIDATOS = {
    "red": {"tipo": "capas", "hidden_layer_sizes": (64, 32), "alpha": 0.1, "max_iter": 20, "semillas": 3},
    "logistica": {"tipo": "logistica", "C": 1.0},
    "arboles": {"tipo": "arboles", "max_iter": 200, "learning_rate": 0.05, "max_leaf_nodes": 7,
                "min_samples_leaf": 300, "l2_regularization": 1.0},
}
RECONSTRUCCION = Path("datos/reconstruccion/filas.csv.gz")
MODELO = Path("modelo/red.json")
INFORME = Path("modelo/INFORME.md")


@dataclass
class Datos:
    fechas: np.ndarray  # datetime64[D]
    monedas: np.ndarray
    x: np.ndarray  # señales en bruto (NaN si faltan)
    y: np.ndarray  # 1 si llegó a +50 %
    caida: np.ndarray = field(default=None)  # 1 si cayó −20 % sin llegar a +50 %

    def __post_init__(self) -> None:
        if self.caida is None:
            self.caida = np.zeros(len(self.y))

    def __len__(self) -> int:
        return len(self.y)

    def filtrar(self, filtro: np.ndarray) -> "Datos":
        return Datos(self.fechas[filtro], self.monedas[filtro], self.x[filtro], self.y[filtro], self.caida[filtro])

    def tramo(self, desde=None, hasta=None) -> "Datos":
        filtro = np.ones(len(self), dtype=bool)
        if desde is not None:
            filtro &= self.fechas >= np.datetime64(desde, "D")
        if hasta is not None:
            filtro &= self.fechas <= np.datetime64(hasta, "D")
        return self.filtrar(filtro)


def _valor(texto: str) -> float:
    return float(texto) if texto not in ("", None) else math.nan


def matriz(filas: list[dict], entradas: Optional[list[str]] = None) -> np.ndarray:
    """Las entradas del modelo de cada fila con señales (strings del CSV): ``ENTRADAS`` o, al puntuar con un modelo
    guardado, las suyas (``Red.entradas``), así un modelo entrenado con otras señales sigue funcionando."""
    entradas = ENTRADAS if entradas is None else entradas
    x = np.array([[_valor(f.get(k, "")) for k in senales.SENALES] for f in filas], dtype=float).reshape(-1, len(senales.SENALES))
    libro = [senales.SENALES.index(k) for k in senales.LIBRO if k not in EXCLUIDAS]
    columnas = {
        "tiene_libro": (~np.isnan(x[:, libro])).any(axis=1).astype(float),
        "tiene_metricas": (~np.isnan(x[:, [senales.SENALES.index(k) for k in senales.METRICAS]])).any(axis=1).astype(float),
        "es_futuros": np.array([f["mercado"] == "futures" for f in filas], dtype=float),
    }
    return np.column_stack([columnas[k] if k in columnas else x[:, senales.SENALES.index(k)]
                            for k in entradas]).reshape(len(filas), len(entradas))


def a_datos(filas: list[dict]) -> Datos:
    """Filas con ``estado`` y las señales (strings del CSV) → matrices. Solo las finales y completas de los días sin
    candidatas pendientes."""
    abiertos = {f["fecha"] for f in filas if f.get("estado") == "pendiente"}
    filas = [f for f in filas if f["fecha"] not in abiertos]
    x = matriz(filas)
    utiles = np.array([f.get("estado") in etiquetas.FINALES and f.get("completa") == "1" for f in filas], dtype=bool)
    y = np.array([f.get("estado") == "llego" for f in filas], dtype=float)
    minimo = np.array([_valor(f.get("pct_minimo", "")) for f in filas], dtype=float).reshape(-1)
    caida = ((minimo <= CAIDA) & (y == 0)).astype(float)
    return Datos(np.array([f["fecha"] for f in filas], dtype="datetime64[D]")[utiles],
                 np.array([f["moneda"] for f in filas]).reshape(-1)[utiles], x[utiles], y[utiles], caida[utiles])


def leer_reconstruccion(ruta: Path = RECONSTRUCCION) -> Datos:
    with gzip.open(ruta, "rt", encoding="utf-8", newline="") as fh:
        return a_datos(list(csv.DictReader(fh)))


def leer_reales(etiquetas_csv: Path = etiquetas.SALIDA, senales_csv: Path = senales.SALIDA) -> Datos:
    sen = senales.leer_csv(senales_csv)
    filas = []
    for clave, fila in etiquetas.leer_csv(etiquetas_csv).items():
        if clave in sen:
            filas.append({**sen[clave], "estado": fila["estado"], "pct_minimo": fila.get("pct_minimo", "")})
        elif fila["estado"] == "pendiente":
            filas.append({"fecha": fila["fecha"], "moneda": fila["moneda"], "mercado": fila["mercado"],
                          "estado": "pendiente"})
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


# --- Modelos en numpy ----------------------------------------------------------------------------------

def _sigmoide(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def _puntuar_capas(miembro: dict, entrada: np.ndarray) -> np.ndarray:
    a = entrada
    for w, b in zip(miembro["pesos"][:-1], miembro["sesgos"][:-1]):
        a = np.maximum(a @ w + b, 0)
    return _sigmoide((a @ miembro["pesos"][-1] + miembro["sesgos"][-1]).ravel())


def _puntuar_arboles(miembro: dict, entrada: np.ndarray) -> np.ndarray:
    total = np.full(len(entrada), float(miembro["base"]))
    filas = np.arange(len(entrada))
    for arbol in miembro["arboles"]:
        nodo = np.zeros(len(entrada), dtype=int)
        while True:
            internos = ~arbol["hoja"][nodo]
            if not internos.any():
                break
            n = nodo[internos]
            valor = entrada[filas[internos], arbol["variable"][n]]
            izquierda = np.where(np.isnan(valor), arbol["falta_izq"][n], valor <= arbol["corte"][n])
            nodo[internos] = np.where(izquierda, arbol["izq"][n], arbol["der"][n])
        total += arbol["valor"][nodo]
    return _sigmoide(total)


@dataclass
class Modelo:
    """Uno o varios miembros (redes con distinta semilla, una logística o unos árboles); la puntuación es la media."""
    miembros: list[dict]

    def puntuar(self, entrada: np.ndarray) -> np.ndarray:
        total = np.zeros(len(entrada))
        for m in self.miembros:
            total += _puntuar_capas(m, entrada) if m["tipo"] == "capas" else _puntuar_arboles(m, entrada)
        return total / len(self.miembros)

    def a_json(self) -> dict:
        def miembro(m: dict) -> dict:
            if m["tipo"] == "capas":
                return {"tipo": "capas", "pesos": [np.round(w, 8).tolist() for w in m["pesos"]],
                        "sesgos": [np.round(b, 8).tolist() for b in m["sesgos"]]}
            return {"tipo": "arboles", "base": float(m["base"]),
                    "arboles": [{k: v.tolist()
                                 for k, v in a.items()} for a in m["arboles"]]}
        return {"miembros": [miembro(m) for m in self.miembros]}

    @classmethod
    def de_json(cls, d: dict) -> "Modelo":
        miembros = []
        for m in d["miembros"]:
            if m["tipo"] == "capas":
                miembros.append({"tipo": "capas", "pesos": [np.array(w) for w in m["pesos"]],
                                 "sesgos": [np.array(b) for b in m["sesgos"]]})
            else:
                tipos = {"variable": int, "corte": float, "falta_izq": bool, "izq": int, "der": int, "hoja": bool,
                         "valor": float}
                miembros.append({"tipo": "arboles", "base": m["base"],
                                 "arboles": [{k: np.array(a[k], dtype=t) for k, t in tipos.items()} for a in m["arboles"]]})
        return cls(miembros)


@dataclass
class Red:
    """Lo necesario para predecir sin scikit-learn: cuantiles, el modelo de +50 %, el de riesgo y cuántas mostrar.

    ``umbral`` solo lo tienen los modelos antiguos (``redes`` en el JSON), que mostraban las que lo pasaban.
    """
    cuantiles: Cuantiles
    modelo: Modelo
    entradas: list[str]
    riesgo: Optional[Modelo] = None
    por_dia: Optional[int] = POR_DIA
    umbral: Optional[float] = None
    riesgo_peso: float = RIESGO_PESO

    def puntuar(self, x: np.ndarray) -> np.ndarray:
        return self.modelo.puntuar(self.cuantiles.aplicar(x))

    def puntuar_riesgo(self, x: np.ndarray) -> Optional[np.ndarray]:
        return None if self.riesgo is None else self.riesgo.puntuar(self.cuantiles.aplicar(x))

    def orden(self, puntos: np.ndarray, riesgo: Optional[np.ndarray]) -> np.ndarray:
        """Valor por el que se ordenan las candidatas del día (más = mejor)."""
        return puntos if riesgo is None or not self.riesgo_peso else puntos * (1 - self.riesgo_peso * riesgo)

    def mostrar(self, puntos: np.ndarray, riesgo: Optional[np.ndarray] = None) -> np.ndarray:
        """Cuáles muestra de las candidatas de un día: las ``por_dia`` primeras por ``orden`` (o, en un modelo
        antiguo, las que pasan el umbral)."""
        puntos = np.asarray(puntos, dtype=float)
        if self.por_dia is None:
            return puntos >= self.umbral if self.umbral is not None else np.zeros(len(puntos), dtype=bool)
        elegidas = np.zeros(len(puntos), dtype=bool)
        elegidas[np.argsort(-self.orden(puntos, riesgo), kind="stable")[:self.por_dia]] = True
        return elegidas

    def guardar(self, ruta: Path, extra: dict) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({
            "entradas": self.entradas, "por_dia": self.por_dia, "umbral": self.umbral,
            "riesgo_peso": self.riesgo_peso, "cuantiles": self.cuantiles.puntos.tolist(),
            "modelo": self.modelo.a_json(), "riesgo": self.riesgo.a_json() if self.riesgo else None, **extra,
        }, ensure_ascii=False))

    @classmethod
    def cargar(cls, ruta: Path = MODELO) -> "Red":
        d = json.loads(ruta.read_text())
        cuantiles = Cuantiles(np.array(d["cuantiles"]))
        if "redes" in d:  # formato antiguo: solo redes y un umbral
            modelo = Modelo([{"tipo": "capas", "pesos": [np.array(w) for w in r["pesos"]],
                              "sesgos": [np.array(b) for b in r["sesgos"]]} for r in d["redes"]])
            return cls(cuantiles, modelo, d["entradas"], None, None, d.get("umbral"))
        return cls(cuantiles, Modelo.de_json(d["modelo"]), d["entradas"],
                   Modelo.de_json(d["riesgo"]) if d.get("riesgo") else None, d.get("por_dia"), d.get("umbral"),
                   d.get("riesgo_peso", RIESGO_PESO))


# --- Entrenamiento de un modelo ------------------------------------------------------------------------

def pesos_por_racha(fechas: np.ndarray, monedas: np.ndarray) -> np.ndarray:
    """``1/√n`` con ``n`` los días de la racha de cada fila (días seguidos de la misma moneda, con huecos de hasta
    ``RACHA_HUECO`` días). Normalizados para que sumen el número de filas."""
    if not len(fechas):
        return np.ones(0)
    orden = np.lexsort((fechas, monedas))
    f, m = fechas[orden], monedas[orden]
    nueva = np.ones(len(orden), dtype=bool)
    nueva[1:] = (m[1:] != m[:-1]) | ((f[1:] - f[:-1]) > np.timedelta64(RACHA_HUECO, "D"))
    grupo_ordenado = np.cumsum(nueva) - 1
    grupo = np.empty(len(orden), dtype=int)
    grupo[orden] = grupo_ordenado
    pesos = 1 / np.sqrt(np.bincount(grupo)[grupo])
    return pesos * len(pesos) / pesos.sum()


def _exportar_arboles(modelo) -> dict:
    """Los árboles de un ``HistGradientBoostingClassifier`` binario, para puntuar con numpy."""
    arboles = []
    for (predictor,) in modelo._predictors:
        n = predictor.nodes
        arboles.append({"variable": n["feature_idx"].astype(int), "corte": n["num_threshold"].astype(float),
                        "falta_izq": n["missing_go_to_left"].astype(bool), "izq": n["left"].astype(int),
                        "der": n["right"].astype(int), "hoja": n["is_leaf"].astype(bool),
                        "valor": n["value"].astype(float)})
    return {"tipo": "arboles", "base": float(np.ravel(modelo._baseline_prediction)[0]), "arboles": arboles}


def ajustar(entrada: np.ndarray, y: np.ndarray, configuracion: dict, pesos: Optional[np.ndarray] = None) -> Modelo:
    """Entrena un modelo con las entradas ya pasadas por los cuantiles.

    La red no usa parada temprana: la de scikit-learn mira la exactitud, que apenas cambia cuando solo el 5 % llega
    a +50 %, y cortaba el entrenamiento a las pocas épocas. Se para a propósito en ``max_iter`` épocas.
    """
    tipo = configuracion["tipo"]
    y = y.astype(int)
    if tipo == "capas":
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.neural_network import MLPClassifier

        miembros = []
        for semilla in range(configuracion.get("semillas", 1)):
            modelo = MLPClassifier(activation="relu", solver="adam", batch_size=512, learning_rate_init=1e-3,
                                   early_stopping=False, tol=0, n_iter_no_change=10**6, random_state=semilla,
                                   hidden_layer_sizes=configuracion["hidden_layer_sizes"],
                                   alpha=configuracion["alpha"], max_iter=configuracion["max_iter"])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                modelo.fit(entrada, y, sample_weight=pesos)
            miembros.append({"tipo": "capas", "pesos": list(modelo.coefs_), "sesgos": list(modelo.intercepts_)})
        return Modelo(miembros)
    if tipo == "logistica":
        from sklearn.linear_model import LogisticRegression

        modelo = LogisticRegression(max_iter=2000, C=configuracion["C"]).fit(entrada, y, sample_weight=pesos)
        return Modelo([{"tipo": "capas", "pesos": [modelo.coef_.T.copy()], "sesgos": [modelo.intercept_.copy()]}])
    if tipo == "arboles":
        from sklearn.ensemble import HistGradientBoostingClassifier

        parametros = {k: v for k, v in configuracion.items() if k != "tipo"}
        modelo = HistGradientBoostingClassifier(early_stopping=False, random_state=0, **parametros)
        modelo.fit(entrada, y, sample_weight=pesos)
        return Modelo([_exportar_arboles(modelo)])
    raise ValueError(f"tipo de modelo desconocido: {tipo}")


def entrenar_red(datos: Datos, configuracion: dict, con_riesgo: bool = True) -> Red:
    """Cuantiles, el modelo de +50 % y (si ``con_riesgo``) el de caída, con los pesos por racha."""
    cuantiles = Cuantiles.ajustar(datos.x)
    entrada = cuantiles.aplicar(datos.x)
    pesos = pesos_por_racha(datos.fechas, datos.monedas)
    modelo = ajustar(entrada, datos.y, configuracion, pesos)
    riesgo = ajustar(entrada, datos.caida, configuracion, pesos) if con_riesgo and 0 < datos.caida.sum() < len(datos) else None
    return Red(cuantiles, modelo, ENTRADAS, riesgo)


# --- Medidas --------------------------------------------------------------------------------------------

def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Probabilidad de que una que llegó puntúe más que una que no (0,5 = al azar)."""
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else math.nan


def elegidas_por_dia(fechas: np.ndarray, orden: np.ndarray, k: int = POR_DIA) -> np.ndarray:
    """Las ``k`` primeras de cada día por ``orden`` (más = mejor)."""
    elegidas = np.zeros(len(fechas), dtype=bool)
    for dia in np.unique(fechas):
        filas = np.flatnonzero(fechas == dia)
        elegidas[filas[np.argsort(-orden[filas], kind="stable")[:k]]] = True
    return elegidas


def _por_dia(fechas: np.ndarray, valores: np.ndarray, elegidas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Por día: suma de ``valores`` de las elegidas y cuántas se eligieron."""
    dias, indice = np.unique(fechas, return_inverse=True)
    return (np.bincount(indice, weights=valores * elegidas, minlength=len(dias)),
            np.bincount(indice, weights=elegidas.astype(float), minlength=len(dias)))


def intervalo(fechas: np.ndarray, valores: np.ndarray, elegidas: np.ndarray, semilla: int = 0) -> tuple[float, float]:
    """Intervalo del ``INTERVALO`` de la proporción de ``valores`` entre las elegidas, remuestreando días."""
    suma, cuantas = _por_dia(fechas, valores, elegidas)
    if cuantas.sum() == 0 or len(cuantas) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(semilla)
    muestras = rng.integers(0, len(cuantas), size=(REMUESTREOS, len(cuantas)))
    total = cuantas[muestras].sum(axis=1)
    proporciones = suma[muestras].sum(axis=1)[total > 0] / total[total > 0]
    cola = (1 - INTERVALO) / 2
    return float(np.quantile(proporciones, cola)), float(np.quantile(proporciones, 1 - cola))


def medir(datos: Datos, red: Red) -> dict:
    """Cómo acierta ``red`` con ``datos``: AUC de las dos puntuaciones y qué pasó con las que mostraría cada día."""
    p = red.puntuar(datos.x)
    r = red.puntuar_riesgo(datos.x)
    elegidas = elegidas_por_dia(datos.fechas, red.orden(p, r))
    primera = elegidas_por_dia(datos.fechas, red.orden(p, r), 1)
    n = int(elegidas.sum())
    return {
        "filas": len(datos), "dias": int(len(np.unique(datos.fechas))), "llegaron": int(datos.y.sum()),
        "base": float(datos.y.mean()) if len(datos) else math.nan,
        "base_caida": float(datos.caida.mean()) if len(datos) else math.nan,
        "monedas_que_llegaron": int(len(np.unique(datos.monedas[datos.y == 1]))),
        "auc": auc(datos.y, p), "auc_riesgo": auc(datos.caida, r) if r is not None else math.nan,
        "mostradas": n, "llegaron_mostradas": int(datos.y[elegidas].sum()),
        "precision": float(datos.y[elegidas].mean()) if n else math.nan,
        "precision_intervalo": intervalo(datos.fechas, datos.y, elegidas),
        "caida_mostradas": float(datos.caida[elegidas].mean()) if n else math.nan,
        "caida_intervalo": intervalo(datos.fechas, datos.caida, elegidas),
        "primera": float(datos.y[primera].mean()) if primera.any() else math.nan,
    }


def importancias(red: Red, datos: Datos, repeticiones: int = 3, semilla: int = 0) -> list[tuple[str, float]]:
    """Cuánto baja el AUC al desordenar cada señal (más = el modelo se apoya más en ella)."""
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

def unir(reconstruccion: Datos, reales: Datos) -> Datos:
    """Las dos fuentes juntas; si una moneda y día está en las dos, queda la real."""
    vistas = set(zip(reales.fechas.tolist(), reales.monedas.tolist()))
    quedan = np.array([(f, m) not in vistas for f, m in zip(reconstruccion.fechas.tolist(),
                                                            reconstruccion.monedas.tolist())], dtype=bool)
    r = reconstruccion.filtrar(quedan)
    return Datos(np.concatenate([r.fechas, reales.fechas]), np.concatenate([r.monedas, reales.monedas]),
                 np.vstack([r.x, reales.x]), np.concatenate([r.y, reales.y]), np.concatenate([r.caida, reales.caida]))


def tramos(reconstruccion: Datos, reales: Datos) -> dict:
    """Prueba: los últimos 90 días (o desde el inicio de las listas reales, si llevan menos). Antes, ``CORTES``
    tramos de 90 días para elegir el modelo, cada uno con 11 días de separación con lo que se usa para entrenarlo."""
    fin = reconstruccion.fechas.max()
    if len(reales):
        fin = max(fin, reales.fechas.max())
    inicio_prueba = fin - PRUEBA
    if len(reales):
        inicio_prueba = max(inicio_prueba, reales.fechas.min())
    cortes = []
    fin_corte = inicio_prueba - SEPARACION
    for _ in range(CORTES):
        inicio = fin_corte - VENTANA_CORTE + np.timedelta64(1, "D")
        cortes.append((inicio, fin_corte))
        fin_corte = inicio - np.timedelta64(1, "D")
    a_fecha = lambda d: d.astype(date)
    return {"prueba": (a_fecha(inicio_prueba), a_fecha(fin)),
            "cortes": [(a_fecha(a), a_fecha(b)) for a, b in reversed(cortes)]}


def _antes(datos: Datos, inicio: date) -> Datos:
    return datos.tramo(hasta=np.datetime64(inicio, "D") - SEPARACION)


def elegir(todo: Datos, cortes: list[tuple[date, date]], candidatos: dict = CANDIDATOS,
           aviso: Callable[[str], None] = lambda texto: None) -> tuple[str, dict]:
    """Mide cada candidato en cada corte (entrenado solo con lo anterior) y elige el que más acierta con las que
    mostraría cada día (media de los cortes); el AUC desempata."""
    resultados = {}
    for nombre, configuracion in candidatos.items():
        por_corte = []
        for inicio, fin in cortes:
            entreno, ventana = _antes(todo, inicio), todo.tramo(inicio, fin)
            if not len(ventana) or not 0 < entreno.y.sum() < len(entreno):
                continue
            red = entrenar_red(entreno, configuracion)
            por_corte.append({"desde": inicio.isoformat(), "hasta": fin.isoformat(), **medir(ventana, red)})
        resultados[nombre] = {
            "cortes": por_corte,
            "precision": float(np.nanmean([c["precision"] for c in por_corte])) if por_corte else math.nan,
            "auc": float(np.nanmean([c["auc"] for c in por_corte])) if por_corte else math.nan,
            "caida_mostradas": float(np.nanmean([c["caida_mostradas"] for c in por_corte])) if por_corte else math.nan,
        }
        aviso(f"{nombre}: aciertos de las {POR_DIA} mejores {resultados[nombre]['precision']:.3f}, "
              f"AUC {resultados[nombre]['auc']:.3f}")
    validos = [n for n in resultados if not math.isnan(resultados[n]["precision"])]
    if not validos:
        return next(iter(candidatos)), resultados
    mejor = max(validos, key=lambda n: (round(resultados[n]["precision"], 3), resultados[n]["auc"]))
    return mejor, resultados


def entrenar(reconstruccion: Datos, reales: Datos, candidatos: dict = CANDIDATOS,
             aviso: Callable[[str], None] = lambda texto: None) -> tuple[Red, dict]:
    t = tramos(reconstruccion, reales)
    todo = unir(reconstruccion, reales)
    inicio_prueba, fin_prueba = t["prueba"]
    # Para elegir y medir, solo lo anterior a la prueba (también las listas reales de esos días).
    previo = todo.tramo(hasta=np.datetime64(inicio_prueba, "D") - SEPARACION)
    nombre, comparacion = elegir(previo, t["cortes"], candidatos, aviso)
    configuracion = candidatos[nombre]

    red = entrenar_red(_antes(todo, inicio_prueba), configuracion)
    informe: dict = {"tramos": {"prueba": [inicio_prueba.isoformat(), fin_prueba.isoformat()],
                                "cortes": [[a.isoformat(), b.isoformat()] for a, b in t["cortes"]]},
                     "modelo": nombre,
                     "configuracion": {k: list(v) if isinstance(v, tuple) else v for k, v in configuracion.items()},
                     "comparacion": comparacion, "por_dia": POR_DIA, "caida": CAIDA, "riesgo_peso": RIESGO_PESO,
                     "evaluacion": {}}
    for etiqueta, datos in (("prueba: reconstrucción", reconstruccion.tramo(inicio_prueba, fin_prueba)),
                            ("prueba: listas reales", reales.tramo(inicio_prueba, fin_prueba))):
        if len(datos):
            informe["evaluacion"][etiqueta] = medir(datos, red)
    ultimo = t["cortes"][-1]
    ventana = previo.tramo(*ultimo)
    if len(ventana) and 0 < ventana.y.sum() < len(ventana):
        red_corte = entrenar_red(_antes(previo, ultimo[0]), configuracion, con_riesgo=False)
        informe["importancias"] = [[n, round(v, 4)] for n, v in importancias(red_corte, ventana)[:15]]
        informe["importancias_tramo"] = [ultimo[0].isoformat(), ultimo[1].isoformat()]

    # El modelo que se usa cada día, con la misma configuración y todo lo que ya tiene resultado (también la
    # prueba, con tus listas reales): así aprende de los últimos resultados.
    final = entrenar_red(todo, configuracion)
    informe["datos_hasta"] = todo.fechas.max().astype(date).isoformat()
    informe["filas_red_final"] = len(todo)
    informe["entrenada"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return final, informe


# --- Informe --------------------------------------------------------------------------------------------

def _pct(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.1f} %"


def _num(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.3f}"


def _margen(par) -> str:
    if not par or any(v is None or math.isnan(v) for v in par):
        return ""
    return f" ({par[0] * 100:.0f}-{par[1] * 100:.0f} %)"


NOMBRES = {"red": "red neuronal (64 y 32 neuronas)", "logistica": "regresión logística", "arboles": "árboles de gradiente"}


def informe_markdown(informe: dict) -> str:
    t = informe["tramos"]
    k = informe.get("por_dia", POR_DIA)
    lineas = ["# Informe de la red", "",
              f"- Muestra las **{k} mejores de cada día**, ordenadas por "
              + (f"puntuación × (1 − {informe['riesgo_peso']:g} × riesgo)." if informe.get("riesgo_peso") else
                 "puntuación; el riesgo de caída se muestra al lado, sin cambiar el orden."),
              f"- Modelo elegido: **{NOMBRES.get(informe['modelo'], informe['modelo'])}** "
              f"(el que más acertó con las {k} mejores de cada día en {len(t['cortes'])} cortes de 90 días, "
              f"del {t['cortes'][0][0]} al {t['cortes'][-1][1]}).",
              f"- Prueba: {t['prueba'][0]} a {t['prueba'][1]} (listas reales y, para comparar, la reconstrucción de esos "
              "días), con el modelo entrenado solo con lo anterior.",
              f"- Riesgo: un segundo modelo del mismo tipo puntúa la probabilidad de caer −{abs(informe.get('caida', CAIDA)):g} % "
              "en los 10 días sin llegar a +50 %."]
    if informe.get("datos_hasta"):
        lineas.append(f"- Modelo que se usa cada día: el mismo tipo, entrenado otra vez con todo lo que ya tiene "
                      f"resultado (hasta el {informe['datos_hasta']}, {informe['filas_red_final']} filas). Las cifras "
                      "de abajo son las de los modelos que no habían visto esos días.")
    lineas += ["", "## Comparación en los cortes", "",
               f"Media de los cortes. Entre paréntesis, el intervalo del {INTERVALO * 100:.0f} % (remuestreando días).",
               "", f"| Modelo | AUC | Llegaron de las {k} mejores | Cayeron −20 % sin llegar de las {k} mejores |",
               "|---|---:|---:|---:|"]
    for nombre, c in informe["comparacion"].items():
        marca = " (elegido)" if nombre == informe["modelo"] else ""
        lineas.append(f"| {NOMBRES.get(nombre, nombre)}{marca} | {_num(c['auc'])} | {_pct(c['precision'])} | "
                      f"{_pct(c['caida_mostradas'])} |")
    elegido = informe["comparacion"].get(informe["modelo"], {}).get("cortes", [])
    if elegido:
        lineas += ["", "Modelo elegido, corte por corte:", "",
                   _CABECERA.format(k=k), "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for c in elegido:
            lineas.append(_fila_medida(f"{c['desde']} a {c['hasta']}", c))
    lineas += ["", "## Prueba", "",
               _CABECERA.format(k=k), "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for nombre, e in informe["evaluacion"].items():
        lineas.append(_fila_medida(nombre, e))
    lineas += ["", "AUC: probabilidad de que una moneda que llegó a +50 % puntúe más que una que no (0,5 = al azar).",
               "Solo cuentan los días cuyos 10 días ya terminaron."]
    if informe.get("importancias"):
        a, b = informe.get("importancias_tramo", ["", ""])
        lineas += ["", "## Señales en las que más se apoya el modelo", "",
                   f"Cuánto baja el AUC del último corte ({a} a {b}) al desordenar cada señal.", "",
                   "| Señal | Caída del AUC |", "|---|---:|"]
        lineas += [f"| `{n}` | {v:.4f} |" for n, v in informe["importancias"]]
    return "\n".join(lineas) + "\n"


_CABECERA = ("| Tramo | Filas | Llegaron (al azar) | AUC | Llegaron de las {k} mejores | La mejor del día llegó | "
             "AUC riesgo | Cayeron −20 % sin llegar, de las {k} mejores | Cayeron −20 % sin llegar, al azar |")


def _fila_medida(nombre: str, e: dict) -> str:
    return (f"| {nombre} | {e['filas']} | {e['llegaron']} ({_pct(e['base'])}) | {_num(e['auc'])} | "
            f"{e['llegaron_mostradas']} de {e['mostradas']}: {_pct(e['precision'])}{_margen(e.get('precision_intervalo'))} | "
            f"{_pct(e['primera'])} | {_num(e.get('auc_riesgo'))} | {_pct(e['caida_mostradas'])}"
            f"{_margen(e.get('caida_intervalo'))} | {_pct(e.get('base_caida'))} |")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Entrena la red y escribe modelo/red.json y modelo/INFORME.md.")
    parser.add_argument("--reconstruccion", type=Path, default=RECONSTRUCCION)
    parser.add_argument("--modelo", type=Path, default=MODELO)
    parser.add_argument("--informe", type=Path, default=INFORME)
    args = parser.parse_args(argv)

    reconstruccion = leer_reconstruccion(args.reconstruccion)
    reales = leer_reales()
    print(f"Reconstrucción: {len(reconstruccion)} filas; listas reales: {len(reales)}", file=sys.stderr)
    red, informe = entrenar(reconstruccion, reales, aviso=lambda texto: print(texto, file=sys.stderr, flush=True))
    red.guardar(args.modelo, {"informe": informe})
    texto = informe_markdown(informe)
    args.informe.parent.mkdir(parents=True, exist_ok=True)
    args.informe.write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
