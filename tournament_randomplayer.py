from tornado import gen
import ujson as json
from diplomacy import Game
from diplomacy.utils.export import to_saved_game_format
from diplomacy_research.players.random_player import RandomPlayer
from diplomacy_research.utils.cluster import start_io_loop, stop_io_loop

@gen.coroutine
def main():
    """ Plays a local game with 7 bots """
    player = RandomPlayer()
    game = Game()

    # Playing game
    while not game.is_game_done:
        orders = yield {power_name: player.get_orders(game, power_name) for power_name in game.powers}
        for power_name, power_orders in orders.items():
            game.set_orders(power_name, power_orders)
        game.process()

    # Saving to disk
    with open('game.json', 'w') as file:
        file.write(json.dumps(to_saved_game_format(game)))
    stop_io_loop()

if __name__ == '__main__':
    start_io_loop(main)

