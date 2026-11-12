# SERAPHIM MODEL LAYER — minimal HTTP transport for provider adapters (S13).
#
# A provider adapter has to talk to a real endpoint, but the transport is a
# *seam*: a test injects a fake and the whole suite runs offline against a
# loopback server, so CI never needs network or tokens.  Only the standard
# library is used — SERAPHIM has no production dependency on a provider SDK
# (pyproject: click + pyyaml only), which also keeps the wire format explicit
# instead of hidden behind a vendor client.
#
# The transport returns *any* HTTP status as a response (including 4xx/5xx) and
# raises a normalized error only for connection-level failures.  Mapping a
# status onto a provider error kind is the adapter's job, because only the
# adapter knows what a status means for its protocol.

from __future__ import annotations

import contextlib
import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from seraphim.model_layer.errors import (
    provider_response_invalid_error,
    provider_timeout_error,
    provider_unavailable_error,
)

#: Default User-Agent.  Not a credential, not a version of the endpoint.
DEFAULT_USER_AGENT = "seraphim/0.1"

#: Upper bound on one physical line read from a streamed response.  A conforming
#: SSE line is tiny; the cap exists so a hostile or broken endpoint cannot make
#: the reader allocate without bound.  A line longer than this is delivered in
#: pieces, and the SSE parser's own event cap rejects the malformed result.
DEFAULT_MAX_LINE_BYTES = 8 * 1024 * 1024

#: How many bytes of decoded stream data the background reader may buffer ahead
#: of the consumer.  Without a bound the reader would pull the whole body into
#: memory as fast as the endpoint can send it, which defeats the adapter's
#: response-size cap (S14 review finding M3).
DEFAULT_MAX_BUFFERED_BYTES = 1024 * 1024

#: Upper bound on a *non-streaming* response body.  A completion is a JSON object
#: that has to fit in memory anyway; the cap exists so a hostile or broken
#: endpoint cannot make ``request()`` allocate without bound (C5 review D6).  It
#: mirrors ``StreamLimits.max_response_bytes``, the budget the streaming path
#: already enforces.
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: Chunk size used while reading a bounded non-streaming body.
_RESPONSE_READ_CHUNK_BYTES = 64 * 1024

#: How often a reader waiting for buffer space re-checks whether the stream was
#: closed underneath it.
_BUDGET_POLL_SECONDS = 0.05


class StreamIdle(Exception):
    """No stream data arrived within the requested wait window.

    Raised by :meth:`HttpStream.read_line` when the caller passed a timeout and
    the endpoint stayed silent.  It is a *poll* signal, not a failure: the caller
    is expected to re-check its cancellation token and deadline and then read
    again.  No data is lost — the line remains queued.
    """


@dataclass
class HttpResponse:
    """A transport-level HTTP response (status + headers + raw body)."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def text(self) -> str:
        """Decode the body as text (never raises on invalid UTF-8)."""
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Parse the body as JSON.  Raises ``json.JSONDecodeError`` if invalid."""
        return json.loads(self.text())


@runtime_checkable
class HttpStream(Protocol):
    """A streaming HTTP response the adapter reads incrementally.

    ``read_line`` returns one line (without stripping the terminator), ``None``
    at end of stream, or raises :class:`StreamIdle` when the wait window expires.
    ``close`` releases the connection; it must be safe to call twice and must
    unblock a pending ``read_line``.
    """

    status: int
    headers: dict[str, str]

    def read_line(self, timeout: float | None = None) -> str | None: ...

    def close(self) -> None: ...


