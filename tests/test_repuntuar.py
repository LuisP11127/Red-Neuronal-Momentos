import json

import numpy as np

from red_momentos import red, repuntuar, senales


class ModeloFalso:
    """Puntúa con la señal ``var_1d`` y da como riesgo la mitad; muestra las 2 mejores."""
    entradas = ["var_1d"]
    por_dia = 2

    def puntuar(self, x):
        return x[:, 0]

    def puntuar_riesgo(self, x):
        return x[:, 0] / 2

    def orden(self, puntos, riesgo):
        return puntos

    def mostrar(self, puntos, riesgo=None):
        return red.Red.mostrar(red.Red(None, None, [], por_dia=2), puntos, riesgo)


def prediccion(var):
    return {"fecha": "2026-10-21", "vela_utc": "2026-10-22", "hora": "2026-10-23T00:43:42Z", "umbral": 0.35,
            "mostradas": [], "monedas": [
                {"moneda": m, "mercado": "futures", "simbolo": m + "USDT", "listas": ["momento-b"], "puntuacion": 0.3,
                 "mostrar": False, "precio": 1.0, "senales": {**{k: None for k in senales.SENALES}, "var_1d": v}}
                for m, v in var.items()]}


def test_puntuar_otra_vez_conserva_la_lista_y_guarda_lo_de_antes():
    p = prediccion({"AIN": 0.1, "ON": 0.4, "GWEI": 0.2})
    sello = {"modelo": "logistica", "datos_hasta": "2026-10-10", "hora": "2026-11-11T00:00:00Z"}
    nueva = repuntuar.puntuar(p, ModeloFalso(), sello)
    assert [m["moneda"] for m in nueva["monedas"]] == ["ON", "GWEI", "AIN"]
    assert nueva["mostradas"] == ["ON", "GWEI"] and nueva["por_dia"] == 2 and nueva["umbral"] is None
    assert nueva["monedas"][0]["puntuacion"] == 0.4 and nueva["monedas"][0]["riesgo"] == 0.2
    assert all(m["precio"] == 1.0 for m in nueva["monedas"]) and nueva["hora"] == p["hora"]
    assert nueva["repuntuada"] == {**sello, "antes": {"umbral": 0.35, "mostradas": []}}
    # Otra vez sobre la ya puntuada: lo de antes sigue siendo lo del modelo antiguo.
    otra = repuntuar.puntuar(nueva, ModeloFalso(), {**sello, "hora": "2026-11-12T00:00:00Z"})
    assert otra["repuntuada"]["antes"] == {"umbral": 0.35, "mostradas": []}
    assert otra["monedas"] == nueva["monedas"]


def test_solo_las_de_modelos_antiguos(tmp_path):
    (tmp_path / "2026-10-21.json").write_text(json.dumps(prediccion({"AIN": 0.1})))
    (tmp_path / "2026-11-09.json").write_text(json.dumps({**prediccion({"ON": 0.1}), "fecha": "2026-11-09",
                                                         "umbral": None, "por_dia": 3}))
    (tmp_path / "2026-10-22.json").write_text(json.dumps({**prediccion({"ON": 0.1}), "fecha": "2026-10-22",
                                                         "por_dia": 3, "repuntuada": {"antes": {}}}))
    assert [p["fecha"] for _, p in repuntuar.antiguas(tmp_path)] == ["2026-10-21", "2026-10-22"]
    assert np.isnan(red.matriz([{"var_1d": None, "mercado": "spot"}], ["var_1d"])[0, 0])
