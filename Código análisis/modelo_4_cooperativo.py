"""
=============================================================================
MODELO 4 — COOPERACIÓN CON MERCADO LOCAL DE PRECIO ENDÓGENO
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Variante del Modelo 4 coherente con el mercado local de precio
    endógeno del Modelo 3. La función característica v(S) ya NO es una
    suma aditiva de valores individuales: al ser el precio endógeno, el
    valor que recibe la propia coalición depende de cuánto decide
    ofrecer en conjunto, lo que introduce sinergia real entre sus
    miembros.

    CORRECCIÓN (respecto a la versión anterior):
    La versión anterior calculaba v(S) para cualquier coalición propia
    S ⊊ P asumiendo que tenía acceso EXCLUSIVO a toda la demanda local
    (D_S = demanda de consumidores + déficit de los miembros de S,
    sin contar con que el resto de prosumidores P\\S también compite
    por esa misma demanda). Esto es físicamente imposible de forma
    simultánea para más de una coalición a la vez, y sobrestimaba de
    forma sistemática el valor de las coaliciones pequeñas frente a la
    gran coalición, dando una sinergia de cooperación artificialmente
    muy negativa.

    La corrección consiste en definir v(S) como "lo mejor que puede
    hacer la coalición S actuando como un único decisor conjunto,
    dado que el resto de prosumidores P\\S sigue ofreciendo
    exactamente lo que ofrece en el equilibrio REAL del Modelo 3"
    (cargado desde el CSV que exporta modelo_3_nash_v2.py), compitiendo
    todos por la MISMA demanda agregada D (consumidores + déficit de
    TODOS los prosumidores, no solo los de S).

    Esto reutiliza exactamente la misma maquinaria matemática que ya
    decide la mejor respuesta de un prosumidor individual en el
    Modelo 3 (`mejor_respuesta_cerrada` / `beneficio_oferta`), tratando
    a la coalición S como un único superagente con capacidad conjunta
    cap_S y déficit conjunto deficit_S, que reacciona de forma óptima
    frente a una oferta del resto C_S ya fijada (no a cero, como en la
    versión anterior). Para S = P no hay "resto" (C_S = 0), así que
    v(P) no cambia respecto a la versión anterior: ese caso nunca tuvo
    el problema, ya que no requiere ningún supuesto sobre agentes
    externos.

    Como consecuencia de reutilizar literalmente las funciones de
    Modelo 3 en lugar de mantener una copia paralela (Q_optima_cerrada
    / beneficio_coalicion ya no existen en este archivo), la misma
    clase de inconsistencia que causó el bug corregido en Modelo 3 no
    puede volver a aparecer aquí: solo hay una fórmula, no dos.

Requisito de ejecución:
    Este script necesita que modelo_3_nash_v2.py se haya ejecutado
    primero y haya generado el archivo "M3v2_equilibrio_detalle.csv"
    en CARPETA_OUTPUTS, con la oferta de equilibrio real de cada
    prosumidor en cada instante.

Notas:
    - No hay batería virtual.
    - El valor de Shapley y el nucleolus se calculan exactamente igual
      que en la versión anterior; lo único que cambia es cómo se
      calcula v(S) para coaliciones propias.
=============================================================================
"""

import itertools
import math
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import pyomo.environ as pyo
from esios_precios import obtener_precios_pvpc, guardar_precios_csv
from modelo_3_nash_v2 import beneficio_oferta, mejor_respuesta_cerrada, p_local

# =============================================================================
# 0. CONFIGURACIÓN GENERAL
# =============================================================================

RUTA_EXCEL = r"D:\TFG\Código limpieza datos\Data\data_unificada.xlsx"
CARPETA_OUTPUTS = r"D:\TFG\Código análisis\Outputs"
os.makedirs(CARPETA_OUTPUTS, exist_ok=True)

N_SEMANAS = 52
N_INTERVALOS = N_SEMANAS * 7 * 96

IDS_PROSUMIDORES = [16, 17, 18, 19, 1, 2]
IDS_CONSUMIDORES = [i for i in range(1, 16) if i not in IDS_PROSUMIDORES]

ALPHA = 0.05

ESIOS_TOKEN = "6d67be18496ea45180ad0e9e5f6620681023864c14a46aeef27804644966184b"
ESIOS_AÑO   = 2022

