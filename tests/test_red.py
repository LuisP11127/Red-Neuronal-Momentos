import json
import math
from datetime import date

import numpy as np
import pytest

from red_momentos import red, senales


def test_cuantiles_ordenan_y_manejan_faltantes_y_empates():
    x = np.array([[1.0, 0.0], [2.0, 0.0], [3.0, 1.0], [4.0, 1.0], [np.nan, 1.0]])
    c = red.Cuantiles.ajustar(x)
    t = c.aplicar(np.array([[1.0, 0.0], [2.5, 1.0], [4.0, np.nan], [100.0, 0.0], [-5.0, 0.0]]))
    assert t[0, 0] == 0 and t[2, 0] == 1 and t[3, 0] == 1 and t[4, 0] == 0  # fuera de rango: en los extremos
    assert 0 < t[1, 0] < 1
    assert t[2, 1] == 0.5  # falta: en el medio
    assert t[0, 1] < t[1, 1]  # 0 queda por debajo de 1 aunque haya empates
    assert np.array_equal(c.aplicar(np.array([[np.nan, np.nan]])), [[0.5, 0.5]])


def _problema(n=600, semilla=0):
    rng = np.random.default_rng(semilla)
    x = rng.normal(size=(n, 3))
    y = (x[:, 0] + rng.normal(scale=0.5, size=n) > 0.5).astype(int)
    return x, y


def test_los_modelos_en_numpy_dan_lo_mismo_que_scikit_learn(tmp_path):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier

    x, y = _problema()
    cuantiles = red.Cuantiles.ajustar(x)
    e = cuantiles.aplicar(x)
    # Red: media de dos semillas.
    redes = [MLPClassifier(hidden_layer_sizes=(8, 4), max_iter=2000, random_state=s).fit(e, y) for s in (0, 1)]
    capas = red.Modelo([{"tipo": "capas", "pesos": list(m.coefs_), "sesgos": list(m.intercepts_)} for m in redes])
    assert np.allclose(capas.puntuar(e), np.mean([m.predict_proba(e)[:, 1] for m in redes], axis=0))
    # Logística y árboles, entrenados con ``ajustar``.
    logistica = red.ajustar(e, y, {"tipo": "logistica", "C": 1.0})
    assert np.allclose(logistica.puntuar(e), LogisticRegression(max_iter=2000, C=1.0).fit(e, y).predict_proba(e)[:, 1])
    parametros = {"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 7, "min_samples_leaf": 20,
                  "l2_regularization": 1.0}
    arboles = red.ajustar(e, y, {"tipo": "arboles", **parametros})
    hgb = HistGradientBoostingClassifier(early_stopping=False, random_state=0, **parametros).fit(e, y)
    assert np.allclose(arboles.puntuar(e), hgb.predict_proba(e)[:, 1])
    # Un dato que falta sigue el camino que aprendieron los árboles.
    con_falta = e.copy()
    con_falta[:5, 0] = np.nan
    assert np.allclose(arboles.puntuar(con_falta), hgb.predict_proba(con_falta)[:, 1])

    # Guardar y cargar, con el modelo de riesgo.
    propia = red.Red(cuantiles, arboles, ["a", "b", "c"], riesgo=capas, por_dia=2)
    ruta = tmp_path / "red.json"
    propia.guardar(ruta, {"informe": {}})
    cargada = red.Red.cargar(ruta)
    assert np.allclose(cargada.puntuar(x), propia.puntuar(x), atol=1e-6)
    assert np.allclose(cargada.puntuar_riesgo(x), propia.puntuar_riesgo(x), atol=1e-6)
    assert cargada.por_dia == 2 and cargada.umbral is None and cargada.entradas == ["a", "b", "c"]


def test_carga_el_formato_antiguo_con_umbral(tmp_path):
    from sklearn.neural_network import MLPClassifier

    x, y = _problema()
    cuantiles = red.Cuantiles.ajustar(x)
    m = MLPClassifier(hidden_layer_sizes=(4,), max_iter=2000, random_state=0).fit(cuantiles.aplicar(x), y)
    ruta = tmp_path / "red.json"
    ruta.write_text(json.dumps({"entradas": ["a", "b", "c"], "umbral": 0.5, "cuantiles": cuantiles.puntos.tolist(),
                                "redes": [{"pesos": [w.tolist() for w in m.coefs_],
                                           "sesgos": [b.tolist() for b in m.intercepts_]}]}))
    antigua = red.Red.cargar(ruta)
    p = antigua.puntuar(x)
    assert np.allclose(p, m.predict_proba(cuantiles.aplicar(x))[:, 1], atol=1e-6)
    assert antigua.puntuar_riesgo(x) is None and antigua.por_dia is None
    assert np.array_equal(antigua.mostrar(p), p >= 0.5)


