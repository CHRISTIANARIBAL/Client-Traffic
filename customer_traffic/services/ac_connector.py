
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from librouteros import connect


PORT = int(os.getenv("MIKROTIK_API_PORT", "8728"))
USERNAME = os.getenv("MIKROTIK_API_USERNAME", "")
PASSWORD = os.getenv("MIKROTIK_API_PASSWORD", "")
API_TIMEOUT = float(os.getenv("MIKROTIK_API_TIMEOUT", "3"))

AC_CONFIG = (
    ("AC1", "10.99.2.31"),
    ("AC2", "10.99.2.32"),
    ("AC3", "10.99.2.33"),
)


class ACConnection:
    def __init__(self, name, ip):
        self.name = name
        self.ip = ip
        self.api = None
        self.lock = threading.Lock()

    def _connect_locked(self):
        if self.api is not None:
            return self.api

        if not USERNAME or not PASSWORD:
            raise RuntimeError(
                "Set MIKROTIK_API_USERNAME and MIKROTIK_API_PASSWORD."
            )

        api = connect(
            host=self.ip,
            username=USERNAME,
            password=PASSWORD,
            port=PORT,
            timeout=API_TIMEOUT,
        )

        self.api = api
        globals()[f"api_{self.name.lower()}"] = api
        return api

    def _disconnect_locked(self):
        api = self.api
        self.api = None
        globals()[f"api_{self.name.lower()}"] = None

        if api is not None:
            try:
                api.close()
            except Exception:
                pass

    def fetch_queues(self):
        with self.lock:
            try:
                api = self._connect_locked()
                return list(api("/queue/simple/print"))
            except Exception:
                self._disconnect_locked()
                raise

    def connect_once(self):
        with self.lock:
            try:
                self._connect_locked()
                return True
            except Exception as error:
                self._disconnect_locked()
                print(f"{self.name} connection failed: {error}")
                return False


AC_CONNECTIONS = {
    name: ACConnection(name, ip)
    for name, ip in AC_CONFIG
}

api_ac1 = None
api_ac2 = None
api_ac3 = None

lock_ac1 = AC_CONNECTIONS["AC1"].lock
lock_ac2 = AC_CONNECTIONS["AC2"].lock
lock_ac3 = AC_CONNECTIONS["AC3"].lock

TRAFFIC_EXECUTOR = ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix="mikrotik-traffic",
)


def get_access_concentrators():
    return list(AC_CONNECTIONS.values())


def start_connections():
    for connection in get_access_concentrators():
        print(f"Connecting to {connection.name}...")
        if connection.connect_once():
            print(f"{connection.name} connected.")


def search_ac(connection, queue_name):
    try:
        queues = connection.fetch_queues()

        for queue in queues:
            if queue.get("name") != queue_name:
                continue

            upload, download = queue.get("rate", "0/0").split("/", 1)

            return {
                "ac": connection.name,
                "pppoe_username": queue_name,
                "upload": int(upload),
                "download": int(download),
            }

    except Exception as error:
        print(f"{connection.name} traffic lookup failed: {error}")

    return None


def get_customer_traffic(queue_name):
    futures = [
        TRAFFIC_EXECUTOR.submit(search_ac, connection, queue_name)
        for connection in get_access_concentrators()
    ]

    results = []

    for future in futures:
        try:
            results.append(future.result())
        except Exception as error:
            print(f"Traffic lookup worker failed: {error}")
            results.append(None)

    return next(
        (result for result in results if result is not None),
        None,
    )
