"""
=============================================================================
MODELO 0 — OPTIMIZACIÓN DETERMINISTA
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Modelo centralizado determinista donde Nexus actúa como coordinador
    único. Optimiza los flujos de energía entre prosumidores, consumidores,
    el Marketplace (Nexus) y la red eléctrica convencional.

    Conjuntos de agentes:
        - Prosumidores (P): agentes con generación fotovoltaica activa.
          IDs en el Excel: Consumidor_16, 17, 18, 19 (producen y consumen)
          y Consumidor_1, 2 (solo consumen, pero los dejamos en C por ahora)
          --> En este modelo: P = {16, 17, 18, 19}
        - Consumidores (C): agentes sin generación fotovoltaica.
          IDs en el Excel: Consumidor_1 hasta Consumidor_15

    Variables de decisión:
        x_PtoH[i,t]   : Energía fotovoltaica del prosumidor i en t
                         destinada a su propio consumo (kWh)
        x_PtoN[i,t]   : Energía fotovoltaica del prosumidor i en t
                         cedida a Nexus (kWh)
        x_NtoHP[i,t]  : Energía asignada por Nexus al prosumidor i en t
                         para cubrir su consumo (kWh)
        x_RtoHP[i,t]  : Energía adquirida de la red por el prosumidor i
                         en t (kWh)
        x_NtoHC[j,t]  : Energía asignada por Nexus al consumidor j en t
                         (kWh)
        x_RtoHC[j,t]  : Energía adquirida de la red por el consumidor j
                         en t (kWh)
        x_NtoR[t]     : Energía vendida por Nexus a la red en t cuando
                         no hay demanda suficiente (kWh)
        ED[t]          : Energía disponible gestionada por Nexus en t (kWh)

    Función objetivo:
        Maximizar el beneficio económico neto agregado de todos los agentes,
        incluyendo el ingreso de Nexus por venta a la red de excedentes no
        redistribuidos.

Notas:
    - No hay batería virtual.
    - Los precios son datos reales PVPC 2022 descargados de la API de ESIOS.
      Si la descarga falla, se usan precios sintéticos como fallback.
    - El período por defecto es UNA SEMANA para verificación rápida.
      Cambiar N_SEMANAS = 52 para el año completo.
    - Los datos se leen del Excel en D:/TFG/Código limpieza datos/Data/
      data_unificada.xlsx. Ajustar RUTA_EXCEL si es necesario.
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

RUTA_EXCEL = r"D:\TFG\Código limpieza datos\Data\data_unificada.xlsx"
CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
os.makedirs(CARPETA_OUTPUTS, exist_ok=True)

# Período de simulación:
# Cada intervalo es de 15 minutos → 1 día = 96 intervalos, 1 semana = 672
N_SEMANAS  = 52          # Cambiar a 52 para año completo
N_INTERVALOS = N_SEMANAS * 7 * 96

# IDs de los agentes tal como aparecen en las hojas del Excel
IDS_PROSUMIDORES = [16, 17, 18, 19, 1, 2]                                       # Tienen producción fotovoltaica
IDS_CONSUMIDORES = [i for i in range(1, 16) if i not in IDS_PROSUMIDORES]       # Solo consumen (3 al 15)

# Coeficiente de compensación regulado por la red española
# La red paga alpha * p_red al prosumidor por excedentes vertidos
ALPHA = 0.05   # 5% del precio de red (valor orientativo; ajustar según regulación)

# Capacidad máxima de energía gestionable por Nexus en cada intervalo (kWh)
CAP_ED = 1000.0

# Token personal de la API de ESIOS (REE)
# Solicitar en: https://api.esios.ree.es
ESIOS_TOKEN = "6d67be18496ea45180ad0e9e5f6620681023864c14a46aeef27804644966184b"
ESIOS_AÑO   = 2022

# =============================================================================
# 1. CARGA DE DATOS DESDE EXCEL
# =============================================================================

def cargar_datos_excel(ruta, ids_prosumidores, ids_consumidores, n_intervalos):
    """
    Lee las hojas del Excel y devuelve diccionarios de GEF y CE
    indexados por (id_agente, t), donde t va de 1 a n_intervalos.

    Columnas usadas:
        - 'Consumption [KWh]' : consumo en kWh (todas las hojas)
        - 'Production'        : producción en kWh (hojas de prosumidores)

    Para las hojas Consumidor_1 a Consumidor_15:
        Production = 0 (consumidores puros)
    Para las hojas Consumidor_16 a Consumidor_19:
        Production puede ser > 0
    """
    print("Cargando datos desde Excel...")

    GEF = {}   # Generación fotovoltaica: solo prosumidores
    CE_P = {}  # Consumo de prosumidores
    CE_C = {}  # Consumo de consumidores

    # --- Prosumidores ---
    for i in ids_prosumidores:
        nombre_hoja = f"Consumidor_{i}"
        df = pd.read_excel(ruta, sheet_name=nombre_hoja)

        # Nos quedamos solo con las primeras n_intervalos filas
        df = df.head(n_intervalos).reset_index(drop=True)

        col_consumo    = "Consumption [KWh]"
        col_produccion = "Production"

        for t_idx, row in df.iterrows():
            t = t_idx + 1  # Índice 1-based
            # Reemplazar comas por puntos si el Excel usa separador europeo
            consumo    = float(str(row[col_consumo]).replace(",", "."))
            produccion = float(str(row[col_produccion]).replace(",", "."))
            GEF[(i, t)]  = max(0.0, produccion)
            CE_P[(i, t)] = max(0.0, consumo)

        print(f"  Prosumidor {i}: {len(df)} intervalos cargados")

    # --- Consumidores ---
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
# 2. GENERACIÓN DE PRECIOS SINTÉTICOS (estilo PVPC español 2019)
# =============================================================================

def generar_precios_sinteticos(n_intervalos):
    """
    Genera precios sintéticos realistas para p_red y p_mkt basados en
    el patrón horario típico del PVPC español de 2019.

    Cada intervalo es de 15 minutos, por lo que hay 96 intervalos por día.
    El precio se repite con el mismo patrón diario.

    Unidades: €/kWh
    """
    print("Generando precios sintéticos (estilo PVPC 2019)...")

    p_red  = {}
    p_mkt  = {}
    p_ahorro = {}

    for t in range(1, n_intervalos + 1):
        # Hora del día (0-23) basada en el intervalo de 15 minutos
        hora = ((t - 1) % 96) / 4.0  # hora continua (0.0 a 23.75)

        # p_red: patrón PVPC con dos picos (mañana y tarde)
        pico_manana = 0.06 * math.exp(-((hora - 9.0) / 2.0) ** 2)
        pico_tarde  = 0.08 * math.exp(-((hora - 19.0) / 2.0) ** 2)
        base_red    = 0.10
        p_red[t]    = round(base_red + pico_manana + pico_tarde, 6)

        # p_mkt: precio de compensación de Nexus
        # Siempre: alpha * p_red < p_mkt < p_red
        # Aquí lo definimos como el 60% del precio de red (orientativo)
        p_mkt[t] = round(0.60 * p_red[t], 6)

        # p_ahorro: mínimo entre p_mkt y p_red (incentivo al autoconsumo)
        p_ahorro[t] = min(p_mkt[t], p_red[t])

    print("Precios generados correctamente.\n")
    return p_red, p_mkt, p_ahorro


# =============================================================================
# 3. CONSTRUCCIÓN DEL MODELO PYOMO
# =============================================================================

def construir_modelo(GEF, CE_P, CE_C,
                     p_red, p_mkt, p_ahorro,
                     ids_prosumidores, ids_consumidores,
                     n_intervalos, alpha, cap_ed):
    """
    Construye y devuelve el modelo Pyomo del Modelo 0 Determinista.
    """
    print("Construyendo modelo Pyomo...")

    m = pyo.ConcreteModel()

    # -------------------------------------------------------------------------
    # 3.1 Índices y conjuntos
    # -------------------------------------------------------------------------
    m.P = pyo.Set(initialize=ids_prosumidores, doc="Prosumidores")
    m.C = pyo.Set(initialize=ids_consumidores, doc="Consumidores puros")
    m.T = pyo.Set(initialize=range(1, n_intervalos + 1), doc="Intervalos temporales (15 min)")

    # -------------------------------------------------------------------------
    # 3.2 Parámetros
    # -------------------------------------------------------------------------

    # Generación fotovoltaica de cada prosumidor (kWh por intervalo de 15 min)
    m.GEF = pyo.Param(m.P, m.T, initialize=GEF,
                      within=pyo.NonNegativeReals,
                      doc="Generación fotovoltaica del prosumidor i en t (kWh)")

    # Consumo de prosumidores (kWh por intervalo de 15 min)
    m.CE_P = pyo.Param(m.P, m.T, initialize=CE_P,
                       within=pyo.NonNegativeReals,
                       doc="Consumo del prosumidor i en t (kWh)")

    # Consumo de consumidores (kWh por intervalo de 15 min)
    m.CE_C = pyo.Param(m.C, m.T, initialize=CE_C,
                       within=pyo.NonNegativeReals,
                       doc="Consumo del consumidor j en t (kWh)")

    # Precios (€/kWh)
    m.p_red    = pyo.Param(m.T, initialize=p_red,
                           within=pyo.NonNegativeReals,
                           doc="Precio de la red convencional en t (€/kWh)")
    m.p_mkt    = pyo.Param(m.T, initialize=p_mkt,
                           within=pyo.NonNegativeReals,
                           doc="Precio de compensación de Nexus en t (€/kWh)")
    m.p_ahorro = pyo.Param(m.T, initialize=p_ahorro,
                           within=pyo.NonNegativeReals,
                           doc="Precio implícito del autoconsumo en t (€/kWh)")
    m.alpha    = pyo.Param(initialize=alpha,
                           within=pyo.NonNegativeReals,
                           doc="Coeficiente de compensación regulado (fracción de p_red)")
    m.cap_ED   = pyo.Param(initialize=cap_ed,
                           within=pyo.NonNegativeReals,
                           doc="Capacidad máxima de energía gestionable por Nexus (kWh)")

    # -------------------------------------------------------------------------
    # 3.3 Variables de decisión
    # -------------------------------------------------------------------------

    # Prosumidores
    m.x_PtoH  = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía FV del prosumidor i en t → autoconsumo (kWh)")
    m.x_PtoN  = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía FV del prosumidor i en t → Nexus (kWh)")
    m.x_NtoHP = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía de Nexus → prosumidor i en t (kWh)")
    m.x_RtoHP = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía de la red → prosumidor i en t (kWh)")

    # Consumidores
    m.x_NtoHC = pyo.Var(m.C, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía de Nexus → consumidor j en t (kWh)")
    m.x_RtoHC = pyo.Var(m.C, m.T, domain=pyo.NonNegativeReals,
                         doc="Energía de la red → consumidor j en t (kWh)")

    # Nexus
    m.x_NtoR  = pyo.Var(m.T, domain=pyo.NonNegativeReals,
                         doc="Energía de Nexus → red en t (excedente no redistribuido) (kWh)")
    m.ED      = pyo.Var(m.T, domain=pyo.NonNegativeReals,
                         doc="Energía disponible gestionada por Nexus en t (kWh)")

    # -------------------------------------------------------------------------
    # 3.4 Restricciones
    # -------------------------------------------------------------------------

    # R1: Balance energético del excedente fotovoltaico (prosumidores)
    # Toda la energía generada se reparte entre autoconsumo y cesión a Nexus
    def balance_fv(m, i, t):
        return m.x_PtoH[i, t] + m.x_PtoN[i, t] == m.GEF[i, t]
    m.R1_balance_FV = pyo.Constraint(m.P, m.T, rule=balance_fv,
                                      doc="Balance FV: autoconsumo + cesión a Nexus = GEF")

    # R2: Balance de consumo de prosumidores
    # La demanda se cubre con generación propia + energía de Nexus + red
    def balance_consumo_P(m, i, t):
        return m.x_PtoH[i, t] + m.x_NtoHP[i, t] + m.x_RtoHP[i, t] == m.CE_P[i, t]
    m.R2_consumo_P = pyo.Constraint(m.P, m.T, rule=balance_consumo_P,
                                     doc="Balance consumo prosumidor")

    # R3: Balance de consumo de consumidores puros
    # La demanda se cubre con energía de Nexus + red
    def balance_consumo_C(m, j, t):
        return m.x_NtoHC[j, t] + m.x_RtoHC[j, t] == m.CE_C[j, t]
    m.R3_consumo_C = pyo.Constraint(m.C, m.T, rule=balance_consumo_C,
                                     doc="Balance consumo consumidor puro")

    # R4: Balance de Nexus
    # Toda la energía recibida de prosumidores se redistribuye o vende a la red
    def balance_nexus(m, t):
        entradas  = sum(m.x_PtoN[i, t] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t] for j in m.C)
        return entradas == salidas_P + salidas_C + m.x_NtoR[t]
    m.R4_balance_nexus = pyo.Constraint(m.T, rule=balance_nexus,
                                         doc="Balance de Nexus: entradas = salidas + venta red")

    # R5: Balance acumulado de energía disponible en Nexus
    def balance_ED(m, t):
        entradas  = sum(m.x_PtoN[i, t] for i in m.P)
        salidas_P = sum(m.x_NtoHP[i, t] for i in m.P)
        salidas_C = sum(m.x_NtoHC[j, t] for j in m.C)
        if t == 1:
            return m.ED[t] == entradas - salidas_P - salidas_C - m.x_NtoR[t]
        else:
            return m.ED[t] == m.ED[t-1] + entradas - salidas_P - salidas_C - m.x_NtoR[t]
    m.R5_balance_ED = pyo.Constraint(m.T, rule=balance_ED,
                                      doc="Balance acumulado de energía en Nexus")

    # R6: Límite de capacidad de Nexus
    def cap_nexus(m, t):
        return m.ED[t] <= m.cap_ED
    m.R6_cap_ED = pyo.Constraint(m.T, rule=cap_nexus,
                                  doc="Capacidad máxima de Nexus")

    # R7: Restricción anti-arbitraje (solo prosumidores)
    # Un prosumidor no puede ceder a Nexus más de lo que le sobra
    # tras cubrir su propio consumo en ese instante
    def anti_arbitraje(m, i, t):
        excedente = m.GEF[i, t] - m.CE_P[i, t]
        if excedente <= 0:
            return m.x_PtoN[i, t] == 0.0
        else:
            return m.x_PtoN[i, t] <= excedente
    m.R7_anti_arbitraje = pyo.Constraint(m.P, m.T, rule=anti_arbitraje,
                                          doc="Anti-arbitraje: cesión a Nexus ≤ excedente real")

    # -------------------------------------------------------------------------
    # 3.5 Función objetivo
    # -------------------------------------------------------------------------
    def funcion_objetivo(m):
        # Beneficio de los prosumidores
        beneficio_P = sum(
            m.p_ahorro[t] * m.x_PtoH[i, t]   # Ahorro por autoconsumo
          + m.p_mkt[t]    * m.x_PtoN[i, t]   # Compensación por ceder a Nexus
          - m.p_red[t]    * m.x_RtoHP[i, t]  # Coste de comprar de la red
          - m.p_mkt[t]    * m.x_NtoHP[i, t]  # Coste de comprar de Nexus
            for i in m.P for t in m.T
        )
        # Coste neto de los consumidores
        coste_C = sum(
            m.p_mkt[t] * m.x_NtoHC[j, t]    # Pago a Nexus
          + m.p_red[t] * m.x_RtoHC[j, t]    # Pago a la red
            for j in m.C for t in m.T
        )
        # Ingreso de Nexus por venta de excedentes a la red
        ingreso_nexus = sum(
            m.alpha * m.p_red[t] * m.x_NtoR[t]
            for t in m.T
        )
        return beneficio_P - coste_C + ingreso_nexus

    m.Objetivo = pyo.Objective(rule=funcion_objetivo, sense=pyo.maximize,
                                doc="Maximizar beneficio económico neto agregado")

    print("Modelo construido correctamente.\n")
    return m


# =============================================================================
# 4. RESOLUCIÓN
# =============================================================================

def resolver_modelo(m):
    """
    Resuelve el modelo con HiGHS y devuelve los resultados.
    """
    print("Resolviendo modelo...")
    solver = pyo.SolverFactory("highs")

    if not solver.available():
        raise RuntimeError(
            "HiGHS no está disponible. Instálalo con: pip install highspy\n"
            "o alternativamente usa GLPK: conda install -c conda-forge glpk\n"
            "O alternativamente usa CBC: pip install cylp"
        )

    results = solver.solve(m, tee=False)

    estado     = results.solver.status
    condicion  = results.solver.termination_condition
    print(f"  Estado del solver: {estado}")
    print(f"  Condición de terminación: {condicion}")

    if condicion != pyo.TerminationCondition.optimal:
        print("  ADVERTENCIA: La solución no es óptima. Revisar el modelo.")
    else:
        print(f"  Valor objetivo: {pyo.value(m.Objetivo):.4f} €")

    print()
    return results


# =============================================================================
# 5. EXTRACCIÓN DE RESULTADOS
# =============================================================================

def extraer_resultados(m):
    """
    Extrae los valores óptimos de las variables y los devuelve
    como DataFrames para facilitar el análisis y los gráficos.
    """
    tiempos = list(m.T)

    # Variables de prosumidores
    registros_P = []
    for i in m.P:
        for t in tiempos:
            registros_P.append({
                "agente": i,
                "t": t,
                "tipo": "prosumidor",
                "GEF": pyo.value(m.GEF[i, t]),
                "CE": pyo.value(m.CE_P[i, t]),
                "x_PtoH": pyo.value(m.x_PtoH[i, t]),
                "x_PtoN": pyo.value(m.x_PtoN[i, t]),
                "x_NtoHP": pyo.value(m.x_NtoHP[i, t]),
                "x_RtoHP": pyo.value(m.x_RtoHP[i, t]),
            })

    # Variables de consumidores
    registros_C = []
    for j in m.C:
        for t in tiempos:
            registros_C.append({
                "agente": j,
                "t": t,
                "tipo": "consumidor",
                "CE": pyo.value(m.CE_C[j, t]),
                "x_NtoHC": pyo.value(m.x_NtoHC[j, t]),
                "x_RtoHC": pyo.value(m.x_RtoHC[j, t]),
            })

    # Variables de Nexus
    registros_N = []
    for t in tiempos:
        registros_N.append({
            "t": t,
            "ED": pyo.value(m.ED[t]),
            "x_NtoR": pyo.value(m.x_NtoR[t]),
            "p_red": pyo.value(m.p_red[t]),
            "p_mkt": pyo.value(m.p_mkt[t]),
            "p_ahorro": pyo.value(m.p_ahorro[t]),
        })

    df_P = pd.DataFrame(registros_P)
    df_C = pd.DataFrame(registros_C)
    df_N = pd.DataFrame(registros_N)

    return df_P, df_C, df_N


# =============================================================================
# 6. GRÁFICOS
# =============================================================================

def graficar_resultados(df_P, df_C, df_N, n_intervalos_dia=96):
    """
    Genera los gráficos principales de resultados.
    Por defecto muestra solo el primer día (96 intervalos de 15 min).
    """
    print("Generando gráficos...")

    CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
    if not os.path.exists(CARPETA_OUTPUTS):
        os.makedirs(CARPETA_OUTPUTS)

    t_dia = list(range(1, n_intervalos_dia + 1))
    horas_dia = [((t - 1) / 4.0) for t in t_dia]  # Horas continuas 0-23.75

    # --- Gráfico 1: Evolución de precios PVPC reales durante el período ---
    plt.figure(figsize=(14, 4))
    plt.plot(df_N["t"].values, df_N["p_red"].values,
             label="p_red (red)", color="steelblue", linewidth=0.8, alpha=0.9)
    plt.plot(df_N["t"].values, df_N["p_mkt"].values,
             label="p_mkt (Nexus)", color="orange", linewidth=0.8, alpha=0.9)
    plt.plot(df_N["t"].values, df_N["p_ahorro"].values,
             label="p_ahorro (autoconsumo)", color="green",
             linewidth=0.8, linestyle="--", alpha=0.9)
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Precio (€/kWh)")
    plt.title("Evolución de precios PVPC reales 2022 — Período simulado")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(CARPETA_OUTPUTS, "grafico_precios.png"), dpi=150)
    plt.close()

    # --- Gráfico 2: Flujos de energía por prosumidor (primer día) ---
    df_P_dia = df_P[df_P["t"].isin(t_dia)]
    prosumidores = df_P_dia["agente"].unique()
    n_pros = len(prosumidores)
    n_cols = 2
    n_filas = (n_pros + n_cols - 1) // n_cols  # filas necesarias (3 si hay 6)
    fig, axes = plt.subplots(n_filas, n_cols,
                              figsize=(20, 4.5 * n_filas), sharex=True)
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]
    for ax, i in zip(axes, prosumidores):
        df_i = df_P_dia[df_P_dia["agente"] == i]
        ax.plot(horas_dia, df_i["GEF"].values,    label="GEF (generación)",  linewidth=2)
        ax.plot(horas_dia, df_i["CE"].values,     label="CE (consumo)",      linewidth=2)
        ax.plot(horas_dia, df_i["x_PtoH"].values, label="x_PtoH (autoconsume)")
        ax.plot(horas_dia, df_i["x_PtoN"].values, label="x_PtoN (→ Nexus)")
        ax.plot(horas_dia, df_i["x_RtoHP"].values,label="x_RtoHP (← red)")
        ax.set_title(f"Prosumidor {i} — Primer día")
        ax.set_ylabel("Energía (kWh)")
        ax.legend(fontsize=11)
        ax.grid(True)
    # Ocultar ejes sobrantes si el nº de prosumidores no llena la rejilla
    for k in range(len(prosumidores), len(axes)):
        axes[k].set_visible(False)
    # Etiqueta del eje x en la fila inferior
    for ax in axes[-n_cols:]:
        ax.set_xlabel("Hora del día")
    plt.tight_layout()
    plt.savefig(os.path.join(CARPETA_OUTPUTS, "grafico_prosumidores.png"), dpi=150)
    plt.close()

    # --- Gráfico 3: Energía disponible en Nexus (ED) — semana completa ---
    plt.figure(figsize=(14, 4))
    plt.plot(df_N["t"].values, df_N["ED"].values, color="green", linewidth=1)
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Energía disponible en Nexus (kWh)")
    plt.title("Evolución de ED — Período simulado")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(CARPETA_OUTPUTS, "grafico_ED.png"), dpi=150)
    plt.close()

    # --- Gráfico 4: Venta de Nexus a la red (x_NtoR) ---
    plt.figure(figsize=(14, 4))
    plt.fill_between(df_N["t"].values, df_N["x_NtoR"].values,
                     alpha=0.5, color="orange", label="x_NtoR (→ red)")
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Energía vendida a la red (kWh)")
    plt.title("Excedentes de Nexus vendidos a la red")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(CARPETA_OUTPUTS, "grafico_NtoR.png"), dpi=150)
    plt.close()

    # --- Gráfico 5: Objetivo acumulado ---
    beneficio_intervalo = []
    for t in df_N["t"].values:
        df_P_t = df_P[df_P["t"] == t]
        df_C_t = df_C[df_C["t"] == t]
        df_N_t = df_N[df_N["t"] == t].iloc[0]

        ben_P = (
            df_P_t["x_PtoH"].sum() * df_N_t["p_ahorro"]
          + df_P_t["x_PtoN"].sum() * df_N_t["p_mkt"]
          - df_P_t["x_RtoHP"].sum() * df_N_t["p_red"]
          - df_P_t["x_NtoHP"].sum() * df_N_t["p_mkt"]
        )
        coste_C = (
            df_C_t["x_NtoHC"].sum() * df_N_t["p_mkt"]
          + df_C_t["x_RtoHC"].sum() * df_N_t["p_red"]
        )
        ing_nexus = ALPHA * df_N_t["p_red"] * df_N_t["x_NtoR"]
        beneficio_intervalo.append(float(ben_P - coste_C + ing_nexus))

    acumulado = np.cumsum(beneficio_intervalo)
    plt.figure(figsize=(14, 4))
    plt.plot(df_N["t"].values, beneficio_intervalo, label="Beneficio por intervalo", alpha=0.6)
    plt.plot(df_N["t"].values, acumulado, label="Beneficio acumulado", linewidth=2)
    plt.xlabel("Intervalo (15 min)")
    plt.ylabel("Beneficio (€)")
    plt.title("Evolución del beneficio económico neto")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(CARPETA_OUTPUTS, "grafico_objetivo.png"), dpi=150)
    plt.close()

    print(f"Gráficos guardados en {CARPETA_OUTPUTS}/\n")


# =============================================================================
# 7. ESCENARIO DE REFERENCIA SIN NEXUS
# =============================================================================

def calcular_escenario_sin_nexus(df_P, df_C, df_N, alpha):
    """
    Calcula el coste/beneficio de cada agente en el escenario de referencia
    donde Nexus no existe:
        - Prosumidores: autoconsumen primero, vierten excedente a la red
          a alpha * p_red. Si tienen déficit, compran de la red a p_red.
        - Consumidores: compran toda su energía de la red a p_red.

    Devuelve una lista con el gasto neto por intervalo en el escenario
    sin Nexus, con el mismo signo que el escenario con Nexus (negativo = gasto).
    """
    tiempos = sorted(df_N["t"].unique())
    gasto_sin_nexus = []

    for t in tiempos:
        df_P_t = df_P[df_P["t"] == t]
        df_C_t = df_C[df_C["t"] == t]
        df_N_t = df_N[df_N["t"] == t].iloc[0]
        p_red_t = df_N_t["p_red"]

        gasto_t = 0.0

        # Prosumidores sin Nexus
        for _, row in df_P_t.iterrows():
            gef  = row["GEF"]
            ce   = row["CE"]
            autoconsumo = min(gef, ce)
            excedente   = max(0.0, gef - ce)
            deficit     = max(0.0, ce - gef)

            # Ingreso por autoconsumo (ahorro respecto a comprar de red)
            gasto_t += autoconsumo * p_red_t
            # Ingreso por venta de excedente a la red
            gasto_t += excedente * alpha * p_red_t
            # Coste por compra de red cuando hay déficit
            gasto_t -= deficit * p_red_t

        # Consumidores sin Nexus: compran todo de la red
        for _, row in df_C_t.iterrows():
            ce = row["CE"]
            gasto_t -= ce * p_red_t

        gasto_sin_nexus.append(gasto_t)

    return gasto_sin_nexus


def calcular_escenario_con_nexus(df_P, df_C, df_N, alpha):
    """
    Recalcula el beneficio por intervalo en el escenario con Nexus,
    usando la misma lógica que la función objetivo del modelo.
    """
    tiempos = sorted(df_N["t"].unique())
    beneficio_con_nexus = []

    for t in tiempos:
        df_P_t = df_P[df_P["t"] == t]
        df_C_t = df_C[df_C["t"] == t]
        df_N_t = df_N[df_N["t"] == t].iloc[0]

        p_red_t    = df_N_t["p_red"]
        p_mkt_t    = df_N_t["p_mkt"]
        p_ahorro_t = df_N_t["p_ahorro"]

        ben_P = (
            df_P_t["x_PtoH"].sum()  * p_ahorro_t
          + df_P_t["x_PtoN"].sum()  * p_mkt_t
          - df_P_t["x_RtoHP"].sum() * p_red_t
          - df_P_t["x_NtoHP"].sum() * p_mkt_t
        )
        coste_C = (
            df_C_t["x_NtoHC"].sum() * p_mkt_t
          + df_C_t["x_RtoHC"].sum() * p_red_t
        )
        ing_nexus = alpha * p_red_t * df_N_t["x_NtoR"]

        beneficio_con_nexus.append(float(ben_P - coste_C + ing_nexus))

    return beneficio_con_nexus


def graficar_comparativa_nexus(df_P, df_C, df_N, alpha, carpeta_outputs):
    """
    Genera el gráfico comparativo entre el escenario con Nexus,
    sin Nexus y la diferencia (ahorro que aporta Nexus).
    """
    print("Generando gráfico comparativo con/sin Nexus...")

    tiempos = sorted(df_N["t"].values)

    beneficio_con    = calcular_escenario_con_nexus(df_P, df_C, df_N, alpha)
    beneficio_sin    = calcular_escenario_sin_nexus(df_P, df_C, df_N, alpha)

    acumulado_con    = np.cumsum(beneficio_con)
    acumulado_sin    = np.cumsum(beneficio_sin)
    ahorro_acumulado = acumulado_con - acumulado_sin

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    # --- Panel superior: beneficio por intervalo ---
    axes[0].plot(tiempos, beneficio_con, label="Con Nexus",
                 color="steelblue", alpha=0.7, linewidth=1)
    axes[0].plot(tiempos, beneficio_sin, label="Sin Nexus",
                 color="tomato", alpha=0.7, linewidth=1)
    axes[0].fill_between(tiempos,
                          beneficio_con, beneficio_sin,
                          where=[c > s for c, s in zip(beneficio_con, beneficio_sin)],
                          alpha=0.2, color="green",
                          label="Nexus mejor")
    axes[0].fill_between(tiempos,
                          beneficio_con, beneficio_sin,
                          where=[c <= s for c, s in zip(beneficio_con, beneficio_sin)],
                          alpha=0.2, color="red",
                          label="Sin Nexus mejor")
    axes[0].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[0].set_ylabel("Beneficio por intervalo (€)")
    axes[0].set_title("Comparativa por intervalo: Con Nexus vs Sin Nexus")
    axes[0].legend()
    axes[0].grid(True)

    # --- Panel inferior: acumulados y ahorro ---
    axes[1].plot(tiempos, acumulado_con, label="Acumulado con Nexus",
                 color="steelblue", linewidth=2)
    axes[1].plot(tiempos, acumulado_sin, label="Acumulado sin Nexus",
                 color="tomato", linewidth=2)
    axes[1].plot(tiempos, ahorro_acumulado, label="Ahorro acumulado (Nexus − Sin Nexus)",
                 color="green", linewidth=2, linestyle="--")
    axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[1].set_xlabel("Intervalo (15 min)")
    axes[1].set_ylabel("Beneficio acumulado (€)")
    axes[1].set_title("Acumulados y ahorro total aportado por Nexus")
    axes[1].legend()
    axes[1].grid(True)

    # Anotación del ahorro final
    ahorro_final = ahorro_acumulado[-1]
    axes[1].annotate(
        f"Ahorro total: {ahorro_final:.2f} €",
        xy=(tiempos[-1], ahorro_final),
        xytext=(tiempos[-1] * 0.75, ahorro_final + abs(ahorro_final) * 0.1),
        arrowprops=dict(arrowstyle="->", color="green"),
        fontsize=10, color="green"
    )

    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "grafico_comparativa_nexus.png"), dpi=150)
    plt.close()

    print(f"  Ahorro total aportado por Nexus en el período: {ahorro_final:.4f} €")
    print("Gráfico comparativo guardado.\n")

    return beneficio_con, beneficio_sin, ahorro_acumulado



# =============================================================================
# 7b. DESGLOSE DE AHORRO INDIVIDUAL POR AGENTE
# =============================================================================

def calcular_ahorro_por_agente(df_P, df_C, df_N, alpha, carpeta_outputs):
    """
    Calcula el ahorro individual de cada agente gracias a Nexus,
    comparando lo que paga/ingresa con Nexus vs sin Nexus.
    Genera una tabla resumen y un gráfico de barras.
    """
    print("Calculando ahorro por agente...")
    tiempos = sorted(df_N["t"].unique())
    resultados = []

    # --- Prosumidores ---
    for i in df_P["agente"].unique():
        df_i = df_P[df_P["agente"] == i]
        balance_con    = 0.0
        balance_sin    = 0.0

        for t in tiempos:
            df_it  = df_i[df_i["t"] == t]
            df_N_t = df_N[df_N["t"] == t].iloc[0]
            if df_it.empty:
                continue

            row        = df_it.iloc[0]
            p_red_t    = df_N_t["p_red"]
            p_mkt_t    = df_N_t["p_mkt"]
            p_ahorro_t = df_N_t["p_ahorro"]

            # Con Nexus
            balance_con += (
                row["x_PtoH"]  * p_ahorro_t
              + row["x_PtoN"]  * p_mkt_t
              - row["x_RtoHP"] * p_red_t
              - row["x_NtoHP"] * p_mkt_t
            )

            # Sin Nexus
            gef         = row["GEF"]
            ce          = row["CE"]
            autoconsumo = min(gef, ce)
            excedente   = max(0.0, gef - ce)
            deficit     = max(0.0, ce - gef)
            balance_sin += (
                autoconsumo * p_red_t
              + excedente   * alpha * p_red_t
              - deficit     * p_red_t
            )

        ahorro = balance_con - balance_sin
        resultados.append({
            "agente": f"Prosumidor {i}",
            "tipo": "Prosumidor",
            "balance_con_nexus": round(balance_con, 4),
            "balance_sin_nexus": round(balance_sin, 4),
            "ahorro_nexus": round(ahorro, 4)
        })

    # --- Consumidores ---
    for j in df_C["agente"].unique():
        df_j = df_C[df_C["agente"] == j]
        balance_con = 0.0
        balance_sin = 0.0

        for t in tiempos:
            df_jt  = df_j[df_j["t"] == t]
            df_N_t = df_N[df_N["t"] == t].iloc[0]
            if df_jt.empty:
                continue

            row     = df_jt.iloc[0]
            p_red_t = df_N_t["p_red"]
            p_mkt_t = df_N_t["p_mkt"]

            # Con Nexus
            balance_con -= (
                row["x_NtoHC"] * p_mkt_t
              + row["x_RtoHC"] * p_red_t
            )

            # Sin Nexus
            balance_sin -= row["CE"] * p_red_t

        ahorro = balance_con - balance_sin
        resultados.append({
            "agente": f"Consumidor {j}",
            "tipo": "Consumidor",
            "balance_con_nexus": round(balance_con, 4),
            "balance_sin_nexus": round(balance_sin, 4),
            "ahorro_nexus": round(ahorro, 4)
        })

    df_res = pd.DataFrame(resultados).sort_values("ahorro_nexus", ascending=False)

    # --- Tabla resumen en consola ---
    print("\n" + "=" * 70)
    print("AHORRO INDIVIDUAL POR AGENTE GRACIAS A NEXUS")
    print("=" * 70)
    print(f"{'Agente':<20} {'Tipo':<12} {'Con Nexus (€)':<16} {'Sin Nexus (€)':<16} {'Ahorro (€)':<12}")
    print("-" * 70)
    for _, row in df_res.iterrows():
        print(f"{row['agente']:<20} {row['tipo']:<12} "
              f"{row['balance_con_nexus']:>14.4f}   "
              f"{row['balance_sin_nexus']:>14.4f}   "
              f"{row['ahorro_nexus']:>10.4f}")
    print("-" * 70)
    print(f"{'TOTAL COMUNIDAD':<20} {'':<12} "
          f"{df_res['balance_con_nexus'].sum():>14.4f}   "
          f"{df_res['balance_sin_nexus'].sum():>14.4f}   "
          f"{df_res['ahorro_nexus'].sum():>10.4f}")
    print("=" * 70 + "\n")

    # --- Gráfico de barras ---
    colores = ["steelblue" if t == "Prosumidor" else "coral"
               for t in df_res["tipo"]]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    x      = np.arange(len(df_res))
    ancho  = 0.35
    axes[0].bar(x - ancho/2, df_res["balance_con_nexus"],
                ancho, label="Con Nexus", color="steelblue", alpha=0.8)
    axes[0].bar(x + ancho/2, df_res["balance_sin_nexus"],
                ancho, label="Sin Nexus", color="tomato", alpha=0.8)
    axes[0].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(df_res["agente"], rotation=45, ha="right", fontsize=11)
    axes[0].set_ylabel("Balance económico (€)")
    axes[0].set_title("Balance con Nexus vs Sin Nexus por agente")
    axes[0].legend()
    axes[0].grid(True, axis="y")

    bars = axes[1].bar(x, df_res["ahorro_nexus"],
                       color=colores, alpha=0.85)
    axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(df_res["agente"], rotation=45, ha="right", fontsize=11)
    axes[1].set_ylabel("Ahorro gracias a Nexus (€)")
    axes[1].set_title("Ahorro individual por agente")
    axes[1].grid(True, axis="y")

    for bar in bars:
        altura = bar.get_height()
        axes[1].annotate(
            f"{altura:.2f}€",
            xy=(bar.get_x() + bar.get_width() / 2, altura),
            xytext=(0, 4 if altura >= 0 else -12),
            textcoords="offset points",
            ha="center", va="bottom", fontsize=9
        )

    from matplotlib.patches import Patch
    leyenda = [Patch(color="steelblue", label="Prosumidor"),
               Patch(color="coral",     label="Consumidor")]
    axes[1].legend(handles=leyenda)

    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "grafico_ahorro_por_agente.png"), dpi=150)
    plt.close()

    print("Gráfico de ahorro por agente guardado.\n")
    return df_res


# =============================================================================
# 7. RESUMEN DE RESULTADOS
# =============================================================================

def imprimir_resumen(df_P, df_C, df_N, m):
    """
    Imprime un resumen compacto de los resultados principales.
    """
    print("=" * 60)
    print("RESUMEN DE RESULTADOS — MODELO 0 DETERMINISTA")
    print("=" * 60)

    print(f"\nValor objetivo total: {pyo.value(m.Objetivo):.4f} €")

    print("\n--- Prosumidores ---")
    for i in df_P["agente"].unique():
        df_i = df_P[df_P["agente"] == i]
        print(f"  Prosumidor {i}:")
        print(f"    GEF total generado:       {df_i['GEF'].sum():.3f} kWh")
        print(f"    Autoconsumo (x_PtoH):     {df_i['x_PtoH'].sum():.3f} kWh")
        print(f"    Cedido a Nexus (x_PtoN):  {df_i['x_PtoN'].sum():.3f} kWh")
        print(f"    Recibido de Nexus:         {df_i['x_NtoHP'].sum():.3f} kWh")
        print(f"    Comprado de red:           {df_i['x_RtoHP'].sum():.3f} kWh")

    print("\n--- Consumidores (agregado) ---")
    print(f"  CE total consumidores:     {df_C['CE'].sum():.3f} kWh")
    print(f"  Recibido de Nexus total:   {df_C['x_NtoHC'].sum():.3f} kWh")
    print(f"  Comprado de red total:     {df_C['x_RtoHC'].sum():.3f} kWh")

    print("\n--- Nexus ---")
    print(f"  Energía vendida a red:     {df_N['x_NtoR'].sum():.3f} kWh")
    print(f"  ED máximo alcanzado:       {df_N['ED'].max():.3f} kWh")
    print("=" * 60)


# =============================================================================
# 8. MAIN
# =============================================================================

if __name__ == "__main__":

    # --- 8.1 Carga de datos ---
    GEF, CE_P, CE_C = cargar_datos_excel(
        ruta             = RUTA_EXCEL,
        ids_prosumidores = IDS_PROSUMIDORES,
        ids_consumidores = IDS_CONSUMIDORES,
        n_intervalos     = N_INTERVALOS
    )

    # --- 8.2 Descarga de precios PVPC desde ESIOS ---
    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token        = ESIOS_TOKEN,
        año          = ESIOS_AÑO,
        n_intervalos = N_INTERVALOS
    )
    guardar_precios_csv(p_red, p_mkt, p_ahorro,
                        os.path.join(CARPETA_OUTPUTS, "precios_pvpc_2022.csv"))

    # --- 8.3 Construcción del modelo ---
    modelo = construir_modelo(
        GEF              = GEF,
        CE_P             = CE_P,
        CE_C             = CE_C,
        p_red            = p_red,
        p_mkt            = p_mkt,
        p_ahorro         = p_ahorro,
        ids_prosumidores = IDS_PROSUMIDORES,
        ids_consumidores = IDS_CONSUMIDORES,
        n_intervalos     = N_INTERVALOS,
        alpha            = ALPHA,
        cap_ed           = CAP_ED
    )

    # --- 8.4 Resolución ---
    resolver_modelo(modelo)

    # --- 8.5 Extracción de resultados ---
    df_P, df_C, df_N = extraer_resultados(modelo)

    # --- 8.6 Resumen ---
    imprimir_resumen(df_P, df_C, df_N, modelo)

    # --- 8.7 Gráficos ---
    graficar_resultados(df_P, df_C, df_N)
    # --- 8.8 Gráfico comparativo con/sin Nexus ---
    CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
    if not os.path.exists(CARPETA_OUTPUTS):
        os.makedirs(CARPETA_OUTPUTS)
    graficar_comparativa_nexus(df_P, df_C, df_N, ALPHA, CARPETA_OUTPUTS)

    # --- 8.9 Desglose de ahorro individual por agente ---
    calcular_ahorro_por_agente(df_P, df_C, df_N, ALPHA, CARPETA_OUTPUTS)