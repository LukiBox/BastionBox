"""The Hardware Optimizer — "fit the AI to the machine", with the math shown.

Local models are only as good as how well they fit the box they run on. This
module (1) detects the hardware, (2) given a model file, computes a concrete
offload plan — how many layers on the GPU, what context length fits, KV-cache
quantization — and (3) shows the arithmetic so the user can trust the answer
instead of taking a black box on faith.

Everything degrades gracefully and never crashes: a machine with no GPU, or a
mocked ``0 GB`` config, yields a valid CPU-only plan with honestly-set
expectations. Detection uses only what is safely available (``os``,
``psutil`` if present, ``nvidia-smi``/``wmic`` if present); every probe is
wrapped so a missing tool means "unknown", not an exception.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class HardwareProfile:
    cpu_cores: int = 0
    cpu_threads: int = 0
    has_avx2: bool = False
    has_avx512: bool = False
    ram_gb: float = 0.0
    gpu_name: str = ""
    vram_gb: float = 0.0
    gpu_backend: str = "none"   # cuda / vulkan / metal / none

    def summary(self) -> str:
        gpu = f"{self.gpu_name} ({self.vram_gb:.0f} GB, {self.gpu_backend})" \
            if self.vram_gb else "no discrete GPU"
        return (f"{self.cpu_cores}C/{self.cpu_threads}T, {self.ram_gb:.0f} GB RAM, "
                f"{gpu}")


@dataclass
class OffloadPlan:
    """A fit-to-machine plan plus the human-readable math behind it."""

    gpu_layers: int
    total_layers: int
    context_length: int
    kv_cache_bits: int          # 16 (f16), 8, or 4 — KV quantization
    batch_size: int
    est_weights_gb: float
    est_kv_gb: float
    cpu_only: bool
    tier: str                   # "cpu" / "entry" / "workstation" / "server"
    notes: list[str] = field(default_factory=list)

    def explain(self) -> str:
        """The one-line 'show the math' string the wizard displays."""
        where = "CPU only" if self.cpu_only else \
            f"{self.gpu_layers}/{self.total_layers} layers on GPU"
        return (f"{self.est_weights_gb:.1f} GB weights + {self.est_kv_gb:.1f} GB "
                f"KV @ {self.context_length // 1024}k ctx → {where}")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detect() -> HardwareProfile:
    """Best-effort hardware probe. Never raises; unknowns stay at defaults."""
    p = HardwareProfile()
    p.cpu_cores = os.cpu_count() or 0
    p.cpu_threads = p.cpu_cores

    try:  # richer info if psutil is around, but we do not require it
        import psutil  # type: ignore
        p.cpu_cores = psutil.cpu_count(logical=False) or p.cpu_cores
        p.cpu_threads = psutil.cpu_count(logical=True) or p.cpu_threads
        p.ram_gb = round(psutil.virtual_memory().total / 1024**3, 1)
    except Exception:  # noqa: BLE001
        p.ram_gb = _ram_gb_fallback()

    p.has_avx2, p.has_avx512 = _detect_avx()
    _detect_gpu(p)
    return p


def _ram_gb_fallback() -> float:
    try:
        if hasattr(os, "sysconf"):  # POSIX
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                         / 1024**3, 1)
        import ctypes  # Windows
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX(); stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / 1024**3, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _detect_avx() -> tuple[bool, bool]:
    try:
        import cpuinfo  # type: ignore
        flags = set(cpuinfo.get_cpu_info().get("flags", []))
        return ("avx2" in flags,
                any(f.startswith("avx512") for f in flags))
    except Exception:  # noqa: BLE001
        return (True, False)  # AVX2 is a safe assumption on any modern x86-64


def _detect_gpu(p: HardwareProfile) -> None:
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5)
            line = out.stdout.strip().splitlines()[0]
            name, mem = [x.strip() for x in line.split(",")]
            p.gpu_name, p.vram_gb, p.gpu_backend = name, round(float(mem) / 1024, 1), "cuda"
            return
        except Exception:  # noqa: BLE001
            pass
    # Metal on Apple Silicon: unified memory acts as VRAM.
    if os.uname().sysname == "Darwin" if hasattr(os, "uname") else False:
        p.gpu_backend = "metal"
        p.vram_gb = p.ram_gb  # unified memory


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def plan(profile: HardwareProfile, *, model_size_gb: float, n_layers: int = 32,
         hidden_dim: int = 4096, requested_context: int = 16384) -> OffloadPlan:
    """Compute an offload plan for a model of *model_size_gb* on *profile*.

    The KV-cache estimate is the standard ``2 (K,V) * n_layers * ctx *
    hidden_dim * bytes_per_elem`` formula. We prefer the largest context that
    fits, then trade KV precision (f16 → q8 → q4) before giving up GPU layers.
    """
    notes: list[str] = []
    vram = max(profile.vram_gb, 0.0)
    ram = max(profile.ram_gb, 0.0)

    # Choose KV precision that keeps the cache affordable at the requested ctx.
    def kv_gb(ctx: int, bits: int) -> float:
        bytes_per = bits / 8
        return 2 * n_layers * ctx * hidden_dim * bytes_per / 1024**3

    context = requested_context
    kv_bits = 16
    # Shrink context to something sane if even q4 KV would be enormous.
    while kv_gb(context, 4) > max(vram, ram) * 0.6 and context > 2048:
        context //= 2
        notes.append(f"context reduced to {context} to fit KV cache")

    # Pick the finest KV precision that fits alongside weights on the GPU.
    est_kv = kv_gb(context, 16)
    for bits in (16, 8, 4):
        if model_size_gb + kv_gb(context, bits) <= vram * 0.92:
            kv_bits, est_kv = bits, kv_gb(context, bits)
            break
        kv_bits, est_kv = bits, kv_gb(context, bits)

    if vram <= 0:
        return OffloadPlan(
            gpu_layers=0, total_layers=n_layers, context_length=context,
            kv_cache_bits=8, batch_size=256,
            est_weights_gb=model_size_gb, est_kv_gb=kv_gb(context, 8),
            cpu_only=True, tier="cpu",
            notes=notes + [
                "No GPU detected — running on CPU. Expect slower generation; "
                "prefer a 3–8B Q4 model and keep context modest."])

    # How much of the model fits in VRAM after the KV cache?
    budget = vram * 0.92 - est_kv
    frac = min(1.0, max(0.0, budget / model_size_gb)) if model_size_gb else 1.0
    gpu_layers = int(math.floor(frac * n_layers))
    gpu_layers = max(0, min(n_layers, gpu_layers))
    if 0 < gpu_layers < n_layers:
        notes.append(f"partial offload — {n_layers - gpu_layers} layer(s) stay on "
                     f"CPU; generation is bottlenecked by the slowest tier")

    tier = ("server" if vram >= 24 else "workstation" if vram >= 12
            else "entry" if vram >= 6 else "cpu")
    return OffloadPlan(
        gpu_layers=gpu_layers, total_layers=n_layers, context_length=context,
        kv_cache_bits=kv_bits, batch_size=512 if gpu_layers == n_layers else 256,
        est_weights_gb=model_size_gb, est_kv_gb=est_kv,
        cpu_only=gpu_layers == 0, tier=tier, notes=notes)


def recommend_model_class(profile: HardwareProfile) -> str:
    """Honest, hardware-tiered guidance on what model class to run."""
    v = profile.vram_gb
    if v >= 24:
        return "30B+ (Q4/Q5) fits comfortably; or a 70B at Q4 with reduced context."
    if v >= 12:
        return "14B Q4/Q5 is the sweet spot; 30B MoE works with modest context."
    if v >= 6:
        return "7–9B Q4 recommended; expect ~20–40 t/s on a modern GPU."
    if profile.ram_gb >= 16:
        return "CPU-only: a 3–8B Q4 model is usable; keep context ≤8k for latency."
    return "Limited memory: use a 1–3B Q4 model; set expectations accordingly."
