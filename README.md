# PiNAP - The Raspberry Pi 5 Conversion Kit for QNAP NAS
This repository contains the scripts required to support the Raspberry Pi 5 conversion of a QNAP NAS using the PiNAP board v1.3.

# Table of Contents
- [Hardware Requirements](#hardware-requirements)
- [Raspberry Pi OS Installation](#raspberry-pi-os-installation)
- [Open Media Vault Installation](#open-media-vault-installation)
- [PiNAP Software Installation](#pinap-software-installation)
- [Testing](#testing)
- [Configurable Options](#configurable-options)

# Introduction
This has currently only been tested on the QNAP TS-410 model, but it should work with other QNAPs of the same family, with the same motherboard, but with different number of drive bays. As people report success, I will update a "supported hardware" list.

These instructions assume you have a working knowledge of the Raspberry Pi OS and Open Media Vault. For more detailed instructions on using those, please refer to the Internet.

# Hardware Requirements
To convert your QNAP to Raspberry Pi and Open Media Vault you will need the following hardware:
- Raspberry Pi 5 - I am using the version with 8GB RAM, with the Raspberry Pi Active cooler
- PCIe Slot for Raspberry Pi 5 (P02) 
    - https://thepihut.com/products/pcie-slot-for-raspberry-pi-5-p02
    - Some PCIe slots don't work, so be careful to get this specific model, which I can confirm works with the SATA backplane.
- PCIe extension cable (30cm)
    - https://www.amazon.co.uk/dp/B0FJ58388R
    - Not all cables work correctly. This one specifically has the right angles in the correct orientation, however you will need to sand off 5 mm of the edge of the PCB to get it to fit. This doesn't affect its functionality as long as the modification is clean.
- The PiNAP conversion kit (available from Tindie - https://www.tindie.com/). The kit includes;
    - the fully populated conversion PCB with 5v buck convertor.
    - the power socket and 2mm bolts
    - nylon PCB standoffs
    - M3 bolts
    - 40 pin ribbon cable
    - 2 way power button cable
- You will reuse your QNAP case, power supply and internal cables.
- Hard disks.
- You will also need a Dremel to cut out a hole in the back of the case and drill and 2mm drill bit to mount the power socket.
- A soldering iron and steady hand to solder two tiny wires on the SATA backplane to enable the power on SATA3 and SATA4. These instructions assume you have already done this to modify your SATA backplane.

A more detailed explanation, instructions and pictures of the various modifications can be found in my blog: https://blog.mostlyrobots.net/

# Raspberry Pi OS Installation
Create a USB flash disk with the latest Raspberry Pi OS 64 bit **Lite image** using the Raspberry Pi Imager software. **Open Media Vault only works on the Lite version of the OS.**

The Raspberry Pi 5 will not initially boot when installed in the PiNAP board because it cannot measure the power supply and refuses to boot from USB. You need to make a change to the `/boot/firmware/config.txt`. There are two options to achieve this:

## Option 1 - Boot the Pi5 initially with USB-C Power
Before installing the Pi5 in the PiNAP board you can boot the Pi5 independently, install the Raspberry Pi OS and make some changes to the `/boot/firmware/config.txt`. Boot the Pi 5 from the USB flash disk with a compatible 5v USB-C supply and once it has booted, edit the `/boot/firmware/config.txt` file. Add the following lines to the end of the file:

    usb_max_current_enable=1
    dtparam=pciex1
    dtoverlay=pwm,pin=12,func=4
    dtoverlay=w1-gpio,gpiopin=14

Save and shutdown.

You can now install the Pi5 in the PiNAP convertor PCB and connect all the connectors in the case and continue the installation process.

Connect the Pi 5 to the network and ensure everything is up to date:

    sudo apt update
    sudo apt upgrade

Reboot the Pi 5

## Option 2 - Edit the config.txt file on the USB flash disk before booting
When you have created the USB flash disk with the latest Raspberry Pi OS 64 bit **Lite image** using the Raspberry Pi Imager software, insert the flash disk into a suitable laptop or computer. In the "bootfs" partition you should find the file /config.txt. Add the following lines to the end of the file:

    usb_max_current_enable=1
    dtparam=pciex1
    dtoverlay=pwm,pin=12,func=4
    dtoverlay=w1-gpio,gpiopin=14

Save the file and eject the USB flash drive.

You can now install the Pi5 in the PiNAP convertor PCB and connect all the connectors in the case and continue the installation process.

Connect the Pi 5 to the network and ensure everything is up to date:

    sudo apt update
    sudo apt upgrade

Reboot the Pi 5

## Verify PCIe SATA Backplane is recognised
    $ lspci
        0001:00:00.0 PCI bridge: Broadcom Inc. and subsidiaries BCM2712 PCIe Bridge (rev 21)
    --> 0001:01:00.0 SCSI storage controller: Marvell Technology Group Ltd. 88SX7042 PCIe 4-port SATA-II controller (rev 02)
        0002:00:00.0 PCI bridge: Broadcom Inc. and subsidiaries BCM2712 PCIe Bridge (rev 21)
        0002:01:00.0 Ethernet controller: Raspberry Pi Ltd RP1 PCIe 2.0 South Bridge

# Open Media Vault Installation
I installed Open Media Vault (OMV) first and get that running, then install the Device Tree Overlay and daemon. OMV configured the ethernet port as "end0" not the default "eth0" so the device tree needs to reflect that.

The Open Media Vault install was very straight forward. The instructions are easy to follow. Follow the instructions for Raspberry Pi: https://github.com/OpenMediaVault-Plugin-Developers/installScript

    wget -O - https://github.com/OpenMediaVault-Plugin-Developers/installScript/raw/master/install | sudo bash

This should install Open Media Vault, you can then access the web interface using a browser.

Ensure everything is up to date:

    sudo apt update
    sudo apt upgrade
	
You can now setup Open Media Vault, install the various plugins you need, configure the disks and RAID Arrays and create a filing system and shares.

	$ lsblk
	NAME   MAJ:MIN RM  SIZE RO TYPE  MOUNTPOINTS
	sda      8:0    1 28.7G  0 disk
	├─sda1   8:1    1  512M  0 part  /boot/firmware
	└─sda2   8:2    1 28.2G  0 part  /
	sdb      8:16   0  2.7T  0 disk
	└─md0    9:0    0  8.2T  0 raid5 /export/data
                                     /srv/dev-disk-by-uuid-abcdef12-39fd-456a-abcd-123456789123
	sdc      8:32   0  2.7T  0 disk
	└─md0    9:0    0  8.2T  0 raid5 /export/data
                                     /srv/dev-disk-by-uuid-abcdef12-39fd-456a-abcd-123456789123
	sdd      8:48   0  2.7T  0 disk
	└─md0    9:0    0  8.2T  0 raid5 /export/data
                                     /srv/dev-disk-by-uuid-abcdef12-39fd-456a-abcd-123456789123
	sde      8:64   0  2.7T  0 disk
	└─md0    9:0    0  8.2T  0 raid5 /export/data
                                     /srv/dev-disk-by-uuid-abcdef12-39fd-456a-abcd-123456789123

Reboot the Pi 5

# PiNAP Software Installation
    cd ~
    git clone https://github.com/JonRussell00/PiNAP.git
    cd PiNAP
    sudo cp pinap-leds.dts /boot/firmware/overlays/pinap-leds.dts
    sudo cp pinap-daemon.py /usr/local/bin/pinap-daemon.py
    sudo cp pinap-daemon.service /etc/systemd/system/pinap-daemon.service
    sudo cp pinap-lan-led-trigger.service /etc/systemd/system/pinap-lan-led-trigger.service
    sudo chmod +x /usr/local/bin/pinap-daemon.py

# Configure OneWire for the Temperature Sensor

    lsmod | grep w1

You should see w1_gpio and w1_therm listed. If not, load them:

    sudo modprobe w1_gpio
    sudo modprobe w1_therm

Reboot the Pi 5

You should now be able to see the onboard OneWire temperature sensor:

    $ sudo ls -la /sys/bus/w1/devices/
    lrwxrwxrwx 1 root root 0 Jun 18 01:39 28-00000xxxxxxx -> ../../../devices/w1_bus_master1/28-00000xxxxxxx
    lrwxrwxrwx 1 root root 0 Jun 18 17:12 w1_bus_master1 -> ../../../devices/w1_bus_master1

Make a note of the number of your temperature sensors unique number starting "28-" 

Test the sensor reads the correct temperature substituting your unique ID in the following command:

    $ sudo cat /sys/bus/w1/devices/28-000000000000/temperature | awk '{printf "%.2f\n", $1/1000}'
    28.75

Edit the daemon Python file /usr/local/bin/pinap-daemon.py and add your unique ID. Edit the TEMP_SENSOR_ID variable here:

    # ---------------------------------------------------------------------------
    # Temperature sensor configuration (1-wire DS18B20 on GPIO 14)
    # ---------------------------------------------------------------------------
    # 1-wire device ID for the temperature sensor
    # ## UPDATE FOR YOUR SENSOR ID ##
    TEMP_SENSOR_ID = '28-000000000000'
    # Path to the sensor's temperature attribute (value is in milli-degrees C)
    TEMP_SENSOR_PATH = Path(f'/sys/bus/w1/devices/{TEMP_SENSOR_ID}/temperature')

# Device Tree Overlay
Build the device tree overlay:

    sudo dtc -@ -I dts -O dtb -o /boot/firmware/overlays/pinap-leds.dtbo /boot/firmware/overlays/pinap-leds.dts

Edit the `/boot/firmware/config.txt` file. Add the following lines to the end of the file:

    dtoverlay=pinap-leds

Enable the netdev LED trigger

    sudo modprobe ledtrig-netdev
    echo "ledtrig-netdev" | sudo tee -a /etc/modules

Double check your ethernet port is labelled "end0".

    $ ip link show
    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    2: end0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT group default qlen 1000
        link/ether d8:3a:dd:ff:ff:ff brd ff:ff:ff:ff:ff:ff
        altname enxd83addffffff

if its still "eth0" you will need to change it to "end0" with:

    sudo omv-firstaid

The LAN LED Trigger service assumes "end0"

# Enable the Python Daemon

    sudo systemctl daemon-reload
    sudo systemctl enable pinap-daemon.service
    sudo systemctl start pinap-daemon.service

# Enable LAN LED Trigger Service

    sudo systemctl daemon-reload
    sudo systemctl enable pinap-lan-led-trigger.service
    sudo systemctl start pinap-lan-led-trigger.service

# Testing

At the end of the install process you should have the following lines at the end of your `/boot/firmware/config.txt` 

    usb_max_current_enable=1
    dtparam=pciex1
    dtoverlay=pinap-leds
    dtoverlay=w1-gpio,gpiopin=14
    dtoverlay=pwm,pin=12,func=4

Reboot the Pi 5
All the features should now be functional:
- The Green Status LED on the front panel should make a heartbeat flashing pattern
- The Amber LAN LED should flash in time with network activity
- The four Green HDD LEDs should flash in time with disk activity
- When you shutdown or startup the PiNAP should beep, in a similar fashion to the QNAP functionality.
- If you press the USB button on the front panel, the Blue USB LED should light and the PiNAP should beep. I currently don't use the USB button, USB LED or eSATA LED for anything. They are there for future expansion and compatibility. There's no reason why you can trigger a script when the USB button is pressed to copy files from the USB to the RAID Array if you need that functionality.


# ⚠️ Important Safety Notes
- Always disconnect power before working with hardware
- The SATA backplane modification requires precision soldering
- Test all connections before closing the case

# Troubleshooting
## Common Issues
- **Pi won't boot from PiNAP power**: Ensure `usb_max_current_enable=1` is set in config.txt
- **LAN LED not working**: Verify ethernet interface is named "end0" using `ip link show`
- **Temperature sensor not detected**: Check w1_gpio and w1_therm modules are loaded

# Configurable options

## Red or Green HDD LEDs
You can change the HDD activity LEDs to use the Red LEDs by editing the Python file `/usr/local/bin/pinap-daemon.py` and changing HDD_LED_COLOR from "green" to "red":

    # HDD activity LEDs are dual-colour (red or green sharing the activity pin).
    # Select which colour to use: 'red' or 'green'.
    #   RED:   power pin LOW,  brightness 1 = on, brightness 0 = off
    #   GREEN: power pin HIGH, brightness 0 = on, brightness 1 = off
    # HDD_LED_COLOR = 'red'
    HDD_LED_COLOR = 'green'
