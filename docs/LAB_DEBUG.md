# Lab debugging: real Ouster sensor

Work top to bottom. Each step has one command and a clear "what it means".

## 0. Fast path

```bash
ouster-demo discover                      # find sensors on the LAN (mDNS)
ouster-demo doctor <SENSOR_IP> --sdk      # walks DNS -> ping -> HTTP API -> config -> UDP -> SDK decode
make run SENSOR=<SENSOR_IP>               # or: docker compose up   (with OUSTER_SOURCE set in .env)
```

Cross-check with Ouster's own viewer (needs a display; stop the demo first, both want UDP 7502):

```bash
.venv/bin/ouster-cli source <SENSOR_IP> viz
```

If that shows no points either, the problem is the network/sensor, not this app.

`doctor` stops at the first thing that is broken and prints what to try. The UI shows the same
failure (overlay card) with the same hints, so you don't need to read logs first.

## 1. Network basics

| Symptom | Likely cause | Fix |
|---|---|---|
| `cannot resolve os-xxxx.local` | mDNS not available (Docker, no avahi) | Use the IP address |
| No ping | cable / power / wrong subnet | Link LED? PC and sensor on same subnet? |
| Direct PC<->sensor cable, no DHCP | sensor falls back to link-local `169.254.x.x` | Give the PC a link-local or static IP on that NIC: `nmcli con mod <con> ipv4.method link-local && nmcli con up <con>` |
| HTTP API (port 80) fails but ping works | wrong IP / proxy env vars | `unset http_proxy https_proxy`; `curl http://<ip>/api/v1/sensor/metadata/sensor_info` |

Sensor IP unknown? `ouster-demo discover`, check the router's DHCP table, or read it off the
sensor's web page at `http://os-<serial>.local`.

## 2. Sensor reachable but no data (the most common lab problem)

The sensor *pushes* UDP to a destination address (`udp_dest`). Nothing arrives if that is not this PC.

1. `ouster-demo doctor <ip>`: the "listening for UDP" step tells you whether packets reach this PC at all.
2. **Docker**: must use host networking (`network_mode: host`, already set in `docker-compose.yml`).
   Bridge networking drops sensor UDP. Linux only. On macOS/Windows run natively (`make install run`).
3. **Firewall**: `sudo ufw allow 7502/udp && sudo ufw allow 7503/udp` (or `sudo ufw disable` for a bench test).
4. **Several NICs / VPN**: `doctor` prints the route used to reach the sensor. The sensor will be told to
   send to the address of that NIC.
5. **You set `udp_dest` yourself** (e.g. a fixed multicast/other host): set `OUSTER_NO_AUTO_UDP_DEST=1`
   and `OUSTER_LIDAR_PORT`/`OUSTER_IMU_PORT` to match.
6. Another program already holds UDP 7502 (Ouster Studio, `ouster-cli`, a second copy of the demo): stop it.

## 3. Frames arrive but are incomplete / choppy

128-beam sensors send datagrams larger than a 1500-byte MTU, so they arrive IP-fragmented. A busy link or
small kernel buffers drops fragments, and the SDK discards incomplete frames.

```bash
sudo sysctl -w net.core.rmem_max=26214400
sudo sysctl -w net.ipv4.ipfrag_high_thresh=67108864
# dedicated NIC + jumbo-capable switch:  sudo ip link set <iface> mtu 9000
```

`doctor` checks both sysctls and prints the MTU of the NIC facing the sensor. Use a dedicated Gigabit
NIC (or a direct cable) rather than a busy shared network.

## 4. Sensor config / firmware

* `open_source failed ... firmware`: SDK 1.0.x supports current FW 3.x/2.x; check `doctor` output for
  the sensor's FW and compare with the Ouster SDK release notes. The SDK version is pinned in
  `pyproject.toml`.
* Sensor says `STANDBY`: it is not spinning. The SDK sets `operating_mode=NORMAL` when it reinitializes.
  If you disabled that (`OUSTER_NO_REINIT=1`), set it yourself from the sensor web UI.
* After a sensor reboot you may see `init_id`/serial mismatch warnings: `OUSTER_SOFT_ID_CHECK=1`.
* Lower the load: set the sensor to `512x10` or `1024x10` lidar mode from its web UI. The demo
  supports any mode.

## 5. Looks wrong in the viewer

| Symptom | Fix |
|---|---|
| Everything is "ground" / ground plane wrong | Sensor must see some floor. Make sure the sensor is level and the floor is within ~30 m. Raise **Ground tolerance** in *Perception tuning* |
| Ceiling/lights show up as objects | Lower **Max height** (default 2.6 m above the floor) |
| People merge into one box | Lower **Cluster gap**, raise **Min points** to drop noise |
| Nothing detected far away | Raise **Max range**; far objects have few points |
| Boxes flicker | Normal for very sparse objects; confirmed tracks need 3 consecutive hits |
| Speeds look off | Velocities are in the *sensor* frame. Valid in world terms only when the sensor is stationary |

## 6. Record data for later (so you can debug without the sensor)

```bash
ouster-cli source <SENSOR_IP> save run.pcap       # writes run.pcap + run.json (metadata)
make run SENSOR=data/run.pcap                      # replay it through the same pipeline
```

Put `run.pcap` and `run.json` in `./data/` and use `/data/run.pcap` in the container.

## 7. What to send back if it still fails

```bash
ouster-demo doctor <SENSOR_IP> --sdk 2>&1 | tee doctor.txt
docker compose logs --tail=200 > demo.log
```
