from slowapi import Limiter
from fastapi import Request


def get_real_ip(request: Request):
    """
    Retrieve the real IP address of the client from the request headers.

    This function checks for the IP address in the following order:
    1. "CF-Connecting-IP" header (used by Cloudflare)
    2. "X-Forwarded-For" header (used by proxies)
    3. Falls back to the client's direct connection IP

    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host


limiter = Limiter(key_func=get_real_ip)
