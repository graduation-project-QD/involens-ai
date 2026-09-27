const LABELS = {
  SELLER: { id: 15, color: "#ed5548" },
  ADDRESS: { id: 16, color: "#3b82f6" },
  TIMESTAMP: { id: 17, color: "#35a56a" },
  TOTAL_COST: { id: 18, color: "#9255d9" },
  ITEM_NAME: { id: 19, color: "#d97706" },
  QUANTITY: { id: 20, color: "#0891b2" },
  UNIT_PRICE: { id: 21, color: "#db2777" },
  LINE_TOTAL: { id: 22, color: "#7c3aed" },
};
const LINE_ITEM_LABELS = new Set(["ITEM_NAME", "QUANTITY", "UNIT_PRICE", "LINE_TOTAL"]);

const state = {
  mode: "train",
  images: [],
  current: null,
  regions: [],
  selectedId: null,
  category: "SELLER",
  dirty: false,
  zoom: 1,
  baseScale: 1,
  rotation: 0,
  rotationsByImage: new Map(),
  pointer: null,
  pan: null,
  labelsVisible: true,
  csvPath: "",
  rotationCsvPath: "",
  missingFieldsPath: "",
  missingFields: new Set(),
  undoStack: [],
  redoStack: [],
  lineItemId: 1,
  loadRequestId: 0,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  tabs: [...document.querySelectorAll(".mode-tab")],
  workspaceImport: $("#workspaceImport"),
  workspaceCsvPath: $("#workspaceCsvPath"),
  workspaceImageDir: $("#workspaceImageDir"),
  openWorkspace: $("#openWorkspace"),
  workspaceHint: $("#workspaceHint"),
  refreshList: $("#refreshList"),
  listTitle: $("#listTitle"),
  listCount: $("#listCount"),
  imageSearch: $("#imageSearch"),
  statusFilter: $("#statusFilter"),
  flagFilterOption: $('#statusFilter option[value="flagged"]'),
  rotationFilterOption: $('#statusFilter option[value="rotation_pending"]'),
  imageList: $("#imageList"),
  currentName: $("#currentName"),
  imageMeta: $("#imageMeta"),
  emptyStage: $("#emptyStage"),
  viewport: $("#canvasViewport"),
  frame: $("#canvasFrame"),
  surface: $("#canvasSurface"),
  image: $("#receiptImage"),
  svg: $("#annotationLayer"),
  regionLayer: $("#regionLayer"),
  draftRect: $("#draftRect"),
  zoomOut: $("#zoomOut"),
  zoomIn: $("#zoomIn"),
  zoomLabel: $("#zoomLabel"),
  rotateLeft: $("#rotateLeft"),
  rotateRight: $("#rotateRight"),
  fineRotateLeft: $("#fineRotateLeft"),
  fineRotateRight: $("#fineRotateRight"),
  rotationAngle: $("#rotationAngle"),
  undoAction: $("#undoAction"),
  redoAction: $("#redoAction"),
  rotationPanel: $("#rotationPanel"),
  rotationStatus: $("#rotationStatus"),
  rotationPath: $("#rotationPath"),
  confirmRotation: $("#confirmRotation"),
  fitImage: $("#fitImage"),
  toggleLabels: $("#toggleLabels"),
  categoryGrid: $("#categoryGrid"),
  categoryIdBadge: $("#categoryIdBadge"),
  lineItemControl: $("#lineItemControl"),
  lineItemId: $("#lineItemId"),
  lineItemHint: $("#lineItemHint"),
  nextLineItem: $("#nextLineItem"),
  toggleMissingField: $("#toggleMissingField"),
  missingFieldHint: $("#missingFieldHint"),
  regionText: $("#regionText"),
  coordX: $("#coordX"),
  coordY: $("#coordY"),
  coordW: $("#coordW"),
  coordH: $("#coordH"),
  regionDetails: $("#regionDetails"),
  deleteRegion: $("#deleteRegion"),
  regionList: $("#regionList"),
  regionCount: $("#regionCount"),
  validation: $("#validationMessage"),
  flagImage: $("#flagImage"),
  save: $("#saveAnnotation"),
  saveAndNext: $("#saveAndNext"),
  previousImage: $("#previousImage"),
  nextImage: $("#nextImage"),
  draftStatus: $("#draftStatus"),
  markChecked: $("#markChecked"),
  exportCsv: $("#exportCsv"),
  csvPath: $("#csvPath"),
  saveState: $("#saveState"),
  toast: $("#toast"),
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body.error || body || `HTTP ${response.status}`);
  return body;
}

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("visible"), 3000);
}

function setDirty(value) {
  state.dirty = value;
  els.saveState.classList.toggle("dirty", value);
  els.saveState.classList.remove("error");
  els.saveState.querySelector("span:last-child").textContent = value ? "Có thay đổi chưa lưu" : "Đã đồng bộ";
  if (value) scheduleDraftSave();
  renderImageList();
  validateCurrent();
}

function draftStorageKey() {
  if (!state.current || !state.csvPath) return null;
  return `mcocr-labeler:draft:${state.mode}:${state.csvPath}:${state.current.img_id}`;
}

function scheduleDraftSave() {
  clearTimeout(scheduleDraftSave.timer);
  scheduleDraftSave.timer = setTimeout(saveDraftNow, 500);
}

function saveDraftNow() {
  const key = draftStorageKey();
  if (!key || !state.dirty) return;
  try {
    localStorage.setItem(key, JSON.stringify({
      regions: state.regions,
      missing_fields: [...state.missingFields],
      saved_at: new Date().toISOString(),
    }));
    els.draftStatus.textContent = `Bản nháp tự động: ${new Date().toLocaleTimeString("vi-VN")}`;
  } catch (_) {
    els.draftStatus.textContent = "Không thể lưu bản nháp trong trình duyệt";
  }
}

function readDraft() {
  const key = draftStorageKey();
  if (!key) return null;
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value && Array.isArray(value.regions) && Array.isArray(value.missing_fields) ? value : null;
  } catch (_) {
    return null;
  }
}

function clearDraft() {
  const key = draftStorageKey();
  if (key) localStorage.removeItem(key);
  els.draftStatus.textContent = "Bản nháp tự động: đã đồng bộ với CSV";
}

function editorSnapshot() {
  return {
    regions: structuredClone(state.regions),
    missingFields: [...state.missingFields],
    selectedId: state.selectedId,
    category: state.category,
    lineItemId: state.lineItemId,
  };
}

