import pandas as pd
import os
import matplotlib.pyplot as plt
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

print(os.getcwd())
ruta = "C:\\Users\\imaria\\OneDrive - IREC-edu\\Code\\Python Space\\REAL Project\\Data_precleaned.xlsx"
ExcelFile = pd.ExcelFile(ruta)

print(ExcelFile.sheet_names)

total_consumers = pd.read_excel(ruta, sheet_name = "Total Consumers")
total_producers = pd.read_excel(ruta, sheet_name="Total Producers")

print(total_consumers)
print(total_producers)

## Gráfico del consumidor 1
plt.figure()
total_consumers[1].plot()

plt.title("Consumer1 - Evolución temporal")
plt.xlabel("Tiempo")
plt.ylabel("Consumo")
plt.show()

## Gráfico agregado
plt.figure()

total_consumers.sum(axis=1).plot()

plt.title("Consumo total agregado")
plt.xlabel("Tiempo")
plt.ylabel("Consumo total")
plt.show()

## Gráfico producción vs consumo agregados
plt.figure()

total_consumers.sum(axis=1).plot()
total_producers.sum(axis=1).plot()

plt.legend(["Consumo", "Producción"])
plt.title("Consumo vs Producción")
plt.xlabel("Tiempo")
plt.ylabel("Energía")
plt.show()

print(total_consumers.columns)

## Análisis individuo 1
consumer1 = total_consumers[1]

plt.figure(figsize=(10,4))
consumer1.plot()
plt.title("Consumidor 1")
plt.show()

## Análisis completo
for col in total_consumers.columns:
    serie = total_consumers[col]
    
    print("------ Columna", col, "------")
    print("NaN:", serie.isna().sum())
    print("Min:", serie.min())
    print("Max:", serie.max())
    print("Negativos:", (serie < 0).sum())
    print("Ceros:", (serie == 0).sum())
    print()

### Actividad 0.1: Solcuonar señales correlacionadas.
# Paso 1: Normalización
import numpy as np
import pandas as pd

def normalizar_serie(serie):
    if serie.std() == 0:
        return None  # señal constante, la ignoramos
    return (serie - serie.mean()) / serie.std()

df = total_consumers.copy()

normalizadas = {}

for col in df.columns:
    serie = df[col].dropna()
    norm = normalizar_serie(serie)
    if norm is not None:
        normalizadas[col] = norm.values

# Paso 2: Comparación entre todas las señales.
from itertools import combinations

duplicadas = []
reales = set(normalizadas.keys())
visitadas = set()

for col1, col2 in combinations(normalizadas.keys(), 2):
    
    if col1 in visitadas or col2 in visitadas:
        continue
    
    s1 = normalizadas[col1]
    s2 = normalizadas[col2]
    
    # Asegurar misma longitud
    min_len = min(len(s1), len(s2))
    s1 = s1[:min_len]
    s2 = s2[:min_len]
    
    correlacion = np.corrcoef(s1, s2)[0, 1]
    
    if abs(correlacion) > 0.9999:  # umbral muy alto
        duplicadas.append((col1, col2, correlacion))
        visitadas.add(col2)
        if col2 in reales:
            reales.remove(col2)

# Paso extra: Visualización.
print("Señales duplicadas encontradas:")
for d in duplicadas:
    print(d)

print("\nNúmero total original:", len(df.columns))
print("Número de señales reales:", len(reales))
print("Columnas reales:", sorted(reales))

# Paso 3: Eliminar duplicadas.
df_limpio = df[sorted(reales)].copy()

### Actividad 0.2: Solucionar datos auséntes de prosumidores.
# Paso 1: Detectar patrón real.
usuario = 1
serie = total_producers[usuario].copy()

## Crear índice temporal si no lo tienes ya
if not isinstance(serie.index, pd.DatetimeIndex):
    time_index = pd.date_range(
        start="2019-01-01 00:00:00",
        periods=len(serie),
        freq="15min"
    )
    serie.index = time_index

## Crear columna auxiliar con hora del día (0–95)
serie_df = serie.to_frame(name="produccion")
serie_df["periodo_dia"] = (
    serie_df.index.hour * 4 +
    serie_df.index.minute // 15
)

