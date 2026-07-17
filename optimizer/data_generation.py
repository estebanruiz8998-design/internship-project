"""Generación de datos sintéticos del día.

Produce un lote diario con la forma de la actividad real de Coopcentral:
  * Snapshot de tasas de referencia (BanRep, IBR, DTF) y curva TES.
  * Lote de fondeo: emisiones de CDT Dorado y pagarés a la orden.
  * Solicitudes de crédito de tesorería de cooperativas afiliadas.

Los datos son SINTÉTICOS/ILUSTRATIVOS. Los nombres de cooperativas son
inventados: no corresponden a contrapartes reales, ni a estados financieros
o posiciones reales. La estructura de los productos y los niveles de tasa sí
replican los de Coopcentral y el mercado colombiano a julio de 2026.
"""

from __future__ import annotations

import csv
import os
import random

from . import config
from .domain import dtf_ta_a_ea


# Nombres de cooperativas INVENTADOS para la demostración.
_COOPERATIVAS = [
    "Cooperativa Financiera del Altiplano",
    "Coop. de Ahorro y Crédito Los Andes",
    "Fondo de Empleados Solidaridad Andina",
    "Cooperativa El Progreso del Oriente",
    "Cooperativa Agraria del Valle Verde",
    "Coop. Multiactiva Horizonte",
    "Cooperativa de Transportadores Unidos del Sur",
    "Cooperativa Médica San Rafael",
    "Fondo Cooperativo del Café",
    "Cooperativa Popular de Boyacá",
    "Cooperativa Educativa Nueva Granada",
    "Coop. de Vivienda Ciudad Región",
    "Cooperativa Industrial del Caribe",
    "Cooperativa Lechera del Norte",
    "Cooperativa de Comerciantes del Pacífico",
    "Fondo Solidario de los Llanos",
]


def _redondear_millones(monto: float, paso: float = 10_000_000) -> float:
    """Redondea a múltiplos de 10 millones (montos limpios como en la mesa)."""
    return round(monto / paso) * paso


def generar_snapshot_mercado() -> tuple[dict, dict]:
    """Devuelve (tasas_referencia, curva_tes) a partir de los valores por defecto.

    El E.A. de la DTF se DERIVA de su cotización nominal T.A. para que queden
    consistentes y quede demostrada la conversión de convención.
    """
    tasas = dict(config.TASAS_REFERENCIA_DEFECTO)
    tasas["dtf_ea"] = dtf_ta_a_ea(tasas["dtf_nominal_ta"])
    curva = dict(config.CURVA_TES_DEFECTO)
    return tasas, curva


def generar_lote_fondeo(rng: random.Random, tasas: dict) -> list[dict]:
    """Genera 9-13 instrumentos de fondeo (CDT Dorado / pagaré)."""
    n = rng.randint(9, 13)
    coops = rng.sample(_COOPERATIVAS, k=min(n, len(_COOPERATIVAS)))
    dtf = tasas["dtf_ea"]
    ibr3m = tasas["ibr_3m"]

    # Tasa pasiva base (lo que paga el banco) para CDT fija, por plazo.
    base_cdt_fija = {90: 0.0960, 180: 0.1000, 360: 0.1050}

    instrumentos = []
    for i in range(n):
        coop = coops[i % len(coops)]
        es_cdt = rng.random() < 0.70
        tipo = "CDT_DORADO" if es_cdt else "PAGARE"

        if es_cdt:
            # El grueso de los CDT es a 90/180 días; menos a 360.
            plazo = rng.choices([90, 180, 360], weights=[0.40, 0.40, 0.20])[0]
        else:
            # Pagaré a la orden: un solo vencimiento, mayormente a medio plazo.
            plazo = rng.choices([180, 270, 360], weights=[0.50, 0.30, 0.20])[0]

        monto = _redondear_millones(rng.uniform(200_000_000, 3_000_000_000))

        # Elección del tipo de tasa (con presencia deliberada de DTF).
        r = rng.random()
        if r < 0.55:
            tipo_tasa = "FIJA"
        elif r < 0.75:
            tipo_tasa = "DTF"
        else:
            tipo_tasa = "IBR"

        if tipo_tasa == "FIJA":
            base = base_cdt_fija.get(plazo, 0.1030)
            if not es_cdt:
                base += 0.0035  # el pagaré suele pagar un poco más
            tasa = base + rng.uniform(-0.0030, 0.0035)
            spread_bps = 0.0
        elif tipo_tasa == "DTF":
            spread_bps = rng.uniform(80, 200)
            tasa = dtf + spread_bps / 10_000.0
        else:  # IBR
            spread_bps = rng.uniform(60, 180)
            tasa = ibr3m + spread_bps / 10_000.0

        instrumentos.append({
            "id": f"F{i+1:02d}",
            "tipo": tipo,
            "cooperativa": coop,
            "monto": f"{monto:.0f}",
            "plazo_dias": plazo,
            "tipo_tasa": tipo_tasa,
            "spread_bps": f"{spread_bps:.1f}",
            "tasa_ea": f"{tasa:.6f}",
        })
    return instrumentos


