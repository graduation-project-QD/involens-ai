# MC-OCR Label Studio

Local annotation tool for creating and reviewing MC-OCR-compatible CSV files.

Supported labels:

- Document fields: `SELLER`, `ADDRESS`, `TIMESTAMP`, `TOTAL_COST`
- Line-item fields: `ITEM_NAME`, `QUANTITY`, `UNIT_PRICE`, `LINE_TOTAL`

Line-item regions require a positive `line_item_id`. Regions belonging to the same receipt row use the same ID. The UI stores these IDs in the `anno_line_item_ids` JSON-array column; document-level fields use `null`. Legacy six-column MC-OCR CSV files remain importable and are upgraded to the extended seven-column schema when saved.

## Run

From PowerShell:

```powershell
cd D:\graduation-project-2\apps\mcocr-labeler
.\run.ps1
```

Then open <http://127.0.0.1:8765>.

The first run finds an available Python 3.11+ runtime, creates a local virtual environment and installs Pillow. It accepts the project's cached Python environment, a `python` command, or Python Launcher versions 3.11–3.13. If the project environment already has Pillow, the server can also be started directly:

```powershell
python server.py
```

## Persistence

- Train and validation modes write directly to the selected CSV path.
- Active train/validation paths and completion status: `data/annotation_workspaces.json`
- Hard-to-read image flags: `<csv-name>.flagged.json`, stored beside the selected train/validation CSV
- Confirmed reading orientation: `mcocr_train_rotation.csv` or `mcocr_val_rotation.csv`, stored beside the selected annotation CSV
- Fields explicitly absent from a receipt: `<csv-name>.missing_fields.json`, stored beside the selected annotation CSV
- Unsaved per-image drafts: browser local storage; restored automatically after refresh or reopening the app
- Review sessions: `data/review_sessions/`
- Automatic CSV backups: `data/backups/`

Stopping the localhost server does not delete these files. The `data/` directory is ignored by Git because it can contain working state and backups.

The app refuses to open a direct workspace unless the CSV `img_id` values and image filenames match exactly. Saving updates the existing `img_id` row and creates a backup before replacing the CSV. Existing `anno_image_quality` values are preserved.

## Assigned train/validation workflow

Use **Đánh nhãn Train** or **Đánh nhãn Validation** for a pre-created assignment:

1. Enter the full path to the member's `mcocr_train_df.csv` or `mcocr_val_df.csv`.
2. Enter the full path to the matching `train_images` or `val_images` directory.
3. Open the workspace, annotate each image, and save. Each save writes directly to the selected CSV.
4. Rotate the browser view until the receipt is upright, then select **Xác nhận chiều đọc**. The saved value is clockwise `0`, `90`, `180`, or `270`.
5. Mark an image complete to track progress. Completion requires a confirmed reading orientation. Downloading the annotation CSV remains available as an optional copy.

Before completion, Validation requires `SELLER`, `ADDRESS`, `TIMESTAMP`, and `TOTAL_COST`. Every `line_item_id` in Train and Validation requires `ITEM_NAME`, `QUANTITY`, `UNIT_PRICE`, and `LINE_TOTAL`. If a field is genuinely not printed, select its category and line item, then use **Trường này không xuất hiện** instead of drawing a fake region.

In Train mode, existing `SELLER`, `ADDRESS`, `TIMESTAMP`, and `TOTAL_COST` regions are locked and preserved by the server. Annotators add only the four line-item fields. Validation mode allows all eight labels.

Use **Gắn cờ ảnh khó đọc** when blur or other degradation makes a reliable annotation impossible. The flag does not alter the annotation CSV and does not automatically mark the image complete. Use the **Ảnh khó đọc** filter to review these images later; the sidecar JSON can also be used to exclude or adjudicate them before training.

The left/right rotate controls change only the browser view in 90-degree steps. The source image is never rewritten. Drawing and moving regions on a rotated view are inverse-mapped to the original image coordinate system, so CSV `segmentation`, `bbox`, `width`, and `height` always remain aligned with the original file.

**Xác nhận chiều đọc** stores the current browser angle in the separate rotation metadata CSV. A confirmed `0` is distinct from an image that has not been checked. This metadata is intended for a later preprocessing script that rotates image files and transforms all annotation coordinates together.

The editor keeps up to 50 Undo/Redo states per open image. Unsaved work is also debounced into browser local storage and restored automatically; a successful CSV save removes that draft. Navigation supports **Ảnh trước**, **Ảnh tiếp**, and **Lưu và sang ảnh tiếp theo**. Shortcuts: `Ctrl+Z`, `Ctrl+Y`, `Ctrl+S`, `Ctrl+Shift+S`, `Alt+Left`, and `Alt+Right`. Use the **Chưa xác nhận chiều đọc** filter to audit orientation metadata before finishing an assignment.

For one product row, choose its `line_item_id`, then draw `ITEM_NAME`, `QUANTITY`, `UNIT_PRICE`, and `LINE_TOTAL`. Use **Dòng kế tiếp** before starting the next product row.

**Kiểm tra nhãn LLM** keeps its imported CSV in a separate review session and never overwrites the uploaded source file.
