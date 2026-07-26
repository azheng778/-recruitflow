from __future__ import annotations

from io import BytesIO
from decimal import Decimal

import pytest
from PIL import Image
import fitz

from app.ocr import AliyunAdvancedOcrClient, OcrPageResult
from app.services import BusinessError, _prepare_image_for_ocr, extract_resume_document
from app.services_error import OcrServiceError


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_aliyun_response_parsing_supports_primary_and_compatible_shapes():
    result = AliyunAdvancedOcrClient._parse_response(
        {"prism_wordsInfo": [{"word": "姓名：虚构测试", "prob": 98}, {"word": "Python", "prob": 0.96}]}
    )
    assert result.text == "姓名：虚构测试\nPython"
    assert result.confidence == pytest.approx(0.97)
    assert AliyunAdvancedOcrClient._parse_response({"content": "兼容文本"}).text == "兼容文本"
    assert AliyunAdvancedOcrClient._parse_response({"ret": [{"word": "兼容行"}]}).text == "兼容行"


def test_prepare_image_rejects_corrupted_payload():
    with pytest.raises(BusinessError) as error:
        _prepare_image_for_ocr(b"not-an-image")
    assert error.value.code == "INVALID_IMAGE"


def test_image_resume_uses_mocked_ocr_and_records_metadata(tmp_path, monkeypatch):
    target = tmp_path / "resume.png"
    target.write_bytes(image_bytes())

    class StubClient:
        def recognize_image(self, payload: bytes):
            assert payload
            return OcrPageResult(
                text="姓名：虚构候选人\n手机号：13800001111\n熟悉 Python、FastAPI、MySQL，拥有 5 年工作经验。" * 3,
                confidence=0.91,
            )

    monkeypatch.setattr("app.services.get_aliyun_ocr_client", lambda: StubClient())
    result = extract_resume_document(target, "png")
    assert result.extraction_method == "aliyun_ocr"
    assert result.page_count == 1
    assert result.ocr_confidence == Decimal("0.91")
    assert "OCR" in result.review_warnings[0]


def test_ocr_client_requires_configuration():
    with pytest.raises(OcrServiceError) as error:
        AliyunAdvancedOcrClient(appcode="").recognize_image(image_bytes())
    assert error.value.code == "OCR_NOT_CONFIGURED"


def test_scanned_pdf_renders_pages_and_uses_mocked_ocr(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(image_bytes())
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_image(page.rect, filename=str(image_path))
    document.save(pdf_path)
    document.close()

    class StubClient:
        def recognize_image(self, payload: bytes):
            return OcrPageResult("虚构扫描简历 " * 40, 0.88)

    monkeypatch.setattr("app.services.get_aliyun_ocr_client", lambda: StubClient())
    result = extract_resume_document(pdf_path, "pdf")
    assert result.extraction_method == "aliyun_ocr"
    assert result.page_count == 1
    assert result.ocr_confidence == Decimal("0.88")