@runtime_checkable
class HttpTransport(Protocol):
    """The seam a provider adapter sends requests through."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Perform one HTTP request.

        Returns a response for any HTTP status.  Raises a normalized
        ``ProviderError`` (``timeout``/``unavailable``) for a connection-level
        failure.  The ``headers`` mapping may contain a credential, so an
        implementation must never log it.
        """
        ...

    def open_stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpStream:
        """Open a streaming request without consuming the body.

        Returns a stream for any HTTP status (including 4xx/5xx, whose body the
        adapter maps onto a normalized error).  Raises a normalized
        ``ProviderError`` only when the connection itself cannot be established.
        """
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect.

    urllib's default handler rebuilds the request and copies the original headers
    (everything except ``content-length``/``content-type``) onto the new URL, so a
    ``3xx`` from a misconfigured endpoint would send the ``Authorization`` header
    — the credential — to a host the operator never configured.  Returning
    ``None`` makes urllib raise ``HTTPError`` for the redirect status, so it
    reaches the adapter as an ordinary response and is mapped to a normalized
    error instead of silently exfiltrating the key.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    """Real HTTP transport built on :mod:`urllib.request`.

    Args:
        provider_id: Reported in a normalized transport error so the failure is
            attributed to the right provider.
        user_agent: Value of the ``User-Agent`` header.
        max_line_bytes: Cap on one physical line read from a streamed response.
    """

    def __init__(
        self,
        *,
        provider_id: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.provider_id = provider_id
        self.user_agent = user_agent
        self.max_line_bytes = max_line_bytes
        self.max_response_bytes = max_response_bytes
        # Redirects are deliberately not followed (see ``_NoRedirectHandler``).
        self._opener = urllib.request.build_opener(_NoRedirectHandler)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request_headers = {"User-Agent": self.user_agent, **headers}
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        # ``timeout`` is a socket-level (per-operation) timeout, so a slow-drip
        # endpoint can keep a non-streaming request alive far beyond it and can
        # stream an unbounded body.  The deadline bounds total elapsed time and
        # ``max_response_bytes`` bounds the allocation (C5 review D6).
        deadline = time.monotonic() + timeout
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=self._read_bounded(response, url, deadline, timeout),
                )
        except urllib.error.HTTPError as exc:
            # An HTTP error status is a *response*, not a transport failure.
            return HttpResponse(
                status=int(exc.code),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=_read_error_body(exc, self.max_response_bytes),
            )
        except TimeoutError as exc:
            raise self._timeout_error(url, timeout) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise self._timeout_error(url, timeout) from exc
            raise provider_unavailable_error(
                self.provider_id,
                safe_message=(f"cannot reach {_safe_url(url)}: {type(exc.reason).__name__}"),
            ) from exc
        except OSError as exc:
            raise provider_unavailable_error(
                self.provider_id,
                safe_message=f"cannot reach {_safe_url(url)}: {type(exc).__name__}",
            ) from exc

    def open_stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpStream:
        request_headers = {"User-Agent": self.user_agent, **headers}
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            return _BufferedStream(
                status=int(exc.code),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=_read_error_body(exc),
            )
        except TimeoutError as exc:
            raise self._timeout_error(url, timeout) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise self._timeout_error(url, timeout) from exc
            raise provider_unavailable_error(
                self.provider_id,
                safe_message=(f"cannot reach {_safe_url(url)}: {type(exc.reason).__name__}"),
            ) from exc
        except OSError as exc:
            raise provider_unavailable_error(
                self.provider_id,
                safe_message=f"cannot reach {_safe_url(url)}: {type(exc).__name__}",
            ) from exc
        return _UrllibStream(
            response,
            provider_id=self.provider_id,
            url=url,
            max_line_bytes=self.max_line_bytes,
        )

    def _timeout_error(self, url: str, timeout: float):
        return provider_timeout_error(
            self.provider_id,
            safe_message=f"HTTP request to {_safe_url(url)} timed out after {timeout}s",
        )

    def _read_bounded(self, response: Any, url: str, deadline: float, timeout: float) -> bytes:
        """Read *response* body incrementally, enforcing a byte cap and a wall-clock deadline.

        A non-streaming response is a single JSON blob that must fit in memory.
        This method prevents two C5-review-D6 vulnerabilities:
        1. *unbounded allocation* — the body is read in chunks and rejected when
           the cap is exceeded;
        2. *slow-drip exhaustion* — a wall-clock deadline bounds the total time,
           because the socket ``timeout`` only covers the *next* read call.
        """
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() >= deadline:
                raise self._timeout_error(url, timeout)
            try:
                chunk = response.read(_RESPONSE_READ_CHUNK_BYTES)
            except OSError:
                break
            if not chunk:
                break
            # Check before appending so the final ``b"".join`` stays tight.
            total += len(chunk)
            if total > self.max_response_bytes:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"response body exceeds {self.max_response_bytes} bytes"
                    ),
                )
            chunks.append(chunk)
        return b"".join(chunks)


class _StreamFailure:
    """Carries a background reader's exception to the consumer thread."""

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error


