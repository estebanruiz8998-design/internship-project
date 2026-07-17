"""Compliance / Guardrail Agent.

Re-valida de forma INDEPENDIENTE una asignación contra las cuatro reglas duras:
encaje, concentración, liquidez y calce de duración. Recalcula todo a partir de
las posiciones de la asignación (no confía en los cálculos internos del
Optimization Agent). Si una asignación falla cualquier control, se descarta:
sin excepciones, sin "marcado pero mostrado igual".
"""

from __future__ import annotations

from . import config
from .domain import (
    Asignacion,
    CheckCumplimiento,
    PoolFondeo,
    ResultadoCumplimiento,
    formato_cop,
    formato_pct,
)


class GuardrailAgent:
    def __init__(self, pool: PoolFondeo):
        self.pool = pool

    def validar(self, asignacion: Asignacion) -> ResultadoCumplimiento:
        invertible = self.pool.monto_invertible
        checks: list[CheckCumplimiento] = []

        # 1) Encaje: nada de lo desplegado puede exceder el pool invertible, y el
        #    encaje retenido debe corresponder al 2,5% de los depósitos (CDT).
        desplegado = sum(p.monto for p in asignacion.posiciones)
        encaje_esperado = sum(
            i.monto * config.ENCAJE_PCT for i in self.pool.instrumentos if i.es_deposito
        )
        encaje_ok = (
            desplegado <= invertible + 1.0
            and abs(self.pool.encaje_total - encaje_esperado) <= 1.0
        )
        checks.append(CheckCumplimiento(
            nombre="Encaje sobre depósitos (CDT)",
            aprobado=encaje_ok,
            detalle=(
                f"Encaje retenido {formato_cop(self.pool.encaje_total)} "
                f"({formato_pct(config.ENCAJE_PCT)} sobre CDT). Desplegado no "
                f"excede el pool invertible."
            ),
            limite=f"Desplegado <= {formato_cop(invertible)}",
            observado=f"Desplegado {formato_cop(desplegado)}",
        ))

        # 2) Concentración por cooperativa. Se RECALCULA desde las posiciones de
        #    crédito (no se confía en el campo poblado por el optimizador): esto es
        #    lo que hace del control una re-validación realmente independiente.
        tope = invertible * config.MAX_COUNTERPARTY_PCT
        exp_recalc: dict[str, float] = {}
        for p in asignacion.posiciones_credito():
            exp_recalc[p.cooperativa] = exp_recalc.get(p.cooperativa, 0.0) + p.monto
        peor_coop, peor_exp = None, 0.0
        for coop, exp in exp_recalc.items():
            if exp > peor_exp:
                peor_coop, peor_exp = coop, exp
        conc_ok = peor_exp <= tope + 1.0
        checks.append(CheckCumplimiento(
            nombre="Concentración por contraparte",
            aprobado=conc_ok,
            detalle=(
                f"Máxima exposición: {peor_coop or '—'} con "
                f"{formato_cop(peor_exp)} ({formato_pct(peor_exp / invertible)} del pool)."
            ),
            limite=f"<= {formato_pct(config.MAX_COUNTERPARTY_PCT)} "
                   f"({formato_cop(tope)})",
            observado=f"{formato_pct((peor_exp / invertible) if invertible else 0)}",
        ))

        # 3) Colchón de liquidez en TES corto (tenor <= tenor de liquidez).
        liquidez = sum(
            p.monto for p in asignacion.posiciones_tes()
            if p.plazo_dias <= config.TENOR_LIQUIDEZ_DIAS
        )
        min_liq = invertible * config.MIN_LIQUIDITY_PCT
        liq_ok = liquidez >= min_liq - 1.0
        checks.append(CheckCumplimiento(
            nombre="Colchón mínimo de liquidez (TES corto)",
            aprobado=liq_ok,
            detalle=(
                f"En TES <= {config.TENOR_LIQUIDEZ_DIAS} días: {formato_cop(liquidez)} "
                f"({formato_pct((liquidez / invertible) if invertible else 0)} del pool)."
            ),
            limite=f">= {formato_pct(config.MIN_LIQUIDITY_PCT)} "
                   f"({formato_cop(min_liq)})",
            observado=f"{formato_cop(liquidez)}",
        ))

        # 4) Calce de duración fondeo vs. despliegue. También se RECALCULA la
        #    duración del despliegue desde las posiciones (misma definición que
        #    calcular_metricas_asignacion / elegir_tenor_calce), sin confiar en el
        #    campo poblado por el optimizador.
        monto_desplegado = sum(p.monto for p in asignacion.posiciones)
        dur_despliegue = (
            sum(p.monto * p.plazo_dias for p in asignacion.posiciones) / monto_desplegado
            if monto_desplegado else 0.0
        )
        dur_fondeo = self.pool.duracion_ponderada_dias
        brecha = abs(dur_despliegue - dur_fondeo)
        dur_ok = brecha <= config.DURATION_TOLERANCE_DAYS + 1e-6
        checks.append(CheckCumplimiento(
            nombre="Calce de duración fondeo/despliegue",
            aprobado=dur_ok,
            detalle=(
                f"Duración fondeo {dur_fondeo:.0f} d vs. despliegue "
                f"{dur_despliegue:.0f} d (brecha {brecha:.0f} d)."
            ),
            limite=f"brecha <= {config.DURATION_TOLERANCE_DAYS} días",
            observado=f"{brecha:.0f} días",
        ))

        aprobada = all(c.aprobado for c in checks)
        return ResultadoCumplimiento(
            etiqueta=asignacion.etiqueta, aprobada=aprobada, checks=checks
        )

    def primera_aprobada(
        self, asignaciones: list[Asignacion]
    ) -> tuple[Asignacion | None, ResultadoCumplimiento | None, list[ResultadoCumplimiento]]:
        """Recorre las alternativas en orden y devuelve la primera que aprueba.

        Devuelve (asignacion_aprobada, su_resultado, resultados_de_todas).
        """
        resultados: list[ResultadoCumplimiento] = []
        aprobada: Asignacion | None = None
        res_aprobada: ResultadoCumplimiento | None = None
        for a in asignaciones:
            r = self.validar(a)
            resultados.append(r)
            if r.aprobada and aprobada is None:
                aprobada, res_aprobada = a, r
        return aprobada, res_aprobada, resultados
