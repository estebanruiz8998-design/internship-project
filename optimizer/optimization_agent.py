"""Optimization Agent.

Busca sobre el MISMO pool invertible la asignación que maximiza el margen
esperado ajustado por riesgo, sujeta a todas las restricciones:

  * Presupuesto: lo colocado en crédito no puede invadir el colchón de liquidez.
  * Colchón de liquidez: MIN_LIQUIDITY_PCT del pool queda en TES corto.
  * Concentración: exposición de crédito por cooperativa <= MAX_COUNTERPARTY_PCT.
  * Calce de duración: la duración promedio ponderada de lo colocado debe quedar
    dentro de DURATION_TOLERANCE_DAYS respecto a la del fondeo. El tenor del TES
    remanente se usa como palanca de calce (ALM).

Como el número de solicitudes es pequeño, se enumeran exhaustivamente todos los
subconjuntos: la solución es óptima, no heurística. Devuelve las 3 mejores
alternativas (la recomendada + 2 opciones), no solo una.
"""

from __future__ import annotations

from itertools import combinations

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

# Límite de seguridad para la enumeración exhaustiva (2^N subconjuntos).
_MAX_ENUMERACION = 20


class OptimizationAgent:
    def __init__(self, mercado_snapshot: SnapshotMercado):
        self.snapshot = mercado_snapshot

    # -- utilidades internas ------------------------------------------------
    #
    # El objetivo es el MARGEN ANUALIZADO ajustado por riesgo (spread * monto),
    # neutral al plazo: no premia estirar duración para acumular carry. El tenor
    # del TES remanente se fija por CALCE de duración (elegir_tenor_calce), no
    # para maximizar margen, de modo que la ventaja provenga solo de qué créditos
    # se seleccionan.

    def _margen_credito(self, s: SolicitudCredito, cof: float) -> float:
        """Margen anualizado (spread ajustado por riesgo * monto)."""
        return s.monto_solicitado * (s.rendimiento_ajustado_ea - cof)

    def _margen_tes(self, monto: float, tenor: int, cof: float) -> float:
        """Margen anualizado del TES (spread sobre costo de fondos * monto)."""
        return monto * (self.snapshot.tes_por_tenor(tenor) - cof)

    def _tenores_parking(self) -> list[int]:
        return sorted(t for t in self.snapshot.curva_tes
                      if t <= config.MAX_TENOR_PARKING_DIAS)

    # -- optimización -------------------------------------------------------

    def optimizar(
        self, pool: PoolFondeo, solicitudes: list[SolicitudCredito],
        incluir_ids: frozenset[str] = frozenset(),
    ) -> list[Asignacion]:
        invertible = pool.monto_invertible
        cof = pool.costo_fondos_ea
        dur_fondeo = pool.duracion_ponderada_dias
        colchon = invertible * config.MIN_LIQUIDITY_PCT
        capacidad_credito = invertible - colchon
        tope_coop = invertible * config.MAX_COUNTERPARTY_PCT
        tenor_liq = config.TENOR_LIQUIDEZ_DIAS
        margen_colchon = self._margen_tes(colchon, tenor_liq, cof)
        tenores = self._tenores_parking()
        tol = config.DURATION_TOLERANCE_DAYS

        # Prefiltro: descartar solicitudes individualmente inviables (monto por
        # encima del cupo o del tope de concentración por sí solas).
        viables = [
            s for s in solicitudes
            if s.monto_solicitado <= capacidad_credito + 1e-6
            and s.monto_solicitado <= tope_coop + 1e-6
        ]
        if len(viables) > _MAX_ENUMERACION:
            # Salvaguarda de tamaño: quedarse con las de mayor densidad de margen,
            # PERO reteniendo siempre las que la línea base fondeó (incluir_ids).
            # Así la asignación de la línea base sigue estando dentro del espacio
            # de búsqueda y el delta óptima-vs-base nunca puede volverse negativo,
            # aun cuando se activa la truncación.
            forzadas = [s for s in viables if s.id in incluir_ids]
            resto = sorted(
                (s for s in viables if s.id not in incluir_ids),
                key=lambda s: self._margen_credito(s, cof) / s.monto_solicitado,
                reverse=True,
            )
            cupo = max(0, _MAX_ENUMERACION - len(forzadas))
            viables = forzadas + resto[:cupo]

        n = len(viables)
        candidatos: list[tuple[float, frozenset, dict]] = []

        for k in range(0, n + 1):
            for combo in combinations(range(n), k):
                subset = [viables[i] for i in combo]
                total_credito = sum(s.monto_solicitado for s in subset)
                if total_credito > capacidad_credito + 1e-6:
                    continue
                # Concentración por cooperativa.
                exp: dict[str, float] = {}
                ok = True
                for s in subset:
                    exp[s.cooperativa] = exp.get(s.cooperativa, 0.0) + s.monto_solicitado
                    if exp[s.cooperativa] > tope_coop + 1e-6:
                        ok = False
                        break
                if not ok:
                    continue

                remanente = capacidad_credito - total_credito
                base_num = (
                    sum(s.monto_solicitado * s.plazo_dias for s in subset)
                    + colchon * tenor_liq
                )
                factible, tenor_rem, _dur = elegir_tenor_calce(
                    base_num, remanente, invertible, dur_fondeo, tenores, tol
                )
                if not factible:
                    continue

                margen_rem = (
                    self._margen_tes(remanente, tenor_rem, cof)
                    if (remanente > 1e-6 and tenor_rem is not None) else 0.0
                )
                margen_total = (
                    sum(self._margen_credito(s, cof) for s in subset)
                    + margen_colchon
                    + margen_rem
                )
                candidatos.append((
                    margen_total,
                    frozenset(s.id for s in subset),
                    {"subset": subset, "remanente": remanente, "tenor_rem": tenor_rem},
                ))

        # Ordenar por margen y quedarse con las 3 mejores alternativas distintas.
        candidatos.sort(key=lambda c: c[0], reverse=True)
        vistos: set[frozenset] = set()
        top: list[Asignacion] = []
        for _margen, ids, info in candidatos:
            if ids in vistos:
                continue
            vistos.add(ids)
            top.append(self._construir_asignacion(
                info["subset"], info["remanente"], info["tenor_rem"],
                colchon, tenor_liq, pool, len(solicitudes),
                rango=len(top) + 1,
            ))
            if len(top) == 3:
                break
        return top

    def _construir_asignacion(
        self, subset, remanente, tenor_rem, colchon, tenor_liq,
        pool: PoolFondeo, total_solicitudes: int, rango: int,
    ) -> Asignacion:
        posiciones = [Posicion.desde_credito(s, s.monto_solicitado) for s in subset]
        posiciones.append(Posicion.tes(
            monto=colchon, tenor_dias=tenor_liq,
            rendimiento_ea=self.snapshot.tes_por_tenor(tenor_liq),
            etiqueta=f"TES {tenor_liq}d (colchón liquidez)",
        ))
        if remanente > 1e-6 and tenor_rem is not None:
            posiciones.append(Posicion.tes(
                monto=remanente, tenor_dias=tenor_rem,
                rendimiento_ea=self.snapshot.tes_por_tenor(tenor_rem),
                etiqueta=f"TES {tenor_rem}d (remanente, calce ALM)",
            ))

        etiqueta = "Óptima" if rango == 1 else f"Alternativa {rango}"
        asignacion = Asignacion(etiqueta=etiqueta, posiciones=posiciones)
        calcular_metricas_asignacion(
            asignacion, pool.costo_fondos_ea, total_solicitudes,
            horizonte_dias=pool.duracion_ponderada_dias,
            costo_encaje_anual=pool.encaje_total * pool.costo_fondos_ea,
        )
        return asignacion
