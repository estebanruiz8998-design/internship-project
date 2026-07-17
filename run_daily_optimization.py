#!/usr/bin/env python3
"""Optimizador Diario de Margen de Tesorería — Coopcentral.

Ejecuta un ciclo diario completo de punta a punta:

    generación de datos sintéticos -> mercado -> fondeo -> demanda/riesgo ->
    línea base -> optimización -> cumplimiento -> informe

Uso:
    python run_daily_optimization.py               # corrida por defecto
    python run_daily_optimization.py --semilla 7   # otro día sintético
    python run_daily_optimization.py --regenerar    # fuerza nuevos datos
    python run_daily_optimization.py --fecha 2026-07-17 --salida reports/dia.html
"""

from __future__ import annotations

import argparse
import os

from optimizer import config
from optimizer import data_generation
from optimizer.market_data_agent import MarketDataAgent
from optimizer.funding_agent import FundingAgent
from optimizer.demand_risk_agent import DemandRiskAgent
from optimizer.baseline_agent import BaselineAgent
from optimizer.optimization_agent import OptimizationAgent
from optimizer.guardrail_agent import GuardrailAgent
from optimizer.reporting_agent import ReportingAgent
from optimizer.rationale import generar_rationale
from optimizer.domain import formato_cop, formato_bps, formato_pct

_MESES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_larga(iso: str) -> str:
    """'2026-07-17' -> '17 de julio de 2026'."""
    try:
        a, m, d = iso.split("-")
        return f"{int(d)} de {_MESES[int(m)]} de {int(a)}"
    except Exception:
        return iso


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimizador Diario de Margen — Coopcentral")
    parser.add_argument("--semilla", type=int, default=config.SEMILLA_DEFECTO,
                        help="Semilla para la generación sintética reproducible.")
    parser.add_argument("--regenerar", action="store_true",
                        help="Regenera los CSV de entrada aunque ya existan.")
    parser.add_argument("--fecha", type=str, default="2026-07-17",
                        help="Fecha de operación (ISO), solo para el informe.")
    parser.add_argument("--salida", type=str, default=None,
                        help="Ruta del informe HTML de salida.")
    args = parser.parse_args()

    # 1) Datos sintéticos del día.
    faltan = not (os.path.exists(config.CSV_TASAS) and os.path.exists(config.CSV_FONDEO)
                  and os.path.exists(config.CSV_CREDITOS) and os.path.exists(config.CSV_CURVA_TES))
    if args.regenerar or faltan:
        data_generation.generar_todo(semilla=args.semilla)
        print(f"[datos]     Lote sintético generado (semilla {args.semilla}).")
    else:
        print("[datos]     Usando CSV de entrada existentes (usa --regenerar para renovar).")

    # 2) Market Data Agent.
    mercado = MarketDataAgent()
    snapshot = mercado.cargar()
    print(f"[mercado]   BanRep {formato_pct(snapshot.banrep_politica)} · "
          f"IBR3M {formato_pct(snapshot.ibr_3m)} · "
          f"DTF {formato_pct(snapshot.dtf_nominal_ta)} T.A. -> {formato_pct(snapshot.dtf_ea)} E.A.")

    # 3) Funding Agent.
    pool = FundingAgent(mercado).procesar()
    print(f"[fondeo]    Captado {formato_cop(pool.monto_captado_bruto)} · "
          f"encaje {formato_cop(pool.encaje_total)} · "
          f"invertible {formato_cop(pool.monto_invertible)} · "
          f"WACF {formato_pct(pool.costo_fondos_ea)}")

    # 4) Demand & Risk Agent.
    solicitudes = DemandRiskAgent(mercado).procesar()
    demanda_total = sum(s.monto_solicitado for s in solicitudes)
    print(f"[demanda]   {len(solicitudes)} solicitudes de crédito · "
          f"demanda total {formato_cop(demanda_total)}")

    # 5) Baseline Agent.
    baseline = BaselineAgent(snapshot).asignar(pool, solicitudes)
    print(f"[base]      Margen {formato_bps(baseline.margen_bps)} · "
          f"{formato_cop(baseline.margen_cop_total)} · "
          f"{baseline.creditos_fondeados} créditos fondeados")

    # 6) Optimization Agent (top 3: óptima + 2 alternativas).
    top = OptimizationAgent(snapshot).optimizar(pool, solicitudes)

    # 7) Compliance / Guardrail Agent (re-valida y descarta lo que no aprueba).
    guardrail = GuardrailAgent(pool)
    optimizada, res_opt, resultados = guardrail.primera_aprobada(top)

    if optimizada is None:
        print("[cumplim.]  Ninguna alternativa superó el control de cumplimiento.")
        return

    aprobadas = [a for a, r in zip(top, resultados) if r.aprobada]
    alternativas = [a for a in aprobadas if a is not optimizada][:2]
    print(f"[óptima]    Margen {formato_bps(optimizada.margen_bps)} · "
          f"{formato_cop(optimizada.margen_cop_total)} · "
          f"{optimizada.creditos_fondeados} créditos · "
          f"cumplimiento {'APROBADO' if res_opt.aprobada else 'RECHAZADO'}")

    delta = optimizada.margen_cop_total - baseline.margen_cop_total
    print(f"[delta]     +{formato_cop(delta)} "
          f"(+{formato_bps(optimizada.margen_bps - baseline.margen_bps)}) a favor de la optimización")

    # 8) Rationale.
    rationale = generar_rationale(optimizada, solicitudes, pool)

    # 9) Reporting Agent.
    ruta = ReportingAgent().generar(
        fecha=_fecha_larga(args.fecha),
        pool=pool,
        snapshot=snapshot,
        solicitudes=solicitudes,
        baseline=baseline,
        optimizada=optimizada,
        alternativas=alternativas,
        cumplimiento=res_opt,
        rationale=rationale,
        semilla=args.semilla,
        ruta_salida=args.salida,
    )
    print(f"[informe]   Generado: {ruta}")


if __name__ == "__main__":
    main()
