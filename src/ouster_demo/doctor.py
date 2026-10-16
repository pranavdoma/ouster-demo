"""``ouster-demo doctor``: step-by-step diagnosis of a lidar connection.

Walks the same path the real stream takes - DNS -> reachability -> sensor HTTP API ->
sensor config -> UDP delivery -> SDK decode - and says exactly where it breaks.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional

import requests

OK, WARN, FAIL = "\033[32m[ OK ]\033[0m", "\033[33m[WARN]\033[0m", "\033[31m[FAIL]\033[0m"
if not sys.stdout.isatty():
    OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"


def _p(tag: str, msg: str, hint: str = "") -> None:
    print(f"{tag} {msg}")
    if hint:
        for line in hint.splitlines():
            print(f"       -> {line}")


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def check_host_resolution(host: str) -> Optional[str]:
    try:
        ip = socket.gethostbyname(host)
        _p(OK, f"'{host}' resolves to {ip}")
        return ip
    except socket.gaierror as exc:
        hint = "Use the sensor IP address directly, or check that the sensor is powered and on this network."
        if host.endswith(".local"):
            hint = (
                "mDNS (.local) lookups fail inside Docker bridge networks and on hosts without avahi.\n"
                "Use the sensor's IP, or run `ouster-demo discover` to find it."
            )
        _p(FAIL, f"cannot resolve '{host}': {exc}", hint)
        return None


def check_ping(ip: str) -> bool:
    if shutil.which("ping") is None:
        _p(WARN, "ping not installed, skipping ICMP test")
        return True
    r = subprocess.run(["ping", "-c", "3", "-W", "2", ip], capture_output=True, text=True)
    if r.returncode == 0:
        line = [ln for ln in r.stdout.splitlines() if "rtt" in ln or "round-trip" in ln]
        _p(OK, f"ping {ip} OK " + (line[0].split("=")[-1].strip() if line else ""))
        return True
    _p(
        FAIL,
        f"no ping reply from {ip}",
        "Check the Ethernet cable / link light, sensor power, and that this PC is on the same subnet.\n"
        "Sensor default is link-local (169.254.x.x) or DHCP; a direct PC<->sensor cable needs a\n"
        "link-local/static address on this PC (e.g. `nmcli con mod <eth> ipv4.method link-local`).",
    )
    return False


def check_route(ip: str) -> None:
    if platform.system() != "Linux" or shutil.which("ip") is None:
        return
    r = subprocess.run(["ip", "-o", "route", "get", ip], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        _p(OK, "route: " + r.stdout.strip().split("\\")[0][:140])
        parts = r.stdout.split()
        if "dev" in parts:
            dev = parts[parts.index("dev") + 1]
            mtu = _read(f"/sys/class/net/{dev}/mtu")
            if mtu:
                _p(OK, f"interface {dev} MTU {mtu}")
                if int(mtu) <= 1500:
                    _p(
                        WARN,
                        "MTU is 1500: 128-beam sensors send UDP datagrams larger than that, so they arrive IP-fragmented",
                        "Fine on a quiet link, but if frames drop try a larger MTU on a dedicated NIC:\n"
                        f"  sudo ip link set {dev} mtu 9000   (switch/NIC must support jumbo frames)",
                    )


def check_http(ip: str):
    base = f"http://{ip}"
    out = {}
    for name, path in (
        ("firmware", "/api/v1/system/firmware"),
        ("config", "/api/v1/sensor/config"),
        ("sensor_info", "/api/v1/sensor/metadata/sensor_info"),
    ):
        try:
            r = requests.get(base + path, timeout=4)
            r.raise_for_status()
            out[name] = r.json()
        except requests.HTTPError as exc:
            if name == "sensor_info":
                _p(WARN, "sensor_info endpoint missing (HTTP 404): sensor runs OLD firmware (<2.2)",
                   "Use ouster-sdk==0.12.0 (pinned in this project); SDK 0.13+/1.x need newer firmware.")
            else:
                _p(WARN, f"GET {path}: {exc}")
        except Exception as exc:  # noqa: BLE001
            _p(FAIL, f"GET {path}: {type(exc).__name__}: {exc}",
               "The sensor HTTP API (port 80) is unreachable. Wrong IP, different subnet, or a firewall.")
            if name == "firmware":
                return None
    fw = out.get("firmware", {}).get("fw") or out.get("sensor_info", {}).get("image_rev")
    si = out.get("sensor_info", {})
    _p(OK, f"sensor firmware: {fw}" + (f" ({si.get('prod_line')} S/N {si.get('prod_sn')})" if si else ""))
    cfg = out.get("config", {})
    if cfg:
        keys = ("lidar_mode", "udp_dest", "udp_port_lidar", "udp_port_imu", "operating_mode", "timestamp_mode", "azimuth_window")
        _p(OK, "config: " + ", ".join(f"{k}={cfg[k]}" for k in keys if k in cfg))
        if str(cfg.get("operating_mode", "NORMAL")).upper() == "STANDBY":
            _p(WARN, "operating_mode is STANDBY - the sensor is not spinning/streaming", "Set to NORMAL (the SDK does this automatically when it reinitializes).")
        if not cfg.get("udp_dest"):
            _p(WARN, "udp_dest is not set - the sensor does not know where to send data", "The SDK sets it automatically unless OUSTER_NO_AUTO_UDP_DEST=1.")
    return out


def local_ips_towards(ip: str) -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, 80))
        addr = s.getsockname()[0]
        s.close()
        return addr
    except OSError:
        return None


def check_sysctl() -> None:
    if platform.system() != "Linux":
        return
    rmem = _read("/proc/sys/net/core/rmem_max")
    if rmem and int(rmem) < 4 * 1024 * 1024:
        _p(
            WARN,
            f"net.core.rmem_max={rmem} is small; the UDP socket buffer may overflow at 10-20 Hz on 128 beams",
            "sudo sysctl -w net.core.rmem_max=26214400",
        )
    elif rmem:
        _p(OK, f"net.core.rmem_max={rmem}")
    frag = _read("/proc/sys/net/ipv4/ipfrag_high_thresh")
    if frag and int(frag) < 8 * 1024 * 1024:
        _p(
            WARN,
            f"net.ipv4.ipfrag_high_thresh={frag}: IP fragment reassembly buffer is small",
            "If frames arrive incomplete/missing: sudo sysctl -w net.ipv4.ipfrag_high_thresh=67108864",
        )
    elif frag:
        _p(OK, f"net.ipv4.ipfrag_high_thresh={frag}")


def check_udp(port: int, seconds: float, expect_ip: Optional[str]) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", port))
    except OSError as exc:
        _p(WARN, f"cannot bind UDP {port}: {exc}", "Another process (maybe the demo itself, or ouster-cli) is already receiving. Stop it and re-run.")
        return
    sock.settimeout(0.5)
    t_end = time.time() + seconds
    n, nbytes, srcs = 0, 0, set()
    while time.time() < t_end:
        try:
            data, addr = sock.recvfrom(65535)
            n += 1
            nbytes += len(data)
            srcs.add(addr[0])
        except socket.timeout:
            continue
    sock.close()
    if n:
        _p(OK, f"received {n} UDP packets ({nbytes / 1e6:.2f} MB, {nbytes * 8 / seconds / 1e6:.0f} Mbit/s) on port {port} from {sorted(srcs)}")
        if expect_ip and expect_ip not in srcs:
            _p(WARN, f"packets came from {sorted(srcs)}, not {expect_ip}", "Another sensor on the network may be streaming to this PC.")
    else:
        _p(
            FAIL,
            f"no UDP packets on port {port} in {seconds:.0f}s",
            "Sensor reachable but nothing arrives: udp_dest is not this PC, or a firewall is dropping UDP.\n"
            "  - Let the SDK configure it (default): run the demo / `--sdk` check below.\n"
            f"  - Firewall: sudo ufw allow {port}/udp   (and the IMU port) or `sudo ufw disable` for a bench test.\n"
            "  - In Docker use host networking (`network_mode: host`); bridge networking breaks sensor UDP.\n"
            "  - Multiple NICs: make sure the route to the sensor uses the NIC you expect (see 'route' above).",
        )


def check_sdk(source: str, open_kwargs: dict) -> None:
    try:
        from ouster.sdk import open_source, client
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        _p(FAIL, f"ouster-sdk import failed: {exc}", "pip install 'ouster-sdk==0.12.0'")
        return
    try:
        from importlib.metadata import version

        _p(OK, f"ouster-sdk {version('ouster-sdk')}")
    except Exception:  # noqa: BLE001
        pass
    t0 = time.time()
    try:
        src = open_source(source, **open_kwargs)
    except Exception as exc:  # noqa: BLE001
        _p(FAIL, f"open_source failed: {exc}", "HTTP/connect errors = reachability; 404 on sensor_info = SDK too new for this firmware.")
        return
    info = src.metadata
    _p(OK, f"SDK connected in {time.time() - t0:.1f}s: {info.prod_line} {info.format.pixels_per_column}x{info.format.columns_per_frame} @ {info.format.fps} Hz, FW {info.fw_rev}")
    lut = client.XYZLut(info)
    got = 0
    t_start = time.time()
    for scan in src:
        rng = np.asarray(scan.field(client.ChanField.RANGE))
        valid = rng > 0
        pts = np.asarray(lut(scan))[valid]
        got += 1
        _p(
            OK if valid.mean() > 0.2 else WARN,
            f"frame {got}: {valid.mean() * 100:.0f}% valid pixels, {valid.sum()} points, "
            f"max range {rng.max() / 1000:.1f} m, z span {pts[:, 2].min():.2f}..{pts[:, 2].max():.2f} m",
            "" if valid.mean() > 0.2 else "Very few returns: sensor facing a wall / dome cap on / dirty window?",
        )
        if got >= 5 or time.time() - t_start > 20:
            break
    if got == 0:
        _p(FAIL, "SDK opened the sensor but produced no complete frames", "Almost always UDP loss: see the UDP checks above (firewall, Docker bridge, rmem, fragmentation).")
    try:
        src.close()
    except Exception:  # noqa: BLE001
        pass
    sys.stdout.flush()
    os._exit(0)  # the SDK's receive thread can keep the process alive after close()


def run(host: str, sdk: bool = False, listen: float = 4.0, lidar_port: int = 7502, open_kwargs: Optional[dict] = None) -> int:
    print(f"== ouster-demo doctor: {host} ({platform.platform()}) ==")
    if os.path.exists(os.path.expanduser(host)):
        print("This looks like a file; running the SDK decode check only.")
        check_sdk(host, {})
        return 0
    ip = check_host_resolution(host)
    if not ip:
        return 2
    reachable = check_ping(ip)
    check_route(ip)
    me = local_ips_towards(ip)
    if me:
        _p(OK, f"this PC reaches the sensor via {me}")
    http = check_http(ip)
    check_sysctl()
    if http is None:
        print("\nStopping: the sensor HTTP API is unreachable (fix networking first).")
        return 2
    cfg = http.get("config", {})
    port = int(cfg.get("udp_port_lidar") or lidar_port)
    if listen > 0:
        dest = cfg.get("udp_dest")
        if dest and me and dest != me:
            _p(WARN, f"sensor udp_dest={dest} but this PC is {me}", "Packets go to the other host. The SDK will fix this on connect (unless auto udp_dest is disabled).")
        print(f"... listening for UDP on {port} for {listen:.0f}s")
        check_udp(port, listen, ip)
    if sdk:
        check_sdk(host, open_kwargs or {})
    print("\nTip: add --sdk to run the full SDK connect + decode test (this will (re)configure udp_dest).")
    return 0 if reachable else 1


def discover(timeout: float = 8.0) -> int:
    """Find sensors on the LAN (wraps the SDK's own `ouster-cli discover`)."""
    exe = shutil.which("ouster-cli") or os.path.join(os.path.dirname(sys.executable), "ouster-cli")
    if not os.path.exists(exe):
        print("ouster-cli not found; reinstall ouster-sdk")
        return 1
    print("Searching for Ouster sensors (Ctrl+C to stop)...")
    try:
        return subprocess.call([exe, "discover"], timeout=max(timeout, 10) * 2)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        return 0


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"hint": "use `ouster-demo doctor`"}))
