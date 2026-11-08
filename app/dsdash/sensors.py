"""Reads PC stats once per tick. Rendering only ever sees a Stats value."""
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from .gpu import GpuSensors

HISTORY = 256


@dataclass
class Stats:
    cpu_percent: float = 0.0
    cpu_history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    ram_percent: float = 0.0
    ram_history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    net_up: float = 0.0     # Bytes per second
    net_down: float = 0.0
    usb_connected: bool = False
    gpu_percent: Optional[float] = None
    gpu_history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    gpu_memory_gb: Optional[float] = None
    temperature: Optional[float] = None     # Celsius
    net_history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))


class Sensors:
    def __init__(self, disk_path: str = "C:\\"):
        import psutil
        self._psutil = psutil
        self._disk_path = disk_path
        self.stats = Stats()
        self._gpu = GpuSensors()
        psutil.cpu_percent()
        self._last_net = psutil.net_io_counters()
        self._last_time = time.monotonic()

    def update(self) -> Stats:
        psutil, stats = self._psutil, self.stats
        stats.cpu_percent = psutil.cpu_percent()
        stats.cpu_history.append(stats.cpu_percent)

        memory = psutil.virtual_memory()
        stats.ram_percent = memory.percent
        stats.ram_history.append(memory.percent)
        stats.ram_used_gb = memory.used / 2**30
        stats.ram_total_gb = memory.total / 2**30

        disk = shutil.disk_usage(self._disk_path)
        stats.disk_percent = disk.used * 100 / disk.total
        stats.disk_free_gb = disk.free / 2**30

        now = time.monotonic()
        net = psutil.net_io_counters()
        elapsed = max(now - self._last_time, 0.001)
        stats.net_up = (net.bytes_sent - self._last_net.bytes_sent) / elapsed
        stats.net_down = (net.bytes_recv - self._last_net.bytes_recv) / elapsed
        stats.net_history.append(stats.net_up + stats.net_down)
        self._last_net, self._last_time = net, now

        load, memory_bytes, stats.temperature = self._gpu.read()
        stats.gpu_percent = load
        stats.gpu_history.append(load or 0.0)
        stats.gpu_memory_gb = None if memory_bytes is None else memory_bytes / 2**30
        return stats
