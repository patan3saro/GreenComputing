"""
Controller — beacon ingestion, ranking, and expiry management.

Stores two parallel views of the world:
  - `beacons`       : NOMINAL beacons declared by executors (used in Stage 1
                       allocation, possibly biased by misreporting).
  - `real_beacons`  : REALIZED beacons (ground-truth ex-post) used in
                       Stage 2 incentive sharing.

Internal structure (per view):
  - `beacons_by_id : dict[int, BeaconEntry]`  - primary lookup, O(1) update.
  - `_heap : list`                            - lazy-deleted priority queue
                                                  for ranking; entries become
                                                  stale and are skipped on
                                                  pop.

Ranking key (Sec. III of the paper):
    (-expected_dwell_time, -energy_available, -cpu_capacity, counter)

The counter is a monotone tie-breaker that prevents heapq from comparing
the dict payload when keys collide.
"""

import heapq
from dataclasses import dataclass, asdict
from typing import Optional


# ETSI CAM standard expiry (Sec. III, paper)
DEFAULT_VEHICLE_EXPIRY_MS = 500
DEFAULT_CLOUD_EXPIRY_MS = 900_000      # 15 min
DEFAULT_CLOUD_DWELL = 1e6              # proxy for "infinite" dwell


@dataclass
class BeaconEntry:
    """Decoded beacon stored at the Controller side."""
    node_type: str                   # 'vehicle' or 'cloud'
    instant_sec: float               # beacon timestamp at emitter
    beacon_id: int
    cpu_capacity: float
    queue_capacity: int
    cpu_power: float
    tx_power: float
    energy_available: float
    dollars_per_kwh: float
    ul_datarate: float
    dl_datarate: float
    position_x: float
    position_y: float
    speed: float
    dwell_time: float                # estimated dwell time under gNB coverage
    received_at_ms: float            # controller wall-clock at reception

    def as_dict(self):
        return asdict(self)


def _decode_beacon_tuple(tup, node_type, dwell_time, received_at_ms):
    """
    Convert the raw 13-tuple emitted by Vehicle/Cloud.create_beacon() into
    a typed BeaconEntry.
    """
    return BeaconEntry(
        node_type=node_type,
        instant_sec=tup[0],
        beacon_id=tup[1],
        cpu_capacity=tup[2],
        queue_capacity=tup[3],
        cpu_power=tup[4],
        tx_power=tup[5],
        energy_available=tup[6],
        dollars_per_kwh=tup[7],
        ul_datarate=tup[8],
        dl_datarate=tup[9],
        position_x=tup[10],
        position_y=tup[11],
        speed=tup[12],
        dwell_time=dwell_time,
        received_at_ms=received_at_ms,
    )


def _ranking_key(entry: BeaconEntry):
    """
    Paper Sec. III ranking criteria:
      1. expected dwell time      (higher is better)
      2. energy availability      (higher is better)
      3. computational capacity   (higher is better)
    Negated so that heapq (min-heap) returns the best node first.
    """
    return (
        -entry.dwell_time,
        -entry.energy_available,
        -entry.cpu_capacity,
    )


class BeaconStore:
    """
    One side of the Controller's beacon storage (nominal or realized).
    Encapsulates the dict + lazy heap pattern.
    """

    def __init__(self):
        self._by_id: dict[int, BeaconEntry] = {}
        self._heap: list = []
        self._counter = 0          # monotone tie-breaker for heap

    def upsert(self, entry: BeaconEntry):
        """Insert or replace a beacon for the given node id."""
        self._by_id[entry.beacon_id] = entry
        self._counter += 1
        heapq.heappush(
            self._heap,
            (_ranking_key(entry), self._counter, entry.beacon_id),
        )
        # Compact the heap if it grows too far above the dict size.
        if len(self._heap) > 4 * max(len(self._by_id), 8):
            self._compact_heap()

    def _compact_heap(self):
        """Rebuild the heap from current `_by_id` to discard stale entries."""
        self._heap = [
            (_ranking_key(e), self._counter + i, bid)
            for i, (bid, e) in enumerate(self._by_id.items())
        ]
        self._counter += len(self._by_id)
        heapq.heapify(self._heap)

    def remove_expired(self, current_time_ms,
                       vehicle_expiry_ms=DEFAULT_VEHICLE_EXPIRY_MS,
                       cloud_expiry_ms=DEFAULT_CLOUD_EXPIRY_MS):
        """
        Drop entries whose received_at_ms is older than their type-specific
        expiry. Operates on `_by_id`; the heap is reconciled lazily on pop.
        """
        expired_ids = []
        for bid, entry in self._by_id.items():
            exp = vehicle_expiry_ms if entry.node_type == 'vehicle' else cloud_expiry_ms
            if current_time_ms - entry.received_at_ms > exp:
                expired_ids.append(bid)
        for bid in expired_ids:
            del self._by_id[bid]

    def all_active(self) -> list[BeaconEntry]:
        """Return all currently active beacons (insertion-time order)."""
        return list(self._by_id.values())

    def top_k(self, k: int) -> list[BeaconEntry]:
        """
        Return the top-k beacons by ranking key, with lazy deletion of stale
        heap entries (those that were superseded by `upsert` or removed).
        """
        result = []
        kept = []
        seen_ids = set()
        while self._heap and len(result) < k:
            key, ctr, bid = heapq.heappop(self._heap)
            entry = self._by_id.get(bid)
            if entry is None:
                continue                              # entry was removed
            if bid in seen_ids:
                continue                              # already emitted; this is a stale duplicate
            if _ranking_key(entry) != key:
                continue                              # superseded by a newer upsert
            result.append(entry)
            seen_ids.add(bid)
            kept.append((key, ctr, bid))
        # restore the entries we popped but want to keep in the heap
        for item in kept:
            heapq.heappush(self._heap, item)
        return result

    def __len__(self):
        return len(self._by_id)

    def __contains__(self, beacon_id):
        return beacon_id in self._by_id

    def get(self, beacon_id) -> Optional[BeaconEntry]:
        return self._by_id.get(beacon_id)


