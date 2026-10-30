from __future__ import annotations

import http.server
import json
import threading
import unittest
from types import SimpleNamespace

from invoice_ai.inference.pipeline import PipelineError
from invoice_ai.worker.consumer import ResultPublishError, process_delivery
from invoice_ai.worker.handler import download_image, failure_message, handle_request, image_kind

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class FileServer:
    """Serves fixed bodies on localhost to exercise the real urllib download path."""

    routes: dict[str, bytes] = {}

    def __enter__(self) -> "FileServer":
        routes = self.routes

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                body = routes.get(self.path.split("?")[0])
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


class DownloadTests(unittest.TestCase):
    def test_signatures(self):
        self.assertEqual(image_kind(JPEG), "jpeg")
        self.assertEqual(image_kind(PNG), "png")
        self.assertEqual(image_kind(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertIsNone(image_kind(b"%PDF-1.7"))

    def test_download_success_with_presigned_query(self):
        FileServer.routes = {"/bucket/a.jpg": JPEG}
        with FileServer() as server:
            self.assertEqual(download_image(server.base + "/bucket/a.jpg?X-Amz-Signature=abc"), JPEG)

    def test_http_error_is_retryable_download_failure(self):
        FileServer.routes = {}
        with FileServer() as server, self.assertRaises(PipelineError) as raised:
            download_image(server.base + "/missing.jpg")
        self.assertEqual(raised.exception.code, "IMAGE_DOWNLOAD_FAILED")

    def test_too_large_and_not_an_image(self):
        FileServer.routes = {"/big.jpg": JPEG + b"\x00" * 200, "/doc.pdf": b"%PDF-1.7" + b"\x00" * 50}
        with FileServer() as server:
            with self.assertRaises(PipelineError) as raised:
                download_image(server.base + "/big.jpg", max_bytes=150)
            self.assertEqual(raised.exception.code, "FILE_TOO_LARGE")
            with self.assertRaises(PipelineError) as raised:
                download_image(server.base + "/doc.pdf")
            self.assertEqual(raised.exception.code, "IMAGE_DECODE_FAILED")

    def test_non_http_scheme_is_rejected(self):
        with self.assertRaises(PipelineError) as raised:
            download_image("file:///etc/passwd")
        self.assertEqual(raised.exception.code, "IMAGE_DOWNLOAD_FAILED")


class FakeResult:
    def to_contract(self, document_id: str) -> dict:
        return {"status": 0, "error": None, "data": {"id": document_id, "needs_review": False, "warnings": []}}


class FakePipeline:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def process(self, image_bytes: bytes, img_id: str = "document") -> FakeResult:
        self.calls.append((image_bytes, img_id))
        if self.error:
            raise self.error
        return FakeResult()


REQUEST = SimpleNamespace(id="7d1f0c2e-0000-0000-0000-000000000001", url="http://minio/x.jpg")


class HandleRequestTests(unittest.TestCase):
    def test_success(self):
        pipeline = FakePipeline()
        message = handle_request(REQUEST, pipeline, downloader=lambda url: JPEG)
        self.assertEqual((message["status"], message["data"]["id"]), (0, REQUEST.id))
        self.assertEqual(pipeline.calls, [(JPEG, REQUEST.id)])

    def test_download_failure_is_retryable(self):
        def fail(url: str) -> bytes:
            raise PipelineError("IMAGE_DOWNLOAD_FAILED", "Không tải được ảnh từ MinIO")

        message = handle_request(REQUEST, FakePipeline(), downloader=fail)
        self.assertEqual(message, failure_message(REQUEST.id, "IMAGE_DOWNLOAD_FAILED", "Không tải được ảnh từ MinIO"))
        self.assertTrue(message["error"]["retryable"])

    def test_pipeline_errors_are_not_retryable(self):
        message = handle_request(REQUEST, FakePipeline(PipelineError("NO_TEXT_FOUND", "x")), downloader=lambda url: JPEG)
        self.assertEqual((message["status"], message["error"]["code"], message["error"]["retryable"]), (1, "NO_TEXT_FOUND", False))
        message = handle_request(REQUEST, FakePipeline(RuntimeError("boom")), downloader=lambda url: JPEG)
        self.assertEqual(message["error"]["code"], "PROCESSING_FAILED")

    def test_failure_message_matches_backend_contract(self):
        message = failure_message("abc", "IMAGE_DECODE_FAILED", "m")
        # AiExtractionResultService: status 1 needs error.code + error.message and data.id
        self.assertEqual(set(message), {"status", "error", "data"})
        self.assertEqual(message["data"], {"id": "abc"})
        self.assertTrue(message["error"]["code"] and message["error"]["message"])


class FakeChannel:
    def __init__(self) -> None:
        self.acked: list[int] = []

    def basic_ack(self, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)


class ProcessDeliveryTests(unittest.TestCase):
    def body(self, payload: dict) -> bytes:
        return json.dumps(payload).encode("utf-8")

    def test_result_published_then_acked(self):
        channel, published = FakeChannel(), []
        handle = lambda request: {"status": 0, "data": {"id": request.id}}
        process_delivery(channel, 5, self.body({"id": "d1", "url": "http://x"}), handle, published.append)
        self.assertEqual(json.loads(published[0])["data"]["id"], "d1")
        self.assertEqual(channel.acked, [5])

    def test_unreadable_request_acked_without_result(self):
        for body in (b"not json", self.body({"id": "d1"}), self.body({"url": "http://x"}), b"\xff\xfe"):
            channel, published = FakeChannel(), []
            process_delivery(channel, 1, body, lambda r: {"status": 0}, published.append)
            self.assertEqual((channel.acked, published), ([1], []))

    def test_publish_failure_leaves_request_unacked(self):
        def broken(message: str) -> None:
            raise ConnectionError("closed")

        channel = FakeChannel()
        with self.assertRaises(ResultPublishError):
            process_delivery(channel, 9, self.body({"id": "d1", "url": "http://x"}), lambda r: {"status": 0}, broken)
        self.assertEqual(channel.acked, [])


if __name__ == "__main__":
    unittest.main()
