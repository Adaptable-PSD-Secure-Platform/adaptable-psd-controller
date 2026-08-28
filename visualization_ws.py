from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, Optional

try:
    import websockets
except ImportError:  # pragma: no cover - 실행 환경에서 requirements 설치 여부에 따라 달라짐
    websockets = None


SnapshotProvider = Callable[[], dict]


class VisualizationWebSocketServer:
    """
    중앙제어 상태를 연결된 HTML 클라이언트에 브로드캐스트합니다.

    중앙제어부와 WebSocket 이벤트 루프를 분리해, 기존 SerialTransport의
    동기 호출 및 시리얼 reader 스레드와 서로 blocking하지 않도록 합니다.
    HTML은 명령을 보내지 않고 상태를 수신해서 화면만 갱신합니다.
    """

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.host = host
        self.port = port

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._server: Any = None
        self._clients: set[Any] = set()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._startup_error: Optional[BaseException] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if websockets is None:
            raise RuntimeError(
                "HTML 시뮬레이터 연결에는 websockets 패키지가 필요합니다. "
                "requirements.txt를 설치하세요."
            )

        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="visualization-websocket",
            daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("HTML WebSocket 서버 시작 시간이 초과되었습니다.")
        if self._startup_error:
            raise RuntimeError(
                f"HTML WebSocket 서버를 시작하지 못했습니다: {self._startup_error}"
            ) from self._startup_error

        print(f"[HTML] WebSocket server: ws://{self.host}:{self.port}")

    def stop(self) -> None:
        if not self._thread:
            return

        loop = self._loop
        stop_event = self._stop_event
        if loop and stop_event and not loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                self._signal_stop(stop_event), loop
            )
            try:
                future.result(timeout=2.0)
            except Exception:
                pass

        self._thread.join(timeout=3.0)
        self._thread = None
        self._loop = None
        self._stop_event = None
        print("[HTML] WebSocket server stopped")

    def publish(self, message: dict) -> None:
        """중앙제어 스레드에서 호출해도 안전한 비동기 브로드캐스트입니다."""
        loop = self._loop
        if not loop or loop.is_closed():
            return

        future = asyncio.run_coroutine_threadsafe(
            self._broadcast(message), loop
        )
        future.add_done_callback(self._consume_future_error)

    @staticmethod
    def _consume_future_error(future: Any) -> None:
        try:
            future.result()
        except Exception:
            # 클라이언트가 이미 끊긴 경우에는 다음 상태 브로드캐스트를 방해하지 않습니다.
            pass

    def _run_event_loop(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()

        try:
            self._server = await websockets.serve(  # type: ignore[union-attr]
                self._handle_client,
                self.host,
                self.port,
            )
            self._ready.set()
            await self._stop_event.wait()
        finally:
            clients = list(self._clients)
            if clients:
                await asyncio.gather(
                    *(client.close() for client in clients),
                    return_exceptions=True,
                )
            self._clients.clear()

            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None

    async def _signal_stop(self, stop_event: asyncio.Event) -> None:
        stop_event.set()

    async def _handle_client(self, websocket: Any) -> None:
        self._clients.add(websocket)
        try:
            initial_snapshot = self.snapshot_provider()
            await websocket.send(self._encode(initial_snapshot))

            # HTML은 현재 상태를 수신만 하므로, 연결 유지를 위해 입력을 소비합니다.
            async for _message in websocket:
                pass
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)

    async def _broadcast(self, message: dict) -> None:
        if not self._clients:
            return

        encoded = self._encode(message)
        clients = list(self._clients)
        results = await asyncio.gather(
            *(client.send(encoded) for client in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                self._clients.discard(client)

    @staticmethod
    def _encode(message: dict) -> str:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
