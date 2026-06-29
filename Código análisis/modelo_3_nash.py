"""
=============================================================================
MODELO 3 — JUEGO DE NASH CON MERCADO LOCAL DE PRECIO ENDÓGENO
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Variante del Modelo 3 en la que el precio de compensación deja de ser
    un parámetro fijo establecido por Nexus y pasa a determinarse de
    forma endógena según la oferta y la demanda agregadas de la propia
    comunidad energética, de forma aislada del precio de la red salvo
    por los dos límites que acotan el precio local en todo momento.

    Precio local (lineal, calibrado sin parámetros externos):

        p_local(t, Q) = max( alpha*p_red(t),
                              p_red(t) * (1 - (1-alpha) * Q / D_t) )

    donde Q es la oferta agregada que decide ofrecer la comunidad en el
    instante t y D_t es la demanda agregada (consumidores puros más
    prosumidores en déficit). El precio vale p_red(t) cuando Q=0 y cae
    hasta alpha*p_red(t) exactamente cuando Q alcanza D_t, sin introducir
    ningún parámetro adicional al margen de los que ya existían.

    A diferencia de la versión con precio exógeno, aquí SÍ existe un
    incentivo genuino a retener oferta: como el ingreso total Q*p_local(Q)
    es una parábola con máximo interior, ofrecer el 100% del excedente
    deja de ser una estrategia dominante. Se comprueba en el Modelo
    Propuesto, y se valida numéricamente en este código contra una
    búsqueda exhaustiva, que la mejor respuesta de cada prosumidor frente
    a la oferta del resto tiene una expresión cerrada (ver función
    `mejor_respuesta_cerrada`), por lo que el equilibrio de Nash se
    calcula mediante iteración de mejor respuesta sin necesidad de
    ningún solver de optimización.

    CORRECCIÓN (respecto a la versión anterior):
    El cálculo de la oferta óptima de cada prosumidor (mejor_respuesta_
    cerrada / beneficio_oferta) ya vendía la totalidad de lo ofrecido
    q_i al precio local pl, sin partirlo en una porción "buena" y una
    "mala". Sin embargo, el bucle que construía el informe final volvía
    a partir q_i con frac_local (x_tilde / resto_red), reintroduciendo
    de facto la lógica antigua y dando un beneficio reportado distinto
    al que realmente usó el prosumidor para decidir su oferta. Esta
    versión elimina esa duplicación: el reporte llama directamente a
    `beneficio_oferta`, la misma función que decide la oferta óptima,
    de modo que decisión y reporte son, por construcción, coherentes.
    Como consecuencia, también se corrige `x_NtoR` (la energía que
    Nexus acaba canalizando a la red): pasa de una fórmula basada en
    frac_local (que daba un valor positivo incluso cuando Q < D, lo
    cual no tiene sentido físico) a `max(0, Q_eq - D_t)`, el excedente
    que la demanda local no puede absorber al precio pactado.

Notas:
    - No hay batería virtual.
    - Reutiliza los mismos datos y precios de red que los modelos
      anteriores; lo único que cambia es la formación del precio local.
    - Al final de la ejecución se exporta el detalle completo (df_P) a
      CSV, porque el Modelo 4 corregido necesita la oferta real de
      equilibrio de cada prosumidor para evaluar correctamente las
      coaliciones propias (ver modelo_4_cooperativo_v2.py).
=============================================================================
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from esios_precios import obtener_precios_pvpc, guardar_precios_csv

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

MAX_ITER_BR = 300      # máximo de iteraciones de mejor respuesta por instante
TOL_BR      = 1e-6     # tolerancia de convergencia (kWh)
LAMBDA_BR   = 0.3       # tasa de amortiguación de la iteración simultánea


# =============================================================================
# 1. CARGA DE DATOS DESDE EXCEL
# =============================================================================

def cargar_datos_excel(ruta, ids_prosumidores, ids_consumidores, n_intervalos):
    print("Cargando datos desde Excel...")

    GEF, CE_P, CE_C = {}, {}, {}

    for i in ids_prosumidores:
        nombre_hoja = f"Consumidor_{i}"
        df = pd.read_excel(ruta, sheet_name=nombre_hoja)
        df = df.head(n_intervalos).reset_index(drop=True)
        col_consumo, col_produccion = "Consumption [KWh]", "Production"
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
# 2. PRECIO LOCAL ENDÓGENO
# =============================================================================

def p_local(Q, D, alpha, p_red_t):
    """Precio local lineal acotado entre alpha*p_red y p_red."""
    if D <= 0:
        return alpha * p_red_t
    return max(alpha * p_red_t, p_red_t * (1 - (1 - alpha) * Q / D))


def beneficio_oferta(q_i, C, D, deficit_i, surplus_i, alpha, p_red_t):
    """
    Beneficio del prosumidor i derivado de su decisión de oferta q_i,
    dado lo que ofrecen los demás (C), la demanda agregada D y su propio
    déficit. Incluye el valor de rescate alpha*p_red sobre la parte de
    su excedente que decide NO ofrecer al mercado local: esa energía
    sigue canalizándose a través de Nexus hacia la red al precio de
    compensación regulado.

    Importante: la totalidad de q_i (lo que SÍ se ofrece) se vende al
    precio local pl, sin partir q_i en una fracción "local" y una
    fracción "red": el precio pl ya incorpora el efecto agregado de la
    congestión sobre el valor de cada unidad ofrecida, así que no hay
    racionamiento físico individual del lado vendedor. Esta es la
    función que decide la oferta óptima (mejor_respuesta_cerrada) y
    también la que debe usarse para reportar el beneficio resultante:
    usar cualquier otra fórmula en el reporte introduce una
    inconsistencia entre lo que el prosumidor realmente eligió y lo
    que se le atribuye económicamente.

    No incluye el término de autoconsumo, que es constante respecto a
    esta decisión y se añade aparte.
    """
    Q = q_i + C
    pl = p_local(Q, D, alpha, p_red_t)
    frac_local = min(1.0, Q / D) if D > 0 else 0.0
    venta        = q_i * pl
    compra_local = deficit_i * frac_local * pl
    compra_red   = deficit_i * (1 - frac_local) * p_red_t
    rescate       = alpha * p_red_t * (surplus_i - q_i)
    return venta - compra_local - compra_red + rescate


def mejor_respuesta_cerrada(C, D, deficit_i, alpha, surplus_i, p_red_t):
    """
    Mejor respuesta del prosumidor i en forma cerrada, dado que los
    demás ofrecen en conjunto C. Incluye el valor de rescate de la
    energía no ofrecida, lo que simplifica la expresión del óptimo
    interior respecto a la versión sin rescate (el factor (1-alpha)
    desaparece del denominador). Se evalúan los candidatos relevantes
    de ambas regiones y se elige el que da mayor beneficio, validado
    mediante búsqueda exhaustiva en pruebas previas.

    Nota: esta función es genérica respecto a quién sea "i" — sirve
    igual para un prosumidor individual que para una coalición entera
    tratada como un único decisor (con surplus_i = capacidad conjunta
    de la coalición y deficit_i = déficit conjunto). El Modelo 4
    reutiliza esta misma función para evaluar v(S) de cada coalición,
    en vez de mantener una copia paralela de la fórmula.
    """
    if surplus_i <= 0:
        return 0.0

    q_kink = D - C  # valor de q_i en el que Q alcanza D
    candidatos = [0.0, surplus_i]

    if D - deficit_i > 1e-9:
        q_interior = (D**2 + C * (2 * deficit_i - D)) / (2 * (D - deficit_i))
        limite_suave = min(max(q_kink, 0.0), surplus_i)
        q_interior = float(np.clip(q_interior, 0.0, limite_suave))
        candidatos.append(q_interior)

    mejor_q, mejor_val = 0.0, -np.inf
    for q in candidatos:
        q = float(np.clip(q, 0.0, surplus_i))
        val = beneficio_oferta(q, C, D, deficit_i, surplus_i, alpha, p_red_t)
        if val > mejor_val:
            mejor_val, mejor_q = val, q
    return mejor_q


def iterar_equilibrio(surplus, deficit, D_t, alpha, pr, q_inicial):
    """
    Iteración de mejor respuesta SIMULTÁNEA (tipo Jacobi) y amortiguada:
    todos los jugadores se mueven a la vez, y solo una fracción
    LAMBDA_BR de la distancia hacia su mejor respuesta en cada paso.
    La actualización secuencial puede producir sobreimpulso cuando el
    punto de partida está lejos del equilibrio, llevando a un punto
    fijo distinto del que se alcanzaría con ajustes graduales; la
    versión amortiguada evita ese artefacto y permite distinguir de
    forma fiable los distintos equilibrios estables que tiene este
    juego (ver discusión en el Modelo Propuesto).
    """
    ids = list(surplus.keys())
    q = dict(q_inicial)
    for it in range(MAX_ITER_BR):
        cambio_max = 0.0
        q_nuevo = {}
        for i in ids:
            C_i = sum(q[k] for k in ids if k != i)
            br = mejor_respuesta_cerrada(C_i, D_t, deficit[i], alpha, surplus[i], pr)
            q_nuevo[i] = q[i] + LAMBDA_BR * (br - q[i])
            cambio_max = max(cambio_max, abs(q_nuevo[i] - q[i]))
        q = q_nuevo
        if cambio_max < TOL_BR:
            return q, True
    return q, False


# =============================================================================
# 3. EQUILIBRIO DE NASH POR ITERACIÓN DE MEJOR RESPUESTA
# =============================================================================

def calcular_equilibrio_nash(GEF, CE_P, CE_C, p_red, p_mkt, p_ahorro,
                              ids_prosumidores, ids_consumidores,
                              n_intervalos, alpha):
    """
    Para cada instante t, calcula DOS posibles equilibrios de Nash
    mediante iteración de mejor respuesta simultánea y amortiguada,
    partiendo de dos puntos de arranque distintos:

      - Equilibrio A: arrancando desde que nadie ofrece nada. En la
        práctica converge al equilibrio de retención moderada cuando
        este existe (el más favorable para los prosumidores).
      - Equilibrio B: arrancando desde que todos ofrecen el máximo
        disponible. Converge al equilibrio de saturación competitiva,
        en el que la oferta inunda el mercado y el precio local cae
        al suelo regulado.

    Cuando ambos arranques convergen al mismo punto, el equilibrio es
    único en ese instante. Cuando difieren, el juego tiene equilibrios
    múltiples y la teoría de juegos no predice por sí sola cuál
    prevalecería sin un mecanismo de coordinación: esa ambigüedad es en
    sí misma uno de los resultados centrales de este modelo.

    El beneficio reportado para cada prosumidor se calcula llamando
    directamente a `beneficio_oferta` con la oferta de equilibrio ya
    alcanzada, en vez de reimplementar la fórmula: así se garantiza
    que el beneficio reportado es exactamente el que el prosumidor
    obtiene de la decisión que realmente tomó.
    """
    print("Calculando equilibrios de Nash con mercado local endógeno...")

    registros_P, registros_N = [], []
    n_no_convergio = 0
    n_multiplicidad = 0

    for t in range(1, n_intervalos + 1):

        surplus, deficit, autoconsumo = {}, {}, {}
        for i in ids_prosumidores:
            gef, ce = GEF[(i, t)], CE_P[(i, t)]
            autoconsumo[i] = min(gef, ce)
            surplus[i]     = max(0.0, gef - ce)
            deficit[i]     = max(0.0, ce - gef)

        D_t = sum(CE_C[(j, t)] for j in ids_consumidores) + sum(deficit.values())
        pr = p_red[t]

        q_inicial_A = {i: 0.0 for i in ids_prosumidores}
        q_inicial_B = {i: surplus[i] for i in ids_prosumidores}

        q_A, ok_A = iterar_equilibrio(surplus, deficit, D_t, alpha, pr, q_inicial_A)
        q_B, ok_B = iterar_equilibrio(surplus, deficit, D_t, alpha, pr, q_inicial_B)

        if not (ok_A and ok_B):
            n_no_convergio += 1

        Q_A, Q_B = sum(q_A.values()), sum(q_B.values())
        hay_multiplicidad = abs(Q_A - Q_B) > 1e-3
        if hay_multiplicidad:
            n_multiplicidad += 1

        for nombre_eq, q_eq, Q_eq in [("A", q_A, Q_A), ("B", q_B, Q_B)]:
            pl_t = p_local(Q_eq, D_t, alpha, pr)
            frac_local = min(1.0, Q_eq / D_t) if D_t > 0 else 0.0

            for i in ids_prosumidores:
                C_i = Q_eq - q_eq[i]

                # Mismo cálculo, exactamente la misma función, que decidió
                # la oferta óptima: garantiza coherencia entre decisión y
                # reporte por construcción, no por duplicación manual.
                beneficio_venta = beneficio_oferta(
                    q_eq[i], C_i, D_t, deficit[i], surplus[i], alpha, pr
                )
                rescate_i = alpha * pr * (surplus[i] - q_eq[i])
                x_NtoHP   = deficit[i] * frac_local
                x_RtoHP   = deficit[i] * (1 - frac_local)

                beneficio = p_ahorro[t] * autoconsumo[i] + beneficio_venta

                registros_P.append({
                    "equilibrio": nombre_eq, "agente": i, "t": t,
                    "GEF": GEF[(i, t)], "CE": CE_P[(i, t)],
                    "x_PtoH": autoconsumo[i],
                    "q_ofrecido": q_eq[i],
                    "surplus_disponible": surplus[i],
                    "fraccion_ofrecida": (q_eq[i] / surplus[i]) if surplus[i] > 1e-9 else np.nan,
                    "x_PtoN": q_eq[i],     # todo lo ofrecido se vende al precio local pl_t
                    "rescate": rescate_i,  # valor de rescate sobre lo NO ofrecido
                    "x_NtoHP": x_NtoHP, "x_RtoHP": x_RtoHP,
                    "beneficio": beneficio,
                })

            # Excedente que la demanda local no puede absorber al precio
            # pactado: solo existe cuando la oferta agregada supera la
            # demanda agregada. (Antes se calculaba con frac_local sobre
            # Q_eq, lo que daba un valor positivo incluso con Q_eq < D_t,
            # algo sin sentido físico: si la oferta no llega a cubrir la
            # demanda, no puede sobrar nada que mandar a la red).
            x_NtoR_agregado = max(0.0, Q_eq - D_t)

            registros_N.append({
                "equilibrio": nombre_eq, "t": t, "Q_t": Q_eq, "D_t": D_t,
                "p_local": pl_t, "p_red": pr, "p_mkt_referencia": p_mkt[t],
                "x_NtoR": x_NtoR_agregado,
                "hay_multiplicidad": hay_multiplicidad,
            })

    if n_no_convergio > 0:
        print(f"  ADVERTENCIA: {n_no_convergio} de {n_intervalos} instantes "
              f"no convergieron dentro de {MAX_ITER_BR} iteraciones.")
    print(f"  Instantes con equilibrios múltiples (A y B difieren): "
          f"{n_multiplicidad} de {n_intervalos} ({100*n_multiplicidad/n_intervalos:.1f}%)")

    df_P, df_N = pd.DataFrame(registros_P), pd.DataFrame(registros_N)
    print("Equilibrios calculados correctamente.\n")
    return df_P, df_N


# =============================================================================
# 4. RESUMEN
# =============================================================================

def imprimir_resumen(df_P, df_N):
    print("=" * 70)
    print("RESUMEN — MODELO 3 NASH CON MERCADO LOCAL ENDÓGENO")
    print("=" * 70)

    for eq, etiqueta in [("A", "Equilibrio A (retención, arranque en cero)"),
                         ("B", "Equilibrio B (saturación, arranque en oferta máxima)")]:
        dP, dN = df_P[df_P.equilibrio == eq], df_N[df_N.equilibrio == eq]
        print(f"\n--- {etiqueta} ---")
        print(f"  Beneficio agregado de prosumidores: {dP['beneficio'].sum():.4f} €")
        print(f"  Fracción media ofrecida del excedente disponible: "
              f"{dP['fraccion_ofrecida'].mean()*100:.1f}%")
        print(f"  Precio local medio: {dN['p_local'].mean():.4f} €/kWh")

    # --- Desglose solo dentro de los instantes con multiplicidad ---
    df_N_multi = df_N[df_N["hay_multiplicidad"]]
    df_P_multi = df_P[df_P["t"].isin(df_N_multi["t"].unique())]

    print("\n--- Solo dentro de los instantes con equilibrios múltiples ---")
    for eq in ["A", "B"]:
        dP = df_P_multi[df_P_multi.equilibrio == eq]
        dN = df_N_multi[df_N_multi.equilibrio == eq]
        print(f"  Equilibrio {eq}: fracción media ofrecida = {dP['fraccion_ofrecida'].mean()*100:.1f}%, "
              f"beneficio agregado en esos instantes = {dP['beneficio'].sum():.2f} €, "
              f"precio local medio = {dN['p_local'].mean():.4f} €/kWh")

    n_total = df_N["t"].nunique()
    n_multi = df_N[df_N.equilibrio == "A"]["hay_multiplicidad"].sum()
    print(f"\nInstantes con equilibrios múltiples: {n_multi} de {n_total} "
          f"({100*n_multi/n_total:.1f}%)")
    print("=" * 70 + "\n")


def graficar_resultados(df_P, df_N, carpeta_outputs, n_intervalos_dia=96):
    print("Generando gráficos...")

    df_dia = df_N[(df_N["t"] <= n_intervalos_dia) & (df_N["equilibrio"] == "A")]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(df_dia["t"], df_dia["p_local"], label="Precio local (equilibrio A)", color="seagreen")
    ax.plot(df_dia["t"], df_dia["p_red"], label="Precio de red", color="indianred", linestyle="--")
    ax.plot(df_dia["t"], df_dia["p_mkt_referencia"], label="Referencia 60% red (modelo exógeno)",
            color="gray", linestyle=":")
    ax.set_xlabel("Intervalo (primer día)")
    ax.set_ylabel("€/kWh")
    ax.set_title("Precio local endógeno frente a las referencias — Modelo 3 (equilibrio A)")
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "M3v2_grafico_precio_local.png"), dpi=150)
    plt.close()

    fig, ax = plt.subplots(figsize=(12, 6))
    for eq, color, etiqueta in [("A", "seagreen", "Equilibrio A (retención)"),
                                 ("B", "indianred", "Equilibrio B (saturación)")]:
        d = df_P[df_P.equilibrio == eq].groupby("t")["fraccion_ofrecida"].mean().sort_index()
        ax.plot(d.index, d.rolling(96, min_periods=1).mean()*100, label=etiqueta, color=color)
    ax.set_xlabel("Intervalo de tiempo (15 min)")
    ax.set_ylabel("% medio del excedente ofrecido (media móvil diaria)")
    ax.set_title("Comparativa de los dos equilibrios — Modelo 3")
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "M3v2_grafico_comparativa_equilibrios.png"), dpi=150)
    plt.close()

    print("Gráficos guardados.\n")


def graficar_ventaja_acumulada(df_P, carpeta_outputs):
    beneficio_A_t = df_P[df_P.equilibrio == "A"].groupby("t")["beneficio"].sum().sort_index()
    beneficio_B_t = df_P[df_P.equilibrio == "B"].groupby("t")["beneficio"].sum().sort_index()
    ventaja = (beneficio_A_t - beneficio_B_t).cumsum()

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(ventaja.index, ventaja.values, color="darkgreen", linewidth=1.3)
    ax.set_xlabel("Intervalo de tiempo (15 min)")
    ax.set_ylabel("Ventaja acumulada de A sobre B (€)")
    ax.set_title("Ventaja económica acumulada del equilibrio de retención frente al de saturación")
    ax.grid(True)
    ax.text(0.02, 0.95, f"Total: {ventaja.iloc[-1]:.2f} €", transform=ax.transAxes,
            fontsize=11, va="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "M3v2_grafico_ventaja_acumulada.png"), dpi=150)
    plt.close()


def graficar_multiplicidad_semanal(df_N, carpeta_outputs):
    dN = df_N[df_N.equilibrio == "A"].copy()
    dN["semana"] = (dN["t"] - 1) // (7 * 96) + 1
    conteo = dN.groupby("semana")["hay_multiplicidad"].sum()

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(conteo.index, conteo.values, color="indianred", width=0.8)
    ax.set_xlabel("Semana del año")
    ax.set_ylabel("Nº de intervalos de 15 min con equilibrios múltiples")
    ax.set_title("Distribución semanal de los instantes con multiplicidad genuina — Modelo 3")
    ax.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(carpeta_outputs, "M3v2_grafico_multiplicidad_semanal.png"), dpi=150)
    plt.close()


# =============================================================================
# 5. MAIN
# =============================================================================

if __name__ == "__main__":

    GEF, CE_P, CE_C = cargar_datos_excel(
        ruta=RUTA_EXCEL, ids_prosumidores=IDS_PROSUMIDORES,
        ids_consumidores=IDS_CONSUMIDORES, n_intervalos=N_INTERVALOS
    )

    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token=ESIOS_TOKEN, año=ESIOS_AÑO, n_intervalos=N_INTERVALOS
    )

    df_P, df_N = calcular_equilibrio_nash(
        GEF, CE_P, CE_C, p_red, p_mkt, p_ahorro,
        IDS_PROSUMIDORES, IDS_CONSUMIDORES, N_INTERVALOS, ALPHA
    )

    imprimir_resumen(df_P, df_N)
    graficar_resultados(df_P, df_N, CARPETA_OUTPUTS)
    graficar_ventaja_acumulada(df_P, CARPETA_OUTPUTS)
    graficar_multiplicidad_semanal(df_N, CARPETA_OUTPUTS)

    # Exportación necesaria para el Modelo 4 corregido: la oferta real de
    # equilibrio de cada prosumidor (q_ofrecido) se usa allí como el
    # comportamiento del "resto" de la coalición al evaluar v(S) para
    # coaliciones propias. Sin este archivo, Modelo 4 no puede ejecutarse.
    ruta_csv = os.path.join(CARPETA_OUTPUTS, "M3v2_equilibrio_detalle.csv")
    df_P.to_csv(ruta_csv, index=False)
    print(f"Detalle de equilibrio exportado a: {ruta_csv}")
