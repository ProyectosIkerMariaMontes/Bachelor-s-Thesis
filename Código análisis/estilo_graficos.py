"""
=============================================================================
ESTILO COMÚN DE GRÁFICOS — Proyecto NexusFlex (TFG)
=============================================================================
Sube globalmente el tamaño de fuente de TODOS los gráficos de matplotlib
para que sigan siendo legibles después de reducirse al pegarlos en Word.

Uso:
    Añadir al PRINCIPIO de cada modelo, justo después de
    "import matplotlib.pyplot as plt":

        import estilo_graficos   # aplica el estilo legible automáticamente

    No hace falta nada más: con solo importarlo, el estilo queda activo.

Por qué funciona:
    Cuando se pega una imagen en Word, esta se reduce (típicamente al
    60-80% de su tamaño original). Si la fuente se diseñó para verse bien
    a tamaño completo, al reducirse queda diminuta. La solución es generar
    la figura con fuentes GRANDES de origen, de modo que tras la reducción
    sigan teniendo un tamaño cómodo de lectura.
=============================================================================
"""

import matplotlib
import matplotlib.pyplot as plt

# Backend no interactivo (evita problemas al guardar sin pantalla)
matplotlib.use("Agg")

# -----------------------------------------------------------------------------
# Tamaños de fuente generosos, pensados para sobrevivir a la reducción en Word.
# Si aún los quieres más grandes/pequeños, ajusta ESCALA (1.0 = estos valores).
# -----------------------------------------------------------------------------
ESCALA = 1.0

plt.rcParams.update({
    "font.size":         int(15 * ESCALA),  # tamaño base de todo el texto
    "axes.titlesize":    int(18 * ESCALA),  # título de cada subgráfico
    "axes.labelsize":    int(16 * ESCALA),  # etiquetas de los ejes (x, y)
    "xtick.labelsize":   int(13 * ESCALA),  # números del eje x
    "ytick.labelsize":   int(13 * ESCALA),  # números del eje y
    "legend.fontsize":   int(12 * ESCALA),  # texto de la leyenda
    "figure.titlesize":  int(19 * ESCALA),  # título global de la figura
    "lines.linewidth":   2.0,               # líneas algo más gruesas
    "savefig.dpi":       150,               # resolución de guardado
    "savefig.bbox":      "tight",           # recorta márgenes sobrantes
})
