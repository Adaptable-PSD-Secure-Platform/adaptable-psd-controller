# Adaptable PSD Central Controller

PC-based central controller for the Adaptable PSD (Adaptable Platform Screen Door) project.

This controller receives train type and stop-position context, looks up precomputed movement data, builds door control commands, and sends them to the ESP32 Platform Hub using **JSON over Serial**.

## Overview

The central controller is responsible for:

- receiving the detected **train type** from the AI module
- receiving stop-position context from the Hub/DCU status JSON:
  - `case`
  - `stop_error_m`
- allowing manual fallback input when automatic input is unavailable
- loading matching rows from `AUSD_Lookup_135_final.csv`
- deciding which door units should move
- building JSON commands
- sending commands to the **ESP32 Platform Hub**
- receiving ACK and periodic status feedback from the Hub

## System Architecture

```text
PC
├─ AI Module (Python, YOLO)
├─ Central Controller (Python)
├─ ai_result.json
└─ AUSD_Lookup_135_final.csv
        ↓ JSON over Serial
ESP32 Platform Hub
        ↓ RS-485 / UART
Arduino Mega DCUs
        ↓
Door Units / Sensors
```

## Control Flow
```text
YOLO model detects train type
        ↓
model.py saves ai_result.json
        ↓
main.py loads train_type automatically
        ↓
Hub/DCU sends case by status_report JSON
        ↓
Central Controller updates case automatically
        ↓
AUSD_Lookup_135_final.csv is queried
        ↓
Door movement commands are generated
        ↓
JSON command is sent to ESP32 Platform Hub
        ↓
ESP32 returns ACK / periodic status report
```

## Project Structure
```text
central_controller/
├─ main.py
├─ model.py
├─ central_controller.py
├─ command_builder.py
├─ data_loader.py
├─ transport_serial.py
├─ config.py
├─ requirements.txt
├─ best.pt
├─ ai_result.json
└─ data/
   └─ AUSD_Lookup_135_final.csv
```

## Communication
The PC and ESP32 communicate using:
- USB Serial
- JSON line protocol
- UTF-8 encoding
- one JSON object per line
- 115200 bps

## PC → Hub Command JSON Example
```json
{
  "platform_id": 1,
  "seq": 0,
  "doors": [
    {
      "dcu_idx": 4,
      "cmd": "Open",
      "dir": "Right",
      "dist_step": 3
    }
  ]
}
```

## Hub → PC ACK JSON Example
```json
{
  "msg_type": "ack",
  "platform_id": 1,
  "result": "OK",
  "last_seq": 0,
  "status": "OPENING"
}
```

## Hub → PC Periodic Status JSON Example
```json
{
  "msg_type": "status_report",
  "platform_id": 1,
  "case": 3
}
```

## AI Result File Example
model.py saves the final train-type decision to ai_result.json.
```json
{
  "train_type": "지하철 대형통근형",
  "frame": 334,
  "elapsed_sec": 27.2,
  "locked": true
}
```

## Data Source
### Runtime
- `data/AUSD_Lookup_135_final.csv`

## How to Run
### 1. Install dependencies
`pip install -r requirements.txt`

### 2. Prepare CSV
Place `AUSD_Lookup_135_final.csv` in the `data` folder.

The AUSD format stores `Stop Error (mm)` and `Move Distance (mm)` in
millimetres and identifies one door unit with `Unit ID`. The loader converts
these values into the metre-based runtime format.

### 3. Configure serial
Edit `config.py`:
```python
USE_MOCK_SERIAL = True
SERIAL_PORT = "COM4"
BAUDRATE = 115200
```
- USE_MOCK_SERIAL = True → test mode without ESP32
- USE_MOCK_SERIAL = False → real serial communication with ESP32

### 4. Run AI detection
`python model.py`

### 5. Run central controller
`python main.py`

## CLI Example
```text
train GTX-A
case 3
error 0.00
open
close
stop
stop-all
emergency on
reset
seq-reset
```
