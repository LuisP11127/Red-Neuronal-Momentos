import json
from datetime import date, datetime, timezone

import pytest

from red_momentos import fechas, listas


def escribir_dia(carpeta, fecha, monedas):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{fecha}.json").write_text(json.dumps({"fecha": fecha, "monedas": monedas}), encoding="utf-8")


def fila(simbolo, mercado="futures", base=None):
    return {"mercado": mercado, "simbolo": simbolo, "base": base or simbolo.removesuffix("USDT"),
            "quote": "USDT", "precio": 1.0, "hora": "2026-10-02T15:00:00Z", "intervalo": "1d"}


def test_dia_de_la_lista_y_vela_utc():
    # La vela que abre el 16 de octubre a las 00:00 UTC es el día «15 de octubre» de las listas (19:00 en Lima).
    assert fechas.vela_utc(date(2026, 10, 15)) == date(2026, 10, 16)
    assert fechas.dia_lista(date(2026, 10, 16)) == date(2026, 10, 15)
    # A las 19:30 de Lima del 16 (00:30 UTC del 17) ya cerró la vela que abrió el 16 a las 00:00 UTC.
    assert fechas.ultima_vela_cerrada(datetime(2026, 10, 17, 0, 30, tzinfo=timezone.utc)) == date(2026, 10, 16)
    assert fechas.ultima_vela_cerrada(datetime(2026, 10, 16, 23, 59, tzinfo=timezone.utc)) == date(2026, 10, 15)


def test_sincronizar_copia_cambia_y_borra(tmp_path):
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    escribir_dia(origen, "2026-10-01", [fila("AUSDT")])
    escribir_dia(origen, "2026-10-02", [fila("BUSDT")])
    (origen / "estrellas.json").write_text('{"estrellas": {}}', encoding="utf-8")
    (origen / "README.md").write_text("no se copia", encoding="utf-8")

    cambios = listas.sincronizar(origen, destino)
    assert cambios.nuevos == ["2026-10-01.json", "2026-10-02.json", "estrellas.json"]
    assert not (destino / "README.md").exists()
    assert (destino / "2026-10-01.json").read_bytes() == (origen / "2026-10-01.json").read_bytes()

    assert not listas.sincronizar(origen, destino)  # nada cambió

    escribir_dia(origen, "2026-10-02", [fila("BUSDT"), fila("CUSDT")])
    (origen / "2026-10-01.json").unlink()  # «Borrar» en la web de origen
    cambios = listas.sincronizar(origen, destino)
    assert cambios.cambiados == ["2026-10-02.json"]
    assert cambios.borrados == ["2026-10-01.json"]
    assert sorted(p.name for p in destino.iterdir()) == ["2026-10-02.json", "estrellas.json"]
    assert cambios.resumen() == "cambiados: 2026-10-02; borrados: 2026-10-01"


def test_un_archivo_roto_no_se_copia_ni_borra_la_copia(tmp_path):
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    escribir_dia(origen, "2026-10-01", [fila("AUSDT")])
    listas.sincronizar(origen, destino)
    copia = (destino / "2026-10-01.json").read_bytes()

    (origen / "2026-10-01.json").write_text("{roto", encoding="utf-8")
    escribir_dia(origen, "2026-10-03", [])
    (origen / "2026-10-03.json").write_text('{"fecha": "2026-10-04", "monedas": []}', encoding="utf-8")
    cambios = listas.sincronizar(origen, destino)
    assert [o.split(":")[0] for o in cambios.omitidos] == ["2026-10-01.json", "2026-10-03.json"]
    assert (destino / "2026-10-01.json").read_bytes() == copia
    assert not (destino / "2026-10-03.json").exists()


def test_origen_vacio_no_toca_la_copia(tmp_path):
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    escribir_dia(destino, "2026-10-01", [])
    origen.mkdir()
    with pytest.raises(ValueError):
        listas.sincronizar(origen, destino)
    with pytest.raises(FileNotFoundError):
        listas.sincronizar(tmp_path / "no-existe", destino)
    assert (destino / "2026-10-01.json").exists()


def test_main_copia_las_tres_fuentes(tmp_path, capsys):
    for clave, carpeta in [("a", "docs/seguimiento"), ("b", "docs/seguimiento"), ("s", "datos/seguimiento")]:
        escribir_dia(tmp_path / clave / carpeta, "2026-10-01", [fila("AUSDT")])
    destino = tmp_path / "listas"
    codigo = listas.main(["--momento-a", str(tmp_path / "a"), "--momento-b", str(tmp_path / "b"),
                          "--scanner-pump", str(tmp_path / "s"), "--destino", str(destino)])
    assert codigo == 0
    assert sorted(p.name for p in destino.iterdir()) == ["momento-a", "momento-b", "scanner-pump"]
    assert "momento-a: nuevos: 2026-10-01" in capsys.readouterr().out
    # Si una fuente falla, las demás se copian igual y el código de salida lo avisa.
    assert listas.main(["--momento-a", str(tmp_path / "no-existe"), "--destino", str(destino)]) == 1


def test_candidatas_no_repetidas_con_futuros(tmp_path):
    raiz = tmp_path / "listas"
    escribir_dia(raiz / "momento-a", "2026-10-01", [
        fila("PEPEUSDT", "spot"), fila("1000PEPEUSDT", "futures", base="1000PEPE"), fila("SOLUSDT", "spot")])
    escribir_dia(raiz / "momento-b", "2026-10-01", [fila("SOLUSDT", "spot"), fila("ARBUSDT")])
    escribir_dia(raiz / "momento-b", "2026-10-02", [fila("SOLUSDT", "spot")])
    escribir_dia(raiz / "scanner-pump", "2026-10-01", [fila("XUSDT")])

    resultado = {(c.fecha.isoformat(), c.moneda): c for c in listas.candidatas(raiz)}
    assert sorted(resultado) == [("2026-10-01", "ARB"), ("2026-10-01", "PEPE"), ("2026-10-01", "SOL"),
                                 ("2026-10-02", "SOL")]
    pepe = resultado[("2026-10-01", "PEPE")]
    assert (pepe.mercado, pepe.simbolo, pepe.listas) == ("futures", "1000PEPEUSDT", ("momento-a",))
    assert len(pepe.filas) == 2
    assert resultado[("2026-10-01", "SOL")].listas == ("momento-a", "momento-b")
    assert resultado[("2026-10-01", "SOL")].mercado == "spot"
    assert listas.explosiones(raiz) == {"X": {date(2026, 10, 1)}}
