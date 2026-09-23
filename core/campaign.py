"""Ax-backed Bayesian optimization campaign scoped to one user workspace."""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from datetime import datetime, timezone

from ax.analysis.plotly.cross_validation import CrossValidationPlot
from ax.api.client import Client
from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig
from ax.utils.common.sympy import parse_objective_expression

from core import storage

Direction = Literal['maximize', 'minimize', 'record']

_NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_NAME_HINT = ('must start with a letter and contain only letters, digits and '
              'underscores (Ax uses names in model expressions and tables)')


@dataclass(frozen=True)
class MetricSpec:
    name: str
    direction: Direction = 'maximize'


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: Literal['range', 'choice'] = 'range'
    low: float = 0.0
    high: float = 1.0
    unit: str = ''
    log_scale: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignConfig:
    name: str
    metrics: tuple[MetricSpec, ...]
    parameters: tuple[ParameterSpec, ...]
    simulation: bool = True

    @property
    def objectives(self) -> tuple[MetricSpec, ...]:
        return tuple(m for m in self.metrics if m.direction != 'record')

    @property
    def primary(self) -> MetricSpec:
        return self.objectives[0]

    @property
    def tracking_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.metrics if m.direction == 'record')

    @property
    def objective_expr(self) -> str:
        # Ax objective string: comma-separated terms, leading '-' minimizes.
        return ', '.join(('-' if m.direction == 'minimize' else '') + m.name
                         for m in self.objectives)

    @property
    def param_map(self) -> dict[str, ParameterSpec]:
        return {p.name: p for p in self.parameters}


@dataclass(frozen=True)
class TrialRef:
    trial_index: int
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Record:
    trial_index: int
    parameters: dict[str, Any]
    metrics: dict[str, float]


def format_value(value: Any) -> str:
    """Display text for a metric value: full fixed-point digits.

    Keeps every recorded digit (no ``%.3g``-style rounding) and never falls
    back to scientific notation, so 23500.0 shows as ``23500`` instead of
    ``2.35e+04``.
    """
    text = format(Decimal(repr(float(value))), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def validate_config(cfg: CampaignConfig) -> None:
    """Raise ValueError with a user-facing message if the config can't run."""
    if not cfg.name.strip():
        raise ValueError('Campaign name is required.')
    if not cfg.metrics:
        raise ValueError('At least one metric is required.')
    metric_names = [m.name for m in cfg.metrics]
    for name in metric_names:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f'Metric name "{name}" {_NAME_HINT}.')
    duplicates = {n for n in metric_names if metric_names.count(n) > 1}
    if duplicates:
        raise ValueError('Duplicate metric name(s): ' + ', '.join(sorted(duplicates)))
    if not cfg.objectives:
        raise ValueError('At least one metric must be Maximize or Minimize '
                         '(record-only metrics cannot drive the optimizer).')
    # Ax parses objective names through sympy, which rejects Python keywords
    # and sympy builtins ("yield", "lambda", "gamma", ...) as bare names.
    for metric in cfg.objectives:
        try:
            parse_objective_expression(metric.name)
        except Exception:
            alternative = metric.name.capitalize()
            try:
                parse_objective_expression(alternative)
            except Exception:
                alternative = metric.name + '_value'
            raise ValueError(
                f'Metric name "{metric.name}" is a reserved word in Ax '
                f'objective expressions — rename it to "{alternative}".'
            ) from None
    if not cfg.parameters:
        raise ValueError('At least one parameter is required.')
    param_names = [p.name for p in cfg.parameters]
    for name in param_names:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f'Parameter name "{name}" {_NAME_HINT}.')
    dup_params = {n for n in param_names if param_names.count(n) > 1}
    if dup_params:
        raise ValueError('Duplicate parameter name(s): ' + ', '.join(sorted(dup_params)))
    clash = set(param_names) & set(metric_names)
    if clash:
        raise ValueError('Name used as both parameter and metric: '
                         + ', '.join(sorted(clash)))
    for p in cfg.parameters:
        if p.kind == 'range':
            if not p.low < p.high:
                raise ValueError(f'{p.name}: low must be < high.')
            if p.log_scale and p.low <= 0:
                raise ValueError(f'{p.name}: log scale requires low > 0.')
        else:
            choices = [c for c in p.choices if c]
            if len(set(choices)) < 2:
                raise ValueError(f'{p.name}: need ≥2 distinct comma-separated choices.')


