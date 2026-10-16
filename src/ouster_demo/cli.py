"""Command line entry point: ``ouster-demo [serve|doctor|discover]``."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    s = Settings()
    if args.source:
        s.source = args.source
    if args.port:
        s.port = args.port
    if args.host:
        s.host = args.host
    if args.fps:
        s.fps = args.fps
    if args.lidar_port:
        s.lidar_port = args.lidar_port
    if args.imu_port:
        s.imu_port = args.imu_port
    if args.no_auto_udp_dest:
        s.no_auto_udp_dest = True
    if args.no_reinitialize:
        s.no_reinitialize = True
    if args.soft_id_check:
        s.soft_id_check = True
    if args.timeout:
        s.timeout = args.timeout
    if args.no_loop:
        s.loop = False

    print(f"\n  General Autonomy x Ouster  |  source={s.source or '(enter sensor IP in the UI)'}")
    url = "http://genauto.localhost" + ("" if s.port == 80 else f":{s.port}")
    print(f"  Open {url}   (any *.localhost name resolves to this PC; or http://<this-pc-ip>:{s.port} from another machine)\n")
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level=args.log_level)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from . import doctor

    kw = {}
    if args.lidar_port:
        kw["lidar_port"] = args.lidar_port
    return doctor.run(args.host, sdk=args.sdk, listen=args.listen, lidar_port=args.lidar_port or 7502, open_kwargs=kw)


def _discover(_: argparse.Namespace) -> int:
    from . import doctor

    return doctor.discover()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ouster-demo", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    sp = sub.add_parser("serve", help="run the demo server (default)")
    sp.add_argument("--source", help="sensor hostname/IP, or a .pcap/.osf path (env OUSTER_SOURCE)")
    sp.add_argument("--host", help="bind address (default 0.0.0.0)")
    sp.add_argument("--port", type=int, help="HTTP port (default 8080)")
    sp.add_argument("--fps", type=float, help="frame rate cap")
    sp.add_argument("--lidar-port", type=int, default=0, help="UDP lidar destination port")
    sp.add_argument("--imu-port", type=int, default=0, help="UDP IMU destination port")
    sp.add_argument("--no-auto-udp-dest", action="store_true", help="do not set sensor udp_dest automatically")
    sp.add_argument("--no-reinitialize", action="store_true", help="do not reinitialize the sensor")
    sp.add_argument("--soft-id-check", action="store_true", help="tolerate init_id/serial mismatch")
    sp.add_argument("--timeout", type=float, default=0.0, help="seconds to wait for lidar packets")
    sp.add_argument("--no-loop", action="store_true", help="do not loop pcap/osf files")
    sp.add_argument("--log-level", default="info")
    sp.set_defaults(func=_serve)

    dp = sub.add_parser("doctor", help="diagnose a lidar connection step by step")
    dp.add_argument("host", help="sensor hostname/IP (or a pcap path)")
    dp.add_argument("--sdk", action="store_true", help="also run a full SDK connect + decode test")
    dp.add_argument("--listen", type=float, default=4.0, help="seconds to listen for raw UDP (0 to skip)")
    dp.add_argument("--lidar-port", type=int, default=0)
    dp.set_defaults(func=_doctor)

    sub.add_parser("discover", help="find Ouster sensors on the network").set_defaults(func=_discover)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in ("serve", "doctor", "discover", "-h", "--help")):
        argv = ["serve"] + argv        # `ouster-demo --source 10.0.0.5` == `ouster-demo serve --source ...`
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
