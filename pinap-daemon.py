#!/usr/bin/env python3

# This script monitors disk activity and controls LEDs
# It reads /sys/block/*/stat to detect I/O activity
# and writes to /sys/class/leds/*/brightness to control LEDs
#
# It also monitors a GPIO switch and controls the USB LED

import time
import sys
import signal
from pathlib import Path
import RPi.GPIO as GPIO

# HDD activity LEDs are dual-colour (red or green sharing the activity pin).
# Select which colour to use: 'red' or 'green'.
#   RED:   power pin LOW,  brightness 1 = on, brightness 0 = off
#   GREEN: power pin HIGH, brightness 0 = on, brightness 1 = off
# HDD_LED_COLOR = 'red'
HDD_LED_COLOR = 'green'

# Mapping of disk devices to LED names
DISK_LED_MAP = {
    'sdb': 'disk1:activity',
    'sdc': 'disk2:activity',
    'sdd': 'disk3:activity',
    'sde': 'disk4:activity',
}

# Green LED power-control GPIO per disk (BCM numbering). 
# These pins must be HIGH (and the activity brightness 0)
# for the green LED to light.
DISK_GREEN_PWR_MAP = {
    'sdb': 1,    # HDD1_PWR
    'sdc': 7,    # HDD2_PWR
    'sdd': 8,    # HDD3_PWR
    'sde': 25,   # HDD4_PWR
}

# Poll interval in seconds (0.1 = 100ms)
POLL_INTERVAL = 0.1

# LED flash duration in seconds
FLASH_DURATION = 0.05

# GPIO pin for the switch
SWITCH_GPIO_PIN = 24

# Path to the USB LED brightness control
USB_LED_BRIGHTNESS = Path('/sys/class/leds/usb:activity/brightness')

# ---------------------------------------------------------------------------
# Temperature sensor configuration (1-wire DS18B20 on GPIO 14)
# ---------------------------------------------------------------------------
# 1-wire device ID for the temperature sensor
# ## UPDATE FOR YOUR SENSOR ID ##
TEMP_SENSOR_ID = '28-000000000000'
# Path to the sensor's temperature attribute (value is in milli-degrees C)
TEMP_SENSOR_PATH = Path(f'/sys/bus/w1/devices/{TEMP_SENSOR_ID}/temperature')

# ---------------------------------------------------------------------------
# Beeper / amplifier configuration
# ---------------------------------------------------------------------------
# PWM square wave output pin for the beeper (BCM numbering)
BEEPER_PWM_GPIO = 13
# Two GPIOs that, when driven high, set the amplifier volume to maximum
VOLUME_GPIO_A = 5
VOLUME_GPIO_B = 6
# Tone frequency in Hz (Middle C / C4 ~= 261.63 Hz)
TONE_FREQUENCY_HZ = 261.63
# How long to sound the tone for, in seconds, when the switch is pressed
TONE_DURATION_SECONDS = 0.3
# Tone played once when the daemon starts and once when it shuts down
STARTUP_SHUTDOWN_TONE_HZ = 800
STARTUP_SHUTDOWN_TONE_SECONDS = 2.0

# ---------------------------------------------------------------------------
# Fan (4-wire 12V PC fan) PWM configuration
# ---------------------------------------------------------------------------
# The fan is driven by the kernel HARDWARE PWM, enabled via:
#     dtoverlay=pwm,pin=12,func=4
# in /boot/firmware/config.txt. GPIO 12 is therefore controlled through
# /sys/class/pwm and NOT through RPi.GPIO.
#
# Channel exported under the pwmchip (the simple 'pwm' overlay exposes one channel, 0).
FAN_PWM_CHANNEL = 0
# pwmchip number under /sys/class/pwm. Set to an int to force a specific chip,
# or leave as None to auto-detect (handy because the RP1 chip number on the
# Pi 5 is not stable across kernels).
FAN_PWMCHIP = None
# Intel 4-wire fan spec recommends ~25 kHz; hardware PWM can generate this.
FAN_PWM_FREQUENCY_HZ = 25000
# Invert the PWM duty cycle. Set True as the fan is driven through an
# inverting buffer/driver (e.g. a Darlington), so a requested 20% becomes an
# 80% electrical duty that the driver inverts back to 20% at the fan.
INVERT_FAN_PWM = True
# Temperature/duty mapping. At/below TEMP_LOW the fan runs at FAN_MIN_DUTY,
# at/above TEMP_HIGH it runs at FAN_MAX_DUTY, linear in between.
TEMP_LOW_C = 20.0
TEMP_HIGH_C = 40.0
FAN_MIN_DUTY = 0     # percent (PWM fans cannot be reliably controlled below about 20%)
FAN_MAX_DUTY = 100   # percent
# How often (seconds) to read the temperature and adjust the fan speed
FAN_UPDATE_INTERVAL = 10.0

