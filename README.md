# Visor de Estado Hídrico de los Sistemas AyA

Visor de categoría hídrica y coberturas de los sistemas de agua potable AyA de
la GAM y las regiones periféricas de Costa Rica. La aplicación se ejecuta con
Streamlit e incorpora una interfaz cartográfica Leaflet autocontenida.

## Funciones disponibles

- identificación visual de sistemas deficitarios y superavitarios;
- clasificación ICH I, II, III y IV con prioridad gráfica sobre las demás capas;
- explicación ampliada de cada categoría ICH mediante ventanas activadas por clic;
- consulta por nombre o código del sistema;
- filtros combinables por provincia, cantón, distrito, región operativa,
  categoría hídrica y sistema;
- filtrado geoespacial de sistemas AyA, puntos ASADA y coberturas Thiessen;
- popup público limitado a categoría hídrica, nombre, dotación estimada,
  consumo estimado por conexión y factor de ocupación;
- capa nacional de 5.400 fuentes de aprovechamiento ASADA con nombre y código
  del operador, más las coordenadas del punto;
- capas de municipalidades, ESPH, ASADAS, áreas protegidas y distritos;
- criterios especiales con el tipo de restricción o facilidad y el código de
  abastecimiento asociado;
- coberturas someras/estimadas de ASADAS mediante polígonos Thiessen;
- mapas base de OpenStreetMap, CARTO, Esri y OpenTopoMap;
- dibujo temporal de puntos, líneas, polígonos, rectángulos y texto/notas;
- pin con coordenadas WGS84 y copia al portapapeles;
- búsqueda por latitud y longitud WGS84 con zoom y pin resaltado;
- medición de distancias;
- importación temporal de KML y KMZ;
- exportación del mapa visible a JPG;
- actualización automática de la sesión cada 15 minutos mediante
  `streamlit_autorefresh`.

Los dibujos, notas y archivos importados son temporales y se eliminan al
recargar la aplicación.

## Ejecución local

Se recomienda Python 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

El visor quedará disponible normalmente en `http://localhost:8501`.

## Actualizar los datos

Los archivos que consume el visor están en `map/data/`. Es posible sustituirlos
directamente siempre que conserven los mismos nombres, geometrías WGS84 y
atributos públicos permitidos.

| Archivo | Atributos públicos permitidos |
|---|---|
| `sistemas.geojson.gz` | `codigo`, `region`, `nombre`, `ich`, `dotacion_lpd`, `consumo_conexion_m3_mes`, `factor_ocupacion`, `territorios` |
| `municipalidades.geojson` | `operador`, `sistema` |
| `esph.geojson` | `operador`, `sistema` |
| `asadas.geojson.gz` | `codigo`, `nombre`, `territorio` |
| `cobertura-thiessen-asadas.geojson.gz` | `codigo`, `referencia`, `provincia`, `canton`, `distrito`, `alcance`, `metodo`, `territorios` |
| `criterios-especiales.geojson` | `codigo_sistema`, `nombre_sistema`, `codigo_abastecimiento`, `zona`, `zona_operativa`, `tipo`, `detalle` |
| `areas-protegidas.geojson` | `codigo`, `nombre`, `categoria` |
| `distritos.geojson.gz` | `clave`, `codigo`, `provincia`, `canton`, `distrito` |

Después de sustituir archivos, ejecute:

```bash
python scripts/check_public_data.py
```

### Actualizar sistemas AyA y datos ACH

La capa principal se genera relacionando el campo `codsistema` del SHP con la
columna `CODIGO SISTEMA` del Excel. Los códigos se normalizan sin guiones, por
ejemplo `MEA01` y `PCA14`. La geometría se conserva con precisión submétrica y
se comprime para reducir el tiempo de carga del visor.

```bash
pip install -r requirements-update.txt
python scripts/import_aya_systems.py \
  --shapefile "/ruta/Sistemas_AP_AYA.shp" \
  --workbook "/ruta/Datos ACH Streamlit Gam Perifericos.xlsx"
python scripts/check_public_data.py
```

El proceso exige correspondencia completa y única entre ambos archivos. No
publica producción, ANC, demanda, balance, servicios atendidos ni los demás
campos de cálculo del Excel.

### Actualizar ASADAS y distritos nacionales

La capa de puntos ASADA y la división distrital se importan directamente desde
SHP WGS84. El proceso conserva los vértices distritales, publica solo los
atributos permitidos y calcula mediante intersección espacial la pertenencia de
los sistemas y las coberturas Thiessen a cada territorio.

```bash
pip install -r requirements-update.txt
python scripts/import_national_territorial_layers.py \
  --asadas-shapefile "/ruta/ASADAS_AYA.shp" \
  --districts-shapefile "/ruta/Distritos_CR.shp"
python scripts/check_public_data.py
```

