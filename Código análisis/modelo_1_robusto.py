"""
=============================================================================
MODELO 1 — OPTIMIZACIÓN ROBUSTA
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Extensión del Modelo 0 que incorpora incertidumbre acotada en los
    parámetros del sistema. Nexus sigue actuando como planificador central
    pero toma decisiones robustas ante la variabilidad de la generación
    fotovoltaica, el consumo y los precios.

    El problema max-min se transforma en un programa lineal equivalente
    de un solo nivel mediante la sustitución analítica de los peores
    valores de precio para cada configuración de variables de decisión.

    Intervalos de incertidumbre:
        GEF : ±25% (alta variabilidad por dependencia meteorológica)
        CE  : ±15% (variabilidad moderada por hábitos de consumo)
        p_red: ±20% (variabilidad del mercado mayorista PVPC)
        p_mkt: ±10% (variabilidad controlada por política de Nexus)

Notas:
    - No hay batería virtual.
    - Los precios son sintéticos basados en patrones PVPC españoles de 2019.
    - El período por defecto es UNA SEMANA para verificación rápida.
      Cambiar N_SEMANAS = 52 para el año completo.
    - Los datos se leen del Excel en la ruta definida en RUTA_EXCEL.
=============================================================================
"""

import pyomo.environ as pyo
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
import os
from esios_precios import obtener_precios_pvpc, guardar_precios_csv

# =============================================================================
# 0. CONFIGURACIÓN GENERAL
# =============================================================================

RUTA_EXCEL = r"D:\TFG\Código limpieza datos\Data\data_unificada.xlsx"
CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
os.makedirs(CARPETA_OUTPUTS, exist_ok=True)

# Período de simulación
N_SEMANAS    = 52                       # Cambiar a 52 para año completo
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
# Intervalos de incertidumbre (fracción del valor nominal)
# -----------------------------------------------------------------------
DELTA_GEF  = 0.25   # ±25%: alta variabilidad por dependencia meteorológica
DELTA_CE   = 0.15   # ±15%: variabilidad moderada por hábitos de consumo
DELTA_PRED = 0.20   # ±20%: variabilidad del mercado mayorista PVPC
DELTA_PMKT = 0.10   # ±10%: variabilidad controlada por política de Nexus


# =============================================================================
# 1. CARGA DE DATOS DESDE EXCEL
# =============================================================================

