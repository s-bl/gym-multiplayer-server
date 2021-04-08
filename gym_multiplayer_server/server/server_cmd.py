import cmd

from twisted.internet import reactor


class ServerCMD(cmd.Cmd):
    intro = "Type help or ? to list commands.\n"
    prompt = "(cmd) "
    file = None

    def __init__(self, server):
        super().__init__()

        self.server = server

    def do_list_all_games(self, arg):
        "list all games"
        self.server.list_all_games()

    def do_list_avatars(self, arg):
        "list avatars"
        self.server.list_avatars()

    def do_show_leaderboard_matrix(self, arg):
        "Show leaderboard"
        self.server.show_leaderboard_matrix()

    def do_quit(self, arg):
        reactor.callFromThread(self.server.quit)
        return True

    def precmd(self, line):
        line = line.lower()
        return line
