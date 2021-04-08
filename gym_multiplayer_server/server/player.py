import os
import pickle
import time
from uuid import uuid4

from trueskill import Rating
from twisted.spread import pb

from gym_multiplayer_server.common.error import ServerClientVersionMissmatchError


class ClientState:
    IDLE = 0
    WAITING_FOR_GAME = 1
    PLAYING = 2
    DETACHED = 98
    ERROR = 99


class Client(pb.Referenceable):
    def __init__(self, server, avatar, mind):
        self.identifier = str(uuid4())[:8]
        self.server = server
        self.avatar = avatar
        self.mind = mind
        self.game = None

        self.state = ClientState.IDLE

        self._add_to_server_list("idle", to_global_list=True)

    def _remove_from_server_list(self, from_global_list=False):
        if from_global_list:
            if self in self.server.all_connected_clients:
                self.server.all_connected_clients.remove(self)
        if self in self.server.idle_clients:
            self.server.idle_clients.remove(self)
        if self in self.server.waiting_clients:
            self.server.waiting_clients.remove(self)
        if self in self.server.playing_clients:
            self.server.playing_clients.remove(self)

    def _add_to_server_list(self, list_name, to_global_list=False):
        self._remove_from_server_list()

        if to_global_list:
            self.server.all_connected_clients.append(self)

        if list_name == "idle":
            self.server.idle_clients.append(self)
        elif list_name == "waiting":
            self.server.waiting_clients.append(self)
        elif list_name == "playing":
            self.server.playing_clients.append(self)

    def _connection_error(self, *args, **kwargs):
        self.avatar.detached(self.mind)

    def __hash__(self):
        return hash(self.identifier)

    # Functions called by remote client
    def remote_request_stats(self):
        keys = [
            "username",
            "finished_games",
            "games_lost",
            "games_won",
            "games_drawn",
        ]
        return {
            key: value for key, value in self.avatar.get_state().items() if key in keys
        }

    def remote_start_queuing(self):
        self.state = ClientState.WAITING_FOR_GAME
        self._add_to_server_list("waiting")

        self.game = self.server.join_game(self)

    def remote_stop_queueing(self):
        self.game.abort("Stop queuing")
        self.game = None
        self.state = ClientState.IDLE
        self._add_to_server_list("idle")

    def remote_receive_action(self, ac):
        self.game.step(self, ac)

    # Functions called by game
    def game_starts(self, ob, info):
        self.state = ClientState.PLAYING
        self._add_to_server_list("playing")

        try:
            d = self.mind.callRemote("game_starts", ob=ob, info=info)
            d.addErrback(self._connection_error)
        except pb.DeadReferenceError:
            self._connection_error()

    def send_observation(self, ob, r, done, info):
        try:
            d = self.mind.callRemote(
                "receive_observation", ob=ob, r=r, done=done, info=info
            )
            d.addErrback(self._connection_error)
        except pb.DeadReferenceError:
            self._connection_error()

    def game_done(self, ob, r, done, info):
        try:
            if self.game.clients[0] is self:
                player = 1
            else:
                player = 2

            games_won = 0
            games_lost = 0
            games_drawn = 0

            for winner in self.game.game_outcomes:
                if winner == 0:
                    self.avatar.games_drawn += 1
                    games_drawn += 1
                elif winner == 1 and player == 1:
                    self.avatar.games_won += 1
                    games_won += 1
                elif winner != 1 and player == 2:
                    games_won += 1
                    self.avatar.games_won += 1
                else:
                    self.avatar.games_lost += 1
                    games_lost += 1

            d = self.mind.callRemote(
                "game_done",
                ob=ob,
                r=r,
                done=done,
                info=info,
                result={
                    "games_played": len(self.game.game_outcomes),
                    "games_won": games_won,
                    "games_lost": games_lost,
                    "games_drawn": games_drawn,
                },
            )
            d.addErrback(self._connection_error)

            self.avatar.finished_games_ids.append(self.game.identifier)
            self.avatar.finished_games += 1

            self.game = None
            self.state = ClientState.IDLE
            self._add_to_server_list("idle")

        except pb.DeadReferenceError:
            self._connection_error()

    def game_aborted(self, msg):
        try:
            d = self.mind.callRemote("game_aborted", msg=msg)
            d.addErrback(self._connection_error)
            self._add_to_server_list("idle")
        except pb.DeadReferenceError:
            self._connection_error()

    # Functions called by player
    def detached(self):
        self.state = ClientState.DETACHED

        self._remove_from_server_list(from_global_list=True)

        if self in self.server.client_to_game_mapping:
            game = self.game
            game.abort(f"Player {self.avatar.username} left the game")


class Avatar(pb.Avatar):
    def __init__(self, username, server):
        self.server = server
        self.username = username
        self.clients = []
        self.finished_games_ids = []
        self.finished_games = 0
        self.games_lost = 0
        self.games_won = 0
        self.games_drawn = 0
        self.last_saved = None
        self.rating = Rating()
        self.rating_mu = self.rating.mu
        self.rating_sigma = self.rating.sigma

    def attached(self, mind):
        if len(self.clients) == 0:
            self.server.active_avatars.append(self)

        client = Client(server=self.server, avatar=self, mind=mind)
        self.clients.append(client)

    def detached(self, mind):
        try:
            client = [client for client in self.clients if client.mind is mind][0]
            self.clients.remove(client)
            client.detached()

            if len(self.clients) == 0:
                self.server.active_avatars.remove(self)
        except:
            pass

    # Functions called by remote client
    def perspective_check_server_client_compatibility(self, client_version):
        if client_version != self.server.__VERSION__:
            raise ServerClientVersionMissmatchError(
                f"Client vers. {client_version} and server vers."
                f"{self.server.__VERSION__} incompatible, please update"
            )
        return True

    def perspective_request_remote_client(self, mind):
        client = [
            client for client in self.clients if client.mind.broker is mind.broker
        ][0]
        return client

    def get_state(self):
        state = dict(
            username=self.username,
            finished_games_ids=self.finished_games_ids,
            last_saved=time.time(),
            finished_games=self.finished_games,
            games_lost=self.games_lost,
            games_won=self.games_won,
            games_drawn=self.games_drawn,
            rating_mu=self.rating.mu,
            rating_sigma=self.rating.sigma,
        )

        return state

    # Functions called by server
    def save(self, path):
        state = self.get_state()

        path = os.path.join(path, "avatars")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, self.username + ".pkl"), "wb") as f:
            pickle.dump(state, f)

    def load(self, path):
        path = os.path.join(path, "avatars", self.username + ".pkl")
        if os.path.exists(path):
            with open(path, "rb") as f:
                state = pickle.load(f)

            self.__dict__.update(state)
            self.rating = Rating(self.rating_mu, self.rating_sigma)
