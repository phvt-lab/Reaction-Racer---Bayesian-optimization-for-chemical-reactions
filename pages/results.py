"""Results page: Pareto front (multi-objective), podium (single), top-5 board."""

import plotly.graph_objects as go
from nicegui import ui

import theme
from core.campaign import MetricSpec, format_value
from core.workspace import current_username, service


def _arrow(metric: MetricSpec) -> str:
    return '↓' if metric.direction == 'minimize' else '↑'


def _pareto_card(records, pareto: frozenset[int],
                 objectives: tuple[MetricSpec, ...]) -> None:
    """Two leading objectives; star markers are the non-dominated (Pareto) trials."""
    x_obj, y_obj = objectives[0], objectives[1]
    color_obj = objectives[2] if len(objectives) > 2 else None
    rows = [r for r in records
            if x_obj.name in r.metrics and y_obj.name in r.metrics]
    front = [r for r in rows if r.trial_index in pareto]
    dominated = [r for r in rows if r.trial_index not in pareto]

    colorbar = (dict(title=color_obj.name, thickness=12, x=1.01)
                if color_obj else None)
    fig = go.Figure()
    if dominated:
        marker = (dict(color=[r.metrics[color_obj.name] for r in dominated],
                       colorscale=theme.NEON_SCALE, size=10, opacity=0.5,
                       colorbar=colorbar)
                  if color_obj else
                  dict(color='#7a2bff', size=10, opacity=0.55))
        fig.add_trace(go.Scatter(
            x=[r.metrics[x_obj.name] for r in dominated],
            y=[r.metrics[y_obj.name] for r in dominated],
            mode='markers', name='Dominated', marker=marker,
            text=[f'Trial {r.trial_index}' for r in dominated]))
    marker = (dict(color=[r.metrics[color_obj.name] for r in front],
                   colorscale=theme.NEON_SCALE, symbol='star', size=17,
                   colorbar=colorbar if not dominated else None)
              if color_obj else
              dict(color='#ffd166', symbol='star', size=17,
                   line=dict(color='#ffffff', width=1)))
    fig.add_trace(go.Scatter(
        x=[r.metrics[x_obj.name] for r in front],
        y=[r.metrics[y_obj.name] for r in front],
        mode='markers+text', name='Pareto optimal', marker=marker,
        text=[f'#{r.trial_index}' for r in front],
        textposition='top center', textfont=dict(color='#ffd166', size=11)))

    with theme.section_card('PARETO FRONT', 'account_tree', magenta=True):
        fig.update_layout(
            title=dict(text=f'{x_obj.name} vs {y_obj.name}',
                       font={'color': '#9beaff'}),
            xaxis_title=f'{x_obj.name} {_arrow(x_obj)}',
            yaxis_title=f'{y_obj.name} {_arrow(y_obj)}',
            height=470, hovermode='closest')
        ui.plotly(theme.style_figure(fig)).classes('w-full')
        caption = (f'{len(front)} Pareto-optimal of {len(rows)} completed trials '
                   '— starred points are non-dominated (hover for trial id)')
        if color_obj:
            caption += f'; color = {color_obj.name}'
        ui.label(caption).classes('text-purple-300 text-sm')


def _podium_card(top, primary: MetricSpec, completed: int) -> None:
    with theme.section_card('PODIUM', 'emoji_events'):
        order = list(range(len(top)))
        if len(top) == 3:
            order = [1, 0, 2]  # 2nd, 1st, 3rd — first place center stage
        heights = {0: 'pt-10', 1: '', 2: 'pt-16'}
        with ui.row().classes('items-end justify-center gap-3 w-full'):
            for slot in order:
                record = top[slot]
                rank = slot + 1
                card = ui.card().classes(
                    'neon-card p-3 text-center flex-1 min-w-40 '
                    + heights.get(slot, ''))
                with card:
                    ui.icon('emoji_events', size='2rem').classes(
                        ['neon-amber', 'neon-green', 'neon-magenta'][rank - 1])
                    ui.label(f'{rank}'
                             f'{["st", "nd", "rd"][rank - 1]} PLACE') \
                        .classes('neon-title text-sm')
                    value = (record.metrics or {}).get(primary.name)
                    ui.label(format_value(value) if value is not None else '—') \
                        .classes('text-h5 neon-green')
                    ui.label(f'Trial {record.trial_index}') \
                        .classes('text-purple-300 text-sm')
                    for pname, pvalue in record.parameters.items():
                        ui.label(f'{pname}: {pvalue}') \
                            .classes('text-cyan-200 text-xs')
        ui.label(f'{completed} completed runs — keep going!') \
            .classes('neon-amber text-center w-full')