function pushHistory() {
  if (!state.current) return;
  state.undoStack.push(editorSnapshot());
  if (state.undoStack.length > 50) state.undoStack.shift();
  state.redoStack = [];
  refreshHistoryButtons();
}

function applyEditorSnapshot(snapshot) {
  state.regions = structuredClone(snapshot.regions);
  state.missingFields = new Set(snapshot.missingFields);
  state.selectedId = snapshot.selectedId;
  state.lineItemId = snapshot.lineItemId;
  setCategory(snapshot.category, false);
  setDirty(true);
  renderAll();
}

function undoEdit() {
  if (!state.undoStack.length) return;
  state.redoStack.push(editorSnapshot());
  applyEditorSnapshot(state.undoStack.pop());
  refreshHistoryButtons();
}

function redoEdit() {
  if (!state.redoStack.length) return;
  state.undoStack.push(editorSnapshot());
  applyEditorSnapshot(state.redoStack.pop());
  refreshHistoryButtons();
}

function refreshHistoryButtons() {
  els.undoAction.disabled = !state.undoStack.length;
  els.redoAction.disabled = !state.redoStack.length;
}

function setFailure(message) {
  els.saveState.classList.remove("dirty");
  els.saveState.classList.add("error");
  els.saveState.querySelector("span:last-child").textContent = message;
}

async function loadState(selectName = null) {
  const requestedMode = state.mode;
  const requestId = ++state.loadRequestId;
  try {
    const payload = await api(`/api/state?mode=${requestedMode}`);
    if (requestId !== state.loadRequestId || requestedMode !== state.mode) return;
    state.images = payload.images;
    state.csvPath = payload.csv_path || "";
    state.rotationCsvPath = payload.rotation_csv_path || "";
    state.missingFieldsPath = payload.missing_fields_path || "";
    els.workspaceCsvPath.value = payload.workspace?.csv_path || els.workspaceCsvPath.value;
    els.workspaceImageDir.value = payload.workspace?.image_directory || els.workspaceImageDir.value;
    els.csvPath.textContent = state.csvPath ? `Lưu tại: ${state.csvPath}` : "Chưa có phiên CSV đang hoạt động.";
    renderImageList();
    if (selectName) {
      const image = state.images.find((item) => item.img_id === selectName);
      if (image) await selectImage(image, true);
    }
  } catch (error) {
    if (requestId !== state.loadRequestId || requestedMode !== state.mode) return;
    showToast(error.message, true);
    setFailure("Không tải được dữ liệu");
  }
}

function filteredImages() {
  const term = els.imageSearch.value.trim().toLowerCase();
  const filter = els.statusFilter.value;
  return state.images.filter((image) => {
    const matchesName = image.img_id.toLowerCase().includes(term);
    let matchesStatus = true;
    if (filter === "pending") matchesStatus = !image.checked;
    if (filter === "done") matchesStatus = image.checked;
    if (filter === "saved") matchesStatus = image.annotated;
    if (filter === "empty") matchesStatus = !image.annotated;
    if (filter === "flagged") matchesStatus = image.flagged;
    if (filter === "rotation_pending") matchesStatus = !image.rotation_confirmed;
    return matchesName && matchesStatus;
  });
}

