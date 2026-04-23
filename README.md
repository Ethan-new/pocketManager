# weather_epaper

Current weather on a Waveshare 2.13" e-Paper HAT (V4), refreshed on a schedule
and powered by a PiSugar (battery + RTC wake) so the Pi can sleep between
updates. Falls back to an in-process sleep loop if no PiSugar is present.

## Hardware

- Raspberry Pi (Zero 2 W or any model with the 40-pin header)
- Waveshare 2.13" e-Paper HAT, V4
- (Optional) PiSugar 2/3 for battery + RTC wake / shutdown cycle

## 1. Pi base setup

Flash Raspberry Pi OS (Lite is fine), boot, and connect to wifi. Then:

```bash
sudo raspi-config nonint do_spi 0          # enable SPI for the e-paper HAT
sudo apt update
sudo apt install -y python3-pip python3-pil python3-numpy git fonts-dejavu
```

The script assumes the user is named `ethan`. If yours differs, change `User=`
and the paths in `weather-epaper.service` and the sudoers file, plus the
`libdir` path at the top of `weather_epaper.py`.

## 2. Waveshare e-Paper library

The script imports `waveshare_epd.epd2in13_V4` from a checkout at
`/home/ethan/e-Paper/RaspberryPi_JetsonNano/python/lib`:

```bash
cd ~
git clone https://github.com/waveshareteam/e-Paper.git
```

## 3. (Optional) PiSugar — battery + scheduled wake

Without PiSugar the script still runs, but it can't read battery % or schedule
deep-sleep wake — it falls back to staying alive and sleeping in-process.

```bash
curl https://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash
```

This installs `pisugar-server`, which the script talks to over
`127.0.0.1:8423`.

## 4. Get the code

```bash
mkdir -p ~/Desktop && cd ~/Desktop
git clone <this-repo-url> pocketManager
cd pocketManager
```

Edit the config block near the top of `weather_epaper.py` for your location:

```python
LAT = 43.6532
LON = -79.3832
LOCATION_NAME = "Toronto"
UNITS = "celsius"           # or "fahrenheit"
WIND_UNITS = "kmh"          # mph, kmh, ms, kn
REFRESH_MINUTE_MARKS = (29, 59)   # wakes at :29 and :59 every hour
```

## 5. Allow passwordless shutdown

The script calls `sudo shutdown -h now` after each refresh so the PiSugar can
power-cycle it. Install the sudoers drop-in:

```bash
sudo install -m 440 sudoers.d/weather-epaper /etc/sudoers.d/weather-epaper
```

## 6. Install the systemd service

```bash
sudo install -m 644 weather-epaper.service /etc/systemd/system/weather-epaper.service
sudo systemctl daemon-reload
sudo systemctl enable weather-epaper.service
```

It's a `oneshot` service: it runs at boot, draws one frame, schedules the next
PiSugar wake, and shuts the Pi down. The PiSugar powers it back on at the next
mark and the cycle repeats.

## Manual usage

```bash
python3 weather_epaper.py                  # full cycle (will shut down at end)
python3 weather_epaper.py --no-shutdown    # render once, stay on
python3 weather_epaper.py --preview        # writes preview.png on a desktop (no HAT needed)
```

If an SSH session is active when the script finishes, it skips the shutdown so
you don't get kicked off mid-debug.

## Troubleshooting

- **No image / SPI errors** — confirm SPI is enabled (`ls /dev/spidev*`) and
  the HAT is fully seated. The script auto-detects "no display" errors and
  stays online instead of shutting down.
- **`battery: ??`** — `pisugar-server` isn't running or isn't reachable on
  `127.0.0.1:8423`. Check `systemctl status pisugar-server`.
- **Pi never wakes back up** — check `journalctl -u weather-epaper` for the
  `pisugar rtc_alarm_set` response. If the PiSugar rejects the alarm the
  script logs an error and falls back to staying online.
- **Logs** — `journalctl -u weather-epaper -e`.
