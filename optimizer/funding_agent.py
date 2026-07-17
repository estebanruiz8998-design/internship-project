"""Funding Agent.

Ingiere el lote de fondeo del día (CDT Dorado y pagarés a la orden), descuenta
el encaje (solo sobre depósitos a término; los pagarés no cargan encaje) y
entrega el pool invertible con su tasa pasiva promedio ponderada (WACF, el
costo de fondos efectivo del día).
"""

from __future__ import annotations

import csv

from . import config
from .domain import InstrumentoFondeo, PoolFondeo
from .market_data_agent import MarketDataAgent


class FundingAgent:
    def __init__(self, mercado: MarketDataAgent, ruta_fondeo: str | None = None):
        self.mercado = mercado
        self.ruta_fondeo = ruta_fondeo or config.CSV_FONDEO

    def _cargar(self) -> list[InstrumentoFondeo]:
        instrumentos: list[InstrumentoFondeo] = []
        with open(self.ruta_fondeo, newline="", encoding="utf-8") as fh:
            for fila in csv.DictReader(fh):
                inst = InstrumentoFondeo(
                    id=fila["id"],
                    tipo=fila["tipo"],
                    cooperativa=fila["cooperativa"],
                    monto=float(fila["monto"]),
                    plazo_dias=int(fila["plazo_dias"]),
                    tipo_tasa=fila["tipo_tasa"],
                    spread_bps=float(fila["spread_bps"]),
                    tasa_ea=float(fila["tasa_ea"]),
                )
                inst.indexado_dtf = self.mercado.es_expuesto_transicion(inst.tipo_tasa)
                instrumentos.append(inst)
        return instrumentos

    def procesar(self) -> PoolFondeo:
        instrumentos = self._cargar()

        captado_bruto = 0.0
        encaje_total = 0.0
        invertible = 0.0
        dur_num = 0.0            # numerador de la duración ponderada (por nominal)
        monto_dtf = 0.0

        for inst in instrumentos:
            captado_bruto += inst.monto
            # El encaje aplica solo a depósitos (CDT); los pagarés están exentos.
            if inst.es_deposito:
                inst.encaje_aplicado = inst.monto * config.ENCAJE_PCT
            else:
                inst.encaje_aplicado = 0.0
            inst.monto_invertible = inst.monto - inst.encaje_aplicado

            encaje_total += inst.encaje_aplicado
            invertible += inst.monto_invertible
            dur_num += inst.monto * inst.plazo_dias
            if inst.indexado_dtf:
                monto_dtf += inst.monto

        # Costo de fondos: tasa pasiva promedio ponderada por el nominal captado
        # (el banco paga intereses sobre el nominal, no sobre el invertible).
        wacf = (sum(i.monto * i.tasa_ea for i in instrumentos) / captado_bruto
                if captado_bruto else 0.0)
        duracion = dur_num / captado_bruto if captado_bruto else 0.0

        return PoolFondeo(
            instrumentos=instrumentos,
            monto_captado_bruto=captado_bruto,
            encaje_total=encaje_total,
            monto_invertible=invertible,
            costo_fondos_ea=wacf,
            duracion_ponderada_dias=duracion,
            monto_indexado_dtf=monto_dtf,
        )
