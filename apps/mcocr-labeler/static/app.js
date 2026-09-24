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
  savedImages: new Set(),
  zoom: 1,
  baseScale: 1,
  rotation: 0,
  rotationsByImage: new Map(),
  pointer: null,
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
  reviewImport: $("#reviewImport"),
  workspaceCsvPath: $("#workspaceCsvPath"),
  workspaceImageDir: $("#workspaceImageDir"),
  openWorkspace: $("#openWorkspace"),
  workspaceHint: $("#workspaceHint"),
  reviewCsv: $("#reviewCsv"),
  reviewImageDir: $("#reviewImageDir"),
  importReview: $("#importReview"),
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
  rotationLabel: $("#rotationLabel"),
  undoAction: $("#undoAction"),
  redoAction: $("#redoAction"),
  rotationPanel: $("#rotationPanel"),
  rotationStatus: $("#rotationStatus"),
  rotationPath: $("#rotationPath"),
  confirmRotation: $("#confirmRotation"),
  fitImage: $("#fitImage"),
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
  if (value) {
    if (state.current) state.savedImages.delete(savedImageKey(state.current.img_id));
    scheduleDraftSave();
  }
  renderImageList();
  validateCurrent();
}

function savedImageKey(imgId) {
  return `${state.mode}:${state.csvPath}:${imgId}`;
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
    if (state.mode !== "review") {
      els.workspaceCsvPath.value = payload.workspace?.csv_path || els.workspaceCsvPath.value;
      els.workspaceImageDir.value = payload.workspace?.image_directory || els.workspaceImageDir.value;
    }
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
    const statusClass = image.missing_image ? "missing" : image.flagged ? "flagged" : image.checked ? "checked" : !hasUnsavedChanges && state.savedImages.has(savedImageKey(image.img_id)) ? "saved" : "";
    const statusTitle = image.missing_image
      ? "Thiếu ảnh"
      : image.flagged
        ? "Ảnh khó đọc đã được gắn cờ"
      : image.checked
        ? (state.mode === "review" ? "Đã kiểm tra" : "Đã hoàn tất")
      : statusClass === "saved"
        ? "Đã lưu vào CSV"
        : (state.mode === "review" ? "Chưa kiểm tra" : "Chưa hoàn tất");
    button.innerHTML = `
      <span class="image-number">${String(index + 1).padStart(3, "0")}</span>
      <span class="image-copy">
        <span class="image-name" title="${escapeHtml(image.img_id)}">${escapeHtml(image.img_id)}</span>
        <span class="image-size">${image.width || "?"} × ${image.height || "?"} · ${image.anno_num || 0} vùng${state.mode === "review" ? "" : image.rotation_confirmed ? ` · hướng ${image.rotation_to_upright}°` : " · chưa xác nhận hướng"}</span>
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
    const firstEditableRegion = state.regions.find((region) => !region.locked);
    state.selectedId = (firstEditableRegion || state.regions[0])?.id || null;
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
        ? (firstEditableRegion?.label || "ITEM_NAME")
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
  const quarterTurn = state.rotation % 180 !== 0;
  const orientedWidth = quarterTurn ? state.current.height : state.current.width;
  const orientedHeight = quarterTurn ? state.current.width : state.current.height;
  state.baseScale = Math.min(availableWidth / orientedWidth, availableHeight / orientedHeight, 1);
  state.zoom = 1;
  applyZoom();
}

function applyZoom() {
  if (!state.current) return;
  const scale = state.baseScale * state.zoom;
  const width = Math.round(state.current.width * scale);
  const height = Math.round(state.current.height * scale);
  const quarterTurn = state.rotation % 180 !== 0;
  els.frame.style.width = `${quarterTurn ? height : width}px`;
  els.frame.style.height = `${quarterTurn ? width : height}px`;
  els.surface.style.width = `${width}px`;
  els.surface.style.height = `${height}px`;
  els.image.style.width = `${width}px`;
  els.image.style.height = `${height}px`;
  els.svg.style.width = `${width}px`;
  els.svg.style.height = `${height}px`;
  if (state.rotation === 90) els.surface.style.transform = `translate(${height}px, 0) rotate(90deg)`;
  else if (state.rotation === 180) els.surface.style.transform = `translate(${width}px, ${height}px) rotate(180deg)`;
  else if (state.rotation === 270) els.surface.style.transform = `translate(0, ${width}px) rotate(-90deg)`;
  else els.surface.style.transform = "none";
  els.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  els.rotationLabel.textContent = `${state.rotation}°`;
  renderRotationControl();
}

function updateImageMeta() {
  if (!state.current) return;
  const orientation = state.mode === "review"
    ? ""
    : state.current.rotation_confirmed
      ? ` · hướng: ${state.current.rotation_to_upright}° đã xác nhận`
      : " · hướng: chưa xác nhận";
  els.imageMeta.textContent = `${state.current.width} × ${state.current.height} px · ${state.regions.length} vùng · quality: ${state.current.anno_image_quality || "trống"}${orientation}${state.current.flagged ? " · 🚩 ảnh khó đọc" : ""}`;
}

function renderRotationControl() {
  const available = Boolean(state.current) && state.mode !== "review";
  els.rotationPanel.classList.toggle("hidden", state.mode === "review");
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

function svgPoint(event) {
  const bounds = els.frame.getBoundingClientRect();
  const renderedWidth = Number.parseFloat(els.surface.style.width) || state.current.width;
  const renderedHeight = Number.parseFloat(els.surface.style.height) || state.current.height;
  const scaleX = renderedWidth / state.current.width;
  const scaleY = renderedHeight / state.current.height;
  const displayX = clamp(event.clientX - bounds.left, 0, bounds.width);
  const displayY = clamp(event.clientY - bounds.top, 0, bounds.height);
  let x;
  let y;
  if (state.rotation === 90) {
    x = displayY / scaleX;
    y = state.current.height - displayX / scaleY;
  } else if (state.rotation === 180) {
    x = state.current.width - displayX / scaleX;
    y = state.current.height - displayY / scaleY;
  } else if (state.rotation === 270) {
    x = state.current.width - displayY / scaleX;
    y = displayX / scaleY;
  } else {
    x = displayX / scaleX;
    y = displayY / scaleY;
  }
  return {
    x: clamp(x, 0, state.current.width),
    y: clamp(y, 0, state.current.height),
  };
}

function rotateView(delta) {
  if (!state.current) return;
  state.rotation = (state.rotation + delta + 360) % 360;
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
  state.regions.forEach((region, index) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
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
    const labelWidth = Math.max(68, labelText.length * 8.2);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", x);
    rect.setAttribute("y", Math.max(0, y - 22));
    rect.setAttribute("width", labelWidth);
    rect.setAttribute("height", 22);
    rect.setAttribute("fill", regionColor(region));
    rect.setAttribute("class", "region-label-bg");
    rect.setAttribute("pointer-events", "none");
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", x + 5);
    text.setAttribute("y", Math.max(14, y - 6));
    text.setAttribute("class", "region-label");
    text.textContent = labelText;
    group.append(polygon, rect, text);
    els.regionLayer.appendChild(group);
  });
}

function selectedRegion() { return state.regions.find((region) => region.id === state.selectedId) || null; }

function selectRegion(id) {
  state.selectedId = id;
  const region = selectedRegion();
  if (region && !region.locked) setCategory(region.label, false);
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
  const unavailable = !state.current || state.mode === "review"
    || (state.mode === "train" && state.regions.some((region) => region.locked && region.label === state.category));
  els.toggleMissingField.classList.toggle("hidden", state.mode === "review");
  els.missingFieldHint.classList.toggle("hidden", state.mode === "review");
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
  if (!state.current || state.mode === "review") return;
  const key = currentMissingFieldKey();
  pushHistory();
  if (state.missingFields.has(key)) state.missingFields.delete(key);
  else state.missingFields.add(key);
  setDirty(true);
  renderAll();
}

function updateCategoryAvailability() {
  [...els.categoryGrid.querySelectorAll(".category")].forEach((button) => {
    button.disabled = state.mode === "train" && state.regions.some(
      (region) => region.locked && region.label === button.dataset.label,
    );
  });
}

function renderInspector() {
  const region = selectedRegion();
  const controls = [els.regionText, els.coordX, els.coordY, els.coordW, els.coordH, els.deleteRegion];
  controls.forEach((control) => { control.disabled = !region || Boolean(region?.locked); });
  els.regionCount.textContent = state.regions.length;
  els.regionList.innerHTML = "";
  state.regions.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `region-item${item.id === state.selectedId ? " active" : ""}`;
    row.innerHTML = `
      <i class="region-color" style="background:${regionColor(item)}"></i>
      <div><strong>${escapeHtml(item.label)}${isLineItemLabel(item.label) ? ` · dòng #${item.line_item_id ?? "?"}` : ""}${item.locked ? " · khóa" : ""}</strong><span>${escapeHtml(item.text || "Chưa nhập nội dung")}</span></div>
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
  const lockNote = region.locked ? " · nhãn train gốc được khóa" : "";
  els.regionDetails.textContent = `category_id ${LABELS[region.label].id} · area ${Math.round(width * height)} px²${lockNote}`;
}