class _UrllibStream:
    """A streaming response read by a background thread.

    A blocking socket read cannot be interrupted cooperatively, so a daemon
    thread pumps ``readline()`` into a queue while the consumer waits with a
    timeout.  That keeps ``read_line`` interruptible (cancellation and deadlines
    are checked between chunks) and lets ``close`` release the connection even
    while a read is pending.

    The queue is bounded by a byte budget (:data:`DEFAULT_MAX_BUFFERED_BYTES`):
    the reader blocks once it has buffered that much, so a fast endpoint cannot
    be read into memory without bound ahead of the consumer.
    """

    def __init__(
        self,
        response: Any,
        *,
        provider_id: str = "",
        url: str = "",
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        max_buffered_bytes: int = DEFAULT_MAX_BUFFERED_BYTES,
    ) -> None:
        self.status = int(response.status)
        self.headers = dict(response.headers.items())
        self._response = response
        self._provider_id = provider_id
        self._url = url
        self._max_line_bytes = max_line_bytes
        self._max_buffered_bytes = max(1, int(max_buffered_bytes))
        #: The socket behind the response, used to interrupt a pending read on
        #: ``close`` (see the method's docstring).
        self._socket = _underlying_socket(response)
        self._queue: queue.Queue[Any] = queue.Queue()
        self._closed = False
        self._eof = False
        #: Buffer budget shared by the reader (claims) and the consumer (releases).
        self._space = threading.Condition()
        self._queued_bytes = 0
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        try:
            while not self._closed:
                chunk = self._response.readline(self._max_line_bytes)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                if not self._reserve(len(text)):
                    break
                self._queue.put(text)
        except Exception as exc:  # surfaced to the consumer as a normalized error
            self._queue.put(_StreamFailure(exc))
        finally:
            # Closed from the pump's own thread, so the response's lock is free
            # and this cannot block anyone (see ``close``).
            with contextlib.suppress(Exception):
                self._response.close()
            self._queue.put(None)

    def _reserve(self, size: int) -> bool:
        """Claim *size* bytes of the buffer budget; ``False`` once closed."""
        with self._space:
            while self._queued_bytes >= self._max_buffered_bytes and not self._closed:
                self._space.wait(timeout=_BUDGET_POLL_SECONDS)
            if self._closed:
                return False
            self._queued_bytes += size
            return True

    def _release(self, size: int) -> None:
        with self._space:
            self._queued_bytes = max(0, self._queued_bytes - size)
            self._space.notify_all()

    def read_line(self, timeout: float | None = None) -> str | None:
        if self._closed or self._eof:
            return None
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise StreamIdle() from None
        if item is None:
            # End of stream.  Remembered, so a later call also reports the end
            # rather than an idle stream (S14 review finding m4).
            self._eof = True
            return None
        if isinstance(item, _StreamFailure):
            raise self._normalize(item.error)
        self._release(len(item))
        return item

    def close(self) -> None:
        """Release the connection without waiting for a pending read.

        A pending ``recv`` cannot be cancelled portably from another thread:
        ``shutdown`` does not wake it on Windows, and ``HTTPResponse.close`` would
        have to take the buffered reader's lock that the pump thread is holding —
        so the caller would stall for as long as the socket timeout.  Closing the
        *socket* is the one operation that reliably unblocks the reader; the pump
        then closes the response itself, from its own thread.  Idempotent and
        never raises.
        """
        if self._closed:
            return
        self._closed = True
        # Wake the reader if it is waiting for buffer space.
        with self._space:
            self._space.notify_all()
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()

    def _normalize(self, error: BaseException) -> Any:
        if isinstance(error, (TimeoutError, socket.timeout)):
            return provider_timeout_error(
                self._provider_id,
                safe_message=f"stream from {_safe_url(self._url)} timed out",
            )
        return provider_unavailable_error(
            self._provider_id,
            safe_message=(
                f"stream from {_safe_url(self._url)} failed: {type(error).__name__}"
            ),
        )


class _BufferedStream:
    """A non-streaming response exposed through the stream interface.

    Used for an HTTP error status: the body was already read, so it is handed to
    the adapter line by line and the adapter maps the status onto a normalized
    error.  This keeps one code path in the adapter for "open, check status".
    """

    def __init__(self, *, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self._lines = body.decode("utf-8", errors="replace").splitlines(keepends=True)
        self._position = 0

    def read_line(self, timeout: float | None = None) -> str | None:
        if self._position >= len(self._lines):
            return None
        line = self._lines[self._position]
        self._position += 1
        return line

    def text(self) -> str:
        """The whole buffered body as text (never raises on invalid UTF-8)."""
        return "".join(self._lines)

    def json(self) -> Any:
        """Parse the buffered body as JSON (raises ``json.JSONDecodeError``)."""
        return json.loads(self.text())

    def close(self) -> None:
        self._position = len(self._lines)


def _read_error_body(error: urllib.error.HTTPError, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES) -> bytes:
    """Read and close an error response body.

    An ``HTTPError`` is a file-like response object: reading the body but never
    closing it keeps the connection alive until garbage collection, so it is
    closed here (S14 review finding m8).  The read is bounded like a success body:
    an error page is no reason to allocate without limit (C5 review D6).
    """
    try:
        return error.read(max_bytes + 1)[:max_bytes]
    except Exception:  # pragma: no cover - defensive: body already consumed
        return b""
    finally:
        with contextlib.suppress(Exception):
            error.close()


def _underlying_socket(response: Any) -> Any:
    """Best-effort handle on the socket behind a streaming response.

    Used only to interrupt a pending read in :meth:`_UrllibStream.close`; the
    private attribute is read defensively so an unexpected response object simply
    means "no interruptible close" rather than a crash.
    """
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    return getattr(raw, "_sock", None)


def _safe_url(url: str) -> str:
    """Return a URL with any userinfo (``user:pass@``) removed.

    A URL can carry a credential in its userinfo component; an error message
    must not echo it.  The host and path are enough to locate the endpoint.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    if "@" in rest.split("/", 1)[0]:
        rest = rest.split("@", 1)[1]
    return f"{scheme}://{rest}"


__all__ = [
    "DEFAULT_MAX_BUFFERED_BYTES",
    "DEFAULT_MAX_LINE_BYTES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_USER_AGENT",
    "HttpResponse",
    "HttpStream",
    "HttpTransport",
    "StreamIdle",
    "UrllibTransport",
]