function renderImageList() {
  const images = filteredImages();
  els.imageList.innerHTML = "";
  els.listCount.textContent = `${images.length}/${state.images.length} ảnh`;
  if (!images.length) {
    els.imageList.innerHTML = '<p class="hint" style="padding:12px">Không có ảnh phù hợp.</p>';
    return;
  }
  images.forEach((image, index) => {
    const button = document.createElement("button");
    button.className = `image-item${state.current?.img_id === image.img_id ? " active" : ""}`;
    const hasUnsavedChanges = state.current?.img_id === image.img_id && state.dirty;
    const statusClass = image.missing_image
      ? "missing"
      : hasUnsavedChanges
        ? "dirty"
        : image.checked
          ? "checked"
          : image.annotated
            ? "saved"
            : "empty";
    const statusTitle = image.missing_image
      ? "Thiếu ảnh"
      : hasUnsavedChanges
        ? "Có thay đổi chưa lưu"
      : image.checked
        ? "Đã hoàn tất"
      : image.annotated
        ? "Đã có dữ liệu trong CSV"
        : "Chưa có vùng nhãn";
    button.innerHTML = `
      <span class="image-number">${String(index + 1).padStart(3, "0")}</span>
      <span class="image-copy">
        <span class="image-name" title="${escapeHtml(image.img_id)}">${escapeHtml(image.img_id)}</span>
        <span class="image-size">${image.width || "?"} × ${image.height || "?"} · ${image.anno_num || 0} vùng${image.rotation_confirmed ? ` · hướng ${image.rotation_to_upright}°` : " · chưa xác nhận hướng"}</span>
      </span>
      <span class="item-flag" title="Ảnh khó đọc">${image.flagged ? "🚩" : ""}</span>
      <span class="item-status ${statusClass}" title="${statusTitle}"></span>`;
    button.addEventListener("click", () => selectImage(image));
    els.imageList.appendChild(button);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function selectImage(image, force = false) {
  if (state.dirty && !force) saveDraftNow();
  if (image.missing_image) {
    showToast(`Không tìm thấy ảnh ${image.img_id}. Hãy kiểm tra thư mục ảnh.`, true);
    return;
  }
  try {
    const annotation = await api(`/api/annotation?mode=${state.mode}&img_id=${encodeURIComponent(image.img_id)}`);
    state.current = {
      ...image,
      width: annotation.width,
      height: annotation.height,
      anno_image_quality: annotation.anno_image_quality || "",
    };
    state.regions = annotation.regions.map((region, index) => ({ ...region, id: `region-${index + 1}-${Date.now()}` }));
    state.missingFields = new Set(annotation.missing_fields || []);
    const draft = readDraft();
    if (draft) {
      state.regions = draft.regions;
      state.missingFields = new Set(draft.missing_fields);
    }
    state.undoStack = [];
    state.redoStack = [];
    refreshHistoryButtons();
    const firstRegion = state.regions[0];
    state.selectedId = firstRegion?.id || null;
    const existingItemIds = state.regions
      .filter((region) => isLineItemLabel(region.label))
      .map((region) => positiveInteger(region.line_item_id, 0));
    state.lineItemId = Math.max(1, ...existingItemIds);
    const rotationKey = `${state.mode}:${image.img_id}`;
    state.rotation = state.rotationsByImage.has(rotationKey)
      ? state.rotationsByImage.get(rotationKey)
      : (image.rotation_confirmed ? image.rotation_to_upright : 0);
    setCategory(
      state.mode === "train"
        ? (firstRegion?.label || "ITEM_NAME")
        : (state.regions[0]?.label || "SELLER"),
      false,
    );
    state.zoom = 1;
    setDirty(Boolean(draft));
    els.draftStatus.textContent = draft
      ? `Đã khôi phục bản nháp lúc ${new Date(draft.saved_at).toLocaleTimeString("vi-VN")}`
      : "Bản nháp tự động: đã đồng bộ với CSV";
    els.currentName.textContent = image.img_id;
    updateImageMeta();
    els.emptyStage.classList.add("hidden");
    els.viewport.classList.remove("hidden");
    els.image.src = `/api/image/${encodeURIComponent(image.img_id)}?mode=${state.mode}&v=${Date.now()}`;
    await new Promise((resolve, reject) => {
      els.image.onload = resolve;
      els.image.onerror = reject;
    });
    els.svg.setAttribute("viewBox", `0 0 ${annotation.width} ${annotation.height}`);
    fitImage();
    renderAll();
    if (draft) showToast("Đã khôi phục bản nháp chưa lưu của ảnh này");
  } catch (error) {
    showToast(error.message, true);
  }
}

function fitImage() {
  if (!state.current) return;
  const availableWidth = Math.max(100, els.viewport.clientWidth - 56);
  const availableHeight = Math.max(100, els.viewport.clientHeight - 56);
  const geometry = rotationGeometry(state.current.width, state.current.height, state.rotation);
  state.baseScale = Math.min(availableWidth / geometry.width, availableHeight / geometry.height, 1);
  state.zoom = 1;
  applyZoom();
}

function applyZoom() {
  if (!state.current) return;
  const scale = state.baseScale * state.zoom;
  const width = Math.round(state.current.width * scale);
  const height = Math.round(state.current.height * scale);
  const geometry = rotationGeometry(width, height, state.rotation);
  els.frame.style.width = `${Math.ceil(geometry.width)}px`;
  els.frame.style.height = `${Math.ceil(geometry.height)}px`;
  els.surface.style.width = `${width}px`;
  els.surface.style.height = `${height}px`;
  els.image.style.width = `${width}px`;
  els.image.style.height = `${height}px`;
  els.svg.style.width = `${width}px`;
  els.svg.style.height = `${height}px`;
  els.surface.style.transform = state.rotation === 0
    ? "none"
    : `translate(${-geometry.minX}px, ${-geometry.minY}px) rotate(${state.rotation}deg)`;
  els.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  els.rotationAngle.value = state.rotation;
  renderRotationControl();
}

function zoomAt(nextZoom, clientX = null, clientY = null) {
  if (!state.current) return;
  const viewportRect = els.viewport.getBoundingClientRect();
  const anchorX = clientX ?? (viewportRect.left + viewportRect.width / 2);
  const anchorY = clientY ?? (viewportRect.top + viewportRect.height / 2);
  const oldFrameRect = els.frame.getBoundingClientRect();
  const relativeX = oldFrameRect.width
    ? clamp((anchorX - oldFrameRect.left) / oldFrameRect.width, 0, 1)
    : .5;
  const relativeY = oldFrameRect.height
    ? clamp((anchorY - oldFrameRect.top) / oldFrameRect.height, 0, 1)
    : .5;

  state.zoom = clamp(nextZoom, .35, 4);
  applyZoom();

  const newFrameRect = els.frame.getBoundingClientRect();
  els.viewport.scrollLeft += newFrameRect.left + relativeX * newFrameRect.width - anchorX;
  els.viewport.scrollTop += newFrameRect.top + relativeY * newFrameRect.height - anchorY;
}

function updateImageMeta() {
  if (!state.current) return;
  const orientation = state.current.rotation_confirmed
    ? ` · hướng: ${state.current.rotation_to_upright}° đã xác nhận`
    : " · hướng: chưa xác nhận";
  els.imageMeta.textContent = `${state.current.width} × ${state.current.height} px · ${state.regions.length} vùng · quality: ${state.current.anno_image_quality || "trống"}${orientation}${state.current.flagged ? " · 🚩 ảnh khó đọc" : ""}`;
}

function renderRotationControl() {
  const available = Boolean(state.current);
  els.rotationPanel.classList.remove("hidden");
  els.confirmRotation.disabled = !available;
  els.confirmRotation.textContent = `Xác nhận chiều đọc: ${state.rotation}°`;
  els.rotationPath.textContent = state.rotationCsvPath ? `Lưu tại: ${state.rotationCsvPath}` : "File góc xoay sẽ được tạo cạnh CSV nhãn.";
  const matchesSaved = available
    && state.current.rotation_confirmed
    && state.current.rotation_to_upright === state.rotation;
  els.confirmRotation.classList.toggle("confirmed", Boolean(matchesSaved));
  if (!available) {
    els.rotationStatus.textContent = "Chưa chọn ảnh";
  } else if (matchesSaved) {
    els.rotationStatus.textContent = `Đã lưu ${state.rotation}°`;
  } else if (state.current.rotation_confirmed) {
    els.rotationStatus.textContent = `Đã lưu ${state.current.rotation_to_upright}° · đang xem ${state.rotation}°`;
  } else {
    els.rotationStatus.textContent = `Chưa xác nhận · đang xem ${state.rotation}°`;
  }
}

function normalizeRotation(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return state.rotation;
  return ((Math.round(parsed) % 360) + 360) % 360;
}

function rotationGeometry(width, height, rotation) {
  const radians = rotation * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const corners = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ].map(([x, y]) => [x * cos - y * sin, x * sin + y * cos]);
  const xs = corners.map(([x]) => x);
  const ys = corners.map(([, y]) => y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  return { minX, minY, width: maxX - minX, height: maxY - minY, cos, sin };
}

function framePoint(event) {
  const bounds = els.frame.getBoundingClientRect();
  return {
    x: clamp(event.clientX - bounds.left, 0, bounds.width),
    y: clamp(event.clientY - bounds.top, 0, bounds.height),
  };
}

function originalPointFromDisplay(displayPoint) {
  const renderedWidth = Number.parseFloat(els.surface.style.width) || state.current.width;
  const renderedHeight = Number.parseFloat(els.surface.style.height) || state.current.height;
  const scaleX = renderedWidth / state.current.width;
  const scaleY = renderedHeight / state.current.height;
  const geometry = rotationGeometry(renderedWidth, renderedHeight, state.rotation);
  const rotatedX = displayPoint.x + geometry.minX;
  const rotatedY = displayPoint.y + geometry.minY;
  const sourceX = rotatedX * geometry.cos + rotatedY * geometry.sin;
  const sourceY = -rotatedX * geometry.sin + rotatedY * geometry.cos;
  return {
    x: clamp(sourceX / scaleX, 0, state.current.width),
    y: clamp(sourceY / scaleY, 0, state.current.height),
  };
}

function svgPoint(event) { return originalPointFromDisplay(framePoint(event)); }

function displayRectanglePoints(start, end) {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const right = Math.max(start.x, end.x);
  const bottom = Math.max(start.y, end.y);
  return [
    originalPointFromDisplay({ x: left, y: top }),
    originalPointFromDisplay({ x: right, y: top }),
    originalPointFromDisplay({ x: right, y: bottom }),
    originalPointFromDisplay({ x: left, y: bottom }),
  ].flatMap(({ x, y }) => [round(x), round(y)]);
}

function rotateView(delta) {
  if (!state.current) return;
  state.rotation = normalizeRotation(state.rotation + delta);
  state.rotationsByImage.set(`${state.mode}:${state.current.img_id}`, state.rotation);
  fitImage();
}

function setRotationFromInput() {
  if (!state.current) return;
  state.rotation = normalizeRotation(els.rotationAngle.value);
  state.rotationsByImage.set(`${state.mode}:${state.current.img_id}`, state.rotation);
  fitImage();
}

function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }
function round(value) { return Math.round(value * 100) / 100; }
function isLineItemLabel(label) { return LINE_ITEM_LABELS.has(label); }

function positiveInteger(value, fallback = 1) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function bboxFromPoints(points) {
  const xs = points.filter((_, index) => index % 2 === 0);
  const ys = points.filter((_, index) => index % 2 === 1);
  const x = Math.min(...xs), y = Math.min(...ys);
  return [x, y, Math.max(...xs) - x, Math.max(...ys) - y].map(round);
}

function rectanglePoints(x, y, width, height) {
  return [x, y, x + width, y, x + width, y + height, x, y + height].map(round);
}

function regionColor(region) { return LABELS[region.label]?.color || "#777"; }

function renderAll() {
  updateCategoryAvailability();
  renderRegions();
  renderInspector();
  renderMissingFieldControl();
  refreshHistoryButtons();
  renderImageList();
  validateCurrent();
}

function renderRegions() {
  els.regionLayer.innerHTML = "";
  els.regionLayer.classList.toggle("labels-hidden", !state.labelsVisible);
  state.regions.forEach((region, index) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", `region-group${region.id === state.selectedId ? " is-selected" : ""}`);
    const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    const pairs = [];
    for (let i = 0; i < region.segmentation.length; i += 2) pairs.push(`${region.segmentation[i]},${region.segmentation[i + 1]}`);
    polygon.setAttribute("points", pairs.join(" "));
    polygon.setAttribute("fill", regionColor(region));
    polygon.setAttribute("stroke", regionColor(region));
    polygon.setAttribute("class", `region-polygon${region.id === state.selectedId ? " selected" : ""}`);
    polygon.dataset.regionId = region.id;
    const [x, y] = bboxFromPoints(region.segmentation);
    const itemSuffix = isLineItemLabel(region.label) ? ` · L${region.line_item_id ?? "?"}` : "";
    const labelText = `${index + 1} · ${region.label}${itemSuffix}`;
    const compactText = `${index + 1}`;
    const compactWidth = Math.max(13, compactText.length * 5.5 + 6);
    const labelX = x - compactWidth - 3;
    const labelY = y;

    const compactRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    compactRect.setAttribute("x", labelX);
    compactRect.setAttribute("y", labelY);
    compactRect.setAttribute("width", compactWidth);
    compactRect.setAttribute("height", 14);
    compactRect.setAttribute("fill", regionColor(region));
    compactRect.setAttribute("class", "region-label-bg region-label-compact");

    const compactLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    compactLabel.setAttribute("x", labelX + 3);
    compactLabel.setAttribute("y", labelY + 10);
    compactLabel.setAttribute("class", "region-label region-label-compact");
    compactLabel.textContent = compactText;

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = labelText;
    group.append(polygon, compactRect, compactLabel, title);
    els.regionLayer.appendChild(group);
  });
}

function toggleRegionLabels() {
  state.labelsVisible = !state.labelsVisible;
  els.toggleLabels.classList.toggle("active", !state.labelsVisible);
  els.toggleLabels.textContent = state.labelsVisible ? "#" : "×";
  els.toggleLabels.setAttribute("aria-label", state.labelsVisible ? "Ẩn badge nhãn" : "Hiện badge nhãn");
  els.toggleLabels.title = state.labelsVisible ? "Ẩn badge nhãn (H)" : "Hiện badge nhãn (H)";
  renderRegions();
}

function selectedRegion() { return state.regions.find((region) => region.id === state.selectedId) || null; }

function selectRegion(id) {
  state.selectedId = id;
  const region = selectedRegion();
  if (region) setCategory(region.label, false);
  renderAll();
}

function syncLineItemControl() {
  const enabled = isLineItemLabel(state.category);
  els.lineItemControl.classList.toggle("is-disabled", !enabled);
  els.lineItemId.disabled = !enabled;
  els.nextLineItem.disabled = !enabled;
  els.lineItemId.value = state.lineItemId;
  els.lineItemHint.textContent = enabled
    ? `Các vùng ${state.category} mới sẽ thuộc dòng hàng #${state.lineItemId}.`
    : "SELLER, ADDRESS, TIMESTAMP và TOTAL_COST luôn có line_item_id = null.";
  renderMissingFieldControl();
}

function currentMissingFieldKey() {
  return isLineItemLabel(state.category) ? `${state.category}:${state.lineItemId}` : state.category;
}

function renderMissingFieldControl() {
  const key = currentMissingFieldKey();
  const active = state.missingFields.has(key);
  const hasRegion = state.regions.some((region) => region.label === state.category
    && (!isLineItemLabel(state.category) || Number(region.line_item_id) === state.lineItemId));
  const unavailable = !state.current;
  els.toggleMissingField.classList.remove("hidden");
  els.missingFieldHint.classList.remove("hidden");
  els.toggleMissingField.disabled = unavailable || (hasRegion && !active);
  els.toggleMissingField.classList.toggle("active", active);
  els.toggleMissingField.textContent = active ? "Bỏ đánh dấu: trường không xuất hiện" : "Trường này không xuất hiện";
  if (active) {
    els.missingFieldHint.textContent = `${key} đã được khai báo là không có trên hóa đơn.`;
  } else if (hasRegion) {
    els.missingFieldHint.textContent = `${key} đã có vùng nhãn nên không thể đánh dấu vắng mặt.`;
  } else {
    els.missingFieldHint.textContent = `Chỉ dùng khi ${key} thực sự không được in trên hóa đơn.`;
  }
}

function toggleMissingField() {
  if (!state.current) return;
  const key = currentMissingFieldKey();
  pushHistory();
  if (state.missingFields.has(key)) state.missingFields.delete(key);
  else state.missingFields.add(key);
  setDirty(true);
  renderAll();
}

function updateCategoryAvailability() {
  [...els.categoryGrid.querySelectorAll(".category")].forEach((button) => {
    button.disabled = false;
  });
}

function renderInspector() {
  const region = selectedRegion();
  const controls = [els.regionText, els.coordX, els.coordY, els.coordW, els.coordH, els.deleteRegion];
  controls.forEach((control) => { control.disabled = !region; });
  els.regionCount.textContent = state.regions.length;
  els.regionList.innerHTML = "";
  state.regions.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `region-item${item.id === state.selectedId ? " active" : ""}`;
    row.innerHTML = `
      <i class="region-color" style="background:${regionColor(item)}"></i>
      <div><strong>${escapeHtml(item.label)}${isLineItemLabel(item.label) ? ` · dòng #${item.line_item_id ?? "?"}` : ""}</strong><span>${escapeHtml(item.text || "Chưa nhập nội dung")}</span></div>
      <b class="region-index">#${index + 1}</b>`;
    row.addEventListener("click", () => selectRegion(item.id));
    els.regionList.appendChild(row);
  });
  if (!region) {
    els.regionText.value = "";
    [els.coordX, els.coordY, els.coordW, els.coordH].forEach((input) => { input.value = ""; });
    els.regionDetails.textContent = "Chọn hoặc tạo một vùng để chỉnh sửa.";
    return;
  }
  const [x, y, width, height] = bboxFromPoints(region.segmentation);
  els.regionText.value = region.text || "";
  els.coordX.value = Math.round(x);
  els.coordY.value = Math.round(y);
  els.coordW.value = Math.round(width);
  els.coordH.value = Math.round(height);
  els.regionDetails.textContent = `category_id ${LABELS[region.label].id} · area ${Math.round(width * height)} px²`;
}

