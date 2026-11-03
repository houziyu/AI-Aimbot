"""tensorrt entry point. Shared settings live in config.py."""

from app import cli, run


def main():
    return run("tensorrt")


if __name__ == "__main__":
    cli(main)