def test_mostrar_las_mejores_del_dia_con_el_riesgo():
    modelo = red.Red(red.Cuantiles(np.zeros((red.CUANTILES, 1))), red.Modelo([]), ["a"], por_dia=2)
    puntos = np.array([0.30, 0.25, 0.20, 0.10])
    assert modelo.mostrar(puntos).tolist() == [True, True, False, False]
    riesgo = np.array([0.1, 0.9, 0.1, 0.1])
    assert modelo.mostrar(puntos, riesgo).tolist() == [True, True, False, False]  # el riesgo solo avisa
    # Si el riesgo cuenta: 0,25 × (1 − 0,9) = 0,025 queda por debajo de 0,20 × (1 − 0,1) = 0,18.
    modelo.riesgo_peso = 1.0
    assert modelo.mostrar(puntos, riesgo).tolist() == [True, False, True, False]
    # Con menos candidatas que ``por_dia``, se muestran todas.
    assert modelo.mostrar(np.array([0.1])).tolist() == [True]


def test_pesos_por_racha():
    fechas = np.array(["2026-01-01", "2026-01-02", "2026-01-04", "2026-01-10", "2026-01-01"], dtype="datetime64[D]")
    monedas = np.array(["A", "A", "A", "A", "B"])
    w = red.pesos_por_racha(fechas, monedas)
    # A: racha de 3 (el hueco de 2 días no la corta) y una suelta; B: suelta.
    crudos = np.array([1 / np.sqrt(3)] * 3 + [1, 1])
    assert np.allclose(w, crudos * 5 / crudos.sum())


def filas_sinteticas(n, inicio, rng, mercado="futures"):
    filas = []
    for i in range(n):
        senal = rng.normal()
        fila = {k: "" for k in senales.SENALES}
        llego = senal + rng.normal(scale=0.7) > 1.6
        cae = not llego and rng.normal() - senal > 0.8
        fila.update({"fecha": str(np.datetime64(inicio) + np.timedelta64(i % 200, "D")), "moneda": f"M{i % 37}",
                     "mercado": mercado, "completa": "1", "vol_rel_1d": f"{senal:.4f}", "rango_1d": f"{rng.normal():.4f}",
                     "libro_deseq_2": "0.5" if i % 2 else "", "estado": "llego" if llego else "no_llego",
                     "pct_minimo": "-25" if cae else "-5"})
        filas.append(fila)
    return filas


def test_a_datos():
    rng = np.random.default_rng(1)
    filas = filas_sinteticas(10, "2026-01-01", rng)
    filas[1]["completa"] = "0"
    filas[2].update({"estado": "no_llego", "pct_minimo": "-30"})
    filas[3].update({"estado": "llego", "pct_minimo": "-30"})
    # Un día con una candidata pendiente: aunque otra ya llegó, el día no cuenta.
    filas += [{**filas[4], "fecha": "2026-03-01", "moneda": "P", "estado": "pendiente"},
              {**filas[4], "fecha": "2026-03-01", "moneda": "Q", "estado": "llego"}]
    datos = red.a_datos(filas)
    assert len(datos) == 9 and datos.x.shape == (9, len(red.ENTRADAS))
    assert "2026-03-01" not in datos.fechas.astype(str).tolist()
    j = red.ENTRADAS.index
    assert set(datos.x[:, j("tiene_libro")]) == {0.0, 1.0}
    assert set(datos.x[:, j("tiene_metricas")]) == {0.0}
    assert set(datos.x[:, j("es_futuros")]) == {1.0}
    # Cae −20 % solo si no llegó a +50 % (la fila 1 es la 2 de ``filas``: la incompleta no entra).
    assert datos.caida[1] == 1 and datos.y[1] == 0
    assert datos.caida[2] == 0 and datos.y[2] == 1