Los selectores del visor funcionan en cascada: Cantón se habilita al escoger
Provincia y Distrito se habilita al escoger Cantón. La opción “Todo el país”
restablece la cobertura nacional.

### Actualización directa desde SHP

Para actualizar Cobertura Thiessen, Criterios especiales o Acueductos
Municipales, use el ZIP original del Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`
y `.cpg`). El importador conserva todos los polígonos, anillos y vértices; no
simplifica ni reemplaza la geometría por otra capa. También reproyecta CRTM05 y
Web Mercator a WGS84 cuando corresponde y elimina los atributos que no deben
publicarse.

```bash
python scripts/import_shapefile_layers.py \
  --thiessen "/ruta/Cobertura_Thiessen_ASADAS_UTAPS.zip" \
  --criteria "/ruta/Criterios Especiales CCH GAM.zip" \
  --municipal "/ruta/Acueductos_Municipales_.zip"
python scripts/check_public_data.py
```

Es posible actualizar solo la capa que cambió. Por ejemplo, para Criterios
especiales:

```bash
python scripts/import_shapefile_layers.py \
  --criteria "/ruta/Criterios Especiales CCH GAM.zip"
python scripts/check_public_data.py
```

La simbología se determina automáticamente con `cond_espec`: Artículo 43 se
muestra como facilidad azul hachurada y las restricciones en rojo/terracota
hachurado. El popup se abre únicamente al hacer clic en la geometría.

### Actualizar capacidad hídrica GAM y criterios especiales juntos

Cuando el SHP de capacidad trae polígonos por zona de abastecimiento, use el
importador conjunto para conservar sus geometrías y recalcular la relación con
los distritos del visor. El ICH se toma del SHP nuevo; dotación, consumo por
conexión y factor de ocupación se toman de `scripts/metricas_gam_2026.csv`,
ya que esos campos no están en el SHP. MEA23 se unificó con MEA16 y se elimina
de la capa pública; MEA16 utiliza sus propios indicadores actualizados. Como
el SHP reciente de MEA16 cubre solo parte del antiguo polígono de MEA23,
`scripts/area_mea23_barrio_espana.geojson` conserva la geometría pública
anterior de Barrio España y el importador suma únicamente su porción no cubierta
por el SHP reciente a MEA16. Los otros sistemas ausentes de la fuente nueva se
mantienen sin cambios. El
importador exige correspondencia completa entre los 30 códigos del SHP y la
tabla de indicadores. Los códigos de abastecimiento y zonas operativas de los
criterios se relacionan por sistema, nombre de zona e intersección espacial.

```bash
pip install -r requirements-update.txt
python scripts/update_hydric_layers.py \
  --capacity "/ruta/Capacidad Hídrica.zip" \
  --criteria "/ruta/Criterios Especiales.zip"
python scripts/check_public_data.py
```

La fuente pública de puntos ASADA identifica al operador, pero no proporciona
un nombre o identificador propio para cada fuente. El popup indica el código
del operador y las coordenadas WGS84 para distinguir los puntos.

Para regenerar las capas complementarias desde las fuentes originales:

1. Cree una carpeta local `source_private/` (está excluida de Git).
2. Copie allí los archivos con los nombres indicados en
   `scripts/update_public_data.py`.
3. Instale las dependencias de actualización y ejecute el proceso.

```bash
pip install -r requirements-update.txt
python scripts/update_public_data.py
python scripts/check_public_data.py
```

Los procesos eliminan correos, teléfonos, balances, identificadores internos,
fechas de edición y cualquier otro atributo que no esté en la tabla anterior.
Nunca publique la carpeta `source_private/`.

La cobertura Thiessen es una aproximación espacial de consulta. No representa
un límite oficial de prestación ni sustituye la verificación técnica de campo.

## Publicación en Streamlit Community Cloud

GitHub Pages no ejecuta aplicaciones Python. Para una publicación Streamlit:

1. publique este proyecto en un repositorio GitHub llamado `ACH_GAM_VISOR`;
2. en Streamlit Community Cloud seleccione ese repositorio y la rama principal;
3. indique `app.py` como archivo de entrada;
4. despliegue la aplicación.

Las dependencias de producción están fijadas en `requirements.txt`. Cada cambio
en GitHub provoca un nuevo despliegue; la recarga automática del navegador está
configurada en `app.py`.

## Privacidad y alcance

El repositorio solo contiene datos derivados para publicación. Los popups
exponen atributos mínimos. El mapa es informativo y no sustituye un criterio
técnico formal ni una disponibilidad de servicio.

Las licencias de Leaflet y sus complementos se conservan en
`map/vendor/THIRD_PARTY_NOTICES.md` y `map/vendor/licenses/`.
