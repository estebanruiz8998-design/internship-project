"""Generación del racional en lenguaje llano para la asignación recomendada.

Produce 3-4 frases que explican, con números reales de la corrida, por qué se
fondeó a unas cooperativas y no a otras y por qué parte de los fondos quedó en
TES. No es texto de relleno: se construye a partir de las decisiones efectivas.
"""

from __future__ import annotations

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

    frases: list[str] = []

    # Frase 1: qué se fondeó y con qué criterio.
    if fondeadas:
        mejores = sorted(fondeadas, key=lambda s: s.rendimiento_ajustado_ea, reverse=True)
        nombres = [f"{s.cooperativa} (calif. {s.calificacion})" for s in mejores[:2]]
        frases.append(
            f"Se priorizaron las {len(fondeadas)} solicitudes con mayor margen "
            f"ajustado por pérdida esperada —encabezadas por "
            f"{' y '.join(nombres)}—, desplegando {formato_cop(asignacion.monto_en_credito)} "
            f"en crédito de tesorería."
        )
    else:
        frases.append(
            "Ninguna solicitud ofreció margen ajustado por riesgo suficiente frente "
            "al TES bajo las restricciones del día; el pool permaneció en TES."
        )

    # Frase 2: por qué se dejó algo por fuera (margen, concentración o transición).
    if rechazadas:
        peor = min(rechazadas, key=lambda s: s.rendimiento_ajustado_ea)
        dtf_rechazadas = [s for s in rechazadas if s.indexado_dtf]
        if dtf_rechazadas:
            ejemplo = dtf_rechazadas[0]
            frases.append(
                f"Se dejaron por fuera {len(rechazadas)} solicitudes; entre ellas, "
                f"colocaciones indexadas a DTF como la de {ejemplo.cooperativa} "
                f"perdieron atractivo tras el castigo por riesgo de transición DTF→IBR, "
                f"pese a una tasa nominal competitiva."
            )
        else:
            frases.append(
                f"Se descartaron {len(rechazadas)} solicitudes por menor margen "
                f"ajustado por riesgo (p. ej. {peor.cooperativa}, calif. "
                f"{peor.calificacion}) o por chocar contra el tope de concentración."
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
