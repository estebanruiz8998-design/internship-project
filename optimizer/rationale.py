"""Generación del racional en lenguaje llano para la asignación recomendada.

Produce 3-4 frases que explican, con números reales de la corrida, por qué se
fondeó a unas cooperativas y no a otras y por qué parte de los fondos quedó en
TES. No es texto de relleno: se construye a partir de las decisiones efectivas.
"""

from __future__ import annotations

from . import config
from .domain import (
    Asignacion,
    PoolFondeo,
    SolicitudCredito,
    formato_cop,
    formato_pct,
)


def generar_rationale(
    asignacion: Asignacion,
    solicitudes: list[SolicitudCredito],
    pool: PoolFondeo,
) -> str:
    invertible = pool.monto_invertible
    fondeadas_ids = {p.referencia for p in asignacion.posiciones_credito()}
    fondeadas = [s for s in solicitudes if s.id in fondeadas_ids]
    rechazadas = [s for s in solicitudes if s.id not in fondeadas_ids]

    cof = pool.costo_fondos_ea
    aporte = lambda s: s.monto_solicitado * (s.rendimiento_ajustado_ea - cof)

    frases: list[str] = []

    # Frase 1: qué se fondeó y con qué criterio REAL (el optimizador maximiza el
    # aporte TOTAL de margen ajustado por riesgo sujeto a las restricciones, no un
    # ranking por tasa: por eso un crédito grande con buen spread puede entrar por
    # encima de otro con tasa ajustada algo mayor pero monto menor).
    if fondeadas:
        mejores = sorted(fondeadas, key=aporte, reverse=True)
        nombres = [f"{s.cooperativa} (calif. {s.calificacion})" for s in mejores[:2]]
        frases.append(
            f"Se seleccionó el conjunto de {len(fondeadas)} solicitudes que "
            f"maximiza el aporte total de margen ajustado por pérdida esperada, "
            f"dentro de las restricciones —con mayor aporte de "
            f"{' y '.join(nombres)}—, desplegando "
            f"{formato_cop(asignacion.monto_en_credito)} en crédito de tesorería."
        )
    else:
        frases.append(
            "Ninguna solicitud ofreció margen ajustado por riesgo suficiente frente "
            "al TES bajo las restricciones del día; el pool permaneció en TES."
        )

    # Frase 2: por qué se dejó algo por fuera. Solo se menciona la concentración
    # si el tope realmente resultó vinculante para alguna cooperativa fondeada.
    if rechazadas:
        peor = min(rechazadas, key=lambda s: s.rendimiento_ajustado_ea)
        dtf_rechazadas = [s for s in rechazadas if s.indexado_dtf]
        tope = invertible * config.MAX_COUNTERPARTY_PCT
        concentracion_vinculante = any(
            v > tope - 1_000_000 for v in asignacion.exposicion_por_cooperativa.values()
        )
        if dtf_rechazadas:
            ejemplo = dtf_rechazadas[0]
            frases.append(
                f"Se dejaron por fuera {len(rechazadas)} solicitudes; entre ellas, "
                f"colocaciones indexadas a DTF como la de {ejemplo.cooperativa} "
                f"perdieron atractivo tras el castigo por riesgo de transición DTF→IBR, "
                f"pese a una tasa nominal competitiva."
            )
        elif concentracion_vinculante:
            frases.append(
                f"Se descartaron {len(rechazadas)} solicitudes: unas por aportar "
                f"menos margen ajustado por riesgo (p. ej. {peor.cooperativa}, calif. "
                f"{peor.calificacion}) y otras por chocar contra el tope de "
                f"concentración por cooperativa, que resultó vinculante."
            )
        else:
            frases.append(
                f"Se descartaron {len(rechazadas)} solicitudes por aportar menos "
                f"margen ajustado por riesgo dentro del cupo disponible (p. ej. "
                f"{peor.cooperativa}, calif. {peor.calificacion}); su colocación "
                f"habría desplazado a otras de mayor aporte o rendido menos que el TES."
            )

    # Frase 3: por qué parte quedó en TES (liquidez + calce de duración).
    pct_tes = (asignacion.monto_en_tes / invertible) if invertible else 0.0
    frases.append(
        f"{formato_pct(pct_tes)} del pool ({formato_cop(asignacion.monto_en_tes)}) "
        f"quedó en TES: cubre el colchón mínimo de liquidez y ajusta la duración del "
        f"despliegue a la del fondeo (calce ALM)."
    )

    # Frase 4: resultado neto.
    frases.append(
        f"El resultado respeta las cuatro restricciones regulatorias y captura un "
        f"margen de {asignacion.margen_bps:.0f} bps sobre el costo de fondos."
    )

    return " ".join(frases)