EQUILIBRIO_REFERENCIA = "A"   # equilibrio del Modelo 3 usado como comportamiento real del "resto"


# =============================================================================
# 1. CARGA DE DATOS (idéntico a los modelos anteriores)
# =============================================================================

def cargar_datos_excel(ruta, ids_prosumidores, ids_consumidores, n_intervalos):
    print("Cargando datos desde Excel...")
    GEF, CE_P, CE_C = {}, {}, {}
    for i in ids_prosumidores:
        df = pd.read_excel(ruta, sheet_name=f"Consumidor_{i}").head(n_intervalos).reset_index(drop=True)
        for t_idx, row in df.iterrows():
            t = t_idx + 1
            GEF[(i, t)]  = max(0.0, float(str(row["Production"]).replace(",", ".")))
            CE_P[(i, t)] = max(0.0, float(str(row["Consumption [KWh]"]).replace(",", ".")))
        print(f"  Prosumidor {i}: {len(df)} intervalos cargados")
    for j in ids_consumidores:
        df = pd.read_excel(ruta, sheet_name=f"Consumidor_{j}").head(n_intervalos).reset_index(drop=True)
        for t_idx, row in df.iterrows():
            t = t_idx + 1
            CE_C[(j, t)] = max(0.0, float(str(row["Consumption [KWh]"]).replace(",", ".")))
        print(f"  Consumidor {j}: {len(df)} intervalos cargados")
    print("Datos cargados correctamente.\n")
    return GEF, CE_P, CE_C


def cargar_equilibrio_modelo3(carpeta_outputs, equilibrio=EQUILIBRIO_REFERENCIA):
    """
    Carga la oferta real de equilibrio de cada prosumidor en cada
    instante, calculada por modelo_3_nash_v2.py. Es la pieza que
    permite que v(S) de una coalición propia compita por la demanda
    real contra el comportamiento real del resto, en vez de asumir
    que el resto no existe.
    """
    ruta = os.path.join(carpeta_outputs, "M3v2_equilibrio_detalle.csv")
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            "No se encuentra M3v2_equilibrio_detalle.csv. Ejecuta primero "
            "modelo_3_nash_v2.py: el Modelo 4 necesita la oferta real de "
            "equilibrio de cada prosumidor para evaluar las coaliciones propias."
        )
    print(f"Cargando equilibrio real del Modelo 3 (equilibrio {equilibrio})...")
    df = pd.read_csv(ruta)
    df = df[df["equilibrio"] == equilibrio]
    q_eq_m3 = {
        (int(a), int(t)): float(q)
        for a, t, q in zip(df["agente"], df["t"], df["q_ofrecido"])
    }
    print("Equilibrio del Modelo 3 cargado correctamente.\n")
    return q_eq_m3


# =============================================================================
# 2. FUNCIÓN CARACTERÍSTICA v(S)
# =============================================================================

def calcular_v_S(S, ids_prosumidores_total, GEF, CE_P, CE_C, p_red, p_ahorro,
                  ids_consumidores, n_intervalos, alpha, q_eq_m3):
    """
    v(S) = lo mejor que puede hacer la coalición S, tratada como un
    único decisor conjunto con capacidad cap_S y déficit deficit_S,
    cuando compite por la demanda agregada GLOBAL (consumidores +
    déficit de TODOS los prosumidores, no solo los de S) contra el
    resto de prosumidores P\\S, que se asume ofrecen exactamente lo
    que ofrecen en el equilibrio real del Modelo 3.

    Para S = P, el "resto" está vacío (C_S = 0 en todo instante), así
    que esto coincide exactamente con el cálculo de v(P) de la versión
    anterior: ese caso nunca tuvo el problema de la demanda exclusiva.
    """
    if len(S) == 0:
        return 0.0

    S_set = set(S)
    resto = [i for i in ids_prosumidores_total if i not in S_set]

    demanda_consumidores = {
        t: sum(CE_C[(j, t)] for j in ids_consumidores) for t in range(1, n_intervalos + 1)
    }

    valor_total = 0.0
    for t in range(1, n_intervalos + 1):
        autoconsumo_S, cap_S, deficit_S = 0.0, 0.0, 0.0
        for i in S:
            gef, ce = GEF[(i, t)], CE_P[(i, t)]
            autoconsumo_S += min(gef, ce)
            cap_S         += max(0.0, gef - ce)
            deficit_S     += max(0.0, ce - gef)

        deficit_resto = 0.0
        for i in resto:
            gef, ce = GEF[(i, t)], CE_P[(i, t)]
            deficit_resto += max(0.0, ce - gef)

        # Demanda GLOBAL: la misma que usa el Modelo 3, no una versión
        # reducida solo para S. Es la pieza que elimina el problema de
        # los "varios universos paralelos con acceso exclusivo".
        D_t = demanda_consumidores[t] + deficit_S + deficit_resto

        # Oferta real del resto en el equilibrio del Modelo 3 (dato
        # empírico, no un supuesto de C=0 como antes).
        C_S = sum(q_eq_m3.get((i, t), 0.0) for i in resto)

        pr = p_red[t]

        Q_opt = mejor_respuesta_cerrada(C_S, D_t, deficit_S, alpha, cap_S, pr)
        beneficio_neto = beneficio_oferta(Q_opt, C_S, D_t, deficit_S, cap_S, alpha, pr)

        valor_total += p_ahorro[t] * autoconsumo_S + beneficio_neto

    return valor_total


