import datetime
import os
import time
from laserhockey.hockey_env import HockeyEnv
from numbers import Number
from uuid import uuid4

import gym
import numpy as np
from twisted.spread import pb


class GameStates:
    WAITING_FOR_PLAYER = 0
    GAME_RUNNING = 1
    ABORTED = 98
    ERROR = 99


class Game(pb.Viewable):
    def __init__(self, server):
        self.identifier = str(uuid4())[:8]

        self.server = server

        self.clients = (None, None)
        self.last_ob = None
        self.last_player_two_ob = None
        self.action = (None, None)

        self.ob = None
        self.player_two_ob = None
        self.reward = None
        self.done = None
        self.info = None

        self.last_op_timestamp = time.time()

        self.state = GameStates.WAITING_FOR_PLAYER
        self.server.all_games.append(self)
        self.server.waiting_games.append(self)

        self.transition_buffer = []
        self.num_games_played = 0
        self.MAX_GAMES = 4

        self.env = None

    def _start(self):
        self.state = GameStates.GAME_RUNNING
        self.server.running_games.append(self)

        self.env = gym.envs.make("Hockey-v0")
        self.game_outcomes = []
        self.ob = self.env.reset(one_starting=self.num_games_played % 2)

        self.player_two_ob = self.env.obs_agent_two()
        self.last_ob = self.ob
        self.last_player_two_ob = self.player_two_ob

        info = dict(
            id=self.identifier,
            player=(self.clients[0].avatar.username, self.clients[1].avatar.username),
        )

        self.clients[0].game_starts(self.ob.tolist(), info)
        self.clients[1].game_starts(self.player_two_ob.tolist(), info)

        self.last_op_timestamp = time.time()

    def _done(self, ob, player_two_ob, r, done, info):
        self.clients[0].game_done(ob.tolist(), r, done, info)
        self.clients[1].game_done(player_two_ob.tolist(), r, done, info)
        self._save()
        self.server.game_done(self)
        self._close()

    def _save(self):
        now = datetime.datetime.now()

        path = os.path.join(
            self.server.working_dir,
            "games",
            str(now.year),
            str(now.month),
            str(now.day),
        )
        os.makedirs(path, exist_ok=True)
        np.savez(
            os.path.join(path, self.identifier),
            {
                "identifier": self.identifier,
                "player_one": self.clients[0].avatar.username,
                "player_two": self.clients[1].avatar.username,
                "transitions": self.transition_buffer,
                "timestamp": time.time(),
            },
        )

    def _close(self):
        if self in self.server.all_games:
            self.server.all_games.remove(self)
        if self in self.server.waiting_games:
            self.server.waiting_games.remove(self)
        if self in self.server.running_games:
            self.server.running_games.remove(self)

        if self.clients[0] is not None:
            del self.server.client_to_game_mapping[self.clients[0]]
        if self.clients[1] is not None:
            del self.server.client_to_game_mapping[self.clients[1]]

        del self.server.game_to_client_mapping[self]

        if self.env:
            self.env.close()

    # Functions called by server
    def add_player(self, client):
        if self.clients[0] is None:
            self.clients = (client, None)
            self.server.game_to_client_mapping[self] = self.clients
        elif self.clients[1] is None:
            self.clients = (self.clients[0], client)
            self.server.game_to_client_mapping[self] = self.clients

        self.server.client_to_game_mapping[client] = self

        self.last_op_timestamp = time.time()

        if self.clients[0] is not None and self.clients[1] is not None:
            self._start()

    @staticmethod
    def validate_action(action):
        is_valid = True
        if not isinstance(action, list):
            is_valid = False
        if not len(action) == 4:
            is_valid = False
        if not all([isinstance(x, Number) for x in action]):
            is_valid = False

        return is_valid

    # Functions called by client
    def step(self, client, ac):
        if client is self.clients[0]:
            if self.validate_action(ac):
                self.action = (ac, self.action[1])
            else:
                print(f"Invalid action from player {self.clients[0].avatar.username}")
                self.clients[0].send_observation(
                    self.ob.tolist(), self.reward, self.done, self.info
                )
                return
        if client is self.clients[1]:
            if self.validate_action(ac):
                self.action = (self.action[0], ac)
            else:
                print(f"Invalid action from player {self.clients[1].avatar.username}")
                self.clients[1].send_observation(
                    self.player_two_ob.tolist(), self.reward, self.done, self.info
                )
                return

        self.last_op_timestamp = time.time()

        if self.action[0] is not None and self.action[1] is not None:
            self.ob, self.reward, self.done, self.info = self.env.step(
                np.concatenate(self.action)
            )
            self.player_two_ob = self.env.obs_agent_two()

            # if self.state == GameStates.GAME_RUNNING:
            # self.env.render()

            self.transition_buffer.append(
                (self.last_ob, self.action, self.ob, self.reward, self.done, self.info)
            )

            self.last_ob = self.ob
            self.last_player_two_ob = self.player_two_ob

            self.action = (None, None)
            do_reset = False
            if self.done:
                self.num_games_played += 1
                self.game_outcomes.append(self.info["winner"])

                if self.num_games_played >= self.MAX_GAMES:
                    self._done(
                        self.ob, self.player_two_ob, self.reward, self.done, self.info
                    )
                else:
                    self.ob = self.env.reset(one_starting=self.num_games_played % 2)
                    self.player_two_ob = self.env.obs_agent_two()
                    do_reset = True

            if not self.done or do_reset:
                self.clients[0].send_observation(
                    self.ob.tolist(), self.reward, self.done, self.info
                )
                # TODO: Recompute info dict for player two
                self.clients[1].send_observation(
                    self.player_two_ob.tolist(), self.reward, self.done, self.info
                )

    def abort(self, msg):
        self.state = GameStates.ABORTED

        if self.clients[0] is not None:
            self.clients[0].game_aborted(msg)
        if self.clients[1] is not None:
            self.clients[1].game_aborted(msg)

        self._close()


HockeyEnv