## Promedio por período del día
perfil_medio = serie_df.groupby("periodo_dia")["produccion"].mean()

perfil_con_sol = perfil_medio.copy()
perfil_sin_sol = perfil_medio.copy()

perfil_con_sol[perfil_medio == 0] = np.nan
perfil_sin_sol[perfil_medio > 0] = np.nan

plt.figure(figsize=(12,5))

plt.plot(perfil_con_sol, label="Producción promedio", linewidth=2)
plt.plot(perfil_sin_sol, color="red", linewidth=2, label="Promedio = 0")

plt.title("Perfil promedio diario producción")
plt.xlabel("Período del día (0-95)")
plt.ylabel("Producción promedio")
plt.legend()
plt.show()

## Duración dia y noche
serie = total_producers[1].copy()

df = pd.DataFrame({"produccion": serie})
df["mes"] = df.index.month

umbral = 0.01  # todo lo menor que esto se considera noche

df["es_noche"] = df["produccion"] <= umbral
df["periodo_dia"] = (~df["es_noche"]).astype(int)  # 1 = día, 0 = noche

def obtener_periodos(grupo):
    noche = (grupo["es_noche"].sum())
    dia = len(grupo) - noche
    return pd.Series({"periodos_noche": noche, "periodos_dia": dia})

df.index = pd.date_range(start="2019-01-01 00:00:00", periods=len(df), freq="15min")

resumen_mensual = df.groupby([df.index.month, df.index.date]).apply(obtener_periodos)

promedio_mensual = resumen_mensual.groupby(level=0).mean()
print(promedio_mensual)

import pandas as pd
import numpy as np
from scipy.interpolate import interp1d

## total_producers ya tiene índices de fecha-hora
total_producers.index = pd.to_datetime(total_producers.index)
for usuario in range(15):  # solo los prosumidores
    serie = total_producers[usuario].copy()
    
    # Convertir a días
    dias = serie.index.date
    df_diario = serie.groupby(dias).sum()  # producción diaria total por día
    
    # Detectar días con producción cero total (faltantes)
    dias_faltantes = df_diario[df_diario == 0].dropna().index
    
    # Detectar bloques contiguos de días faltantes
    if len(dias_faltantes) == 0:
        continue
    
    bloques = []
    start = dias_faltantes[0]
    bloque = [start]
    
    for i in range(1, len(dias_faltantes)):
        if (dias_faltantes[i] - dias_faltantes[i-1]).days == 1:
            bloque.append(dias_faltantes[i])
        else:
            bloques.append(bloque)
            bloque = [dias_faltantes[i]]
    bloques.append(bloque)
    
    # Interpolación por bloque
    for bloque in bloques:
        # Rango de días alrededor para interpolar
        start = min(bloque) - pd.Timedelta(days=1)
        end = max(bloque) + pd.Timedelta(days=1)
        
        # Extraer datos reales alrededor del bloque
        mask = (serie.index.date >= start) & (serie.index.date <= end)
        serie_alrededor = serie[mask]
        
        # Solo tomar datos con producción > 0
        serie_alrededor = serie_alrededor[serie_alrededor > 0]
        if len(serie_alrededor) < 2:
            continue  # no hay suficientes datos para interpolar
        
        # Interpolación lineal temporal
        f = interp1d(
            serie_alrededor.index.astype(np.int64),
            serie_alrededor.values,
            kind='linear',
            fill_value="extrapolate"
        )
        
        # Rellenar días faltantes
        mask_faltantes = serie.index.date >= min(bloque)
        mask_faltantes &= serie.index.date <= max(bloque)
        serie.loc[mask_faltantes] = f(serie.loc[mask_faltantes].index.astype(np.int64))
    
    # Guardar de nuevo
    total_producers[usuario] = serie

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

usuario = 1  # ejemplo
serie = total_producers[usuario].copy()
serie.index = pd.to_datetime(serie.index)

# Identificar días con producción cero total
produccion_diaria = serie.groupby(serie.index.date).sum()
dias_faltantes = produccion_diaria[produccion_diaria == 0].index