function setCategory(label, updateRegion = true) {
  if (!LABELS[label]) return;
  state.category = label;
  els.categoryIdBadge.textContent = `ID ${LABELS[label].id}`;
  [...els.categoryGrid.querySelectorAll(".category")].forEach((button) => {
    button.classList.toggle("active", button.dataset.label === label);
  });
  const region = selectedRegion();
  if (!updateRegion && region && isLineItemLabel(region.label) && region.line_item_id) {
    state.lineItemId = positiveInteger(region.line_item_id, state.lineItemId);
  }
  if (updateRegion && region && region.label !== label) {
    pushHistory();
    region.label = label;
    region.category_id = LABELS[label].id;
    region.line_item_id = isLineItemLabel(label) ? state.lineItemId : null;
    state.missingFields.delete(isLineItemLabel(label) ? `${label}:${state.lineItemId}` : label);
    setDirty(true);
    renderAll();
  }
  syncLineItemControl();
}

function updateSelectedRectangle() {
  const region = selectedRegion();
  if (!region || !state.current) return;
  pushHistory();
  const x = clamp(Number(els.coordX.value) || 0, 0, state.current.width - 1);
  const y = clamp(Number(els.coordY.value) || 0, 0, state.current.height - 1);
  const width = clamp(Number(els.coordW.value) || 1, 1, state.current.width - x);
  const height = clamp(Number(els.coordH.value) || 1, 1, state.current.height - y);
  region.segmentation = rectanglePoints(x, y, width, height);
  region.bbox = [x, y, width, height].map(round);
  setDirty(true);
  renderRegions();
  els.regionDetails.textContent = `category_id ${LABELS[region.label].id} · area ${Math.round(width * height)} px²`;
}

