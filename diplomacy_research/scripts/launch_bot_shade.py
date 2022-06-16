#!/usr/bin/env python3
# ==============================================================================
# Copyright 2019 - Philip Paquette
#
# NOTICE:  Permission is hereby granted, free of charge, to any person obtaining
#   a copy of this software and associated documentation files (the "Software"),
#   to deal in the Software without restriction, including without limitation the
#   rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#   sell copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
# ==============================================================================
""" Small script that periodically runs the diplomacy private bot to
    generate orders for active games currently loaded on a server.
    You can stop the bot with keyboard interruption (Ctrl+C).
    Usage:
        python -m diplomacy_research.scripts.bot [--host=localhost] [--port=8432] [--period=10]
    By default, connect to server localhost:8432 (host:port) and run every 10 seconds (period).
"""
import argparse
from distutils.ccompiler import new_compiler
import logging
import json

# Import sys for explicit library import.
import sys
import os

from diplomacy import connect
from diplomacy.utils import constants, exceptions, strings
from tornado import gen, ioloop

from diplomacy.engine.message import Message

sys.path.append('./')
from diplomacy_research.players.benchmark_player import DipNetSLPlayer, download_model
from diplomacy_research.players.borgia_player_shade import BorgiaPlayer
from diplomacy_research.settings import REDIS_DOWNLOAD_URL, TF_SERVING_DOWNLOAD_URL, ALBERT_AI_DOWNLOAD_URL, \
    WORKING_DIR, IN_PRODUCTION
from diplomacy_research.utils.process import download_file

LOGGER = logging.getLogger('diplomacy_research.scripts.launch_bot')
PERIOD_SECONDS = 2


class Bot():
    """ Bot class. Properties:
        - host: name of host to connect
        - port: port to connect in host
        - username: name of user to connect to server. By default, private bot username.
        - password: password of user to connect to server. BY default, private bot password.
        - period_seconds: time (in seconds) between 2 queries in server to look for powers to order.
            By default, 10 seconds.
        - player_builder: a callable (without arguments) to be used to create a "player"
            which is responsible for generating orders for a single power in a game.
            Can be a class. By default, class RandomPlayer.
        - buffer_size: number of powers this bot will ask to manage to server.

        - game_prefix: connect only to games with this prefix, or any games when None
    """
    __slots__ = ['host', 'port', 'username', 'password', 'period_seconds', 'player', 'game_to_phase', 'buffer_size', 'game_prefix']

    def __init__(self, host, port, *, period_seconds=PERIOD_SECONDS, buffer_size=128, game_prefix=None):
        """ Initialize the bot.
            :param host: (required) name of host to connect
            :param port: (required) port to connect
            :param period_seconds: time in second between two consecutive bot queries on server. Default 10 seconds.
            :param buffer_size: number of powers to ask to server.
        """
        self.host = host
        self.port = port
        self.username = constants.PRIVATE_BOT_USERNAME
        self.password = constants.PRIVATE_BOT_PASSWORD
        self.period_seconds = period_seconds
        self.player = None
        self.game_to_phase = {}
        self.buffer_size = buffer_size
        self.game_prefix = game_prefix

    @gen.coroutine
    def run(self):
        """ Main bot code. """

        # Creating player
        self.player = BorgiaPlayer() #DipNetSLPlayer()

        # Connecting to server
        connection = yield connect(self.host, self.port)
        LOGGER.info('Connected to %s', connection.url)
        LOGGER.info('Opening a channel.')
        try:
            #channel = yield connection.authenticate(self.username, self.password, create_user=False)
            channel = yield connection.authenticate(self.username, self.password)

            LOGGER.info('Connected as user %s.', self.username)
        except exceptions.ResponseException:
            channel = yield connection.authenticate(self.username, self.password, create_user=True)
            LOGGER.info('Created user %s.', self.username)

        game_dummy_powers = {}
        while True:
            try:
                # The call to channel.get_dummy_waiting_orders() should use game_prefix.
                all_dummy_power_names = yield channel.get_dummy_waiting_powers(buffer_size=self.buffer_size)

                # Getting orders for the dummy powers
                if all_dummy_power_names:
                    LOGGER.info('Managing %d game(s).', len(all_dummy_power_names))
                    yield [self.generate_orders(channel, game_id, dummy_power_names)
                           for game_id, dummy_power_names in all_dummy_power_names.items()
                            if (self.game_prefix is None or str(game_id).startswith(self.game_prefix))]

                    # Cheat for messages. populate active game_ids                
                    for game_id, dummy_power_names in all_dummy_power_names.items():
                        if game_id in game_dummy_powers:
                            if len(dummy_power_names) > len(game_dummy_powers[game_id]):
                                game_dummy_powers[game_id] = dummy_power_names
                        else:
                            game_dummy_powers[game_id] = dummy_power_names

                # Check games for messsages.
                if game_dummy_powers:
                    yield [self.handle_messaging(channel, game_id, dummy_power_names)
                           for game_id, dummy_power_names in game_dummy_powers.items()]

                yield gen.sleep(self.period_seconds)

            # Server error - Logging, but continuing
            except (exceptions.DiplomacyException, RuntimeError) as error:
                LOGGER.error(error)

    @gen.coroutine
    def handle_messaging(self, channel, game_id, dummy_power_names):
        
        try:
            # Join powers.
            yield channel.join_powers(game_id=game_id, power_names=dummy_power_names)

            # Join all games
            games = yield {power_name: channel.join_game(game_id=game_id, power_name=power_name)
                           for power_name in dummy_power_names}

            # Checks for messaging.
            yield [self.submit_messages(games[power_name], power_name) for power_name in dummy_power_names]

        except exceptions.ResponseException as exc:
            LOGGER.error('Exception occurred while working on game %s: %s', game_id, exc)

    @gen.coroutine
    def submit_messages(self, game, power_name):
        """ Retrieves and submits messages for a power
            :param game: An instance of the game object.
            :param power_name: The name of the power submitting messages (e.g. 'FRANCE')
            :type game: diplomacy.client.network_game.NetworkGame
        """

        with game.current_state():
            if isinstance(self.player, BorgiaPlayer):
                
                messages = yield self.player.get_messages(game, power_name)
                
                if messages:
                    yield [game.send_game_message(message=message) for message in messages]
                    for message in messages:
                        LOGGER.info('%s/%s/%s/message: %s', game.game_id, game.current_short_phase, power_name, message.negotiation)

    @gen.coroutine
    def generate_orders(self, channel, game_id, dummy_power_names):
        """ Generate orders for a list of power names in a network game.
            :param channel: a channel connected to a server.
            :param game_id: ID of network game to join.
            :param dummy_power_names: a sequence of power names waiting
                for orders in network game to join.
            :type channel: diplomacy.client.channel.Channel
            :type game_channel: diplomacy.client.channel.Channel
        """
        try:
            # Join powers.
            yield channel.join_powers(game_id=game_id, power_names=dummy_power_names)

            # Join all games
            games = yield {power_name: channel.join_game(game_id=game_id, power_name=power_name)
                           for power_name in dummy_power_names}

            # Retrieves and submits all orders
            yield [self.submit_orders(games[power_name], power_name) for power_name in dummy_power_names]

        except exceptions.ResponseException as exc:
            LOGGER.error('Exception occurred while working on game %s: %s', game_id, exc)

    @gen.coroutine
    def submit_orders(self, game, power_name):
        """ Retrieves and submits orders for a power
            :param game: An instance of the game object.
            :param power_name: The name of the power submitting orders (e.g. 'FRANCE')
            :type game: diplomacy.client.network_game.NetworkGame
        """
        with game.current_state():
            orders, should_draw = yield self.player.get_orders(game, power_name, with_draw=True)

            # Setting vote
            vote = strings.YES if should_draw else strings.NO
            if game.get_power(power_name).vote != vote:
                yield game.vote(power_name=power_name, vote=vote)

            # Setting orders
            yield game.set_orders(power_name=power_name, orders=orders, wait=False)

            # Printing log message
            LOGGER.info('%s/%s/%s/orders: %s', game.game_id, game.current_short_phase, power_name,
                        ', '.join(orders) if orders else '(empty)')