def test_tramos():
    recon = red.Datos(np.array(["2023-01-01", "2026-10-10"], dtype="datetime64[D]"), np.array(["A", "B"]),
                      np.zeros((2, 1)), np.zeros(2))
    reales = red.Datos(np.array(["2026-09-30", "2026-10-12"], dtype="datetime64[D]"), np.array(["A", "B"]),
                       np.zeros((2, 1)), np.zeros(2))
    t = red.tramos(recon, reales)
    assert t["prueba"] == (date(2026, 9, 30), date(2026, 10, 12))  # las listas reales llevan menos de 90 días
    assert len(t["cortes"]) == red.CORTES
    assert t["cortes"][-1] == (date(2026, 6, 22), date(2026, 9, 19))  # 11 días antes de la prueba: la etiqueta dura 10
    for (a, b), (c, d) in zip(t["cortes"], t["cortes"][1:]):
        assert (b - a).days == 89 and (c - b).days == 1  # 90 días seguidos
    # Con más de 90 días de listas reales, la prueba son los últimos 90.
    largas = red.Datos(np.array(["2026-01-01", "2026-10-12"], dtype="datetime64[D]"), np.array(["A", "B"]),
                       np.zeros((2, 1)), np.zeros(2))
    assert red.tramos(recon, largas)["prueba"] == (date(2026, 7, 14), date(2026, 10, 12))


def test_unir_prefiere_la_fila_real():
    recon = red.Datos(np.array(["2026-01-01", "2026-01-02"], dtype="datetime64[D]"), np.array(["A", "A"]),
                      np.array([[1.0], [2.0]]), np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    reales = red.Datos(np.array(["2026-01-02"], dtype="datetime64[D]"), np.array(["A"]), np.array([[9.0]]),
                       np.array([1.0]), np.array([0.0]))
    juntos = red.unir(recon, reales)
    assert juntos.x.ravel().tolist() == [1.0, 9.0] and juntos.y.tolist() == [0.0, 1.0]
    assert juntos.caida.tolist() == [0.0, 0.0]


def test_intervalo_remuestreando_dias():
    fechas = np.repeat(np.arange(30), 3)
    y = np.tile([1.0, 0.0, 0.0], 30)
    elegidas = np.ones(len(y), dtype=bool)
    bajo, alto = red.intervalo(fechas, y, elegidas)
    assert bajo == pytest.approx(1 / 3) and alto == pytest.approx(1 / 3)  # todos los días iguales: sin margen
    y2 = np.concatenate([np.ones(45), np.zeros(45)])
    bajo, alto = red.intervalo(fechas, y2, elegidas)
    assert bajo < 0.5 < alto


def test_entrenar_de_punta_a_punta(monkeypatch):
    monkeypatch.setattr(red, "CORTES", 2)
    rng = np.random.default_rng(2)
    recon = red.a_datos(filas_sinteticas(3000, "2025-12-01", rng) + filas_sinteticas(600, "2026-06-01", rng))
    reales = red.a_datos(filas_sinteticas(200, "2026-09-30", rng))
    candidatos = {"logistica": red.CANDIDATOS["logistica"],
                  "arboles": {**red.CANDIDATOS["arboles"], "max_iter": 20, "min_samples_leaf": 20},
                  "red": {**red.CANDIDATOS["red"], "hidden_layer_sizes": (8,), "semillas": 1, "max_iter": 5}}
    modelo, informe = red.entrenar(recon, reales, candidatos)
    assert informe["modelo"] in candidatos and set(informe["comparacion"]) == set(candidatos)
    assert len(informe["comparacion"]["logistica"]["cortes"]) == 2
    prueba = informe["evaluacion"]["prueba: listas reales"]
    assert prueba["auc"] > 0.7  # la señal sintética está en vol_rel_1d
    _, por_dia = np.unique(reales.tramo(*informe["tramos"]["prueba"]).fechas, return_counts=True)
    assert prueba["mostradas"] == np.minimum(por_dia, red.POR_DIA).sum()
    assert informe["importancias"][0][0] == "vol_rel_1d"
    hasta = max(recon.fechas.max(), reales.fechas.max()).astype(date).isoformat()
    assert informe["datos_hasta"] == hasta and informe["filas_red_final"] == len(red.unir(recon, reales))
    assert informe["entrenada"].endswith("Z")
    assert modelo.por_dia == red.POR_DIA and modelo.riesgo is not None and modelo.umbral is None
    texto = red.informe_markdown(informe)
    assert "| prueba: listas reales |" in texto and "vol_rel_1d" in texto and "(elegido)" in texto
    assert "Modelo que se usa cada día" in texto