function deleteSelected() {
  if (!state.selectedId) return;
  const index = state.regions.findIndex((region) => region.id === state.selectedId);
  if (index < 0) return;
  pushHistory();
  state.regions.splice(index, 1);
  state.selectedId = state.regions[Math.min(index, state.regions.length - 1)]?.id || null;
  setDirty(true);
  renderAll();
}

function completenessIssues() {
  if (!state.current) return [];
  const issues = [];
  const documentLabels = ["SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST"];
  const itemLabels = ["ITEM_NAME", "QUANTITY", "UNIT_PRICE", "LINE_TOTAL"];
  const presentDocument = new Set(state.regions.filter((region) => documentLabels.includes(region.label)).map((region) => region.label));
  if (state.mode === "val") {
    documentLabels.forEach((label) => {
      if (!presentDocument.has(label) && !state.missingFields.has(label)) issues.push(`thiếu ${label}`);
      if (presentDocument.has(label) && state.missingFields.has(label)) issues.push(`${label} bị khai báo mâu thuẫn`);
    });
  }
  const itemIds = new Set(
    state.regions
      .filter((region) => itemLabels.includes(region.label) && positiveInteger(region.line_item_id, 0) > 0)
      .map((region) => Number(region.line_item_id)),
  );
  state.missingFields.forEach((key) => {
    const match = /^(ITEM_NAME|QUANTITY|UNIT_PRICE|LINE_TOTAL):(\d+)$/.exec(key);
    if (match) itemIds.add(Number(match[2]));
  });
  if (!itemIds.size) issues.push("chưa có dòng mặt hàng");
  [...itemIds].sort((a, b) => a - b).forEach((itemId) => {
    itemLabels.forEach((label) => {
      const present = state.regions.some((region) => region.label === label && Number(region.line_item_id) === itemId);
      const absent = state.missingFields.has(`${label}:${itemId}`);
      if (!present && !absent) issues.push(`dòng ${itemId} thiếu ${label}`);
      if (present && absent) issues.push(`dòng ${itemId} ${label} bị khai báo mâu thuẫn`);
    });
  });
  return issues;
}