@ui.page('/results')
def results_page() -> None:
    if not current_username():
        ui.navigate.to('/login')
        return
    campaign = service.current()
    with theme.shell('/results', 'OPTIMIZATION RESULTS: TOP CANDIDATES'):
        if not campaign.is_active() or not campaign.history():
            with theme.section_card('WAITING FOR DATA', 'hourglass_empty'):
                ui.label('Complete at least one trial to see results.')
                ui.button('GO TO DASHBOARD', icon='speed', color=None,
                          on_click=lambda: ui.navigate.to('/campaign')) \
                    .props('unelevated').classes('neon-btn')
            return

        cfg = campaign.config
        objectives = cfg.objectives
        primary = cfg.primary
        records = campaign.history()
        pareto = campaign.pareto_indices()
        top = campaign.top_k(3)

        with ui.row().classes('w-full gap-4 items-stretch flex-wrap'):
            if len(objectives) == 1:
                _podium_card(top, primary, len(records))
            else:
                _pareto_card(records, pareto, objectives)

            # --- leaderboard: ranked along the primary objective ---
            with theme.section_card(f'TOP 5 ALL-TIME ({primary.name})',
                                    'leaderboard', magenta=True):
                medals = ('🥇', '🥈', '🥉', '', '')
                rows = []
                for i, record in enumerate(campaign.top_k(5), start=1):
                    marks = medals[i - 1]
                    if record.trial_index in pareto:
                        marks = (marks + '⭐') if marks else '⭐'
                    row = {'rank': i, 'run': record.trial_index, 'marks': marks,
                           **(record.metrics or {})}
                    row.update(record.parameters)
                    rows.append(row)
                columns = [{'name': 'rank', 'label': '#', 'field': 'rank',
                            'align': 'left'},
                           {'name': 'run', 'label': 'Run', 'field': 'run'},
                           {'name': 'marks', 'label': '', 'field': 'marks',
                            'align': 'center'}]
                columns += [{'name': m.name, 'label': m.name, 'field': m.name,
                             'sortable': True, 'align': 'right'}
                            for m in cfg.metrics]
                columns += [{'name': p.name,
                             'label': p.name + (f' ({p.unit})' if p.unit else ''),
                             'field': p.name, 'sortable': True}
                            for p in cfg.parameters]
                table = ui.table(columns=columns, rows=rows, row_key='rank') \
                    .classes('w-full')
                table.props('dense flat hide-pagination')

                if len(objectives) == 1:
                    ui.label('BEST PARAMETERIZATION').classes('neon-section')
                    for pname, pvalue in top[0].parameters.items():
                        ui.label(f'{pname}: {pvalue}').classes('neon-green')
                else:
                    ui.label(f'PARETO SET ({len(pareto)})').classes('neon-section')
                    ranked = campaign.top_k(len(records))
                    front_records = [r for r in ranked if r.trial_index in pareto]
                    for record in front_records[:6]:
                        params = ', '.join(
                            f'{k}={v:.6g}' if isinstance(v, float) else f'{k}={v}'
                            for k, v in record.parameters.items())
                        ui.label(f'#{record.trial_index} · {params}') \
                            .classes('neon-green text-sm')
                    if len(front_records) > 6:
                        ui.label(f'… {len(front_records) - 6} more Pareto trials') \
                            .classes('text-purple-300 text-sm')
