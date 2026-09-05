"""GOAT A3000 LiDAR Pro (51rcxt) — GOAT patches.

Stock upstream wires the V2 clean commands. If this hardware behaves
like the A3000 LiDAR (cr0e4u) — getCleanInfo_V2 never answering and
clean_V2 being silently ignored — swap them for the mower variants:
  GetCleanInfoV2 -> GetCleanInfo   (state actually reported)
  CleanV2        -> CleanMowerArea (clean endpoint, reads /tmp/goat_zones)
Only apply this if the stock profile is confirmed broken; the Pro is a
different platform (model GOAT_INT_A2600_LIDAR_PLUS_NA) and may not
need it.
"""

from __future__ import annotations

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    CapabilityLifeSpan,
    CapabilitySet,
    CapabilitySetEnable,
    CapabilitySettings,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json import (
    GetBorderSwitch,
    GetChildLock,
    GetCrossMapBorderWarning,
    GetCutDirection,
    GetMoveUpWarning,
    GetSafeProtect,
    SetBorderSwitch,
    SetChildLock,
    SetCrossMapBorderWarning,
    SetCutDirection,
    SetMoveUpWarning,
    SetSafeProtect,
)
from deebot_client.commands.json.advanced_mode import GetAdvancedMode, SetAdvancedMode
from deebot_client.commands.json.battery import GetBattery
from deebot_client.commands.json.charge_state import GetChargeState
from deebot_client.commands.json.clean import (
    CleanMower,
    CleanMowerArea,
    CleanMowerEndAndCharge,
    CleanV2,
    GetCleanInfo,
)
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.error import GetError
from deebot_client.commands.json.life_span import GetLifeSpan, ResetLifeSpan
from deebot_client.commands.json.network import GetNetInfo
from deebot_client.commands.json.play_sound import PlaySound
from deebot_client.commands.json.stats import GetStats, GetTotalStats
from deebot_client.commands.json.true_detect import GetTrueDetect, SetTrueDetect
from deebot_client.commands.json.volume import GetVolume, SetVolume
from deebot_client.const import DataType
from deebot_client.events import (
    AdvancedModeEvent,
    AvailabilityEvent,
    BatteryEvent,
    BorderSwitchEvent,
    ChildLockEvent,
    CrossMapBorderWarningEvent,
    CustomCommandEvent,
    CutDirectionEvent,
    ErrorEvent,
    LifeSpan,
    LifeSpanEvent,
    MoveUpWarningEvent,
    NetworkInfoEvent,
    ReportStatsEvent,
    SafeProtectEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
    TrueDetectEvent,
    VolumeEvent,
)
from deebot_client.models import StaticDeviceInfo


def get_device_info() -> StaticDeviceInfo:
    """Get device info for this model."""
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.MOWER,
            availability=CapabilityEvent(
                AvailabilityEvent, [GetBattery(is_available_check=True)]
            ),
            battery=CapabilityEvent(BatteryEvent, [GetBattery()]),
            # Dock in HA means END the run, not just go home: plain
            # Charge leaves the task suspended (app shows END/Continue,
            # workComplete never fires, mower may auto-resume). Pause and
            # Continue from the Ecovacs app still resume normally.
            charge=CapabilityExecute(CleanMowerEndAndCharge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=CleanMowerArea),
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=CustomCommand
            ),
            error=CapabilityEvent(ErrorEvent, [GetError()]),
            life_span=CapabilityLifeSpan(
                types=(LifeSpan.BLADE, LifeSpan.LENS_BRUSH),
                event=LifeSpanEvent,
                get=[
                    GetLifeSpan(
                        [
                            LifeSpan.BLADE,
                            LifeSpan.LENS_BRUSH,
                        ]
                    )
                ],
                reset=ResetLifeSpan,
            ),
            network=CapabilityEvent(NetworkInfoEvent, [GetNetInfo()]),
            play_sound=CapabilityExecute(PlaySound),
            settings=CapabilitySettings(
                advanced_mode=CapabilitySetEnable(
                    AdvancedModeEvent, [GetAdvancedMode()], SetAdvancedMode
                ),
                border_switch=CapabilitySetEnable(
                    BorderSwitchEvent, [GetBorderSwitch()], SetBorderSwitch
                ),
                cut_direction=CapabilitySet(
                    CutDirectionEvent, [GetCutDirection()], SetCutDirection
                ),
                child_lock=CapabilitySetEnable(
                    ChildLockEvent, [GetChildLock()], SetChildLock
                ),
                moveup_warning=CapabilitySetEnable(
                    MoveUpWarningEvent, [GetMoveUpWarning()], SetMoveUpWarning
                ),
                cross_map_border_warning=CapabilitySetEnable(
                    CrossMapBorderWarningEvent,
                    [GetCrossMapBorderWarning()],
                    SetCrossMapBorderWarning,
                ),
                safe_protect=CapabilitySetEnable(
                    SafeProtectEvent, [GetSafeProtect()], SetSafeProtect
                ),
                true_detect=CapabilitySetEnable(
                    TrueDetectEvent, [GetTrueDetect()], SetTrueDetect
                ),
                volume=CapabilitySet(VolumeEvent, [GetVolume()], SetVolume),
            ),
            state=CapabilityEvent(StateEvent, [GetChargeState(), GetCleanInfo()]),
            stats=CapabilityStats(
                clean=CapabilityEvent(StatsEvent, [GetStats()]),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, [GetTotalStats()]),
            ),
        ),
    )
