"""Market Data Agent.

Carga la fotografía de tasas del día (BanRep, TES, DTF, IBR) desde los CSV
generados y marca como "expuesto a transición" cualquier instrumento indexado
a DTF (Ley 2294 de 2023, art. 314: la DTF deja de publicarse el 31/12/2026 y
se lee como IBR-3M E.A. desde el 01/01/2027).
"""

from __future__ import annotations

import csv

from . import config
from .domain import SnapshotMercado


class MarketDataAgent:
    """Provee el snapshot de mercado y la definición de riesgo de transición."""

    def __init__(self, ruta_tasas: str | None = None, ruta_curva: str | None = None):
        self.ruta_tasas = ruta_tasas or config.CSV_TASAS
        self.ruta_curva = ruta_curva or config.CSV_CURVA_TES

    def cargar(self) -> SnapshotMercado:
        tasas: dict[str, float] = {}
        with open(self.ruta_tasas, newline="", encoding="utf-8") as fh:
            for fila in csv.DictReader(fh):
                tasas[fila["clave"]] = float(fila["valor"])

        curva: dict[int, float] = {}
        with open(self.ruta_curva, newline="", encoding="utf-8") as fh:
            for fila in csv.DictReader(fh):
                curva[int(fila["tenor_dias"])] = float(fila["rendimiento_ea"])

        return SnapshotMercado(
            banrep_politica=tasas["banrep_politica"],
            ibr_overnight=tasas["ibr_overnight"],
            ibr_1m=tasas["ibr_1m"],
            ibr_3m=tasas["ibr_3m"],
            dtf_ea=tasas["dtf_ea"],
            dtf_nominal_ta=tasas["dtf_nominal_ta"],
            curva_tes=curva,
            fecha_transicion_ibr=config.FECHA_TRANSICION_IBR,
        )

    @staticmethod
    def es_expuesto_transicion(tipo_tasa: str) -> bool:
        """Un instrumento está expuesto a la transición si está indexado a DTF."""
        return tipo_tasa.upper() == "DTF"
