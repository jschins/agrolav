"""Browser IP as seen through Caddy: public egress, not loopback or LAN."""
from shared.http_ip import request_client_ip

__all__ = ["request_client_ip"]
