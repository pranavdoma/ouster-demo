# General Autonomy × Ouster: live lidar perception demo

Real Ouster sensor → real-time perception → browser UI. One container, no cloud, no GPU, no model downloads.

* **Stream**: Ouster SDK (live sensor, or `.pcap`/`.osf` replay) → 3D point cloud at the sensor frame rate
* **Perception** (CPU, ~20 ms/frame): ground-plane RANSAC → voxel/Euclidean clustering → oriented 3D boxes →
  rule-based classification (pedestrian / cyclist / car / truck / structure) → Kalman multi-object tracking
  (IDs, speed, heading, trails)
* **UI**: Three.js viewer in General Autonomy branding: split **BEV (top-down) | 3D** view with thin, depth-faded
  lidar-style points. Colour by scan (height × intensity) / class / height / intensity / range, live
  tuning sliders, object list, pipeline timing, one-click source switching. Fully offline (no CDN).

> Verified on an **OS0-32, firmware 2.1.2**. Because that firmware predates the SDK 1.x metadata API, the SDK is
> pinned to **`ouster-sdk==0.12.0`**. If you have newer firmware (≥ 3.x) you can try a newer SDK.

## Run it (one file)

```bash
./launch.sh                 # start (sensor IP from .env, default 169.254.43.8) -> http://genauto.localhost
./launch.sh 192.168.1.50    # start against a specific sensor
./launch.sh stop | status | logs | doctor | discover | native
```

All instructions are also in the header of [`launch.sh`](launch.sh).

## Run it (Docker, manual)

```bash
cp .env.example .env          # set OUSTER_SOURCE=<sensor ip>   (or leave empty and type it in the UI)
docker compose up -d --build
# open http://genauto.localhost   (PORT=80 in .env; any *.localhost name resolves to this PC, no setup)
# from another machine: http://<this-pc-ip>:<PORT>
```

Docker uses `network_mode: host` on purpose: the sensor pushes UDP to this machine and bridge networking breaks
that. Linux only. On macOS/Windows run natively.

## Run it (native)

```bash
make install
make run SENSOR=192.168.1.50          # or: .venv/bin/ouster-demo --source 192.168.1.50
```

Requires Python ≥ 3.9. Sensor on a direct cable with no DHCP? It uses a link-local `169.254.x.x` address:
find it with `ip neigh` / `ouster-demo discover` and give your NIC an address on that link.

## When something is wrong

```bash
ouster-demo doctor <sensor-ip> --sdk     # DNS → ping → HTTP API → config → UDP → SDK decode, with fixes
```

The UI shows the same failure as an overlay card. Full playbook: [docs/LAB_DEBUG.md](docs/LAB_DEBUG.md).

## Options

| Env var / flag | Meaning |
|---|---|
| `OUSTER_SOURCE` / `--source` | sensor hostname/IP, or path to `.pcap` / `.osf` |
| `PORT` / `--port` | UI port (default 8080) |
| `OUSTER_NO_AUTO_UDP_DEST`, `OUSTER_LIDAR_PORT`, `OUSTER_IMU_PORT`, `OUSTER_NO_REINIT`, `OUSTER_SOFT_ID_CHECK`, `OUSTER_TIMEOUT` | advanced sensor/network behaviour, see `.env.example` |

Record a run for later replay: `ouster-cli source <ip> save data/run.pcap`, then use `/data/run.pcap` as the source.

## How it works

```
Ouster sensor ──UDP──▶ ouster-sdk ──▶ Frame(xyz, range, reflectivity)
                                         │
                       perception/  ground ▸ cluster ▸ boxes ▸ tracker
                                         │
              engine (thread, auto-reconnect) ──▶ binary WebSocket (8 B/point + JSON header)
                                         │
                              FastAPI  ──▶  web/ (Three.js)
```

* `src/ouster_demo/sources/` – SDK adapter (the only place that touches the SDK)
* `src/ouster_demo/perception/` – the perception stack; swap in a learned detector by replacing
  `cluster.py`/`boxes.py` and returning `Detection` objects
* `src/ouster_demo/engine.py` – source → perception → publish, with reconnect/backoff and error surfacing
* `src/ouster_demo/web/` – UI (vendored Three.js + Inter / IBM Plex Mono fonts)
* `tests/` – pipeline + server tests using a test-only simulator in `ouster_demo/dev` (`make test`)

## Notes / limitations

* Perception is **classical** (no neural network), which keeps it deterministic, CPU-only and dependency-free.
  Class labels are geometric heuristics, tuned for people/vehicles; indoors, furniture can be mislabelled.
* Speeds are in the sensor frame: correct in world terms for a stationary sensor.
* Defaults assume a stationary sensor that can see some floor; tune *Perception tuning* in the UI otherwise.
