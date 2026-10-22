"""Días de las listas y velas diarias de Binance.

Las velas diarias de Binance abren a las 00:00 UTC. Las listas de Momento-A, Momento-B y Scanner-pump
nombran cada día con la fecha en que abre la vela en hora de Lima (UTC−5), que es la del día anterior:
la vela que abre el 16 de octubre a las 00:00 UTC abre en Lima el 15 a las 19:00, así que es el día
«2026-10-15» de las listas, y cierra el 16 a las 19:00 (hora Lima).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

UN_DIA = timedelta(days=1)


def vela_utc(dia_lista: date) -> date:
    """Día UTC en que abre (a las 00:00) la vela de un día de las listas."""
    return dia_lista + UN_DIA


def dia_lista(vela: date) -> date:
    """Día de las listas de la vela que abre ese día a las 00:00 UTC."""
    return vela - UN_DIA


def ms(dia: date) -> int:
    """Milisegundos de las 00:00 UTC de un día (como el ``openTime`` de Binance)."""
    return int(datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc).timestamp() * 1000)


def dia_de_ms(milisegundos: int) -> date:
    return datetime.fromtimestamp(milisegundos / 1000, timezone.utc).date()


def ultima_vela_cerrada(ahora: datetime | None = None) -> date:
    """Día UTC de la última vela diaria cerrada: la que abrió ayer (UTC) cerró hoy a las 00:00 UTC."""
    ahora = ahora or datetime.now(timezone.utc)
    return ahora.astimezone(timezone.utc).date() - UN_DIA
