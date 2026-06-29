"""
=============================================================================
MÓDULO DE DESCARGA DE PRECIOS PVPC — API ESIOS (REE)
Proyecto NexusFlex — TFG
=============================================================================
Descripción:
    Descarga los precios horarios del PVPC (Precio Voluntario para el
    Pequeño Consumidor) del año 2022 desde la API de ESIOS (Red Eléctrica
    de España) y los convierte al formato de diccionario indexado por t
    que usan los modelos de optimización.

    Los precios se descargan en €/MWh y se convierten a €/kWh.
    Los precios horarios se replican a intervalos de 15 minutos
    (4 intervalos por hora) para ser consistentes con la granularidad
    de los datos de consumo y generación.

    Si la descarga falla (sin conexión o token inválido), el módulo
    cae automáticamente a los precios sintéticos como fallback.

Uso:
    from esios_precios import obtener_precios_pvpc

    p_red, p_mkt, p_ahorro = obtener_precios_pvpc(
        token    = "tu_token_aqui",
        año      = 2022,
        n_intervalos = N_INTERVALOS
    )

API ESIOS:
    Indicador 1001: PVPC (€/MWh)
    Documentación: https://api.esios.ree.es
=============================================================================
"""

import requests
import math
import pandas as pd
from datetime import datetime, timedelta


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def obtener_precios_pvpc(token, año=2022, n_intervalos=34944):
    """
    Descarga los precios PVPC horarios de ESIOS para el año indicado
    y los devuelve como diccionarios indexados por t (1-based).

    Parámetros:
        token        : token personal de la API de ESIOS
        año          : año a descargar (por defecto 2022)
        n_intervalos : número de intervalos de 15 min a devolver

    Devuelve:
        p_red    : dict {t: precio_red_en_€/kWh}
        p_mkt    : dict {t: precio_nexus_en_€/kWh}  (60% de p_red)
        p_ahorro : dict {t: min(p_mkt, p_red)}
    """
    print(f"Descargando precios PVPC {año} desde ESIOS...")

    try:
        precios_horarios = _descargar_pvpc_anual(token, año)

        if precios_horarios is None or len(precios_horarios) == 0:
            raise ValueError("No se obtuvieron precios de ESIOS.")

        p_red, p_mkt, p_ahorro = _convertir_a_intervalos_15min(
            precios_horarios, n_intervalos
        )

        print(f"  Precios PVPC {año} descargados correctamente.")
        print(f"  Rango: {min(p_red.values()):.4f} — {max(p_red.values()):.4f} €/kWh")
        print()
        return p_red, p_mkt, p_ahorro

    except Exception as e:
        print(f"  ADVERTENCIA: Error al descargar precios de ESIOS: {e}")
        print("  Usando precios sintéticos como fallback.\n")
        return _precios_sinteticos_fallback(n_intervalos)


# =============================================================================
# DESCARGA ANUAL POR MESES
# =============================================================================

def _descargar_pvpc_anual(token, año):
    """
    Descarga los precios PVPC horarios mes a mes para el año completo.
    Devuelve una lista de (datetime, precio_€/MWh) ordenada por fecha.

    Prueba primero el formato x-api-key (moderno) y si falla
    prueba el formato Authorization: Token token= (antiguo).
    """
    # Formato moderno (recomendado por ESIOS desde 2022)
    headers = {
        "x-api-key": token,
        "Accept": "application/json; application/vnd.esios-api-v2+json",
        "Content-Type": "application/json",
        "Host": "api.esios.ree.es",
    }

    # Verificar token con petición de prueba
    test_url = (
        "https://api.esios.ree.es/indicators/1001"
        "?time_trunc=hour"
        "&start_date=2022-01-01T00:00:00"
        "&end_date=2022-01-01T23:59:59"
    )
    test_response = requests.get(test_url, headers=headers, timeout=30)

    if test_response.status_code == 403:
        # Probar formato antiguo
        print("  Probando formato alternativo de autenticación...")
        headers = {
            "Authorization": f"Token token={token}",
            "Accept": "application/json; application/vnd.esios-api-v2+json",
            "Content-Type": "application/json",
            "Host": "api.esios.ree.es",
        }
        test_response2 = requests.get(test_url, headers=headers, timeout=30)
        if test_response2.status_code == 403:
            raise ConnectionError(
                "Token rechazado con ambos formatos (403). "
                "Verifica que el token es correcto y está activo en "
                "https://api.esios.ree.es"
            )
        print("  Formato alternativo aceptado.")
    else:
        print("  Formato x-api-key aceptado.")

    indicador = 1001  # PVPC €/MWh
    base_url  = "https://api.esios.ree.es/indicators"

    todos_los_precios = []

    # Descargamos mes a mes para evitar respuestas demasiado grandes
    for mes in range(1, 13):
        fecha_inicio = datetime(año, mes, 1)
        if mes == 12:
            fecha_fin = datetime(año, 12, 31, 23, 59, 59)
        else:
            fecha_fin = datetime(año, mes + 1, 1) - timedelta(seconds=1)

        url = (
            f"{base_url}/{indicador}"
            f"?start_date={fecha_inicio.strftime('%Y-%m-%dT%H:%M:%S')}"
            f"&end_date={fecha_fin.strftime('%Y-%m-%dT%H:%M:%S')}"
            f"&time_trunc=hour"
        )

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            raise ConnectionError(
                f"Error HTTP {response.status_code} al descargar mes {mes}/{año}"
            )

        datos = response.json()
        valores = datos["indicator"]["values"]

        for v in valores:
            # Parsear fecha
            fecha_str = v["datetime"]
            # ESIOS devuelve fechas en formato ISO con zona horaria
            fecha = pd.to_datetime(fecha_str, utc=True).tz_convert("Europe/Madrid")
            precio_mwh = float(v["value"])
            precio_kwh = precio_mwh / 1000.0
            todos_los_precios.append((fecha, precio_kwh))

        print(f"  Mes {mes:02d}/{año}: {len(valores)} horas descargadas")

    # Ordenar por fecha
    todos_los_precios.sort(key=lambda x: x[0])
    return todos_los_precios


