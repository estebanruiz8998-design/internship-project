"""Reporting Agent.

Produce el informe de una página (HTML autocontenido, estilo memo interno) que
verá el jefe de la mesa. Es el ÚNICO agente cuya salida ve directamente un
lector no técnico.

Contiene: fondeo del día y costo de fondos; comparación lado a lado de la
asignación base vs. la optimizada (margen en bps y en COP); el delta en COP en
tipografía grande; el racional en lenguaje llano; y la lista visible de cada
restricción verificada y aprobada.

Sin dependencias externas: HTML + CSS embebidos + gráfico SVG en línea.
"""

from __future__ import annotations

import html
import os

from . import config
from .domain import (
    Asignacion,
    PoolFondeo,
    ResultadoCumplimiento,
    SnapshotMercado,
    SolicitudCredito,
    dtf_ta_a_ea,
    formato_bps,
    formato_cop,
    formato_cop_mm,
    formato_pct,
)

# --- Paleta (validada, modo claro; ver skill dataviz / palette.md) ----------
_COL_SURFACE = "#fcfcfb"
_COL_PLANE = "#f9f9f7"
_COL_INK = "#0b0b0b"
_COL_INK2 = "#52514e"
_COL_MUTED = "#898781"
_COL_GRID = "#e1e0d9"
_COL_BORDER = "rgba(11,11,11,0.10)"
_COL_BASE = "#898781"     # línea base -> gris neutro (la opción menor)
_COL_OPT = "#2a78d6"      # optimizada -> azul primario (el foco)
_COL_GOOD = "#006300"     # delta positivo / check aprobado
_COL_CRIT = "#d03b3b"     # check reprobado


def _e(texto: str) -> str:
    return html.escape(str(texto))


def _svg_comparacion(base_cop: float, opt_cop: float) -> str:
    """Gráfico de barras horizontal: margen COP base vs. optimizada."""
    ancho, alto = 620, 150
    x0, x_max = 12, 470          # área de barras
    max_val = max(base_cop, opt_cop, 1.0)

    def barra(y, val, color, etiqueta):
        w = (val / max_val) * (x_max - x0)
        w = max(w, 2.0)
        return (
            f'<text x="{x0}" y="{y - 9}" font-size="13" fill="{_COL_INK2}">{etiqueta}</text>'
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="26" rx="4" fill="{color}"/>'
            f'<text x="{x0 + w + 8:.1f}" y="{y + 18}" font-size="14" '
            f'fill="{_COL_INK}" font-weight="600" style="font-variant-numeric:tabular-nums">'
            f'{_e(formato_cop(val))}</text>'
        )

    return (
        f'<svg viewBox="0 0 {ancho} {alto}" width="100%" role="img" '
        f'aria-label="Comparación de margen en COP entre la asignación base y la optimizada">'
        f'{barra(30, base_cop, _COL_BASE, "Línea base (manual)")}'
        f'{barra(95, opt_cop, _COL_OPT, "Asignación optimizada")}'
        f'</svg>'
    )


def _tiles_fondeo(pool: PoolFondeo) -> str:
    tiles = [
        ("Fondeo captado hoy", formato_cop(pool.monto_captado_bruto),
         f"{len(pool.instrumentos)} instrumentos (CDT Dorado + pagarés)"),
        ("Encaje retenido", formato_cop(pool.encaje_total),
         f"{formato_pct(config.ENCAJE_PCT)} sobre CDT (< 18 meses)"),
        ("Pool invertible", formato_cop(pool.monto_invertible),
         "neto de encaje, a desplegar"),
        ("Costo de fondos (WACF)", formato_pct(pool.costo_fondos_ea),
         "tasa pasiva promedio ponderada E.A."),
    ]
    celdas = ""
    for titulo, valor, sub in tiles:
        celdas += (
            f'<div class="tile">'
            f'<div class="tile-t">{_e(titulo)}</div>'
            f'<div class="tile-v">{_e(valor)}</div>'
            f'<div class="tile-s">{_e(sub)}</div>'
            f'</div>'
        )
    return f'<div class="tiles">{celdas}</div>'


