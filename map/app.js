(() => {
  "use strict";

  const COLORS = {
    I: "#ff0000",
    II: "#ff8c00",
    III: "#ffd700",
    IV: "#00a651",
    unknown: "#8b98a5",
  };

  const CATEGORY_INFO = {
    I: {
      title: "Acueducto con déficit hídrico",
      range: "Balance hídrico inferior a -20 %",
      summary: "Opera con acciones permanentes y estrictas para el control hídrico del sistema.",
      actions: [
        "Posibles episodios de desabastecimiento o servicio discontinuo.",
        "Abastecimiento de emergencia mediante camiones cisterna.",
        "Racionamientos y bajas presiones de servicio.",
        "Mayor frecuencia de reclamos por faltante.",
        "Aprobación limitada de nuevos servicios conforme al concepto de desarrollo máximo.",
      ],
      note: "La condición requiere evaluación técnica estricta para cualquier disponibilidad o crecimiento de demanda.",
    },
    II: {
      title: "Acueducto en crecimiento máximo",
      range: "Balance hídrico entre -20 % y -5 %",
      summary: "Opera con acciones frecuentes y puntuales para controlar la demanda y sostener el servicio.",
      actions: [
        "Posible servicio intermitente o racionamiento puntual.",
        "Sectorización de la distribución.",
        "Aprovechamiento de fuentes a máxima capacidad.",
        "Cierre de tanques para control de la demanda.",
        "Posibles presiones inferiores a 10 mca y regulación de válvulas.",
        "Aprobación limitada de nuevos servicios conforme al concepto de desarrollo máximo.",
      ],
      note: "El sistema alcanzó su crecimiento máximo y requiere control operativo frecuente.",
    },
    III: {
      title: "Acueducto en transición",
      range: "Balance hídrico entre -5 % y +10 %",
      summary: "Mantiene condiciones generalmente aceptables, aunque puede presentar déficit parcial, localizado o estacional.",
      actions: [
        "Aprovechamiento de fuentes a máxima capacidad.",
        "Regulación de válvulas.",
        "Cierre de tanques ante interrupciones puntuales o condiciones críticas.",
        "Evaluación restringida de nuevos servicios cuando exista déficit localizado.",
      ],
      note: "El margen reducido puede comprometer el servicio en época seca o ante variaciones de producción y demanda.",
    },
    IV: {
      title: "Acueducto con capacidad hídrica",
      range: "Superávit superior a +10 %",
      summary: "Opera en condiciones adecuadas para la prestación del servicio y con control hídrico estable.",
      actions: [
        "Satisfacción general de continuidad, calidad y cantidad.",
        "Interrupciones principalmente asociadas a reparaciones o emergencias.",
        "Sin restricción hídrica general para tramitar disponibilidades.",
        "Menor frecuencia de reclamos por faltante.",
      ],
      note: "La categoría IV no elimina restricciones particulares, ambientales, de infraestructura o normativas que deban evaluarse por separado.",
    },
  };

  const DATA_FILES = {
    metadata: "data/metadata.json",
    systems: "data/sistemas.geojson",
    municipal: "data/municipalidades.geojson",
    esph: "data/esph.geojson",
    asadas: "data/asadas.geojson",
    thiessen: "data/cobertura-thiessen-asadas.geojson",
    criteria: "data/criterios-especiales.geojson",
    ona: "data/onas.geojson",
    protected: "data/areas-protegidas.geojson",
    districts: "data/distritos.geojson",
  };

  const DEFAULT_BOUNDS = L.latLngBounds([9.646, -84.505], [10.025, -83.925]);
  const layerStore = {};
  const layerFactories = {};
  const importGroup = L.featureGroup();
  const measurementGroup = L.featureGroup();
  let systemsData = null;
  let systemsLayer = null;
  let selectedCondition = "Todos";
  let messageTimer = null;
  let pinMode = false;
  let coordinatePin = null;
  let coordinateHighlight = null;
  let measuring = false;
  let measurementPoints = [];

  const elements = {
    loading: document.getElementById("loadingOverlay"),
    message: document.getElementById("mapMessage"),
    searchForm: document.getElementById("systemSearchForm"),
    searchInput: document.getElementById("systemSearch"),
    searchOptions: document.getElementById("systemOptions"),
    coordinateForm: document.getElementById("coordinateSearchForm"),
    coordinateLatitude: document.getElementById("coordinateLatitude"),
    coordinateLongitude: document.getElementById("coordinateLongitude"),
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
    categoryDialog: document.getElementById("categoryInfoDialog"),
    categoryCode: document.getElementById("categoryInfoCode"),
    categoryTitle: document.getElementById("categoryInfoTitle"),
    categoryRange: document.getElementById("categoryInfoRange"),
    categorySummary: document.getElementById("categoryInfoSummary"),
    categoryActions: document.getElementById("categoryInfoActions"),
    categoryNote: document.getElementById("categoryInfoNote"),
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
  map.createPane("estimatedCoverage").style.zIndex = 345;
  map.createPane("operators").style.zIndex = 360;
  map.createPane("criteria").style.zIndex = 690;
  map.createPane("systems").style.zIndex = 430;
  map.createPane("operatorPoints").style.zIndex = 470;
  map.createPane("drawings").style.zIndex = 650;
  map.createPane("coordinatePins").style.zIndex = 695;

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

  function criteriaVisualKind(records) {
    const hasArticle43 = records.some(
      (item) => normalized(item.tipo) === "FACILIDAD"
        && normalized(item.detalle).includes("ARTICULO43"),
    );
    const hasRestriction = records.some(
      (item) => normalized(item.tipo) === "RESTRICCION",
    );

    if (hasArticle43 && hasRestriction) return "mixed";
    if (hasArticle43) return "facility";
    if (hasRestriction) return "restriction";
    return "special";
  }

  function criteriaStyle(kind) {
    const styles = {
      facility: {
        color: "#1e6a9e",
        weight: 3,
        fillColor: "#d9edff",
        fillOpacity: 0.76,
      },
      restriction: {
        color: "#9f2016",
        weight: 4,
        fillColor: "#fff0ed",
        fillOpacity: 0.78,
      },
      mixed: {
        color: "#73415f",
        weight: 4,
        fillColor: "#f4eef5",
        fillOpacity: 0.8,
      },
      special: {
        color: "#9a6500",
        weight: 3,
        fillColor: "#fff4d6",
        fillOpacity: 0.72,
      },
    };
    return {
      ...styles[kind],
      opacity: 1,
      className: `criteria-dominant criteria-${kind}`,
    };
  }

  function ensureCriteriaPatterns() {
    const svg = map.getPane("criteria")?.querySelector("svg");
    if (!svg || svg.querySelector("#criteria-facility-pattern")) return;

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `
      <pattern id="criteria-facility-pattern" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
        <rect width="12" height="12" fill="#d9edff" fill-opacity="0.86"></rect>
        <line x1="0" y1="0" x2="0" y2="12" stroke="#2878ad" stroke-width="2.5" stroke-opacity="0.72"></line>
      </pattern>
      <pattern id="criteria-restriction-pattern" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(-35)">
        <rect width="12" height="12" fill="#fff0ed" fill-opacity="0.9"></rect>
        <line x1="0" y1="0" x2="0" y2="12" stroke="#b42318" stroke-width="3" stroke-opacity="0.82"></line>
      </pattern>
      <pattern id="criteria-mixed-pattern" width="14" height="14" patternUnits="userSpaceOnUse">
        <rect width="14" height="14" fill="#f4eef5" fill-opacity="0.9"></rect>
        <path d="M-3 3L3-3M0 14L14 0M11 17L17 11" stroke="#2878ad" stroke-width="2.2" stroke-opacity="0.72"></path>
        <path d="M-3 11L3 17M0 0L14 14M11-3L17 3" stroke="#b42318" stroke-width="2.2" stroke-opacity="0.78"></path>
      </pattern>
      <pattern id="criteria-special-pattern" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
        <rect width="12" height="12" fill="#fff4d6" fill-opacity="0.88"></rect>
        <line x1="0" y1="0" x2="0" y2="12" stroke="#a66a00" stroke-width="2.2" stroke-opacity="0.68"></line>
      </pattern>
    `;
    svg.prepend(defs);
  }

  function systemColor(ich) {
    return COLORS[ich] || COLORS.unknown;
  }

  function openCategoryInfo(category) {
    const info = CATEGORY_INFO[category];
    if (!info || !elements.categoryDialog) return;
    const dialogColors = {
      I: "#b90000",
      II: "#c85f00",
      III: "#9a7200",
      IV: "#007c3e",
    };
    elements.categoryDialog.style.setProperty(
      "--category-color",
      dialogColors[category] || "#075b9e",
    );
    elements.categoryCode.textContent = `ICH ${category}`;
    elements.categoryTitle.textContent = info.title;
    elements.categoryRange.textContent = info.range;
    elements.categorySummary.textContent = info.summary;
    elements.categoryActions.innerHTML = info.actions
      .map((action) => `<li>${escapeHtml(action)}</li>`)
      .join("");
    elements.categoryNote.textContent = info.note;
    if (typeof elements.categoryDialog.showModal === "function") {
      elements.categoryDialog.showModal();
    } else {
      elements.categoryDialog.setAttribute("open", "");
    }
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
          <button
            type="button"
            class="popup-category-info"
            data-popup-ich="${escapeHtml(properties.ich)}"
          >Conocer esta categoría hídrica</button>
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

  function criteriaPopup(properties, records) {
    const types = [...new Set(records.map((item) => item.tipo).filter(Boolean))];
    return `
      <article class="popup-card criteria-popup">
        <header class="popup-head">
          <small>${escapeHtml(properties.codigo_sistema)}</small>
          <strong>${escapeHtml(properties.nombre_sistema)}</strong>
        </header>
        <div class="popup-body">
          <div class="popup-row">
            <span>Condiciones registradas</span>
            <span>${escapeHtml(types.join(" / ") || "No especificadas")}</span>
          </div>
          <div class="criteria-list">
            ${records.map((item) => `
              <section class="criteria-item">
                <div class="criteria-item-head">
                  <strong>${escapeHtml(item.zona || item.codigo_abastecimiento)}</strong>
                  <span class="criteria-kind ${item.tipo === "Facilidad" ? "facility" : item.tipo === "Restricción" ? "restriction" : "special"}">
                    ${escapeHtml(item.tipo)}
                  </span>
                </div>
                <dl>
                  <div><dt>Detalle</dt><dd>${escapeHtml(item.detalle)}</dd></div>
                  <div><dt>Código</dt><dd>${escapeHtml(item.codigo_abastecimiento)}</dd></div>
                  <div><dt>Zona operativa</dt><dd>${escapeHtml(item.zona_operativa)}</dd></div>
                </dl>
              </section>
            `).join("")}
          </div>
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
    layerFactories.municipal = () => polygonLayer(
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

    layerStore.thiessen = polygonLayer(
      data.thiessen,
      {
        color: "#008b98",
        weight: 1.2,
        dashArray: "5 4",
        fillColor: "#42c4cb",
        fillOpacity: 0.11,
      },
      (p) => simplePopup(p.referencia, "Cobertura ASADA somera/estimada", [
        ["Código", p.codigo],
        ["Ubicación", [p.distrito, p.canton, p.provincia].filter(Boolean).join(", ")],
        ["Alcance", p.alcance],
        ["Método", p.metodo],
      ]),
      "estimatedCoverage",
    );

    layerStore.criteria = L.geoJSON(data.criteria, {
      pane: "criteria",
      style: (feature) => {
        return {
          ...criteriaStyle(criteriaVisualKind([feature.properties])),
          pane: "criteria",
        };
      },
      onEachFeature: (item, layer) => {
        layer.bindPopup(criteriaPopup(item.properties, [item.properties]), {
          maxWidth: 390,
          autoPan: true,
          closeButton: true,
          offset: [0, -8],
        });
      },
    });
    layerStore.criteria.on("add", () => {
      window.requestAnimationFrame(() => {
        ensureCriteriaPatterns();
        layerStore.criteria.bringToFront();
      });
    });

    layerFactories.ona = () => polygonLayer(
      data.ona,
      {
        color: "#c43c78",
        weight: 1.5,
        dashArray: "5 4",
        fillColor: "#e888ae",
        fillOpacity: 0.12,
      },
      (p) => simplePopup(p.sistema, "Cobertura ONA/SUA", [
        ["Organización", p.operador],
        ["Tipo", "Organización de usuarios de agua"],
      ]),
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
      (p) => simplePopup("Ubicación administrativa", "Distrito GAM", [
        ["Provincia", p.provincia],
        ["Cantón", p.canton],
        ["Distrito", p.distrito],
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

  function updateCoordinateInputs(latlng) {
    elements.coordinateLatitude.value = latlng.lat.toFixed(6);
    elements.coordinateLongitude.value = latlng.lng.toFixed(6);
  }

  function clearCoordinateHighlight() {
    if (!coordinateHighlight) return;
    map.removeLayer(coordinateHighlight);
    coordinateHighlight = null;
  }

  function highlightCoordinate(latlng) {
    clearCoordinateHighlight();
    coordinateHighlight = L.circleMarker(latlng, {
      pane: "coordinatePins",
      radius: 18,
      color: "#ffbf00",
      weight: 4,
      opacity: 0.96,
      fillColor: "#20a8e0",
      fillOpacity: 0.24,
      interactive: false,
      className: "coordinate-highlight",
    }).addTo(map);
  }

  function placeCoordinatePin(latlng, options = {}) {
    const { highlight = false, openPopup = true } = options;
    if (coordinatePin) map.removeLayer(coordinatePin);
    clearCoordinateHighlight();
    if (highlight) highlightCoordinate(latlng);
    const icon = L.divIcon({
      className: "coordinate-pin",
      html: "",
      iconSize: [25, 25],
      iconAnchor: [12, 24],
    });
    coordinatePin = L.marker(latlng, {
      icon,
      draggable: true,
      pane: "coordinatePins",
      zIndexOffset: 1000,
    }).addTo(map);
    const update = () => coordinatePin.bindPopup(coordinatePopup(coordinatePin.getLatLng()), {
      closeButton: true,
      maxWidth: 260,
    });
    update();
    coordinatePin.on("dragend", () => {
      clearCoordinateHighlight();
      update();
      updateCoordinateInputs(coordinatePin.getLatLng());
      coordinatePin.openPopup();
    });
    updateCoordinateInputs(latlng);
    if (openPopup) coordinatePin.openPopup();
  }

  function parseCoordinate(value) {
    const token = String(value ?? "").trim().replace(",", ".");
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(token)) return null;
    const number = Number(token);
    return Number.isFinite(number) ? number : null;
  }

  function locateCoordinate() {
    const latitude = parseCoordinate(elements.coordinateLatitude.value);
    const longitude = parseCoordinate(elements.coordinateLongitude.value);
    if (latitude === null || longitude === null) {
      showMessage("Ingrese latitud y longitud WGS84 en grados decimales.", true);
      return;
    }
    if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
      showMessage("La latitud debe estar entre -90 y 90 y la longitud entre -180 y 180.", true);
      return;
    }

    stopCoordinateMode();
    finishMeasurement();
    const latlng = L.latLng(latitude, longitude);
    placeCoordinatePin(latlng, { highlight: true, openPopup: false });
    map.flyTo(latlng, 17, { animate: true, duration: 0.9 });
    window.setTimeout(() => coordinatePin?.openPopup(), 950);
    showMessage(`Punto WGS84 ubicado: ${latitude.toFixed(6)}, ${longitude.toFixed(6)}.`);
    closeSidebarOnMobile();
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
    document.querySelectorAll("[data-ich-info]").forEach((button) => {
      button.addEventListener("click", () => openCategoryInfo(button.dataset.ichInfo));
    });

    elements.categoryDialog?.addEventListener("click", (event) => {
      if (event.target === elements.categoryDialog) elements.categoryDialog.close();
    });

    document.querySelectorAll("input[data-layer]").forEach((input) => {
      input.addEventListener("change", () => {
        const layerName = input.dataset.layer;
        let layer = layerStore[layerName];
        if (!layer && input.checked && layerFactories[layerName]) {
          showMessage("Preparando la cobertura detallada…");
          layer = layerFactories[layerName]();
          layerStore[layerName] = layer;
        }
        if (!layer) return;
        if (input.checked) layer.addTo(map);
        else map.removeLayer(layer);
        if (layerStore.criteria && map.hasLayer(layerStore.criteria)) {
          layerStore.criteria.bringToFront();
        } else {
          systemsLayer?.bringToFront();
        }
      });
    });

    document.querySelectorAll(".filter-tab").forEach((button) => {
      button.addEventListener("click", () => applyCondition(button.dataset.condition));
    });

    elements.searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      locateSystem(elements.searchInput.value);
    });

    elements.coordinateForm.addEventListener("submit", (event) => {
      event.preventDefault();
      locateCoordinate();
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
      const popupElement = event.popup.getElement();
      const categoryButton = popupElement?.querySelector(".popup-category-info");
      const copyButton = popupElement?.querySelector(".copy-coordinate");

      categoryButton?.addEventListener("click", () => {
        const category = categoryButton.dataset.popupIch;
        map.closePopup(event.popup);
        openCategoryInfo(category);
      });

      copyButton?.addEventListener("click", async () => {
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
      const [metadata, systems, municipal, esph, asadas, thiessen, criteria, ona, protectedAreas, districts] = await Promise.all([
        loadJson("metadata", DATA_FILES.metadata),
        loadJson("systems", DATA_FILES.systems),
        loadJson("municipal", DATA_FILES.municipal),
        loadJson("esph", DATA_FILES.esph),
        loadJson("asadas", DATA_FILES.asadas),
        loadJson("thiessen", DATA_FILES.thiessen),
        loadJson("criteria", DATA_FILES.criteria),
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
        thiessen,
        criteria,
        ona,
        protected: protectedAreas,
        districts,
      });
      populateSearch();
      bindInterface();

      const metadataLabels = {
        systemCount: metadata.systems,
        deficitCount: metadata.deficit,
        surplusCount: metadata.surplus,
        dataPeriod: metadata.period || "No indicado",
      };
      Object.entries(metadataLabels).forEach(([id, value]) => {
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      });

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
