import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

A6K = {
    "host": os.environ["A6K_HOST"],
    "port": int(os.getenv("A6K_PORT", "22")),
    "username": os.environ["A6K_USER"],
    "client_keys": [os.path.expanduser(os.getenv("A6K_SSH_KEY", "~/.ssh/id_ed25519"))],
}

ABC = {
    "host": os.environ["ABC_HOST"],
    "port": int(os.environ["ABC_PORT"]),
    "username": os.environ["ABC_USER"],
    "client_keys": [os.path.expanduser(os.getenv("ABC_SSH_KEY", "~/.ssh/id_ed25519"))],
}