def _panel_estrategia(a: Asignacion, cof: float, destacada: bool) -> str:
    clase = "panel panel-opt" if destacada else "panel panel-base"
    filas = [
        ("Margen (anualizado)", formato_bps(a.margen_bps)),
        ("Margen en COP (sobre plazo)", formato_cop(a.margen_cop_total)),
        ("Colocado en crédito", formato_cop(a.monto_en_credito)),
        ("Estacionado en TES", formato_cop(a.monto_en_tes)),
        ("Solicitudes fondeadas", f"{a.creditos_fondeados} de "
         f"{a.creditos_fondeados + a.creditos_rechazados}"),
        ("Duración despliegue", f"{a.duracion_ponderada_dias:.0f} días"),
    ]
    cuerpo = ""
    for k, v in filas:
        cuerpo += (
            f'<div class="row"><span class="row-k">{_e(k)}</span>'
            f'<span class="row-v">{_e(v)}</span></div>'
        )
    titulo = "Asignación optimizada" if destacada else "Línea base (manual · por orden de llegada)"
    return f'<div class="{clase}"><h3>{_e(titulo)}</h3>{cuerpo}</div>'


def _checklist(cumplimiento: ResultadoCumplimiento) -> str:
    filas = ""
    for c in cumplimiento.checks:
        icono = "✓" if c.aprobado else "✗"
        color = _COL_GOOD if c.aprobado else _COL_CRIT
        estado = "APROBADO" if c.aprobado else "RECHAZADO"
        filas += (
            f'<tr>'
            f'<td class="chk" style="color:{color}">{icono}</td>'
            f'<td>{_e(c.nombre)}</td>'
            f'<td class="mono">{_e(c.limite)}</td>'
            f'<td class="mono">{_e(c.observado)}</td>'
            f'<td style="color:{color};font-weight:600">{_e(estado)}</td>'
            f'</tr>'
        )
    return (
        '<table class="checks"><thead><tr>'
        '<th></th><th>Restricción verificada</th><th>Límite</th>'
        '<th>Observado</th><th>Estado</th></tr></thead>'
        f'<tbody>{filas}</tbody></table>'
    )


def _tabla_decisiones(
    solicitudes: list[SolicitudCredito],
    optimizada: Asignacion,
    baseline: Asignacion,
) -> str:
    ids_opt = {p.referencia for p in optimizada.posiciones_credito()}
    ids_base = {p.referencia for p in baseline.posiciones_credito()}
    filas = ""
    for s in sorted(solicitudes, key=lambda x: x.orden_llegada):
        en_opt = s.id in ids_opt
        en_base = s.id in ids_base
        dec_opt = "Fondeada" if en_opt else "Rechazada"
        color_opt = _COL_GOOD if en_opt else _COL_MUTED
        dtf = ' <span class="badge">DTF</span>' if s.indexado_dtf else ""
        filas += (
            f'<tr>'
            f'<td class="mono">{_e(s.id)}</td>'
            f'<td>{_e(s.cooperativa)}{dtf}</td>'
            f'<td class="mono">{_e(s.calificacion)}</td>'
            f'<td class="mono num">{_e(formato_cop_mm(s.monto_solicitado))}</td>'
            f'<td class="mono num">{_e(str(s.plazo_dias))}d</td>'
            f'<td class="mono num">{_e(formato_pct(s.tasa_ofrecida_ea))}</td>'
            f'<td class="mono num">{_e(formato_pct(s.rendimiento_ajustado_ea))}</td>'
            f'<td class="mono">{"Sí" if en_base else "No"}</td>'
            f'<td class="mono" style="color:{color_opt};font-weight:600">{dec_opt}</td>'
            f'</tr>'
        )
    return (
        '<table class="detalle"><thead><tr>'
        '<th>ID</th><th>Cooperativa</th><th>Calif.</th><th>Monto</th>'
        '<th>Plazo</th><th>Tasa</th><th>Ajust. riesgo</th>'
        '<th>Base</th><th>Óptima</th></tr></thead>'
        f'<tbody>{filas}</tbody></table>'
    )


def _tira_mercado(snapshot: SnapshotMercado) -> str:
    dtf_ea = snapshot.dtf_ea
    tes_corto = snapshot.tes_por_tenor(360)
    tes_largo = snapshot.curva_tes.get(3600, tes_corto)
    items = [
        ("BanRep (política)", formato_pct(snapshot.banrep_politica)),
        ("IBR overnight", formato_pct(snapshot.ibr_overnight)),
        ("IBR 3M", formato_pct(snapshot.ibr_3m)),
        ("DTF (nom. T.A.)", formato_pct(snapshot.dtf_nominal_ta)),
        ("DTF (E.A.)", formato_pct(dtf_ea)),
        ("TES ~1a", formato_pct(tes_corto)),
        ("TES ~10a", formato_pct(tes_largo)),
    ]
    celdas = "".join(
        f'<div class="m-item"><span class="m-k">{_e(k)}</span>'
        f'<span class="m-v">{_e(v)}</span></div>'
        for k, v in items
    )
    return f'<div class="mkt">{celdas}</div>'