def calcular_todas_las_coaliciones(ids_prosumidores, GEF, CE_P, CE_C,
                                    p_red, p_ahorro, ids_consumidores,
                                    n_intervalos, alpha, q_eq_m3):
    print(f"Calculando v(S) para las {2**len(ids_prosumidores)} coaliciones posibles...")
    v = {}
    for r in range(0, len(ids_prosumidores) + 1):
        for S in itertools.combinations(ids_prosumidores, r):
            v[frozenset(S)] = calcular_v_S(
                S, ids_prosumidores, GEF, CE_P, CE_C, p_red, p_ahorro,
                ids_consumidores, n_intervalos, alpha, q_eq_m3
            )
    print("Función característica calculada correctamente.\n")
    return v


# =============================================================================
# 3. VALOR DE SHAPLEY
# =============================================================================

def calcular_shapley(ids_prosumidores, v):
    print("Calculando valor de Shapley...")
    N, n = list(ids_prosumidores), len(ids_prosumidores)
    phi = {i: 0.0 for i in N}
    for i in N:
        resto = [j for j in N if j != i]
        for r in range(0, n):
            for S in itertools.combinations(resto, r):
                S_set = frozenset(S)
                peso = (math.factorial(len(S_set)) * math.factorial(n - len(S_set) - 1)
                        / math.factorial(n))
                phi[i] += peso * (v[frozenset(S_set | {i})] - v[S_set])
    print("Valor de Shapley calculado correctamente.\n")
    return phi


# =============================================================================
# 4. NUCLEOLUS
# =============================================================================

def calcular_nucleolus(ids_prosumidores, v, max_iter=None, tol=1e-6):
    print("Calculando nucleolus (programas lineales secuenciales)...")
    N, n = list(ids_prosumidores), len(ids_prosumidores)
    v_N = v[frozenset(N)]

    coaliciones = []
    for r in range(1, n):
        for S in itertools.combinations(N, r):
            coaliciones.append(frozenset(S))

    if max_iter is None:
        max_iter = len(coaliciones) + 5

    fijadas, libres = {}, set(coaliciones)

    for iteracion in range(max_iter):
        m = pyo.ConcreteModel()
        m.I = pyo.Set(initialize=N)
        m.phi = pyo.Var(m.I, domain=pyo.Reals)
        m.eps = pyo.Var(domain=pyo.Reals)
        m.eficiencia = pyo.Constraint(expr=sum(m.phi[i] for i in m.I) == v_N)
        m.libres_cons = pyo.ConstraintList()
        for S in libres:
            m.libres_cons.add(v[S] - sum(m.phi[i] for i in S) <= m.eps)
        m.fijadas_cons = pyo.ConstraintList()
        for S, valor_fijo in fijadas.items():
            m.fijadas_cons.add(v[S] - sum(m.phi[i] for i in S) == valor_fijo)
        m.Obj = pyo.Objective(expr=m.eps, sense=pyo.minimize)

        pyo.SolverFactory("highs").solve(m, tee=False)
        eps_opt = pyo.value(m.eps)
        phi_opt = {i: pyo.value(m.phi[i]) for i in N}

        nuevas_tight = {S for S in libres
                        if abs((v[S] - sum(phi_opt[i] for i in S)) - eps_opt) <= tol}
        for S in nuevas_tight:
            fijadas[S] = eps_opt
        libres -= nuevas_tight

        if len(libres) == 0 or len(fijadas) >= len(coaliciones):
            break
    else:
        print(f"  ADVERTENCIA: límite de {max_iter} iteraciones alcanzado sin "
              f"fijar todas las coaliciones ({len(libres)} sin fijar).")

    print("Nucleolus calculado correctamente.\n")
    return phi_opt, fijadas


