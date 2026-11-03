import ipaddress
import re
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr


class ModelAPIError(RuntimeError):
    def __init__(self, message, *, code="model_error"):
        super().__init__(message)
        self.code = code


def model_failure_message(error, service):
    name = "Embedding" if service == "Embedding" else "LLM"
    messages = {
        "vision_unsupported": "当前账号的 LLM 未启用图片识别，请在账号设置中更换或启用支持图片的模型。",
        "not_purchased": f"{name} 模型尚未开通，请在模型服务商控制台开通当前模型，或到账号设置更换可用配置。",
        "unauthorized": f"{name} API Key 无效或已失效，请到账号设置检查。",
        "forbidden": f"当前账号无权调用 {name} 模型，请检查模型服务商授权和账号设置。",
        "rate_limited": f"{name} 调用额度不足或请求过于频繁，请检查服务商额度后重试。",
        "timeout": f"{name} 请求超时，问题已保存，可以稍后重试。",
        "connection": f"暂时无法连接 {name} 服务，请检查网络和 API 地址后重试。",
        "invalid_response": "模型返回的内容未符合回答格式，问题已保存，可以重试。",
        "invalid_citations": "模型返回的引用未通过核对，问题已保存，可以重试。",
        "truncated": "模型回答超出长度限制，问题已保存，可以缩小问题范围后重新提问。",
    }
    return messages.get(error.code, "回答生成失败，问题已保存，可以重试。")


def local_endpoint(value):
    return urlsplit(value).hostname in {"localhost", "127.0.0.1", "::1"}


def validate_model_endpoint(value, provider="aliyun"):
    if provider == "aliyun":
        return validate_aliyun_endpoint(value)
    if provider == "siliconflow":
        if value.rstrip("/") != "https://api.siliconflow.cn/v1":
            raise ModelAPIError("硅基流动请使用 https://api.siliconflow.cn/v1 基础地址。")
        return value.rstrip("/")
    if provider == "deepseek":
        if value.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise ModelAPIError("DeepSeek 请使用 https://api.deepseek.com 或其 /v1 地址。")
        return value.rstrip("/")
    if provider != "openai_compatible":
        raise ModelAPIError("不支持这个模型接口类型。")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
        if (
            not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in {"https", "http"}
            or (parsed.scheme == "http" and not local_endpoint(value))
            or (port is not None and not 1 <= port <= 65535)
            or "\\" in value
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global and not address.is_loopback:
            raise ValueError()
        return value.rstrip("/")
    except ValueError:
        raise ModelAPIError(
            "请填写有效的 HTTPS API 地址；本机服务可使用 http://localhost。"
        ) from None


def validate_aliyun_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    allowed = host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or host.endswith(".maas.aliyuncs.com")
    if (
        parsed.scheme != "https"
        or not allowed
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/compatible-mode/v1"
    ):
        raise ModelAPIError("The CSV endpoint is not a supported Alibaba Cloud model endpoint.")
    return value.rstrip("/")


def post_model_json(
    client: httpx.Client,
    endpoint: str,
    path: str,
    api_key: SecretStr,
    body: dict,
    service: str,
) -> dict:
    try:
        response = client.post(
            endpoint + path,
            headers={
                **(
                    {"Authorization": "Bearer " + api_key.get_secret_value()}
                    if api_key.get_secret_value()
                    else {}
                ),
                "Content-Type": "application/json",
            },
            json=body,
        )
    except httpx.TimeoutException:
        raise ModelAPIError(f"The {service} request timed out.", code="timeout") from None
    except httpx.RequestError:
        raise ModelAPIError(
            f"Could not connect to the {service} service.", code="connection"
        ) from None
    if not response.is_success:
        # 错误正文可能回显凭据，只输出状态码和不含密钥的错误标识。
        code = ""
        try:
            candidate = response.json().get("error", {}).get("code", "")
            if (
                isinstance(candidate, str)
                and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", candidate)
                and not candidate.startswith("sk-")
                and api_key.get_secret_value() not in candidate
            ):
                code = "/" + candidate
        except (ValueError, AttributeError):
            pass
        kind = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
            response.status_code, "service_error"
        )
        if response.status_code == 403 and code == "/AccessDenied.Unpurchased":
            kind = "not_purchased"
        raise ModelAPIError(
            f"{service} service returned HTTP {response.status_code}{code}.", code=kind
        )
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise TypeError("not an object")
        return result
    except (ValueError, TypeError):
        raise ModelAPIError(f"The {service} response is not a valid JSON object.") from None