def _alternativas(alts: list[Asignacion], baseline_cop: float) -> str:
    if not alts:
        return ""
    filas = ""
    for a in alts:
        delta = a.margen_cop_total - baseline_cop
        pos = delta >= -1.0
        sg = "+" if pos else "−"
        col = _COL_GOOD if pos else _COL_CRIT
        filas += (
            f'<tr><td>{_e(a.etiqueta)}</td>'
            f'<td class="mono num">{_e(formato_bps(a.margen_bps))}</td>'
            f'<td class="mono num">{_e(formato_cop(a.margen_cop_total))}</td>'
            f'<td class="mono num">{_e(a.creditos_fondeados)} créditos</td>'
            f'<td class="mono num" style="color:{col}">{sg}{_e(formato_cop(abs(delta)))}</td>'
            f'</tr>'
        )
    return (
        '<table class="detalle"><thead><tr>'
        '<th>Alternativa (también aprobada por cumplimiento)</th>'
        '<th>Margen</th><th>Margen COP</th><th>Créditos</th>'
        '<th>Δ vs. base</th></tr></thead>'
        f'<tbody>{filas}</tbody></table>'
    )


_CSS = """
:root{
  --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --border:rgba(11,11,11,0.10);
  --base:#898781; --opt:#2a78d6; --good:#006300;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45;}
.page{max-width:900px;margin:24px auto;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:34px 40px;}
header.top{display:flex;justify-content:space-between;align-items:flex-start;
  border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:6px;}
.brand{font-size:20px;font-weight:700;letter-spacing:-.01em}
.brand small{display:block;font-weight:500;color:var(--ink2);font-size:13px;
  letter-spacing:0;margin-top:2px}
.meta{text-align:right;font-size:12.5px;color:var(--ink2)}
h2.sec{font-size:13px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin:30px 0 12px;font-weight:700}
.mkt{display:flex;flex-wrap:wrap;gap:0;border:1px solid var(--border);
  border-radius:8px;overflow:hidden;margin-top:14px}
.m-item{flex:1 1 auto;padding:8px 12px;border-right:1px solid var(--grid);
  display:flex;flex-direction:column;min-width:96px}
.m-item:last-child{border-right:none}
.m-k{font-size:11px;color:var(--muted)}
.m-v{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.tile{border:1px solid var(--border);border-radius:8px;padding:14px 16px;background:var(--surface)}
.tile-t{font-size:12px;color:var(--ink2)}
.tile-v{font-size:21px;font-weight:700;margin:4px 0 2px;letter-spacing:-.01em}
.tile-s{font-size:11.5px;color:var(--muted)}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.panel{border:1px solid var(--border);border-radius:8px;padding:16px 18px}
.panel-opt{border:1.5px solid var(--opt);box-shadow:0 0 0 3px rgba(42,120,214,.06)}
.panel h3{margin:0 0 10px;font-size:14px}
.panel-opt h3{color:var(--opt)}
.row{display:flex;justify-content:space-between;padding:5px 0;
  border-bottom:1px solid var(--grid);font-size:13px}
.row:last-child{border-bottom:none}
.row-k{color:var(--ink2)}
.row-v{font-weight:600;font-variant-numeric:tabular-nums}
.hero{margin:22px 0 6px;border:1px solid var(--border);border-radius:10px;
  background:linear-gradient(0deg,rgba(0,99,0,.04),rgba(0,99,0,.04)),var(--surface);
  padding:20px 24px;display:flex;align-items:center;justify-content:space-between;gap:20px}
.hero-l .hero-k{font-size:13px;color:var(--ink2)}
.hero-l .hero-sub{font-size:12.5px;color:var(--muted);margin-top:4px}
.hero-v{font-size:40px;font-weight:800;color:var(--good);letter-spacing:-.02em;
  line-height:1;white-space:nowrap}
.hero-bps{font-size:14px;color:var(--good);font-weight:600;text-align:right;margin-top:6px}
.rationale{border-left:3px solid var(--opt);background:var(--plane);
  padding:12px 16px;border-radius:0 8px 8px 0;font-size:13.5px;color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
.checks th,.checks td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid)}
.checks th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.checks .chk{font-size:15px;font-weight:800;text-align:center;width:24px}
.mono{font-variant-numeric:tabular-nums}
.num{text-align:right;white-space:nowrap}
.detalle th,.detalle td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:left}
.detalle th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.detalle tbody tr:hover{background:var(--plane)}
.badge{display:inline-block;font-size:9.5px;font-weight:700;color:#8a5a00;
  background:#fdeecb;border-radius:4px;padding:1px 4px;vertical-align:middle}
.svgbox{border:1px solid var(--border);border-radius:8px;padding:14px 16px 6px}
footer.foot{margin-top:26px;padding-top:12px;border-top:1px solid var(--grid);
  font-size:11px;color:var(--muted);line-height:1.5}
@media print{body{background:#fff}.page{border:none;margin:0;max-width:none}}
@media (max-width:720px){.tiles{grid-template-columns:repeat(2,1fr)}
  .compare{grid-template-columns:1fr}.hero{flex-direction:column;align-items:flex-start}}
"""


