"""torch entry point. Shared settings live in config.py."""

from app import cli, run


def main():
    return run("torch")


if __name__ == "__main__":
    cli(main)
