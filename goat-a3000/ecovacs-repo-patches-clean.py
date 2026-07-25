"""Clean commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deebot_client.events import StateEvent
from deebot_client.logging_filter import get_logger
from deebot_client.message import HandlingResult, MessageBodyDataDict
from deebot_client.models import ApiDeviceInfo, CleanAction, CleanMode, State

from .common import ExecuteCommand, JsonCommandWithMessageHandling

if TYPE_CHECKING:
    from deebot_client.authentication import Authenticator
    from deebot_client.event_bus import EventBus

_LOGGER = get_logger(__name__)

# Last known active task type ("auto", "spotArea", ...), cached from
# getCleanInfo / onCleanInfo. RESUME must echo the running task's type:
# the A3000 silently ignores a resume whose type mismatches the task
# (response is still code 0 / "ok"). Verified via MQTT capture 2026-07-25.
_LAST_TASK_TYPE: str | None = None


class Clean(ExecuteCommand):
    """Clean command."""

    NAME = "clean"

    def __init__(self, action: CleanAction) -> None:
        super().__init__(self._get_args(action))

    async def _execute(
        self,
        authenticator: Authenticator,
        device_info: ApiDeviceInfo,
        event_bus: EventBus,
    ) -> tuple[HandlingResult, dict[str, Any]]:
        """Execute command."""
        state = event_bus.get_last_event(StateEvent)
        if state and isinstance(self._args, dict):
            if (
                self._args["act"] == CleanAction.RESUME.value
                and state.state != State.PAUSED
            ):
                self._args = self._get_args(CleanAction.START)
            elif (
                self._args["act"] == CleanAction.START.value
                and state.state == State.PAUSED
            ):
                self._args = self._get_args(CleanAction.RESUME)

        return await super()._execute(authenticator, device_info, event_bus)

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        args = {"act": action.value}
        if action == CleanAction.START:
            args["type"] = CleanMode.AUTO.value
        return args


class CleanArea(Clean):
    """Clean area command."""

    def __init__(
        self, mode: CleanMode, area: list[int | float], cleanings: int = 1
    ) -> None:
        self._additional_args = {
            "type": mode.value,
            "content": ",".join(str(i) for i in area),
            "count": cleanings,
        }
        super().__init__(CleanAction.START)

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        args = super()._get_args(action)
        if action == CleanAction.START:
            args.update(self._additional_args)
        return args


class CleanV2(Clean):
    """Clean V2 command."""

    NAME = "clean_V2"

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        content: dict[str, str] = {}
        args = {"act": action.value, "content": content}
        match action:
            case CleanAction.START:
                content["type"] = CleanMode.AUTO.value
            case CleanAction.STOP | CleanAction.PAUSE:
                content["type"] = ""
        return args


class CleanAreaV2(CleanV2):
    """Clean area command."""

    def __init__(self, mode: CleanMode, area: list[int | float], _: int = 1) -> None:
        self._additional_content = {
            "type": mode.value,
            "value": ",".join(str(i) for i in area),
        }
        super().__init__(CleanAction.START)

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        args = super()._get_args(action)
        if action == CleanAction.START:
            args["content"].update(self._additional_content)
        return args


class GetCleanInfo(JsonCommandWithMessageHandling, MessageBodyDataDict):
    """Get clean info command."""

    NAME = "getCleanInfo"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus: EventBus, data: dict[str, Any]
    ) -> HandlingResult:
        """Handle message->body->data and notify the correct event subscribers.

        :return: A message response
        """
        global _LAST_TASK_TYPE  # noqa: PLW0603
        status: State | None = None
        state = data.get("state")
        if data.get("trigger") == "alert":
            status = State.ERROR
        elif state in ("clean", "washing"):
            clean_state = data.get("cleanState", {})
            motion_state = clean_state.get("motionState")
            if motion_state == "working":
                status = State.CLEANING
            elif motion_state == "pause":
                status = State.PAUSED
            elif motion_state == "goCharging":
                status = State.RETURNING

            clean_type = clean_state.get("type")
            content = clean_state.get("content", {})
            if "type" in content:
                clean_type = content.get("type")

            if clean_type:
                _LAST_TASK_TYPE = clean_type

            if clean_type == "customArea":
                area_values = content
                if "value" in content:
                    area_values = content.get("value")

                _LOGGER.debug("Last custom area values (x1,y1,x2,y2): %s", area_values)

        elif state == "goCharging":
            status = State.RETURNING
        elif state == "idle":
            status = State.IDLE
            _LAST_TASK_TYPE = None

        if status:
            event_bus.notify(StateEvent(status))
            return HandlingResult.success()

        return HandlingResult.analyse()


class GetCleanInfoV2(GetCleanInfo):
    """Get clean info v2 command."""

    NAME = "getCleanInfo_V2"

class CleanMower(CleanV2):
    """Clean command for GOAT LiDAR mowers.

    Uses the 'clean' endpoint (not 'clean_V2') with area-based content.
    Fixes empty type field (error 20003) for PAUSE/STOP actions.
    """

    NAME = "clean"

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        # GOAT LiDAR mowers use 'auto' type for all actions.
        # Sending empty string for pause/stop causes cloud error 20003.
        # RESUME is the exception: it must match the running task's type
        # (e.g. resuming a paused spotArea run with type auto is silently
        # ignored), so echo the last type seen in getCleanInfo/onCleanInfo.
        if action == CleanAction.RESUME and _LAST_TASK_TYPE:
            return {"act": action.value, "content": {"type": _LAST_TASK_TYPE}}
        return {"act": action.value, "content": {"type": "auto"}}


class CleanMowerArea(CleanMower):
    """CleanMower variant that reads zone IDs from /tmp/goat_zones.

    Write a comma-separated zone ID string to /tmp/goat_zones inside the
    container before calling start_mowing. The file is consumed on first use.
    If absent or empty, falls back to full-auto mode (same as CleanMower).

    Zone IDs for cr0e4u (GOAT A3000 LiDAR, fw 1.13.31):
      2=Front Street, 3=Front, 4=Left Side Street,
      5=Backyard Side, 6=Left Side, 7=Backyard
    """

    _ZONES_FILE = "/tmp/goat_zones"

    def _get_args(self, action: CleanAction) -> dict[str, Any]:
        import os  # noqa: PLC0415
        if action == CleanAction.START:
            try:
                with open(self._ZONES_FILE) as f:
                    zones = f.read().strip()
                os.unlink(self._ZONES_FILE)
                if zones:
                    return {"act": action.value, "content": {"type": "spotArea", "value": zones}}
            except OSError:
                pass
        return super()._get_args(action)
