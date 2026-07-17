"""Baseline Agent.

Reproduce el heurístico manual realista de la mesa (el statu quo implícito):
atiende las solicitudes de crédito de tesorería EN EL ORDEN EN QUE LLEGARON
hasta que se toca el colchón de liquidez, respetando el tope de concentración
por cooperativa (un control básico que la mesa sí conoce), y estaciona el
remanente en el TES de tenor más cercano a la duración del fondeo.

NO optimiza el margen ajustado por riesgo ni ordena por atractivo: ese es
justamente el punto de comparación contra la optimización.
"""

from __future__ import annotations

from . import config
from .domain import (
    Asignacion,
    PoolFondeo,
    Posicion,
    SnapshotMercado,
    SolicitudCredito,
    calcular_metricas_asignacion,
    elegir_tenor_calce,
)


class BaselineAgent:
    def __init__(self, mercado_snapshot: SnapshotMercado):
        self.snapshot = mercado_snapshot

    def asignar(
        self,
        pool: PoolFondeo,
        solicitudes: list[SolicitudCredito],
    ) -> Asignacion:
        invertible = pool.monto_invertible
        colchon = invertible * config.MIN_LIQUIDITY_PCT
        tope_coop = invertible * config.MAX_COUNTERPARTY_PCT
        capacidad_credito = invertible - colchon
        tenor_liq = config.TENOR_LIQUIDEZ_DIAS
        tenores = sorted(t for t in self.snapshot.curva_tes
                         if t <= config.MAX_TENOR_PARKING_DIAS)
        tol = config.DURATION_TOLERANCE_DAYS
        dur_fondeo = pool.duracion_ponderada_dias

        exposicion: dict[str, float] = {}
        fondeadas: list[SolicitudCredito] = []
        colocado = 0.0
        base_num = colchon * tenor_liq  # numerador de duración de lo ya fijo

        # Heurístico manual: se atienden en ORDEN DE LLEGADA (FCFS), sin ordenar
        # por atractivo. Solo se respetan controles básicos que la mesa sí conoce:
        # cupo (sin tocar el colchón), tope de concentración y no romper el calce
        # de duración (una mesa no presta tan corto que descuadre su ALM).
        for s in sorted(solicitudes, key=lambda x: x.orden_llegada):
            if colocado + s.monto_solicitado > capacidad_credito + 1e-6:
                continue
            exp_actual = exposicion.get(s.cooperativa, 0.0)
            if exp_actual + s.monto_solicitado > tope_coop + 1e-6:
                continue
            # ¿Fondearla dejaría el despliegue calzable en duración?
            base_num_tent = base_num + s.monto_solicitado * s.plazo_dias
            remanente_tent = capacidad_credito - (colocado + s.monto_solicitado)
            factible, _, _ = elegir_tenor_calce(
                base_num_tent, remanente_tent, invertible, dur_fondeo, tenores, tol
            )
            if not factible:
                continue
            # Se fondea.
            fondeadas.append(s)
            colocado += s.monto_solicitado
            exposicion[s.cooperativa] = exp_actual + s.monto_solicitado
            base_num = base_num_tent

        posiciones: list[Posicion] = [
            Posicion.desde_credito(s, s.monto_solicitado) for s in fondeadas
        ]
        # Colchón de liquidez en TES corto (90 días).
        posiciones.append(Posicion.tes(
            monto=colchon, tenor_dias=tenor_liq,
            rendimiento_ea=self.snapshot.tes_por_tenor(tenor_liq),
            etiqueta=f"TES {tenor_liq}d (colchón liquidez)",
        ))
        # Remanente al TES que mejor calza la duración del fondeo.
        remanente = capacidad_credito - colocado
        if remanente > 1e-6:
            _, tenor_rem, _ = elegir_tenor_calce(
                base_num, remanente, invertible, dur_fondeo, tenores, tol
            )
            posiciones.append(Posicion.tes(
                monto=remanente, tenor_dias=tenor_rem,
                rendimiento_ea=self.snapshot.tes_por_tenor(tenor_rem),
                etiqueta=f"TES {tenor_rem}d (remanente)",
            ))

        asignacion = Asignacion(etiqueta="Línea base (manual · orden de llegada)", posiciones=posiciones)
        asignacion.rationale = (
            "Se atendieron las solicitudes en orden de llegada hasta agotar el "
            "cupo disponible, sin priorizar por margen ajustado por riesgo; el "
            "remanente se estacionó en TES calzando la duración del fondeo."
        )
        calcular_metricas_asignacion(
            asignacion, pool.costo_fondos_ea, len(solicitudes),
            horizonte_dias=dur_fondeo,
            costo_encaje_anual=pool.encaje_total * pool.costo_fondos_ea,
        )
        return asignacion