# =============================================================================
# 5. RESUMEN Y GRÁFICOS
# =============================================================================

def imprimir_resumen(ids_prosumidores, v, shapley, nucleolus):
    print("=" * 70)
    print("RESUMEN — MODELO 4 COOPERACIÓN CON MERCADO LOCAL ENDÓGENO")
    print("=" * 70)

    v_N = v[frozenset(ids_prosumidores)]
    suma_individual = sum(v[frozenset([i])] for i in ids_prosumidores)

    print(f"\nv(P) — valor de la gran coalición:        {v_N:.4f} €")
    print(f"Suma de v({{i}}) — valores individuales:    {suma_individual:.4f} €")
    print(f"Sinergia de la cooperación (v(P) - Σv(i)): {v_N - suma_individual:.4f} €")

    print(f"\n{'Prosumidor':<12}{'v({i})':>12}{'Shapley':>14}{'Nucleolus':>14}")
    print("-" * 52)
    for i in ids_prosumidores:
        print(f"{i:<12}{v[frozenset([i])]:>12.4f}{shapley[i]:>14.4f}{nucleolus[i]:>14.4f}")
    print("-" * 52)
    print(f"{'TOTAL':<12}{suma_individual:>12.4f}"
          f"{sum(shapley.values()):>14.4f}{sum(nucleolus.values()):>14.4f}")
    print("=" * 70 + "\n")


def graficar_comparativa(ids_prosumidores, v, shapley, nucleolus, carpeta_outputs):
    print("Generando gráfico comparativo...")
    x = np.arange(len(ids_prosumidores))
    ancho = 0.25
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x - ancho, [v[frozenset([i])] for i in ids_prosumidores], ancho,
           label="Valor individual v({i})", color="lightgray")
    ax.bar(x, [shapley[i] for i in ids_prosumidores], ancho,
           label="Valor de Shapley", color="steelblue")
    ax.bar(x + ancho, [nucleolus[i] for i in ids_prosumidores], ancho,
           label="Nucleolus", color="darkorange")
    ax.set_xticks(x)
    ax.set_xticklabels([f"Prosumidor {i}" for i in ids_prosumidores])
    ax.set_ylabel("Beneficio asignado (€)")
    ax.set_title("Comparativa de mecanismos de reparto — Modelo 4 (mercado endógeno)")
    ax.legend()
    ax.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "M4v2_grafico_comparativa_reparto.png"), dpi=150)
    plt.close()
    print("Gráfico guardado.\n")


# =============================================================================
# 6. MAIN
# =============================================================================

if __name__ == "__main__":

    GEF, CE_P, CE_C = cargar_datos_excel(
        ruta=RUTA_EXCEL, ids_prosumidores=IDS_PROSUMIDORES,
        ids_consumidores=IDS_CONSUMIDORES, n_intervalos=N_INTERVALOS
    )

    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token=ESIOS_TOKEN, año=ESIOS_AÑO, n_intervalos=N_INTERVALOS
    )

    q_eq_m3 = cargar_equilibrio_modelo3(CARPETA_OUTPUTS)

    v = calcular_todas_las_coaliciones(
        IDS_PROSUMIDORES, GEF, CE_P, CE_C, p_red, p_ahorro,
        IDS_CONSUMIDORES, N_INTERVALOS, ALPHA, q_eq_m3
    )

    shapley = calcular_shapley(IDS_PROSUMIDORES, v)
    nucleolus, _ = calcular_nucleolus(IDS_PROSUMIDORES, v)

    imprimir_resumen(IDS_PROSUMIDORES, v, shapley, nucleolus)
    graficar_comparativa(IDS_PROSUMIDORES, v, shapley, nucleolus, CARPETA_OUTPUTS)