# =============================================================================
# CONVERSIÓN DE HORARIO A INTERVALOS DE 15 MIN
# =============================================================================

def _convertir_a_intervalos_15min(precios_horarios, n_intervalos):
    """
    Replica cada precio horario a 4 intervalos de 15 minutos.
    Devuelve diccionarios indexados por t (1-based).

    Si hay menos horas de las necesarias (p. ej. por años bisiestos
    o horas de cambio de horario), rellena con el último valor disponible.
    """
    p_red    = {}
    p_mkt    = {}
    p_ahorro = {}

    t = 1
    for _, precio_kwh in precios_horarios:
        for _ in range(4):  # 4 intervalos de 15 min por hora
            if t > n_intervalos:
                break
            p_red[t]    = round(precio_kwh, 6)
            p_mkt[t]    = round(0.60 * precio_kwh, 6)
            p_ahorro[t] = min(p_mkt[t], p_red[t])
            t += 1
        if t > n_intervalos:
            break

    # Si faltan intervalos (no debería ocurrir con un año completo),
    # rellenar con el último precio disponible
    if t <= n_intervalos:
        ultimo_precio = p_red.get(t - 1, 0.10)
        print(f"  ADVERTENCIA: rellenando {n_intervalos - t + 1} "
              f"intervalos faltantes con {ultimo_precio:.4f} €/kWh")
        while t <= n_intervalos:
            p_red[t]    = ultimo_precio
            p_mkt[t]    = round(0.60 * ultimo_precio, 6)
            p_ahorro[t] = p_mkt[t]
            t += 1

    return p_red, p_mkt, p_ahorro


# =============================================================================
# FALLBACK: PRECIOS SINTÉTICOS
# =============================================================================

def _precios_sinteticos_fallback(n_intervalos):
    """
    Genera precios sintéticos basados en el patrón PVPC español
    como alternativa cuando la descarga de ESIOS falla.
    """
    print("Generando precios sintéticos de fallback...")

    p_red    = {}
    p_mkt    = {}
    p_ahorro = {}

    for t in range(1, n_intervalos + 1):
        hora        = ((t - 1) % 96) / 4.0
        pico_manana = 0.06 * math.exp(-((hora - 9.0) / 2.0) ** 2)
        pico_tarde  = 0.08 * math.exp(-((hora - 19.0) / 2.0) ** 2)
        base_red    = 0.10
        p_red[t]    = round(base_red + pico_manana + pico_tarde, 6)
        p_mkt[t]    = round(0.60 * p_red[t], 6)
        p_ahorro[t] = min(p_mkt[t], p_red[t])

    return p_red, p_mkt, p_ahorro


# =============================================================================
# UTILIDAD: GUARDAR PRECIOS EN CSV (para diagnóstico)
# =============================================================================

def guardar_precios_csv(p_red, p_mkt, p_ahorro, ruta_salida):
    """
    Guarda los precios descargados en un CSV para verificación y diagnóstico.
    """
    df = pd.DataFrame({
        "t":       list(p_red.keys()),
        "p_red":   list(p_red.values()),
        "p_mkt":   list(p_mkt.values()),
        "p_ahorro": list(p_ahorro.values()),
    })
    df.to_csv(ruta_salida, index=False)
    print(f"Precios guardados en: {ruta_salida}")
