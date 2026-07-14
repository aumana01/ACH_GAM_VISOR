# ACH GAM VISOR

Visor público de condición hídrica y coberturas de abastecimiento de agua
potable en la Gran Área Metropolitana de Costa Rica. La aplicación se ejecuta
con Streamlit e incorpora una interfaz cartográfica Leaflet autocontenida.

## Funciones disponibles

- identificación visual de sistemas deficitarios y superavitarios;
- clasificación ICH I, II, III y IV con prioridad gráfica sobre las demás capas;
- consulta por nombre o código del sistema;
- capas de municipalidades, ESPH, ASADAS, ONA, áreas protegidas y distritos;
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
| `sistemas.geojson` | `codigo`, `nombre`, `condicion`, `ich` |
| `municipalidades.geojson` | `operador`, `sistema` |
| `esph.geojson` | `operador`, `sistema` |
| `asadas.geojson` | `codigo`, `operador` |
| `cobertura-thiessen-asadas.geojson` | `codigo`, `referencia`, `provincia`, `canton`, `distrito`, `alcance`, `metodo` |
| `criterios-especiales.geojson` | `codigo_sistema`, `nombre_sistema`, `codigo_abastecimiento`, `zona`, `zona_operativa`, `tipo`, `detalle` |
| `onas.geojson` | `operador`, `sistema` |
| `areas-protegidas.geojson` | `codigo`, `nombre`, `categoria` |
| `distritos.geojson` | `provincia`, `canton`, `distrito` |

Después de sustituir archivos, ejecute:

```bash
python scripts/check_public_data.py
```

### Actualización directa desde SHP

Para actualizar únicamente Cobertura Thiessen o Criterios especiales, use el
ZIP original del Shapefile (`.shp`, `.shx`, `.dbf`, `.prj` y `.cpg`). El
importador conserva todos los polígonos, anillos y vértices; no simplifica ni
reemplaza la geometría por otra capa. También reproyecta CRTM05 a WGS84 cuando
corresponde y elimina los atributos que no deben publicarse.

```bash
python scripts/import_shapefile_layers.py \
  --thiessen "/ruta/Cobertura_Thiessen_ASADAS_UTAPS.zip" \
  --criteria "/ruta/Criterios Especiales CCH GAM.zip"
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

Para regenerar todos los archivos desde las fuentes originales:

1. Cree una carpeta local `source_private/` (está excluida de Git).
2. Copie allí los diez archivos con los nombres indicados en
   `scripts/update_public_data.py`.
3. Instale las dependencias de actualización y ejecute el proceso.

```bash
pip install -r requirements-update.txt
python scripts/update_public_data.py
python scripts/check_public_data.py
```

El proceso elimina correos, teléfonos, balances, identificadores internos,
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
