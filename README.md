# FUSD Central Controller

PC-based central controller for the FUSD (Flexible Unit-Type Screen Door) project.

This controller receives train type and stop-position context, looks up precomputed movement data, builds door control commands, and sends them to the ESP32 Platform Hub using **JSON over Serial**.

## Overview

The central controller is responsible for:

- receiving the detected **train type**
- receiving stop-position context:
  - `case`
  - `stop_error_m`
- loading matching rows from `Movement_Data.csv`
- deciding which door units should move
- building JSON commands
- sending commands to the **ESP32 Platform Hub**
- receiving ACK and periodic status feedback from the Hub

## System Architecture

```text
PC
├─ AI Module (Python)
├─ Central Controller (Python)
└─ Movement_Data.csv
        ↓ JSON over Serial
ESP32 Platform Hub
        ↓ RS-485 / UART
Arduino Mega DCUs
        ↓
Door Units / Sensors
```

## Control Flow
```text
AI detects train type
        ↓
Stop-position sensor determines case / stop error
        ↓
Central Controller looks up Movement_Data.csv
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
├─ central_controller.py
├─ command_builder.py
├─ data_loader.py
├─ transport_serial.py
├─ config.py
├─ requirements.txt
└─ data/
   └─ Movement_Data.csv
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
  "status": "OPENED",
  "last_seq": 0,
  "uptime_ms": 153240,
  "Trainposition": 3,
  "doors_status": [
    {
      "dcu_idx": 4,
      "state": "Open",
      "dir": "Right",
      "dist_step": 3,
      "jammed": false,
      "emergency": false
    }
  ]
}
```

## Data Source
### Runtime
- `data/Movement_Data.csv`

## How to Run
### 1. Install dependencies
`pip install -r requirements.txt`

### 2. Prepare CSV
Place the runtime file here:
`data/Movement_Data.csv`

### 3. Configure serial
Edit `config.py`:
```python
USE_MOCK_SERIAL = True
SERIAL_PORT = "COM4"
BAUDRATE = 115200
```
- USE_MOCK_SERIAL = True → test mode without ESP32
- USE_MOCK_SERIAL = False → real serial communication with ESP32

### 4. Run
`python main.py`

## CLI Example
```text
train GTX-A
case 3
open
close
stop
stop-all
emergency on|off
seq-reset
```