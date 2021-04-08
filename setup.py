import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="gym-multiplayer-server",
    packages=["gym_multiplayer_server", "gym_multiplayer_server.server",
              "gym_multiplayer_server.client", "gym_multiplayer_server.common",
              "gym_multiplayer_server.misc", "gym_multiplayer_server.web_frontend"],
    version="1.0",
    author="Sebastian Blaes",
    author_email="sebastianblaes@gmail.com",
    description="Multiplayer server for 2 player gym environments",
    long_description=long_description,
    url="https://github.com/s-bl/gym-multiplayer-server",
    include_package_data=True,
)