def _config_to_dict(cfg: CampaignConfig) -> dict[str, Any]:
    return {
        'name': cfg.name,
        'simulation': cfg.simulation,
        'metrics': [{'name': m.name, 'direction': m.direction} for m in cfg.metrics],
        'parameters': [
            {'name': p.name, 'kind': p.kind, 'low': p.low, 'high': p.high,
             'unit': p.unit, 'log_scale': p.log_scale, 'choices': list(p.choices)}
            for p in cfg.parameters
        ],
    }


def _config_from_dict(payload: dict[str, Any]) -> CampaignConfig:
    metrics = tuple(
        MetricSpec(name=str(m['name']), direction=m.get('direction', 'maximize'))
        for m in payload['metrics'])
    for m in metrics:
        if m.direction not in ('maximize', 'minimize', 'record'):
            raise ValueError(f'Unknown direction for metric {m.name}: {m.direction}')
    parameters = tuple(
        ParameterSpec(
            name=str(p['name']), kind=p.get('kind', 'range'),
            low=float(p.get('low', 0.0)), high=float(p.get('high', 1.0)),
            unit=str(p.get('unit', '')), log_scale=bool(p.get('log_scale', False)),
            choices=tuple(str(c) for c in p.get('choices', ())),
        )
        for p in payload['parameters'])
    cfg = CampaignConfig(
        name=str(payload['name']), metrics=metrics, parameters=parameters,
        simulation=bool(payload.get('simulation', True)))
    validate_config(cfg)
    return cfg


def _ax_parameter(p: ParameterSpec):
    if p.kind == 'choice':
        return ChoiceParameterConfig(name=p.name, values=list(p.choices),
                                     parameter_type='str')
    return RangeParameterConfig(
        name=p.name, bounds=(float(p.low), float(p.high)), parameter_type='float',
        scaling='log' if p.log_scale else None)


