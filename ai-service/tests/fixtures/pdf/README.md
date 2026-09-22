# T09 synthetic PDF fixtures

These PDFs contain synthetic invoice-like text only and are safe to keep in Git.

| File | Expected T09 result |
|---|---|
| `valid_one_page.pdf` | PASS; render at 200 DPI, then T07 preprocessing |
| `two_pages.pdf` | `PDF_PAGE_COUNT_UNSUPPORTED` |
| `encrypted.pdf` | `PDF_ENCRYPTED` |
| `corrupt.pdf` | `PDF_DECODE_ERROR` |
| `pixel_bomb.pdf` | `PIXEL_LIMIT_EXCEEDED` before rasterization |

The visual fixture was rendered with both PDFium and Poppler during T09 QA. PDF text extraction is not used by the intake implementation.

