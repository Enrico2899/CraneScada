"""
Layout del DB export del PLC (Q3_DB, DB7901).

Riflette esattamente la struttura definita in TIA Portal. Se il DB viene
modificato lato PLC (aggiunta/rimozione campi), aggiornare qui gli offset
di conseguenza — per questo esiste VersionDB: se in futuro leggiamo una
versione diversa da quella attesa, l'app dovrebbe segnalarlo invece di
fidarsi ciecamente degli offset sotto.

Offset in formato Siemens (byte.bit per i Bool).
"""

from dataclasses import dataclass

import snap7.util

EXPECTED_DB_VERSION = 1  # TODO: allineare al valore scritto in VersionDB sul PLC

# Offset (in byte) dei campi non-Bool
OFFSET_VERSION_DB = 0
OFFSET_CYCLE_COUNTER = 2
OFFSET_MISSION_ID = 6
OFFSET_STEP_NUMBER = 10
OFFSET_OPERATING_MODE = 12
OFFSET_TASK_TYPE = 14

# I sei bit discreti vivono tutti nel byte a offset 16
OFFSET_DISCRETE_BYTE = 16
BIT_MISSION_ACTIVE = 0
BIT_MISSION_PAUSE = 1
BIT_WAITING_INTERACTION = 2
BIT_MOVEMENT_DETECTED = 3
BIT_PICKUP_ACTIVE = 4
BIT_DEPOSIT_ACTIVE = 5

OFFSET_CRANE_POS_X = 18
OFFSET_CRANE_POS_Y = 22
OFFSET_CRANE_POS_Z = 26

OFFSET_TARGET_PICKUP_X = 30
OFFSET_TARGET_PICKUP_Y = 34
OFFSET_TARGET_PICKUP_Z = 38

OFFSET_TARGET_DEPOSIT_X = 42
OFFSET_TARGET_DEPOSIT_Y = 46
OFFSET_TARGET_DEPOSIT_Z = 50

OFFSET_LASER_PICKUP_X = 54
OFFSET_LASER_PICKUP_Y = 58
OFFSET_LASER_PICKUP_Z = 62

OFFSET_LASER_DEPOSIT_X = 66
OFFSET_LASER_DEPOSIT_Y = 70
OFFSET_LASER_DEPOSIT_Z = 74

OFFSET_LIFTED_WEIGHT = 78

DB_SIZE = 82  # OFFSET_LIFTED_WEIGHT + 4 byte (REAL)


@dataclass
class CraneSnapshot:
    """Rappresentazione Python di una lettura completa del DB."""

    version_db: int
    cycle_counter: int
    mission_id: int
    step_number: int
    operating_mode: int
    task_type: int

    mission_active: bool
    mission_pause: bool
    waiting_interaction: bool
    movement_detected: bool
    pickup_active: bool
    deposit_active: bool

    pos_x: float
    pos_y: float
    pos_z: float

    target_pickup_x: float
    target_pickup_y: float
    target_pickup_z: float

    target_deposit_x: float
    target_deposit_y: float
    target_deposit_z: float

    laser_pickup_x: float
    laser_pickup_y: float
    laser_pickup_z: float

    laser_deposit_x: float
    laser_deposit_y: float
    laser_deposit_z: float

    lifted_weight: float


def parse_snapshot(buffer: bytearray) -> CraneSnapshot:
    """
    Converte il buffer grezzo letto dal DB (tramite s7_client) in un
    CraneSnapshot con tutti i campi già tipizzati.

    NOTA: usa snap7.util per il parsing invece di struct.unpack manuale,
    perché gestisce correttamente l'endianness Siemens (big-endian) e gli
    offset a bit per i Bool.
    """
    return CraneSnapshot(
        version_db=snap7.util.get_int(buffer, OFFSET_VERSION_DB),
        cycle_counter=snap7.util.get_dint(buffer, OFFSET_CYCLE_COUNTER),
        mission_id=snap7.util.get_dint(buffer, OFFSET_MISSION_ID),
        step_number=snap7.util.get_int(buffer, OFFSET_STEP_NUMBER),
        operating_mode=snap7.util.get_int(buffer, OFFSET_OPERATING_MODE),
        task_type=snap7.util.get_int(buffer, OFFSET_TASK_TYPE),
        mission_active=snap7.util.get_bool(buffer, OFFSET_DISCRETE_BYTE, BIT_MISSION_ACTIVE),
        mission_pause=snap7.util.get_bool(buffer, OFFSET_DISCRETE_BYTE, BIT_MISSION_PAUSE),
        waiting_interaction=snap7.util.get_bool(
            buffer, OFFSET_DISCRETE_BYTE, BIT_WAITING_INTERACTION
        ),
        movement_detected=snap7.util.get_bool(
            buffer, OFFSET_DISCRETE_BYTE, BIT_MOVEMENT_DETECTED
        ),
        pickup_active=snap7.util.get_bool(buffer, OFFSET_DISCRETE_BYTE, BIT_PICKUP_ACTIVE),
        deposit_active=snap7.util.get_bool(buffer, OFFSET_DISCRETE_BYTE, BIT_DEPOSIT_ACTIVE),
        pos_x=snap7.util.get_real(buffer, OFFSET_CRANE_POS_X),
        pos_y=snap7.util.get_real(buffer, OFFSET_CRANE_POS_Y),
        pos_z=snap7.util.get_real(buffer, OFFSET_CRANE_POS_Z),
        target_pickup_x=snap7.util.get_real(buffer, OFFSET_TARGET_PICKUP_X),
        target_pickup_y=snap7.util.get_real(buffer, OFFSET_TARGET_PICKUP_Y),
        target_pickup_z=snap7.util.get_real(buffer, OFFSET_TARGET_PICKUP_Z),
        target_deposit_x=snap7.util.get_real(buffer, OFFSET_TARGET_DEPOSIT_X),
        target_deposit_y=snap7.util.get_real(buffer, OFFSET_TARGET_DEPOSIT_Y),
        target_deposit_z=snap7.util.get_real(buffer, OFFSET_TARGET_DEPOSIT_Z),
        laser_pickup_x=snap7.util.get_real(buffer, OFFSET_LASER_PICKUP_X),
        laser_pickup_y=snap7.util.get_real(buffer, OFFSET_LASER_PICKUP_Y),
        laser_pickup_z=snap7.util.get_real(buffer, OFFSET_LASER_PICKUP_Z),
        laser_deposit_x=snap7.util.get_real(buffer, OFFSET_LASER_DEPOSIT_X),
        laser_deposit_y=snap7.util.get_real(buffer, OFFSET_LASER_DEPOSIT_Y),
        laser_deposit_z=snap7.util.get_real(buffer, OFFSET_LASER_DEPOSIT_Z),
        lifted_weight=snap7.util.get_real(buffer, OFFSET_LIFTED_WEIGHT),
    )
