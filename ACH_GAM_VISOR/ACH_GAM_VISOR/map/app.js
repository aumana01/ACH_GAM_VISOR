(() => {
  "use strict";

  const COLORS = {
    I: "#ff0000",
    II: "#ff8c00",
    III: "#ffd700",
    IV: "#00a651",
    unknown: "#8b98a5",
  };

  const DATA_FILES = {
    metadata: "data/metadata.json",
    systems: "data/sistemas.geojson",
    municipal: "data/municipalidades.geojson",
    esph: "data/esph.geojson",
    asadas: "data/asadas.geojson",
    ona: "data/onas.geojson",
    protected: "data/areas-protegidas.geojson",
    districts: "data/distritos.geojson",
  };

  const DEFAULT_BOUNDS = L.latLngBounds([9.646, -84.505], [10.025, -83.925]);
  const layerStore = {};
  const importGroup = L.featureGroup();
  const measurementGroup = L.featureGroup();
  let systemsData = null;
  let systemsLayer = null;
  let selectedCondition = "Todos";
  let messageTimer = null;
  let pinMode = false;
  let coordinatePin = null;
  let measuring = false;
  let measurementPoints = [];

  const elements = {
    loading: document.getElementById("loadingOverlay"),
    message: document.getElementById("mapMessage"),
    searchForm: document.getElementById("systemSearchForm"),
    searchInput: document.getElementById("systemSearch"),
    searchOptions: document.getElementById("systemOptions"),
    pinTool: document.getElementById("pinTool"),
    measureTool: document.getElementById("measureTool"),
    importTool: document.getElementById("importTool"),
    kmlInput: document.getElementById("kmlInput"),
    captureTool: document.getElementById("captureTool"),
    homeTool: document.getElementById("homeTool"),
    measurementPanel: document.getElementById("measurementPanel"),
    measurementValue: document.getElementById("measurementValue"),
    clearMeasurement: document.getElementById("clearMeasurement"),
    sidebar: document.getElementById("sidebar"),
    openSidebar: document.getElementById("openSidebar"),
    closeSidebar: document.getElementById("closeSidebar"),
  };

  const map = L.map("map", {
    zoomControl: false,
    minZoom: 7,
    maxZoom: 20,
    preferCanvas: false,
    doubleClickZoom: true,
  });

  map.createPane("restrictions").style.zIndex = 320;
  map.createPane("reference").style.zIndex = 330;
  map.createPane("operators").style.zIndex = 360;
  map.createPane("systems").style.zIndex = 430;
  map.createPane("operatorPoints").style.zIndex = 470;
  map.createPane("drawings").style.zIndex = 650;

  const baseMaps = {
    "Calles · OpenStreetMap": L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 20,
        crossOrigin: true,
        attribution: "© OpenStreetMap contributors",
      },
    ),
    "Claro · Carto": L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      {
        maxZoom: 20,
        crossOrigin: true,
        subdomains: "abcd",
        attribution: "© OpenStreetMap contributors © CARTO",
      },
    ),
    "Satélite · Esri": L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 20,
        crossOrigin: true,
        attribution: "Tiles © Esri",
      },
    ),
    "Relieve · OpenTopoMap": L.tileLayer(
      "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 17,
        crossOrigin: true,
        attribution: "© OpenStreetMap contributors, SRTM | © OpenTopoMap",
      },
    ),
  };

  baseMaps["Claro · Carto"].addTo(map);
  L.control.layers(baseMaps, null, { position: "topright", collapsed: true }).addTo(map);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  map.fitBounds(DEFAULT_BOUNDS, { padding: [18, 18] });
  importGroup.addTo(map);
  measurementGroup.addTo(map);

  const captureLegend = L.control({ position: "bottomleft" });
  captureLegend.onAdd = () => {
    const node = L.DomUtil.create("div", "map-capture-legend");
    node.innerHTML = `
      <strong>Capacidad hídrica GAM</strong>
      <span><i style="background:${COLORS.I}"></i>I · Altamente deficitario</span>
      <span><i style="background:${COLORS.II}"></i>II · Crecimiento máximo</span>
      <span><i style="background:${COLORS.III}"></i>III · Transición</span>
      <span><i style="background:${COLORS.IV}"></i>IV · Margen disponible</span>
    `;
    return node;
  };
  captureLegend.addTo(map);

  if (map.pm) {
    map.pm.setLang("es");
    map.pm.addControls({
      position: "topright",
      drawMarker: true,
      drawCircleMarker: false,
      drawPolyline: true,
      drawRectangle: true,
      drawPolygon: true,
      drawCircle: false,
      drawText: true,
      editMode: true,
      dragMode: false,
      cutPolygon: false,
      removalMode: true,
      rotateMode: false,
    });
    map.pm.setPathOptions({
      color: "#003f78",
      fillColor: "#20a8e0",
      fillOpacity: 0.22,
      weight: 3,
      pane: "drawings",
    });
    map.on("pm:drawstart", () => {
      stopCoordinateMode();
      finishMeasurement();
    });
  }

  const screenshoter = L.simpleMapScreenshoter({
    hidden: true,
    preventDownload: true,
    cropImageByInnerWH: false,
    hideElementsWithSelectors: [
      ".leaflet-control-zoom",
      ".leaflet-control-layers",
      ".leaflet-pm-toolbar",
      ".leaflet-control-attribution",
    ],
    mimeType: "image/jpeg",
    caption: "ACH GAM VISOR · Capacidad hídrica GAM",
    captionColor: "#002b5c",
    captionBgColor: "#ffffff",
    captionFontSize: 16,
    captionOffset: 10,
  }).addTo(map);

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function normalized(value) {
    return String(value ?? "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-zA-Z0-9]/g, "")
      .toUpperCase();
  }

  function systemColor(ich) {
    return COLORS[ich] || COLORS.unknown;
  }

  function systemPopup(properties) {
    const statusClass = properties.condicion === "Déficit" ? "deficit" : "surplus";
    return `
      <article class="popup-card">
        <header class="popup-head">
          <small>${escapeHtml(properties.codigo)}</small>
          <strong>${escapeHtml(properties.nombre)}</strong>
        </header>
        <div class="popup-body">
          <div class="popup-row">
            <span>Condición</span>
            <span class="status-pill ${statusClass}">${escapeHtml(properties.condicion)}</span>
          </div>
          <div class="popup-row">
            <span>Clasificación ICH</span>
            <span>${escapeHtml(properties.ich)}</span>
          </div>
        </div>
      </article>
    `;
  }

  function simplePopup(title, subtitle, rows = []) {
    return `
      <article class="popup-card">
        <header class="popup-head">
          <small>${escapeHtml(subtitle)}</small>
          <strong>${escapeHtml(title)}</strong>
        </header>
        <div class="popup-body">
          ${rows.map(([label, value]) => `
            <div class="popup-row">
              <span>${escapeHtml(label)}</span>
              <span>${escapeHtml(value || "—")}</span>
            </div>
          `).join("")}
        </div>
      </article>
    `;
  }

  function buildSystemsLayer() {
    if (systemsLayer) map.removeLayer(systemsLayer);
    const features = selectedCondition === "Todos"
      ? systemsData.features
      : systemsData.features.filter(
        (item) => item.properties.condicion === selectedCondition,
      );

    systemsLayer = L.geoJSON(
      { type: "FeatureCollection", features },
      {
        pane: "systems",
        style: (item) => ({
          pane: "systems",
          color: "#233b50",
          weight: 1.45,
          opacity: 0.92,
          fillColor: systemColor(item.properties.ich),
          fillOpacity: 0.7,
        }),
        onEachFeature: (item, layer) => {
          layer.bindPopup(systemPopup(item.properties), {
            closeButton: true,
            maxWidth: 300,
          });
          layer.bindTooltip(
            `${escapeHtml(item.properties.codigo)} · ${escapeHtml(item.properties.nombre)}`,
            { sticky: true, direction: "top", opacity: 0.92 },
          );
          layer.on({
            mouseover: () => layer.setStyle({ weight: 3.4, fillOpacity: 0.84 }),
            mouseout: () => layer.setStyle({ weight: 1.45, fillOpacity: 0.7 }),
          });
        },
      },
    ).addTo(map);
    systemsLayer.bringToFront();
  }

  function polygonLayer(data, style, popupBuilder, pane) {
    return L.geoJSON(data, {
      pane,
      style: { ...style, pane },
      onEachFeature: (item, layer) => {
        layer.bindPopup(popupBuilder(item.properties), { maxWidth: 300 });
        layer.on({
          mouseover: () => layer.setStyle({ weight: Math.max((style.weight || 1) + 1.5, 2.5) }),
          mouseout: () => layer.setStyle({ ...style, pane }),
        });
      },
    });
  }

  function buildOptionalLayers(data) {
    layerStore.municipal = polygonLayer(
      data.municipal,
      { color: "#286fbe", weight: 1.45, fillColor: "#5997d4", fillOpacity: 0.15 },
      (p) => simplePopup(p.sistema, "Cobertura municipal", [["Operador", p.operador]]),
      "operators",
    );

    layerStore.esph = polygonLayer(
      data.esph,
      { color: "#7639a9", weight: 1.8, fillColor: "#9b68c2", fillOpacity: 0.18 },
      (p) => simplePopup(p.sistema, "Otro operador", [["Operador", p.operador]]),
      "operators",
    );

    const asadaIcon = L.divIcon({
      className: "asada-marker",
      html: "",
      iconSize: [17, 17],
      iconAnchor: [8, 8],
    });
    layerStore.asadas = L.geoJSON(data.asadas, {
      pane: "operatorPoints",
      pointToLayer: (_item, latlng) => L.marker(latlng, {
        icon: asadaIcon,
        pane: "operatorPoints",
      }),
      onEachFeature: (item, layer) => {
        layer.bindPopup(simplePopup(
          item.properties.operador,
          "ASADA",
          item.properties.codigo ? [["Código", item.properties.codigo]] : [],
        ));
      },
    });

    layerStore.ona = polygonLayer(
      data.ona,
      {
        color: "#c43c78",
        weight: 1.5,
        dashArray: "5 4",
        fillColor: "#e888ae",
        fillOpacity: 0.12,
      },
      (p) => simplePopup(p.sistema, "Zona ONA", [["Operador", p.operador]]),
      "restrictions",
    );

    layerStore.protected = polygonLayer(
      data.protected,
      {
        color: "#468d54",
        weight: 1.4,
        dashArray: "6 4",
        fillColor: "#79ae78",
        fillOpacity: 0.13,
      },
      (p) => simplePopup(p.nombre, "Área protegida", [
        ["Código", p.codigo],
        ["Categoría", p.categoria],
      ]),
      "restrictions",
    );

    layerStore.districts = polygonLayer(
      data.districts,
      {
        color: "#66798a",
        weight: 1,
        dashArray: "4 4",
        fillColor: "#ffffff",
        fillOpacity: 0,
      },
      (p) => simplePopup(p.distrito, "Distrito", [
        ["Cantón", p.canton],
        ["Provincia", p.provincia],
      ]),
      "reference",
    );
  }

  function uniqueSystems() {
    const records = new Map();
    for (const item of systemsData.features) {
      const p = item.properties;
      if (!records.has(p.codigo)) records.set(p.codigo, p);
    }
    return [...records.values()].sort((a, b) => a.codigo.localeCompare(b.codigo, "es"));
  }

  function populateSearch() {
    elements.searchOptions.innerHTML = uniqueSystems()
      .map((item) => `<option value="${escapeHtml(item.codigo)} — ${escapeHtml(item.nombre)}"></option>`)
      .join("");
  }

  function applyCondition(condition) {
    selectedCondition = condition;
    document.querySelectorAll(".filter-tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.condition === condition);
    });
    buildSystemsLayer();
    showMessage(
      condition === "Todos" ? "Se muestran todos los sistemas." : `Filtro aplicado: ${condition}.`,
    );
  }

  function locateSystem(query) {
    const token = normalized(query.split("—")[0]);
    if (!token) {
      showMessage("Escriba un código o nombre de sistema.", true);
      return;
    }
    const records = uniqueSystems();
    const match = records.find((item) => normalized(item.codigo) === token)
      || records.find((item) => normalized(item.nombre) === normalized(query))
      || records.find((item) =>
        normalized(`${item.codigo}${item.nombre}`).includes(normalized(query)),
      );
    if (!match) {
      showMessage("No se encontró un sistema con ese código o nombre.", true);
      return;
    }

    if (selectedCondition !== "Todos" && selectedCondition !== match.condicion) {
      applyCondition("Todos");
    }

    const matches = systemsData.features.filter(
      (item) => item.properties.codigo === match.codigo,
    );
    const temporary = L.geoJSON({ type: "FeatureCollection", features: matches });
    map.fitBounds(temporary.getBounds(), { padding: [55, 55], maxZoom: 15 });
    const layer = Object.values(systemsLayer._layers).find(
      (candidate) => candidate.feature?.properties?.codigo === match.codigo,
    );
    if (layer) window.setTimeout(() => layer.openPopup(), 320);
    elements.searchInput.value = `${match.codigo} — ${match.nombre}`;
    closeSidebarOnMobile();
  }

  function showMessage(text, isError = false, timeout = 3600) {
    window.clearTimeout(messageTimer);
    elements.message.textContent = text;
    elements.message.classList.toggle("error", isError);
    elements.message.classList.add("visible");
    messageTimer = window.setTimeout(
      () => elements.message.classList.remove("visible"),
      timeout,
    );
  }

  function formatDistance(meters) {
    if (meters < 1000) return `${meters.toFixed(meters < 100 ? 1 : 0)} m`;
    return `${(meters / 1000).toFixed(meters < 10000 ? 2 : 1)} km`;
  }

  function totalMeasurement() {
    let total = 0;
    for (let index = 1; index < measurementPoints.length; index += 1) {
      total += map.distance(measurementPoints[index - 1], measurementPoints[index]);
    }
    return total;
  }

  function redrawMeasurement() {
    measurementGroup.clearLayers();
    if (!measurementPoints.length) {
      elements.measurementValue.textContent = "0 m";
      return;
    }
    const line = L.polyline(measurementPoints, {
      pane: "drawings",
      color: "#003f78",
      weight: 4,
      dashArray: "8 6",
    }).addTo(measurementGroup);
    line.bringToFront();
    measurementPoints.forEach((point, index) => {
      const marker = L.circleMarker(point, {
        pane: "drawings",
        radius: index === 0 ? 5 : 4,
        color: "#ffffff",
        weight: 2,
        fillColor: "#003f78",
        fillOpacity: 1,
      }).addTo(measurementGroup);
      if (index === measurementPoints.length - 1) {
        marker.bindTooltip(formatDistance(totalMeasurement()), {
          permanent: true,
          direction: "top",
          className: "measurement-tooltip",
        });
      }
    });
    elements.measurementValue.textContent = formatDistance(totalMeasurement());
  }

  function startMeasurement() {
    stopCoordinateMode();
    map.pm?.disableDraw();
    measuring = true;
    measurementPoints = [];
    measurementGroup.clearLayers();
    elements.measureTool.classList.add("active");
    elements.measureTool.querySelector("span:last-child").textContent = "Finalizar";
    elements.measurementPanel.hidden = false;
    elements.measurementValue.textContent = "0 m";
    map.getContainer().style.cursor = "crosshair";
    showMessage("Medición activa: haga clic sobre el mapa para agregar puntos.");
  }

  function finishMeasurement() {
    if (!measuring) return;
    measuring = false;
    elements.measureTool.classList.remove("active");
    elements.measureTool.querySelector("span:last-child").textContent = "Medir";
    map.getContainer().style.cursor = "";
  }

  function clearMeasurement() {
    finishMeasurement();
    measurementPoints = [];
    measurementGroup.clearLayers();
    elements.measurementPanel.hidden = true;
  }

  function coordinatePopup(latlng) {
    const coordinates = `${latlng.lat.toFixed(6)}, ${latlng.lng.toFixed(6)}`;
    return `
      <div class="coordinate-popup">
        <strong>Coordenadas WGS84</strong>
        <code>${coordinates}</code>
        <button type="button" class="copy-coordinate" data-coordinate="${coordinates}">Copiar coordenadas</button>
      </div>
    `;
  }

  function placeCoordinatePin(latlng) {
    if (coordinatePin) map.removeLayer(coordinatePin);
    const icon = L.divIcon({
      className: "coordinate-pin",
      html: "",
      iconSize: [25, 25],
      iconAnchor: [12, 24],
    });
    coordinatePin = L.marker(latlng, {
      icon,
      draggable: true,
      pane: "drawings",
      zIndexOffset: 1000,
    }).addTo(map);
    const update = () => coordinatePin.bindPopup(coordinatePopup(coordinatePin.getLatLng()), {
      closeButton: true,
      maxWidth: 260,
    });
    update();
    coordinatePin.on("dragend", () => {
      update();
      coordinatePin.openPopup();
    });
    coordinatePin.openPopup();
  }

  function startCoordinateMode() {
    finishMeasurement();
    map.pm?.disableDraw();
    pinMode = true;
    elements.pinTool.classList.add("active");
    map.getContainer().style.cursor = "crosshair";
    showMessage("Haga clic en el mapa para colocar un pin WGS84.");
  }

  function stopCoordinateMode() {
    pinMode = false;
    elements.pinTool.classList.remove("active");
    if (!measuring) map.getContainer().style.cursor = "";
  }

  async function parseKmlOrKmz(file) {
    const extension = file.name.split(".").pop().toLowerCase();
    let kmlText;
    if (extension === "kmz") {
      const archive = await JSZip.loadAsync(file);
      const kmlEntry = Object.values(archive.files).find(
        (entry) => !entry.dir && entry.name.toLowerCase().endsWith(".kml"),
      );
      if (!kmlEntry) throw new Error("El KMZ no contiene un archivo KML.");
      kmlText = await kmlEntry.async("string");
    } else if (extension === "kml") {
      kmlText = await file.text();
    } else {
      throw new Error("Seleccione un archivo .kml o .kmz.");
    }

    const documentXml = new DOMParser().parseFromString(kmlText, "text/xml");
    if (documentXml.querySelector("parsererror")) {
      throw new Error("El archivo KML no tiene una estructura válida.");
    }
    return toGeoJSON.kml(documentXml, { skipNullGeometry: true });
  }

  async function importFile(file) {
    try {
      showMessage(`Importando ${file.name}…`, false, 8000);
      const geojson = await parseKmlOrKmz(file);
      if (!geojson.features.length) throw new Error("El archivo no contiene geometrías visibles.");
      const layer = L.geoJSON(geojson, {
        pane: "drawings",
        style: (item) => ({
          pane: "drawings",
          color: item.properties?.stroke || "#003f78",
          weight: Number(item.properties?.["stroke-width"]) || 3,
          fillColor: item.properties?.fill || "#20a8e0",
          fillOpacity: Number(item.properties?.["fill-opacity"] ?? 0.2),
        }),
        pointToLayer: (_item, latlng) => L.circleMarker(latlng, {
          pane: "drawings",
          radius: 6,
          color: "#ffffff",
          weight: 2,
          fillColor: "#003f78",
          fillOpacity: 1,
        }),
        onEachFeature: (item, featureLayer) => {
          const name = item.properties?.name || file.name;
          featureLayer.bindPopup(simplePopup(name, "Archivo importado"));
        },
      }).addTo(importGroup);
      const bounds = layer.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [35, 35], maxZoom: 16 });
      showMessage(`${file.name} importado temporalmente (${geojson.features.length} elementos).`);
    } catch (error) {
      console.error(error);
      showMessage(error.message || "No fue posible importar el archivo.", true, 6000);
    } finally {
      elements.kmlInput.value = "";
    }
  }

  async function captureMap() {
    try {
      elements.captureTool.disabled = true;
      showMessage("Generando captura JPG…", false, 10000);
      const blob = await screenshoter.takeScreen("blob", {
        mimeType: "image/jpeg",
        cropImageByInnerWH: false,
        domtoimageOptions: {
          bgcolor: "#ffffff",
          cacheBust: true,
          quality: 0.96,
        },
      });
      const anchor = document.createElement("a");
      const date = new Date().toISOString().slice(0, 10);
      anchor.href = URL.createObjectURL(blob);
      anchor.download = `ach-gam-visor-${date}.jpg`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
      showMessage("Captura JPG generada.");
    } catch (error) {
      console.error(error);
      showMessage(
        "No se pudo generar la captura con este mapa base. Pruebe con el mapa Claro u OpenStreetMap.",
        true,
        7000,
      );
    } finally {
      elements.captureTool.disabled = false;
    }
  }

  function closeSidebarOnMobile() {
    if (window.matchMedia("(max-width: 760px)").matches) {
      elements.sidebar.classList.remove("open");
    }
  }

  function bindInterface() {
    document.querySelectorAll("input[data-layer]").forEach((input) => {
      input.addEventListener("change", () => {
        const layer = layerStore[input.dataset.layer];
        if (!layer) return;
        if (input.checked) layer.addTo(map);
        else map.removeLayer(layer);
        systemsLayer?.bringToFront();
      });
    });

    document.querySelectorAll(".filter-tab").forEach((button) => {
      button.addEventListener("click", () => applyCondition(button.dataset.condition));
    });

    elements.searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      locateSystem(elements.searchInput.value);
    });

    document.getElementById("clearLayers").addEventListener("click", () => {
      document.querySelectorAll("input[data-layer]:not([data-layer='systems'])").forEach((input) => {
        input.checked = false;
        const layer = layerStore[input.dataset.layer];
        if (layer) map.removeLayer(layer);
      });
      applyCondition("Todos");
      map.fitBounds(DEFAULT_BOUNDS, { padding: [18, 18] });
    });

    elements.pinTool.addEventListener("click", () => {
      if (pinMode) stopCoordinateMode();
      else startCoordinateMode();
    });

    elements.measureTool.addEventListener("click", () => {
      if (measuring) finishMeasurement();
      else startMeasurement();
    });

    elements.clearMeasurement.addEventListener("click", clearMeasurement);
    elements.importTool.addEventListener("click", () => elements.kmlInput.click());
    elements.kmlInput.addEventListener("change", () => {
      const [file] = elements.kmlInput.files;
      if (file) importFile(file);
    });
    elements.captureTool.addEventListener("click", captureMap);
    elements.homeTool.addEventListener("click", () => {
      map.fitBounds(DEFAULT_BOUNDS, { padding: [18, 18] });
      showMessage("Extensión general restaurada.");
    });

    elements.openSidebar.addEventListener("click", () => elements.sidebar.classList.add("open"));
    elements.closeSidebar.addEventListener("click", () => elements.sidebar.classList.remove("open"));

    map.on("click", (event) => {
      if (pinMode) {
        placeCoordinatePin(event.latlng);
        stopCoordinateMode();
        return;
      }
      if (measuring) {
        measurementPoints.push(event.latlng);
        redrawMeasurement();
      }
    });

    map.on("popupopen", (event) => {
      const copyButton = event.popup.getElement()?.querySelector(".copy-coordinate");
      if (!copyButton) return;
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(copyButton.dataset.coordinate);
          copyButton.textContent = "Copiado";
        } catch {
          showMessage("No se pudo copiar automáticamente; seleccione las coordenadas.", true);
        }
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      stopCoordinateMode();
      finishMeasurement();
      map.pm?.disableDraw();
    });

    window.addEventListener("resize", () => map.invalidateSize({ debounceMoveend: true }));
  }

  async function loadJson(key, url) {
    if (window.ACH_GAM_DATA?.[key]) return window.ACH_GAM_DATA[key];
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) throw new Error(`No fue posible cargar ${url}.`);
    return response.json();
  }

  async function initialize() {
    try {
      const [metadata, systems, municipal, esph, asadas, ona, protectedAreas, districts] = await Promise.all([
        loadJson("metadata", DATA_FILES.metadata),
        loadJson("systems", DATA_FILES.systems),
        loadJson("municipal", DATA_FILES.municipal),
        loadJson("esph", DATA_FILES.esph),
        loadJson("asadas", DATA_FILES.asadas),
        loadJson("ona", DATA_FILES.ona),
        loadJson("protected", DATA_FILES.protected),
        loadJson("districts", DATA_FILES.districts),
      ]);

      systemsData = systems;
      buildSystemsLayer();
      buildOptionalLayers({
        municipal,
        esph,
        asadas,
        ona,
        protected: protectedAreas,
        districts,
      });
      populateSearch();
      bindInterface();

      document.getElementById("systemCount").textContent = metadata.systems;
      document.getElementById("deficitCount").textContent = metadata.deficit;
      document.getElementById("surplusCount").textContent = metadata.surplus;
      document.getElementById("dataPeriod").textContent = metadata.period || "No indicado";

      map.fitBounds(systemsLayer.getBounds(), { padding: [18, 18] });
      elements.loading.classList.add("hidden");
      window.setTimeout(() => map.invalidateSize(), 380);
    } catch (error) {
      console.error(error);
      elements.loading.innerHTML = `
        <strong>No fue posible cargar el visor</strong>
        <span>${escapeHtml(error.message || "Error inesperado")}</span>
      `;
      showMessage("Revise que los archivos públicos existan en map/data/.", true, 12000);
    }
  }

  initialize();
})();