class Controller:
    """
    Centralized controller co-located with the gNodeB.

    Maintains two BeaconStore instances:
      - `.nominal` : beacons declared by executors (Stage 1 input).
      - `.realized`: ground-truth beacons (Stage 2 input).
    """

    def __init__(self, gnb_position_x=900, gnb_position_y=900):
        self.gnb_position_x = gnb_position_x
        self.gnb_position_y = gnb_position_y
        self.nominal = BeaconStore()
        self.realized = BeaconStore()

    # ------------------------------------------------------------------
    #                       Vehicle beacons
    # ------------------------------------------------------------------
    def receive_vehicle_beacon(self, beacon_tuple, current_time_ms, dwell_time):
        """Ingest a nominal beacon from a vehicle."""
        entry = _decode_beacon_tuple(
            beacon_tuple, node_type='vehicle',
            dwell_time=dwell_time, received_at_ms=current_time_ms,
        )
        self.nominal.upsert(entry)

    def receive_vehicle_real_beacon(self, beacon_tuple, current_time_ms, dwell_time):
        """Ingest a realized (ground-truth) beacon from a vehicle."""
        entry = _decode_beacon_tuple(
            beacon_tuple, node_type='vehicle',
            dwell_time=dwell_time, received_at_ms=current_time_ms,
        )
        self.realized.upsert(entry)

    # ------------------------------------------------------------------
    #                       Cloud beacons
    # ------------------------------------------------------------------
    def receive_cloud_beacon(self, beacon_tuple, current_time_ms):
        """Ingest a nominal beacon from a cloud node."""
        entry = _decode_beacon_tuple(
            beacon_tuple, node_type='cloud',
            dwell_time=DEFAULT_CLOUD_DWELL, received_at_ms=current_time_ms,
        )
        self.nominal.upsert(entry)

    def receive_cloud_real_beacon(self, beacon_tuple, current_time_ms):
        """Ingest a realized (ground-truth) beacon from a cloud node."""
        entry = _decode_beacon_tuple(
            beacon_tuple, node_type='cloud',
            dwell_time=DEFAULT_CLOUD_DWELL, received_at_ms=current_time_ms,
        )
        self.realized.upsert(entry)

    # ------------------------------------------------------------------
    #                       Expiry management
    # ------------------------------------------------------------------
    def clean_expired_beacons(self, current_time_ms,
                              vehicle_expiry_ms=DEFAULT_VEHICLE_EXPIRY_MS,
                              cloud_expiry_ms=DEFAULT_CLOUD_EXPIRY_MS):
        """Drop expired entries from BOTH the nominal and realized stores."""
        self.nominal.remove_expired(current_time_ms, vehicle_expiry_ms, cloud_expiry_ms)
        self.realized.remove_expired(current_time_ms, vehicle_expiry_ms, cloud_expiry_ms)

    # ------------------------------------------------------------------
    #                       Ranking (Sec. III)
    # ------------------------------------------------------------------
    def get_top_nodes(self, count, source='nominal') -> list[BeaconEntry]:
        """
        Return the top-`count` beacons by paper ranking criteria.
        `source` selects 'nominal' (Stage 1) or 'realized' (Stage 2 audit).
        """
        store = self.nominal if source == 'nominal' else self.realized
        return store.top_k(count)

    # ------------------------------------------------------------------
    #                       Back-compat accessors
    # ------------------------------------------------------------------
    # The legacy code reads `controller.beacons` as a list and iterates over
    # it with `b[1]` (id) and `b[2]` (dict). We expose properties returning
    # tuples in the OLD format so the existing `value_function`-style
    # consumers keep working until they are refactored.

    @property
    def beacons(self) -> list:
        """Legacy view of the nominal store as list of old-format tuples."""
        return [self._to_legacy_tuple(e) for e in self.nominal.all_active()]

    @property
    def real_beacons(self) -> list:
        """Legacy view of the realized store as list of old-format tuples."""
        return [self._to_legacy_tuple(e) for e in self.realized.all_active()]

    @staticmethod
    def _to_legacy_tuple(entry: BeaconEntry):
        """
        Old format expected by `value_function.optimize_task_allocation`:
            (priority_key, beacon_id, details_dict, received_at_ms)
        """
        priority = (-entry.dwell_time, -entry.energy_available, -entry.cpu_capacity)
        details = {
            "type": entry.node_type,
            "instant_sec": entry.instant_sec,
            "beacon_id": entry.beacon_id,
            "cpu_capacity": entry.cpu_capacity,
            "queue_capacity": entry.queue_capacity,
            "cpu_power": entry.cpu_power,
            "tx_power": entry.tx_power,
            "energy_available": entry.energy_available,
            "dollars_per_kwh": entry.dollars_per_kwh,
            "ul_datarate": entry.ul_datarate,
            "dl_datarate": entry.dl_datarate,
            "position_x": entry.position_x,
            "position_y": entry.position_y,
            "speed": entry.speed,
        }
        return (priority, entry.beacon_id, details, entry.received_at_ms)