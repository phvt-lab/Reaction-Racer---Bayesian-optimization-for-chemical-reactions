"""Active campaign dashboard: suggest/submit loop, progress trace, history."""

import asyncio
import math

import plotly.graph_objects as go
from nicegui import ui, run

import theme
from core import simulation
from core.workspace import current_username, service


@ui.page('/campaign')
async def dashboard() -> None:
    if not current_username():
        ui.navigate.to('/login')
        return
    campaign = service.current()
    if not campaign.is_active():
        with theme.shell('/campaign', 'NO ACTIVE CAMPAIGN'):
            with theme.section_card('GETTING STARTED', 'rocket_launch'):
                ui.label('Configure objectives and parameters to start optimizing.')
                ui.button('OPEN CAMPAIGN CONFIGURATION', icon='tune',
                          color=None,
                          on_click=lambda: ui.navigate.to('/config')) \
                    .props('unelevated').classes('neon-btn')
        return

    cfg = campaign.config

    with theme.shell('/campaign', f'ACTIVE OPTIMIZATION: {cfg.name}'):
        with ui.row().classes('w-full gap-4 items-start flex-wrap'):
            with ui.column().classes('flex-[2_1_480px] gap-4'):
                # --- progress trace ---
                with theme.section_card('OPTIMIZATION PROGRESS', 'monitoring'):

                    @ui.refreshable
                    def progress_panel() -> None:
                        metric = trace_select.value or cfg.primary.name
                        xs, observed, best = campaign.trace(metric)
                        if not xs:
                            ui.label('No completed trials yet — suggest and submit your '
                                     'first experiment.').classes('text-purple-300')
                            return
                        spec = next((m for m in cfg.metrics if m.name == metric),
                                    cfg.primary)
                        arrow = '↓' if spec.direction == 'minimize' else '↑'
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=xs, y=observed, mode='markers+lines',
                            name=f'Observed {metric}',
                            marker=dict(color='#00f0ff', size=11, symbol='star',
                                        line=dict(color='#ffffff', width=1)),
                            line=dict(color='rgba(0,240,255,.35)', width=1)))
                        fig.add_trace(go.Scatter(
                            x=xs, y=best, mode='lines', name='Best so far',
                            line=dict(color='#ff2fd6', width=3)))
                        fig.update_layout(
                            title=dict(text=f'{metric} {arrow} — best-so-far vs run',
                                       font={'color': '#9beaff'}),
                            xaxis_title='Run #', yaxis_title=metric,
                            height=340, hovermode='x unified')
                        ui.plotly(theme.style_figure(fig)).classes('w-full')

                    trace_select = ui.select(
                        options=[m.name for m in cfg.objectives],
                        value=cfg.primary.name, label='Trace metric',
                        on_change=lambda _: progress_panel.refresh()) \
                        .props('outlined dense color=cyan w-44')
                    progress_panel()

                # --- history table ---
                with theme.section_card('REACTION HISTORY', 'history'):

                    @ui.refreshable
                    def history_panel() -> None:
                        records = campaign.history()
                        if not records:
                            ui.label('Completed trials will appear here.') \
                                .classes('text-purple-300')
                            return
                        metric_names = [m.name for m in cfg.metrics]
                        columns = [{'name': 'run', 'label': 'Run', 'field': 'run',
                                    'sortable': True, 'align': 'left'}]
                        for p in cfg.parameters:
                            label = p.name + (f' ({p.unit})' if p.unit else '')
                            columns.append({'name': p.name, 'label': label,
                                            'field': p.name, 'sortable': True})
                        for m in metric_names:
                            columns.append({'name': m, 'label': m, 'field': m,
                                            'sortable': True, 'align': 'right'})
                        rows = []
                        for record in reversed(records):
                            row = {'run': record.trial_index,
                                   **record.parameters, **(record.metrics or {})}
                            rows.append(row)
                        table = ui.table(columns=columns, rows=rows, row_key='run') \
                            .classes('w-full')
                        table.props('dense flat')

                    history_panel()

            with ui.column().classes('flex-[1_1_340px] gap-4'):
                # --- next experiment / actions ---
                with theme.section_card('NEXT EXPERIMENT', 'lightbulb', magenta=True):

                    @ui.refreshable
                    def experiment_panel() -> None:
                        pending = campaign.pending()
                        for trial in pending:
                            with ui.card().classes('neon-card w-full p-2'):
                                ui.label(f'Trial {trial.trial_index}') \
                                    .classes('neon-amber text-sm')
                                for pname, value in trial.parameters.items():
                                    spec = cfg.param_map[pname]
                                    suffix = f' {spec.unit}' if spec.unit else ''
                                    ui.label(f'{pname}: {value}{suffix}') \
                                        .classes('text-cyan-200')
                            if cfg.simulation:
                                ui.button('SIMULATE RESULT', icon='auto_awesome',
                                          color=None) \
                                    .props('unelevated') \
                                    .classes('neon-btn-hot w-full') \
                                    .on('click', lambda t=trial: _simulate(t))
                            else:
                                inputs: dict[str, ui.number] = {}
                                with ui.column().classes('w-full gap-1'):
                                    for metric in cfg.metrics:
                                        inputs[metric.name] = ui.number(
                                            metric.name, value=None) \
                                            .props('outlined dense')
                                ui.button('SUBMIT DATA', icon='check',
                                          color=None) \
                                    .props('unelevated') \
                                    .classes('neon-btn-hot w-full') \
                                    .on('click', lambda t=trial, i=inputs: _submit(t, i))
                            if len(pending) > 1:
                                ui.separator()
                        with ui.row().classes('items-end gap-2 w-full'):
                            batch = ui.number('Batch size', value=1, min=1, max=10,
                                              step=1).props('outlined dense')
                            ui.button('SUGGEST', icon='casino', color=None) \
                                .props('unelevated') \
                                .classes('neon-btn-big') \
                                .on('click', lambda b=batch: _suggest(b))

                    experiment_panel()

                # --- settings summary ---
                with theme.section_card('CURRENT SETTINGS', 'settings'):
                    ui.label('Objectives: ' + ' · '.join(
                        f"{m.name} {'↓' if m.direction == 'minimize' else '↑'}"
                        for m in cfg.objectives)).classes('neon-green')
                    if cfg.tracking_names:
                        ui.label(f'Tracking: {", ".join(cfg.tracking_names)}') \
                            .classes('text-purple-300 text-sm')
                    ui.label(f'Mode: {"Simulation" if cfg.simulation else "Manual entry"}') \
                        .classes('neon-amber')
                    ui.label(f'Metrics: {", ".join(m.name for m in cfg.metrics)}')
                    for p in cfg.parameters:
                        if p.kind == 'range':
                            span = f'{p.low:g}–{p.high:g}'
                        else:
                            span = ', '.join(p.choices)
                        unit = f' {p.unit}' if p.unit else ''
                        ui.label(f'{p.name}: {span}{unit}').classes('text-purple-300 text-sm')
                    if campaign.finished:
                        ui.label('🏁 RACE COMPLETED').classes('neon-amber text-h6')
                    else:
                        ui.button('END RACE', icon='flag', color=None,
                                  on_click=lambda: _finish()) \
                            .props('flat').classes('neon-amber')
                    ui.button('RECONFIGURE', icon='tune', color=None,
                              on_click=lambda: ui.navigate.to('/config')) \
                        .props('flat').classes('neon-magenta')

    # --- action handlers ---

    def _refresh_all() -> None:
        progress_panel.refresh()
        experiment_panel.refresh()
        history_panel.refresh()
        theme.refresh_status()

    async def _finish() -> None:
        # Worker thread: service.finish() takes the campaign lock, which a
        # concurrent suggest may hold for a long time — never block the loop.
        try:
            await run.io_bound(campaign.finish)
        except Exception as exc:
            ui.notify(f'Could not finish the race: {exc}', type='negative',
                      timeout=6000)
            return
        _refresh_all()
        ui.notify('Race completed — campaign marked finished 🏁', type='positive')

    def _ui_safe(action) -> None:
        """Apply a UI update, ignoring the deleted-slot error raised when the
        page was closed while an awaited service call was still running."""
        try:
            action()
        except RuntimeError:
            pass

    async def _suggest(batch) -> None:
        count = int(batch.value or 1)
        note = ui.notification('Fitting model and suggesting…', spinner=True)
        try:
            trials = await run.io_bound(campaign.suggest, count)
        except Exception as exc:
            note.dismiss()
            ui.notify(f'Suggestion failed: {exc}', type='negative', timeout=6000)
            return
        note.dismiss()
        _ui_safe(lambda: ui.notify(f'{len(trials)} trial(s) suggested',
                                   type='positive'))
        _ui_safe(_refresh_all)
        await run.io_bound(campaign.refresh_accuracy)
        _ui_safe(theme.refresh_status)

    async def _simulate(trial) -> None:
        values = simulation.evaluate(trial.parameters, cfg.parameters,
                                     tuple(m.name for m in cfg.metrics))
        await _complete(trial, values)

    async def _submit(trial, inputs: dict) -> None:
        objective_names = {m.name for m in cfg.objectives}
        values = {}
        for metric, element in inputs.items():
            value = element.value
            if value is None:
                if metric in objective_names:
                    ui.notify(f'{metric} is required', type='warning')
                    return
                continue
            values[metric] = float(value)
        await _complete(trial, values)

    async def _complete(trial, values: dict) -> None:
        try:
            await run.io_bound(campaign.complete, trial.trial_index, values)
        except (ValueError, KeyError) as exc:
            ui.notify(str(exc), type='negative', timeout=6000)
            return
        except Exception as exc:
            ui.notify(f'Completion failed: {exc}', type='negative', timeout=6000)
            return
        objective_value = values.get(cfg.primary.name)
        if objective_value is not None and not math.isnan(objective_value):
            ui.notify(f'Trial {trial.trial_index} completed: '
                      f'{cfg.primary.name} = {format_value(objective_value)}',
                      type='positive')
        else:
            ui.notify(f'Trial {trial.trial_index} completed', type='positive')
        _refresh_all()
        await run.io_bound(campaign.refresh_accuracy)
        theme.refresh_status()

    async def _warm_model_chip() -> None:
        if campaign.is_active() and campaign.accuracy() is None:
            await run.io_bound(campaign.refresh_accuracy)
            _ui_safe(theme.refresh_status)

    asyncio.create_task(_warm_model_chip())
