"""Parámetros de configuración del Optimizador Diario de Margen de Tesorería.

Este módulo centraliza TODOS los parámetros ajustables del modelo. Está pensado
para que un revisor de cumplimiento (compliance) o el jefe de la mesa pueda leer
las reglas del negocio sin tener que bucear en la lógica de cada agente.

Todas las tasas se expresan como Efectivo Anual (E.A.) salvo que se indique lo
contrario. Los montos están en pesos colombianos (COP).

Contexto de mercado: julio de 2026, tasa de política del Banco de la República
(BanRep) en el orden del 12%, TES a 10 años ~13,2%. Datos ilustrativos/sintéticos
estructurados sobre los productos reales de Coopcentral.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. RESTRICCIONES REGULATORIAS Y ESTRUCTURALES (parámetros nombrados y ajustables)
#    Un revisor de cumplimiento quiere verlos aquí, no enterrados en la lógica.
# ---------------------------------------------------------------------------

# Encaje sobre nuevos depósitos (CDT). Tras la reducción de encaje del Banco de
# la República, el CDT a menos de 18 meses quedó en 2,5% (el CDT >= 18 meses y
# los bonos están en 0%). Los pagarés a la orden y demás títulos de deuda no
# cargan encaje como los depósitos a término. Todos los CDT del lote son a
# 90/180/360 días (< 18 meses), por lo que aplica el 2,5%. Ajustable.
ENCAJE_PCT: float = 0.025

# Tope de concentración de exposición de crédito de tesorería por cooperativa,
# como porcentaje del pool invertible del día. Evita concentrar el riesgo de
# contraparte en una sola cooperativa afiliada.
MAX_COUNTERPARTY_PCT: float = 0.25

# Colchón mínimo de liquidez que debe permanecer en TES de corto plazo,
# como porcentaje del pool invertible.
MIN_LIQUIDITY_PCT: float = 0.15

# Tolerancia de calce de duración (en días) entre la duración promedio ponderada
# de lo captado (fondeo) y la de lo colocado (despliegue). Una banda de ~75 días
# es razonable para el ALM diario de una mesa (no se calza al día exacto).
DURATION_TOLERANCE_DAYS: int = 75

# Tenor máximo (días) admisible para estacionar fondos en TES. La liquidez y el
# remanente del día se colocan en TES de plazo corto/medio (hasta ~2 años); no se
# usan TES largos (5-10 años) como vehículo de parqueo del pool diario.
MAX_TENOR_PARKING_DIAS: int = 720

# ---------------------------------------------------------------------------
# 2. RIESGO DE TRANSICIÓN DTF -> IBR
#    La DTF se está desmontando (base legal: Ley 2294 de 2023, art. 314). El
#    Banco de la República deja de publicar la DTF el 31 de diciembre de 2026 y,
#    desde el 1 de enero de 2027, toda referencia a DTF se lee como IBR a 3 meses
#    efectivo anual. Los contratos ya indexados a DTF conservan la DTF hasta su
#    vencimiento, pero un CDT o crédito indexado a DTF que venza tras esa fecha
#    se repreciará a IBR: ese riesgo debe pesar en la recomendación, no solo la
#    tasa nominal.
# ---------------------------------------------------------------------------

FECHA_TRANSICION_IBR: str = "2027-01-01"
BASE_LEGAL_TRANSICION: str = "Ley 2294 de 2023, art. 314"

# Castigo (haircut) en puntos básicos aplicado al atractivo de un despliegue
# indexado a DTF, para reflejar el riesgo de repreciación/discontinuidad.
DTF_TRANSITION_HAIRCUT_BPS: float = 35.0

# ---------------------------------------------------------------------------
# 3. PARÁMETROS DE RIESGO DE CRÉDITO (pérdida esperada)
#    Coopcentral tiene data histórica de relación con su red -> su ventaja
#    informativa frente a un inversionista genérico. Se modela con una
#    calificación interna simple.
# ---------------------------------------------------------------------------

# Probabilidad de incumplimiento (PD) anual por calificación interna.
PD_POR_CALIFICACION: dict[str, float] = {
    "A": 0.005,   # 0,50%  cooperativa muy sólida, relación larga
    "B": 0.015,   # 1,50%
    "C": 0.035,   # 3,50%
    "D": 0.070,   # 7,00%  relación más frágil / balance ajustado
}

# Severidad de la pérdida (LGD): pérdida dado el incumplimiento. Se asume cierta
# recuperación vía el fondo de garantías / mecanismos de la red solidaria.
LGD_PCT: float = 0.45

# ---------------------------------------------------------------------------
# 4. CONVENCIONES DE CÁLCULO
# ---------------------------------------------------------------------------

# Base de días para prorratear intereses (Actual/365).
BASE_DIAS: int = 365

# Semilla por defecto para la generación sintética reproducible del lote diario.
SEMILLA_DEFECTO: int = 20260717

# ---------------------------------------------------------------------------
# 5. SNAPSHOT DE TASAS DE REFERENCIA (valores por defecto, julio 2026)
#    El Market Data Agent los lee desde un CSV generado; estos son los valores
#    con los que se genera ese CSV si no existe.
#    Todas E.A. salvo la nota de DTF.
# ---------------------------------------------------------------------------

# La DTF se cotiza como nominal trimestre anticipada (T.A.). El E.A. se DERIVA de
# esta cifra con la fórmula E.A. = [1/(1 - DTF/4)]^4 - 1 (ver domain.dtf_ta_a_ea),
# para que ambas queden siempre consistentes. 0,1013 T.A. -> ~10,80% E.A.
TASAS_REFERENCIA_DEFECTO: dict[str, float] = {
    "banrep_politica": 0.1200,   # Tasa de política BanRep
    "ibr_overnight": 0.1200,     # IBR sobre-noche (~ tasa de política)
    "ibr_1m": 0.1195,            # IBR 1 mes
    "ibr_3m": 0.1185,            # IBR 3 meses
    "dtf_nominal_ta": 0.1013,    # DTF nominal trimestre anticipada (cotización)
    # "dtf_ea" se calcula al cargar el snapshot (no se fija a mano).
}

# Curva TES (rendimiento E.A. por tenor en días). Corto plazo para calce de
# liquidez; largo plazo como contexto.
CURVA_TES_DEFECTO: dict[int, float] = {
    90: 0.1120,
    180: 0.1145,
    360: 0.1180,
    720: 0.1230,
    1800: 0.1280,
    3600: 0.1320,   # ~13,2% a 10 años (dato de referencia dado)
}

# Tenor de TES usado como vehículo del colchón de liquidez (corto plazo).
TENOR_LIQUIDEZ_DIAS: int = 90

# ---------------------------------------------------------------------------
# 6. RUTAS DE ARCHIVOS
# ---------------------------------------------------------------------------

import os as _os

_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
DIR_DATOS = _os.path.join(_RAIZ, "data")
DIR_REPORTES = _os.path.join(_RAIZ, "reports")

CSV_TASAS = _os.path.join(DIR_DATOS, "market_rates.csv")
CSV_CURVA_TES = _os.path.join(DIR_DATOS, "tes_curve.csv")
CSV_FONDEO = _os.path.join(DIR_DATOS, "funding_batch.csv")
CSV_CREDITOS = _os.path.join(DIR_DATOS, "credit_requests.csv")