class HardwarePWM:
    SYSFS_ROOT = Path('/sys/class/pwm')

    def __init__(self, channel, frequency_hz, chip=None):
        self.channel = channel
        self.chip_path = self._resolve_chip(chip, channel)
        self.path = self.chip_path / f'pwm{channel}'
        self.period_ns = int(round(1_000_000_000 / frequency_hz))

        # Export the channel if it isn't already
        if not self.path.exists():
            (self.chip_path / 'export').write_text(str(channel))
            # Give udev a moment to create the attribute files
            for _ in range(50):
                if self.path.exists():
                    break
                time.sleep(0.02)

        # Always start from a known, safe state. Order matters: duty must be
        # <= period at all times, so zero it before changing period.
        self._write('duty_cycle', 0)
        self._write('period', self.period_ns)
        self._write('enable', 1)

    @classmethod
    def _resolve_chip(cls, chip, channel):
        if chip is not None:
            path = cls.SYSFS_ROOT / f'pwmchip{chip}'
            if not path.exists():
                raise FileNotFoundError(f'{path} does not exist')
            return path
        # Auto-detect: pick the first pwmchip that exposes the channel.
        for path in sorted(cls.SYSFS_ROOT.glob('pwmchip*')):
            try:
                npwm = int((path / 'npwm').read_text().strip())
            except (IOError, ValueError):
                continue
            if channel < npwm:
                print(f'Using {path} for hardware PWM', file=sys.stderr)
                return path
        raise FileNotFoundError(
            'No usable pwmchip found under /sys/class/pwm '
            '(is dtoverlay=pwm,pin=12,func=4 set and the Pi rebooted?)')

    def _write(self, attr, value):
        (self.path / attr).write_text(str(value))

    def set_duty_fraction(self, fraction):
        """Set duty cycle as a fraction in [0.0, 1.0]."""
        fraction = max(0.0, min(1.0, fraction))
        self._write('duty_cycle', int(self.period_ns * fraction))

    def stop(self):
        try:
            self._write('duty_cycle', 0)
            self._write('enable', 0)
        except IOError:
            pass