def generar_solicitudes_credito(
    rng: random.Random, tasas: dict, pool_invertible_estimado: float
) -> list[dict]:
    """Genera solicitudes de crédito de tesorería.

    La demanda total se calibra MUY por encima de la capacidad de crédito (~1,8x
    el cupo tras el colchón de liquidez) para que la selección de a quién fondear
    sea una decisión real y no trivial: no alcanza para todos.

    Precio basado en riesgo PARCIAL: la prima por peor calificación NO compensa
    del todo la mayor pérdida esperada, de modo que el rendimiento AJUSTADO POR
    RIESGO cae con el riesgo. Así, los créditos de peor calificación pueden rendir
    menos que un TES: la ventaja del optimizador es justamente descartarlos.
    """
    dtf = tasas["dtf_ea"]
    ibr3m = tasas["ibr_3m"]

    capacidad_credito = pool_invertible_estimado * (1.0 - config.MIN_LIQUIDITY_PCT)
    objetivo_demanda = capacidad_credito * 1.80
    # Calificación con pesos realistas (la mayoría de la red es sólida).
    califs = ["A", "B", "C", "D"]
    pesos_calif = [0.30, 0.35, 0.25, 0.10]
    # Prima de tasa por calificación (compensa solo PARCIALMENTE la pérdida
    # esperada -> el rendimiento ajustado por riesgo baja con la calificación).
    prima_calif = {"A": 0.0000, "B": 0.0030, "C": 0.0075, "D": 0.0130}
    # Ajuste de tasa por plazo (más largo, un poco más alto).
    def ajuste_plazo(dias: int) -> float:
        return 0.0000 + (dias - 90) / 360.0 * 0.0080

    base_credito = 0.1300  # tasa base de crédito de tesorería (E.A.)

    solicitudes = []
    total = 0.0
    orden = 0
    coops_ciclo = _COOPERATIVAS[:]
    rng.shuffle(coops_ciclo)

    while total < objetivo_demanda and orden < 16:
        coop = coops_ciclo[orden % len(coops_ciclo)]
        # Tamaño como fracción del pool (3%-16%) para que la demanda escale con el
        # fondeo del día y la escasez sea consistente sin importar el tamaño.
        frac = rng.uniform(0.03, 0.16)
        monto = _redondear_millones(
            min(max(frac * pool_invertible_estimado, 200_000_000), 3_000_000_000)
        )
        # El crédito de tesorería de Coopcentral es de corto plazo (~90-180 días),
        # bullet a vencimiento; los plazos reflejan esa realidad.
        plazo = rng.choice([90, 120, 180])
        calif = rng.choices(califs, weights=pesos_calif, k=1)[0]

        r = rng.random()
        if r < 0.50:
            tipo_tasa = "FIJA"
        elif r < 0.70:
            tipo_tasa = "DTF"
        else:
            tipo_tasa = "IBR"

        # Componente idiosincrático (pricing de relación) para dispersar el
        # atractivo entre solicitudes de una misma calificación.
        nivel = base_credito + prima_calif[calif] + ajuste_plazo(plazo)
        nivel += rng.uniform(-0.0070, 0.0070)

        if tipo_tasa == "FIJA":
            spread_bps = 0.0
            tasa = nivel
        elif tipo_tasa == "DTF":
            spread_bps = (nivel - dtf) * 10_000.0
            tasa = nivel
        else:  # IBR
            spread_bps = (nivel - ibr3m) * 10_000.0
            tasa = nivel

        orden += 1
        solicitudes.append({
            "id": f"C{orden:02d}",
            "cooperativa": coop,
            "monto_solicitado": f"{monto:.0f}",
            "plazo_dias": plazo,
            "calificacion": calif,
            "tipo_tasa": tipo_tasa,
            "spread_bps": f"{spread_bps:.1f}",
            "tasa_ofrecida_ea": f"{tasa:.6f}",
            "orden_llegada": orden,
        })
        total += monto

    return solicitudes


def _escribir_csv(ruta: str, campos: list[str], filas: list[dict]) -> None:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)


def generar_todo(semilla: int | None = None) -> None:
    """Genera y escribe en disco todos los CSV de entrada del día."""
    semilla = config.SEMILLA_DEFECTO if semilla is None else semilla
    rng = random.Random(semilla)

    tasas, curva = generar_snapshot_mercado()

    # 1) Tasas de referencia.
    _escribir_csv(
        config.CSV_TASAS,
        ["clave", "valor"],
        [{"clave": k, "valor": f"{v:.6f}"} for k, v in tasas.items()],
    )

    # 2) Curva TES.
    _escribir_csv(
        config.CSV_CURVA_TES,
        ["tenor_dias", "rendimiento_ea"],
        [{"tenor_dias": t, "rendimiento_ea": f"{v:.6f}"} for t, v in sorted(curva.items())],
    )

    # 3) Lote de fondeo.
    fondeo = generar_lote_fondeo(rng, tasas)
    _escribir_csv(
        config.CSV_FONDEO,
        ["id", "tipo", "cooperativa", "monto", "plazo_dias", "tipo_tasa",
         "spread_bps", "tasa_ea"],
        fondeo,
    )

    # 4) Solicitudes de crédito (demanda calibrada > pool invertible).
    captado = sum(float(f["monto"]) for f in fondeo)
    invertible_estimado = captado * (1.0 - config.ENCAJE_PCT * 0.7)  # aprox.
    creditos = generar_solicitudes_credito(rng, tasas, invertible_estimado)
    _escribir_csv(
        config.CSV_CREDITOS,
        ["id", "cooperativa", "monto_solicitado", "plazo_dias", "calificacion",
         "tipo_tasa", "spread_bps", "tasa_ofrecida_ea", "orden_llegada"],
        creditos,
    )


if __name__ == "__main__":
    generar_todo()
    print("Datos sintéticos generados en", config.DIR_DATOS)