class ReportingAgent:
    def generar(
        self,
        fecha: str,
        pool: PoolFondeo,
        snapshot: SnapshotMercado,
        solicitudes: list[SolicitudCredito],
        baseline: Asignacion,
        optimizada: Asignacion,
        alternativas: list[Asignacion],
        cumplimiento: ResultadoCumplimiento,
        rationale: str,
        semilla: int,
        ruta_salida: str | None = None,
    ) -> str:
        delta_cop = optimizada.margen_cop_total - baseline.margen_cop_total
        delta_bps = optimizada.margen_bps - baseline.margen_bps
        pos = delta_cop >= -1.0
        signo = "+" if pos else "−"
        flecha = "▲" if pos else "▼"
        color_delta = _COL_GOOD if pos else _COL_CRIT

        # La sección de alternativas solo se muestra si hay alternativas.
        seccion_alts = (
            '<h2 class="sec">Alternativas evaluadas</h2>'
            + _alternativas(alternativas, baseline.margen_cop_total)
        ) if alternativas else ""

        cuerpo = f"""
<div class="page">
  <header class="top">
    <div class="brand">Banco Cooperativo Coopcentral
      <small>Mesa de Tesorería · Renta Fija — Optimizador Diario de Margen (prueba de concepto)</small>
    </div>
    <div class="meta">
      Fecha de operación: <b>{_e(fecha)}</b><br>
      Corrida sintética · semilla {_e(semilla)}<br>
      Transición DTF→IBR: {_e(snapshot.fecha_transicion_ibr)}
    </div>
  </header>

  <h2 class="sec">Referencias de mercado del día</h2>
  {_tira_mercado(snapshot)}

  <h2 class="sec">Fondeo del día</h2>
  {_tiles_fondeo(pool)}

  <h2 class="sec">Asignación: manual (statu quo) vs. optimizada</h2>
  <div class="compare">
    {_panel_estrategia(baseline, pool.costo_fondos_ea, destacada=False)}
    {_panel_estrategia(optimizada, pool.costo_fondos_ea, destacada=True)}
  </div>

  <div class="hero">
    <div class="hero-l">
      <div class="hero-k">Margen adicional capturado por la optimización (sobre el plazo)</div>
      <div class="hero-sub">Mismo pool, mismas reglas de cumplimiento · dos rutas de código distintas</div>
    </div>
    <div>
      <div class="hero-v" style="color:{color_delta}">{signo}{_e(formato_cop(abs(delta_cop)))}</div>
      <div class="hero-bps" style="color:{color_delta}">{flecha} {signo}{_e(formato_bps(abs(delta_bps)))} de margen anualizado</div>
    </div>
  </div>

  <div class="svgbox">{_svg_comparacion(baseline.margen_cop_total, optimizada.margen_cop_total)}</div>

  <h2 class="sec">Por qué esta asignación</h2>
  <div class="rationale">{_e(rationale)}</div>

  <h2 class="sec">Restricciones verificadas (control independiente de cumplimiento)</h2>
  {_checklist(cumplimiento)}

  <h2 class="sec">Detalle de decisiones por solicitud</h2>
  {_tabla_decisiones(solicitudes, optimizada, baseline)}

  {seccion_alts}

  <footer class="foot">
    Esta corrida utiliza datos sintéticos/ilustrativos, estructurados sobre los
    productos reales de Coopcentral (CDT Dorado, pagarés a la orden, crédito de
    tesorería) y sobre niveles de mercado publicados a julio de 2026 (BanRep ~12%,
    TES 10a ~13,2%). Los nombres de cooperativas son inventados; no corresponden a
    contrapartes, estados financieros ni posiciones reales. Base de la transición
    DTF→IBR: {_e(config.BASE_LEGAL_TRANSICION)}. Pendiente de aprobación para
    conectar con datos reales de la mesa.
  </footer>
</div>
"""

        documento = (
            "<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>Optimizador de Margen — Coopcentral — {_e(fecha)}</title>"
            f"<style>{_CSS}</style></head><body>{cuerpo}</body></html>"
        )

        ruta = ruta_salida or os.path.join(config.DIR_REPORTES, "informe_tesoreria.html")
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(documento)
        return ruta