function validateCurrent() {
  els.save.disabled = true;
  els.saveAndNext.disabled = true;
  els.markChecked.disabled = true;
  els.flagImage.disabled = !state.current;
  els.confirmRotation.disabled = !state.current;
  els.flagImage.textContent = state.current?.flagged ? "Bỏ cờ ảnh này" : "🚩 Gắn cờ ảnh khó đọc";
  els.flagImage.classList.toggle("active", Boolean(state.current?.flagged));
  els.validation.className = "validation-message";
  const navigationImages = filteredImages();
  const currentIndex = state.current ? navigationImages.findIndex((image) => image.img_id === state.current.img_id) : -1;
  els.previousImage.disabled = !state.current || !navigationImages.length || currentIndex === 0;
  els.nextImage.disabled = !state.current || !navigationImages.length || currentIndex === navigationImages.length - 1;
  if (!state.current) {
    els.validation.textContent = "Hãy chọn một ảnh.";
    return false;
  }
  const emptyIndex = state.regions.findIndex((region) => !region.text?.trim());
  if (emptyIndex >= 0) {
    els.validation.textContent = `Vùng #${emptyIndex + 1} chưa có nội dung chữ.`;
    els.validation.classList.add("error");
    return false;
  }
  const missingLineItemIndex = state.regions.findIndex((region) => {
    const itemId = Number(region.line_item_id);
    return isLineItemLabel(region.label) && (!Number.isInteger(itemId) || itemId < 1);
  });
  if (missingLineItemIndex >= 0) {
    els.validation.textContent = `Vùng #${missingLineItemIndex + 1} thiếu line_item_id hợp lệ.`;
    els.validation.classList.add("error");
    return false;
  }
  const issues = completenessIssues();
  const orientationPending = !state.current.rotation_confirmed;
  if (issues.length) {
    els.validation.textContent = `Chưa đủ nhãn: ${issues.slice(0, 3).join("; ")}${issues.length > 3 ? `; và ${issues.length - 3} lỗi khác` : ""}`;
    els.validation.classList.add("error");
  } else if (orientationPending) {
    els.validation.textContent = `${state.regions.length} vùng hợp lệ · hãy xác nhận chiều đọc trước khi hoàn tất`;
  } else {
    els.validation.textContent = `${state.regions.length} vùng hợp lệ · anno_image_quality được giữ nguyên`;
    els.validation.classList.add("ok");
  }
  els.save.disabled = false;
  els.saveAndNext.disabled = false;
  els.markChecked.disabled = orientationPending || issues.length > 0;
  return true;
}

async function saveAnnotation() {
  if (!validateCurrent()) return false;
  try {
    const payload = await api("/api/annotation", {
      method: "PUT",
      body: JSON.stringify({
        mode: state.mode,
        img_id: state.current.img_id,
        width: state.current.width,
        height: state.current.height,
        regions: state.regions,
        missing_fields: [...state.missingFields],
      }),
    });
    setDirty(false);
    clearDraft();
    showToast(`Đã lưu ${payload.anno_num} vùng vào CSV`);
    await loadState(state.current.img_id);
    return true;
  } catch (error) {
    showToast(error.message, true);
    setFailure("Lưu thất bại");
    return false;
  }
}

async function navigateImage(delta, force = true) {
  if (!state.current) return;
  saveDraftNow();
  const navigationImages = filteredImages();
  const index = navigationImages.findIndex((image) => image.img_id === state.current.img_id);
  const next = index < 0
    ? (delta > 0 ? navigationImages[0] : navigationImages[navigationImages.length - 1])
    : navigationImages[index + delta];
  if (next) await selectImage(next, force);
}

async function saveAndNext() {
  if (await saveAnnotation()) await navigateImage(1, true);
}

