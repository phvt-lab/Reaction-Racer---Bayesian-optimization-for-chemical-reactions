"""Built-in synthetic reaction model for demo and testing.

Produces plausible multi-metric results for *any* user-defined parameter set by
matching parameter names to chemical roles (temperature, catalyst, pressure,
solvent, time); unknown range parameters contribute a smooth hashed response.
"""

import hashlib
import math
import random
from typing import Iterable, Sequence

from core.campaign import ParameterSpec

DEFAULT_METRICS = ('Yield', 'Selectivity', 'Cost')
# Case-insensitive lookup: metric names are user-defined (e.g. "Yield").
_NOISE = {'yield': 1.2, 'selectivity': 1.5, 'cost': 0.4}

_rng = random.Random()


def _norm(value: float, spec: ParameterSpec) -> float:
    span = (spec.high - spec.low) or 1.0
    return min(1.0, max(0.0, (value - spec.low) / span))


def _bell(x: float, center: float, width: float) -> float:
    return math.exp(-0.5 * ((x - center) / width) ** 2)


def _unit(key: str) -> float:
    """Stable pseudo-random fraction in [0, 1) for arbitrary names."""
    digest = hashlib.md5(key.encode()).digest()
    return int.from_bytes(digest[:4], 'big') / 2**32


def evaluate(params: dict, specs: Sequence[ParameterSpec],
             metrics: Iterable[str]) -> dict[str, float]:
    """Return simulated metric values for one parameterization."""
    t = c = p = dur = None
    solvent_factor = 0.94
    generic = 0.0
    for spec in specs:
        value = params.get(spec.name)
        if value is None:
            continue
        name = spec.name.lower()
        if spec.kind == 'choice':
            if any(k in name for k in ('solvent', 'base', 'media')):
                solvent_factor = 0.88 + 0.12 * _unit(str(value))
            continue
        frac = _norm(float(value), spec)
        if 'temp' in name or name.startswith('t_'):
            t = frac
        elif 'cat' in name or 'load' in name:
            c = frac
        elif 'press' in name:
            p = frac
        elif 'time' in name or 'dur' in name:
            dur = frac
        else:
            generic += (_unit(spec.name) - 0.5) * frac

    # building blocks
    shape = _bell(t, 0.60, 0.28) if t is not None else 0.65 + 0.3 * generic
    cat_sat = 1.0 - math.exp(-2.5 * c) if c is not None else 0.85
    press_boost = 0.90 + 0.10 * p if p is not None else 1.0
    time_factor = _bell(dur, 0.5, 0.45) if dur is not None else 1.0

    yield_value = 95.0 * shape * cat_sat * press_boost * time_factor * solvent_factor
    sel_shape = _bell(t, 0.32, 0.30) if t is not None else 0.70 - 0.2 * generic
    selectivity_value = 92.0 * sel_shape * (1.0 - (0.18 * c if c is not None else 0.0)) \
        * solvent_factor
    cost_value = (8.0
                  + (6.0 * c if c is not None else 2.0)
                  + 5.0 * solvent_factor
                  + (0.04 * max(0.0, (t or 0.0)) * 200.0 if t is not None else 0.0)
                  + (1.5 * p if p is not None else 0.0)
                  + (2.0 * generic if abs(generic) > 1e-9 else 0.0))

    known = {'yield': yield_value, 'selectivity': selectivity_value, 'cost': cost_value}
    result = {}
    for metric in metrics:
        key = metric.lower()
        base = known.get(key)
        if base is None:  # user-defined metric: smooth param-driven response
            base = 50.0 + 40.0 * (generic + _unit(metric) - 0.5)
        sigma = _NOISE.get(key, 1.0)
        result[metric] = round(base + _rng.gauss(0.0, sigma), 3)
    return result
