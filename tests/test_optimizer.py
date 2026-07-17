"""Pruebas del Optimizador Diario de Margen (solo librería estándar).

    python -m unittest tests.test_optimizer      # o:  python tests/test_optimizer.py

Cubre lo que un revisor querría confirmar:
  * la conversión DTF (T.A. -> E.A.),
  * que el encaje solo aplica a CDT (no a pagarés),
  * que el Guardrail REALMENTE rechaza violaciones (concentración y liquidez),
  * que el delta optimización - línea base nunca es negativo (por construcción),
  * y que la asignación óptima siempre supera el control de cumplimiento.
"""

from __future__ import annotations

import unittest

from optimizer import config, data_generation
from optimizer.market_data_agent import MarketDataAgent
from optimizer.funding_agent import FundingAgent
from optimizer.demand_risk_agent import DemandRiskAgent
from optimizer.baseline_agent import BaselineAgent
from optimizer.optimization_agent import OptimizationAgent
from optimizer.guardrail_agent import GuardrailAgent
from optimizer.domain import (
    Asignacion,
    Posicion,
    dtf_ta_a_ea,
    calcular_metricas_asignacion,
)


def _pipeline(semilla: int):
    data_generation.generar_todo(semilla=semilla)
    mercado = MarketDataAgent()
    snapshot = mercado.cargar()
    pool = FundingAgent(mercado).procesar()
    solicitudes = DemandRiskAgent(mercado).procesar()
    return snapshot, pool, solicitudes


class TestFinanzas(unittest.TestCase):
    def test_dtf_ta_a_ea(self):
        # 10,13% T.A. -> ~10,81% E.A. (fórmula [1/(1-DTF/4)]^4 - 1).
        self.assertAlmostEqual(dtf_ta_a_ea(0.1013), 0.10805, places=4)
        # Una DTF más alta produce un E.A. más alto (monotonía).
        self.assertGreater(dtf_ta_a_ea(0.12), dtf_ta_a_ea(0.10))

    def test_encaje_solo_cdt(self):
        _, pool, _ = _pipeline(20260717)
        for inst in pool.instrumentos:
            if inst.tipo == "PAGARE":
                self.assertEqual(inst.encaje_aplicado, 0.0)
            else:  # CDT_DORADO
                self.assertAlmostEqual(
                    inst.encaje_aplicado, inst.monto * config.ENCAJE_PCT, places=2
                )
        # Pool invertible = captado - encaje.
        self.assertAlmostEqual(
            pool.monto_invertible,
            pool.monto_captado_bruto - pool.encaje_total, places=2,
        )

    def test_rendimiento_ajustado_baja_con_riesgo_y_penaliza_dtf(self):
        _, _, solicitudes = _pipeline(20260717)
        for s in solicitudes:
            # El ajuste por riesgo nunca sube el rendimiento sobre la tasa nominal.
            self.assertLessEqual(s.rendimiento_ajustado_ea, s.tasa_ofrecida_ea + 1e-12)
            if s.indexado_dtf:
                self.assertGreater(s.haircut_transicion, 0.0)


class TestGuardrailRechaza(unittest.TestCase):
    """El Guardrail debe RECHAZAR asignaciones que violan las reglas duras."""

    def _pool(self):
        _, pool, _ = _pipeline(20260717)
        return pool

    def test_rechaza_concentracion(self):
        pool = self._pool()
        inv = pool.monto_invertible
        # Un crédito a UNA cooperativa por encima del tope de concentración.
        monto = inv * (config.MAX_COUNTERPARTY_PCT + 0.10)
        pos = Posicion(
            clase="CREDITO", referencia="X1", cooperativa="Coop Concentrada",
            monto=monto, plazo_dias=120, rendimiento_ea=0.14,
            rendimiento_ajustado_ea=0.135,
        )
        buffer = Posicion.tes(inv * config.MIN_LIQUIDITY_PCT, 90, 0.112, "TES")
        resto = Posicion.tes(inv - monto - buffer.monto, 180, 0.1145, "TES")
        a = Asignacion(etiqueta="viola-concentracion", posiciones=[pos, buffer, resto])
        calcular_metricas_asignacion(a, pool.costo_fondos_ea, 1, pool.duracion_ponderada_dias)
        res = GuardrailAgent(pool).validar(a)
        self.assertFalse(res.aprobada)
        conc = next(c for c in res.checks if "Concentración" in c.nombre)
        self.assertFalse(conc.aprobado)

    def test_rechaza_liquidez(self):
        pool = self._pool()
        inv = pool.monto_invertible
        # Sin colchón de liquidez: todo a crédito repartido bajo el tope.
        n = 6
        monto = inv / n
        posiciones = [
            Posicion(clase="CREDITO", referencia=f"X{i}", cooperativa=f"Coop {i}",
                     monto=monto, plazo_dias=180, rendimiento_ea=0.14,
                     rendimiento_ajustado_ea=0.135)
            for i in range(n)
        ]
        a = Asignacion(etiqueta="viola-liquidez", posiciones=posiciones)
        calcular_metricas_asignacion(a, pool.costo_fondos_ea, n, pool.duracion_ponderada_dias)
        res = GuardrailAgent(pool).validar(a)
        self.assertFalse(res.aprobada)
        liq = next(c for c in res.checks if "liquidez" in c.nombre.lower())
        self.assertFalse(liq.aprobado)

    def test_ignora_campos_spoofeados(self):
        """El control es independiente: recalcula desde posiciones, no confía en
        los campos que puebla el optimizador (concentración y duración)."""
        snapshot, pool, sol = _pipeline(20260717)
        top = OptimizationAgent(snapshot).optimizar(pool, sol)
        guard = GuardrailAgent(pool)
        opt = top[0]
        self.assertTrue(guard.validar(opt).aprobada)
        # Se corrompen los campos poblados por el optimizador con valores que,
        # de ser creídos, dispararían un rechazo. El guardrail debe ignorarlos.
        opt.duracion_ponderada_dias = 99999.0
        opt.exposicion_por_cooperativa = {"Falsa": pool.monto_invertible * 10}
        self.assertTrue(guard.validar(opt).aprobada)


class TestComparacion(unittest.TestCase):
    def test_delta_no_negativo_y_optima_aprobada(self):
        semillas = [1, 2, 3, 7, 42, 99, 100, 2026, 20260717]
        for s in semillas:
            snapshot, pool, solicitudes = _pipeline(s)
            base = BaselineAgent(snapshot).asignar(pool, solicitudes)
            top = OptimizationAgent(snapshot).optimizar(pool, solicitudes)
            guard = GuardrailAgent(pool)
            optima, res, _ = guard.primera_aprobada(top)
            with self.subTest(semilla=s):
                self.assertIsNotNone(optima, "no hubo óptima aprobada")
                self.assertTrue(res.aprobada)
                # Delta nunca negativo (tolerancia numérica).
                self.assertGreaterEqual(
                    optima.margen_cop_total - base.margen_cop_total, -1.0
                )
                # La línea base también debe ser independientemente cumplidora.
                self.assertTrue(guard.validar(base).aprobada)
                # El optimizador devuelve hasta 3 alternativas.
                self.assertLessEqual(len(top), 3)
                self.assertGreaterEqual(len(top), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
