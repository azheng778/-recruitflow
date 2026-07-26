from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .services_error import OcrServiceError


@dataclass(frozen=True)
class OcrPageResult:
    text: str
    confidence: float | None


class AliyunAdvancedOcrClient:
    """Minimal, credential-safe client for Alibaba Cloud Market advanced OCR."""

    def __init__(self, *, endpoint: str | None = None, appcode: str | None = None, timeout_seconds: int | None = None):
        self.endpoint = endpoint or settings.aliyun_ocr_endpoint
        self.appcode = appcode if appcode is not None else settings.aliyun_ocr_appcode
        self.timeout_seconds = timeout_seconds or settings.aliyun_ocr_timeout_seconds

    def recognize_image(self, image_bytes: bytes) -> OcrPageResult:
        if not self.appcode:
            raise OcrServiceError("OCR_NOT_CONFIGURED", "阿里云 OCR 尚未配置", 503)
        payload = {
            "img": base64.b64encode(image_bytes).decode("ascii"),
            "prob": True,
            "charInfo": False,
            "rotate": True,
            "table": False,
            "sortPage": True,
            "noStamp": False,
            "figure": False,
            "row": True,
            "paragraph": True,
            "oricoord": False,
        }
        headers = {
            "Authorization": f"APPCODE {self.appcode}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        last_error: OcrServiceError | None = None
        for attempt in range(2):
            try:
                response = httpx.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                )
                if response.status_code in {429} or response.status_code >= 500:
                    last_error = OcrServiceError("OCR_UPSTREAM_UNAVAILABLE", "OCR 服务暂时不可用，请稍后重试", 503)
                    if attempt == 0:
                        time.sleep(0.25)
                        continue
                    raise last_error
                if response.status_code in {401, 403}:
                    raise OcrServiceError("OCR_AUTH_FAILED", "OCR 凭证无效或没有接口权限", 503)
                if response.status_code == 413:
                    raise OcrServiceError("OCR_IMAGE_TOO_LARGE", "图片超过 OCR 服务大小限制", 413)
                if response.status_code >= 400:
                    raise OcrServiceError("OCR_RECOGNITION_FAILED", "OCR 服务未能识别该图片", 422)
                try:
                    body = response.json()
                except ValueError as exc:
                    raise OcrServiceError("OCR_INVALID_RESPONSE", "OCR 服务返回格式异常", 502) from exc
                return self._parse_response(body)
            except httpx.TimeoutException as exc:
                last_error = OcrServiceError("OCR_TIMEOUT", "OCR 服务响应超时，请稍后重试", 504)
                if attempt == 0:
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = OcrServiceError("OCR_NETWORK_ERROR", "无法连接 OCR 服务，请稍后重试", 502)
                if attempt == 0:
                    continue
                raise last_error from exc
        raise last_error or OcrServiceError("OCR_UPSTREAM_UNAVAILABLE", "OCR 服务暂时不可用", 503)

    @staticmethod
    def _parse_response(body: dict[str, Any]) -> OcrPageResult:
        if str(body.get("code", "")).lower() not in {"", "0", "200", "success"} and body.get("success") is False:
            raise OcrServiceError("OCR_RECOGNITION_FAILED", "OCR 服务未能识别该图片", 422)
        words: list[str] = []
        probabilities: list[float] = []
        candidates = body.get("prism_wordsInfo") or body.get("ret") or []
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                word = item.get("word") or item.get("content") or item.get("text")
                if word:
                    words.append(str(word).strip())
                value = item.get("prob") or item.get("probability") or item.get("confidence")
                try:
                    if value is not None:
                        value_float = float(value)
                        probabilities.append(value_float / 100 if value_float > 1 else value_float)
                except (TypeError, ValueError):
                    pass
        if not words and isinstance(body.get("content"), str):
            words = [body["content"].strip()]
        text = "\n".join(item for item in words if item)
        if not text:
            raise OcrServiceError("OCR_EMPTY_RESULT", "OCR 未识别到可用文字，请上传更清晰的简历", 422)
        confidence = sum(probabilities) / len(probabilities) if probabilities else None
        return OcrPageResult(text=text, confidence=confidence)
