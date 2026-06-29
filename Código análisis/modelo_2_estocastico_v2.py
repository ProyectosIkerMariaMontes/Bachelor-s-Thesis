"""
=============================================================================
MODELO 2 — OPTIMIZACIÓN ESTOCÁSTICA
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Extensión del Modelo 0 que incorpora incertidumbre mediante un conjunto
    finito de escenarios con probabilidades asignadas. Nexus sigue actuando
    como planificador central, pero maximiza el valor esperado del beneficio
    en lugar de protegerse contra el peor caso como en el Modelo 1.

    Escenarios:
        w=1 Pesimista  (π=0.20): GEF×0.75, CE×1.15, p_red×1.20, p_mkt×1.10
        w=2 Nominal    (π=0.60): GEF×1.00, CE×1.00, p_red×1.00, p_mkt×1.00
        w=3 Optimista  (π=0.20): GEF×1.25, CE×0.85, p_red×0.80, p_mkt×0.90

    Los factores de escenario son consistentes con los intervalos de
    incertidumbre del Modelo 1 (±25% GEF, ±15% CE, ±20% p_red, ±10% p_mkt),
    lo que permite una comparación directa entre ambos enfoques.
    El escenario pesimista coincide con el peor caso del Modelo 1.

Notas:
    - No hay batería virtual.
    - Los precios base son datos reales PVPC 2022 de ESIOS.
    - El período por defecto es UNA SEMANA para verificación rápida.
      Cambiar N_SEMANAS = 52 para el año completo.
=============================================================================
"""

import pyomo.environ as pyo
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
import estilo_graficos  # estilo legible para Word (fuentes grandes)
import os
from esios_precios import obtener_precios_pvpc, guardar_precios_csv

# =============================================================================
# 0. CONFIGURACIÓN GENERAL
# =============================================================================

RUTA_EXCEL     = r"D:\TFG\Código limpieza datos\Data\data_unificada.xlsx"
CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
os.makedirs(CARPETA_OUTPUTS, exist_ok=True)

# Período de simulación
N_SEMANAS    = 52           # Cambiar a 52 para año completo
N_INTERVALOS = N_SEMANAS * 7 * 96

# IDs de los agentes
IDS_PROSUMIDORES = [16, 17, 18, 19, 1, 2]
IDS_CONSUMIDORES = [i for i in range(1, 16) if i not in IDS_PROSUMIDORES]

# Coeficiente de compensación regulado
ALPHA = 0.05

# Capacidad máxima de energía gestionable por Nexus (kWh)
CAP_ED = 1000.0

# Token personal de la API de ESIOS (REE)
ESIOS_TOKEN = "6d67be18496ea45180ad0e9e5f6620681023864c14a46aeef27804644966184b"
ESIOS_AÑO   = 2022

# -----------------------------------------------------------------------
# Definición de escenarios
# Cada escenario es un dict con su probabilidad y sus factores de escala
# respecto al valor nominal de cada parámetro incierto.
# Los factores son consistentes con los intervalos del Modelo 1:
#   GEF  ±25%  →  factores 0.75 / 1.00 / 1.25
#   CE   ±15%  →  factores 1.15 / 1.00 / 0.85
#   pred ±20%  →  factores 1.20 / 1.00 / 0.80
#   pmkt ±10%  →  factores 1.10 / 1.00 / 0.90
# -----------------------------------------------------------------------
ESCENARIOS = {
    1: {"nombre": "Pesimista",
        "pi": 0.20,
        "f_gef":  0.75,
        "f_ce":   1.15,
        "f_pred": 1.20,
        "f_pmkt": 1.10},
    2: {"nombre": "Nominal",
        "pi": 0.60,
        "f_gef":  1.00,
        "f_ce":   1.00,
        "f_pred": 1.00,
        "f_pmkt": 1.00},
    3: {"nombre": "Optimista",
        "pi": 0.20,
        "f_gef":  1.25,
        "f_ce":   0.85,
        "f_pred": 0.80,
        "f_pmkt": 0.90},
}


# =============================================================================
# 1. CARGA DE DATOS DESDE EXCEL
# =============================================================================