class DiskLEDMonitor:
    def __init__(self):
        self.last_stats = {}
        self.led_paths = {}
        self.disk_paths = {}
        
        # Initialize paths
        for disk, led_name in DISK_LED_MAP.items():
            disk_stat = Path(f'/sys/block/{disk}/stat')
            led_brightness = Path(f'/sys/class/leds/{led_name}/brightness')
            
            if not disk_stat.exists():
                print(f"Warning: {disk} not found, skipping", file=sys.stderr)
                continue
                
            if not led_brightness.exists():
                print(f"Warning: LED {led_name} not found, skipping", file=sys.stderr)
                continue
            
            self.disk_paths[disk] = disk_stat
            self.led_paths[disk] = led_brightness
            self.last_stats[disk] = self._read_disk_stats(disk)
            
        if not self.disk_paths:
            print("Error: No valid disk/LED pairs found", file=sys.stderr)
            sys.exit(1)
        
        # Initialize GPIO for switch
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(SWITCH_GPIO_PIN, GPIO.IN)  # No pull_up_down argument

        # Track switch state so we only beep on the press (falling) edge
        self.prev_switch_state = GPIO.input(SWITCH_GPIO_PIN)

        # Configure HDD LED colour.
        #   RED mode:   power pins stay LOW; disk activity toggles brightness.
        #   GREEN mode: brightness stays 0; disk activity toggles the power pin
        #               (HIGH = green on, LOW = off).
        self.led_color = HDD_LED_COLOR

        # Set up the green power-control pins as outputs, off (LOW) by default.
        self.green_pwr_pins = {}
        for disk in self.disk_paths.keys():
            pin = DISK_GREEN_PWR_MAP.get(disk)
            if pin is None:
                continue
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            self.green_pwr_pins[disk] = pin

        # Initialise every LED to off. In green mode the brightness is fixed at
        # 0 for the whole run; in red mode 0 is simply the off state.
        for disk in self.disk_paths.keys():
            self._write_brightness(disk, 0)
            self._set_led(disk, 0)
        print(f"HDD LEDs using {self.led_color} colour", file=sys.stderr)

        # Check if USB LED exists
        self.usb_led_available = USB_LED_BRIGHTNESS.exists()
        if not self.usb_led_available:
            print("Warning: USB LED not found, switch monitoring disabled", file=sys.stderr)

        # Initialize beeper (PWM) and amplifier volume pins
        GPIO.setup(BEEPER_PWM_GPIO, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(VOLUME_GPIO_A, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(VOLUME_GPIO_B, GPIO.OUT, initial=GPIO.LOW)
        self.beeper_pwm = GPIO.PWM(BEEPER_PWM_GPIO, TONE_FREQUENCY_HZ)

        # Initialize fan via the kernel HARDWARE PWM (/sys/class/pwm). The pin
        # is owned by the 'pwm' overlay, so RPi.GPIO must not touch it.
        try:
            self.fan_pwm = HardwarePWM(FAN_PWM_CHANNEL, FAN_PWM_FREQUENCY_HZ,
                                       chip=FAN_PWMCHIP)
            print(f"Fan hardware PWM at {FAN_PWM_FREQUENCY_HZ} Hz "
                  f"(invert={INVERT_FAN_PWM})", file=sys.stderr)
        except (FileNotFoundError, IOError) as e:
            print(f"Warning: hardware PWM unavailable ({e}); fan control disabled",
                  file=sys.stderr)
            self.fan_pwm = None
        # Apply an initial safe duty
        self._apply_fan_duty(FAN_MIN_DUTY)

        # Check the temperature sensor is present
        self.temp_sensor_available = TEMP_SENSOR_PATH.exists()
        if not self.temp_sensor_available:
            print(f"Warning: temperature sensor {TEMP_SENSOR_PATH} not found, "
                  f"fan will stay at {FAN_MIN_DUTY}%", file=sys.stderr)
        self.last_fan_update = 0.0
    
    def _read_disk_stats(self, disk):
        """Read disk I/O stats. Returns (reads, writes) tuple."""
        try:
            stats = self.disk_paths[disk].read_text().split()
            # stats[0] = reads completed, stats[4] = writes completed
            return (int(stats[0]), int(stats[4]))
        except (IOError, IndexError, ValueError):
            return (0, 0)
    
    def _write_brightness(self, disk, value):
        """Write a raw value to the disk activity brightness file."""
        try:
            self.led_paths[disk].write_text(str(value))
        except IOError as e:
            print(f"Error setting LED brightness for {disk}: {e}", file=sys.stderr)

    def _set_led(self, disk, state):
        """Set LED state: 1=on (activity), 0=off.

        RED mode:   toggle the activity brightness (power pin stays low).
        GREEN mode: toggle the power pin (brightness stays 0)."""
        if self.led_color == 'green':
            pin = self.green_pwr_pins.get(disk)
            if pin is not None:
                GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
        else:  # red
            self._write_brightness(disk, 1 if state else 0)
    
    def _set_usb_led(self, state):
        """Set USB LED state: 1=on, 0=off"""
        if not self.usb_led_available:
            return
        try:
            USB_LED_BRIGHTNESS.write_text(str(state))
        except IOError as e:
            print(f"Error setting USB LED: {e}", file=sys.stderr)

    def _read_temperature(self):
        """Read the 1-wire sensor temperature in degrees C, or None on failure."""
        if not self.temp_sensor_available:
            return None
        try:
            milli = int(TEMP_SENSOR_PATH.read_text().strip())
            return milli / 1000.0
        except (IOError, ValueError) as e:
            print(f"Error reading temperature: {e}", file=sys.stderr)
            return None

    def _temperature_to_duty(self, temp_c):
        """Map a temperature to a fan duty cycle (linear between low and high)."""
        if temp_c <= TEMP_LOW_C:
            return FAN_MIN_DUTY
        if temp_c >= TEMP_HIGH_C:
            return FAN_MAX_DUTY
        fraction = (temp_c - TEMP_LOW_C) / (TEMP_HIGH_C - TEMP_LOW_C)
        return FAN_MIN_DUTY + fraction * (FAN_MAX_DUTY - FAN_MIN_DUTY)

    def _apply_fan_duty(self, duty_percent):
        """Write a fan duty (percent), applying inversion for the driver."""
        if self.fan_pwm is None:
            return
        fraction = max(0.0, min(1.0, duty_percent / 100.0))
        if INVERT_FAN_PWM:
            fraction = 1.0 - fraction
        try:
            self.fan_pwm.set_duty_fraction(fraction)
        except IOError as e:
            print(f"Error setting fan duty: {e}", file=sys.stderr)

    def update_fan(self):
        """Read the temperature and adjust the fan speed accordingly."""
        temp_c = self._read_temperature()
        if temp_c is None:
            # No reading: keep the fan at its minimum safe speed
            self._apply_fan_duty(FAN_MIN_DUTY)
            return
        duty = self._temperature_to_duty(temp_c)
        self._apply_fan_duty(duty)
        #print(f"Temp {temp_c:.2f} C -> fan {duty:.0f}%", file=sys.stderr)

    def play_tone(self, frequency_hz=TONE_FREQUENCY_HZ,
                  duration_seconds=TONE_DURATION_SECONDS):
        """Sound the beeper at the given frequency for the given duration."""
        # Set amplifier volume to maximum
        GPIO.output(VOLUME_GPIO_A, GPIO.HIGH)
        GPIO.output(VOLUME_GPIO_B, GPIO.HIGH)
        try:
            self.beeper_pwm.ChangeFrequency(frequency_hz)
            self.beeper_pwm.start(50)  # 50% duty -> square wave
            time.sleep(duration_seconds)
            self.beeper_pwm.stop()
        finally:
            GPIO.output(BEEPER_PWM_GPIO, GPIO.LOW)
            GPIO.output(VOLUME_GPIO_A, GPIO.LOW)
            GPIO.output(VOLUME_GPIO_B, GPIO.LOW)

    def check_activity(self, disk):
        """Check if disk has activity since last check."""
        current = self._read_disk_stats(disk)
        last = self.last_stats[disk]
        
        # Check if reads or writes have changed
        has_activity = (current[0] != last[0]) or (current[1] != last[1])
        
        self.last_stats[disk] = current
        return has_activity
    
    def check_switch_and_set_usb_led(self):
        """Monitor GPIO switch, set USB LED, and beep on press."""
        switch_state = GPIO.input(SWITCH_GPIO_PIN)

        # LED ON when switch LOW (pressed), OFF when HIGH (released)
        self._set_usb_led(1 if not switch_state else 0)

        # Falling edge (released HIGH -> pressed LOW) means a fresh press: beep
        if switch_state == 0 and self.prev_switch_state == 1:
            self.play_tone()

        self.prev_switch_state = switch_state

    def _handle_sigterm(self, signum, frame):
        """Raise KeyboardInterrupt on SIGTERM so the shutdown path runs."""
        raise KeyboardInterrupt

    def run(self):
        """Main monitoring loop."""
        print("Disk LED daemon started", file=sys.stderr)
        print(f"Monitoring: {', '.join(self.disk_paths.keys())}", file=sys.stderr)

        # Treat SIGTERM (e.g. from systemd on shutdown) like Ctrl-C so the
        # shutdown tone and cleanup run.
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        # Sound the startup tone (e.g. when the Pi boots)
        self.play_tone(STARTUP_SHUTDOWN_TONE_HZ, STARTUP_SHUTDOWN_TONE_SECONDS)

        # Do an initial fan adjustment so the speed reflects the current temp
        self.update_fan()
        self.last_fan_update = time.monotonic()

        try:
            while True:
                for disk in self.disk_paths.keys():
                    if self.check_activity(disk):
                        self._set_led(disk, 1)
                
                # Monitor switch and set USB LED (and beep on press)
                self.check_switch_and_set_usb_led()

                # Periodically adjust the fan based on temperature
                now = time.monotonic()
                if now - self.last_fan_update >= FAN_UPDATE_INTERVAL:
                    self.update_fan()
                    self.last_fan_update = now

                # Keep LEDs on for FLASH_DURATION
                time.sleep(FLASH_DURATION)
                
                # Turn all LEDs off
                for disk in self.disk_paths.keys():
                    self._set_led(disk, 0)
                
                # Wait for next poll
                time.sleep(POLL_INTERVAL - FLASH_DURATION)
                
        except KeyboardInterrupt:
            print("\nShutting down...", file=sys.stderr)
            # Turn off all LEDs
            for disk in self.disk_paths.keys():
                self._set_led(disk, 0)
            # Turn off USB LED
            self._set_usb_led(0)
            # Sound the shutdown tone (e.g. when the Pi powers down)
            try:
                self.play_tone(STARTUP_SHUTDOWN_TONE_HZ,
                               STARTUP_SHUTDOWN_TONE_SECONDS)
            except Exception:
                pass
            # Stop PWM outputs
            try:
                self.fan_pwm.stop()
            except Exception:
                pass
            try:
                self.beeper_pwm.stop()
            except Exception:
                pass
            GPIO.cleanup()

if __name__ == '__main__':
    monitor = DiskLEDMonitor()
    monitor.run()
