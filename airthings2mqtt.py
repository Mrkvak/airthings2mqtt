#!/usr/bin/env python3
from paho.mqtt import client as mqtt
from bluepy.btle import UUID, Peripheral, Scanner, DefaultDelegate
import time
import struct
import threading
import sys
from datetime import datetime

# Config variables
mqtt_interval = 10
mqtt_broker = '127.0.0.1'
mqtt_port = 1883
mqtt_topic = 'airthings/bedroom'
mqtt_client_id = 'waveplus-bedroom'
mqtt_username = 'waveplus'
mqtt_password = 'DJl7tLrQEmjWz0guniRM8lHCO1eDzSM1' # yeah, I know having passwords in repository is a bad practice
mqtt_retry = 30

airthings_sn = 2930165166
report_interval = 30
airthings_mac = None
print_stdout = True

airthings_uuid = UUID("b42e2a68-ade7-11e4-89d3-123b93f75cba")

# Parts of this code were taken from https://github.com/Airthings/waveplus-reader, Copyright (C) 2018 Airthings


# Global variables
mqtt_connected = False
mqtt_client = None
mqtt_lock = threading.Lock()
mqtt_connecting = False
mqtt_last_connect = None

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.stderr.flush()

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    eprint("Connected to mqtt broker with return code: "+str(rc))
    if rc == 0:
        mqtt_connected = True
    else:
        mqtt_connected = False

def on_disconnect(client, userdata, rc):
    eprint("Disconnected with return code: "+str(rc))
    mqtt_connected = False

def mqtt_connect():
    global mqtt_last_connect
    global mqtt_client
    mqtt_lock.acquire()
    if mqtt_last_connect is not None and (datetime.now() - mqtt_last_connect).total_seconds() > mqtt_retry:
        mqtt_lock.release()
        return

    mqtt_last_connect = datetime.now()

    mqtt_client = mqtt.Client(mqtt_client_id)
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    eprint("Connecting to mqtt broker: "+mqtt_broker+":"+str(mqtt_port))
    mqtt_client.loop_start()
    mqtt_client.enable_logger()
    mqtt_client.connect(mqtt_broker, mqtt_port)
    mqtt_lock.release()

def send_mqtt(topic, value):
    global mqtt_connected
    global mqtt_client
    if not mqtt_connected:
        if mqtt_interval is not None:
            mqtt_connect()
        return
    mqtt_client.publish(mqtt_topic+"/"+topic, value)


def get_sn_from_ad255(reply):
    if reply == None:
        return None

    reply_bin = bytearray.fromhex(reply)

    if (((reply_bin[1] << 8) | reply_bin[0]) == 0x0334):
        sn = reply_bin[2]
        sn |= (reply_bin[3] << 8)
        sn |= (reply_bin[4] << 16)
        sn |= (reply_bin[5] << 24)
        return sn
    else:
        return None

def find_mac(serial):
    eprint("Looking for device with serial number "+str(serial))

    scanner = Scanner().withDelegate(DefaultDelegate())
    i = 0
    while i < 100:
        devices = scanner.scan(0.1)
        for dev in devices:
            if get_sn_from_ad255(dev.getValueText(255)) == serial:
                eprint("MAC of our device is: "+dev.addr)
                return dev.addr

    eprint("Could not find our device.")
    return None


class WavePlusReply():
    def __init__(self, response):
        self.version = response[0]
        self.humidity = response[1]/2.0
        self.radon_st = response[4]
        self.radon_lt = response[5]
        self.temperature = response[6] / 100.0
        self.pressure = response[7] / 50.0
        self.co2_ppm = response[8]* 1.0
        self.voc_ppb = response[9] * 1.0


def read_data():
    global airthings_mac
    if airthings_mac is None:
        airthings_mac = find_mac(airthings_sn)
    if airthings_mac is None:
        eprint("We couldn't find our device and MAC is not configured")
        return
    peripheral = Peripheral(airthings_mac)
    try: 
        response = peripheral.getCharacteristics(uuid=airthings_uuid)[0]
        if response is None:
            eprint("Reading data from Airthings device has failed.")
            return
        data = struct.unpack('<BBBBHHHHHHHH', response.read())
        return WavePlusReply(data)
    finally:
        peripheral.disconnect()


def main_loop():
    data = read_data()
    if print_stdout:
        print(data.version, end=",")
        print(data.humidity, end=",")
        print(data.radon_st, end=",")
        print(data.radon_lt, end=",")
        print(data.temperature, end=",")
        print(data.pressure, end=",")
        print(data.co2_ppm, end=",")
        print(data.voc_ppb)
    if not mqtt_connected:
        eprint("Waiting for MQTT connection...")
        mqtt_connect()
        return

    send_mqtt("temperature", data.temperature)
    send_mqtt("pressure", data.pressure)
    send_mqtt("humidity", data.humidity)
    send_mqtt("co2_ppm", data.co2_ppm)
    send_mqtt("voc_ppb", data.voc_ppb)
    send_mqtt("radon_st", data.radon_st)
    send_mqtt("radon_lt", data.radon_lt)

mqtt_connect()
while True:
    data = read_data()
    if data is None:
        eprint("Failed to read data. Terminating.")
        break
    main_loop()
    time.sleep(report_interval)
