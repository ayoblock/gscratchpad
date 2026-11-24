"""WebDAV 传输层（sync v1，见 docs/SYNC_PROTOCOL.md §8）。

标准库 urllib 实现，零新增依赖。支持 PUT / GET / HEAD / PROPFIND（Depth:1）/
MKCOL 与 Basic 认证；URL 允许内嵌用户名（`http://user@host/path`），解析后
拆为独立 user 字段。超时与重试对齐 Android R35 CloudBackup（连接 12s /
读取 30s，网络错误与 5xx 重试 1 次）。所有方法为阻塞调用，调用方必须放在
后台线程。
"""

from __future__ import annotations

import base64
import posixpath
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

CONNECT_TIMEOUT = 12.0
READ_TIMEOUT = 30.0


class WebDavError(Exception):
    """传输失败（网络错误或非 2xx 响应）。message 面向状态行展示。"""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def parse_base_url(url: str) -> tuple[str, str]:
    """拆分基址与内嵌用户名，返回 (归一化 url, user)。

    `http://admin@10.0.0.1:5244/dav/hdd/test` →
    ("http://10.0.0.1:5244/dav/hdd/test", "admin")。
    显式 `http://user:pass@host` 形式中密码部分不提取（密码单独存管），
    仅保留用户名。
    """
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise WebDavError("地址需以 http(s):// 开头")
    parsed = urllib.parse.urlsplit(url)
    user = parsed.username or ""
    netloc = parsed.hostname or ""
    if not netloc:
        raise WebDavError("地址缺少主机名")
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    rebuilt = urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path.rstrip("/"), "", "")
    )
    return rebuilt, urllib.parse.unquote(user)


def join_url(base: str, *parts: str) -> str:
    """在基址后拼接路径片段（各片段做 URL 编码，`/` 保留为分隔符）。"""
    path = base.rstrip("/")
    for part in parts:
        quoted = urllib.parse.quote(part.strip("/"), safe="/")
        path = f"{path}/{quoted}"
    return path