# async def download_models_async():
#     BorgiaPlayer(download_only=True)
#     print('done downloading models')

# def download_models():
#     io_loop = ioloop.IOLoop.instance()
#     io_loop.run_sync(download_models_async)

def main():
    """ Main script function. """
    parser = argparse.ArgumentParser(description='Run a bot to manage unordered dummy powers on a server.')
    parser.add_argument('--host', type=str, default=constants.DEFAULT_HOST,
                        help='run on the given host (default: %s)' % constants.DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=constants.DEFAULT_PORT,
                        help='run on the given port (default: %s)' % constants.DEFAULT_PORT)
    parser.add_argument('--period', type=int, default=PERIOD_SECONDS,
                        help='run every period (in seconds) (default: %d seconds)' % PERIOD_SECONDS)
    parser.add_argument('--buffer-size', type=int, default=128,
                        help='let bot ask for this number of powers to manage on server (default: 128 powers)')
    parser.add_argument('--game-prefix', type=str, default=None,
                        help='connect to only games with this prefix, or all games if None')
    parser.add_argument('--download-models', default=False, action='store_true',
                        help='download bot models without running the app')
    parser.add_argument('--continue-after-download', default=False, action='store_true',
                        help='continue after downloading models (only if download-models is set)')
    args = parser.parse_args()

    LOGGER.info(args)

    # downloading models before running the scripts
    if args.download_models:
        model_url = 'https://jataware-misc.s3.amazonaws.com/neurips2019-sl_model.zip'
        bot_filename = model_url.split('/')[-1]
        bot_name = bot_filename.split('.')[0]
        bot_directory = os.path.join(WORKING_DIR, 'data', 'bot_%s' % bot_name)
        bot_model = os.path.join(bot_directory, bot_filename)
        download_model(model_url, bot_directory, bot_model)
        
        # Downloading container
        tf_serving_img = os.path.join(WORKING_DIR, 'containers', TF_SERVING_DOWNLOAD_URL.split('/')[-1])
        download_file(TF_SERVING_DOWNLOAD_URL, tf_serving_img, force=True)

        if not args.continue_after_download:
            sys.exit(0)

    host = os.getenv('host')
    port = int(os.getenv('port'))
    game_prefix=os.getenv('game_prefix')

    bot = Bot(host, port, period_seconds=args.period, buffer_size=args.buffer_size, game_prefix=game_prefix)
    io_loop = ioloop.IOLoop.instance()
    while True:
        try:
            io_loop.run_sync(bot.run)
        except KeyboardInterrupt:
            LOGGER.error('Bot interrupted.')
            break
        except Exception as exc:                                                         # pylint: disable=broad-except
            LOGGER.error(exc)
            LOGGER.info('Restarting bot...')

if __name__ == '__main__':
    main()