async function markChecked() {
  if (state.dirty) await saveAnnotation();
  if (state.dirty || !state.current) return;
  if (!state.current.rotation_confirmed) {
    showToast("Hãy xoay ảnh đúng chiều và xác nhận chiều đọc trước", true);
    return;
  }
  const issues = completenessIssues();
  if (issues.length) {
    showToast(`Chưa thể hoàn tất: ${issues[0]}`, true);
    return;
  }
  try {
    await api("/api/workspace/check", {
      method: "POST",
      body: JSON.stringify({ mode: state.mode, img_id: state.current.img_id, checked: true }),
    });
    showToast("Đã đánh dấu ảnh là hoàn tất");
    await loadState(state.current.img_id);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function toggleFlag() {
  if (!state.current) return;
  const flagged = !state.current.flagged;
  try {
    const result = await api("/api/workspace/flag", {
      method: "POST",
      body: JSON.stringify({ mode: state.mode, img_id: state.current.img_id, flagged }),
    });
    state.current.flagged = result.flagged;
    const image = state.images.find((item) => item.img_id === state.current.img_id);
    if (image) image.flagged = result.flagged;
    updateImageMeta();
    renderImageList();
    validateCurrent();
    showToast(result.flagged ? "Đã gắn cờ ảnh khó đọc" : "Đã bỏ cờ ảnh");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function confirmRotation() {
  if (!state.current) return;
  try {
    const result = await api("/api/workspace/rotation", {
      method: "POST",
      body: JSON.stringify({
        mode: state.mode,
        img_id: state.current.img_id,
        rotation_to_upright: state.rotation,
      }),
    });
    state.current.rotation_confirmed = true;
    state.current.rotation_to_upright = result.rotation_to_upright;
    state.rotationCsvPath = result.rotation_csv_path;
    const image = state.images.find((item) => item.img_id === state.current.img_id);
    if (image) {
      image.rotation_confirmed = true;
      image.rotation_to_upright = result.rotation_to_upright;
    }
    updateImageMeta();
    renderRotationControl();
    renderImageList();
    validateCurrent();
    showToast(`Đã lưu chiều đọc ${result.rotation_to_upright}°`);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openWorkspace() {
  const csvPath = els.workspaceCsvPath.value.trim();
  const imageDirectory = els.workspaceImageDir.value.trim();
  if (!csvPath || !imageDirectory) {
    showToast("Hãy nhập đường dẫn CSV và thư mục ảnh", true);
    return;
  }
  try {
    const result = await api("/api/workspace/open", {
      method: "POST",
      body: JSON.stringify({ mode: state.mode, csv_path: csvPath, image_directory: imageDirectory }),
    });
    showToast(`Đã mở ${result.rows} ảnh · lưu trực tiếp vào CSV`);
    await loadState();
  } catch (error) {
    showToast(error.message, true);
  }
}

function applyModeUi(mode) {
  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  els.exportCsv.href = `/api/export?mode=${mode}`;
  els.listTitle.textContent = `Ảnh ${mode === "train" ? "train" : "validation"}`;
  els.statusFilter.options[1].textContent = "Chưa hoàn tất";
  els.statusFilter.options[2].textContent = "Đã hoàn tất";
  els.markChecked.textContent = "Đánh dấu hoàn tất";
  els.flagImage.classList.remove("hidden");
  els.rotationPanel.classList.remove("hidden");
  els.flagFilterOption.hidden = false;
  els.flagFilterOption.disabled = false;
  els.rotationFilterOption.hidden = false;
  els.rotationFilterOption.disabled = false;
  els.openWorkspace.textContent = `Mở ${mode === "train" ? "Train" : "Validation"}`;
  els.workspaceHint.textContent = mode === "train"
    ? "CSV rỗng sẽ tạo dòng cho từng ảnh. Có thể sửa, xóa và bổ sung mọi nhãn trong CSV train."
    : "Gán đủ nhãn hóa đơn và mặt hàng; dữ liệu ghi trực tiếp vào CSV validation.";
  updateCategoryAvailability();
  setCategory(mode === "train" ? "ITEM_NAME" : "SELLER", false);
  els.currentName.textContent = "Mở CSV và thư mục ảnh để bắt đầu";
  renderRotationControl();
}

async function switchMode(mode) {
  if (mode === state.mode) return;
  if (state.dirty) saveDraftNow();
  state.mode = mode;
  state.loadRequestId += 1;
  state.images = [];
  state.csvPath = "";
  state.rotationCsvPath = "";
  state.missingFieldsPath = "";
  state.current = null;
  state.regions = [];
  state.missingFields = new Set();
  state.undoStack = [];
  state.redoStack = [];
  state.selectedId = null;
  state.rotation = 0;
  setDirty(false);
  els.csvPath.textContent = "Chưa có phiên CSV đang hoạt động.";
  els.workspaceCsvPath.value = "";
  els.workspaceImageDir.value = "";
  applyModeUi(mode);
  els.emptyStage.classList.remove("hidden");
  els.viewport.classList.add("hidden");
  renderAll();
  await loadState();
}

els.svg.addEventListener("pointerdown", (event) => {
  if (!state.current || event.button !== 0) return;
  event.preventDefault();
  els.svg.setPointerCapture(event.pointerId);
  const point = svgPoint(event);
  const displayPoint = framePoint(event);
  const regionId = event.target.dataset?.regionId;
  if (regionId) {
    selectRegion(regionId);
    pushHistory();
    state.pointer = {
      type: "move",
      start: point,
      original: [...selectedRegion().segmentation],
      moved: false,
      historyPushed: true,
    };
    return;
  }
  pushHistory();
  state.selectedId = null;
  state.pointer = {
    type: "draw",
    start: point,
    current: point,
    startDisplay: displayPoint,
    currentDisplay: displayPoint,
    historyPushed: true,
  };
  els.draftRect.setAttribute("points", `${point.x},${point.y} ${point.x},${point.y} ${point.x},${point.y} ${point.x},${point.y}`);
  els.draftRect.setAttribute("visibility", "visible");
  renderInspector();
});

els.viewport.addEventListener("wheel", (event) => {
  if (!state.current || !event.ctrlKey) return;
  event.preventDefault();
  const factor = Math.exp(-event.deltaY * .002);
  zoomAt(state.zoom * factor, event.clientX, event.clientY);
}, { passive: false });

els.viewport.addEventListener("contextmenu", (event) => {
  if (state.current) event.preventDefault();
});

els.viewport.addEventListener("pointerdown", (event) => {
  if (!state.current || event.button !== 2) return;
  event.preventDefault();
  els.viewport.setPointerCapture(event.pointerId);
  state.pan = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: els.viewport.scrollLeft,
    scrollTop: els.viewport.scrollTop,
  };
  els.viewport.classList.add("is-panning");
});

els.viewport.addEventListener("pointermove", (event) => {
  if (!state.pan || state.pan.pointerId !== event.pointerId) return;
  event.preventDefault();
  els.viewport.scrollLeft = state.pan.scrollLeft - (event.clientX - state.pan.startX);
  els.viewport.scrollTop = state.pan.scrollTop - (event.clientY - state.pan.startY);
});

function stopPanning(event) {
  if (!state.pan || (event.pointerId != null && state.pan.pointerId !== event.pointerId)) return;
  state.pan = null;
  els.viewport.classList.remove("is-panning");
}

els.viewport.addEventListener("pointerup", stopPanning);
els.viewport.addEventListener("pointercancel", stopPanning);
els.viewport.addEventListener("lostpointercapture", stopPanning);

els.svg.addEventListener("pointermove", (event) => {
  if (!state.pointer || !state.current) return;
  const point = svgPoint(event);
  if (state.pointer.type === "draw") {
    state.pointer.current = point;
    state.pointer.currentDisplay = framePoint(event);
    const points = displayRectanglePoints(state.pointer.startDisplay, state.pointer.currentDisplay);
    const pairs = [];
    for (let i = 0; i < points.length; i += 2) pairs.push(`${points[i]},${points[i + 1]}`);
    els.draftRect.setAttribute("points", pairs.join(" "));
    return;
  }
  if (state.pointer.type === "move") {
    const dxRaw = point.x - state.pointer.start.x;
    const dyRaw = point.y - state.pointer.start.y;
    const original = state.pointer.original;
    const box = bboxFromPoints(original);
    const dx = clamp(dxRaw, -box[0], state.current.width - (box[0] + box[2]));
    const dy = clamp(dyRaw, -box[1], state.current.height - (box[1] + box[3]));
    const region = selectedRegion();
    region.segmentation = original.map((value, index) => round(value + (index % 2 === 0 ? dx : dy)));
    state.pointer.moved = Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5;
    renderRegions();
  }
});

els.svg.addEventListener("pointerup", (event) => {
  if (!state.pointer || !state.current) return;
  const pointer = state.pointer;
  state.pointer = null;
  els.draftRect.setAttribute("visibility", "hidden");
  if (pointer.type === "move") {
    if (pointer.moved) setDirty(true);
    else if (pointer.historyPushed) state.undoStack.pop();
    refreshHistoryButtons();
    renderAll();
    return;
  }
  const endDisplay = framePoint(event);
  const displayWidth = Math.abs(endDisplay.x - pointer.startDisplay.x);
  const displayHeight = Math.abs(endDisplay.y - pointer.startDisplay.y);
  if (displayWidth < 4 || displayHeight < 4) {
    if (pointer.historyPushed) state.undoStack.pop();
    refreshHistoryButtons();
    renderAll();
    return;
  }
  const segmentation = displayRectanglePoints(pointer.startDisplay, endDisplay);
  const bbox = bboxFromPoints(segmentation);
  const region = {
    id: `region-${crypto.randomUUID?.() || Date.now()}`,
    category_id: LABELS[state.category].id,
    label: state.category,
    text: "",
    segmentation,
    bbox,
    line_item_id: isLineItemLabel(state.category) ? state.lineItemId : null,
  };
  state.missingFields.delete(currentMissingFieldKey());
  state.regions.push(region);
  state.selectedId = region.id;
  setDirty(true);
  renderAll();
  els.regionText.focus();
});

els.categoryGrid.addEventListener("click", (event) => {
  const button = event.target.closest(".category");
  if (button) {
    state.selectedId = null;
    setCategory(button.dataset.label, false);
    renderAll();
  }
});

els.regionText.addEventListener("input", () => {
  const region = selectedRegion();
  if (!region) return;
  region.text = els.regionText.value;
  setDirty(true);
  renderRegions();
  renderRegionListOnly();
});
els.regionText.addEventListener("focus", () => {
  if (selectedRegion()) pushHistory();
}, { once: false });

els.lineItemId.addEventListener("change", () => {
  const normalized = positiveInteger(els.lineItemId.value, state.lineItemId);
  state.lineItemId = normalized;
  els.lineItemId.value = normalized;
  const region = selectedRegion();
  if (region && isLineItemLabel(region.label) && region.line_item_id !== normalized) {
    pushHistory();
    region.line_item_id = normalized;
    setDirty(true);
    renderAll();
  } else {
    syncLineItemControl();
  }
});

els.nextLineItem.addEventListener("click", () => {
  const usedIds = state.regions
    .filter((region) => isLineItemLabel(region.label))
    .map((region) => positiveInteger(region.line_item_id, 0));
  state.lineItemId = Math.max(state.lineItemId, 0, ...usedIds) + 1;
  state.selectedId = null;
  setCategory("ITEM_NAME", false);
  renderAll();
});

function renderRegionListOnly() {
  const activeId = state.selectedId;
  els.regionList.querySelectorAll(".region-item").forEach((item, index) => {
    const region = state.regions[index];
    item.classList.toggle("active", region.id === activeId);
    item.querySelector("span").textContent = region.text || "Chưa nhập nội dung";
  });
  validateCurrent();
}

[els.coordX, els.coordY, els.coordW, els.coordH].forEach((input) => input.addEventListener("change", updateSelectedRectangle));
els.deleteRegion.addEventListener("click", deleteSelected);
els.save.addEventListener("click", saveAnnotation);
els.markChecked.addEventListener("click", markChecked);
els.flagImage.addEventListener("click", toggleFlag);
els.confirmRotation.addEventListener("click", confirmRotation);
els.toggleMissingField.addEventListener("click", toggleMissingField);
els.undoAction.addEventListener("click", undoEdit);
els.redoAction.addEventListener("click", redoEdit);
els.previousImage.addEventListener("click", () => navigateImage(-1));
els.nextImage.addEventListener("click", () => navigateImage(1));
els.saveAndNext.addEventListener("click", saveAndNext);
els.openWorkspace.addEventListener("click", openWorkspace);
els.refreshList.addEventListener("click", () => loadState(state.current?.img_id));
els.imageSearch.addEventListener("input", () => { renderImageList(); validateCurrent(); });
els.statusFilter.addEventListener("change", () => { renderImageList(); validateCurrent(); });
els.tabs.forEach((tab) => tab.addEventListener("click", () => switchMode(tab.dataset.mode)));
els.rotateLeft.addEventListener("click", () => rotateView(-90));
els.rotateRight.addEventListener("click", () => rotateView(90));
els.fineRotateLeft.addEventListener("click", () => rotateView(-1));
els.fineRotateRight.addEventListener("click", () => rotateView(1));
els.rotationAngle.addEventListener("change", setRotationFromInput);
els.rotationAngle.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    setRotationFromInput();
    els.rotationAngle.blur();
  }
});
els.zoomIn.addEventListener("click", () => zoomAt(state.zoom * 1.2));
els.zoomOut.addEventListener("click", () => zoomAt(state.zoom / 1.2));
els.fitImage.addEventListener("click", fitImage);
els.toggleLabels.addEventListener("click", toggleRegionLabels);

window.addEventListener("keydown", (event) => {
  const editingText = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  if (!editingText && event.key.toLowerCase() === "h") {
    event.preventDefault();
    toggleRegionLabels();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && !editingText && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redoEdit(); else undoEdit();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && !editingText && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redoEdit();
    return;
  }
  if (event.altKey && event.key === "ArrowLeft") {
    event.preventDefault();
    navigateImage(-1);
    return;
  }
  if (event.altKey && event.key === "ArrowRight") {
    event.preventDefault();
    navigateImage(1);
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    if (event.shiftKey) saveAndNext(); else saveAnnotation();
    return;
  }
  if (event.key === "Delete" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) deleteSelected();
});

window.addEventListener("beforeunload", (event) => {
  if (state.dirty) saveDraftNow();
});

window.addEventListener("resize", () => {
  if (state.current && state.zoom === 1) fitImage();
});

ensureInitialState();
async function ensureInitialState() {
  applyModeUi(state.mode);
  await loadState();
}
