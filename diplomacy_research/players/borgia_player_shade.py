


""" 
BorgiaPlayer

- A Benchmark Player capable of sending/receiving DAIDE syntax press.
- Inherits from DipNetSLPlayer which inherits from ModelBasedPlayer.

"""


from diplomacy_research.players.benchmark_player import DipNetSLPlayer
from diplomacy.engine.message import Message
from tornado import gen
import json

class BorgiaPlayer(DipNetSLPlayer):
    def __init__(self, temperature=0.1, use_beam=False, port=9501, name=None):
        """ Constructor
            :param temperature: The temperature to apply to the logits.
            :param use_beam: Boolean that indicates that we want to use a beam search.
            :param port: The port to use for the tf serving to query the model.
            :param name: Optional. The name of this player.
        """
       
        super().__init__(temperature=temperature, use_beam=use_beam, port=port, name=name)


    @gen.coroutine
    def get_messages(self, game, power_name, *, retry_on_failure=True, **kwargs):
        """ 
            :param game: The game object
            :param power_name: All caps name of the power being played.
            :param retry_on_failure: Boolean that indicates to retry querying from the model if an error is encountered.
            :type game: diplomacy.Game
        """

        # For when orders are relevant to messaging: 
        # from diplomacy_research.models.state_space import extract_state_proto, extract_phase_history_proto, \
        # extract_possible_orders_proto, get_orderable_locs_for_powers
        # state_proto = extract_state_proto(game)
        # phase_history_proto = extract_phase_history_proto(game)
        # possible_orders_proto = extract_possible_orders_proto(game)

        incoming = {}
        messages = list()
        for message in game.messages.reversed_values():
            if (str(message.sender).lower() == power_name.lower() and power_name not in incoming):
                # We sent the last message to this power so ignore the power.
                incoming[message.recipient] = None

            elif (str(message.recipient).lower() == power_name.lower() and message.sender not in incoming):
                # Use only the latest message from a power.
                incoming[message.sender] = message.message

            for recipient, incoming_message in incoming.items():
                if not incoming_message:
                    continue
                                
                negotiation = { 
                    "1": {
                        "actors": [str(power_name).capitalize()],
                        "targets": [str(recipient).capitalize()],
                    }
                }

                negotiation = json.dumps(negotiation)

                message = Message(phase=game.current_short_phase, sender=game.role, recipient=recipient, message='No way!')

                messages.append(message)

        return messages