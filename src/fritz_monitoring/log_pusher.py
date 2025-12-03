#!/usr/bin/env python3
"""Push Fritz!Box logs from exporter to Loki."""

import asyncio
import aiohttp
import json
from datetime import datetime, timezone
import time

EXPORTER_URL = "http://fritz_exporter:8000/logs"
LOKI_URL = "http://loki:3100/loki/api/v1/push"
POLL_INTERVAL = 60  # seconds


async def fetch_and_push_logs():
    """Fetch logs from exporter and push to Loki."""
    async with aiohttp.ClientSession() as session:
        # Fetch logs from exporter
        try:
            async with session.get(EXPORTER_URL) as resp:
                if resp.status != 200:
                    print(f"Error fetching logs: {resp.status}")
                    return

                log_text = await resp.text()
                if not log_text.strip():
                    print("No logs received")
                    return

                # Parse NDJSON logs
                logs = []
                for line in log_text.strip().split('\n'):
                    if line:
                        logs.append(json.loads(line))

                if not logs:
                    print("No log entries found")
                    return

                # Filter logs to only recent ones (last 48 hours to be safe with Loki limits)
                now = datetime.now(timezone.utc)
                max_age_hours = 48
                recent_logs = []
                for log in logs:
                    try:
                        ts = datetime.fromisoformat(log['timestamp'])
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        age_hours = (now - ts).total_seconds() / 3600
                        if age_hours <= max_age_hours:
                            recent_logs.append(log)
                    except:
                        pass

                if not recent_logs:
                    print(f"No recent logs found (filtered {len(logs)} old entries)")
                    return

                # Sort logs by timestamp (oldest first) so Loki accepts them in order
                recent_logs.sort(key=lambda x: x['timestamp'])

                print(f"Fetched {len(logs)} log entries, {len(recent_logs)} are recent enough for Loki")

                # Prepare Loki push request
                streams = {}
                for log in recent_logs:
                    # Create label set
                    labels = {
                        'job': 'fritzbox-logs',
                        'severity': log.get('severity', ''),
                        'source': log.get('source', ''),
                        'category': log.get('category', ''),
                    }

                    # Remove empty labels
                    labels = {k: v for k, v in labels.items() if v}

                    # Convert to Loki label string
                    label_str = '{' + ','.join(f'{k}="{v}"' for k, v in sorted(labels.items())) + '}'

                    # Parse timestamp
                    try:
                        ts = datetime.fromisoformat(log['timestamp'])
                        # Use current time for logs to avoid Loki rejection
                        # Store original timestamp in the message
                        original_ts = ts.strftime('%Y-%m-%d %H:%M:%S')
                        ts_ns = str(int(time.time() * 1_000_000_000))
                        # Prepend original timestamp to message
                        message = f"[{original_ts}] {log['message']}"
                    except:
                        ts_ns = str(int(time.time() * 1_000_000_000))
                        message = log['message']

                    # Group by label set
                    if label_str not in streams:
                        streams[label_str] = {
                            'stream': labels,
                            'values': []
                        }

                    streams[label_str]['values'].append([ts_ns, message])

                # Push to Loki
                payload = {
                    'streams': list(streams.values())
                }

                async with session.post(LOKI_URL, json=payload) as resp:
                    if resp.status == 204:
                        print(f"Successfully pushed {len(recent_logs)} logs to Loki")
                    else:
                        print(f"Error pushing to Loki: {resp.status}")
                        error_text = await resp.text()
                        print(f"Response: {error_text}")

        except Exception as e:
            print(f"Error: {e}")


async def main():
    """Main loop."""
    print("Fritz!Box Log Pusher started")
    print(f"Polling {EXPORTER_URL} every {POLL_INTERVAL} seconds")

    while True:
        await fetch_and_push_logs()
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    asyncio.run(main())
