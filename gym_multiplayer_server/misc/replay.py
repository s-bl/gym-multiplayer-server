import argparse
import ast
import time

import imageio
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os
from glob import glob
import datetime
import pandas

from laserhockey.hockey_env import HockeyEnv, FPS, CENTER_X, CENTER_Y


def set_env_state_from_observation(env, observation):
    env.player1.position = (observation[[0, 1]] + [CENTER_X, CENTER_Y]).tolist()
    env.player1.angle = observation[2]
    env.player1.linearVelocity = [observation[3], observation[4]]
    env.player1.angularVelocity = observation[5]
    env.player2.position = (observation[[6, 7]] + [CENTER_X, CENTER_Y]).tolist()
    env.player2.angle = observation[8]
    env.player2.linearVelocity = [observation[9], observation[10]]
    env.player2.angularVelocity = observation[11]
    env.puck.position = (observation[[12, 13]] + [CENTER_X, CENTER_Y]).tolist()
    env.puck.linearVelocity = [observation[14], observation[15]]


def setup_video(output_path, id, fps):
    os.makedirs(output_path, exist_ok=True)
    file_path = os.path.join(output_path, f"{id}.mp4")
    print("Record video in {}".format(file_path))
    # noinspection SpellCheckingInspection
    return (
        imageio.get_writer(
            file_path, fps=35, codec="mjpeg", quality=10, pixelformat="yuvj444p"
        ),
        file_path,
    )


def main(games_path, games_db_path, id, record, render, output_path, verbose, players):

    if players is not None:
        players = ast.literal_eval(players)

    env = HockeyEnv()

    selected_matches = pandas.read_csv(games_db_path)

    matches_path = glob(os.path.join(games_path, "**", "*.npz"), recursive=True)

    if players is not None:
        selected_matches = selected_matches[
            (
                (selected_matches["player_one"] == players[0])
                & (selected_matches["player_two"] == players[1])
            )
            | (
                (selected_matches["player_one"] == players[1])
                & (selected_matches["player_two"] == players[0])
            )
        ]
    if not id is None:
        selected_matches = selected_matches[selected_matches["identifier"] == id]
    if players is None and id is None:
        selected_matches = selected_matches.drop_duplicates(
            subset=["player_one", "player_two"], keep="last"
        )

    print(selected_matches)

    for index, selected_match in selected_matches.iterrows():

        match_path = glob(
            os.path.join(games_path, "**", f'{selected_match["identifier"]}.npz'),
            recursive=True,
        )[0]
        match = np.load(match_path, allow_pickle=True)["arr_0"].item()

        if verbose:
            print("Match id: ", match["identifier"])
            print(
                "Date:"
                + datetime.date.fromtimestamp(match["timestamp"]).strftime(
                    "%m/%d/%Y, %H:%M:%S"
                )
            )
            print(f'{match["player_one"]} vs {match["player_two"]}')
        # noinspection PyChainedComparisons

        if record:
            video, video_path = setup_video(
                output_path,
                match["identifier"]
                + "_"
                + match["player_one"]
                + "_vs_"
                + match["player_two"],
                FPS,
            )

        player_one_score = 0
        player_two_score = 0
        for transition in match["transitions"]:
            set_env_state_from_observation(env, np.asfarray(transition[0]))

            if transition[4]:
                if transition[5]["winner"] == 1:
                    player_one_score += 1
                if transition[5]["winner"] == -1:
                    player_two_score += 1

            if verbose:
                if transition[4]:
                    if transition[5]["winner"] == 0:
                        print("Game end in a draw")
                    elif transition[5]["winner"] == 1:
                        print(f'{match["player_one"]} scored.')
                    else:
                        print(f'{match["player_two"]} scored.')

            if record:
                red = (235, 98, 53)
                blue = (93, 158, 199)
                frame = env.render(mode="rgb_array")
                img = Image.fromarray(frame)
                draw = ImageDraw.Draw(img)
                # font = ImageFont.truetype(<font-file>, <font-size>)
                font = ImageFont.truetype("f2-tecnocratica-ffp.ttf", 24)
                # draw.text((x, y),"Sample Text",(r,g,b))
                draw.rectangle((0, 0, 608, 26), fill=(100, 100, 100))
                draw.text((5, 0), match["player_one"][:25], red, font=font)
                w, h = draw.textsize(match["player_two"][:25], font=font)
                draw.text((595 - w, 0), match["player_two"][:25], blue, font=font)

                font = ImageFont.truetype("f2-tecnocratica-ffp.ttf", 32)
                draw.text((5, 480 - 32 - 5), str(player_one_score), red, font=font)
                w, h = draw.textsize(str(player_two_score), font=font)
                draw.text(
                    (595 - w, 480 - 32 - 5), str(player_two_score), blue, font=font
                )

                # noinspection PyUnboundLocalVariable
                video.append_data(np.asarray(img))
            elif render:
                env.render()
                time.sleep(1 / FPS)

        for _ in range(60):
            video.append_data(np.asarray(img))

        if record:
            video.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--games-path", help="Path to games")
    parser.add_argument("--games-db-path", help="Path to games db")
    parser.add_argument(
        "--record", action="store_true", help="Whether to record video or not"
    )
    parser.add_argument(
        "--render", action="store_true", help="Whether to record video or not"
    )
    parser.add_argument("--id", default=None, help="id of game you want to replay")
    parser.add_argument("--players", default=None, help="name of the players")
    parser.add_argument("--output-path", default=None, help="Where to save video")
    parser.add_argument("--verbose", action="store_true", help="Print more info")

    args = parser.parse_args()
    main(
        args.games_path,
        args.games_db_path,
        args.id,
        args.record,
        args.render,
        args.output_path,
        args.verbose,
        args.players,
    )
