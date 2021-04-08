import os
import pickle
import datetime
from shutil import copyfile
import numpy as np
import argparse

from pychartjs import BaseChart, ChartType, Color, Options


def parseOptions():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        dest="output_dir",
        default=".",
    )
    parser.add_argument(
        "--working-dir",
        type=str,
        dest="working_dir",
        default=".",
    )
    args = parser.parse_args()
    return args


class LineChart(BaseChart):

    type = ChartType.Line

    class labels:
        time = None

    class data:
        class value:
            data = None

            borderColor = Color.JSLinearGradient(
                "ctx", 0, 0, 500, 0, (0, "#1ff4b5"), (0.6, "#1b1a50")
            ).returnGradient()
            pointRadius = 0

    class options:

        title = None
        scales = Options.General(
            xAxes=[Options.General(ticks=Options.General(display=False))]
        )
        legend = Options.General(display=False)


class Fronend:
    def __init__(self, working_dir, output_dir) -> None:

        self.working_dir = working_dir
        self.output_dir = output_dir

        with open(os.path.join(__file__, "templates/head.html"), "r") as f:
            self.head = f.read()

        with open(os.path.join(__file__, "templates/footer.html"), "r") as f:
            self.footer = f.read()

            self.content = []
            # self.add_content(self.statistics)
            self.add_content(self.charts)
            self.add_content(self.ranking)
            # TODO: maybe not show it if too big or only for top teams
            self.add_content(self.leaderboard_link)

    def add_content(self, content_fn):
        self.content.append(content_fn)

    def statistics(self):
        html = f"""<h2>Statistics</h2>
<table class="table table-striped">
<tr>
<td>Active user</td>
<td>{len(self.server.active_avatars)}</td>
</tr>
<tr>
<td>Idle clients</td>
<td>{len(self.server.idle_clients)}</td>
</tr>
<tr>
<td>Waiting clients</td>
<td>{len(self.server.waiting_clients)}</td>
</tr>
<tr>
<td>Playing clients</td>
<td>{len(self.server.playing_clients)}</td>
</tr>
</table>
"""
        return html

    def charts(self):

        stats = self.load_stats()

        def gen_line_chart(key, title, subsampling=1):
            chart = LineChart()
            datetimes = [
                datetime.datetime.fromtimestamp(d[0]) for d in stats[key[0]][key[1]]
            ]
            chart.labels.time = [
                f"{d.day}.{d.month}.{d.year} {d.hour}:{d.minute}" for d in datetimes
            ][-5000::subsampling]
            chart.data.value.data = [p[1] for p in stats[key[0]][key[1]]][
                -5000::subsampling
            ]
            chart.options.title = Options.Title(text=title, fontSize=18)

            return chart.get()

        html = f"""<h2>Statistics</h2>
<div class="row">
<div class="col-lg-3"><canvas id="tot-num-played-games"></canvas></div>
<div class="col-lg-3"><canvas id="playing-games"></canvas></div>
<div class="col-lg-3"><canvas id="waiting-games"></canvas></div>
<div class="col-lg-3"><canvas id="tot-player"></canvas></div>
</div>
<div class="row">
<div class="col-lg-3"><canvas id="con-clients"></canvas></div>
<div class="col-lg-3"><canvas id="idle-clients"></canvas></div>
<div class="col-lg-3"><canvas id="waiting-clients"></canvas></div>
<div class="col-lg-3"><canvas id="playing-clients"></canvas></div>
</div>
<script>
    var ctx = document.getElementById("tot-num-played-games").getContext('2d');
    var data = {gen_line_chart(("games", "total"), "Total Number of Games Played", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("playing-games").getContext('2d');
    var data = {gen_line_chart(("games", "running"), "Running Games", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("waiting-games").getContext('2d');
    var data = {gen_line_chart(("games", "waiting"), "Waiting Games", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("tot-player").getContext('2d');
    var data = {gen_line_chart(("player", "active_player"), "Number of Active Player", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("con-clients").getContext('2d');
    var data = {gen_line_chart(("player", "total_clients"), "Number of Connected Clients", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("idle-clients").getContext('2d');
    var data = {gen_line_chart(("player", "idle_clients"), "Number of Idle Clients", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("waiting-clients").getContext('2d');
    var data = {gen_line_chart(("player", "waiting_clients"), "Number of Waiting Clients", 10)}
    var myChart = new Chart(ctx, data)

    var ctx = document.getElementById("playing-clients").getContext('2d');
    var data = {gen_line_chart(("player", "playing_clients"), "Number of Playing Clients", 10)}
    var myChart = new Chart(ctx, data)
</script>"""

        return html

    def leaderboard_link(self):

        html = """<h2>Leaderboard</h2>
        <p><a href="leaderboard.html" target="_blank">Click here</a> to open the leaderboard</p>
"""

        return html

    def leaderboard(self):

        leaderboard = self.load_leaderboard()

        users = list(leaderboard.keys())

        html = """<h2>Leaderboard</h2>
<table class="table table-hover leaderboard">
<caption><strong>Legend:</strong> Games Won / Games Lost / Drawn Games</caption>
<thead>
<tr>
<th></th>
"""

        html += "".join([f"<th>{user}</th>\n" for user in users]) + "<th>Total</th>\n"
        html += "</tr>\n<tr>\n</thead>"

        sorting = np.argsort(
            [
                -float(leaderboard[user]["total"]["wins"])
                / (
                    leaderboard[user]["total"]["losses"]
                    + leaderboard[user]["total"]["wins"]
                    + leaderboard[user]["total"]["draws"]
                )
                for user in users
            ]
        )

        for user1 in np.asarray(users)[sorting]:
            wins = 0
            losses = 0
            draws = 0
            html += f"<td><strong>{user1}</strong></td>\n"
            for user2 in users:
                if user1 == user2 or user2 not in leaderboard[user1]:
                    html += "<td></td>\n"
                    continue
                wins += leaderboard[user1][user2]["wins"]
                losses += leaderboard[user1][user2]["losses"]
                draws += leaderboard[user1][user2]["draws"]
                html += (
                    f'<td>{leaderboard[user1][user2]["wins"]} / '
                    f'{leaderboard[user1][user2]["losses"]} / '
                    f'{leaderboard[user1][user2]["draws"]}</td>\n'
                )
            html += f"<td>{wins} / {losses} / {draws}</td>\n"
            html += "</tr>\n"
        html += """</table>
"""

        return html

    def ranking(self):

        ranking = self.load_ranking()
        # sort by effective scores
        user_scores = [
            (user, score, std, score - std) for user, (score, std) in ranking.items()
        ]
        sorted_user_scores = sorted(user_scores, key=lambda x: -x[3])

        html = """<h2>Rankings</h2>
<table class="table table-hover ranking">
<caption><strong>Trueskill ranking</strong></caption>
<thead>
<tr>
<th>User</th><th>Score</th><th>Uncertainty</th><th>LCB</th></tr></thead>"""

        for (user, score, std, effective_score) in sorted_user_scores:
            html += f'<tr><td><strong>{user.decode("utf-8")}</strong></td>\n'
            html += f"<td>{np.round(score,2)}</td><td>{np.round(std, 2)}</td><td>{np.round(effective_score, 2)}</td></tr>\n"
        html += "</table>\n"

        return html

    def load_leaderboard(self):
        with open(os.path.join(self.working_dir, "leaderboard.pkl"), "rb") as f:
            leaderboard = pickle.load(f)

        return leaderboard

    def load_ranking(self):
        with open(os.path.join(self.working_dir, "trueskill-ranking.pkl"), "rb") as f:
            ranking = pickle.load(f)
        return ranking

    def load_stats(self):
        with open(os.path.join(self.working_dir, "stats.pkl"), "rb") as f:
            stats = pickle.load(f)

        return stats

    def render(self):
        now = datetime.datetime.now()

        final_html = self.head
        for content_fn in self.content:
            final_html += content_fn()
        final_html += self.footer.format(
            last_update=f"{now.day}.{now.month}.{now.year} {now.hour}:{now.minute}"
        )

        with open(os.path.join(self.output_dir, "index.html"), "w") as f:
            f.write(final_html)

        final_html = self.head
        final_html += self.leaderboard()
        final_html += self.footer.format(
            last_update=f"{now.day}.{now.month}.{now.year} {now.hour}:{now.minute}"
        )

        with open(os.path.join(self.output_dir, "leaderboard.html"), "w") as f:
            f.write(final_html)

        copyfile(
            os.path.join(__file__, "assets/style.css"),
            os.path.join(self.output_dir, "style.css"),
        )


def main(opts):
    frontend = Fronend(opts.working_dir, opts.output_dir)
    frontend.render()


if __name__ == "__main__":
    opts = parseOptions()
    main(opts)