class WebDavClient:
    """单基址的阻塞式 WebDAV 客户端。非线程安全：每线程各自实例化。"""

    def __init__(self, base_url: str, user: str = "", password: str = "") -> None:
        self.base, parsed_user = parse_base_url(base_url)
        self.user = user or parsed_user
        self.password = password
        self._token = None
        if self.user or self.password:
            raw = f"{self.user}:{self.password}".encode("utf-8")
            self._token = base64.b64encode(raw).decode("ascii")

    # ------------------------------------------------------------------ 基础

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        """单次 HTTP 请求，返回 (status, body, response_headers)。"""
        req = urllib.request.Request(url, data=data, method=method)
        if self._token:
            req.add_header("Authorization", f"Basic {self._token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        if data is not None:
            req.add_header("Content-Length", str(len(data)))
        timeout = timeout or (CONNECT_TIMEOUT + READ_TIMEOUT)
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers or {})
        except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
            raise WebDavError(f"网络错误：{exc}") from exc

    def _request_retry(
        self, method: str, url: str, **kwargs
    ) -> tuple[int, bytes, dict[str, str]]:
        """网络错误与 5xx 重试 1 次。"""
        try:
            status, body, headers = self._request(method, url, **kwargs)
        except WebDavError:
            time.sleep(0.5)
            status, body, headers = self._request(method, url, **kwargs)
        return status, body, headers

    # ------------------------------------------------------------------ 操作

    @staticmethod
    def _http_error(action: str, status: int) -> "WebDavError":
        """HTTP 错误统一文案；401 单独提示认证问题（密码未填/错误最常见）。"""
        if status == 401:
            return WebDavError(
                f"{action}失败 HTTP 401：认证被拒，请检查用户名与密码（密码未填也会报此错）",
                status,
            )
        return WebDavError(f"{action}失败 HTTP {status}", status)

    def put(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """上传；2xx 即成功，其余抛 WebDavError。"""
        status, _, _ = self._request_retry(
            "PUT",
            join_url(self.base, path),
            data=data,
            headers={"Content-Type": content_type},
        )
        if not 200 <= status <= 299:
            raise self._http_error("上传", status)

    def get(self, path: str) -> bytes:
        """下载；404 返回 None 之外统一抛错（调用方用 exists/head 区分）。"""
        status, body, _ = self._request_retry("GET", join_url(self.base, path))
        if not 200 <= status <= 299:
            raise self._http_error("下载", status)
        return body

    def get_optional(self, path: str) -> bytes | None:
        """下载；404 返回 None。"""
        status, body, _ = self._request_retry("GET", join_url(self.base, path))
        if status == 404:
            return None
        if not 200 <= status <= 299:
            raise self._http_error("下载", status)
        return body

    def head_size(self, path: str) -> int:
        """远端大小；404 返回 -1；不支持 HEAD 的服务器降级为 GET 只取头。"""
        url = join_url(self.base, path)
        status, _, headers = self._request_retry("HEAD", url)
        if status == 404:
            return -1
        if status in (405, 501):
            # 降级：GET + Range 只取头
            status, _, headers = self._request_retry(
                "GET", url, headers={"Range": "bytes=0-0"}
            )
        if not 200 <= status <= 299:
            return -1
        return int(headers.get("Content-Length") or -1)

    def mkcol_deep(self, path: str) -> None:
        """逐级创建目录；405（已存在）视为成功。"""
        segments = [seg for seg in path.strip("/").split("/") if seg]
        current = ""
        for seg in segments:
            current = f"{current}/{seg}" if current else f"/{seg}"
            status, _, _ = self._request_retry(
                "MKCOL", join_url(self.base, current)
            )
            if status not in (200, 201, 405):
                # 已存在还可能表现为 301/409，放宽到 4xx 内除 401/403 外不阻断
                if status in (401, 403):
                    if status == 401:
                        raise self._http_error("创建目录", status)
                    raise WebDavError(
                        "创建目录被拒 HTTP 403：服务器拒绝了写权限"
                        "（请在 AList/OpenList 管理页给该用户勾选 WebDAV 写入权限）",
                        status,
                    )

    def propfind_entries(self, path: str) -> list[tuple[str, int, str]]:
        """Depth:1 枚举子项（名称、字节数、修改时间），供云端备份列表使用。"""
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:"><D:prop>'
            '<D:resourcetype/><D:getcontentlength/><D:getlastmodified/>'
            '</D:prop></D:propfind>'
        )
        status, data, _ = self._request_retry(
            "PROPFIND",
            (join_url(self.base, "") if not path.strip("/") else join_url(self.base, path) + "/"),
            data=body.encode("utf-8"),
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        if status == 404:
            return []
        if not (200 <= status <= 299 or status == 207):
            raise self._http_error("列目录", status)
        return _parse_propfind_entries(data.decode("utf-8", "replace"), posixpath.basename(path))

    def propfind_children(self, path: str) -> list[str]:
        """Depth:1 枚举子项名。返回第一层子目录/文件的名字列表（URL 解码后）。"""
        return [name for name, _, _ in self.propfind_entries(path)]


def _xml_tag(block: str, name: str) -> str | None:
    match = re.search(
        rf"<(?:[A-Za-z0-9]+:)?{name}\b[^>]*>(.*?)</(?:[A-Za-z0-9]+:)?{name}>",
        block,
        re.S,
    )
    return match.group(1).strip() if match else None


def _parse_propfind_entries(xml_text: str, self_name: str) -> list[tuple[str, int, str]]:
    """multistatus → 子项（名称/大小/修改时间），命名空间无关。"""
    out: list[tuple[str, int, str]] = []
    responses = re.finditer(
        r"<(?:[A-Za-z0-9]+:)?response\b[^>]*>(.*?)</(?:[A-Za-z0-9]+:)?response>",
        xml_text,
        re.S,
    )
    for match in responses:
        block = match.group(1)
        href = _xml_tag(block, "href")
        if not href:
            continue
        name = posixpath.basename(urllib.parse.unquote(href).rstrip("/"))
        if not name or name == self_name:
            continue
        size_raw = _xml_tag(block, "getcontentlength")
        size = int(size_raw) if size_raw and size_raw.isdigit() else -1
        out.append((name, size, _xml_tag(block, "getlastmodified") or ""))
    return out


def _parse_propfind_names(xml_text: str, self_name: str) -> list[str]:
    """从 multistatus 提取子项名（排除自身）。命名空间无关，正则提取 <href>。"""
    names: list[str] = []
    for match in re.finditer(r"<(?:[A-Za-z0-9]+:)?href>(.*?)</(?:[A-Za-z0-9]+:)?href>", xml_text):
        href = match.group(1).strip()
        decoded = urllib.parse.unquote(href)
        name = posixpath.basename(decoded.rstrip("/"))
        if name and name != self_name:
            names.append(name)
    return names
