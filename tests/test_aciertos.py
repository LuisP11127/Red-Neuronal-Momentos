import json
from datetime import datetime, timezone

from red_momentos import aciertos
from red_momentos.binance import Vela

PASO, DIA = aciertos.PASO, aciertos.DIA_MS
HORA = "2026-10-24T04:54:53Z"  # GitHub lanzó la lista del 22 a las 23:54 hora Lima
DESDE = aciertos.hora_ms(HORA)
PRIMERA = -(-DESDE // PASO) * PASO  # la vela de las 05:00 UTC


def velas_15m(desde, cantidad, high=1.0, saltos=None):
    saltos = saltos or {}
    velas = {desde - PASO: Vela(desde - PASO, 1.0, 9.0, 1.0, 1.0, 1, 1, 1, 0.5, 0.5)}  # antes de la lista: no cuenta
    for i in range(cantidad):
        t = desde + i * PASO
        velas[t] = Vela(t, 1.0, saltos.get(i, high), 0.9, 1.0, 1, 1, 1, 0.5, 0.5)
    return velas


def test_se_mide_desde_la_hora_de_la_lista():
    assert datetime.fromtimestamp(PRIMERA / 1000, timezone.utc).strftime("%H:%M") == "05:00"
    # Llega a +50 % 50 horas después de la primera vela: el tercer día contando desde las 04:54.
    velas = velas_15m(PRIMERA, 5 * 96, high=1.1, saltos={200: 1.6})
    r = aciertos.evaluar(1.0, DESDE, velas, cubierto=PRIMERA + 5 * DIA)
    assert (r.estado, r.dias_hasta_50, r.maximo, r.referencia) == ("llego", 3, 1.6, 1.0)
    assert r.dias_vistos == 5


def test_no_llega_y_lo_de_despues_no_cuenta():
    velas = velas_15m(PRIMERA, 11 * 96, high=1.4, saltos={10 * 96: 3.0})
    r = aciertos.evaluar(1.0, DESDE, velas, cubierto=PRIMERA + 11 * DIA)
    assert (r.estado, r.maximo, r.dias_vistos) == ("no_llego", 1.4, 10)


def test_en_curso():
    r = aciertos.evaluar(1.0, DESDE, velas_15m(PRIMERA, 40, high=1.2), cubierto=PRIMERA + 39 * PASO)
    assert (r.estado, r.dias_vistos) == ("pendiente", 0)
    assert aciertos.evaluar(1.0, DESDE, {}, cubierto=DESDE).estado == "pendiente"


class BinanceFalso:
    def __init__(self, velas):
        self.series = velas
        self.pedidos = []
        self.avisos = []

    def velas(self, mercado, simbolo, intervalo, desde, hasta):
        assert intervalo == "15m"
        self.pedidos.append(simbolo)
        return [v for t, v in sorted(self.series.items()) if desde <= t <= hasta], hasta


def test_predicciones_a_resultados(tmp_path):
    (tmp_path / "2026-10-22.json").write_text(json.dumps({"fecha": "2026-10-22", "hora": HORA, "monedas": [
        {"moneda": "ON", "mercado": "futures", "simbolo": "ONUSDT", "mostrar": True, "precio": 1.0},
        {"moneda": "SIN", "mercado": "spot", "simbolo": "SINUSDT", "mostrar": False, "precio": None}]}))
    (tmp_path / "resultados.csv").write_text("no es una predicción")
    candidatas = aciertos.leer_predicciones(tmp_path)
    assert [(c["moneda"], c["mostrada"]) for c in candidatas] == [("ON", "1")]  # sin precio no se puede medir

    falso = BinanceFalso(velas_15m(PRIMERA, 11 * 96, high=1.1, saltos={10: 1.5}))
    ahora = PRIMERA + 12 * DIA
    filas = aciertos.calcular(candidatas, falso, {}, ahora)
    assert [(f["moneda"], f["estado"], f["dias_hasta_50"], f["pct_maximo"]) for f in filas] == [("ON", "llego", "1", "50.00")]
    ruta = tmp_path / "salida.csv"
    aciertos.escribir_csv(ruta, filas)
    # Ya terminó: al día siguiente se reutiliza sin pedir velas.
    falso.pedidos.clear()
    assert aciertos.calcular(candidatas, falso, aciertos.leer_csv(ruta), ahora + DIA) == filas
    assert falso.pedidos == []
    assert "Mostradas por la red con resultado: 1; llegaron: 1." in aciertos.resumen(filas)