if len(dias_faltantes) > 0:
    bloques = []
    bloque = [dias_faltantes[0]]
    for i in range(1, len(dias_faltantes)):
        if (dias_faltantes[i] - dias_faltantes[i-1]).days == 1:
            bloque.append(dias_faltantes[i])
        else:
            bloques.append(bloque)
            bloque = [dias_faltantes[i]]
    bloques.append(bloque)

    for bloque in bloques:
        start = min(bloque) - pd.Timedelta(days=1)
        end = max(bloque) + pd.Timedelta(days=1)
        mask = (serie.index.date >= start) & (serie.index.date <= end)
        serie_alrededor = serie[mask]

        # Reemplazar ceros por NaN solo donde haya datos alrededor
        serie_alrededor = serie_alrededor.replace(0, np.nan)

        # Interpolación temporal
        serie_alrededor = serie_alrededor.interpolate(method='time')

        # Si todavía quedan NaN (al inicio o final), rellenar con valores vecinos
        serie_alrededor = serie_alrededor.fillna(method='bfill').fillna(method='ffill')

        # Guardar
        serie.loc[mask] = serie_alrededor

total_producers[usuario] = serie

# Gráfico mensual
produccion_mensual = serie.resample('M').sum()
plt.figure(figsize=(10,5))
plt.bar(produccion_mensual.index.month, produccion_mensual.values, color='orange')
plt.xticks(range(1,13))
plt.xlabel("Mes")
plt.ylabel("Producción total mensual")
plt.title(f"Producción mensual usuario {usuario}")
plt.show()




serie.index = pd.to_datetime(serie.index)
print(serie.index)

print(serie.head(20))
print(serie.min(), serie.max())


### Actividad 1: Detectar quien tiene excedentes

# Paso 1: Calcular excedente instantáneo
excedentes = {}

for prod_id in range(0, 14):
    cons_id = prod_id + 1
    
    consumo = total_consumers[cons_id]
    produccion = total_producers[prod_id]
    
    min_len = min(len(consumo), len(produccion))
    consumo = consumo.iloc[:min_len]
    produccion = produccion.iloc[:min_len]
    
    excedente = produccion - consumo
    excedentes[cons_id] = excedente  # guardamos con ID real de consumidor

# Paso 2: Cuantificar excedente anual total
resumen_excedente = {}

for i in excedentes:
    excedente_positivo = excedentes[i][excedentes[i] > 0]
    energia_total = excedente_positivo.sum()
    
    resumen_excedente[i] = energia_total

print(resumen_excedente)

# Paso 3: Clasificación
## Paso 3.1: Variables a clusterizar
features = []

for i in range(1, 15):
    consumo = total_consumers[i]
    produccion = total_producers[i]
    
    min_len = min(len(consumo), len(produccion))
    consumo = consumo.iloc[:min_len]
    produccion = produccion.iloc[:min_len]
    
    excedente = produccion - consumo
    
    excedente_pos = excedente[excedente > 0]
    
    energia_total = excedente_pos.sum()
    porcentaje_tiempo = (excedente > 0).mean()
    max_excedente = excedente.max()
    media_excedente = excedente_pos.mean() if len(excedente_pos) > 0 else 0
    
    features.append([
        energia_total,
        porcentaje_tiempo,
        max_excedente,
        media_excedente
    ])

features = np.array(features)

## Paso 3.2: Normalización

scaler = StandardScaler()
features_scaled = scaler.fit_transform(features)

## Paso 3.3: Aplicar K-Means

kmeans = KMeans(n_clusters=3, random_state=42)
clusters = kmeans.fit_predict(features_scaled)

## Paso 3.4: Resultados

for i in range(15):
    print(f"Usuario {i} → Cluster {clusters[i]}")


import pandas as pd

## Paso 4: Visualización clusters
df_clusters = pd.DataFrame(features, columns=[
    "Energia_total",
    "%_tiempo",
    "Max_excedente",
    "Media_excedente"
])

df_clusters["Cluster"] = clusters

print(df_clusters.groupby("Cluster").mean())

### Actividad 2: Tabla de compradores
# Consumidores candidatos (sin producción FV)
candidatos = list(range(15, 51))

