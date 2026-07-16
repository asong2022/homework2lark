from __future__ import annotations

import json
from base64 import b64encode
from dataclasses import dataclass, field
from hashlib import sha3_256
from time import time
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from mistake_notebook_api.domain.errors import JsonValue


@dataclass(slots=True)
class YescanClientError(Exception):
    category: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.category)


def create_signature(
    *,
    client_id: str,
    client_secret: str,
    sign_nonce: str,
    timestamp: int,
    sign_method: str = "SHA3-256",
) -> str:
    if sign_method.upper() != "SHA3-256":
        raise ValueError("unsupported Yescan sign method")
    raw = f"{client_id}_vision_{sign_method}_{sign_nonce}_{timestamp}_{client_secret}"
    return sha3_256(raw.encode("utf-8")).hexdigest().lower()


class YescanJsonTransport(Protocol):
    def post_json(
        self, *, url: str, payload: dict[str, JsonValue], timeout_seconds: int
    ) -> JsonValue: ...


def _reject_non_standard_json(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


class UrllibYescanJsonTransport:
    def post_json(
        self, *, url: str, payload: dict[str, JsonValue], timeout_seconds: int
    ) -> JsonValue:
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            request = Request(
                url,
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                response_bytes = response.read()
        except TimeoutError:
            raise YescanClientError("timeout") from None
        except HTTPError as error:
            if error.code in {408, 504}:
                raise YescanClientError("timeout") from None
            if error.code >= 500:
                raise YescanClientError("unavailable") from None
            response_bytes = error.read()
        except (OSError, URLError):
            raise YescanClientError("unavailable") from None
        except (TypeError, ValueError):
            raise YescanClientError("configuration_error") from None

        try:
            return cast(
                JsonValue,
                json.loads(
                    response_bytes.decode("utf-8"),
                    parse_constant=_reject_non_standard_json,
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise YescanClientError("invalid_response") from None


@dataclass(slots=True)
class YescanApiClient:
    client_id: str
    client_secret: str
    endpoint: str
    timeout_seconds: int
    transport: YescanJsonTransport = field(default_factory=UrllibYescanJsonTransport)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.client_id.startswith("BACK_")
            and self.client_secret
            and self.endpoint.startswith("https://")
            and self.timeout_seconds > 0
        )

    def request(
        self,
        *,
        image_bytes: bytes,
        service_option: str,
        function_option: str,
        output_configs: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        if not self.is_configured:
            raise YescanClientError("configuration_error")

        sign_nonce = uuid4().hex
        timestamp = int(time() * 1000)
        sign_method = "SHA3-256"
        payload: dict[str, JsonValue] = {
            "dataBase64": b64encode(image_bytes).decode("ascii"),
            "dataType": "image",
            "serviceOption": service_option,
            "inputConfigs": json.dumps(
                {"function_option": function_option},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "reqId": uuid4().hex,
            "clientId": self.client_id,
            "signMethod": sign_method,
            "signNonce": sign_nonce,
            "timestamp": timestamp,
            "signature": create_signature(
                client_id=self.client_id,
                client_secret=self.client_secret,
                sign_nonce=sign_nonce,
                timestamp=timestamp,
                sign_method=sign_method,
            ),
        }
        if output_configs is not None:
            payload["outputConfigs"] = json.dumps(
                output_configs,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        response = self.transport.post_json(
            url=self.endpoint,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(response, dict):
            raise YescanClientError("invalid_response")
        return response
