"""
=============================================================================
COMPARACIÓN MODELO 0 (DETERMINISTA) vs MODELO 2 (ESTOCÁSTICO)
Valor de la Solución Estocástica (VSS)
Proyecto NexusFlex — TFG
=============================================================================
Objetivo:
    Comparar correctamente el Modelo 0 y el Modelo 2 para contrastar la
    Hipótesis 2. La métrica central es el VSS (Value of the Stochastic
    Solution), que mide cuánto se gana usando la solución estocástica frente
    a la determinista, AMBAS evaluadas sobre los MISMOS 3 escenarios.

        RP  = valor esperado del Modelo 2 (anticipa la incertidumbre).
        EEV = se toma la decisión de 1ª etapa del Modelo 0 (la cesión a Nexus
              x_PtoN) y se evalúa en los 3 escenarios, dejando reaccionar solo
              el recurso (autoconsumo, compra a red, redistribución, venta).
        VSS = RP - EEV   (siempre >= 0 en maximización).

    DECISIÓN DE MODELADO (opción A):
        1ª etapa  = x_PtoN[i,t]  (cesión a Nexus, común a los 3 escenarios).
        2ª etapa  = todo lo demás (se ajusta a cada escenario).

Enfoque de cálculo del EEV (robusto, sin infactibilidad):
    Una vez fijada la cesión x_PtoN, el resto de flujos quedan determinados
    por los balances físicos, salvo la asignación de Nexus entre agentes con
    déficit, que es la única decisión de recurso con grados de libertad.
    El EEV se evalúa directamente con la misma fórmula de beneficio del
    Modelo 0, sin necesidad de fijar variables dentro del solver (lo que
    causaba infactibilidad). La cesión se recorta en cada escenario al
    excedente realmente disponible, igual que hace el anti-arbitraje:
        x_PtoN_w = min( x_PtoN*,  max(0, GEF_w - CE_P_w) )

    Esto es exacto porque, dada la cesión, el reparto óptimo de Nexus que
    minimiza el coste es trivial: entregar al máximo posible a los agentes
    con déficit (sustituye compra a p_red por compra a p_mkt < p_red, lo que
    siempre conviene) y vender a la red solo el sobrante.
=============================================================================
"""

import os
import pandas as pd

import modelo_0_determinista as M0
import modelo_2_estocastico  as M2


# =============================================================================
# CONFIGURACIÓN (heredada del Modelo 2 para coherencia total)
# =============================================================================
N_INTERVALOS     = M2.N_INTERVALOS
IDS_PROSUMIDORES = M2.IDS_PROSUMIDORES
IDS_CONSUMIDORES = M2.IDS_CONSUMIDORES
ALPHA            = M2.ALPHA
ESCENARIOS       = M2.ESCENARIOS
CARPETA_OUTPUTS  = M2.CARPETA_OUTPUTS
os.makedirs(CARPETA_OUTPUTS, exist_ok=True)

T = range(1, N_INTERVALOS + 1)


# =============================================================================
# 1. CARGA DE DATOS Y PRECIOS (reutiliza las funciones del Modelo 2)
# =============================================================================

def cargar_todo():
    print("=" * 70)
    print("CARGA DE DATOS Y PRECIOS")
    print("=" * 70)

    GEF, CE_P, CE_C = M2.cargar_datos_excel(
        M2.RUTA_EXCEL, IDS_PROSUMIDORES, IDS_CONSUMIDORES, N_INTERVALOS
    )
    p_red, p_mkt, p_ahorro = M2.obtener_precios_pvpc(
        token=M2.ESIOS_TOKEN, año=M2.ESIOS_AÑO, n_intervalos=N_INTERVALOS
    )
    (GEF_w, CE_P_w, CE_C_w,
     p_red_w, p_mkt_w, p_ahorro_w) = M2.generar_parametros_escenarios(
        GEF, CE_P, CE_C, p_red, p_mkt,
        ESCENARIOS, IDS_PROSUMIDORES, IDS_CONSUMIDORES, N_INTERVALOS
    )
    print("Datos y precios cargados.\n")
    return dict(GEF=GEF, CE_P=CE_P, CE_C=CE_C,
                p_red=p_red, p_mkt=p_mkt, p_ahorro=p_ahorro,
                GEF_w=GEF_w, CE_P_w=CE_P_w, CE_C_w=CE_C_w,
                p_red_w=p_red_w, p_mkt_w=p_mkt_w, p_ahorro_w=p_ahorro_w)


