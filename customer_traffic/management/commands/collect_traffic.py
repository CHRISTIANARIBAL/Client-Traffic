
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand
from django.utils import timezone

from customer_traffic.models import CustomerProfile, TrafficHistory
from customer_traffic.services import ac_connector
from customer_traffic.services.traffic_cache import (
    set_live_traffic_batch,
    set_ac_health,
)


class Command(BaseCommand):
    help = "Collect MikroTik traffic concurrently and track AC health"

    def handle(self, *args, **options):
        interval = 1.0
        history_interval = max(
            1,
            int(os.getenv("TRAFFIC_HISTORY_INTERVAL", "5")),
        )
        last_history = 0.0
        last_report = time.monotonic()
        stats = self.new_stats()

        self.stdout.write("Starting traffic collector...")
        self.stdout.write(
            f"Concurrent AC polling | interval: {interval}s | "
            f"history interval: {history_interval}s"
        )

        ac_connector.start_connections()

        while True:
            cycle_started = time.monotonic()
            write_history = (
                cycle_started - last_history >= history_interval
            )

            try:
                result = self.collect_traffic(
                    write_history=write_history
                )
                self.update_stats(stats, result)

                if write_history:
                    last_history = time.monotonic()

            except Exception as error:
                stats["errors"] += 1
                self.stderr.write(f"Collection error: {error}")

            elapsed = time.monotonic() - cycle_started
            stats["cycles"] += 1
            stats["cycle_total_ms"] += elapsed * 1000
            stats["cycle_max_ms"] = max(
                stats["cycle_max_ms"], elapsed * 1000
            )

            if elapsed > interval:
                stats["overruns"] += 1

            if time.monotonic() - last_report >= 60:
                self.print_report(stats)
                stats = self.new_stats()
                last_report = time.monotonic()

            time.sleep(max(0, interval - elapsed))

    def new_stats(self):
        return {
            "cycles": 0,
            "cycle_total_ms": 0.0,
            "cycle_max_ms": 0.0,
            "overruns": 0,
            "errors": 0,
            "queues_cached": 0,
            "redis_total_ms": 0.0,
            "history_query_total_ms": 0.0,
            "history_insert_total_ms": 0.0,
            "history_rows": 0,
            "matched_profiles": 0,
            "history_batches": 0,
            "acs": {},
        }

    def update_stats(self, stats, result):
        stats["queues_cached"] += result["queues_cached"]
        stats["redis_total_ms"] += result["redis_ms"]
        stats["history_query_total_ms"] += result["history_query_ms"]
        stats["history_insert_total_ms"] += result["history_insert_ms"]
        stats["history_rows"] += result["history_rows"]
        stats["matched_profiles"] += result["matched_profiles"]
        stats["history_batches"] += int(result["history_written"])

        for name, data in result["acs"].items():
            current = stats["acs"].setdefault(
                name,
                {
                    "calls": 0,
                    "total_ms": 0.0,
                    "max_ms": 0.0,
                    "queues": 0,
                    "failures": 0,
                },
            )
            current["calls"] += 1
            current["total_ms"] += data["duration_ms"]
            current["max_ms"] = max(
                current["max_ms"], data["duration_ms"]
            )
            current["queues"] += data["queue_count"]
            current["failures"] += int(data["failed"])

    def print_report(self, stats):
        cycles = max(stats["cycles"], 1)

        self.stdout.write("\n--- Collector performance (last minute) ---")
        self.stdout.write(f"Cycles completed: {stats['cycles']}")
        self.stdout.write(
            f"Average cycle: {stats['cycle_total_ms'] / cycles:.1f} ms"
        )
        self.stdout.write(
            f"Slowest cycle: {stats['cycle_max_ms']:.1f} ms"
        )
        self.stdout.write(
            f"Cycles exceeding 1.0s: {stats['overruns']}"
        )
        self.stdout.write(f"Collection errors: {stats['errors']}")

        for name, data in sorted(stats["acs"].items()):
            calls = max(data["calls"], 1)
            self.stdout.write(
                f"{name}: average fetch "
                f"{data['total_ms'] / calls:.1f} ms, "
                f"max {data['max_ms']:.1f} ms, "
                f"average queues {data['queues'] / calls:.0f}, "
                f"failures {data['failures']}"
            )

        self.stdout.write(
            f"Queues cached per minute total: {stats['queues_cached']}"
        )
        self.stdout.write(
            f"Redis write average: {stats['redis_total_ms'] / cycles:.1f} ms/cycle"
        )
        self.stdout.write(
            f"History query/build average: "
            f"{stats['history_query_total_ms'] / cycles:.1f} ms/cycle"
        )
        self.stdout.write(
            f"History insert average: "
            f"{stats['history_insert_total_ms'] / cycles:.1f} ms/cycle"
        )
        self.stdout.write(
            f"History batches written: {stats['history_batches']}"
        )
        self.stdout.write(
            f"History records written: {stats['history_rows']}"
        )
        self.stdout.write(
            f"Profiles matched in history batches: "
            f"{stats['matched_profiles']}"
        )
        self.stdout.write("-------------------------------------------\n")

    def collect_traffic(self, write_history=False):
        connections = ac_connector.get_access_concentrators()
        queues = {}
        timestamp = timezone.now().isoformat()

        metrics = {
            "acs": {},
            "queues_cached": 0,
            "redis_ms": 0.0,
            "history_query_ms": 0.0,
            "history_insert_ms": 0.0,
            "history_rows": 0,
            "matched_profiles": 0,
            "history_written": False,
        }

        # Fetch all ACs concurrently. Each AC still uses its own connection lock.
        with ThreadPoolExecutor(
            max_workers=max(1, len(connections)),
            thread_name_prefix="ac-poll",
        ) as executor:
            submitted = {
                executor.submit(connection.fetch_queues): (
                    connection,
                    time.monotonic(),
                )
                for connection in connections
            }

            for future in as_completed(submitted):
                connection, started = submitted[future]
                failed = False
                queue_count = 0
                error_message = None

                try:
                    result = future.result()
                    queue_count = len(result)

                    for queue in result:
                        queue_name = queue.get("name")

                        if not queue_name or queue_name in queues:
                            continue

                        try:
                            upload, download = queue.get(
                                "rate", "0/0"
                            ).split("/", 1)

                            queues[queue_name] = {
                                "ac": connection.name,
                                "pppoe_username": queue_name,
                                "upload": int(upload),
                                "download": int(download),
                                "timestamp": timestamp,
                            }
                        except (ValueError, TypeError):
                            continue

                except Exception as error:
                    failed = True
                    error_message = str(error)[:300]
                    self.stderr.write(
                        f"{connection.name} collection failed: {error}"
                    )

                duration_ms = (time.monotonic() - started) * 1000
                health = {
                    "ac": connection.name,
                    "status": "unhealthy" if failed else "healthy",
                    "checked_at": timezone.now().isoformat(),
                    "duration_ms": round(duration_ms, 2),
                    "queue_count": queue_count,
                    "error": error_message,
                }

                metrics["acs"][connection.name] = {
                    "duration_ms": duration_ms,
                    "queue_count": queue_count,
                    "failed": failed,
                }

                # Health uses its own Redis key, separate from traffic readings.
                try:
                    set_ac_health(connection.name, health)
                except Exception as error:
                    self.stderr.write(
                        f"{connection.name} health update failed: {error}"
                    )

        # Cache successful readings from all responding ACs.
        started = time.monotonic()
        try:
            set_live_traffic_batch(queues)
            metrics["queues_cached"] = len(queues)
        except Exception as error:
            self.stderr.write(f"Live traffic cache update failed: {error}")

        metrics["redis_ms"] = (time.monotonic() - started) * 1000

        if not write_history or not queues:
            return metrics

        started = time.monotonic()
        profiles = CustomerProfile.objects.filter(
            pppoe_username__in=queues.keys()
        ).only("id", "pppoe_username")

        history_timestamp = timezone.now()
        records = []

        for profile in profiles.iterator(chunk_size=2000):
            traffic = queues.get(profile.pppoe_username)

            if traffic is None:
                continue

            records.append(
                TrafficHistory(
                    customer_id=profile.id,
                    pppoe_username=profile.pppoe_username,
                    ac=traffic["ac"],
                    upload=traffic["upload"],
                    download=traffic["download"],
                    timestamp=history_timestamp,
                )
            )

        metrics["history_query_ms"] = (
            time.monotonic() - started
        ) * 1000
        metrics["matched_profiles"] = len(records)

        if records:
            started = time.monotonic()
            TrafficHistory.objects.bulk_create(
                records,
                batch_size=1000,
            )
            metrics["history_insert_ms"] = (
                time.monotonic() - started
            ) * 1000
            metrics["history_rows"] = len(records)
            metrics["history_written"] = True

        return metrics
