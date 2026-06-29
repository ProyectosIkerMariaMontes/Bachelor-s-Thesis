# Carpeta de datos

Esta carpeta contiene los archivos de datos que alimentan los modelos de optimización.

## Archivo no incluido: `productores.xlsx`

El archivo **`productores.xlsx`** (~48 MB) **no se incluye en este repositorio** por superar el límite de tamaño de GitHub para archivos individuales.

Contiene las series temporales de **generación fotovoltaica** de los 6 prosumidores a resolución de 15 minutos para el año de referencia.

### Cómo obtenerlo

Hay dos formas de conseguir este archivo:

**Opción A — Descargar el archivo ya construido**

Disponible en el siguiente enlace externo:

> ⚠️ _Sustituir por el enlace real (Zenodo, Google Drive, OneDrive, etc.)_
> `https://...`

Una vez descargado, colócalo en esta misma carpeta con el nombre exacto `productores.xlsx`.

**Opción B — Reconstruirlo desde la fuente pública original**

Los datos de generación fotovoltaica provienen del repositorio público:

- Dryad — Lin et al. (2024): [https://doi.org/10.5061/dryad.m37pvmd99](https://doi.org/10.5061/dryad.m37pvmd99)

A partir de esa fuente, los scripts de preprocesamiento del proyecto seleccionan las 6 instalaciones con perfiles de generación más naturales, tratan los valores anómalos y ausentes, y unifican las series. El resultado es el archivo `productores.xlsx`.

## Archivos sí incluidos

El resto de archivos `.xlsx` de esta carpeta (datos de consumo y datos unificados) sí están incluidos en el repositorio, al no superar el límite de tamaño.

---

**Importante:** ningún script funcionará correctamente hasta que `productores.xlsx` esté presente en esta carpeta. Si lo ejecutas sin él, obtendrás un error de archivo no encontrado.
