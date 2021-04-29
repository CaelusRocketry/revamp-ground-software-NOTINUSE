from queue import Empty, Queue
import time
import heapq
import serial
import threading
import serial
from typing import Any, List, Tuple, Union
from packet import Packet, Log, LogPriority
from flask_socketio import Namespace
import socket
import boto3
from decimal import Decimal

# CREATE TABLE
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('CallistoSensorData')

BYTE_SIZE = 8192

DELAY = .05
DELAY_LISTEN = .005
DELAY_SEND = .2
DELAY_HEARTBEAT = 3

SEND_ALLOWED = True

BLOCK_SIZE = 32
f = open("black_box.txt", "w+")
f.close()


class Handler(Namespace):
    """ Handles all communication """

    def init(self, config):
        """ Based on given IP and port, create and connect a socket """

        """ A heapqueue of packets to send """
        self.queue_send: List[Tuple[str, str]] = []
        self.rcvd_data = ""
        
        self.send_thread = threading.Thread(target=self.send, daemon=True)
        self.send_thread.daemon = True
        self.listen_thread = threading.Thread(target=self.listen, daemon=True)
        self.listen_thread.daemon = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.heartbeat_thread.daemon = True
        # This is a queue of arguments to be sent to self.ingest()
        self.ingest_queue = Queue()
        # This thread reads from the ingest queue
        self.ingest_thread = threading.Thread(target=self.ingest_loop, daemon=True)
        self.ingest_thread.daemon = True

        self.ser = None
        self.running = False
        self.INITIAL_TIME = -100
        self.using_xbee = config["telemetry"]["USE_XBEE"]

        if self.using_xbee:
            baud = config["telemetry"]["XBEE_BAUDRATE"]
            xbee_port = config["telemetry"]["XBEE_PORT"]
            self.ser = serial.Serial(xbee_port, baud_rate)
            self.ser.flushInput()
            self.ser.flushOutput()
            print("Finished setting up xbee")
        
        else:
            gs_ip = config["telemetry"]["SOCKET_IP"]
            gs_port = config["telemetry"]["SOCKET_PORT"]
            self.connect_socket(gs_ip, gs_port)

        self.INITIAL_TIME = time.time()

        self.general_copy = None
        self.sensors_copy = None
        self.valves_copy = None
        self.buttons_copy = None

        self.rcvd = ""
        self.heartbeat_packet_number = 0

    ## telemetry methods

    def begin(self):
        """ Starts the send and listen threads """
        self.running = True
        self.listen_thread.start()
        self.heartbeat_thread.start()
        self.send_thread.start()
        self.ingest_thread.start()


    def connect_socket(self, ip, port):
        # Server-side socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Binds to the provided IP and port
        print("IP:", ip, "PORT:", port)
        self.sock.bind((ip, port))

        # Listens for connections, allowing at most 1 pending connection
        self.sock.listen(1)

        # Accept a connection
        (self.conn, _addr) = self.sock.accept()
        
        print("Finished connecting")


    def send_to_flight_software(self, json):
        log = Log(header=json['header'], message=json['message'], timestamp=round(time.time()-self.INITIAL_TIME, 3))
        self.enqueue(Packet(logs=[log], timestamp=log.timestamp))

    def send(self):
        """ Constantly sends next packet from queue to flight software """
        while self.running:
            try:
                if self.queue_send and SEND_ALLOWED:
                    _, packet_str = heapq.heappop(self.queue_send)
                    if self.using_xbee:
                        subpackets = [packet_str[i:60+i] for i in range(0, len(packet_str), 60)] #split into smaller packets of 60
                        for subpacket in subpackets:
                            self.ser.write(subpacket)
                            time.sleep(DELAY_SEND)
                    else:
                        self.conn.send(packet_str)
                    print("Sending:", packet_str)
                time.sleep(DELAY_SEND)

            except Exception as e:
                print("ERROR: ", e)
                self.running = False


    def listen(self):
        """ Constantly listens for any from ground station """
        while self.running:
            if self.using_xbee:
                data = self.ser.read(self.ser.in_waiting).decode()
            else:
                data = self.conn.recv(BYTE_SIZE).decode()
            print("Received: ", data)
            if data:
                self.rcvd += data

            packet_start = self.rcvd.find("^")
            if packet_start != -1:
                packet_end = self.rcvd.find("$", packet_start)
                if packet_end != -1:
                    incoming_packet = self.rcvd[packet_start+1:packet_end]
                    self.ingest_queue.put(incoming_packet)
                    self.rcvd = self.rcvd[packet_end+1:]
        
            time.sleep(DELAY_LISTEN)


    def enqueue(self, packet):
        """ Encrypts and enqueues the given Packet """
        # TODO: This is implemented wrong. It should enqueue by finding packets that have similar priorities, not changing the priorities of current packets.
        packet_str = ("^" + packet.to_string() + "$").encode("ascii")
        heapq.heappush(self.queue_send, (packet.priority, packet_str))

    
    def ingest_loop(self):
        """ Constantly ingests queue data, blocking until an item is available from the queue """
        while self.running:
            # block=True waits until an item is available
            # We add a timeout so the loop can stop
            try:
                data = self.ingest_queue.get(block=True, timeout=1)
                self.ingest(data)
            except Empty:
                pass


    def ingest(self, packet_str):
        """ Prints any packets received """
        print("Ingesting:", packet_str)
        packet = Packet.from_string(packet_str)
        for log in packet.logs:
            log.timestamp = round(log.timestamp, 1)   #########CHANGE THIS TO BE TIMESTAMP - START TIME IF PYTHON
            print("HEADER:", log.header)
            print("TIMESTAMP:", log.timestamp)
            if "heartbeat" in log.header or "stage" in log.header or "response" in log.header or "mode" in log.header:
                self.update_general(log.__dict__)

            if "sensor_data" in log.header:
                self.update_sensor_data(log.__dict__)

            if "valve_data" in log.header:
                self.update_valve_data(log.__dict__)
            
            log.save()


    def heartbeat(self):
        """ Constantly sends heartbeat message """
        while self.running:
            log = Log(header="heartbeat", message="AT - " + str(self.heartbeat_packet_number), timestamp=round(time.time()-self.INITIAL_TIME, 3))
            self.heartbeat_packet_number += 1

            self.enqueue(Packet(logs=[log], priority=LogPriority.INFO, timestamp=log.timestamp))
            print("Sent heartbeat")
            time.sleep(DELAY_HEARTBEAT)

    ## backend methods

    def update_general(self, log):
        log_send('general', log)
        self.socketio.emit('general', log, broadcast=True)
    
    
    def update_sensor_data(self, log):
        data = {}
        for sensor_type, sensor_locations in log['message'].items():
            if sensor_type == 'timestamp':
                data[sensor_type] = sensor_locations
                continue
            data[sensor_type] = {}
            for location, sensor in sensor_locations.items():
                data[sensor_type][location] = {}
                for val_key in sensor:
                    data[sensor_type][location][val_key] = Decimal(str(sensor[val_key]))

        table.put_item(
            Item={
                'Timestamp': Decimal(str(log['timestamp'])),
                'Data': data
            }
        )

        log_send('sensor', log)
        self.socketio.emit('sensor_data', log, broadcast=True)
    
    def update_valve_data(self, log):
        log_send('valve', log)
        self.socketio.emit('valve_data', log, broadcast=True)

    def update_store_data(self):
        self.socketio.emit('general_copy', self.general_copy)
        self.socketio.emit('sensors_copy', self.sensors_copy)
        self.socketio.emit('valves_copy', self.valves_copy)
        self.socketio.emit('buttons_copy', self.buttons_copy)

    ## store copy methods
    def update_general_copy(self, general):
        self.general_copy = general

    def update_sensors_copy(self, sensors):
        self.sensors_copy = sensors

    def update_valves_copy(self, valves):
        self.valves_copy = valves

    def update_buttons_copy(self, buttons):
        self.buttons_copy = buttons

    def on_button_press(self, data):
        log_send('button', data)
        if data['header'] == 'update_general':
            self.update_general_copy(data['message'])
        elif data['header'] == 'update_sensors':
            self.update_sensors_copy(data['message'])
        elif data['header'] == 'update_valves':
            self.update_valves_copy(data['message'])
        elif data['header'] == 'update_buttons':
            self.update_buttons_copy(data['message'])
        elif data['header'] == 'store_data':
            self.update_store_data()
        else:
            print(data)
            log = Log(header=data['header'], message=data['message'], timestamp=round(time.time()-self.INITIAL_TIME, 3))
            self.enqueue(Packet(logs=[log], priority=LogPriority.INFO, timestamp=log.timestamp))

hidden_log_types = {"general", "sensor", "valve", "button"}
def log_send(type, log):
    if type not in hidden_log_types:
        print(f"Sending to Frontend [{type}] {log}")