resumen_consumo = {}

for cons_id in candidatos:
    serie = total_consumers[cons_id]
    
    # Ignorar ceros y NaN
    serie_filtrada = serie[(serie != 0) & (~serie.isna())]
    
    consumo_total = serie_filtrada.sum()
    consumo_medio = serie_filtrada.mean()
    
    resumen_consumo[cons_id] = {
        "Consumo_total": consumo_total,
        "Consumo_medio": consumo_medio
    }

# Convertimos a DataFrame
df_compradores = pd.DataFrame(resumen_consumo).T

# Ordenar por menor consumo total
df_compradores = df_compradores.sort_values("Consumo_medio")

print(df_compradores.head(15))

## Selección automática de los 12 consumidores
top_12 = df_compradores.head(12)

print("Compradores seleccionados:")
print(top_12)

### Actividad 3: Cuantificar excedencia
## Paso 1: Construir diccionarios de excedentes y déficits
excedentes = {}
deficits = {}

for prod_id in range(0, 14):
    cons_id = prod_id + 1
    
    consumo = total_consumers[cons_id]
    produccion = total_producers[prod_id]
    
    min_len = min(len(consumo), len(produccion))
    consumo = consumo.iloc[:min_len]
    produccion = produccion.iloc[:min_len]
    
    excedente = produccion - consumo
    
    excedentes[cons_id] = excedente
    deficits[cons_id] = -excedente[excedente < 0]

## Paso 2: Crear DataFrame con métricas para clustering
features = []
usuarios = []

for cons_id in excedentes:
    exc_pos = excedentes[cons_id][excedentes[cons_id] > 0]
    def_pos = deficits[cons_id]
    
    energia_total = exc_pos.sum()
    porcentaje_tiempo_excedente = (excedentes[cons_id] > 0).mean()
    energia_maxima = exc_pos.max() if len(exc_pos) > 0 else 0
    energia_media = exc_pos.mean() if len(exc_pos) > 0 else 0
    deficit_total = def_pos.sum()
    
    features.append([
        energia_total,
        porcentaje_tiempo_excedente,
        energia_maxima,
        energia_media,
        deficit_total
    ])
    
    usuarios.append(cons_id)

features = np.array(features)

## Paso 3: Escalar las features
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features)

## Paso 4: Clustering
kmeans = KMeans(n_clusters=3, random_state=42)
clusters = kmeans.fit_predict(features_scaled)

## Paso 5: Crear DataFrame final
df_excedentes = pd.DataFrame(features, 
                             columns=["Energia_total", "%_tiempo_excedente", "Max_excedente", "Media_excedente", "Deficit_total"])
df_excedentes["Usuario"] = usuarios
df_excedentes["Cluster"] = clusters

## Paso 6: Interpretar clusters como alto/medio/bajo
cluster_mean = df_excedentes.groupby("Cluster")["Energia_total"].mean()
cluster_map = {}
cluster_map[cluster_mean.idxmax()] = "Excedente alto"
cluster_map[cluster_mean.idxmin()] = "Muy poco excedente"

## Cluster intermedio
intermedio = set(df_excedentes["Cluster"]) - set(cluster_map.keys())
cluster_map[list(intermedio)[0]] = "Poco excedente"

df_excedentes["Clasificacion"] = df_excedentes["Cluster"].map(cluster_map)

## Paso 7: Ordenar por energía total
df_excedentes = df_excedentes.sort_values("Energia_total", ascending=False).reset_index(drop=True)

## Paso 8: Mostrar resultados
print(df_excedentes)

### Actividad 4
## Solo 1 prosumidor
usuario = 1
serie = total_producers[usuario].copy()  # o total_consumers si fuese necesario

n_filas_rellenar = 996

relleno = serie[-n_filas_rellenar:].values
serie.iloc[:n_filas_rellenar] = relleno

print(serie.head(1000))

for prod_id in range(0, 14):
    serie = total_producers[prod_id].copy()
    
    relleno = serie[-n_filas_rellenar:].values
    serie.iloc[:n_filas_rellenar] = relleno
    
    total_producers[prod_id] = serie

print(total_producers.head)