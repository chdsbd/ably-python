import functools
import logging
import asyncio
import websockets
import json
from ably.http.httputils import HttpUtils
from ably.util.exceptions import AblyAuthException
from enum import Enum, IntEnum
from pyee.asyncio import AsyncIOEventEmitter

log = logging.getLogger(__name__)


class ConnectionState(Enum):
    INITIALIZED = 'initialized'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    CLOSING = 'closing'
    CLOSED = 'closed'
    FAILED = 'failed'


class ProtocolMessageAction(IntEnum):
    CONNECTED = 4
    ERROR = 9
    CLOSE = 7
    CLOSED = 8


class Connection(AsyncIOEventEmitter):
    def __init__(self, realtime):
        self.__realtime = realtime
        self.__connection_manager = ConnectionManager(realtime)
        self.__state = ConnectionState.INITIALIZED
        self.__connection_manager.on('connectionstate', self.on_state_update)
        super().__init__()

    async def connect(self):
        await self.__connection_manager.connect()

    async def close(self):
        await self.__connection_manager.close()

    def on_state_update(self, state):
        self.__state = state
        self.__realtime.options.loop.call_soon(functools.partial(self.emit, state))

    @property
    def state(self):
        return self.__state

    @state.setter
    def state(self, value):
        self.__state = value


class ConnectionManager(AsyncIOEventEmitter):
    def __init__(self, realtime):
        self.options = realtime.options
        self.__ably = realtime
        self.__state = ConnectionState.INITIALIZED
        self.__connected_future = None
        self.__closed_future = None
        self.__websocket = None
        self.connect_impl_task = None
        super().__init__()

    def enact_state_change(self, state):
        self.__state = state
        self.emit('connectionstate', state)

    async def connect(self):
        if self.__state == ConnectionState.CONNECTED:
            return

        if self.__state == ConnectionState.CONNECTING:
            if self.__connected_future is None:
                log.fatal('Connection state is CONNECTING but connected_future does not exits')
                return
            await self.__connected_future
        else:
            self.enact_state_change(ConnectionState.CONNECTING)
            self.__connected_future = asyncio.Future()
            self.connect_impl_task = self.ably.options.loop.create_task(self.connect_impl())
            await self.__connected_future
            self.enact_state_change(ConnectionState.CONNECTED)

    async def close(self):
        if self.__state != ConnectionState.CONNECTED:
            log.warn('Connection.closed called while connection state not connected')
        self.enact_state_change(ConnectionState.CLOSING)
        self.__closed_future = asyncio.Future()
        if self.__websocket and self.__state != ConnectionState.FAILED:
            await self.send_close_message()
            await self.__closed_future
        else:
            log.warn('Connection.closed called while connection already closed or not established')
        self.enact_state_change(ConnectionState.CLOSED)
        if self.connect_impl_task:
            await self.connect_impl_task

    async def send_close_message(self):
        await self.sendProtocolMessage({"action": ProtocolMessageAction.CLOSE})

    async def sendProtocolMessage(self, protocolMessage):
        await self.__websocket.send(json.dumps(protocolMessage))

    async def connect_impl(self):
        headers = HttpUtils.default_headers()
        async with websockets.connect(f'wss://{self.options.realtime_host}?key={self.ably.key}',
                                      extra_headers=headers) as websocket:
            self.__websocket = websocket
            task = self.ably.options.loop.create_task(self.ws_read_loop())
            try:
                await task
            except AblyAuthException:
                return

    async def ws_read_loop(self):
        while True:
            raw = await self.__websocket.recv()
            msg = json.loads(raw)
            action = msg['action']
            if action == ProtocolMessageAction.CONNECTED:  # CONNECTED
                if self.__connected_future:
                    self.__connected_future.set_result(None)
                    self.__connected_future = None
                else:
                    log.warn('CONNECTED message received but connected_future not set')
            if action == ProtocolMessageAction.ERROR:  # ERROR
                error = msg["error"]
                if error['nonfatal'] is False:
                    self.enact_state_change(ConnectionState.FAILED)
                    exception = AblyAuthException(error["message"], error["statusCode"], error["code"])
                    if self.__connected_future:
                        self.__connected_future.set_exception(exception)
                        self.__connected_future = None
                    self.__websocket = None
                    raise exception
            if action == ProtocolMessageAction.CLOSED:
                await self.__websocket.close()
                self.__websocket = None
                self.__closed_future.set_result(None)
                break

    @property
    def ably(self):
        return self.__ably

    @property
    def state(self):
        return self.__state
