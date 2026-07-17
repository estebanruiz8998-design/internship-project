"""Modelo de dominio y utilidades financieras compartidas.

Define las estructuras de datos que fluyen entre los agentes y las funciones
de cálculo financiero que TODOS los agentes usan, para que el margen en puntos
básicos (bps) y en pesos (COP) sea consistente en todo el pipeline.

Supuestos de cálculo (documentados para poder defenderlos ante preguntas):
  * Base Actual/365.
  * El interés de una posición se prorratea con el factor efectivo
    (1 + tasa_E.A.)^(dias/365) - 1.
  * El costo de fondos usado para el margen es la tasa pasiva promedio
    ponderada del día (WACF, weighted average cost of funds).
  * El margen de una posición es un proxy de margen neto de intereses (NIM):
    monto * (rendimiento_ajustado - costo_de_fondos_prorrateado_al_plazo).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config


# ---------------------------------------------------------------------------
# Utilidades financieras
# ---------------------------------------------------------------------------

def factor_periodico(tasa_ea: float, dias: int) -> float:
    """Interés efectivo acumulado para un plazo, a partir de una tasa E.A.

    Devuelve (1 + tasa_ea)^(dias/365) - 1.
    """
    return (1.0 + tasa_ea) ** (dias / config.BASE_DIAS) - 1.0


def dtf_ta_a_ea(dtf_nominal_ta: float) -> float:
    """Convierte DTF nominal trimestre anticipado (T.A.) a Efectivo Anual (E.A.).

    Paso 1: pasar de anticipada a vencida en el trimestre.
    Paso 2: capitalizar cuatro trimestres.
        i_vencida_trim = (dtf_ta/4) / (1 - dtf_ta/4)
        E.A. = (1 + i_vencida_trim)^4 - 1
    """
    i_ant_trim = dtf_nominal_ta / 4.0
    i_venc_trim = i_ant_trim / (1.0 - i_ant_trim)
    return (1.0 + i_venc_trim) ** 4 - 1.0


def formato_cop(monto: float, decimales: int = 0) -> str:
    """Formatea un monto en pesos colombianos: '$ 1.234.567.890'.

    Usa punto como separador de miles (convención colombiana).
    """
    if decimales > 0:
        entero, frac = f"{monto:,.{decimales}f}".split(".")
        entero = entero.replace(",", ".")
        return f"$ {entero},{frac}"
    entero = f"{monto:,.0f}".replace(",", ".")
    return f"$ {entero}"


def formato_cop_mm(monto: float) -> str:
    """Formato compacto en millones de COP: 1_730_000_000 -> '$ 1.730 M'."""
    entero = f"{monto / 1e6:,.0f}".replace(",", ".")
    return f"$ {entero} M"


def formato_pct(fraccion: float, decimales: int = 2) -> str:
    """Formatea una fracción como porcentaje: 0.1234 -> '12,34%'."""
    return f"{fraccion * 100:.{decimales}f}".replace(".", ",") + "%"


def formato_bps(bps: float, decimales: int = 0) -> str:
    """Formatea puntos básicos: 350 -> '350 bps'."""
    txt = f"{bps:,.{decimales}f}".replace(",", ".")
    return f"{txt} bps"


# ---------------------------------------------------------------------------
# Estructuras: mercado
# ---------------------------------------------------------------------------

@dataclass
class SnapshotMercado:
    """Fotografía de tasas de referencia del día."""
    banrep_politica: float
    ibr_overnight: float
    ibr_1m: float
    ibr_3m: float
    dtf_ea: float
    dtf_nominal_ta: float
    curva_tes: dict[int, float]              # tenor_dias -> rendimiento E.A.
    fecha_transicion_ibr: str

    def tes_por_tenor(self, dias: int) -> float:
        """Rendimiento TES del tenor de la curva más cercano al plazo pedido."""
        tenor = min(self.curva_tes.keys(), key=lambda t: abs(t - dias))
        return self.curva_tes[tenor]

    def tenor_tes_mas_cercano(self, dias: int) -> int:
        return min(self.curva_tes.keys(), key=lambda t: abs(t - dias))


# ---------------------------------------------------------------------------
# Estructuras: fondeo (lado pasivo)
# ---------------------------------------------------------------------------

@dataclass
class InstrumentoFondeo:
    """Un CDT Dorado o un pagaré a la orden captado hoy."""
    id: str
    tipo: str                 # 'CDT_DORADO' | 'PAGARE'
    cooperativa: str
    monto: float              # COP captados (nominal)
    plazo_dias: int
    tipo_tasa: str            # 'FIJA' | 'DTF' | 'IBR'
    spread_bps: float         # spread sobre el índice (0 si FIJA)
    tasa_ea: float            # tasa pasiva efectiva del instrumento (E.A.)

    # Rellenados por el Funding Agent:
    indexado_dtf: bool = False           # bandera de riesgo de transición
    encaje_aplicado: float = 0.0         # COP retenidos por encaje
    monto_invertible: float = 0.0        # COP disponibles tras encaje

    @property
    def es_deposito(self) -> bool:
        """Los CDT son depósitos (aplican encaje); los pagarés no."""
        return self.tipo == "CDT_DORADO"


# ---------------------------------------------------------------------------
# Estructuras: demanda (lado activo) y riesgo
# ---------------------------------------------------------------------------

@dataclass
class SolicitudCredito:
    """Una solicitud de crédito de tesorería de una cooperativa afiliada."""
    id: str
    cooperativa: str
    monto_solicitado: float
    plazo_dias: int
    calificacion: str          # 'A' | 'B' | 'C' | 'D'
    tipo_tasa: str             # 'FIJA' | 'DTF' | 'IBR'
    spread_bps: float
    tasa_ofrecida_ea: float    # tasa que pagaría la cooperativa (E.A.)
    orden_llegada: int         # para el heurístico FCFS de la línea base

    # Rellenados por el Demand & Risk Agent:
    indexado_dtf: bool = False
    pd_anual: float = 0.0
    lgd: float = 0.0
    perdida_esperada_anual: float = 0.0    # PD * LGD (fracción anual)
    haircut_transicion: float = 0.0        # castigo por riesgo DTF (fracción)
    rendimiento_ajustado_ea: float = 0.0   # tasa ofrecida - EL - haircut


# ---------------------------------------------------------------------------
# Estructuras: fondeo consolidado y posiciones desplegadas
# ---------------------------------------------------------------------------

@dataclass
class PoolFondeo:
    """Resultado del Funding Agent: el pool invertible del día."""
    instrumentos: list[InstrumentoFondeo]
    monto_captado_bruto: float
    encaje_total: float
    monto_invertible: float
    costo_fondos_ea: float          # tasa pasiva promedio ponderada (WACF)
    duracion_ponderada_dias: float
    monto_indexado_dtf: float


@dataclass
class Posicion:
    """Una posición desplegada: un crédito colocado o una compra de TES."""
    clase: str                 # 'CREDITO' | 'TES'
    referencia: str            # id del crédito o etiqueta del TES
    cooperativa: str           # nombre o 'MERCADO (TES)'
    monto: float
    plazo_dias: int
    rendimiento_ea: float      # rendimiento bruto E.A.
    rendimiento_ajustado_ea: float  # neto de pérdida esperada / haircut
    indexado_dtf: bool = False

    def margen_cop(self, costo_fondos_ea: float) -> float:
        """Margen en COP de la posición sobre su plazo (proxy NIM)."""
        rend = factor_periodico(self.rendimiento_ajustado_ea, self.plazo_dias)
        cof = factor_periodico(costo_fondos_ea, self.plazo_dias)
        return self.monto * (rend - cof)

    def spread_anual(self, costo_fondos_ea: float) -> float:
        """Spread anualizado (fracción) sobre el costo de fondos."""
        return self.rendimiento_ajustado_ea - costo_fondos_ea

    @classmethod
    def desde_credito(cls, solicitud: "SolicitudCredito", monto: float) -> "Posicion":
        """Construye una posición de crédito a partir de una solicitud."""
        return cls(
            clase="CREDITO",
            referencia=solicitud.id,
            cooperativa=solicitud.cooperativa,
            monto=monto,
            plazo_dias=solicitud.plazo_dias,
            rendimiento_ea=solicitud.tasa_ofrecida_ea,
            rendimiento_ajustado_ea=solicitud.rendimiento_ajustado_ea,
            indexado_dtf=solicitud.indexado_dtf,
        )

    @classmethod
    def tes(cls, monto: float, tenor_dias: int, rendimiento_ea: float,
            etiqueta: str) -> "Posicion":
        """Construye una posición de TES (sin pérdida esperada: libre de riesgo)."""
        return cls(
            clase="TES",
            referencia=etiqueta,
            cooperativa="MERCADO (TES)",
            monto=monto,
            plazo_dias=tenor_dias,
            rendimiento_ea=rendimiento_ea,
            rendimiento_ajustado_ea=rendimiento_ea,
            indexado_dtf=False,
        )


@dataclass
class Asignacion:
    """Una asignación completa del pool (línea base u optimizada)."""
    etiqueta: str
    posiciones: list[Posicion] = field(default_factory=list)

    # Métricas calculadas (rellenadas por quien construye la asignación):
    margen_cop_total: float = 0.0
    margen_bps: float = 0.0                 # spread anualizado ponderado (bps)
    monto_en_credito: float = 0.0
    monto_en_tes: float = 0.0
    creditos_fondeados: int = 0
    creditos_rechazados: int = 0
    duracion_ponderada_dias: float = 0.0
    exposicion_por_cooperativa: dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def posiciones_credito(self) -> list[Posicion]:
        return [p for p in self.posiciones if p.clase == "CREDITO"]

    def posiciones_tes(self) -> list[Posicion]:
        return [p for p in self.posiciones if p.clase == "TES"]


def elegir_tenor_calce(
    base_num: float,
    remanente: float,
    pool: float,
    duracion_fondeo: float,
    tenores: list[int],
    tolerancia: float,
) -> tuple[bool, int | None, float]:
    """Elige el tenor del TES remanente para CALZAR la duración del fondeo.

    Regla de calce puro (no de carry): entre los tenores permitidos, escoge el
    que deja la duración de despliegue MÁS CERCA de la del fondeo. Es factible si
    esa cercanía queda dentro de la tolerancia. La usan de forma idéntica la
    línea base y la optimización, así que el tenor no es una palanca de margen:
    la ventaja proviene solo de la selección de créditos.

    base_num = numerador de duración de lo ya fijo (créditos + colchón).
    Devuelve (factible, tenor, duracion_despliegue).
    """
    if remanente <= 1e-6:
        dur = base_num / pool if pool else 0.0
        return (abs(dur - duracion_fondeo) <= tolerancia, None, dur)

    mejor = None  # (|brecha|, tenor, dur)
    for t in tenores:
        dur = (base_num + remanente * t) / pool
        brecha = abs(dur - duracion_fondeo)
        if mejor is None or brecha < mejor[0]:
            mejor = (brecha, t, dur)
    if mejor is None:
        return (False, None, 0.0)
    return (mejor[0] <= tolerancia, mejor[1], mejor[2])


def calcular_metricas_asignacion(
    asignacion: "Asignacion",
    costo_fondos_ea: float,
    total_solicitudes: int,
    horizonte_dias: float,
) -> None:
    """Calcula y rellena las métricas de una asignación (in place).

    Usado de forma IDÉNTICA por la línea base y por la optimización, para que el
    margen en bps y en COP sea comparable entre ambas rutas de código.

      * margen_bps       : spread anualizado promedio ponderado por monto (bps).
                           Métrica NEUTRAL AL HORIZONTE (por año), la comparable.
      * margen_cop_total : ese margen anualizado llevado al horizonte de fondeo
                           común (mismo horizonte para ambas estrategias), de modo
                           que el delta en COP NO es un artefacto de plazos: refleja
                           mejor selección, no simplemente activos más largos.
      * duracion         : plazo promedio ponderado por monto.
    """
    posiciones = asignacion.posiciones
    monto_total = sum(p.monto for p in posiciones)

    if monto_total > 0:
        asignacion.margen_bps = (
            sum(p.monto * p.spread_anual(costo_fondos_ea) for p in posiciones)
            / monto_total
        ) * 10_000.0
        asignacion.duracion_ponderada_dias = (
            sum(p.monto * p.plazo_dias for p in posiciones) / monto_total
        )
    else:
        asignacion.margen_bps = 0.0
        asignacion.duracion_ponderada_dias = 0.0

    asignacion.margen_cop_total = (
        (asignacion.margen_bps / 10_000.0) * monto_total * (horizonte_dias / config.BASE_DIAS)
    )

    creditos = asignacion.posiciones_credito()
    asignacion.monto_en_credito = sum(p.monto for p in creditos)
    asignacion.monto_en_tes = sum(p.monto for p in asignacion.posiciones_tes())
    asignacion.creditos_fondeados = len(creditos)
    asignacion.creditos_rechazados = total_solicitudes - len(creditos)

    exp: dict[str, float] = {}
    for p in creditos:
        exp[p.cooperativa] = exp.get(p.cooperativa, 0.0) + p.monto
    asignacion.exposicion_por_cooperativa = exp


@dataclass
class ResultadoCumplimiento:
    """Salida del Guardrail Agent para una asignación."""
    etiqueta: str
    aprobada: bool
    checks: list["CheckCumplimiento"] = field(default_factory=list)


@dataclass
class CheckCumplimiento:
    """Un control individual de cumplimiento."""
    nombre: str
    aprobado: bool
    detalle: str
    limite: str = ""
    observado: str = ""
