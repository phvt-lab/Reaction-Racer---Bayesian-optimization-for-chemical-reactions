"""Username workspace and stored-campaign library."""

from nicegui import ui

import theme
from core.workspace import current_username, login, logout, service


@ui.page('/login')
def login_page() -> None:
    if current_username():
        ui.navigate.to('/')
        return
    ui.page_title('Reaction Racer · Sign in')
    with ui.column().classes('w-full max-w-md mx-auto mt-24 gap-4'):
        with theme.section_card('WELCOME TO REACTION RACER', 'science', magenta=True):
            ui.label('Enter a username to open your private campaign workspace.') \
                .classes('text-purple-200')
            username = ui.input('Username', placeholder='e.g. alex') \
                .props('outlined autofocus')
            username.on('keydown.enter', lambda _: _sign_in(username))
            ui.button('ENTER WORKSPACE', icon='login', color=None,
                      on_click=lambda: _sign_in(username)) \
                .props('unelevated').classes('neon-btn-big w-full')
            ui.label('No password or email required. Anyone who knows your username '
                     'can open that workspace.') \
                .classes('text-orange-300 text-sm')


def _sign_in(username) -> None:
    try:
        name, created = login(username.value or '')
    except ValueError as exc:
        ui.notify(str(exc), type='negative')
        return
    ui.notify(f'Welcome, {name}! New workspace created.' if created
              else f'Welcome back, {name}!', type='positive')
    ui.navigate.to('/')


@ui.page('/')
def workspace_page() -> None:
    if not current_username():
        ui.navigate.to('/login')
        return
    campaigns = service.list_campaigns()
    with theme.shell('/', 'CAMPAIGN WORKSPACE'):
        with ui.row().classes('w-full items-center gap-3'):
            ui.label(f'{len(campaigns)} stored campaign'
                     f'{"s" if len(campaigns) != 1 else ""}') \
                .classes('neon-green text-h6')
            ui.space()
            ui.button('NEW CAMPAIGN', icon='add', color=None,
                      on_click=lambda: ui.navigate.to('/config')) \
                .props('unelevated').classes('neon-btn')
        if not campaigns:
            with theme.section_card('YOUR WORKSPACE IS READY', 'rocket_launch'):
                ui.label('No campaigns yet. Create your first optimization to start '
                         'a race. Your future campaigns will stay here.')
                ui.button('CREATE FIRST CAMPAIGN', icon='rocket_launch', color=None,
                          on_click=lambda: ui.navigate.to('/config')) \
                    .props('unelevated').classes('neon-btn-hot')
            return
        with ui.row().classes('w-full gap-4 items-stretch flex-wrap'):
            for campaign in campaigns:
                with theme.section_card(campaign['name'],
                                        'star' if campaign['active'] else 'history',
                                        magenta=campaign['active']):
                    with ui.row().classes('items-center gap-2 w-full'):
                        if campaign['active']:
                            ui.chip('ACTIVE', icon='bolt', color='positive') \
                                .props('outline dense').classes('neon-green')
                        if campaign['finished']:
                            ui.chip('FINISHED', icon='flag', color='amber') \
                                .props('outline dense').classes('neon-amber')
                    ui.label(f"{campaign['completed']} completed trial"
                             f"{'s' if campaign['completed'] != 1 else ''}"
                             f" · {campaign['running']} suggested") \
                        .classes('text-cyan-200')
                    updated = campaign['updated_at'] or campaign['created_at']
                    if updated:
                        ui.label(f'Updated {updated[:16].replace("T", " ")} UTC') \
                            .classes('text-purple-300 text-sm')
                    ui.button('OPEN CAMPAIGN', icon='arrow_forward', color=None,
                              on_click=lambda cid=campaign['id']: _open(cid)) \
                        .props('unelevated').classes('neon-btn w-full')


def _open(campaign_id: str) -> None:
    try:
        service.select_campaign(campaign_id)
    except (RuntimeError, ValueError) as exc:
        ui.notify(str(exc), type='negative')
        return
    ui.navigate.to('/campaign')
