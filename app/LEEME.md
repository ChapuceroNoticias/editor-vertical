# Editor vertical automático (16:9 -> 9:16)

## Instalación
Con el instalador (`Instalar.bat`, ver `LEEME.txt` junto a la carpeta `app`): instala Python, ffmpeg, Whisper,
Ollama y crea el acceso directo **Editor Vertical** y las carpetas **VideosEdit** y **Renders** en el escritorio.

## Interfaz
Doble clic en **Editor Vertical** (escritorio). Se abre en el navegador (http://127.0.0.1:7860) con el estilo «Grafito»
(oscuro, letra Geist; el rojo solo en la acción principal). A la izquierda está el menú: **Editor**, **Video largo**,
**Lo aprendido** y **Registro** (lo que va haciendo, paso a paso), y abajo **⏻ Cerrar**: detiene todo lo que esté
trabajando (análisis, exportación, vistas previas, video largo) y apaga la plataforma; para volver a usarla, abre
«Editor Vertical» desde el escritorio.
En **Editor**: «Nuevo video» (video, título, estilo de edición en tarjetas, **Analizar video**) y a la derecha los
**trabajos recientes** (clic = abrirlo; «Abrir otro trabajo» para los demás). Con un trabajo abierto, arriba quedan
**←** (volver), el título, **Exportar** y los pasos **Edición · Subtítulos · Exportar**. En Edición, las herramientas
van en el panel de la derecha por pestañas (Pantalla, Imagen, Stickers, Encuadre, Cortes, Más); se cambia sola a la del bloque
o sticker que eliges.
La línea de tiempo tiene abajo el carril **Audio** con la onda del sonido y una marca por cada corte (gris: pausas que
quitó el automático; rojo: tramos quitados a mano). Clic en una marca = pestaña **Cortes**: se ve la onda de lo que
se quitó y de alrededor; arrastra las orillas rojas para recuperar (hacia adentro) o quitar más (hacia afuera),
«▶ Cómo queda» / «▶ Lo quitado» para escuchar, «Recuperar 0.05 s por lado», «Recuperar todo» (Supr) y
‹ Anterior / Siguiente › para recorrerlos.

- **Videos:** pon los videos en la carpeta **VideosEdit** del escritorio. Al exportar, el video final queda en la
  carpeta **Renders** del escritorio con el **título** del cuadro «Título» como nombre (si ya hay otro igual, se le
  agrega (2), (3)...; sin título, con el nombre del video). El desplegable «Nombre del video» lee esa carpeta;
  los que ya tienen su carpeta `_trabajo` dicen **✔ Editado** (al elegirlo se propone abrir ese trabajo y su título).
  «Carpeta _trabajo» lista los trabajos que ya existen, los más recientes primero. ↻ vuelve a leer la carpeta.
  Si el video es .mov, .mkv, .avi, .webm, .m4v, .mts, .flv o .wmv, primero se convierte a MP4.
- **Lectura de textos:** cuando Nacho lee un tweet o una nota de la proyección, el texto se muestra en pantalla
  dividida con zoom (unas 5 líneas) y la cámara sigue la palabra que va leyendo. Mientras hace scroll se ve a Nacho.
  Usa OCR local (RapidOCR); la primera vez descarga sus modelos (~15 MB). Ajustes en la plantilla, sección `lectura`.
- **Imágenes:** al analizar ya **no se buscan imágenes solas**: el video se arma igual (encuadres, pantalla dividida,
  lectura, cortes, subtítulos) pero sin fotos. Si hace falta una, se agrega a mano en la pestaña Edición
  («Agregar imagen aquí», buscar en internet o subir tus fotos). Para volver a la búsqueda
  automática: `set IMAGENES_AUTOMATICAS=1` antes de `python interfaz.py`.
- **Sonido de aviso:** suena (`web/notificacion.mp3`) cuando termina un análisis, una exportación, un «Renderizar de
  nuevo» y cada clip de Video largo.
- **⛔ Cancelar todo** (junto a la barra de progreso): detiene al instante lo que esté trabajando —análisis,
  exportación, conversión, vista fluida, búsqueda de clips del video largo— y saca de la cola
  los fragmentos que esperaban. Si se cancela una exportación, el video a medias se borra.
- **Salida:** MP4 H.264 1080x1920, audio AAC a un máximo de 125 kbps (se cambia en la plantilla: `salida.audio_kbps`).

- **Tiempos:** en toda la interfaz se escriben como minutos:segundos:centésimas, por ejemplo `01:05:30` = 1 min 5.3 s.
  También acepta `01:05` o segundos sueltos (`65.3`).
- **Analizar video** solo analiza (no arma el video final): así se revisa mucho más rápido con las vistas previas.
- **Edición** (todo en una sola pantalla): a la izquierda el video original con el recuadro que se usa; a la derecha
  la vista previa armada en vivo. Abajo la línea de tiempo con carriles (Pantalla, Imágenes, Encuadre de Nacho y
  Encuadre de la pantalla): **arrastra un bloque para moverlo y sus orillas para alargarlo o acortarlo** (se guarda al
  soltar); clic para ir a ese momento y **Ctrl + rueda** para acercar (la rueda sola solo mueve la página). Las orillas tienen **imán** 🧲: se pegan
  (al cuadro exacto) a las orillas de otros bloques, cambios de toma, pausas recortadas, silencios entre frases de
  Nacho y al cursor; una línea amarilla dice a qué se pegó. Con **Alt** apretado se mueven libres. Debajo, los paneles, que siempre muestran lo que
  hay en el punto donde estás:
  - *Pantalla en este momento:* pantalla completa, dividida o solo Nacho, y desde/hasta. Las opciones están siempre,
    también donde la plataforma vio «solo Nacho»: al elegir Dividida o Pantalla completa, ese rato pasa a pantalla
    partida con el recuadro de proyección de la plantilla; luego acomódalo con los recuadros amarillo y azul.
  - *Imagen:* fotos del momento (✕ quita una), dividida / pantalla completa / no mostrar, tiempos, movimiento de las
    fotos, buscar en internet, **📁 Subir desde la PC** (más fotos al momento), eliminar el momento. Si no hay imagen,
    aparecen las dos formas de poner una desde ese punto: **Opción 1 · 📁 Subir imagen desde la PC** (eliges una o
    varias fotos de tu computadora y se crea el momento con ellas) y **Opción 2 · 🔍 Buscar y agregar** (en internet).
    **📸 Captura de la pantalla de Nacho**: toma lo que Nacho proyecta (nota, tuit…) justo donde va el video, recortado
    del video horizontal en calidad completa, y lo pone como imagen con movimiento. Si ya hay imagen en ese punto,
    **📸 Captura** la agrega como otra foto de ese momento.
  - *Stickers:* biblioteca de stickers animados (círculo, óvalo, recuadro, esquinas, subrayado, tachado, flechas,
    tache, palomita, mano dando clic, ¡!, ¿?, destello, explosión). Clic en uno = se pone donde va el video (2.5 s).
    En la vista previa vertical se arrastra, la esquina ◢ lo agranda parejo, las agarraderas de los lados lo estiran
    solo a lo ancho o solo a lo alto (los de línea —círculo, óvalo, recuadro, esquinas, subrayado, tachado— se dibujan
    a la medida y la línea no se engorda), el punto de arriba lo gira (rueda = tamaño, Shift + rueda = girar).
    En el panel: color, ancho, alto, ↺ proporción, giro, voltear, centrar, duplicar, quitar. Quedan encima de lo que
    se ve pero debajo de la franja azul y del título. Su bloque rosa en la
    línea de tiempo (carril «Stickers») se mueve, se estira, se parte y se copia como los demás. Salen en el video
    final y se ven en vivo en Subtítulos.
  - *Encuadre:* sobre el video original hay dos recuadros. **Amarillo/verde = Nacho** (arrástralo, esquinas o Ctrl + rueda
    para acercar, doble clic para centrar; Fijo o Seguir la toma; se guarda solo al soltar, para todo ese tramo;
    para otros tiempos escribe desde/hasta y «Aplicar tiempos» o estira su bloque en la línea de tiempo).
    **Azul = lo que proyecta Nacho** (lo que se ve abajo en la pantalla dividida, o una imagen a pantalla completa):
    se mueve y acerca igual y se guarda solo al soltar, para todo ese tramo.
    **Movimiento de la pantalla de Nacho** (para usarla como si fuera una foto): en el panel Encuadre elige Acercar,
    Alejar o un Paneo (y ritmo suave o constante). Aparecen dos recuadros: azul = inicio y naranja = final; muévelos o
    ajústalos y el video pasa de uno al otro durante ese tramo (se ve en la vista previa y en el video final).
    Los recuadros corregidos a mano se mueven libres por todo el cuadro del video (pueden salirse del área detectada
    y hacerse más grandes que ella).
  - *Imagen sobre la pantalla:* si una imagen cae en un tramo en que Nacho tiene algo en pantalla, en el panel Imagen
    eliges qué se ve: «Esta imagen» o «Lo de la pantalla de Nacho». Las que agregas con «Agregar imagen aquí» ya
    vienen en «Esta imagen».
  - *Quitar tramos del video:* quita un pedazo (imagen y audio) y lo puedes restaurar.
  - Arriba: título, **💾 Guardar**, **Deshacer**, **Rehacer** y **⌨ Atajos**. Lo que arrastras en la línea de tiempo,
    los tramos quitados y las imágenes agregadas se guardan solos; **Guardar** (o Ctrl+S) guarda lo que quedó
    pendiente (título escrito, tiempos escritos en un panel, cambios de una imagen, encuadre). Se pone rojo
    («Guardar cambios») cuando hay algo sin guardar.
  - **🔄 Renderizar de nuevo:** si cambias la edición (por ejemplo agregas imágenes que hacen pantalla dividida, cambias
    tomas o encuadres, quitas tramos), este botón arma una **vista previa ligera** (mitad de tamaño, 15 cuadros por
    segundo, codificación rápida; unas 3 veces más rápido que exportar) con la edición actual, sin hacer el video final.
    Así la pestaña **Subtítulos** toma el acomodo nuevo (los subtítulos pasan a la franja azul donde ahora hay
    pantalla dividida). El video final se arma en **Exportar**. Se pone rojo («hay cambios») cuando la edición ya no
    corresponde a la vista previa; muestra el avance y se detiene con «⛔ Cancelar todo». La pestaña Subtítulos se
    actualiza sola al volver a ella (si tenía cambios sin guardar, avisa en lugar de recargar).
  - **Línea de tiempo:** regla con minutos y segundos (con zoom llega a décimas), el cursor rojo con el tiempo por
    el que va, una línea guía con el tiempo bajo el ratón y **doble clic** para llevar el cursor a ese punto
    (igual que en Video largo). **Ctrl + rueda** acerca o aleja.
  - **Mover pedazos del video (línea «Pantalla»):** los **bloques grises** (Nacho / lo que no se está usando) son
    pedazos del video: **clic** lo selecciona (y lleva ahí el cursor), **arrastrarlo** lo mueve a otro lugar, **Ctrl +
    arrastrarlo** deja una **copia** donde lo sueltes (para repetir una frase), y **S** (o Ctrl+B) lo parte en el cursor
    para mover o copiar solo una parte. Otra forma de repetir: selecciónalo, **Ctrl+C**, clic donde lo quieras y
    **Ctrl+V**. El clip dura más; con «Renderizar de nuevo» los subtítulos se acomodan. También **Shift + arrastrar** sobre la línea Pantalla selecciona cualquier
    pedazo del video (amarillo). Luego: **✂ Cortar** (Ctrl+X: lo quita y lo guarda), **⧉ Copiar** (Ctrl+C), **📋 Pegar
    en el cursor** (Ctrl+V: lo que sigue se recorre), **Duplicar** (Ctrl+D: lo repite justo después), **Quitar** (Supr:
    como «Quitar tramo», se puede restaurar) o **arrástralo** a otro lugar para moverlo (se pega a pausas y cortes; con
    Alt libre). El audio, los subtítulos, la pantalla, las imágenes y los encuadres de ese pedazo se van con él. El
    video se vuelve a armar desde el original (no pierde calidad) en la carpeta del trabajo; **Deshacer** lo regresa.
    Con un **tipo de pantalla** copiado de un bloque (Ctrl+C sobre un bloque de Pantalla) y un pedazo seleccionado,
    **Ctrl+V** pone esa pantalla en ese pedazo.
  - **Barra deslizable** debajo de la línea de tiempo: cuando la acercas (Ctrl + rueda) arrástrala para moverte por
    el video; la rueda sola sobre la línea también avanza o regresa.
  - **«9:16» (Pantalla en este momento):** además de Pantalla completa, Dividida y Solo Nacho, en Clips Chapuceros y
    Clips Fuera hay **9:16**: todo el cuadro vertical sale de **cualquier parte del video completo** (no solo de la
    pantalla de Nacho), como si fuera un video de pantalla. Empieza centrado en Nacho; con el recuadro azul
    («Vista 9:16») sobre el video original lo mueves o lo acercas a la parte que quieras. Morado en la línea de tiempo.
  - **Música de fondo y volumen** (abajo del video, junto al tiempo): Clips Chapuceros, Clips Fuera y Tiktoks Yair
    llevan la música de fondo de siempre, a **volumen fijo** (ya no baja ni sube sola cuando hablan) y solo dura lo
    que dura el video. **🎵 Fondo** sube o baja solo la música; **🔊 Video** sube o baja el audio del video (la voz).
    100% = como viene; de 0 a 200%. Se escucha al reproducir aquí, se guarda solo y se usa en «Renderizar de nuevo»
    y en el video final.
  - **Subtítulos que trae el video de Nacho (difuminar):** al analizar (Clips Chapuceros y Clips Fuera), el lector de
    texto busca en los videos que pone Nacho letras abajo que cambian con lo que se dice (subtítulos quemados) y
    pone encima una **franja difuminada** para que no se vean dos subtítulos a la vez. Los textos fijos (logos,
    nombres en cintillo) no se tocan. En Edición se ve como un **recuadro morado** sobre el video original (muévelo o
    estíralo libre; se guarda al soltar) y como bloque morado en el carril «Difuminar subtítulos» (moverlo, estirarlo,
    Supr, Ctrl+C/V, Ctrl+B). Barra «Subtítulos que trae el video de Nacho»: **＋ Difuminar aquí**, **Quitar el de
    aquí** y **🔍 Buscar de nuevo** (para trabajos analizados antes de este cambio; conserva lo que pusiste a mano).
    Se ve en las vistas previas y en el video final.
  - Un clic sobre un recuadro (sin arrastrarlo) no crea ningún encuadre; solo reproduce o pausa.
  - **Teclado** (clic en un bloque de la línea de tiempo para seleccionarlo): Ctrl+C copiar · Ctrl+X cortar ·
    Ctrl+V pegar en el cursor · Ctrl+D duplicar · Supr borrar · Ctrl+B o S partir en el cursor · [ y ] mover el
    inicio o el final al cursor · Alt+←/→ mover un cuadro (con Shift, un segundo) · Ctrl+Z deshacer · Ctrl+Y rehacer ·
    Espacio reproducir · ←/→ un cuadro · Inicio/Fin · Tab siguiente bloque · Esc quitar la selección.
- **Subtítulos:** la lista a la derecha y la vista previa armada en vivo con tus subtítulos a la izquierda.
  **Si en Edición quitas o restauras un tramo,** los subtítulos se reacomodan solos a los tiempos nuevos: las palabras
  del tramo quitado ya no salen (si se quitó todo un subtítulo, desaparece) y, si lo restauras, vuelven. La pestaña
  se pone al día sola (si tenías cambios sin guardar, te avisa y se acomoda al guardar). Igual en el video final.
  **Altura de cada subtítulo:** cada renglón de la lista tiene su columna «Altura ↕»: ▲ lo sube y ▼ lo baja
  (10 px; con Shift, 50 px), o escribe los píxeles (negativo = más arriba, 0 = donde lo pone la plataforma). También
  se puede **arrastrar el subtítulo arriba o abajo directamente sobre el video**, y Alt+↑/↓ mueve el que se ve en ese
  momento. Solo se mueve ese subtítulo; los demás se quedan donde los pone la plataforma (en la franja azul
  incluida). Se guarda con **Guardar subtítulos** y se usa en el video final y en la vista previa.
- **Vista previa fluida:** al abrir un trabajo se prepara sola, en segundo plano, una copia ligera del video ya sin
  las pausas recortadas (`proxy.mp4` en la carpeta _trabajo). Mientras se prepara, las vistas previas usan el original
  (pueden trabarse en cada pausa); cuando está lista se cambian solas y junto al tiempo dice «✓ vista fluida».
  Si quitas o restauras un tramo, se vuelve a preparar sola.
- **Título en Tiktoks Motivacionales:** se quita cuando Nacho termina de decirlo (si lo dice al empezar); si no, en el
  primer corte después de 2.7 s. En la línea de tiempo (carril Imágenes) aparece el bloque blanco **TÍTULO**: estira
  su orilla derecha para cambiar cuándo se quita. Las vistas previas ya muestran el título.
- Las vistas previas ya muestran el **movimiento de las fotos** (acercar, alejar, paneos) igual que el video final;
  al cerrar «Movimiento de las fotos…» se ve el cambio. Solo las cortinillas aparecen únicamente al exportar.
- **Exportar:** cuando todo está revisado, «Exportar video final» arma el MP4 1080×1920.
- Tiempos: minutos:segundos:centésimas (`01:05:30` = 1 min 5.3 s), siempre del video ya editado.
- **Estilo de edición:** al procesar eliges el estilo:
  - *Clips Chapuceros*: barra roja de título, subtítulos palabra por palabra, pantalla dividida con imágenes, música.
    **Transición de cambio de cámara:** cuando Nacho cambia de cámara pone la cortinilla «El Chapucero» en su video;
    al pasarlo a vertical se veía cortada. Ahora al analizar se busca y en el video se tapa con la cortinilla limpia
    vertical (`assets\transicion_camara.mp4`), con el audio original (por si Nacho habla durante la transición). Las
    pausas recortadas no se la comen. Los trabajos analizados antes la buscan solos la próxima vez que se renderizan.
    Se ve también en las vistas previas de Edición y Subtítulos. En Edición, la barra «Transiciones de cambio de
    cámara» dice cuántas encontró y permite **＋ Transición aquí** (si no encontró alguna), **Quitar la de aquí**,
    **🔍 Buscar de nuevo** e **Ir a la siguiente**. Se apaga con `transicion_camara.activar: false` en la plantilla.
    Si Nacho se calla y habla la persona del video que puso, ese rato el video va a pantalla completa centrado en quien habla.
  - *Tiktoks Motivacionales*: Nacho a pantalla completa alternando encuadre cerca/lejos en los cortes, título inicial
    en recuadro negro (AkuKamu), subtítulos por frase (Staatliches), pausas acortadas dejando silencios más largos al
    final de las oraciones y en los remates (efecto dramático), pocas imágenes a pantalla completa con entrada girando,
    sin música. Plantilla: `plantillas\tiktok_motivacional.json`.
  - *Tiktoks Yair*: como Tiktoks Motivacionales (encuadre cerca/lejos en los cortes, pausas acortadas), pero la
    **entrada** es en pantalla dividida: Yair arriba, el título en **dos cuadros** (naranja con letra negra arriba y
    rojo con letra blanca abajo, letra Aku & Kamu inclinada, medidas de `Titulos_Yair.psd`) que entran de los lados
    con el movimiento medido de los ejemplos (el de la derecha llega con rebote, el de la izquierda frenando suave;
    se elige el lado con `entra_desde`). Durante la entrada Yair tiene **su propio encuadre, fijo y más alejado**
    (casi todo el alto del video original, medido de los ejemplos: `entrada.alto_ventana`, `cara_x`, `cara_y`; se ve
    igual en la vista previa de Edición y se puede corregir a mano en Encuadre), y abajo la **imagen de la entrada**. El título se escribe así: `TEXTO DE ARRIBA – TEXTO DE ABAJO`
    (lo que va antes del guion va en el cuadro de arriba; si un texto es largo, la letra se achica para caber). La
    entrada dura hasta que Yair termina de decir el título (se cambia estirando el bloque TÍTULO, como en
    motivacionales). La imagen de la entrada no se busca sola: en **Edición**, en el inicio del video, el panel
    Imagen muestra «Imagen de la entrada» con **📁 Subir desde la PC** o buscar. Mientras no tenga foto, las vistas
    previas muestran un recuadro gris de aviso y el video final va desenfocado en esa parte. Después: Yair a
    pantalla completa con el mismo encuadre que Tiktoks Motivacionales (cerca / lejos), pero con el ritmo del editor:
    recorta también pausas cortas y cambia de tamaño en casi cada corte (cada ~2–4 s); si pasa mucho sin un corte,
    cambia en un respiro o al inicio de una frase (`encuadre.ritmo_seg`, `max_sin_cambio_seg`).
    Subtítulos palabra por palabra (como Clips Chapuceros) y música de fondo.
    Plantilla: `plantillas\tiktok_yair.json`.
  - *Clips Fuera*: cuando Nacho graba de viaje con el celular (toma de él, o pantalla partida con él a la izquierda
    y un video, tweet o documento a la derecha sobre negro). Mismo diseño que Clips Chapuceros, sin recortar pausas,
    con la música de fondo y sin imágenes de internet. Los videos del celular van a pantalla completa, los tweets a pantalla
    completa, los documentos en pantalla dividida con seguimiento de lectura, y una cortinilla "El Chapucero" al entrar
    y salir de la pantalla dividida. Mientras Nacho habla, el video que puso va en pantalla dividida (él arriba);
    cuando se calla para verlo, va a pantalla completa centrado en quien habla o en lo que se mueve. La voz de Nacho
    se reconoce comparándola con las partes donde sale solo (requiere `scikit-learn`, incluido en requirements.txt).
    Plantilla: `plantillas\clips_fuera.json`.
  - *Tiktoks Gaby*: video de fondo en movimiento (`assets/fondo_gaby.mp4`, se repite si el clip dura más), la
    persona en una franja al centro con encuadre fijo (sin cambios de cámara; si hay varias caras sigue la del
    centro), título amarillo arriba en Raleway Black Italic todo el video (al inicio cada renglón entra de borroso a
    nítido) y subtítulos palabra por palabra con la palabra activa en un cuadro **rosa**. Pausas acortadas, música de
    fondo y sin imágenes. El encuadre se corrige en Edición › Encuadre como en los demás.
  - *Solo subtítulos (Chapucero)*: para un clip YA editado (vertical u horizontal). No recorta ni
    cambia nada: transcribe, corrige nombres y puntuación con el modelo local y le pone los subtítulos con el estilo
    elegido. El título no hace falta. Sale como `NOMBRE_subtitulado.mp4` en su carpeta `_trabajo`.
    **Si cambias el video** (otra versión con el MISMO nombre en VideosEdit, junto a su carpeta `_trabajo`): al abrir
    el trabajo o darle Analizar, la plataforma lo detecta. Si dura lo mismo, usa los mismos subtítulos sin preguntar
    (solo vuelve a buscar la franja azul y el título del inicio). Si la duración es distinta, pregunta: **Usar los
    mismos subtítulos** (los que queden después del final se quitan) o **Transcribir de nuevo**. Si el video no
    cambió y le das Analizar, también pregunta, para no perder las correcciones.
    El **título** se escribe en la misma pestaña Subtítulos (arriba de la lista) y se cambia ahí cuando haga falta;
    con él se nombra el video al exportar. Si no tiene, sale el aviso con el nombre que tendría el archivo. Con
    **Ponerlo en el video** marcado, la barra roja del título se ve encima del clip en vivo (vertical: en su lugar de
    siempre; horizontal: arriba al centro) y sale igual en el video exportado.

## Novedades 1.8.0

- **Título nuevo** (Clips Chapuceros, Clips fuera y Solo subtítulos): barra roja degradada y letra Aku&Kamu. En un renglón
  el texto llena lo ancho de la barra; con **Enter** (en Edición/Subtítulos) o **Shift+Enter** (al analizar) pasa a dos
  renglones y se acomoda dentro de la barra. En Subtítulos, **Ctrl+Enter** guarda el título.
- **Dividida Ganso** (Pantalla): dos cámaras, franja azul más alta y más arriba; abajo la pantalla.
- **Línea de tiempo**: todos los carriles se mueven cada 0.10 s (Alt = cuadro por cuadro); las orillas se estiran.
- **Imágenes 2 (arriba)**: carril propio para poner una imagen arriba y otra abajo de la franja al mismo tiempo.
- **Dos imágenes al mismo tiempo**: con una imagen ya puesta, en el panel Imagen → «＋ Otra imagen aquí»; la nueva
  va arriba (Imágenes 2) desde el cursor. También: en un lugar libre elige «Arriba (en lugar de Nacho)» y luego
  arrástrala en «Imágenes 2» encima de la otra.
- **Captura del video**: toma el cuadro completo.
- **Secciones de audio**: Shift + arrastrar en «Audio» separa una sección; abajo se silencia o se sube/baja su volumen
  (0–300 %). Solo afecta la voz del video, la música de fondo sigue.
- **Subtítulos**: casilla ☑ en cada fila; al subir/bajar uno de los marcados, todos los marcados se mueven igual.
- **Sticker «Rectángulo»**: recuadro rojo recto y delgado (animado, se recolorea y se estira como los demás).

## Video largo (pestaña «Video largo»)

Para sacar varios clips de un video de 1–2 horas:

1. Elige el video (debe estar en VideosEdit; MP4 o WebM para verlo en el navegador). Se ve en grande arriba.
   Debajo de la línea de tiempo está la **onda de sonido** (carril «Audio»); se calcula una vez por video y se guarda.
2. Marca fragmentos mientras lo ves: **A** = entrada, **S** = salida (se crea el fragmento y escribes su título).
   **Espacio** reproduce o pausa, **←/→** 5 s (**Shift** 30 s), **Supr** borra los seleccionados, **Esc** cancela.
3. **Línea de tiempo:** regla con minutos y segundos, el cursor rojo con su tiempo, la marca **A** con el tramo que
   vas a cortar, y una línea guía con el tiempo bajo el ratón. **Doble clic** lleva el cursor a ese punto.
   **Ctrl + rueda** (o − / + y la barra) acerca o aleja para cortar justo donde quieres; **Ver todo** regresa.
   Arrastra los bloques o sus orillas (el video se mueve al punto del corte); con el **imán** se pegan a las pausas
   de la voz (rayitas grises abajo) para no cortar a media palabra.
4. **Grupos:** selecciona varios fragmentos con **Ctrl + clic** (o Shift + clic) y presiona **Ctrl + G**: se exportan
   juntos como **un solo video**, en orden, con el título del primero. **Ctrl + D** los desagrupa. Cada grupo tiene
   su color y su etiqueta (G1, G2...).
5. Opcional: **«Sugerir fragmentos con IA»**: transcribe el video completo (una vez) y Ollama propone clips con
   título y tema (en azul ✨). Sin Ollama, propone cortes por frases cada ~1 minuto. Usa lo aprobado en «Lo aprendido».
6. Deja palomeados los que quieras y presiona **«✂ Exportar los marcados»**. Cada clip (o grupo) se corta, se
   guarda en VideosEdit con su **título como nombre** (`Título.mp4`) y se analiza **sin pre-acomodo**: solo limpia
   las pausas y hace los subtítulos (reusando la transcripción); Nacho queda a pantalla completa centrado y la
   pantalla dividida, las imágenes y los encuadres se ponen a mano en Edición. Al terminar aparece «listo ✓» y el
   enlace «Abrir en el editor»; también salen en el desplegable de trabajos de la pestaña Editor.

Todo queda guardado en `VIDEO_fragmentos\fragmentos.json`, puedes cerrar y seguir después.

## Lo aprendido (la plataforma aprende de tus correcciones)

Cada vez que **exportas**, la plataforma compara lo que armó sola (`plan_auto.json`) con lo que dejaste:

- **Subtítulos:** palabras que Whisper escribe mal y corriges (ej. «Sheinbon» → «Sheinbaum»).
- **Imágenes:** sitios de donde borras imágenes (se evitan) o de donde sí las dejas (se prefieren), tus búsquedas
  (se le dan al modelo como ejemplo), y la duración y el estilo que les das.
- **Acomodos:** si siempre subes/acercas el encuadre de Nacho, y qué pantalla eliges según lo que proyecta.
- **Video largo:** qué temas e información eliges para tus clips (los que exportas) y cuáles descartas (las
  sugerencias que borras o desmarcas), de qué largo los haces y qué partes les quitas con «Quitar tramo». Aprobadas,
  la IA las usa al sugerir fragmentos (busca temas como los que eliges, evita los que descartas y deja fuera lo que
  sueles quitar).

En la pestaña **«Lo aprendido»** ves las reglas propuestas: **Aprobar** o **Descartar**. Solo las aprobadas se
usan, y solo en los análisis nuevos (no cambian videos ya hechos). «Aprender de todos los trabajos» revisa todas
las carpetas `_trabajo` que ya tengas. Todo se guarda en la carpeta `aprendizaje\` del programa.

## Pantalla de Nacho libre e imagen arriba (Edición)

- **Pantalla de Nacho, forma libre:** el recuadro azul se mueve por toda la zona que va desde donde termina la cámara
  de Nacho hasta la orilla derecha, de arriba a abajo (la línea blanca delgada marca esa zona). Las esquinas estiran
  libre (alto o ancho; con **Shift** conserva la forma). Si el recuadro no tiene la forma de abajo, se ve **completo**
  y lo que sobra se rellena con la misma imagen agrandada y difuminada. Igual en la vista previa y en el video final.
- **Imagen arriba (en lugar de Nacho):** en Edición › Imagen, opción «Arriba (en lugar de Nacho)» al agregar o en una
  imagen que ya está. Va en el lugar de Nacho; abajo sigue la pantalla o la imagen que toque (se pueden encimar una
  arriba y otra abajo). En la línea de tiempo va en la mitad de arriba del carril «Imágenes», en verde azulado.

## Exportación rápida (por partes y con la tarjeta gráfica)

- La exportación final se reparte en **3 partes que se arman a la vez** (4 en equipos de 20 hilos o más), cada una en
  su núcleo; al final se juntan **sin volver a codificar** y se les pone el audio de todo el video. Sale idéntica a la
  exportación de antes (mismos cuadros, mismo audio).
- Los cuadros del video original los **decodifica la tarjeta gráfica** (NVDEC) en un proceso aparte; si no se puede,
  ffmpeg lo hace con el procesador, y si tampoco, se usa la lectura de siempre.
- Videos de menos de 20 s se exportan de la forma normal. Si alguna parte falla, se detienen las demás y se exporta de
  la forma normal (sale bien, solo tarda lo de antes).
- Para forzar: variable `EDITOR_TRAMOS` (1 = como antes; 2 a 6 = partes a la vez). `EDITOR_SIN_NVDEC=1` = sin la
  tarjeta gráfica para leer.

## Si la plataforma se alenta después de horas

- **Registro › Estado del equipo** (se actualiza solo): memoria de la plataforma y del equipo, procesador, espacio en
  disco, temperatura y uso de la tarjeta gráfica (avisa si bajó su velocidad por calor) y los procesos que siguen
  trabajando. Cuando algo está mal aparece un aviso en naranja.
- Al abrir otro trabajo se detienen las vistas previas y copias ligeras que seguían trabajando para el anterior.
- Las secciones ocultas pausan su video; el Registro solo se manda al navegador cuando hay líneas nuevas.
- Remedio rápido: **Cerrar** la plataforma, cerrar Chrome y volver a abrir.

## Uso desde la terminal
Todo en un paso:
    cd C:\editor_vertical
    python editor.py todo "C:\videos\clip.mp4" --titulo "¡PRIAN desesperado! Obradoristas al poder" --gpu
    python editor.py todo "C:\videos\moti.mp4" --titulo "La honestidad vale más que el oro" --plantilla plantillas\tiktok_motivacional.json --gpu

El resultado queda en `C:\videos\clip_trabajo\clip_vertical.mp4`.

En dos pasos, para revisar o cambiar las imágenes antes del render:
    python editor.py analizar "C:\videos\clip.mp4" --titulo "..."
    (edita clip_trabajo\plan.json, sección "momentos": inicio/fin, agregar o quitar momentos, ruta de otra imagen;
     o reemplaza los archivos de clip_trabajo\imagenes\ con el mismo nombre)
    python editor.py render "C:\videos\clip_trabajo" --gpu

Opciones:
- `--imagenes CARPETA`  usa tus imágenes (en orden alfabético, una por momento) en lugar de buscarlas
- `--sin-web`           no busca imágenes (no habrá momentos con imagen)
- `--sin-ia`            no usa Ollama; reparte los momentos cada 15 s
- `--sin-musica`        sin música de fondo
- `--modelo-ollama X`   otro modelo de Ollama (por defecto llama3.1:8b)

## Cómo arma el video
- **Tomas fijas:** el encuadre no persigue a Nacho ni a la persona del video que proyecta. El recuadro se queda
  quieto y, solo si la persona se sale del margen, salta de golpe a otra posición fija (como un corte de cámara),
  de preferencia justo en una pausa recortada para que no se note. Si en la toma original Nacho ya sale cortado,
  así se queda. Se calibra en la sección `toma_fija` de cada plantilla (`activar: false` regresa al seguimiento
  anterior). En la pestaña Encuadre el recuadro automático ya se ve con estas tomas fijas.
- La persona va a pantalla completa (del recuadro pequeño si la toma es dividida), siempre con la cabeza bajo el título.
- En los "momentos" cambia a pantalla dividida con una imagen del tema y zoom lento (de 4 a 7 s, cada ~15 s como máximo).
- **Sin saltos a Nacho completo:** dentro de una pantalla dividida ya no se brinca a Nacho mientras la página se
  desplaza; los huecos de menos de 1 s (ya con los cortes) entre dos tramos con pantalla o imagen se tapan, y un tramo
  que empieza o acaba a unas centésimas de un corte se pega al corte (sin cuadros sueltos).
- La proyección solo se muestra si tiene movimiento (un video corriendo); si está congelada se oculta.
- Subtítulos palabra por palabra con la palabra activa en rojo.
- Música en loop que baja sola cuando la persona habla; la voz se nivela si se acerca o aleja del micrófono.

## Revisar las coordenadas con un video nuevo
    python editor.py calibrar "C:\videos\clip.mp4" --t 26
Genera un JPG con los recuadros dibujados. Si no coinciden, ajusta `fuente_16x9` en la plantilla.

## Plantillas
Todo el diseño está en `plantillas\chapucero_vertical.json`: áreas, fuentes, colores, tiempos de los momentos y volumen
de la música. Para una plantilla nueva, cópiala y usa `--plantilla plantillas\otra.json`.

## n8n
Nodo "Execute Command":
    python C:\editor_vertical\editor.py todo "{{ $json.video }}" --titulo "{{ $json.titulo }}" --gpu
La última línea que imprime es JSON: {"ok": true, "salida": "...mp4"}. Léela con un nodo Code (JSON.parse).
