import requests


def get_anpr_zone(backend_url: str, camera_id: str, timeout: float = 2.0):
    url = f"{backend_url.rstrip('/')}/anpr-zones"
    resp = requests.get(url, params={"camera_id": camera_id}, timeout=timeout)
    resp.raise_for_status()
    zones = resp.json()  # expected: [{"zone_id": ..., "polygon": [[x,y], ...]}, ...]
    return zones[0] if zones else None

def get_fences(backend_url: str, camera_id: str, timeout: float = 2.0):
    url = f"{backend_url.rstrip('/')}/fences"
    resp = requests.get(url, params={"camera_id": camera_id}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()  # expected: [{"fence_id": ..., "polygon": [[x,y], ...]}, ...]

def get_loitering_zones(backend_url: str, camera_id: str, timeout: float = 2.0):
    url = f"{backend_url.rstrip('/')}/fences"
    resp = requests.get(url, params={"camera_id": camera_id, "rule_type": "loitering"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()  # expected: [{"zone_id": ..., "polygon": [...], "threshold_seconds": 30}, ...]