function setCategory(label, updateRegion = true) {
  if (!LABELS[label]) return;
  state.category = label;
  els.categoryIdBadge.textContent = `ID ${LABELS[label].id}`;
  [...els.categoryGrid.querySelectorAll(".category")].forEach((button) => {
    button.classList.toggle("active", button.dataset.label === label);
  });
  const region = selectedRegion();
  if (updateRegion && region?.locked) {
    state.selectedId = null;
    syncLineItemControl();
    renderAll();
    return;
  }
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
  if (!region || region.locked || !state.current) return;
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
  if (!state.selectedId || selectedRegion()?.locked) return;
  const index = state.regions.findIndex((region) => region.id === state.selectedId);
  if (index < 0) return;
  pushHistory();
  state.regions.splice(index, 1);
  state.selectedId = state.regions[Math.min(index, state.regions.length - 1)]?.id || null;
  setDirty(true);
  renderAll();
}

function completenessIssues() {
  if (!state.current || state.mode === "review") return [];
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
  els.flagImage.disabled = !state.current || state.mode === "review";
  els.confirmRotation.disabled = !state.current || state.mode === "review";
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
  const orientationPending = state.mode !== "review" && !state.current.rotation_confirmed;
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
    state.savedImages.add(savedImageKey(state.current.img_id));
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
  if (state.mode !== "review" && !state.current.rotation_confirmed) {
    showToast("Hãy xoay ảnh đúng chiều và xác nhận chiều đọc trước", true);
    return;
  }
  const issues = completenessIssues();
  if (issues.length) {
    showToast(`Chưa thể hoàn tất: ${issues[0]}`, true);
    return;
  }
  try {
    const endpoint = state.mode === "review" ? "/api/review/check" : "/api/workspace/check";
    await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ mode: state.mode, img_id: state.current.img_id, checked: true }),
    });
    showToast(state.mode === "review" ? "Đã đánh dấu ảnh là đã kiểm tra" : "Đã đánh dấu ảnh là hoàn tất");
    await loadState(state.current.img_id);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function toggleFlag() {
  if (!state.current || state.mode === "review") return;
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
  if (!state.current || state.mode === "review") return;
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

async function importReview() {
  const file = els.reviewCsv.files[0];
  if (!file) {
    showToast("Hãy chọn file CSV cần kiểm tra", true);
    return;
  }
  try {
    const result = await api("/api/review/import", {
      method: "POST",
      body: JSON.stringify({
        name: file.name,
        csv_text: await file.text(),
        source_directory: els.reviewImageDir.value.trim(),
      }),
    });
    showToast(`Đã nhập ${result.rows} dòng · thiếu ${result.missing_images} ảnh`);
    await loadState();
  } catch (error) {
    showToast(error.message, true);
  }
}

function applyModeUi(mode) {
  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  els.workspaceImport.classList.toggle("hidden", mode === "review");
  els.reviewImport.classList.toggle("hidden", mode !== "review");
  els.exportCsv.href = `/api/export?mode=${mode}`;
  els.listTitle.textContent = mode === "review" ? "Ảnh cần kiểm tra" : `Ảnh ${mode === "train" ? "train" : "validation"}`;
  els.statusFilter.options[1].textContent = mode === "review" ? "Chưa kiểm tra" : "Chưa hoàn tất";
  els.statusFilter.options[2].textContent = mode === "review" ? "Đã kiểm tra" : "Đã hoàn tất";
  els.markChecked.textContent = mode === "review" ? "Đánh dấu đã kiểm tra" : "Đánh dấu hoàn tất";
  els.flagImage.classList.toggle("hidden", mode === "review");
  els.rotationPanel.classList.toggle("hidden", mode === "review");
  els.flagFilterOption.hidden = mode === "review";
  els.flagFilterOption.disabled = mode === "review";
  els.rotationFilterOption.hidden = mode === "review";
  els.rotationFilterOption.disabled = mode === "review";
  if (mode === "review" && ["flagged", "rotation_pending"].includes(els.statusFilter.value)) els.statusFilter.value = "all";
  els.openWorkspace.textContent = `Mở phiên đánh nhãn ${mode === "train" ? "Train" : "Validation"}`;
  els.workspaceHint.textContent = mode === "train"
    ? "CSV rỗng sẽ tạo dòng cho từng ảnh. Nhãn hóa đơn đã có được khóa; các nhãn còn thiếu có thể gán mới."
    : "Gán đủ nhãn hóa đơn và mặt hàng; dữ liệu ghi trực tiếp vào CSV validation.";
  updateCategoryAvailability();
  setCategory(mode === "train" ? "ITEM_NAME" : "SELLER", false);
  els.currentName.textContent = mode === "review" ? "Nhập CSV hoặc chọn ảnh cần kiểm tra" : "Mở CSV và thư mục ảnh để bắt đầu";
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
  const regionId = event.target.dataset?.regionId;
  if (regionId) {
    selectRegion(regionId);
    if (selectedRegion()?.locked) return;
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
  state.pointer = { type: "draw", start: point, current: point, historyPushed: true };
  els.draftRect.setAttribute("x", point.x);
  els.draftRect.setAttribute("y", point.y);
  els.draftRect.setAttribute("width", 0);
  els.draftRect.setAttribute("height", 0);
  els.draftRect.setAttribute("visibility", "visible");
  renderInspector();
});

els.svg.addEventListener("pointermove", (event) => {
  if (!state.pointer || !state.current) return;
  const point = svgPoint(event);
  if (state.pointer.type === "draw") {
    state.pointer.current = point;
    const x = Math.min(state.pointer.start.x, point.x);
    const y = Math.min(state.pointer.start.y, point.y);
    els.draftRect.setAttribute("x", x);
    els.draftRect.setAttribute("y", y);
    els.draftRect.setAttribute("width", Math.abs(point.x - state.pointer.start.x));
    els.draftRect.setAttribute("height", Math.abs(point.y - state.pointer.start.y));
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
  const end = svgPoint(event);
  const x = Math.min(pointer.start.x, end.x);
  const y = Math.min(pointer.start.y, end.y);
  const width = Math.abs(end.x - pointer.start.x);
  const height = Math.abs(end.y - pointer.start.y);
  if (width < 4 || height < 4) {
    if (pointer.historyPushed) state.undoStack.pop();
    refreshHistoryButtons();
    renderAll();
    return;
  }
  const region = {
    id: `region-${crypto.randomUUID?.() || Date.now()}`,
    category_id: LABELS[state.category].id,
    label: state.category,
    text: "",
    segmentation: rectanglePoints(x, y, width, height),
    bbox: [round(x), round(y), round(width), round(height)],
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
  if (!region || region.locked) return;
  region.text = els.regionText.value;
  setDirty(true);
  renderRegions();
  renderRegionListOnly();
});
els.regionText.addEventListener("focus", () => {
  if (selectedRegion() && !selectedRegion().locked) pushHistory();
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
els.importReview.addEventListener("click", importReview);
els.refreshList.addEventListener("click", () => loadState(state.current?.img_id));
els.imageSearch.addEventListener("input", () => { renderImageList(); validateCurrent(); });
els.statusFilter.addEventListener("change", () => { renderImageList(); validateCurrent(); });
els.tabs.forEach((tab) => tab.addEventListener("click", () => switchMode(tab.dataset.mode)));
els.rotateLeft.addEventListener("click", () => rotateView(-90));
els.rotateRight.addEventListener("click", () => rotateView(90));
els.zoomIn.addEventListener("click", () => { state.zoom = Math.min(4, state.zoom * 1.2); applyZoom(); });
els.zoomOut.addEventListener("click", () => { state.zoom = Math.max(.35, state.zoom / 1.2); applyZoom(); });
els.fitImage.addEventListener("click", fitImage);

window.addEventListener("keydown", (event) => {
  const editingText = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
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
