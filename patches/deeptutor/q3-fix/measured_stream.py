class MeasuredStream:
    """Preserve supplier completion and usage trailers when a consumer closes early."""

    def __init__(self, stream: Any, meter: CallMeasurement):
        self.stream, self.meter = stream, meter
        self.iterator: Any = None
        self._reasons: dict[int, str | None] = {}
        self._failure: str | None = None
        self._exhausted = False
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def __aiter__(self) -> Any:
        return self

    def _observe(self, chunk: Any) -> None:
        self.meter.chunk(chunk)
        for choice in getattr(chunk, "choices", []) or []:
            index = getattr(choice, "index", 0)
            reason = getattr(choice, "finish_reason", None)
            self._reasons[index] = reason or self._reasons.get(index)

    def _terminal(self) -> bool:
        return bool(self._reasons) and all(self._reasons.values())

    def _status(self) -> str:
        if self._failure:
            return self._failure
        reasons = set(self._reasons.values())
        if reasons & {"error", "content_filter"}:
            return "failed"
        if "length" in reasons:
            return "truncated"
        if self._terminal():
            return "completed" if reasons <= {"stop", "tool_calls", "function_call"} else "interrupted"
        return "completed" if self._exhausted else "interrupted"

    def _finish(self) -> None:
        # An estimate remains in the ledger for conservative cost accounting;
        # an active guard must not treat it as reconciled supplier usage.
        self.meter.finish(status=self._status(), require_reported_usage=True)

    async def __anext__(self) -> Any:
        if self._closed:
            raise StopAsyncIteration
        token = measurement_active.set(True)
        try:
            if self.iterator is None:
                self.iterator = self.stream.__aiter__()
            chunk = await self.iterator.__anext__()
            self._observe(chunk)
            return chunk
        except StopAsyncIteration:
            self._exhausted = True
            self._finish()
            raise
        except BaseException as exc:
            import asyncio
            self._failure = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            self._finish()
            raise
        finally:
            measurement_active.reset(token)

    async def close(self) -> None:
        if self._closed:
            return
        import asyncio
        token = measurement_active.set(True)
        try:
            # A consumer may stop at finish_reason, one frame before usage.
            # Drain only after an observed terminal, with finite time/frames.
            if self._terminal() and not self._failure and not self._exhausted and not self.meter.usage:
                try:
                    async with asyncio.timeout(1.0):
                        for _ in range(16):
                            chunk = await self.iterator.__anext__()
                            self._observe(chunk)
                            if self.meter.usage:
                                break
                except StopAsyncIteration:
                    self._exhausted = True
                except TimeoutError:
                    pass  # Missing usage is still blocked by _finish.
                except BaseException as exc:
                    self._failure = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
                    raise
        finally:
            self._closed = True
            try:
                self._finish()
            finally:
                try:
                    close = getattr(self.stream, "close", None) or getattr(self.stream, "aclose", None)
                    if close:
                        await close()
                finally:
                    measurement_active.reset(token)

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *args: Any) -> None:
        if args and args[0] is not None:
            import asyncio
            self._failure = "interrupted" if issubclass(args[0], asyncio.CancelledError) else "failed"
        await self.close()