def cargar_datos_excel(ruta, ids_prosumidores, ids_consumidores, n_intervalos):
    """
    Lee las hojas del Excel y devuelve diccionarios de GEF y CE nominales
    indexados por (id_agente, t), donde t va de 1 a n_intervalos.
    """
    print("Cargando datos desde Excel...")

    GEF  = {}
    CE_P = {}
    CE_C = {}

    for i in ids_prosumidores:
        nombre_hoja = f"Consumidor_{i}"
        df = pd.read_excel(ruta, sheet_name=nombre_hoja)
        df = df.head(n_intervalos).reset_index(drop=True)

        col_consumo    = "Consumption [KWh]"
        col_produccion = "Production"

        for t_idx, row in df.iterrows():
            t = t_idx + 1
            consumo    = float(str(row[col_consumo]).replace(",", "."))
            produccion = float(str(row[col_produccion]).replace(",", "."))
            GEF[(i, t)]  = max(0.0, produccion)
            CE_P[(i, t)] = max(0.0, consumo)

        print(f"  Prosumidor {i}: {len(df)} intervalos cargados")

    for j in ids_consumidores:
        nombre_hoja = f"Consumidor_{j}"
        df = pd.read_excel(ruta, sheet_name=nombre_hoja)
        df = df.head(n_intervalos).reset_index(drop=True)

        col_consumo = "Consumption [KWh]"

        for t_idx, row in df.iterrows():
            t = t_idx + 1
            consumo = float(str(row[col_consumo]).replace(",", "."))
            CE_C[(j, t)] = max(0.0, consumo)

        print(f"  Consumidor {j}: {len(df)} intervalos cargados")

    print("Datos cargados correctamente.\n")
    return GEF, CE_P, CE_C


# =============================================================================
# 2. GENERACIÓN DE PRECIOS SINTÉTICOS
# =============================================================================

def generar_precios_sinteticos(n_intervalos):
    """
    Genera precios sintéticos nominales basados en el patrón PVPC español.
    """
    print("Generando precios sintéticos (estilo PVPC 2019)...")

    p_red    = {}
    p_mkt    = {}
    p_ahorro = {}

    for t in range(1, n_intervalos + 1):
        hora = ((t - 1) % 96) / 4.0

        pico_manana = 0.06 * math.exp(-((hora - 9.0) / 2.0) ** 2)
        pico_tarde  = 0.08 * math.exp(-((hora - 19.0) / 2.0) ** 2)
        base_red    = 0.10
        p_red[t]    = round(base_red + pico_manana + pico_tarde, 6)
        p_mkt[t]    = round(0.60 * p_red[t], 6)
        p_ahorro[t] = min(p_mkt[t], p_red[t])

    print("Precios nominales generados correctamente.\n")
    return p_red, p_mkt, p_ahorro


# =============================================================================
# 3. GENERACIÓN DE PARÁMETROS POR ESCENARIO
# =============================================================================

def generar_parametros_escenarios(GEF, CE_P, CE_C, p_red, p_mkt,
                                   escenarios, ids_prosumidores,
                                   ids_consumidores, n_intervalos):
    """
    Aplica los factores de escala de cada escenario a los valores nominales
    para obtener los parámetros indexados por (agente, t, w).
    """
    print("Generando parámetros por escenario...")

    GEF_w    = {}
    CE_P_w   = {}
    CE_C_w   = {}
    p_red_w  = {}
    p_mkt_w  = {}
    p_ahorro_w = {}

    for w, esc in escenarios.items():
        f_gef  = esc["f_gef"]
        f_ce   = esc["f_ce"]
        f_pred = esc["f_pred"]
        f_pmkt = esc["f_pmkt"]

        for i in ids_prosumidores:
            for t in range(1, n_intervalos + 1):
                GEF_w[(i, t, w)]  = GEF[(i, t)]  * f_gef
                CE_P_w[(i, t, w)] = CE_P[(i, t)] * f_ce

        for j in ids_consumidores:
            for t in range(1, n_intervalos + 1):
                CE_C_w[(j, t, w)] = CE_C[(j, t)] * f_ce

        for t in range(1, n_intervalos + 1):
            p_red_w[(t, w)]    = p_red[t] * f_pred
            p_mkt_w[(t, w)]    = p_mkt[t] * f_pmkt
            p_ahorro_w[(t, w)] = min(p_mkt_w[(t, w)], p_red_w[(t, w)])

        print(f"  Escenario {w} ({esc['nombre']}, π={esc['pi']}): generado")

    print("Parámetros por escenario generados correctamente.\n")
    return GEF_w, CE_P_w, CE_C_w, p_red_w, p_mkt_w, p_ahorro_w


# =============================================================================
# 4. CONSTRUCCIÓN DEL MODELO PYOMO ESTOCÁSTICO
# =============================================================================

