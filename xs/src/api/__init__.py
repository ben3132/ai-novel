"""外部 API 接口边界；采集器不得自行读取或硬编码私密凭据。"""

from .api_client import ApiClient

__all__ = ["ApiClient"]
