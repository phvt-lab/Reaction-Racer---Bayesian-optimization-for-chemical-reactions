"""Shared neon theme: global CSS, page shell (header + content + status footer)."""

from contextlib import contextmanager

from nicegui import app, ui

from core.campaign import service

# Neon brand palette: replaces the default NiceGUI/Quasar Material blue on every
# control which still uses a stock color (switches, checkboxes, toggle, spinner,
# focus rings, loading bar, notify toasts, "primary"-colored buttons).
# Status colors (positive/negative) stay at Quasar's defaults so toasts keep a
# readable contrast — they are not part of the blue problem.
app.colors(
    primary='#18c8ff',     # neon cyan — start of the button gradient
    secondary='#7a2bff',   # neon violet — end of the button gradient
    accent='#ff2fd6',      # neon magenta
    info='#00f0ff',
    warning='#ffd166',     # neon amber
    dark='#0d0618',
    dark_page='#0d0618',
)

_CSS = '''
body {
    background: #0d0618 !important;
    background-image:
        radial-gradient(ellipse 80% 50% at 20% -10%, rgba(120, 40, 220, .28), transparent),
        radial-gradient(ellipse 60% 40% at 90% 10%, rgba(0, 240, 255, .12), transparent);
    color: #d9cdf5;
}
.neon-card {
    background: rgba(28, 12, 52, .78) !important;
    border: 1px solid rgba(0, 240, 255, .30);
    border-radius: 14px;
    box-shadow: 0 0 14px rgba(0, 240, 255, .12), inset 0 0 26px rgba(120, 40, 220, .10);
}
.neon-card-magenta {
    background: rgba(40, 8, 48, .78) !important;
    border: 1px solid rgba(255, 47, 214, .35);
    border-radius: 14px;
    box-shadow: 0 0 14px rgba(255, 47, 214, .15), inset 0 0 26px rgba(255, 47, 214, .06);
}
.neon-title {
    font-weight: 800;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: #9beaff;
    text-shadow: 0 0 10px rgba(0, 240, 255, .8);
}
.neon-section {
    font-weight: 700;
    letter-spacing: .10em;
    text-transform: uppercase;
    color: #ff9df0;
    text-shadow: 0 0 8px rgba(255, 47, 214, .6);
}
.neon-magenta { color: #ff7ae6; text-shadow: 0 0 8px rgba(255, 47, 214, .7); }
.neon-green { color: #6dff8a; text-shadow: 0 0 8px rgba(57, 255, 20, .6); }
.neon-amber { color: #ffd166; text-shadow: 0 0 8px rgba(255, 179, 0, .5); }
.neon-header { background: rgba(16, 6, 32, .92) !important; border-bottom: 1px solid rgba(0, 240, 255, .45); }
.neon-footer { background: rgba(16, 6, 32, .92) !important; border-top: 1px solid rgba(255, 47, 214, .40); font-size: .8rem; }
.neon-btn {
    background: linear-gradient(135deg, #18c8ff, #7a2bff) !important;
    color: #ffffff !important;
    font-weight: 700;
    letter-spacing: .06em;
    box-shadow: 0 0 14px rgba(0, 200, 255, .45);
}
.neon-btn-big {
    color: #ffffff !important;
    font-size: 1.3rem !important;
    font-weight: 800 !important;
    letter-spacing: .08em;
    padding: 14px 28px !important;
    background: linear-gradient(135deg, #18c8ff, #7a2bff) !important;
    box-shadow: 0 0 18px rgba(0, 200, 255, .55);
}
.neon-btn-hot {
    color: #ffffff !important;
    background: linear-gradient(135deg, #ff8a00, #ff2fd6) !important;
    box-shadow: 0 0 18px rgba(255, 90, 180, .55);
}
.q-table thead tr { background: rgba(0, 240, 255, .10) !important; }
.q-table th { color: #9beaff !important; font-weight: 700; letter-spacing: .06em; }
.q-field__control::after { border-color: rgba(0, 240, 255, .5) !important; }
'''

NEON_SCALE = [[0.0, '#1a0b3d'], [0.25, '#7a2bff'], [0.5, '#00f0ff'],
              [0.75, '#6dff8a'], [1.0, '#ffd166']]


