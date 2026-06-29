# Bachelor-s-Thesis
My final Bachelor's Thesis

# Optimización de Mecanismos y Estrategias para el Intercambio P2P en un Marketplace de Excedentes Fotovoltaicos

Trabajo de Fin de Grado — Grado en Estadística y Economía (UB · UPC)
Proyecto **NexusFlex** · Nexus Energía / IREC (Institut de Recerca en Energia de Catalunya)

Este repositorio contiene la implementación completa de una familia progresiva de cinco modelos de optimización matemática para el intercambio entre pares (P2P) de excedentes fotovoltaicos en una comunidad energética, junto con el análisis comparativo entre ellos.

---

## Descripción

El trabajo construye y compara cinco modelos de complejidad creciente, todos sobre el mismo ecosistema de 19 agentes (6 prosumidores con generación fotovoltaica y 13 consumidores puros) y validados con precios reales del PVPC español de 2022:

| Modelo | Enfoque | Técnica |
|--------|---------|---------|
| **Modelo 0** | Determinista centralizado | Programación lineal |
| **Modelo 1** | Optimización robusta | Formulación max-min (peor caso) |
| **Modelo 2** | Optimización estocástica | Escenarios probabilísticos |
| **Modelo 3** | Competencia | Juego de Nash con precio endógeno |
| **Modelo 4** | Cooperación | Valor de Shapley y nucleolus |

Adicionalmente, se incluye un script de comparación que calcula el **precio de la robustez** (Modelo 0 vs Modelo 1) y el **valor de la solución estocástica (VSS)** (Modelo 0 vs Modelo 2).

---

## Estructura del repositorio

```
.
├── modelo_0_determinista.py      # Modelo 0: determinista (referencia base)
├── modelo_1_robusto.py           # Modelo 1: optimización robusta
├── modelo_2_estocastico.py       # Modelo 2: optimización estocástica
├── modelo_3_nash.py              # Modelo 3: juego de Nash (competencia)
├── modelo_4_cooperativo.py       # Modelo 4: cooperación (Shapley/nucleolus)
├── comparacion_modelo_0_vs_2.py  # Cálculo del VSS (Modelo 0 vs Modelo 2)
├── esios_precios.py              # Descarga de precios PVPC desde la API de ESIOS
├── estilo_graficos.py            # Estilo común de gráficos (legibilidad)
└── README.md
```

Cada modelo es un script independiente y autocontenido. Los archivos `esios_precios.py` y `estilo_graficos.py` son módulos auxiliares que los modelos importan, por lo que deben estar en la misma carpeta.

---

## Requisitos

- **Python 3.9 o superior**
- **Solver HiGHS** (open source, se instala con `highspy`)

Librerías de Python:

```bash
pip install pyomo highspy pandas numpy matplotlib requests openpyxl
```

| Librería | Uso |
|----------|-----|
| `pyomo` | Modelado algebraico de los problemas de optimización |
| `highspy` | Solver HiGHS para programación lineal |
| `pandas`, `numpy` | Manipulación de datos y cálculo numérico |
| `matplotlib` | Generación de gráficos |
| `requests` | Descarga de precios desde la API de ESIOS |
| `openpyxl` | Lectura del Excel de datos (`.xlsx`) |

---

## Datos de entrada

Los modelos se alimentan de dos fuentes:

1. **Perfiles de generación y consumo** — un archivo Excel (`data_unificada.xlsx`) con una hoja por agente, construido a partir de tres repositorios públicos:
   - Consumo doméstico: Zenodo [5106455](https://doi.org/10.5281/zenodo.5106455) (Ramos et al., 2021)
   - Consumo de edificios: Zenodo [10854881](https://doi.org/10.5281/zenodo.10854881) (Gonçalves et al., 2024)
   - Generación fotovoltaica: Dryad [m37pvmd99](https://doi.org/10.5061/dryad.m37pvmd99) (Lin et al., 2024)

2. **Precios PVPC 2022** — descargados automáticamente desde la API pública de ESIOS (Red Eléctrica de España), indicador 1001. Si la descarga falla, el sistema recurre a precios sintéticos como respaldo.

> El archivo `data_unificada.xlsx` no se incluye en el repositorio. Puede reconstruirse a partir de las tres fuentes públicas referenciadas. Los datos originales del proyecto NexusFlex están sujetos a un acuerdo de confidencialidad con Nexus Energía.

---

## Configuración

Antes de ejecutar, revisa las constantes al inicio de cada script (sección `CONFIGURACIÓN`):

```python
RUTA_EXCEL   = r"...\data_unificada.xlsx"   # ruta al Excel de datos
CARPETA_OUTPUTS = r"...\Outputs"            # carpeta donde se guardan resultados
N_SEMANAS    = 52                           # 1 = prueba rápida; 52 = año completo
ALPHA        = 0.05                         # coeficiente de compensación regulado
CAP_ED       = 1000.0                       # capacidad de gestión de Nexus (kWh)
ESIOS_TOKEN  = "tu_token_de_esios_aqui"     # token personal de la API de ESIOS
```

Notas:

- **`N_SEMANAS`** controla el horizonte temporal. Usa `1` para una prueba rápida (segundos) y `52` para el año completo (varios minutos a varias horas según el modelo).
- **Token de ESIOS**: necesitas un token personal gratuito, solicitable escribiendo a `consultasios@ree.es`. Consulta la [documentación de la API de ESIOS](https://api.esios.ree.es).
- Ajusta `RUTA_EXCEL` y `CARPETA_OUTPUTS` a las rutas de tu equipo.

---

## Ejecución

Cada modelo se ejecuta de forma independiente:

```bash
python modelo_0_determinista.py
python modelo_1_robusto.py
python modelo_2_estocastico.py
python modelo_3_nash.py
python modelo_4_cooperativo.py
```

Para el análisis comparativo del valor de la solución estocástica:

```bash
python comparacion_modelo_0_vs_2.py
```

Cada script imprime un resumen por consola y guarda los resultados (tablas en CSV y gráficos en PNG) en la carpeta `CARPETA_OUTPUTS`.

### Orden recomendado

Los modelos son independientes y pueden ejecutarse en cualquier orden. No obstante, para reproducir el análisis completo del trabajo se recomienda seguir el orden 0 → 1 → 2 → 3 → 4, ya que refleja la progresión metodológica de la memoria.

---

## Resultados principales

Sobre el horizonte anual completo (2022), los modelos arrojan, entre otros:

- **Modelo 0:** ahorro agregado de ~19.224 € frente a la operación sin plataforma (reducción del 44,3 % del gasto energético).
- **Modelos 1 y 2:** precio de la robustez de ~7.209 € frente a un valor de la solución estocástica de ~122 €, lo que favorece el enfoque estocástico para gestionar la incertidumbre.
- **Modelos 3 y 4:** la cooperación entre prosumidores mejora el resultado agregado en ~8,6 % respecto a la competencia descentralizada.

---

## Reproducibilidad

Todo el trabajo está diseñado para ser reproducible con fuentes públicas. Cualquier investigador puede:

1. Descargar los tres datasets públicos referenciados.
2. Construir el archivo `data_unificada.xlsx`.
3. Obtener un token de ESIOS.
4. Ejecutar los scripts en el orden indicado.

---

## Autoría

- **Autor:** Iker Maria Montes
- **Director:** Francisco Arellano Espitia
- **Codirector:** Albert Solà Vilalta
- **Tutor:** Mikel Álvarez Mozos

Trabajo de Fin de Grado · Grado en Estadística y Economía · Universitat de Barcelona y Universitat Politècnica de Catalunya · Junio 2026
