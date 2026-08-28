# Adaptable PSD Central Controller

PC-based central controller for the Adaptable PSD project. The controller
loads the AUSD lookup table, selects the doors for the detected train position,
and communicates with PlatformHUB2 ESP32 using the New JSON protocol.

## Project Structure

```text
central_controller/
├─ main.py
├─ model.py
├─ central_controller.py
├─ command_builder.py
├─ data_loader.py
├─ transport_serial.py
├─ visualization_ws.py
├─ platformhub_simulator.html
├─ config.py
├─ requirements.txt
├─ best.pt
├─ ai_result.json
└─ data/
   └─ AUSD_Lookup_135_final.csv
```

## Lookup Table

Runtime data source:

`data/AUSD_Lookup_135_final.csv`

Required columns:

- `Train Type`
- `Door No.`
- `Case`
- `Stop Error (mm)`
- `Unit ID`
- `Direction`
- `Move Distance (mm)`
- `Valid?`

The loader converts `Stop Error (mm)` and `Move Distance (mm)` to metres for
internal matching and distance-step calculation. `Unit ID` is used directly
as the New JSON `dcu_idx` without renumbering.

## New JSON Communication Flow

The PC uses four request types:

1. Send `status_request` and wait for `status_ack`.
2. Require `train_state: "STOPPED"` and `position_valid: true`.
3. Send `train_context` with the selected door list and wait for
   `selection_ack` with `result: "OK"`.
4. Send `door_control` with `action: "open"`.

The controller does not send a status request or `train_context` automatically
at startup. After the operator sends `status_request` and receives a valid
`status_ack`, the operator sends `select` to transmit `train_context`. The
operator's `open` command is a separate request and only applies to the most
recently approved context.

The ESP32 normally responds with ACK JSON. It can also send
`emergency_status` immediately when emergency state changes.

### PC to ESP32 examples

```json
{"msg_type":"status_request","platform_id":1,"seq":1,"scope":"all"}
```

```json
{
  "msg_type": "train_context",
  "platform_id": 1,
  "seq": 2,
  "train_present": true,
  "case": 4,
  "doors": [
    {"dcu_idx": 0, "dir": "Left", "open_dist_step": 8},
    {"dcu_idx": 1, "dir": "Right", "open_dist_step": 8}
  ]
}
```

```json
{"msg_type":"door_control","platform_id":1,"seq":3,"action":"open"}
```

```json
{"msg_type":"door_control","platform_id":1,"seq":4,"action":"close"}
```

```json
{"msg_type":"door_control","platform_id":1,"seq":5,"action":"stop"}
```

```json
{"msg_type":"emergency_control","platform_id":1,"seq":6,"action":"enter"}
```

```json
{"msg_type":"emergency_control","platform_id":1,"seq":7,"action":"release"}
```

`dcu_idx` follows the New JSON range `0~159`. `seq` starts at `1` and is
monotonically increased for every request.

If an AUSD row has a `dcu_idx` outside `0~159`, the controller ignores that
door and prints a warning before sending the request. If every selected door
is outside the range, the request is rejected because no valid door remains.

The current AUSD CSV contains KTX-1 rows with `Unit ID` values up to `248`.
KTX-1 doors above `dcu_idx=159` are ignored because they cannot be represented
by the current New JSON PlatformHUB range.

## AI Result

`model.py` saves the detected train type to `ai_result.json`.

```json
{
  "train_type": "지하철 대형통근형",
  "frame": 334,
  "elapsed_sec": 27.2,
  "locked": true
}
```

The train names used by the current AUSD table include `GTX-A`, `KTX-1`,
`KTX-산천`, `KTX-청룡`, `KTX-이음`, `누리로`, and `지하철 대형통근형`.

## Configuration

Edit `config.py` for serial settings:

```python
USE_MOCK_SERIAL = True
SERIAL_PORT = "COM4"
BAUDRATE = 115200
```

- `USE_MOCK_SERIAL = True`: run without ESP32 using the New JSON mock
- `USE_MOCK_SERIAL = False`: use the configured serial port
- `USE_VISUALIZATION = True`: publish the central state to the connected HTML
  simulator through WebSocket

## Run

```text
pip install -r requirements.txt
```

Open the following page in a browser after starting the local HTTP server:

`http://127.0.0.1:8000/platformhub_simulator.html`

The HTML simulator is connected-mode only. It does not issue commands and it
does not use its own lookup table. Enter commands in the `main.py` terminal;
the page renders the state snapshots published by the central controller.

The previous `train-2d-simulator-portable-v0.14.html` file is not used by the
controller. Use `platformhub_simulator.html` as the official connected UI.

Run the local HTTP server and the controller in separate terminals:

Terminal 1:

```text
python -m http.server 8000
```

Terminal 2:

```text
python main.py
```

## CLI

```text
help
state
status [active|all]
reload
reset
seq-reset
train GTX-A
case 3
error 0.00
mock-status STOPPED 1 true
select
open
close
stop
depart
emergency on|off
quit
```

After `status active` or `status all` receives a `status_ack` reporting
`train_state: "STOPPED"`, `position_valid: true`, and a `case`, the operator
can send `select`. The controller then sends `train_context` and waits for
`selection_ack: OK`; it does not open the doors at that point. The separate
`open` command sends `door_control/open` using the most recently approved door
list. The controller does not issue an automatic status request after a control
ACK; use `status active` or `status all` when a new status snapshot is needed.
The ESP32 is responsible for idempotent OPEN/CLOSE ACKs and for reversing a
door from CLOSING to OPENING when appropriate.

When using the Mock transport, `mock-status <train_state> <case> <position_valid>`
changes the next `status_ack` response and immediately requests it. For example,
`mock-status DETECTING 4 false` tests the blocked state and
`mock-status STOPPED 4 true` tests the valid state. Use `none` for case when the
ESP32 has not reported a case.