def style_figure(fig):
    """Apply the neon dark theme to a Plotly figure."""
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(20,8,40,.55)',
        font={'color': '#d9cdf5', 'size': 12},
        legend={'orientation': 'h', 'y': 1.14, 'x': 0},
        margin=dict(l=48, r=24, t=44, b=44),
    )
    fig.update_xaxes(gridcolor='rgba(0,240,255,.14)', zerolinecolor='rgba(0,240,255,.30)')
    fig.update_yaxes(gridcolor='rgba(255,47,214,.14)', zerolinecolor='rgba(255,47,214,.30)')
    return fig


NAV = [
    ('/', 'speed', 'Dashboard'),
    ('/config', 'tune', 'Configure'),
    ('/results', 'emoji_events', 'Results'),
    ('/analysis', 'analytics', 'Model'),
]

ui.add_css(_CSS, shared=True)  # global scope + @ui.page routes requires shared=True


@ui.refreshable
def _header_status() -> None:
    if service.is_active():
        ui.chip(service.config.name, icon='science', color='positive') \
            .props('outline dense').classes('neon-green')
    else:
        ui.chip('NO CAMPAIGN', icon='block', color='grey').props('outline dense')


def _model_chip() -> tuple[str, str]:
    """Footer model-fit chip: leave-one-out R² grade from cached Ax CV."""
    accuracy = service.accuracy()
    if not accuracy:
        text = 'Model: warming up…' if accuracy is None else 'Model: n/a'
        return text, 'text-purple-300'
    mean = sum(accuracy.values()) / len(accuracy)
    grade = 'High' if mean >= 0.7 else 'Medium' if mean >= 0.4 else 'Low'
    css = ('neon-green' if mean >= 0.7 else 'neon-amber'
           if mean >= 0.4 else 'neon-magenta')
    return f'Model: {grade} (R² {mean:.2f})', css


@ui.refreshable
def status_bar() -> None:
    st = service.status_summary()
    if not st['active']:
        ui.label('No campaign — open Configure to initialize an optimization')
        return
    with ui.row().classes('items-center gap-4 flex-wrap'):
        ui.label(f"Campaign: {st['name']}").classes('neon-magenta')
        ui.label(f"Completed: {st['completed']}").classes('neon-green')
        ui.label(f"Suggested: {st['running']}").classes('neon-amber')
        ui.label(f"Objectives: {st['objectives']}").classes('neon-magenta')
        ui.label(f"Best: {st['best']}").classes('neon-green')
        if st['pareto']:
            ui.label(f'Pareto: {st["pareto"]} trial(s)').classes('text-cyan-200')
        chip_text, chip_css = _model_chip()
        ui.label(chip_text).classes(chip_css)
        if st['finished']:
            ui.label('🏁 RACE COMPLETED').classes('neon-amber')


def refresh_status() -> None:
    _header_status.refresh()
    status_bar.refresh()


@contextmanager
def shell(active: str, subtitle: str = ''):
    """Standard page chrome: neon header with nav, content column, status footer."""
    ui.page_title('Reaction Racer')
    with ui.header().classes('neon-header gap-2'):
        ui.icon('science', size='1.6rem').classes('text-cyan-300')
        ui.label('REACTION RACER').classes('neon-title text-h6')
        ui.space()
        for path, icon, label in NAV:
            style = 'neon-magenta' if path == active else 'text-purple-200'
            # color=None keeps Quasar from adding "text-primary" (blue !important),
            # so the neon classes above actually control the label color
            ui.button(label, icon=icon, color=None,
                      on_click=lambda p=path: ui.navigate.to(p)) \
                .props('flat no-caps').classes(style)
        _header_status()
    with ui.column().classes('w-full max-w-[1500px] mx-auto p-4 gap-4'):
        if subtitle:
            ui.label(subtitle).classes('neon-title text-h5')
        yield
    with ui.footer().classes('neon-footer'):
        status_bar()


@contextmanager
def section_card(title: str, icon: str = 'view_module', *, magenta: bool = False):
    """Panel with neon title bar; yields a padded content column."""
    card = ui.card().classes('neon-card-magenta w-full' if magenta else 'neon-card w-full')
    with card:
        with ui.row().classes('items-center gap-2 w-full'):
            ui.icon(icon).classes('neon-magenta' if magenta else 'text-cyan-300')
            ui.label(title).classes('neon-section')
        with ui.column().classes('w-full gap-2 px-1 pb-2'):
            yield
    return card
