"""Model analysis page: posterior response surface over two parameters."""

import plotly.graph_objects as go
from nicegui import ui, run

import theme
from core.workspace import current_username, service


def _step(low: float, high: float) -> float:
    span = high - low
    if span <= 0:
        return 1.0
    if float(low).is_integer() and float(high).is_integer() and span <= 40:
        return 1.0
    return span / 50


@ui.page('/analysis')
async def analysis_page() -> None:
    if not current_username():
        ui.navigate.to('/login')
        return
    campaign = service.current()
    if not campaign.is_active():
        with theme.shell('/analysis', 'NO CAMPAIGN'):
            with theme.section_card('NO CAMPAIGN', 'block'):
                ui.label('Initialize a campaign first.')
                ui.button('OPEN CONFIGURATION', icon='tune', color=None,
                          on_click=lambda: ui.navigate.to('/config')) \
                    .props('unelevated').classes('neon-btn')
            return

    cfg = campaign.config
    range_specs = [p for p in cfg.parameters if p.kind == 'range']
    choice_specs = [p for p in cfg.parameters if p.kind == 'choice']

    if len(range_specs) < 2 or len(campaign.history()) < 2:
        with theme.shell('/analysis', 'MODEL ANALYSIS: PARAMETER SPACE'):
            with theme.section_card('NOT ENOUGH DATA', 'hourglass_empty'):
                ui.label('The response surface needs ≥2 range parameters and '
                         '≥2 completed trials.')
                ui.button('GO TO DASHBOARD', icon='speed', color=None,
                          on_click=lambda: ui.navigate.to('/campaign')) \
                    .props('unelevated').classes('neon-btn')
        return

    # --- control state ---
    fixed_values: dict[str, float | str] = {
        spec.name: (spec.low + spec.high) / 2 if spec.kind == 'range'
        else spec.choices[0]
        for spec in cfg.parameters
    }

    @ui.refreshable
    def fixed_editors() -> None:
        axis = {x_select.value, y_select.value}
        for spec in cfg.parameters:
            if spec.name in axis:
                continue
            if spec.kind == 'choice':
                ui.select(options=list(spec.choices),
                          value=fixed_values[spec.name], label=spec.name,
                          on_change=lambda e, n=spec.name:
                              fixed_values.__setitem__(n, str(e.value))) \
                    .props('outlined dense')
            else:
                with ui.row().classes('items-center gap-2 w-full'):
                    ui.label(spec.name).classes('text-purple-300 text-sm w-44')
                    slider = ui.slider(
                        min=spec.low, max=spec.high,
                        step=_step(spec.low, spec.high),
                        value=float(fixed_values[spec.name]),
                        on_change=lambda e, n=spec.name:
                            fixed_values.__setitem__(n, float(e.value))) \
                        .props('color=cyan')
                    label = ui.label().classes('neon-green text-sm w-24')
                    label.bind_text_from(
                        slider, 'value',
                        backward=lambda v: f'{float(v):g} {spec.unit}'.strip())

    def _axis_changed(_) -> None:
        fixed_editors.refresh()

    @ui.refreshable
    def plot_panel(fig=None, caption: str = '') -> None:
        if fig is None:
            ui.label(caption or 'Press RE-VISUALIZE MODEL to render the posterior.') \
                .classes('text-purple-300')
            return
        ui.plotly(theme.style_figure(fig)).classes('w-full')
        if caption:
            ui.label(caption).classes('text-purple-300 text-sm')

    with theme.shell('/analysis', 'MODEL ANALYSIS: PARAMETER SPACE'):
        with ui.row().classes('w-full gap-4 items-start flex-wrap'):
            with theme.section_card('PARAMETER SELECTION', 'tune'):
                objective_select = ui.select(
                    options=[m.name for m in cfg.objectives],
                    value=cfg.primary.name, label='Objective (surface Z)'
                    ).props('outlined color=amber w-44')
                with ui.row().classes('items-center gap-3 flex-wrap'):
                    x_select = ui.select(
                        options=[p.name for p in range_specs],
                        value=range_specs[0].name, label='X axis',
                        on_change=_axis_changed).props('outlined color=cyan')
                    y_select = ui.select(
                        options=[p.name for p in range_specs],
                        value=next(p.name for p in range_specs if p.name !=
                                   range_specs[0].name),
                        label='Y axis', on_change=_axis_changed) \
                        .props('outlined color=pink')
                    mode_toggle = ui.toggle(['3D Surface', 'Contour'],
                                            value='3D Surface') \
                        .props('no-caps toggle-color=accent')
                fixed_editors()
                ui.button('RE-VISUALIZE MODEL', icon='refresh', color=None,
                          on_click=lambda: _render()) \
                    .props('unelevated') \
                    .classes('neon-btn-hot w-full')

            with theme.section_card('RESPONSE SURFACE', 'deployed_code', magenta=True):
                plot_panel()

    async def _render() -> None:
        x_name, y_name = x_select.value, y_select.value
        if x_name == y_name:
            ui.notify('Pick two different parameters for X and Y', type='warning')
            return
        objective = objective_select.value or cfg.primary.name
        fixed = {k: v for k, v in fixed_values.items() if k not in (x_name, y_name)}
        plot_panel.refresh(None, 'Computing posterior predictions…')
        try:
            data = await run.io_bound(campaign.surface, x_name, y_name, fixed, 25,
                                      objective)
        except Exception as exc:
            ui.notify(f'Surface computation failed: {exc}', type='negative',
                      timeout=6000)
            plot_panel.refresh(None, f'Error: {exc}')
            return

        observed = campaign.history()
        fig = go.Figure()
        if mode_toggle.value == '3D Surface':
            fig.add_trace(go.Surface(
                x=data['x'], y=data['y'], z=data['z'], colorscale=theme.NEON_SCALE,
                opacity=0.92, colorbar=dict(title=objective, thickness=12),
                name='Posterior mean'))
            fig.add_trace(go.Scatter3d(
                x=[r.parameters[x_name] for r in observed],
                y=[r.parameters[y_name] for r in observed],
                z=[(r.metrics or {}).get(objective) for r in observed],
                mode='markers', name='Observed',
                marker=dict(size=4, color='#ffffff',
                            line=dict(color='#ff2fd6', width=2))))
            fig.update_layout(
                height=520,
                scene=dict(xaxis_title=x_name, yaxis_title=y_name,
                           zaxis_title=objective, bgcolor='rgba(20,8,40,.55)',
                           xaxis=dict(gridcolor='rgba(0,240,255,.2)'),
                           yaxis=dict(gridcolor='rgba(255,47,214,.2)'),
                           zaxis=dict(gridcolor='rgba(109,255,138,.2)')))
        else:
            fig.add_trace(go.Contour(
                x=data['x'], y=data['y'], z=data['z'], colorscale=theme.NEON_SCALE,
                contours=dict(coloring='heatmap', showlabels=True,
                              labelfont=dict(size=10, color='#0d0618')),
                colorbar=dict(title=objective, thickness=12)))
            fig.add_trace(go.Scatter(
                x=[r.parameters[x_name] for r in observed],
                y=[r.parameters[y_name] for r in observed],
                mode='markers', name='Observed',
                marker=dict(size=10, color='#ffffff', symbol='x',
                            line=dict(color='#ff2fd6', width=2))))
            fig.update_layout(xaxis_title=x_name, yaxis_title=y_name, height=480)

        caption = (f'{objective} posterior mean over a '
                   f'{len(data["x"])}×{len(data["y"])} grid — '
                   f'{x_name} × {y_name}')
        mean_std = data.get('mean_std')
        if mean_std is not None:
            caption += f' · mean predictive σ at observed trials: {float(mean_std):.3g}'
        plot_panel.refresh(fig, caption)