# =============================================================================
# 2. RP — VALOR ESPERADO DEL MODELO 2 (con el solver, tal cual)
# =============================================================================

def calcular_RP(d):
    print("=" * 70)
    print("RP — MODELO 2 ESTOCÁSTICO")
    print("=" * 70)
    m = M2.construir_modelo_estocastico(
        GEF=d["GEF"], GEF_w=d["GEF_w"], CE_P=d["CE_P"], CE_P_w=d["CE_P_w"],
        CE_C=d["CE_C"], CE_C_w=d["CE_C_w"], p_red=d["p_red"], p_red_w=d["p_red_w"],
        p_mkt=d["p_mkt"], p_mkt_w=d["p_mkt_w"], p_ahorro_w=d["p_ahorro_w"],
        escenarios=ESCENARIOS, ids_prosumidores=IDS_PROSUMIDORES,
        ids_consumidores=IDS_CONSUMIDORES, n_intervalos=N_INTERVALOS,
        alpha=ALPHA, cap_ed=M2.CAP_ED,
    )
    M2.resolver_modelo(m, "RP (Modelo 2)")
    import pyomo.environ as pyo
    valor = pyo.value(m.Objetivo)
    print()
    return valor


# =============================================================================
# 3. MODELO 0 NOMINAL — extrae la decisión de 1ª etapa x_PtoN*
# =============================================================================

def resolver_M0_nominal(d):
    print("=" * 70)
    print("MODELO 0 — solución determinista (valores nominales)")
    print("=" * 70)
    import pyomo.environ as pyo
    m = M0.construir_modelo(
        GEF=d["GEF"], CE_P=d["CE_P"], CE_C=d["CE_C"],
        p_red=d["p_red"], p_mkt=d["p_mkt"], p_ahorro=d["p_ahorro"],
        ids_prosumidores=IDS_PROSUMIDORES, ids_consumidores=IDS_CONSUMIDORES,
        n_intervalos=N_INTERVALOS, alpha=ALPHA, cap_ed=M0.CAP_ED,
    )
    M0.resolver_modelo(m)
    valor = pyo.value(m.Objetivo)
    x_PtoN = {(i, t): pyo.value(m.x_PtoN[i, t]) for i in m.P for t in m.T}
    print(f"  Decisión de 1ª etapa x_PtoN* extraída ({len(x_PtoN)} valores)\n")
    return valor, x_PtoN


# =============================================================================
# 4. EEV — evalúa la decisión determinista en los 3 escenarios (sin solver)
# =============================================================================

