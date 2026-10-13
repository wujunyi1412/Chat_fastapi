from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[int, dict[int, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))
        self._lock = asyncio.Lock()

    async def connect(self, room_id: int, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[room_id][user_id].add(websocket)

    async def disconnect(self, room_id: int, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            users = self._rooms.get(room_id)
            if not users:
                return
            users[user_id].discard(websocket)
            if not users[user_id]:
                users.pop(user_id, None)
            if not users:
                self._rooms.pop(room_id, None)

    async def broadcast(self, room_id: int, payload: dict) -> None:
        async with self._lock:
            sockets = [ws for group in self._rooms.get(room_id, {}).values() for ws in group]
        dead: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        if dead:
            async with self._lock:
                for user_id, group in list(self._rooms.get(room_id, {}).items()):
                    group.difference_update(dead)
                    if not group:
                        self._rooms[room_id].pop(user_id, None)

    async def presence(self, room_id: int) -> list[int]:
        async with self._lock:
            return list(self._rooms.get(room_id, {}).keys())


manager = ConnectionManager()