def cargar_datos_excel(ruta, ids_prosumidores, ids_consumidores, n_intervalos):
    """
    Lee las hojas del Excel y devuelve diccionarios de GEF y CE
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
    Genera precios sintéticos realistas basados en el patrón PVPC español.
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

    print("Precios generados correctamente.\n")
    return p_red, p_mkt, p_ahorro


# =============================================================================
# 3. CÁLCULO DE PARÁMETROS ROBUSTOS
# =============================================================================

def calcular_parametros_robustos(GEF, CE_P, CE_C, p_red, p_mkt,
                                  delta_gef, delta_ce, delta_pred, delta_pmkt,
                                  ids_prosumidores, ids_consumidores,
                                  n_intervalos):
    """
    Calcula los valores mínimos y máximos de cada parámetro incierto
    a partir del valor nominal y los porcentajes de incertidumbre.

    Para la transformación max-min → LP:
        - GEF_min: peor caso para el balance FV (menos generación disponible)
        - CE_P_max, CE_C_max: peor caso para el balance de consumo
        - p_red_max: peor caso para los costes de compra de red
        - p_mkt_min/max: depende de si el agente es vendedor o comprador neto
        - p_ahorro_min: peor caso para el incentivo al autoconsumo
    """
    GEF_min  = {}
    CE_P_max = {}
    CE_C_max = {}

    for i in ids_prosumidores:
        for t in range(1, n_intervalos + 1):
            GEF_min[(i, t)]  = GEF[(i, t)]  * (1 - delta_gef)
            CE_P_max[(i, t)] = CE_P[(i, t)] * (1 + delta_ce)

    for j in ids_consumidores:
        for t in range(1, n_intervalos + 1):
            CE_C_max[(j, t)] = CE_C[(j, t)] * (1 + delta_ce)

    p_red_min    = {t: p_red[t] * (1 - delta_pred) for t in p_red}
    p_red_max    = {t: p_red[t] * (1 + delta_pred) for t in p_red}
    p_mkt_min    = {t: p_mkt[t] * (1 - delta_pmkt) for t in p_mkt}
    p_mkt_max    = {t: p_mkt[t] * (1 + delta_pmkt) for t in p_mkt}

    # p_ahorro_min: mínimo entre p_mkt_min y p_red_min
    p_ahorro_min = {t: min(p_mkt_min[t], p_red_min[t]) for t in p_mkt_min}

    return (GEF_min, CE_P_max, CE_C_max,
            p_red_min, p_red_max,
            p_mkt_min, p_mkt_max,
            p_ahorro_min)


# =============================================================================
# 4. CONSTRUCCIÓN DEL MODELO PYOMO ROBUSTO
# =============================================================================

def construir_modelo_robusto(GEF, GEF_min,
                              CE_P, CE_P_max,
                              CE_C, CE_C_max,
                              p_red_max, p_mkt_min, p_mkt_max, p_ahorro_min,
                              ids_prosumidores, ids_consumidores,
                              n_intervalos, alpha, cap_ed):
    """
    Construye el modelo Pyomo del Modelo 1 Robusto.

    El problema max-min se transforma en LP de un solo nivel:
    - Restricciones robustas usan GEF_min y CE_max (peor caso físico)
    - Función objetivo usa peores precios para cada término:
        · p_ahorro_min  (minimiza ahorro por autoconsumo)
        · p_mkt_min     (minimiza ingreso por cesión a Nexus)
        · p_red_max     (maximiza coste de compra a la red)
        · p_mkt_max     (maximiza coste de compra a Nexus para los agentes)
        · p_red_min     (minimiza ingreso de Nexus por venta a la red)

    Nota sobre p_mkt en la función objetivo:
        El precio p_mkt aparece con signos distintos según el término:
        - Como ingreso para el prosumidor que cede (→ usar p_mkt_min)
        - Como coste para el agente que recibe de Nexus (→ usar p_mkt_max)
        Esta asimetría es la correcta para el problema max-min y se
        justifica en la sección 4.3 del Modelo Propuesto.
    """
    print("Construyendo modelo Pyomo robusto...")

    m = pyo.ConcreteModel()

    # -------------------------------------------------------------------------
    # 4.1 Índices y conjuntos
    # -------------------------------------------------------------------------
    m.P = pyo.Set(initialize=ids_prosumidores, doc="Prosumidores")
    m.C = pyo.Set(initialize=ids_consumidores, doc="Consumidores puros")
    m.T = pyo.Set(initialize=range(1, n_intervalos + 1),
                  doc="Intervalos temporales (15 min)")

    # -------------------------------------------------------------------------
    # 4.2 Parámetros nominales (para referencia y gráficos)
    # -------------------------------------------------------------------------
    m.GEF    = pyo.Param(m.P, m.T, initialize=GEF,
                         within=pyo.NonNegativeReals,
                         doc="GEF nominal (kWh)")
    m.CE_P   = pyo.Param(m.P, m.T, initialize=CE_P,
                         within=pyo.NonNegativeReals,
                         doc="CE prosumidor nominal (kWh)")
    m.CE_C   = pyo.Param(m.C, m.T, initialize=CE_C,
                         within=pyo.NonNegativeReals,
                         doc="CE consumidor nominal (kWh)")

    # -------------------------------------------------------------------------
    # 4.3 Parámetros robustos (peores casos)
    # -------------------------------------------------------------------------
    m.GEF_min    = pyo.Param(m.P, m.T, initialize=GEF_min,
                              within=pyo.NonNegativeReals,
                              doc="GEF mínimo robusto (kWh)")
    m.CE_P_max   = pyo.Param(m.P, m.T, initialize=CE_P_max,
                              within=pyo.NonNegativeReals,
                              doc="CE prosumidor máximo robusto (kWh)")
    m.CE_C_max   = pyo.Param(m.C, m.T, initialize=CE_C_max,
                              within=pyo.NonNegativeReals,
                              doc="CE consumidor máximo robusto (kWh)")
    m.p_red_max  = pyo.Param(m.T, initialize=p_red_max,
                              within=pyo.NonNegativeReals,
                              doc="p_red máximo robusto (€/kWh)")
    m.p_mkt_min  = pyo.Param(m.T, initialize=p_mkt_min,
                              within=pyo.NonNegativeReals,
                              doc="p_mkt mínimo robusto (€/kWh)")
    m.p_mkt_max  = pyo.Param(m.T, initialize=p_mkt_max,
                              within=pyo.NonNegativeReals,
                              doc="p_mkt máximo robusto (€/kWh)")
    m.p_ahorro_min = pyo.Param(m.T, initialize=p_ahorro_min,
                                within=pyo.NonNegativeReals,
                                doc="p_ahorro mínimo robusto (€/kWh)")
    m.p_red_min  = pyo.Param(m.T,
                              initialize={t: p_red_max[t] * (1 - 2 * 0.20)
                                          for t in p_red_max},
                              within=pyo.NonNegativeReals,
                              doc="p_red mínimo robusto para venta a red (€/kWh)")
    m.alpha  = pyo.Param(initialize=alpha,
                         within=pyo.NonNegativeReals)
    m.cap_ED = pyo.Param(initialize=cap_ed,
                         within=pyo.NonNegativeReals)

    # -------------------------------------------------------------------------
    # 4.4 Variables de decisión (mismas que Modelo 0)
    # -------------------------------------------------------------------------
    m.x_PtoH  = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="FV → autoconsumo prosumidor i (kWh)")
    m.x_PtoN  = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="FV → Nexus prosumidor i (kWh)")
    m.x_NtoHP = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Nexus → prosumidor i (kWh)")
    m.x_RtoHP = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Red → prosumidor i (kWh)")
    m.x_NtoHC = pyo.Var(m.C, m.T, domain=pyo.NonNegativeReals,
                         doc="Nexus → consumidor j (kWh)")
    m.x_RtoHC = pyo.Var(m.C, m.T, domain=pyo.NonNegativeReals,
                         doc="Red → consumidor j (kWh)")
    m.x_NtoR  = pyo.Var(m.T, domain=pyo.NonNegativeReals,
                         doc="Nexus → red (excedente no redistribuido) (kWh)")
    m.ED      = pyo.Var(m.T, domain=pyo.NonNegativeReals,
                         doc="Energía disponible en Nexus (kWh)")

    # -------------------------------------------------------------------------
    # 4.5 Restricciones robustas
    # -------------------------------------------------------------------------

    # R1: Balance FV conservador (GEF_min)
    def balance_fv_robusto(m, i, t):
        return m.x_PtoH[i, t] + m.x_PtoN[i, t] <= m.GEF_min[i, t]
    m.R1_balance_FV = pyo.Constraint(m.P, m.T, rule=balance_fv_robusto,
                                      doc="Balance FV robusto: ≤ GEF_min")

    # R2: Balance consumo prosumidor conservador (CE_P_max)
    def balance_consumo_P_robusto(m, i, t):
        return (m.x_PtoH[i, t] + m.x_NtoHP[i, t] + m.x_RtoHP[i, t]
                >= m.CE_P_max[i, t])
    m.R2_consumo_P = pyo.Constraint(m.P, m.T, rule=balance_consumo_P_robusto,
                                     doc="Balance consumo prosumidor robusto: ≥ CE_P_max")

    # R3: Balance consumo consumidor conservador (CE_C_max)
    def balance_consumo_C_robusto(m, j, t):
        return m.x_NtoHC[j, t] + m.x_RtoHC[j, t] >= m.CE_C_max[j, t]
    m.R3_consumo_C = pyo.Constraint(m.C, m.T, rule=balance_consumo_C_robusto,
                                     doc="Balance consumo consumidor robusto: ≥ CE_C_max")

    # R4: Balance de Nexus
    def balance_nexus(m, t):
        entradas  = sum(m.x_PtoN[i, t] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t] for j in m.C)
        return entradas == salidas_P + salidas_C + m.x_NtoR[t]
    m.R4_balance_nexus = pyo.Constraint(m.T, rule=balance_nexus,
                                         doc="Balance Nexus")

    # R5: Balance acumulado ED
    def balance_ED(m, t):
        entradas  = sum(m.x_PtoN[i, t] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t] for j in m.C)
        if t == 1:
            return m.ED[t] == entradas - salidas_P - salidas_C - m.x_NtoR[t]
        else:
            return (m.ED[t] == m.ED[t-1] + entradas
                    - salidas_P - salidas_C - m.x_NtoR[t])
    m.R5_balance_ED = pyo.Constraint(m.T, rule=balance_ED,
                                      doc="Balance acumulado ED")

    # R6: Capacidad máxima Nexus
    def cap_nexus(m, t):
        return m.ED[t] <= m.cap_ED
    m.R6_cap_ED = pyo.Constraint(m.T, rule=cap_nexus,
                                  doc="Capacidad máxima Nexus")

    # R7: Anti-arbitraje robusto (GEF_min - CE_P_max)
    def anti_arbitraje_robusto(m, i, t):
        excedente = m.GEF_min[i, t] - m.CE_P_max[i, t]
        if excedente <= 0:
            return m.x_PtoN[i, t] == 0.0
        else:
            return m.x_PtoN[i, t] <= excedente
    m.R7_anti_arbitraje = pyo.Constraint(m.P, m.T,
                                          rule=anti_arbitraje_robusto,
                                          doc="Anti-arbitraje robusto")

    # -------------------------------------------------------------------------
    # 4.6 Función objetivo robusta (LP equivalente del max-min)
    # -------------------------------------------------------------------------
    def funcion_objetivo_robusta(m):
        # Beneficio prosumidores bajo peores precios:
        # p_ahorro_min: minimiza ahorro autoconsumo
        # p_mkt_min: minimiza ingreso por ceder a Nexus
        # p_red_max: maximiza coste de comprar de red
        # p_mkt_max: maximiza coste de recibir de Nexus
        beneficio_P = sum(
            m.p_ahorro_min[t] * m.x_PtoH[i, t]
          + m.p_mkt_min[t]    * m.x_PtoN[i, t]
          - m.p_red_max[t]    * m.x_RtoHP[i, t]
          - m.p_mkt_max[t]    * m.x_NtoHP[i, t]
            for i in m.P for t in m.T
        )
        # Coste consumidores bajo peores precios:
        # p_mkt_max: maximiza coste de recibir de Nexus
        # p_red_max: maximiza coste de comprar de red
        coste_C = sum(
            m.p_mkt_max[t] * m.x_NtoHC[j, t]
          + m.p_red_max[t] * m.x_RtoHC[j, t]
            for j in m.C for t in m.T
        )
        # Ingreso Nexus por venta a red bajo peor precio:
        # p_red_min: minimiza ingreso de Nexus por venta a red
        ingreso_nexus = sum(
            m.alpha * m.p_red_min[t] * m.x_NtoR[t]
            for t in m.T
        )
        return beneficio_P - coste_C + ingreso_nexus

    m.Objetivo = pyo.Objective(rule=funcion_objetivo_robusta,
                                sense=pyo.maximize,
                                doc="Maximizar beneficio bajo peor escenario")

    print("Modelo robusto construido correctamente.\n")
    return m


# =============================================================================
# 5. RESOLUCIÓN
# =============================================================================

def resolver_modelo(m, nombre="Modelo 1 Robusto"):
    print(f"Resolviendo {nombre}...")
    solver = pyo.SolverFactory("highs")

    if not solver.available():
        raise RuntimeError(
            "HiGHS no está disponible. Instálalo con: pip install highspy\n"
            "O alternativamente usa GLPK: conda install -c conda-forge glpk"
        )

    results = solver.solve(m, tee=False)

    estado    = results.solver.status
    condicion = results.solver.termination_condition
    print(f"  Estado del solver: {estado}")
    print(f"  Condición de terminación: {condicion}")

    if condicion != pyo.TerminationCondition.optimal:
        print("  ADVERTENCIA: La solución no es óptima. Revisar el modelo.")
    else:
        print(f"  Valor objetivo (peor caso): {pyo.value(m.Objetivo):.4f} €")

    print()
    return results


# =============================================================================
# 6. EXTRACCIÓN DE RESULTADOS
# =============================================================================

def extraer_resultados(m):
    tiempos = list(m.T)

    registros_P = []
    for i in m.P:
        for t in tiempos:
            registros_P.append({
                "agente": i,
                "t": t,
                "tipo": "prosumidor",
                "GEF":     pyo.value(m.GEF[i, t]),
                "GEF_min": pyo.value(m.GEF_min[i, t]),
                "CE":      pyo.value(m.CE_P[i, t]),
                "CE_max":  pyo.value(m.CE_P_max[i, t]),
                "x_PtoH":  pyo.value(m.x_PtoH[i, t]),
                "x_PtoN":  pyo.value(m.x_PtoN[i, t]),
                "x_NtoHP": pyo.value(m.x_NtoHP[i, t]),
                "x_RtoHP": pyo.value(m.x_RtoHP[i, t]),
            })

    registros_C = []
    for j in m.C:
        for t in tiempos:
            registros_C.append({
                "agente":  j,
                "t":       t,
                "tipo":    "consumidor",
                "CE":      pyo.value(m.CE_C[j, t]),
                "CE_max":  pyo.value(m.CE_C_max[j, t]),
                "x_NtoHC": pyo.value(m.x_NtoHC[j, t]),
                "x_RtoHC": pyo.value(m.x_RtoHC[j, t]),
            })

    registros_N = []
    for t in tiempos:
        registros_N.append({
            "t":           t,
            "ED":          pyo.value(m.ED[t]),
            "x_NtoR":      pyo.value(m.x_NtoR[t]),
            "p_red_min":   pyo.value(m.p_red_min[t]),
            "p_red_max":   pyo.value(m.p_red_max[t]),
            "p_mkt_min":   pyo.value(m.p_mkt_min[t]),
            "p_mkt_max":   pyo.value(m.p_mkt_max[t]),
            "p_ahorro_min": pyo.value(m.p_ahorro_min[t]),
        })

    df_P = pd.DataFrame(registros_P)
    df_C = pd.DataFrame(registros_C)
    df_N = pd.DataFrame(registros_N)

    return df_P, df_C, df_N


# =============================================================================
# 7. RESUMEN DE RESULTADOS
# =============================================================================

def imprimir_resumen(df_P, df_C, df_N, m):
    print("=" * 60)
    print("RESUMEN DE RESULTADOS — MODELO 1 ROBUSTO")
    print("=" * 60)

    print(f"\nValor objetivo (peor caso): {pyo.value(m.Objetivo):.4f} €")

    print("\n--- Prosumidores ---")
    for i in df_P["agente"].unique():
        df_i = df_P[df_P["agente"] == i]
        print(f"  Prosumidor {i}:")
        print(f"    GEF nominal total:         {df_i['GEF'].sum():.3f} kWh")
        print(f"    GEF mínimo robusto total:  {df_i['GEF_min'].sum():.3f} kWh")
        print(f"    Autoconsumo (x_PtoH):      {df_i['x_PtoH'].sum():.3f} kWh")
        print(f"    Cedido a Nexus (x_PtoN):   {df_i['x_PtoN'].sum():.3f} kWh")
        print(f"    Recibido de Nexus:          {df_i['x_NtoHP'].sum():.3f} kWh")
        print(f"    Comprado de red:            {df_i['x_RtoHP'].sum():.3f} kWh")

    print("\n--- Consumidores (agregado) ---")
    print(f"  CE nominal total:          {df_C['CE'].sum():.3f} kWh")
    print(f"  CE máximo robusto total:   {df_C['CE_max'].sum():.3f} kWh")
    print(f"  Recibido de Nexus total:   {df_C['x_NtoHC'].sum():.3f} kWh")
    print(f"  Comprado de red total:     {df_C['x_RtoHC'].sum():.3f} kWh")

    print("\n--- Nexus ---")
    print(f"  Energía vendida a red:     {df_N['x_NtoR'].sum():.3f} kWh")
    print(f"  ED máximo alcanzado:       {df_N['ED'].max():.3f} kWh")
    print("=" * 60)


# =============================================================================
# 8. GRÁFICOS
# =============================================================================

def graficar_resultados_robusto(df_P, df_C, df_N,
                                 carpeta_outputs, n_intervalos_dia=96):
    print("Generando gráficos...")

    t_dia     = list(range(1, n_intervalos_dia + 1))
    horas_dia = [((t - 1) / 4.0) for t in t_dia]

    # --- Gráfico 1a: Evolución de precios PVPC reales durante el período ---
    plt.figure(figsize=(14, 4))
    plt.plot(df_N["t"].values, df_N["p_red_max"].values,
             label="p_red nominal (PVPC 2022)", color="steelblue",
             linewidth=0.8, alpha=0.9)
    plt.plot(df_N["t"].values, df_N["p_mkt_max"].values,
             label="p_mkt nominal (Nexus)", color="orange",
             linewidth=0.8, alpha=0.9)
    plt.plot(df_N["t"].values, df_N["p_ahorro_min"].values,
             label="p_ahorro_min (peor caso)", color="green",
             linewidth=0.8, linestyle="--", alpha=0.9)
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Precio (€/kWh)")
    plt.title("Evolución de precios PVPC reales 2022 — Período simulado (Modelo 1 Robusto)")
    plt.legend(fontsize=8)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M1_grafico_precios.png"), dpi=150)
    plt.close()

    # --- Gráfico 1b: Bandas de incertidumbre sobre el primer día ---
    df_N_dia = df_N[df_N["t"].isin(t_dia)]
    plt.figure(figsize=(12, 5))

    # Banda p_red
    plt.fill_between(horas_dia,
                     df_N_dia["p_red_min"].values,
                     df_N_dia["p_red_max"].values,
                     alpha=0.2, color="steelblue", label="Banda p_red (±20%)")
    plt.plot(horas_dia, df_N_dia["p_red_min"].values,
             color="steelblue", linewidth=1, linestyle="--")
    plt.plot(horas_dia, df_N_dia["p_red_max"].values,
             color="steelblue", linewidth=1, linestyle="--",
             label="p_red min/max")

    # Banda p_mkt
    plt.fill_between(horas_dia,
                     df_N_dia["p_mkt_min"].values,
                     df_N_dia["p_mkt_max"].values,
                     alpha=0.3, color="orange", label="Banda p_mkt (±10%)")
    plt.plot(horas_dia, df_N_dia["p_mkt_min"].values,
             color="orange", linewidth=1, linestyle="--")
    plt.plot(horas_dia, df_N_dia["p_mkt_max"].values,
             color="orange", linewidth=1, linestyle="--",
             label="p_mkt min/max")

    # p_ahorro_min
    plt.plot(horas_dia, df_N_dia["p_ahorro_min"].values,
             color="green", linewidth=2, label="p_ahorro_min (peor caso)")

    plt.xlabel("Hora del día")
    plt.ylabel("Precio (€/kWh)")
    plt.title("Bandas de incertidumbre — Primer día (Modelo 1 Robusto)")
    plt.legend(fontsize=8)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M1_grafico_bandas_precios.png"), dpi=150)
    plt.close()

    # --- Gráfico 2: Flujos energéticos por prosumidor ---
    df_P_dia     = df_P[df_P["t"].isin(t_dia)]
    prosumidores = df_P_dia["agente"].unique()
    fig, axes    = plt.subplots(len(prosumidores), 1,
                                figsize=(12, 4 * len(prosumidores)),
                                sharex=True)
    if len(prosumidores) == 1:
        axes = [axes]
    for ax, i in zip(axes, prosumidores):
        df_i = df_P_dia[df_P_dia["agente"] == i]
        ax.fill_between(horas_dia,
                        df_i["GEF_min"].values, df_i["GEF"].values,
                        alpha=0.2, color="blue", label="Banda GEF")
        ax.plot(horas_dia, df_i["GEF"].values,
                label="GEF nominal", linewidth=2, color="blue")
        ax.plot(horas_dia, df_i["GEF_min"].values,
                label="GEF mínimo", linewidth=1,
                color="blue", linestyle="--")
        ax.plot(horas_dia, df_i["CE"].values,
                label="CE nominal", linewidth=2, color="orange")
        ax.plot(horas_dia, df_i["CE_max"].values,
                label="CE máximo", linewidth=1,
                color="orange", linestyle="--")
        ax.plot(horas_dia, df_i["x_PtoH"].values,
                label="x_PtoH (autoconsumo)", color="green")
        ax.plot(horas_dia, df_i["x_PtoN"].values,
                label="x_PtoN (→ Nexus)", color="red")
        ax.set_title(f"Prosumidor {i} — Primer día (Modelo 1 Robusto)")
        ax.set_ylabel("Energía (kWh)")
        ax.legend(fontsize=7)
        ax.grid(True)
    axes[-1].set_xlabel("Hora del día")
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M1_grafico_prosumidores.png"), dpi=150)
    plt.close()

    # --- Gráfico 3: Excedentes vendidos a la red ---
    plt.figure(figsize=(14, 4))
    plt.fill_between(df_N["t"].values, df_N["x_NtoR"].values,
                     alpha=0.5, color="orange", label="x_NtoR (→ red)")
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Energía vendida a la red (kWh)")
    plt.title("Excedentes de Nexus vendidos a la red (Modelo 1 Robusto)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M1_grafico_NtoR.png"), dpi=150)
    plt.close()

    print(f"Gráficos guardados en {carpeta_outputs}\n")


# =============================================================================
# 9. COMPARATIVA CON ESCENARIO SIN NEXUS (peor caso)
# =============================================================================

def calcular_escenario_sin_nexus_robusto(df_P, df_C, df_N, alpha):
    """
    Escenario de referencia sin Nexus bajo el peor caso robusto:
    - Prosumidores: autoconsumen con GEF_min, demanda = CE_max,
      excedente a red a alpha * p_red_min.
    - Consumidores: compran todo a p_red_max.
    """
    tiempos = sorted(df_N["t"].unique())
    gasto_sin_nexus = []

    for t in tiempos:
        df_P_t = df_P[df_P["t"] == t]
        df_C_t = df_C[df_C["t"] == t]
        df_N_t = df_N[df_N["t"] == t].iloc[0]

        p_red_max_t = df_N_t["p_red_max"]
        p_red_min_t = df_N_t["p_mkt_min"] / 0.60 * (1 - 0.20)

        gasto_t = 0.0

        for _, row in df_P_t.iterrows():
            gef_min = row["GEF_min"]
            ce_max  = row["CE_max"]
            autoconsumo = min(gef_min, ce_max)
            excedente   = max(0.0, gef_min - ce_max)
            deficit     = max(0.0, ce_max - gef_min)
            gasto_t += autoconsumo * p_red_max_t
            gasto_t += excedente   * alpha * p_red_min_t
            gasto_t -= deficit     * p_red_max_t

        for _, row in df_C_t.iterrows():
            gasto_t -= row["CE_max"] * p_red_max_t

        gasto_sin_nexus.append(gasto_t)

    return gasto_sin_nexus


def calcular_beneficio_con_nexus_robusto(df_P, df_C, df_N, alpha):
    """
    Recalcula el beneficio por intervalo bajo el peor caso robusto.
    """
    tiempos = sorted(df_N["t"].unique())
    beneficio = []

    for t in tiempos:
        df_P_t = df_P[df_P["t"] == t]
        df_C_t = df_C[df_C["t"] == t]
        df_N_t = df_N[df_N["t"] == t].iloc[0]

        p_red_max_t   = df_N_t["p_red_max"]
        p_mkt_min_t   = df_N_t["p_mkt_min"]
        p_mkt_max_t   = df_N_t["p_mkt_max"]
        p_ahorro_min_t = df_N_t["p_ahorro_min"]
        p_red_min_t   = p_red_max_t * (1 - 2 * 0.20)

        ben_P = (
            df_P_t["x_PtoH"].sum()  * p_ahorro_min_t
          + df_P_t["x_PtoN"].sum()  * p_mkt_min_t
          - df_P_t["x_RtoHP"].sum() * p_red_max_t
          - df_P_t["x_NtoHP"].sum() * p_mkt_max_t
        )
        coste_C = (
            df_C_t["x_NtoHC"].sum() * p_mkt_max_t
          + df_C_t["x_RtoHC"].sum() * p_red_max_t
        )
        ing_nexus = alpha * p_red_min_t * df_N_t["x_NtoR"]

        beneficio.append(float(ben_P - coste_C + ing_nexus))

    return beneficio


def graficar_comparativa_robusto(df_P, df_C, df_N, alpha, carpeta_outputs):
    print("Generando gráfico comparativo con/sin Nexus (robusto)...")

    tiempos         = sorted(df_N["t"].values)
    beneficio_con   = calcular_beneficio_con_nexus_robusto(df_P, df_C,
                                                            df_N, alpha)
    beneficio_sin   = calcular_escenario_sin_nexus_robusto(df_P, df_C,
                                                            df_N, alpha)
    acumulado_con   = np.cumsum(beneficio_con)
    acumulado_sin   = np.cumsum(beneficio_sin)
    ahorro_acum     = acumulado_con - acumulado_sin

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    axes[0].plot(tiempos, beneficio_con, label="Con Nexus (robusto)",
                 color="steelblue", alpha=0.7, linewidth=1)
    axes[0].plot(tiempos, beneficio_sin, label="Sin Nexus (robusto)",
                 color="tomato", alpha=0.7, linewidth=1)
    axes[0].fill_between(tiempos, beneficio_con, beneficio_sin,
                          where=[c > s for c, s in
                                 zip(beneficio_con, beneficio_sin)],
                          alpha=0.2, color="green", label="Nexus mejor")
    axes[0].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[0].set_ylabel("Beneficio por intervalo (€)")
    axes[0].set_title("Comparativa por intervalo — Modelo 1 Robusto")
    axes[0].legend()
    axes[0].grid(True)

    axes[1].plot(tiempos, acumulado_con,
                 label="Acumulado con Nexus", color="steelblue", linewidth=2)
    axes[1].plot(tiempos, acumulado_sin,
                 label="Acumulado sin Nexus", color="tomato", linewidth=2)
    axes[1].plot(tiempos, ahorro_acum,
                 label="Ahorro acumulado (Nexus − Sin Nexus)",
                 color="green", linewidth=2, linestyle="--")
    axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[1].set_xlabel("Intervalo (15 min)")
    axes[1].set_ylabel("Beneficio acumulado (€)")
    axes[1].set_title("Acumulados y ahorro — Modelo 1 Robusto (peor caso)")
    axes[1].legend()
    axes[1].grid(True)

    ahorro_final = ahorro_acum[-1]
    axes[1].annotate(
        f"Ahorro total: {ahorro_final:.2f} €",
        xy=(tiempos[-1], ahorro_final),
        xytext=(tiempos[-1] * 0.75, ahorro_final + abs(ahorro_final) * 0.1),
        arrowprops=dict(arrowstyle="->", color="green"),
        fontsize=10, color="green"
    )

    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs,
                             "M1_grafico_comparativa_nexus.png"), dpi=150)
    plt.close()

    print(f"  Ahorro total bajo peor caso: {ahorro_final:.4f} €")
    print("Gráfico comparativo guardado.\n")
    return beneficio_con, beneficio_sin, ahorro_acum


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

    # --- 10.2 Descarga de precios PVPC desde ESIOS ---
    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token        = ESIOS_TOKEN,
        año          = ESIOS_AÑO,
        n_intervalos = N_INTERVALOS
    )
    guardar_precios_csv(p_red, p_mkt, p_ahorro,
                        os.path.join(CARPETA_OUTPUTS, "precios_pvpc_2022.csv"))

    # --- 10.3 Cálculo de parámetros robustos ---
    (GEF_min, CE_P_max, CE_C_max,
     p_red_min, p_red_max,
     p_mkt_min, p_mkt_max,
     p_ahorro_min) = calcular_parametros_robustos(
        GEF, CE_P, CE_C, p_red, p_mkt,
        DELTA_GEF, DELTA_CE, DELTA_PRED, DELTA_PMKT,
        IDS_PROSUMIDORES, IDS_CONSUMIDORES, N_INTERVALOS
    )

    # --- 10.4 Construcción del modelo ---
    modelo = construir_modelo_robusto(
        GEF         = GEF,
        GEF_min     = GEF_min,
        CE_P        = CE_P,
        CE_P_max    = CE_P_max,
        CE_C        = CE_C,
        CE_C_max    = CE_C_max,
        p_red_max   = p_red_max,
        p_mkt_min   = p_mkt_min,
        p_mkt_max   = p_mkt_max,
        p_ahorro_min = p_ahorro_min,
        ids_prosumidores = IDS_PROSUMIDORES,
        ids_consumidores = IDS_CONSUMIDORES,
        n_intervalos     = N_INTERVALOS,
        alpha            = ALPHA,
        cap_ed           = CAP_ED
    )

    # --- 10.5 Resolución ---
    resolver_modelo(modelo)

    # --- 10.6 Extracción de resultados ---
    df_P, df_C, df_N = extraer_resultados(modelo)

    # --- 10.7 Resumen ---
    imprimir_resumen(df_P, df_C, df_N, modelo)

    # --- 10.8 Gráficos propios del Modelo 1 ---
    graficar_resultados_robusto(df_P, df_C, df_N, CARPETA_OUTPUTS)

    # --- 10.9 Comparativa con/sin Nexus bajo peor caso ---
    graficar_comparativa_robusto(df_P, df_C, df_N, ALPHA, CARPETA_OUTPUTS)