def _beneficio_escenario(d, x_PtoN_fijada, w):
    """
    Calcula el beneficio total del ecosistema en el escenario w, dada la
    cesión de cada prosumidor (ya recortada al excedente del escenario).
    Replica EXACTAMENTE la fórmula de beneficio del Modelo 0/2.

    Reparto óptimo de Nexus (recurso de 2ª etapa): cada unidad cedida que
    pueda cubrir un déficit se asigna a un agente en déficit (le ahorra
    comprar a p_red y en su lugar paga p_mkt < p_red, lo que siempre mejora
    el beneficio agregado); el sobrante se vende a la red a alpha*p_red.
    """
    GEF_w  = d["GEF_w"]; CE_P_w = d["CE_P_w"]; CE_C_w = d["CE_C_w"]
    p_red_w = d["p_red_w"]; p_mkt_w = d["p_mkt_w"]; p_ahorro_w = d["p_ahorro_w"]

    beneficio = 0.0

    for t in T:
        pr  = p_red_w[(t, w)]
        pm  = p_mkt_w[(t, w)]
        pa  = p_ahorro_w[(t, w)]

        # --- Oferta cedida a Nexus y autoconsumo de cada prosumidor ---
        cedido_total = 0.0
        for i in IDS_PROSUMIDORES:
            gef = GEF_w[(i, t, w)]
            cep = CE_P_w[(i, t, w)]
            ces = x_PtoN_fijada[(i, t)]
            # recorte al excedente disponible del escenario (= anti-arbitraje)
            ces = min(ces, max(0.0, gef - cep))
            autocons = gef - ces                      # x_PtoH (balance FV)
            # déficit del prosumidor tras autoconsumo
            deficit_i = max(0.0, cep - autocons)
            # beneficio del prosumidor: ahorro autoconsumo + compensación cesión
            beneficio += pa * autocons + pm * ces
            # guardamos su déficit para repartir energía de Nexus después
            cedido_total += ces

        # --- Demanda total a cubrir por Nexus (prosumidores en déficit + consumidores) ---
        # Prosumidores en déficit
        deficit_P = []
        for i in IDS_PROSUMIDORES:
            gef = GEF_w[(i, t, w)]; cep = CE_P_w[(i, t, w)]
            ces = min(x_PtoN_fijada[(i, t)], max(0.0, gef - cep))
            autocons = gef - ces
            deficit_P.append(max(0.0, cep - autocons))
        # Consumidores puros
        deficit_C = [CE_C_w[(j, t, w)] for j in IDS_CONSUMIDORES]

        demanda_total = sum(deficit_P) + sum(deficit_C)

        # --- Reparto de Nexus: cubre demanda hasta agotar lo cedido ---
        cubierto_por_nexus = min(cedido_total, demanda_total)
        vendido_a_red      = cedido_total - cubierto_por_nexus

        # Repartir 'cubierto_por_nexus' proporcionalmente entre la demanda
        if demanda_total > 1e-12:
            frac = cubierto_por_nexus / demanda_total
        else:
            frac = 0.0

        # Coste de prosumidores en déficit (parte a p_mkt, resto a p_red)
        for dpi in deficit_P:
            recibido_nexus = dpi * frac
            comprado_red   = dpi - recibido_nexus
            beneficio -= pm * recibido_nexus      # x_NtoHP a p_mkt
            beneficio -= pr * comprado_red        # x_RtoHP a p_red

        # Coste de consumidores (parte a p_mkt, resto a p_red)
        for dcj in deficit_C:
            recibido_nexus = dcj * frac
            comprado_red   = dcj - recibido_nexus
            beneficio -= pm * recibido_nexus      # x_NtoHC a p_mkt
            beneficio -= pr * comprado_red        # x_RtoHC a p_red

        # Ingreso de Nexus por vender el sobrante a la red
        beneficio += ALPHA * pr * vendido_a_red

    return beneficio


def calcular_EEV(d, x_PtoN_estrella):
    print("=" * 70)
    print("EEV — solución determinista evaluada en los 3 escenarios")
    print("=" * 70)

    eev = 0.0
    for w, esc in ESCENARIOS.items():
        ben_w = _beneficio_escenario(d, x_PtoN_estrella, w)
        eev += esc["pi"] * ben_w
        print(f"  Escenario {w} ({esc['nombre']:<9} π={esc['pi']}): "
              f"beneficio = {ben_w:,.4f} €")
    print(f"  EEV (ponderado) = {eev:,.4f} €\n")
    return eev


# =============================================================================
# 5. MAIN
# =============================================================================

if __name__ == "__main__":

    d = cargar_todo()

    valor_RP  = calcular_RP(d)
    valor_M0, x_PtoN_estrella = resolver_M0_nominal(d)
    valor_EEV = calcular_EEV(d, x_PtoN_estrella)

    VSS = valor_RP - valor_EEV

    print("=" * 70)
    print("RESULTADOS — VALOR DE LA SOLUCIÓN ESTOCÁSTICA")
    print("=" * 70)
    print(f"  Modelo 0 (valor objetivo nominal)        : {valor_M0:,.2f} €")
    print(f"  RP  = E[beneficio] Modelo 2              : {valor_RP:,.2f} €")
    print(f"  EEV = determinista en los 3 escenarios   : {valor_EEV:,.2f} €")
    print("-" * 70)
    print(f"  VSS = RP - EEV                           : {VSS:,.2f} €")
    print("=" * 70)

    if VSS >= 0:
        print(f"\n  Usar la solución estocástica aporta {VSS:,.2f} € de beneficio")
        print(f"  esperado frente a usar la solución determinista bajo la misma")
        print(f"  incertidumbre. Esto es el valor de la solución estocástica.")
    else:
        print(f"\n  ATENCIÓN: VSS negativo. Revisar la definición de 1ª etapa o")
        print(f"  el cálculo del EEV: no debería ocurrir en maximización.")

    # Guardado en CSV
    df = pd.DataFrame({
        "Métrica": ["Modelo 0 (nominal)", "RP (Modelo 2)",
                    "EEV", "VSS = RP - EEV"],
        "Valor (€)": [valor_M0, valor_RP, valor_EEV, VSS],
    })
    ruta = os.path.join(CARPETA_OUTPUTS, "comparacion_M0_M2_VSS.csv")
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    print(f"\nResumen guardado en: {ruta}")
