"""Single-instance sandbox supervisor; workers pause when the free host sleeps."""
import os
import signal
import subprocess
import sys
import time


def configure_environment(env):
    hostname = env.get("RENDER_EXTERNAL_HOSTNAME")
    if hostname:
        base = "https://" + hostname
        env.setdefault("TRUSTED_HOSTS", hostname + ",localhost,127.0.0.1")
        env.setdefault("CORS_ORIGINS", base)
        env.setdefault("PAYMENT_CALLBACK_URL", base + "/api/v1/payments/webhooks")
        for name in ("checkout", "deposit", "payout", "refund"):
            env.setdefault("PAWAPAY_" + name.upper() + "_CALLBACK_URL", base + "/api/v1/payments/pawapay/" + name + "-callback")
    if env.get("DATABASE_URL", "").startswith("postgresql://"):
        env["DATABASE_URL"] = env["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)


def main():
    configure_environment(os.environ)
    children = []
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        migration = subprocess.Popen([sys.executable, "-m", "alembic", "upgrade", "head"])
        children.append(migration)
        while migration.poll() is None and not stopping:
            time.sleep(0.25)
        if stopping:
            return 0
        if migration.returncode:
            return migration.returncode
        commands = [
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"],
            [sys.executable, "-m", "app.workers.notification_worker"],
            ["caddy", "run", "--config", "/app/deploy/Caddyfile", "--adapter", "caddyfile"],
        ]
        children = []
        for command in commands:
            children.append(subprocess.Popen(command))
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1  # Let the hosting platform restart the whole healthy group.
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 20
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