def _cell(value: Any) -> Any:
    """Normalize a DataFrame cell to a plain Python value."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise ValueError('nan')
    if hasattr(value, 'item'):  # numpy scalar
        value = value.item()
    return value


def _axis_values(spec: ParameterSpec, n: int) -> list[float]:
    low, high = float(spec.low), float(spec.high)
    if n <= 1 or high <= low:
        return [low]
    if spec.log_scale and low > 0:
        ratio = high / low
        return [low * ratio ** (i / (n - 1)) for i in range(n)]
    return [low + (high - low) * i / (n - 1) for i in range(n)]


def _extract_r2(cards: Any) -> dict[str, float]:
    """Walk AnalysisCards and pull metric -> R² from the CV summary table."""
    found: dict[str, float] = {}
    stack = list(cards or ())
    while stack:
        card = stack.pop()
        children = getattr(card, 'children', None)
        if children:
            stack.extend(children)
        df = getattr(card, 'df', None)
        if df is not None and hasattr(df, 'columns') \
                and 'Metric' in df.columns and 'R²' in df.columns:
            for _, row in df.iterrows():
                try:
                    found[str(row['Metric'])] = float(row['R²'])
                except (TypeError, ValueError):
                    continue
    return found


class CampaignService:
    """Own one Ax ``Client`` and its config for a selected campaign."""

    def __init__(self, username: str, campaign_id: str) -> None:
        self._username = username
        self._campaign_id = campaign_id
        self._lock = threading.RLock()
        self._client: Client | None = None
        self._config: CampaignConfig | None = None
        self._finished = False
        self._accuracy: dict[str, float] | None = None
        # Lock-free read snapshots, replaced atomically under ``_lock`` after
        # every mutation so page renders never wait on a long suggest/fit.
        self._records: list[Record] = []
        self._pending: list[TrialRef] = []
        self._pareto: frozenset[int] = frozenset()

    @property
    def campaign_id(self) -> str:
        return self._campaign_id

    def _paths_ready(self) -> tuple[str, str]:
        return self._username, self._campaign_id

    # ------------------------------------------------------------------ state

    def load(self) -> None:
        with self._lock:
            username, campaign_id = self._paths_ready()
            payload = storage.load(username, campaign_id)
            if payload is None:
                storage.clear(username, campaign_id)
                return
            try:
                cfg = _config_from_dict(payload['config'])
                self._finished = bool(payload.get('finished', False))
            except (KeyError, TypeError, ValueError):
                storage.clear(username, campaign_id)
                return
            snapshot = storage.snapshot_path(username, campaign_id)
            if not snapshot.exists():
                storage.clear(username, campaign_id)
                return
            try:
                client = Client.load_from_json_file(str(snapshot))
            except Exception:
                snapshot.rename(snapshot.with_suffix('.json.corrupt'))
                storage.clear(username, campaign_id)
                return
            self._client, self._config = client, cfg
            self._accuracy = None
            self._rebuild_read_cache()
            self._save_config()

    def is_active(self) -> bool:
        return self._client is not None

    @property
    def config(self) -> CampaignConfig:
        return self._require_cfg()

    @property
    def finished(self) -> bool:
        return self._finished

    def _require(self) -> Client:
        if self._client is None:
            raise RuntimeError('No active campaign.')
        return self._client

    def _require_cfg(self) -> CampaignConfig:
        if self._config is None:
            raise RuntimeError('No active campaign.')
        return self._config

    # ------------------------------------------------------------- lifecycle

    def create(self, cfg: CampaignConfig) -> None:
        validate_config(cfg)
        with self._lock:
            client = Client(random_seed=42)
            client.configure_experiment(
                parameters=[_ax_parameter(p) for p in cfg.parameters],
                name=cfg.name.strip())
            client.configure_optimization(objective=cfg.objective_expr)
            if cfg.tracking_names:
                client.configure_tracking_metrics(list(cfg.tracking_names))
            self._client, self._config = client, cfg
            self._finished = False
            self._accuracy = None
            self._rebuild_read_cache()
            self._save_config()
            self._write_snapshot()

    def finish(self) -> None:
        with self._lock:
            self._require()
            self._finished = True
            self._save_config()

    def _save_config(self) -> None:
        username, campaign_id = self._paths_ready()
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        previous = storage.load(username, campaign_id) or {}
        storage.save(username, campaign_id, {
            'version': 1,
            'config': _config_to_dict(self._require_cfg()),
            'finished': self._finished,
            'completed': len(self._records),
            'running': len(self._pending),
            'created_at': previous.get('created_at', now),
            'updated_at': now,
        })

    def _write_snapshot(self) -> None:
        username, campaign_id = self._paths_ready()
        path = storage.snapshot_path(username, campaign_id)
        tmp = path.with_suffix('.json.tmp')
        self._require().save_to_json_file(str(tmp))
        tmp.replace(path)  # atomic

    # -------------------------------------------------------- experiment loop

    def suggest(self, count: int) -> list[TrialRef]:
        with self._lock:
            client = self._require()
            trials = client.get_next_trials(max_trials=max(1, int(count)))
            self._write_snapshot()
            self._rebuild_read_cache()
            self._save_config()
            return [TrialRef(int(index), dict(params))
                    for index, params in sorted(trials.items())]

    def complete(self, trial_index: int, values: dict[str, float]) -> None:
        with self._lock:
            cfg = self._require_cfg()
            unknown = set(values) - {m.name for m in cfg.metrics}
            if unknown:
                raise ValueError('Unknown metric(s): ' + ', '.join(sorted(unknown)))
            clean: dict[str, float] = {}
            for metric in cfg.metrics:
                if metric.name not in values:
                    continue
                number = float(values[metric.name])
                if not math.isfinite(number):
                    raise ValueError(f'{metric.name} must be a finite number.')
                clean[metric.name] = number
            missing = [m.name for m in cfg.objectives if m.name not in clean]
            if missing:
                raise ValueError('Missing objective value(s): ' + ', '.join(missing))
            self._require().complete_trial(trial_index=trial_index, raw_data=clean)
            self._write_snapshot()
            self._rebuild_read_cache()
            self._save_config()
            self._accuracy = None  # invalidated: completed count changed

    # ------------------------------------------------------------- read sides

    def _rows(self, status: str) -> list[Record]:
        cfg = self._require_cfg()
        df = self._require().summarize(trial_statuses=[status])
        if df is None or df.empty:
            return []
        records: list[Record] = []
        for _, row in df.iterrows():
            try:
                index = int(row['trial_index'])
            except (KeyError, TypeError, ValueError):
                continue
            parameters: dict[str, Any] = {}
            for spec in cfg.parameters:
                if spec.name in df.columns:
                    try:
                        parameters[spec.name] = _cell(row[spec.name])
                    except ValueError:
                        continue
            metrics: dict[str, float] = {}
            for metric in cfg.metrics:
                if metric.name in df.columns:
                    try:
                        metrics[metric.name] = float(_cell(row[metric.name]))
                    except (ValueError, TypeError):
                        continue
            records.append(Record(index, parameters, metrics))
        records.sort(key=lambda r: r.trial_index)
        return records

    def _rebuild_read_cache(self) -> None:
        """Refresh the lock-free snapshots (call with ``_lock`` held).

        The snapshots only depend on trials that already exist, so they stay
        valid for the whole duration of a long-running ``suggest``/fit; new
        running trials are picked up when the mutation finishes.
        """
        if self._client is None or self._config is None:
            self._records, self._pending, self._pareto = [], [], frozenset()
            return
        cfg = self._config
        self._records = self._rows('completed')
        self._pending = [TrialRef(r.trial_index, r.parameters)
                         for r in self._rows('running')]
        frontier: frozenset[int] = frozenset()
        if len(cfg.objectives) > 1:
            try:
                found = self._client.get_pareto_frontier(
                    use_model_predictions=False)
                frontier = frozenset(int(index) for _, _, index, _ in found)
            except Exception:
                frontier = frozenset()
        self._pareto = frontier

    def history(self) -> list[Record]:
        """Completed-trial snapshot; safe to call from the event loop while a
        long ``suggest`` holds the lock (rebuilt after every mutation)."""
        return list(self._records)

    def pending(self) -> list[TrialRef]:
        return list(self._pending)

    def top_k(self, k: int) -> list[Record]:
        """Completed trials ranked best-first along the primary objective."""
        cfg = self._require_cfg()
        primary = cfg.primary
        minimize = primary.direction == 'minimize'
        records = [r for r in self.history() if primary.name in r.metrics]

        def rank(record: Record) -> float:
            value = record.metrics[primary.name]
            return value if minimize else -value

        return sorted(records, key=rank)[:max(1, int(k))]

    def pareto_indices(self) -> frozenset[int]:
        """Trial indices on the observed Pareto front (empty for 1 objective)."""
        return self._pareto

    def trace(self, metric: str | None = None) -> tuple[list[int], list[float],
                                                        list[float]]:
        """Completed-trial series for one metric plus running best-so-far."""
        cfg = self._require_cfg()
        name = metric or cfg.primary.name
        if name not in {m.name for m in cfg.metrics}:
            raise ValueError(f'Unknown metric: {name}')
        minimize = next((m.direction == 'minimize' for m in cfg.metrics
                         if m.name == name), False)
        xs: list[int] = []
        observed: list[float] = []
        best: list[float] = []
        current: float | None = None
        for record in self.history():
            if name not in record.metrics:
                continue
            value = record.metrics[name]
            if current is None or (value < current if minimize else value > current):
                current = value
            xs.append(record.trial_index)
            observed.append(value)
            best.append(current)
        return xs, observed, best

    def status_summary(self) -> dict[str, Any]:
        empty = {'active': False, 'name': '', 'completed': 0, 'running': 0,
                 'objectives': '', 'best': '', 'pareto': 0, 'finished': False}
        cfg = self._config
        if self._client is None or cfg is None:
            return empty
        running = len(self._pending)
        objectives = ' · '.join(
            f"{m.name} {'↓' if m.direction == 'minimize' else '↑'}"
            for m in cfg.objectives)
        ranked = self.top_k(1)
        best = (f'{cfg.primary.name} = '
                f'{format_value(ranked[0].metrics[cfg.primary.name])}'
                if ranked else '—')
        pareto = len(self._pareto) if len(cfg.objectives) > 1 else 0
        return {'active': True, 'name': cfg.name, 'completed': len(self._records),
                'running': running, 'objectives': objectives, 'best': best,
                'pareto': pareto, 'finished': self._finished}

    # -------------------------------------------------------------- model fit

    def refresh_accuracy(self) -> None:
        """Leave-one-out R² per objective (blocking — run in a worker thread)."""
        with self._lock:
            cfg = self._require_cfg()
            client = self._require()
            if len(self.history()) < 3:
                self._accuracy = {}
                return
            try:
                cards = client.compute_analyses(
                    analyses=[CrossValidationPlot(
                        metric_names=[m.name for m in cfg.objectives])],
                    display=False)
                self._accuracy = _extract_r2(cards)
            except Exception:
                self._accuracy = {}

    def accuracy(self) -> dict[str, float] | None:
        """Cached CV R² values; None until first refresh, {} if unavailable.

        Lock-free: ``refresh_accuracy`` only ever rebinds the whole dict."""
        return self._accuracy

    # ---------------------------------------------------------------- surface

    @staticmethod
    def _ensure_model(client: Client) -> None:
        """Refit the surrogate if Ax restored it without a fitted adapter.

        Ax's JSON snapshot serializes the experiment and generation strategy
        but not the fitted model, so ``predict`` fails right after ``load()``
        until something refits (a suggest, an analysis, ...). Refit lazily so
        the response surface works on a freshly restarted app too.
        """
        gs = client._generation_strategy
        if gs.adapter is None:
            gs.fit(experiment=gs.experiment)

    def surface(self, x_name: str, y_name: str, fixed: dict[str, Any],
                resolution: int, metric: str | None = None) -> dict[str, Any]:
        """Posterior mean over an x×y grid; z is row-major in y (plotly order)."""
        with self._lock:
            cfg = self._require_cfg()
            client = self._require()
            mapping = cfg.param_map
            for axis in (x_name, y_name):
                if axis not in mapping:
                    raise ValueError(f'Unknown parameter: {axis}')
                if mapping[axis].kind != 'range':
                    raise ValueError(f'{axis} is not a range parameter.')
            if x_name == y_name:
                raise ValueError('Pick two different parameters for X and Y.')
            metric = metric or cfg.primary.name
            if metric not in {m.name for m in cfg.metrics}:
                raise ValueError(f'Unknown metric: {metric}')
            unknown = set(fixed) - set(mapping)
            if unknown:
                raise ValueError('Unknown fixed parameter(s): '
                                 + ', '.join(sorted(unknown)))
            missing = set(mapping) - set(fixed) - {x_name, y_name}
            if missing:
                raise ValueError('Missing fixed value(s): '
                                 + ', '.join(sorted(missing)))
            n = max(5, int(resolution))
            xs = _axis_values(mapping[x_name], n)
            ys = _axis_values(mapping[y_name], n)
            points = [{**fixed, x_name: x, y_name: y} for y in ys for x in xs]
            self._ensure_model(client)
            predictions = client.predict(points)
            z: list[list[float]] = []
            sems: list[float] = []
            for row_index in range(len(ys)):
                row: list[float] = []
                for col_index in range(len(xs)):
                    prediction = predictions[row_index * len(xs) + col_index]
                    if metric not in prediction:
                        raise ValueError(
                            f'Model does not predict "{metric}" yet — complete '
                            'more trials.')
                    mean, sem = prediction[metric]
                    row.append(float(mean))
                    sems.append(float(sem))
                z.append(row)
            return {'x': xs, 'y': ys, 'z': z, 'metric': metric,
                    'mean_std': sum(sems) / len(sems) if sems else None}


