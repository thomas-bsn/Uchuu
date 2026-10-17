"""Dispatcher webhook : plusieurs handlers par type d'event (chaînage des cogs).

#5 possède `game_started` / `game_completed`, #4 `teams_formed`, #15 les votes MVP/DOFD et
#16 (pronostics) doit observer les mêmes events sans remplacer leurs handlers. Le
contrôleur webhook parcourt donc `handlers_for`, dans l'ordre d'enregistrement.
"""
from services.shameless_events import ShamelessEvent, ShamelessEventDispatcher


def event(event_type="game_completed"):
    return ShamelessEvent(version=1, event_id="e-1", type=event_type)


async def run(dispatcher, event_type):
    for handler in dispatcher.handlers_for(event_type):
        await handler(event(event_type))


async def test_handlers_registered_for_the_same_type_all_run_in_order():
    dispatcher = ShamelessEventDispatcher()
    seen = []

    async def first(_event):
        seen.append("first")

    async def second(_event):
        seen.append("second")

    dispatcher.register("game_completed", first)
    dispatcher.register("game_completed", second)

    await run(dispatcher, "game_completed")

    assert seen == ["first", "second"]


async def test_registering_the_same_handler_twice_does_not_run_it_twice():
    dispatcher = ShamelessEventDispatcher()
    seen = []

    async def handler(_event):
        seen.append("x")

    dispatcher.register("game_started", handler)
    dispatcher.register("game_started", handler)

    await run(dispatcher, "game_started")

    assert seen == ["x"]


async def test_unregistering_one_handler_keeps_the_others():
    dispatcher = ShamelessEventDispatcher()
    seen = []

    async def first(_event):
        seen.append("first")

    async def second(_event):
        seen.append("second")

    dispatcher.register("teams_formed", first)
    dispatcher.register("teams_formed", second)

    dispatcher.unregister("teams_formed", first)
    await run(dispatcher, "teams_formed")

    assert seen == ["second"]


async def test_unregistering_a_type_removes_every_handler_of_that_type():
    dispatcher = ShamelessEventDispatcher()

    async def handler(_event):
        pass

    dispatcher.register("teams_formed", handler)
    dispatcher.unregister("teams_formed")

    assert dispatcher.handler_for("teams_formed") is None
    assert dispatcher.handlers_for("teams_formed") == []
