import os

def getenv(name: str, default=None):
    v = os.getenv(name)
    return default if v is None or v == "" else v

MYSQL_HOST = getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_USER = getenv("MYSQL_USER", "root")
MYSQL_PASS = getenv("MYSQL_PASSWORD", "")
MYSQL_DB   = getenv("MYSQL_DATABASE", "inforadar")
