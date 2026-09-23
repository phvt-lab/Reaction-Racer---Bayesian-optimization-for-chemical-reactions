"""Campaign configuration page: objectives, parameters, simulation mode."""

from nicegui import ui, run

import theme
from core import simulation
from core.campaign import CampaignConfig, MetricSpec, ParameterSpec, validate_config
from core.workspace import current_username, service


@ui.page('/config')
def config_page() -> None:
    if not current_username():
        ui.navigate.to('/login')
        return
    username = current_username()
    # --- page state (local = per user) ---
    rows: list[dict] = [
        {'name': 'temperature', 'kind': 'range', 'low': 50.0, 'high': 200.0,
         'choices': '', 'unit': '°C', 'log': False},
        {'name': 'pressure', 'kind': 'range', 'low': 1.0, 'high': 10.0,
         'choices': '', 'unit': 'bar', 'log': False},
        {'name': 'catalyst_loading', 'kind': 'range', 'low': 1.0, 'high': 10.0,
         'choices': '', 'unit': '%', 'log': False},
        {'name': 'solvent', 'kind': 'choice', 'low': 0.0, 'high': 1.0,
         'choices': 'water, ethanol, toluene, acetonitrile', 'unit': '', 'log': False},
    ]

    # --- handlers: defined first; UI element names resolve lazily at click time ---
    directions: dict[str, str] = {}  # metric name -> maximize | minimize | record

    def _metric_names() -> list[str]:
        return [m.strip() for m in (metrics_chips.value or []) if m.strip()]

    def _direction_label(direction: str) -> str:
        return {'maximize': 'Maximize', 'minimize': 'Minimize',
                'record': 'Record only'}[direction]

    def _set_direction(name: str, label: str) -> None:
        directions[name] = {'Maximize': 'maximize', 'Minimize': 'minimize',
                            'Record only': 'record'}[str(label)]
        directions_editors.refresh()

    def _on_metrics_change(*_) -> None:
        directions_editors.refresh()

    def _build_config() -> CampaignConfig:
        specs = []
        for row in rows:
            if row['kind'] == 'range':
                specs.append(ParameterSpec(
                    name=row['name'].strip(), kind='range',
                    low=float(row['low']), high=float(row['high']),
                    unit=(row['unit'] or '').strip(), log_scale=bool(row['log'])))
            else:
                choices = tuple(c.strip() for c in row['choices'].split(',')
                                if c.strip())
                specs.append(ParameterSpec(
                    name=row['name'].strip(), kind='choice', choices=choices,
                    unit=(row['unit'] or '').strip()))
        return CampaignConfig(
            name=(name_input.value or 'Campaign').strip(),
            metrics=tuple(MetricSpec(name, directions.get(name, 'maximize'))
                          for name in _metric_names()),
            parameters=tuple(specs),
            simulation=bool(sim_switch.value))

    def _collect_errors() -> list[str]:
        errors = []
        if not (name_input.value or '').strip():
            errors.append('Campaign name is required.')
        if not _metric_names():
            errors.append('At least one metric is required.')
        elif all(directions.get(name, 'maximize') == 'record'
                 for name in _metric_names()):
            errors.append('At least one metric must be Maximize or Minimize.')
        if not rows:
            errors.append('At least one parameter is required.')
        seen: set[str] = set()
        for row in rows:
            pname = (row['name'] or '').strip()
            if not pname:
                errors.append('Every parameter needs a name.')
            elif pname in seen:
                errors.append(f'Duplicate parameter name: {pname}.')
            seen.add(pname)
            if row['kind'] == 'range':
                low, high = row['low'], row['high']
                if low is None or high is None or not low < high:
                    errors.append(f'{pname or "parameter"}: low must be < high.')
            else:
                choices = [c.strip() for c in (row['choices'] or '').split(',') if c.strip()]
                if len(choices) < 2:
                    errors.append(f'{pname or "parameter"}: need ≥2 comma-separated choices.')
        if not errors:
            try:
                validate_config(_build_config())
            except ValueError as exc:
                errors.append(str(exc))
        return errors

    async def _on_initialize() -> None:
        errors = _collect_errors()
        if errors:
            ui.notify('; '.join(errors), type='negative', position='top', timeout=5000)
            return
        new_config = _build_config()
        try:
            await run.io_bound(service.create_for, username, new_config)
        except Exception as exc:
            ui.notify(f'Initialization failed: {exc}', type='negative', timeout=6000)
            return
        theme.refresh_status()
        ui.notify(f'Campaign "{new_config.name}" initialized!', type='positive')
        ui.navigate.to('/campaign')

    # --- param editor helpers (must exist before the build references them) ---
    def _kind_changed(event, row: dict) -> None:
        row['kind'] = str(event.value)
        param_editor.refresh()

    def _remove_param(index: int) -> None:
        rows.pop(index)
        param_editor.refresh()

    def _add_param() -> None:
        rows.append({'name': f'parameter_{len(rows) + 1}', 'kind': 'range',
                     'low': 0.0, 'high': 1.0, 'choices': '', 'unit': '', 'log': False})
        param_editor.refresh()

    # --- page build (every element inside its intended card) ---
    active_service = service.current()
    active = active_service.config if active_service.is_active() else None

    with theme.shell('/config', 'CAMPAIGN CONFIGURATION'):
        if active is not None:
            with theme.section_card(f'ACTIVE: {active.name}', 'flag', magenta=True):
                with ui.row().classes('items-center gap-4 flex-wrap'):
                    ui.label('Objectives: ' + ' · '.join(
                        f"{m.name} {'↓' if m.direction == 'minimize' else '↑'}"
                        for m in active.objectives))
                    ui.label(f'Metrics: {", ".join(m.name for m in active.metrics)}')
                    ui.label(f'Parameters: {len(active.parameters)}')
                    ui.label(f'Mode: {"Simulation" if active.simulation else "Manual"}')
                ui.label('Initializing below creates a new stored campaign and makes '
                         'it active. Existing campaigns and trials are preserved.') \
                    .classes('text-orange-300')

        with theme.section_card('CAMPAIGN', 'science'):
            name_input = ui.input('Campaign name', value='Campaign A') \
                .props('outlined')
            sim_switch = ui.switch(
                'Built-in reaction simulation (auto-generate results)', value=True)

        with theme.section_card('OBJECTIVES & METRICS', 'crisis_alert', magenta=True):
            metrics_chips = ui.input_chips(
                'Metrics recorded per trial',
                value=list(simulation.DEFAULT_METRICS),
                on_change=_on_metrics_change).props('outlined')

            @ui.refreshable
            def directions_editors() -> None:
                for name in _metric_names():
                    direction = directions.get(name, 'maximize')
                    with ui.row().classes('items-center gap-3 w-full'):
                        ui.label(name).classes('text-cyan-200 w-48')
                        ui.select(['Maximize', 'Minimize', 'Record only'],
                                  value=_direction_label(direction), label='Role',
                                  on_change=lambda e, n=name:
                                      _set_direction(n, str(e.value))) \
                            .props('outlined dense color=pink w-44')
                        ui.label({'maximize': 'bigger is better',
                                  'minimize': 'smaller is better',
                                  'record': 'tracked, not optimized'}[direction]) \
                            .classes('text-purple-300 text-sm')

            directions_editors()
            ui.label('Every metric is recorded per trial. Two or more '
                     'Maximize/Minimize metrics are optimized jointly — the '
                     'Results page then shows a Pareto front.').classes('text-purple-300 text-sm')

        with theme.section_card('PARAMETERS', 'tune'):

            @ui.refreshable
            def param_editor() -> None:
                for index, row in enumerate(rows):
                    with ui.row().classes('items-center gap-2 w-full flex-wrap'):
                        ui.icon('drag_indicator', size='sm').classes('text-purple-400')
                        ui.input('Name', value=row['name'],
                                 on_change=lambda e, r=row:
                                     r.update(name=str(e.value or ''))) \
                            .props('outlined dense').classes('w-44')
                        ui.select(['range', 'choice'], value=row['kind'], label='Type',
                                  on_change=lambda e, r=row: _kind_changed(e, r)) \
                            .props('outlined dense').classes('w-32')
                        if row['kind'] == 'range':
                            ui.number('Low', value=row['low'],
                                      on_change=lambda e, r=row: r.update(low=e.value)) \
                                .props('outlined dense').classes('w-28')
                            ui.number('High', value=row['high'],
                                      on_change=lambda e, r=row: r.update(high=e.value)) \
                                .props('outlined dense').classes('w-28')
                            ui.checkbox('log', value=row['log'],
                                        on_change=lambda e, r=row:
                                            r.update(log=bool(e.value))) \
                                .props('dense')
                        else:
                            ui.input('Choices (comma separated)', value=row['choices'],
                                     on_change=lambda e, r=row:
                                         r.update(choices=str(e.value or ''))) \
                                .props('outlined dense').classes('flex-1 min-w-64')
                        ui.input('Unit', value=row['unit'],
                                 on_change=lambda e, r=row:
                                     r.update(unit=str(e.value or ''))) \
                            .props('outlined dense').classes('w-24')
                        ui.button(icon='delete', color='negative',
                                  on_click=lambda i=index: _remove_param(i)) \
                            .props('flat dense round')

            param_editor()
            ui.button('ADD PARAMETER', icon='add', color=None,
                      on_click=_add_param) \
                .props('outline color=info')

        with ui.row().classes('w-full justify-center pt-2'):
            ui.button('INITIALIZE OPTIMIZATION', icon='rocket_launch',
                      color=None, on_click=_on_initialize) \
                .props('unelevated').classes('neon-btn-big')

        # Campaign creation always preserves the existing workspace library.