def construir_modelo_estocastico(GEF, GEF_w,
                                  CE_P, CE_P_w,
                                  CE_C, CE_C_w,
                                  p_red, p_red_w,
                                  p_mkt, p_mkt_w,
                                  p_ahorro_w,
                                  escenarios,
                                  ids_prosumidores, ids_consumidores,
                                  n_intervalos, alpha, cap_ed):
    """
    Construye el modelo Pyomo del Modelo 2 Estocástico.

    Las restricciones se replican para cada escenario w.
    La función objetivo maximiza el valor esperado del beneficio
    ponderando cada escenario por su probabilidad π^w.
    """
    print("Construyendo modelo Pyomo estocástico...")

    m = pyo.ConcreteModel()

    # -------------------------------------------------------------------------
    # 4.1 Índices y conjuntos
    # -------------------------------------------------------------------------
    m.P = pyo.Set(initialize=ids_prosumidores, doc="Prosumidores")
    m.C = pyo.Set(initialize=ids_consumidores, doc="Consumidores puros")
    m.T = pyo.Set(initialize=range(1, n_intervalos + 1),
                  doc="Intervalos temporales (15 min)")
    m.W = pyo.Set(initialize=list(escenarios.keys()),
                  doc="Escenarios")

    # -------------------------------------------------------------------------
    # 4.2 Parámetros nominales (para referencia y gráficos)
    # -------------------------------------------------------------------------
    m.GEF   = pyo.Param(m.P, m.T, initialize=GEF,
                         within=pyo.NonNegativeReals,
                         doc="GEF nominal (kWh)")
    m.CE_P  = pyo.Param(m.P, m.T, initialize=CE_P,
                         within=pyo.NonNegativeReals,
                         doc="CE prosumidor nominal (kWh)")
    m.CE_C  = pyo.Param(m.C, m.T, initialize=CE_C,
                         within=pyo.NonNegativeReals,
                         doc="CE consumidor nominal (kWh)")
    m.p_red = pyo.Param(m.T, initialize=p_red,
                         within=pyo.NonNegativeReals,
                         doc="p_red nominal (€/kWh)")
    m.p_mkt = pyo.Param(m.T, initialize=p_mkt,
                         within=pyo.NonNegativeReals,
                         doc="p_mkt nominal (€/kWh)")

    # -------------------------------------------------------------------------
    # 4.3 Parámetros por escenario
    # -------------------------------------------------------------------------
    m.pi     = pyo.Param(m.W,
                          initialize={w: escenarios[w]["pi"]
                                      for w in escenarios},
                          doc="Probabilidad del escenario w")
    m.GEF_w  = pyo.Param(m.P, m.T, m.W, initialize=GEF_w,
                          within=pyo.NonNegativeReals,
                          doc="GEF escenario w (kWh)")
    m.CE_P_w = pyo.Param(m.P, m.T, m.W, initialize=CE_P_w,
                          within=pyo.NonNegativeReals,
                          doc="CE prosumidor escenario w (kWh)")
    m.CE_C_w = pyo.Param(m.C, m.T, m.W, initialize=CE_C_w,
                          within=pyo.NonNegativeReals,
                          doc="CE consumidor escenario w (kWh)")
    m.p_red_w   = pyo.Param(m.T, m.W, initialize=p_red_w,
                              within=pyo.NonNegativeReals,
                              doc="p_red escenario w (€/kWh)")
    m.p_mkt_w   = pyo.Param(m.T, m.W, initialize=p_mkt_w,
                              within=pyo.NonNegativeReals,
                              doc="p_mkt escenario w (€/kWh)")
    m.p_ahorro_w = pyo.Param(m.T, m.W, initialize=p_ahorro_w,
                               within=pyo.NonNegativeReals,
                               doc="p_ahorro escenario w (€/kWh)")
    m.alpha  = pyo.Param(initialize=alpha,
                          within=pyo.NonNegativeReals)
    m.cap_ED = pyo.Param(initialize=cap_ed,
                          within=pyo.NonNegativeReals)

    # -------------------------------------------------------------------------
    # 4.4 Variables de decisión indexadas por escenario
    # -------------------------------------------------------------------------
    m.x_PtoH  = pyo.Var(m.P, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="FV → autoconsumo prosumidor i (kWh)")
    m.x_PtoN  = pyo.Var(m.P, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="FV → Nexus prosumidor i (kWh)")
    m.x_NtoHP = pyo.Var(m.P, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Nexus → prosumidor i (kWh)")
    m.x_RtoHP = pyo.Var(m.P, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Red → prosumidor i (kWh)")
    m.x_NtoHC = pyo.Var(m.C, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Nexus → consumidor j (kWh)")
    m.x_RtoHC = pyo.Var(m.C, m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Red → consumidor j (kWh)")
    m.x_NtoR  = pyo.Var(m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Nexus → red (kWh)")
    m.ED      = pyo.Var(m.T, m.W, domain=pyo.NonNegativeReals,
                         doc="Energía disponible en Nexus (kWh)")

    # -------------------------------------------------------------------------
    # 4.5 Restricciones (replicadas para cada escenario w)
    # -------------------------------------------------------------------------

    # R1: Balance FV por escenario
    def balance_fv(m, i, t, w):
        return m.x_PtoH[i, t, w] + m.x_PtoN[i, t, w] == m.GEF_w[i, t, w]
    m.R1_balance_FV = pyo.Constraint(m.P, m.T, m.W, rule=balance_fv,
                                      doc="Balance FV por escenario")

    # R2: Balance consumo prosumidor por escenario
    def balance_consumo_P(m, i, t, w):
        return (m.x_PtoH[i, t, w] + m.x_NtoHP[i, t, w]
                + m.x_RtoHP[i, t, w] == m.CE_P_w[i, t, w])
    m.R2_consumo_P = pyo.Constraint(m.P, m.T, m.W,
                                     rule=balance_consumo_P,
                                     doc="Balance consumo prosumidor")

    # R3: Balance consumo consumidor por escenario
    def balance_consumo_C(m, j, t, w):
        return (m.x_NtoHC[j, t, w] + m.x_RtoHC[j, t, w]
                == m.CE_C_w[j, t, w])
    m.R3_consumo_C = pyo.Constraint(m.C, m.T, m.W,
                                     rule=balance_consumo_C,
                                     doc="Balance consumo consumidor")

    # R4: Balance de Nexus por escenario
    def balance_nexus(m, t, w):
        entradas  = sum(m.x_PtoN[i, t, w] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t, w] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t, w] for j in m.C)
        return entradas == salidas_P + salidas_C + m.x_NtoR[t, w]
    m.R4_balance_nexus = pyo.Constraint(m.T, m.W, rule=balance_nexus,
                                         doc="Balance Nexus por escenario")

    # R5: Balance acumulado ED por escenario
    def balance_ED(m, t, w):
        entradas  = sum(m.x_PtoN[i, t, w] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t, w] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t, w] for j in m.C)
        if t == 1:
            return m.ED[t, w] == entradas - salidas_P - salidas_C - m.x_NtoR[t, w]
        else:
            return (m.ED[t, w] == m.ED[t-1, w] + entradas
                    - salidas_P - salidas_C - m.x_NtoR[t, w])
    m.R5_balance_ED = pyo.Constraint(m.T, m.W, rule=balance_ED,
                                      doc="Balance acumulado ED")

    # R6: Capacidad máxima Nexus por escenario
    def cap_nexus(m, t, w):
        return m.ED[t, w] <= m.cap_ED
    m.R6_cap_ED = pyo.Constraint(m.T, m.W, rule=cap_nexus,
                                  doc="Capacidad máxima Nexus")

    # R7: Anti-arbitraje por escenario (usa GEF_w del escenario)
    def anti_arbitraje(m, i, t, w):
        excedente = m.GEF_w[i, t, w] - m.CE_P_w[i, t, w]
        if pyo.value(excedente) <= 0:
            return m.x_PtoN[i, t, w] == 0.0
        else:
            return m.x_PtoN[i, t, w] <= excedente
    m.R7_anti_arbitraje = pyo.Constraint(m.P, m.T, m.W,
                                          rule=anti_arbitraje,
                                          doc="Anti-arbitraje por escenario")

    # -------------------------------------------------------------------------
    # 4.6 Función objetivo estocástica
    # Maximiza el valor esperado del beneficio ponderando por π^w
    # -------------------------------------------------------------------------
    def funcion_objetivo_estocastica(m):
        return sum(
            m.pi[w] * (
                # Beneficio prosumidores
                sum(
                    m.p_ahorro_w[t, w] * m.x_PtoH[i, t, w]
                  + m.p_mkt_w[t, w]   * m.x_PtoN[i, t, w]
                  - m.p_red_w[t, w]   * m.x_RtoHP[i, t, w]
                  - m.p_mkt_w[t, w]   * m.x_NtoHP[i, t, w]
                    for i in m.P for t in m.T
                )
                # Coste consumidores
                - sum(
                    m.p_mkt_w[t, w] * m.x_NtoHC[j, t, w]
                  + m.p_red_w[t, w] * m.x_RtoHC[j, t, w]
                    for j in m.C for t in m.T
                )
                # Ingreso Nexus por venta a red
                + sum(
                    m.alpha * m.p_red_w[t, w] * m.x_NtoR[t, w]
                    for t in m.T
                )
            )
            for w in m.W
        )

    m.Objetivo = pyo.Objective(rule=funcion_objetivo_estocastica,
                                sense=pyo.maximize,
                                doc="Maximizar valor esperado del beneficio")

    print("Modelo estocástico construido correctamente.\n")
    return m


# =============================================================================
# 5. RESOLUCIÓN
# =============================================================================

def resolver_modelo(m, nombre="Modelo 2 Estocástico"):
    print(f"Resolviendo {nombre}...")
    solver = pyo.SolverFactory("highs")

    if not solver.available():
        raise RuntimeError(
            "HiGHS no está disponible. Instálalo con: pip install highspy"
        )

    results = solver.solve(m, tee=False)

    estado    = results.solver.status
    condicion = results.solver.termination_condition
    print(f"  Estado del solver: {estado}")
    print(f"  Condición de terminación: {condicion}")

    if condicion != pyo.TerminationCondition.optimal:
        print("  ADVERTENCIA: La solución no es óptima. Revisar el modelo.")
    else:
        print(f"  Valor objetivo (E[beneficio]): {pyo.value(m.Objetivo):.4f} €")

    print()
    return results


# =============================================================================
# 6. EXTRACCIÓN DE RESULTADOS
# =============================================================================

def extraer_resultados(m, escenarios):
    """
    Extrae los valores óptimos para cada escenario y calcula
    también los valores esperados agregados.
    """
    tiempos = list(m.T)

    # Resultados por escenario
    registros_P = []
    for w in m.W:
        for i in m.P:
            for t in tiempos:
                registros_P.append({
                    "escenario": w,
                    "nombre_esc": escenarios[w]["nombre"],
                    "pi": escenarios[w]["pi"],
                    "agente": i,
                    "t": t,
                    "GEF":     pyo.value(m.GEF[i, t]),
                    "GEF_w":   pyo.value(m.GEF_w[i, t, w]),
                    "CE":      pyo.value(m.CE_P[i, t]),
                    "CE_w":    pyo.value(m.CE_P_w[i, t, w]),
                    "x_PtoH":  pyo.value(m.x_PtoH[i, t, w]),
                    "x_PtoN":  pyo.value(m.x_PtoN[i, t, w]),
                    "x_NtoHP": pyo.value(m.x_NtoHP[i, t, w]),
                    "x_RtoHP": pyo.value(m.x_RtoHP[i, t, w]),
                })

    registros_C = []
    for w in m.W:
        for j in m.C:
            for t in tiempos:
                registros_C.append({
                    "escenario": w,
                    "nombre_esc": escenarios[w]["nombre"],
                    "pi": escenarios[w]["pi"],
                    "agente": j,
                    "t": t,
                    "CE":      pyo.value(m.CE_C[j, t]),
                    "CE_w":    pyo.value(m.CE_C_w[j, t, w]),
                    "x_NtoHC": pyo.value(m.x_NtoHC[j, t, w]),
                    "x_RtoHC": pyo.value(m.x_RtoHC[j, t, w]),
                })

    registros_N = []
    for w in m.W:
        for t in tiempos:
            registros_N.append({
                "escenario": w,
                "nombre_esc": escenarios[w]["nombre"],
                "pi": escenarios[w]["pi"],
                "t": t,
                "ED":       pyo.value(m.ED[t, w]),
                "x_NtoR":   pyo.value(m.x_NtoR[t, w]),
                "p_red_w":  pyo.value(m.p_red_w[t, w]),
                "p_mkt_w":  pyo.value(m.p_mkt_w[t, w]),
                "p_ahorro_w": pyo.value(m.p_ahorro_w[t, w]),
                "p_red":    pyo.value(m.p_red[t]),
                "p_mkt":    pyo.value(m.p_mkt[t]),
            })

    df_P = pd.DataFrame(registros_P)
    df_C = pd.DataFrame(registros_C)
    df_N = pd.DataFrame(registros_N)

    return df_P, df_C, df_N


# =============================================================================
# 7. RESUMEN DE RESULTADOS
# =============================================================================

def imprimir_resumen(df_P, df_C, df_N, m, escenarios):
    print("=" * 65)
    print("RESUMEN DE RESULTADOS — MODELO 2 ESTOCÁSTICO")
    print("=" * 65)
    print(f"\nValor objetivo E[beneficio]: {pyo.value(m.Objetivo):.4f} €")

    for w, esc in escenarios.items():
        print(f"\n{'='*30} Escenario {w}: {esc['nombre']} (π={esc['pi']}) {'='*5}")
        df_Pw = df_P[df_P["escenario"] == w]
        df_Cw = df_C[df_C["escenario"] == w]
        df_Nw = df_N[df_N["escenario"] == w]

        print("  --- Prosumidores ---")
        for i in df_Pw["agente"].unique():
            df_i = df_Pw[df_Pw["agente"] == i]
            print(f"  Prosumidor {i}:")
            print(f"    GEF escenario total:      {df_i['GEF_w'].sum():.3f} kWh")
            print(f"    Autoconsumo (x_PtoH):     {df_i['x_PtoH'].sum():.3f} kWh")
            print(f"    Cedido a Nexus (x_PtoN):  {df_i['x_PtoN'].sum():.3f} kWh")
            print(f"    Recibido de Nexus:         {df_i['x_NtoHP'].sum():.3f} kWh")
            print(f"    Comprado de red:           {df_i['x_RtoHP'].sum():.3f} kWh")

        print("  --- Consumidores (agregado) ---")
        print(f"    CE escenario total:        {df_Cw['CE_w'].sum():.3f} kWh")
        print(f"    Recibido de Nexus total:   {df_Cw['x_NtoHC'].sum():.3f} kWh")
        print(f"    Comprado de red total:     {df_Cw['x_RtoHC'].sum():.3f} kWh")

        print("  --- Nexus ---")
        print(f"    Energía vendida a red:     {df_Nw['x_NtoR'].sum():.3f} kWh")

    print("=" * 65)


# =============================================================================
# 8. GRÁFICOS
# =============================================================================

def graficar_resultados_estocastico(df_P, df_C, df_N,
                                     escenarios, carpeta_outputs,
                                     n_intervalos_dia=96):
    print("Generando gráficos...")

    t_dia     = list(range(1, n_intervalos_dia + 1))
    horas_dia = [((t - 1) / 4.0) for t in t_dia]

    colores_esc = {1: "tomato", 2: "steelblue", 3: "seagreen"}

    # --- Gráfico 1a: Evolución de precios PVPC reales durante el período ---
    # Usando el escenario nominal (w=2) como referencia de precios base
    df_N_nom = df_N[df_N["escenario"] == 2]
    plt.figure(figsize=(14, 4))
    plt.plot(df_N_nom["t"].values, df_N_nom["p_red_w"].values,
             label="p_red nominal (PVPC 2022)", color="steelblue",
             linewidth=0.8, alpha=0.9)
    plt.plot(df_N_nom["t"].values, df_N_nom["p_mkt_w"].values,
             label="p_mkt nominal (Nexus)", color="orange",
             linewidth=0.8, alpha=0.9)
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Precio (€/kWh)")
    plt.title("Evolución de precios PVPC reales 2022 — Período simulado (Modelo 2 Estocástico)")
    plt.legend(fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M2_grafico_precios.png"), dpi=150)
    plt.close()

    # --- Gráfico 1b: Precios por escenario durante el primer día ---
    # Muestra cómo los factores de escala modifican los precios base
    df_N_dia = df_N[df_N["t"].isin(t_dia)]
    plt.figure(figsize=(12, 5))
    for w, esc in escenarios.items():
        df_w = df_N_dia[df_N_dia["escenario"] == w]
        plt.plot(horas_dia, df_w["p_red_w"].values,
                 label=f"p_red ({esc['nombre']})",
                 color=colores_esc[w], linewidth=1.5)
        plt.plot(horas_dia, df_w["p_mkt_w"].values,
                 label=f"p_mkt ({esc['nombre']})",
                 color=colores_esc[w], linewidth=1, linestyle="--")
    plt.xlabel("Hora del día")
    plt.ylabel("Precio (€/kWh)")
    plt.title("Precios por escenario — Primer día (Modelo 2 Estocástico)")
    plt.legend(fontsize=12)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M2_grafico_precios_escenarios.png"), dpi=150)
    plt.close()

    # --- Gráfico 2: Flujos energéticos por prosumidor y escenario ---
    prosumidores = df_P["agente"].unique()
    df_P_dia = df_P[df_P["t"].isin(t_dia)]

    n_pros = len(prosumidores)
    n_cols = 2
    n_filas = (n_pros + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_filas, n_cols,
                              figsize=(20, 4.5 * n_filas),
                              sharex=True)
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for ax, i in zip(axes, prosumidores):
        for w, esc in escenarios.items():
            df_iw = df_P_dia[(df_P_dia["agente"] == i) &
                             (df_P_dia["escenario"] == w)]
            ax.plot(horas_dia, df_iw["GEF_w"].values,
                    label=f"GEF {esc['nombre']}",
                    color=colores_esc[w], linewidth=1.5, alpha=0.8)
            ax.plot(horas_dia, df_iw["x_PtoN"].values,
                    label=f"→Nexus {esc['nombre']}",
                    color=colores_esc[w], linewidth=1,
                    linestyle="--", alpha=0.8)

        # GEF nominal como referencia
        df_i_nom = df_P_dia[(df_P_dia["agente"] == i) &
                            (df_P_dia["escenario"] == 2)]
        ax.plot(horas_dia, df_i_nom["CE"].values,
                label="CE nominal", color="orange",
                linewidth=2, alpha=0.6)

        ax.set_title(f"Prosumidor {i} — Primer día (Modelo 2 Estocástico)")
        ax.set_ylabel("Energía (kWh)")
        ax.legend(fontsize=9, ncol=2)
        ax.grid(True)

    for k in range(len(prosumidores), len(axes)):
        axes[k].set_visible(False)
    for ax in axes[-n_cols:]:
        ax.set_xlabel("Hora del día")
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M2_grafico_prosumidores.png"), dpi=150)
    plt.close()

    # --- Gráfico 3: Excedentes vendidos a la red por escenario ---
    fig, axes = plt.subplots(len(escenarios), 1,
                              figsize=(14, 4 * len(escenarios)),
                              sharex=True)
    for ax, (w, esc) in zip(axes, escenarios.items()):
        df_Nw = df_N[df_N["escenario"] == w]
        ax.fill_between(df_Nw["t"].values, df_Nw["x_NtoR"].values,
                        alpha=0.6, color=colores_esc[w],
                        label=f"x_NtoR ({esc['nombre']}, π={esc['pi']})")
        ax.set_ylabel("Energía vendida\na la red (kWh)")
        ax.set_title(f"Excedentes vendidos a la red — {esc['nombre']}")
        ax.legend(fontsize=12)
        ax.grid(True)
    axes[-1].set_xlabel("Intervalo (15 min)")
    plt.suptitle("Excedentes de Nexus vendidos a la red (Modelo 2 Estocástico)",
                 y=1.01)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M2_grafico_NtoR.png"), dpi=150)
    plt.close()

    print(f"Gráficos guardados en {carpeta_outputs}\n")


# =============================================================================
# 9. COMPARATIVA CON ESCENARIO SIN NEXUS
# =============================================================================

def calcular_comparativa_estocastica(df_P, df_C, df_N, alpha, escenarios,
                                      carpeta_outputs):
    """
    Calcula el beneficio esperado con y sin Nexus ponderando por π^w,
    y genera el gráfico comparativo.
    """
    print("Generando gráfico comparativo con/sin Nexus (estocástico)...")

    tiempos = sorted(df_N["t"].unique())

    beneficio_con_esperado  = []
    beneficio_sin_esperado  = []

    for t in tiempos:
        ben_con_t = 0.0
        ben_sin_t = 0.0

        for w, esc in escenarios.items():
            pi_w = esc["pi"]

            df_P_tw = df_P[(df_P["t"] == t) & (df_P["escenario"] == w)]
            df_C_tw = df_C[(df_C["t"] == t) & (df_C["escenario"] == w)]
            df_N_tw = df_N[(df_N["t"] == t) & (df_N["escenario"] == w)].iloc[0]

            p_red_w  = df_N_tw["p_red_w"]
            p_mkt_w  = df_N_tw["p_mkt_w"]
            p_aho_w  = df_N_tw["p_ahorro_w"]

            # Con Nexus
            ben_P = (
                df_P_tw["x_PtoH"].sum()  * p_aho_w
              + df_P_tw["x_PtoN"].sum()  * p_mkt_w
              - df_P_tw["x_RtoHP"].sum() * p_red_w
              - df_P_tw["x_NtoHP"].sum() * p_mkt_w
            )
            coste_C = (
                df_C_tw["x_NtoHC"].sum() * p_mkt_w
              + df_C_tw["x_RtoHC"].sum() * p_red_w
            )
            ing_nexus = alpha * p_red_w * df_N_tw["x_NtoR"]
            ben_con_t += pi_w * float(ben_P - coste_C + ing_nexus)

            # Sin Nexus (bajo el escenario w)
            gasto_sin_t = 0.0
            for _, row in df_P_tw.iterrows():
                gef_w = row["GEF_w"]
                ce_w  = row["CE_w"]
                autoconsumo = min(gef_w, ce_w)
                excedente   = max(0.0, gef_w - ce_w)
                deficit     = max(0.0, ce_w - gef_w)
                gasto_sin_t += autoconsumo * p_red_w
                gasto_sin_t += excedente   * alpha * p_red_w
                gasto_sin_t -= deficit     * p_red_w
            for _, row in df_C_tw.iterrows():
                gasto_sin_t -= row["CE_w"] * p_red_w
            ben_sin_t += pi_w * gasto_sin_t

        beneficio_con_esperado.append(ben_con_t)
        beneficio_sin_esperado.append(ben_sin_t)

    acumulado_con   = np.cumsum(beneficio_con_esperado)
    acumulado_sin   = np.cumsum(beneficio_sin_esperado)
    ahorro_acumulado = acumulado_con - acumulado_sin

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    axes[0].plot(tiempos, beneficio_con_esperado,
                 label="Con Nexus (E[beneficio])",
                 color="steelblue", alpha=0.7, linewidth=1)
    axes[0].plot(tiempos, beneficio_sin_esperado,
                 label="Sin Nexus (E[beneficio])",
                 color="tomato", alpha=0.7, linewidth=1)
    axes[0].fill_between(tiempos,
                          beneficio_con_esperado, beneficio_sin_esperado,
                          where=[c > s for c, s in
                                 zip(beneficio_con_esperado,
                                     beneficio_sin_esperado)],
                          alpha=0.2, color="green", label="Nexus mejor")
    axes[0].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[0].set_ylabel("E[Beneficio] por intervalo (€)")
    axes[0].set_title("Comparativa por intervalo — Modelo 2 Estocástico")
    axes[0].legend()
    axes[0].grid(True)

    axes[1].plot(tiempos, acumulado_con,
                 label="Acumulado con Nexus", color="steelblue", linewidth=2)
    axes[1].plot(tiempos, acumulado_sin,
                 label="Acumulado sin Nexus", color="tomato", linewidth=2)
    axes[1].plot(tiempos, ahorro_acumulado,
                 label="Ahorro acumulado esperado",
                 color="green", linewidth=2, linestyle="--")
    axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[1].set_xlabel("Intervalo (15 min)")
    axes[1].set_ylabel("E[Beneficio acumulado] (€)")
    axes[1].set_title("Acumulados esperados y ahorro — Modelo 2 Estocástico")
    axes[1].legend()
    axes[1].grid(True)

    ahorro_final = ahorro_acumulado[-1]
    axes[1].annotate(
        f"Ahorro esperado total: {ahorro_final:.2f} €",
        xy=(tiempos[-1], ahorro_final),
        xytext=(tiempos[-1] * 0.70,
                ahorro_final + abs(ahorro_final) * 0.1),
        arrowprops=dict(arrowstyle="->", color="green"),
        fontsize=10, color="green"
    )

    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M2_grafico_comparativa_nexus.png"), dpi=150)
    plt.close()

    print(f"  Ahorro esperado total: {ahorro_final:.4f} €")
    print("Gráfico comparativo guardado.\n")

    return beneficio_con_esperado, beneficio_sin_esperado, ahorro_acumulado


# =============================================================================
# 10. MAIN
# =============================================================================

if __name__ == "__main__":

    # --- 10.1 Carga de datos ---
    GEF, CE_P, CE_C = cargar_datos_excel(
        ruta             = RUTA_EXCEL,
        ids_prosumidores = IDS_PROSUMIDORES,
        ids_consumidores = IDS_CONSUMIDORES,
        n_intervalos     = N_INTERVALOS
    )

    # --- 10.2 Descarga de precios PVPC desde ESIOS (base para escenarios) ---
    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token        = ESIOS_TOKEN,
        año          = ESIOS_AÑO,
        n_intervalos = N_INTERVALOS
    )
    guardar_precios_csv(p_red, p_mkt, p_ahorro,
                        os.path.join(CARPETA_OUTPUTS, "precios_pvpc_2022.csv"))

    # --- 10.3 Generación de parámetros por escenario ---
    (GEF_w, CE_P_w, CE_C_w,
     p_red_w, p_mkt_w,
     p_ahorro_w) = generar_parametros_escenarios(
        GEF, CE_P, CE_C, p_red, p_mkt,
        ESCENARIOS, IDS_PROSUMIDORES, IDS_CONSUMIDORES, N_INTERVALOS
    )

    # --- 10.4 Construcción del modelo ---
    modelo = construir_modelo_estocastico(
        GEF          = GEF,
        GEF_w        = GEF_w,
        CE_P         = CE_P,
        CE_P_w       = CE_P_w,
        CE_C         = CE_C,
        CE_C_w       = CE_C_w,
        p_red        = p_red,
        p_red_w      = p_red_w,
        p_mkt        = p_mkt,
        p_mkt_w      = p_mkt_w,
        p_ahorro_w   = p_ahorro_w,
        escenarios   = ESCENARIOS,
        ids_prosumidores = IDS_PROSUMIDORES,
        ids_consumidores = IDS_CONSUMIDORES,
        n_intervalos     = N_INTERVALOS,
        alpha            = ALPHA,
        cap_ed           = CAP_ED
    )

    # --- 10.5 Resolución ---
    resolver_modelo(modelo)

    # --- 10.6 Extracción de resultados ---
    df_P, df_C, df_N = extraer_resultados(modelo, ESCENARIOS)

    # --- 10.7 Resumen ---
    imprimir_resumen(df_P, df_C, df_N, modelo, ESCENARIOS)

    # --- 10.8 Gráficos propios del Modelo 2 ---
    graficar_resultados_estocastico(df_P, df_C, df_N,
                                     ESCENARIOS, CARPETA_OUTPUTS)

    # --- 10.9 Comparativa con/sin Nexus bajo valor esperado ---
    calcular_comparativa_estocastica(df_P, df_C, df_N,
                                      ALPHA, ESCENARIOS, CARPETA_OUTPUTS)