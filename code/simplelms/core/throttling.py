from ninja.throttling import BaseThrottle
import time
import sys
from django.conf import settings

class SimpleRateThrottle(BaseThrottle):
    rate = 10
    duration = 60
    cache = {}

    def allow_request(self, request):
        if 'test' in sys.argv or getattr(settings, 'TESTING', False):
            return True
            
        ip = request.META.get("REMOTE_ADDR", "unknown")
        now = time.time()
        history = self.cache.get(ip, [])
        history = [req for req in history if req > now - self.duration]
        
        if len(history) >= self.rate:
            return False
            
        history.append(now)
        self.cache[ip] = history
        return True