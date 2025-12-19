from ninja.throttling import BaseThrottle
import time

class SimpleRateThrottle(BaseThrottle):
    rate = 10            # maksimum 10 request
    duration = 60        # dalam 60 detik

    cache = {}

    def allow_request(self, request):
        ip = request.META.get("REMOTE_ADDR", "unknown")
        now = time.time()

        # Ambil data lama user
        history = self.cache.get(ip, [])
        # Filter hanya yang dalam window 60 detik
        history = [req for req in history if req > now - self.duration]

        if len(history) >= self.rate:
            return False  # BLOCK

        history.append(now)
        self.cache[ip] = history
        return True