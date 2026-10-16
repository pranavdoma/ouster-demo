# General Autonomy × Ouster: live lidar perception demo

Plug in an Ouster sensor (OS0 / OS1 / OS2), open a browser, see the live 3D point cloud with
real-time perception on top: ground removal, object detection with oriented 3D boxes,
classification (pedestrian / cyclist / vehicle / structure) and multi-object tracking with speed.

* **Source:** a real Ouster sensor via the official [Ouster SDK](https://github.com/ouster-lidar/ouster-sdk) (`ouster-sdk==1.0.1`).
  `.pcap` / `.osf` recordings work through the same code path.
* **Perception:** classical, CPU-only, no model downloads. RANSAC ground plane → voxel-connectivity
  clustering → minimum-area oriented boxes → rule-based classification → Kalman filter + Hungarian tracker.
  ~20 ms/frame for a 128×1024 frame, so it keeps up with a 10 Hz sensor.
* **UI:** Three.js viewer in General Autonomy branding, served by FastAPI over a binary WebSocket.
  All assets (Three.js, fonts, logo) are vendored, so it runs on an offline lab network.

## Run it

### Docker (any Linux PC)

```bash
cp .env.example .env          # set OUSTER_SOURCE=<sensor ip>   (or leave empty and type it in the UI)
docker compose up -d --build
# open http://localhost:8080
```

`docker-compose.yml` uses `network_mode: host`. That is **required**: the sensor pushes UDP to the
host, and Docker's bridge network breaks it. (Linux only; on macOS/Windows use the native install.)

### Native

```bash
make install                  # creates .venv, installs the package
make run SENSOR=192.168.1.50  # or: .venv/bin/ouster-demo --source 192.168.1.50
```

Python ≥ 3.9. Open `http://localhost:8080` (or `http://<this-pc>:8080` from another machine).
The sensor can be changed live from the **Source** box in the UI.

## When the sensor does not behave

```bash
ouster-demo discover                       # find sensors on the LAN
ouster-demo doctor <SENSOR_IP> --sdk       # DNS → ping → HTTP API → config → UDP → SDK decode
```

The UI also shows the failure and hints on screen. Full checklist: **[docs/LAB_DEBUG.md](docs/LAB_DEBUG.md)**.

## Configuration

Environment variables (or CLI flags, see `ouster-demo serve --help`):

| Variable | Default | Meaning |
|---|---|---|
| `OUSTER_SOURCE` | *(empty)* | sensor hostname/IP or `.pcap`/`.osf` path; empty = enter in UI |
| `PORT` | `8080` | web UI port |
| `OUSTER_FPS` | `10` | frame-rate cap (replay pacing and UI) |
| `OUSTER_TIMEOUT` | `5` | seconds to wait for packets |
| `OUSTER_LIDAR_PORT` / `OUSTER_IMU_PORT` | `0` | fixed UDP ports (0 = SDK default) |
| `OUSTER_NO_AUTO_UDP_DEST` | `0` | don't let the SDK set the sensor's `udp_dest` |
| `OUSTER_NO_REINIT` | `0` | never reinitialize the sensor |
| `OUSTER_SOFT_ID_CHECK` | `0` | tolerate `init_id`/serial mismatch |

Perception thresholds (max range, max height, ground tolerance, cluster gap, min points) can be tuned
live in the UI under **Perception tuning**; defaults are in `src/ouster_demo/config.py`.

## Layout

```
src/ouster_demo/
  sources/ouster_source.py   Ouster SDK -> Frame (live sensor, pcap, osf)
  perception/                ground.py · cluster.py · boxes.py · tracker.py · pipeline.py
  engine.py                  source -> perception -> encoded frame, auto-reconnect
  server.py, protocol.py     FastAPI app, WebSocket binary frame format
  doctor.py, cli.py          diagnostics and entry point
  web/                       index.html · style.css · app.js · vendored three.js, fonts, logo
  dev/sim_source.py          test-only synthetic OS0/OS2 generator (used by the test-suite, not by the product)
tests/                       pipeline + server tests (no hardware needed)
docs/LAB_DEBUG.md            real-sensor troubleshooting
```

## Notes and limits

* Velocities are in the **sensor frame**: correct in world terms when the sensor is stationary.
  On a moving platform they are relative (no ego-motion compensation).
* Classification is geometric (size/shape rules), tuned for people, bikes and cars. It is not a
  learned detector; swapping one in means producing `Detection` objects from `perception/boxes.py`.
* The ground model is one plane. Ramps and uneven floors will leak ground into objects.
* Objects seen from one side only get their depth filled from a class prior.
* Tests: `make test` (needs no sensor). On machines with ROS sourced, the Makefile sets
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` to avoid ROS's pytest plugins breaking collection.
* The Ouster SDK is under its own license (BSD-3-Clause + Ouster freeware EULA); Three.js is MIT; Inter and IBM Plex Mono are OFL.
