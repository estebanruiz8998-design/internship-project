"""Demand & Risk Agent.

Puntúa cada solicitud de crédito de tesorería (monto, plazo, calificación
interna de la cooperativa solicitante) y calcula un rendimiento ajustado por
pérdida esperada, no solo la tasa cotizada.

Rendimiento ajustado (E.A.) =
    tasa_ofrecida  -  pérdida_esperada_anual  -  castigo_transición_DTF

donde:
    pérdida_esperada_anual = PD(calificación) * LGD
    castigo_transición_DTF = DTF_TRANSITION_HAIRCUT_BPS (solo si indexado a DTF)
"""

from __future__ import annotations

import csv

from . import config
from .domain import SolicitudCredito
from .market_data_agent import MarketDataAgent


class DemandRiskAgent:
    def __init__(self, mercado: MarketDataAgent, ruta_creditos: str | None = None):
        self.mercado = mercado
        self.ruta_creditos = ruta_creditos or config.CSV_CREDITOS

    def _cargar(self) -> list[SolicitudCredito]:
        solicitudes: list[SolicitudCredito] = []
        with open(self.ruta_creditos, newline="", encoding="utf-8") as fh:
            for fila in csv.DictReader(fh):
                solicitudes.append(SolicitudCredito(
                    id=fila["id"],
                    cooperativa=fila["cooperativa"],
                    monto_solicitado=float(fila["monto_solicitado"]),
                    plazo_dias=int(fila["plazo_dias"]),
                    calificacion=fila["calificacion"],
                    tipo_tasa=fila["tipo_tasa"],
                    spread_bps=float(fila["spread_bps"]),
                    tasa_ofrecida_ea=float(fila["tasa_ofrecida_ea"]),
                    orden_llegada=int(fila["orden_llegada"]),
                ))
        return solicitudes

    def procesar(self) -> list[SolicitudCredito]:
        solicitudes = self._cargar()
        haircut = config.DTF_TRANSITION_HAIRCUT_BPS / 10_000.0

        for s in solicitudes:
            s.indexado_dtf = self.mercado.es_expuesto_transicion(s.tipo_tasa)
            s.pd_anual = config.PD_POR_CALIFICACION.get(s.calificacion, 0.07)
            s.lgd = config.LGD_PCT
            s.perdida_esperada_anual = s.pd_anual * s.lgd
            s.haircut_transicion = haircut if s.indexado_dtf else 0.0
            s.rendimiento_ajustado_ea = (
                s.tasa_ofrecida_ea
                - s.perdida_esperada_anual
                - s.haircut_transicion
            )
        return solicitudes
