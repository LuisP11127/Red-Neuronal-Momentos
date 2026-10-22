from datetime import date

import numpy as np

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


def test_la_red_en_numpy_da_lo_mismo_que_scikit_learn(tmp_path):
    from sklearn.neural_network import MLPClassifier

    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 3))
    y = (x[:, 0] + rng.normal(scale=0.5, size=400) > 0.5).astype(int)
    cuantiles = red.Cuantiles.ajustar(x)
    modelo = MLPClassifier(hidden_layer_sizes=(8, 4), max_iter=2000, random_state=0).fit(cuantiles.aplicar(x), y)
    propia = red.Red(cuantiles, list(modelo.coefs_), list(modelo.intercepts_), 0.5, ["a", "b", "c"])
    assert np.allclose(propia.puntuar(x), modelo.predict_proba(cuantiles.aplicar(x))[:, 1])

    ruta = tmp_path / "red.json"
    propia.guardar(ruta, {"informe": {}})
    cargada = red.Red.cargar(ruta)
    assert np.allclose(cargada.puntuar(x), propia.puntuar(x), atol=1e-6)
    assert cargada.umbral == 0.5


def test_elegir_umbral():
    p = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    y = np.array([1, 0, 1, 0, 0, 0, 1, 0])
    # Con las 4 primeras: 2 de 4 (50 %); con 5: 2 de 5 (40 %); con 7: 3 de 7 (43 %); con 8: 3 de 8 (37,5 %).
    assert red.elegir_umbral(y, p, precision=0.4, minimo=1) == 0.3
    assert red.elegir_umbral(y, p, precision=0.45, minimo=1) == 0.6
    assert red.elegir_umbral(y, p, precision=0.45, minimo=5) is None


def filas_sinteticas(n, inicio, rng, mercado="futures"):
    filas = []
    for i in range(n):
        senal = rng.normal()
        fila = {k: "" for k in senales.SENALES}
        fila.update({"fecha": str(np.datetime64(inicio) + np.timedelta64(i % 200, "D")), "moneda": f"M{i % 37}", "mercado": mercado,
                     "completa": "1", "vol_rel_1d": f"{senal:.4f}", "rango_1d": f"{rng.normal():.4f}",
                     "libro_deseq_2": "0.5" if i % 2 else "",
                     "estado": "llego" if senal + rng.normal(scale=0.7) > 1.6 else "no_llego"})
        filas.append(fila)
    return filas


def test_a_datos_y_tramos():
    rng = np.random.default_rng(1)
    filas = filas_sinteticas(10, "2026-01-01", rng)
    filas[0]["estado"] = "pendiente"
    filas[1]["completa"] = "0"
    datos = red.a_datos(filas)
    assert len(datos) == 8 and datos.x.shape == (8, len(red.ENTRADAS))
    j = red.ENTRADAS.index
    assert set(datos.x[:, j("tiene_libro")]) == {0.0, 1.0}
    assert set(datos.x[:, j("tiene_metricas")]) == {0.0}
    assert set(datos.x[:, j("es_futuros")]) == {1.0}

    recon = red.Datos(np.array(["2023-01-01", "2026-10-10"], dtype="datetime64[D]"), np.array(["A", "B"]),
                      np.zeros((2, 1)), np.zeros(2))
    reales = red.Datos(np.array(["2026-09-30", "2026-10-12"], dtype="datetime64[D]"), np.array(["A", "B"]),
                       np.zeros((2, 1)), np.zeros(2))
    t = red.tramos(recon, reales)
    assert t["prueba"] == (date(2026, 9, 30), date(2026, 10, 12))
    assert t["validacion"][1] == date(2026, 9, 19)  # 11 días antes: la etiqueta dura 10
    assert t["entrenamiento"][1] == t["validacion"][0] - red.SEPARACION


def test_entrenar_de_punta_a_punta():
    rng = np.random.default_rng(2)
    recon = red.a_datos(filas_sinteticas(3000, "2025-01-01", rng) + filas_sinteticas(600, "2026-04-15", rng))
    reales = red.a_datos(filas_sinteticas(200, "2026-09-30", rng))
    modelo, informe = red.entrenar(recon, reales)
    ev = informe["evaluacion"]
    assert set(ev) >= {"entrenamiento", "validacion", "prueba: listas reales"}
    assert ev["validacion"]["auc_red"] > 0.7  # la señal sintética está en vol_rel_1d
    assert informe["importancias"][0][0] == "vol_rel_1d"
    texto = red.informe_markdown(informe)
    assert "| prueba: listas reales |" in texto and "vol_rel_1d" in texto
    if modelo.umbral is not None:
        assert ev["validacion"]["umbral"]["precision"] >= red.PRECISION_MINIMA - 1e-9
