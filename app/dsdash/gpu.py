"""GPU load, GPU memory and temperature.

NVIDIA's driver library (NVML) is used when it's there, as it gives a real GPU temperature.
Windows performance counters fill in the rest, and work on any vendor without admin rights.
Anything a machine doesn't report comes back as None.
"""
import ctypes
import re
from ctypes import wintypes
from typing import Dict, Optional

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2

ENGINES = r"\GPU Engine(*)\Utilization Percentage"
DEDICATED = r"\GPU Adapter Memory(*)\Dedicated Usage"
SHARED = r"\GPU Adapter Memory(*)\Shared Usage"
THERMAL = r"\Thermal Zone Information(*)\High Precision Temperature"

ENGINE_NAME = re.compile(r"luid_\w+?_phys_\d+_eng_\d+")
ADAPTER_NAME = re.compile(r"luid_\w+?_phys_\d+")


class _Value(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("value", _Value)]


def busiest_engine(samples: Dict[str, float]) -> Optional[float]:
    """Load as Task Manager shows it: each engine summed over processes, then the busiest."""
    engines: Dict[str, float] = {}
    for name, value in samples.items():
        match = ENGINE_NAME.search(name)
        if match:
            engines[match.group()] = engines.get(match.group(), 0.0) + value
    return min(100.0, max(engines.values())) if engines else None


def adapter_memory(dedicated: Dict[str, float], shared: Dict[str, float]) -> Optional[float]:
    """Bytes in use on the busiest adapter. An integrated GPU mostly uses shared memory."""
    adapters: Dict[str, float] = {}
    for samples in (dedicated, shared):
        for name, value in samples.items():
            match = ADAPTER_NAME.search(name)
            if match:
                adapters[match.group()] = adapters.get(match.group(), 0.0) + value
    return max(adapters.values()) if adapters else None


def hottest_celsius(samples: Dict[str, float]) -> Optional[float]:
    """The counter is in tenths of a kelvin. Zones that read nonsense are ignored."""
    values = [value / 10 - 273.15 for value in samples.values()]
    values = [value for value in values if 0 < value < 130]
    return max(values) if values else None


def merge(preferred, fallback):
    """Takes each reading from the first source that has it."""
    return tuple(first if first is not None else second for first, second in zip(preferred, fallback))


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class Nvml:
    """The first NVIDIA GPU. `load` lets tests supply a fake library."""

    PATHS = ("nvml.dll", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll")

    def __init__(self, load=None):
        self.lib = None
        self.handle = ctypes.c_void_p()
        for path in self.PATHS:
            try:
                lib = (load or ctypes.WinDLL)(path)
                if lib.nvmlInit_v2() == 0 and lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.handle)) == 0:
                    self.lib = lib
                    return
            except (AttributeError, OSError):
                continue

    def read(self):
        """Load in percent, memory in bytes and temperature in Celsius, or None for each."""
        if not self.lib:
            return None, None, None
        utilization, memory, temperature = _NvmlUtilization(), _NvmlMemory(), ctypes.c_uint()
        ok = self.lib.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(utilization)) == 0
        has_memory = self.lib.nvmlDeviceGetMemoryInfo(self.handle, ctypes.byref(memory)) == 0
        has_temperature = self.lib.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(temperature)) == 0
        return (float(utilization.gpu) if ok else None, float(memory.used) if has_memory else None,
                float(temperature.value) if has_temperature else None)


class GpuSensors:
    def __init__(self):
        self.available = False
        self.nvml = Nvml()
        try:
            self._pdh = ctypes.WinDLL("pdh")
            self._query = wintypes.HANDLE()
            if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)):
                return
            self._counters = {path: self._add(path) for path in (ENGINES, DEDICATED, SHARED, THERMAL)}
            self._pdh.PdhCollectQueryData(self._query)
            self.available = True
        except (AttributeError, OSError):    # Not Windows, or no PDH.
            pass

    def _add(self, path: str):
        counter = wintypes.HANDLE()
        status = self._pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter))
        return None if status else counter

    def _samples(self, counter) -> Dict[str, float]:
        if counter is None:
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        get = self._pdh.PdhGetFormattedCounterArrayW
        get.restype = wintypes.DWORD
        fmt = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        if get(counter, fmt, ctypes.byref(size), ctypes.byref(count), None) != PDH_MORE_DATA:
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        if get(counter, fmt, ctypes.byref(size), ctypes.byref(count), buffer):
            return {}
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        return {items[i].name: items[i].value.value for i in range(count.value) if items[i].value.status in (0, 1)}

    def _counter_values(self):
        if not self.available or self._pdh.PdhCollectQueryData(self._query):
            return None, None, None
        counters = self._counters
        return (busiest_engine(self._samples(counters[ENGINES])),
                adapter_memory(self._samples(counters[DEDICATED]), self._samples(counters[SHARED])),
                hottest_celsius(self._samples(counters[THERMAL])))

    def read(self):
        """Returns load in percent, memory in bytes and temperature in Celsius."""
        return merge(self.nvml.read(), self._counter_values())
