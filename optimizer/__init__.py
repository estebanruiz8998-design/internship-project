"""Optimizador Diario de Margen de Tesorería — Coopcentral (prueba de concepto).

Arquitectura de agentes (cada uno en su propio módulo, inspeccionable por separado):

    MarketDataAgent    -> market_data_agent.py   (fotografía de tasas del día)
    FundingAgent       -> funding_agent.py        (pool invertible y costo de fondos)
    DemandRiskAgent    -> demand_risk_agent.py     (rendimiento ajustado por riesgo)
    BaselineAgent      -> baseline_agent.py        (heurístico manual, statu quo)
    OptimizationAgent  -> optimization_agent.py    (asignación óptima + alternativas)
    GuardrailAgent     -> guardrail_agent.py       (re-validación de cumplimiento)
    ReportingAgent     -> reporting_agent.py       (informe de una página, en español)
"""

from __future__ import annotations

from .market_data_agent import MarketDataAgent
from .funding_agent import FundingAgent
from .demand_risk_agent import DemandRiskAgent
from .baseline_agent import BaselineAgent
from .optimization_agent import OptimizationAgent
from .guardrail_agent import GuardrailAgent
from .reporting_agent import ReportingAgent

__all__ = [
    "MarketDataAgent",
    "FundingAgent",
    "DemandRiskAgent",
    "BaselineAgent",
    "OptimizationAgent",
    "GuardrailAgent",
    "ReportingAgent",
]
