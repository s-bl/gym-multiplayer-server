import pickle
import sys
import os
import time
import datetime
import argparse
from glob import glob
import pathlib
import numpy as np
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from trueskill import quality_1vs1, rate_1vs1, Rating

from zope.interface import implementer

from twisted.cred import portal, checkers
from twisted.spread import pb
from twisted.internet import reactor, task

from gym_multiplayer_server.server.player import Avatar
from gym_multiplayer_server.server.game import Game
from gym_multiplayer_server.server.server_cmd import ServerCMD


def parseOptions():
    parser = argparse.ArgumentParser(
        description="Competition Server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--non-interactive",
        action="store_false",
        dest="interactive",
        default=True,
        help="Run in non-interactive mode, for testing purposes",
    )
    parser.add_argument(
        "--working-dir",
        type=str,
        dest="working_dir",
        default="/tmp/laser-hockey-rl/server/logs",
    )
    args = parser.parse_args()
    return args


class AuthenticationError(Exception):
    pass


class GameServer:

    __VERSION__ = "1.0"

    def __init__(self, working_dir: str, interactive=True):

        self.interactive = interactive

        self.avatars = {}

        self.active_avatars = []

        self.all_connected_clients = []
        self.idle_clients = []
        self.waiting_clients = []
        self.playing_clients = []

        self.game_to_client_mapping = {}
        self.client_to_game_mapping = {}

        self.total_num_played_games = 0
        self.all_games = []
        self.running_games = []
        self.waiting_games = []

        self.leaderboard_matrix = {}

        self.stats = defaultdict(dict)

        self.working_dir = working_dir
        os.makedirs(self.working_dir, exist_ok=True)
        self._load()

        task.LoopingCall(self.maintainance_loop).start(10.0)

        if self.interactive:
            self.server_cmd = ServerCMD(self)
            reactor.callInThread(self.server_cmd.cmdloop)

        reactor.addSystemEventTrigger("before", "shutdown", self._close)

    def _save(self):
        ranking = {}
        for username, avatar in self.avatars.items():
            ranking[username] = (avatar.rating.mu, avatar.rating.sigma)
            avatar.save(self.working_dir)

        with open(os.path.join(self.working_dir, "trueskill-ranking.pkl"), "wb") as f:
            pickle.dump(ranking, f)

        with open(os.path.join(self.working_dir, "leaderboard.pkl"), "wb") as f:
            pickle.dump(self.leaderboard_matrix, f)

        with open(os.path.join(self.working_dir, "stats.pkl"), "wb") as f:
            pickle.dump(self.stats, f)

        with open(os.path.join(self.working_dir, "misc.pkl"), "wb") as f:
            pickle.dump({"total_num_played_games": self.total_num_played_games}, f)

    def _load(self):
        for avatar_state_file in glob(os.path.join(self.working_dir, "avatars", "*")):
            username = pathlib.Path(avatar_state_file).stem
            avatar = Avatar(username, self)
            avatar.load(self.working_dir)
            self.avatars[username.encode("utf-8")] = avatar

        if os.path.exists(os.path.join(self.working_dir, "leaderboard.pkl")):
            with open(os.path.join(self.working_dir, "leaderboard.pkl"), "rb") as f:
                self.leaderboard_matrix = pickle.load(f)

        if os.path.exists(os.path.join(self.working_dir, "stats.pkl")):
            with open(os.path.join(self.working_dir, "stats.pkl"), "rb") as f:
                self.stats = pickle.load(f)

        if os.path.exists(os.path.join(self.working_dir, "misc.pkl")):
            with open(os.path.join(self.working_dir, "misc.pkl"), "rb") as f:
                self.__dict__.update(pickle.load(f))

    def _close(self):
        print("Server stopped")
        self._save()

    def abort_game(self, game, msg):
        game.abort(msg)

    def maintainance_loop(self):
        current_time = time.time()
        for game in self.all_games:
            if (
                current_time - game.last_op_timestamp > 60 * 2
                and not game.clients[1] is None
            ):
                game.abort("Game aborted due to timeout (2 min)")

        for client in self.all_connected_clients:
            if client.mind.broker.disconnected:
                client.detached()
        for client in self.idle_clients:
            if client.mind.broker.disconnected:
                client.detached()
        for client in self.waiting_clients:
            if client.mind.broker.disconnected:
                client.detached()
        for client in self.playing_clients:
            if client.mind.broker.disconnected:
                client.detached()

        self.stats["games"].setdefault("total", []).append(
            [current_time, self.total_num_played_games]
        )
        self.stats["games"].setdefault("total_open", []).append(
            [current_time, len(self.all_games)]
        )
        self.stats["games"].setdefault("waiting", []).append(
            [current_time, len(self.waiting_games)]
        )
        self.stats["games"].setdefault("running", []).append(
            [current_time, len(self.running_games)]
        )

        self.stats["player"].setdefault("active_player", []).append(
            [current_time, len(self.active_avatars)]
        )
        self.stats["player"].setdefault("total_clients", []).append(
            [current_time, len(self.all_connected_clients)]
        )
        self.stats["player"].setdefault("idle_clients", []).append(
            [current_time, len(self.idle_clients)]
        )
        self.stats["player"].setdefault("waiting_clients", []).append(
            [current_time, len(self.waiting_clients)]
        )
        self.stats["player"].setdefault("playing_clients", []).append(
            [current_time, len(self.playing_clients)]
        )

        self._save()

    # Functions called from cmd
    def list_all_games(self):
        current_time = datetime.datetime.now()
        print(
            "{:10}{:15}{:15}{:20}".format(
                "ID", "Player 1", "Player 2", "last operation delta"
            )
        )
        print("".join(["-"] * 60))
        for game in self.all_games:
            time_delta = relativedelta(
                current_time, datetime.datetime.fromtimestamp(game.last_op_timestamp)
            )
            print(
                "{:10}{:15}{:15}{:20}".format(
                    game.identifier,
                    game.clients[0].avatar.username
                    if game.clients[0] is not None
                    else "",
                    game.clients[1].avatar.username
                    if game.clients[1] is not None
                    else "",
                    f"{time_delta.days:02}d, {time_delta.hours:02}h, {time_delta.minutes:02}m, {time_delta.seconds:02}s",
                )
            )

    def list_avatars(self):
        print(
            "{:15}{:20}{:15}{:15}{:15}{:15}".format(
                "Username",
                "Connected Clients",
                "Finished Games",
                "Games Won",
                "Games Lost",
                "Games Drawn",
            )
        )
        print("".join(["-"] * 95))
        for avatar in self.avatars.values():
            print(
                "{:15}{:<20}{:<15}{:<15}{:<15}{:<15}".format(
                    avatar.username,
                    len(avatar.clients),
                    avatar.finished_games,
                    avatar.games_won,
                    avatar.games_lost,
                    avatar.games_drawn,
                )
            )

    def show_leaderboard_matrix(self):
        users = list(self.leaderboard_matrix.keys())

        print(("{:<10}" * (len(users) + 1)).format(" ", *users))
        print("-" * (10 * (len(users) + 1)))
        for user1 in users:
            ln = "{:<10}".format(user1)
            for user2 in users:
                if user1 == user2:
                    ln += " " * 10
                    continue
                if user2 not in self.leaderboard_matrix[user1]:
                    ln += " " * 10
                    continue
                ln += "{:<10}".format(
                    f'{self.leaderboard_matrix[user1][user2]["wins"]}/'
                    f'{self.leaderboard_matrix[user1][user2]["losses"]}/'
                    f'{self.leaderboard_matrix[user1][user2]["draws"]}'
                )
            print(ln)

    def quit(self, *args, **kwargs):
        reactor.stop()

    # Functions called by client
    def join_game(self, client):
        game = None

        all_eligible_games = [
            potential_game
            for potential_game in self.waiting_games
            if (potential_game.clients[0].avatar is not client.avatar)
            and not (
                "BasicOpponent" in potential_game.clients[0].avatar.username
                and "BasicOpponent" in client.avatar.username
            )
        ]  # not strong against weak
        num_total = len(self.all_connected_clients)
        if (
            len(all_eligible_games) > num_total // 6
        ):  # only match up of there is pool to choose from
            own_rating = client.avatar.rating
            qualities = np.array(
                [
                    quality_1vs1(own_rating, g.clients[0].avatar.rating)
                    for g in all_eligible_games
                ]
            )
            # add something for long waiting_time (5 minutes means you have a very high chance to be matched)
            waiting_time = time.time() - np.array(
                [g.last_op_timestamp for g in all_eligible_games]
            )
            qualities += np.minimum(1.0, waiting_time / (60.0 * 5))
            game_idx = np.random.choice(
                range(len(qualities)), p=qualities / np.sum(qualities)
            )
            game = all_eligible_games[game_idx]
            self.waiting_games.remove(game)
            game.add_player(client)

        if game is None:
            game = Game(server=self)
            game.add_player(client)

        return game

    # Function called by Game
    def game_done(self, game):
        player_one, player_two = [c.avatar.username for c in game.clients]
        player_one_avatar, player_two_avatar = [c.avatar for c in game.clients]
        for winner in game.game_outcomes:
            if player_one not in self.leaderboard_matrix:
                self.leaderboard_matrix[player_one] = dict()
                self.leaderboard_matrix[player_one]["total"] = {
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                }
            if player_two not in self.leaderboard_matrix[player_one]:
                self.leaderboard_matrix[player_one][player_two] = {
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                }

            if player_two not in self.leaderboard_matrix:
                self.leaderboard_matrix[player_two] = dict()
                self.leaderboard_matrix[player_two]["total"] = {
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                }
            if player_one not in self.leaderboard_matrix[player_two]:
                self.leaderboard_matrix[player_two][player_one] = {
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                }

            def rating_interpolation(rating_old, rating_new):
                return Rating(
                    0.1 * rating_new.mu + 0.9 * rating_old.mu,
                    0.1 * rating_new.sigma + 0.9 * rating_old.sigma,
                )

            if winner == 0:
                self.leaderboard_matrix[player_one][player_two]["draws"] += 1
                self.leaderboard_matrix[player_two][player_one]["draws"] += 1
                self.leaderboard_matrix[player_one]["total"]["draws"] += 1
                self.leaderboard_matrix[player_two]["total"]["draws"] += 1
                new_one, new_two = rate_1vs1(
                    player_one_avatar.rating, player_two_avatar.rating, drawn=True
                )
                # apply only 10% of update, because draws are not very informative
                new_one = rating_interpolation(player_one_avatar.rating, new_one)
                new_two = rating_interpolation(player_two_avatar.rating, new_two)
            elif winner == 1:
                self.leaderboard_matrix[player_one][player_two]["wins"] += 1
                self.leaderboard_matrix[player_two][player_one]["losses"] += 1
                self.leaderboard_matrix[player_one]["total"]["wins"] += 1
                self.leaderboard_matrix[player_two]["total"]["losses"] += 1
                new_one, new_two = rate_1vs1(
                    player_one_avatar.rating, player_two_avatar.rating
                )
            else:
                self.leaderboard_matrix[player_one][player_two]["losses"] += 1
                self.leaderboard_matrix[player_two][player_one]["wins"] += 1
                self.leaderboard_matrix[player_one]["total"]["losses"] += 1
                self.leaderboard_matrix[player_two]["total"]["wins"] += 1
                new_two, new_one = rate_1vs1(
                    player_two_avatar.rating, player_one_avatar.rating
                )

            player_one_avatar.rating = new_one
            player_two_avatar.rating = new_two

        self.total_num_played_games += 1


@implementer(portal.IRealm)
class GameServerRealm:
    def requestAvatar(self, avatarID, mind, *interfaces):

        assert pb.IPerspective in interfaces

        if avatarID not in self.server.avatars:
            avatar = Avatar(avatarID.decode("utf-8"), self.server)
            self.server.avatars[avatarID] = avatar
        else:
            avatar = self.server.avatars[avatarID]
        return pb.IPerspective, avatar, lambda a=avatar: a.detached(mind)


def main(opts):
    realm = GameServerRealm()
    realm.server = GameServer(
        interactive=opts.interactive, working_dir=opts.working_dir
    )
    checker = checkers.FilePasswordDB("./users.db", cache=True)
    p = portal.Portal(realm, [checker])
    reactor.listenTCP(33000, pb.PBServerFactory(p))
    reactor.run()


if __name__ == "__main__":
    opts = parseOptions()
    main(opts)
