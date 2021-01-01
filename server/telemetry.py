import time
import heapq
import socket
import threading
from packet import Packet, Log, LogPriority

BYTE_SIZE = 8192

DELAY = .05
DELAY_LISTEN = .05
DELAY_SEND = .05
DELAY_HEARTBEAT = 3

SEND_ALLOWED = True

BLOCK_SIZE = 32
f = open("black_box.txt", "w+")
f.close()


class Telemetry:
    """ Telemetry Class handles all communication """

    def __init__(self, ip, port):
        """ Based on given IP and port, create and connect a socket """
        self.queue_send = []
        self.connect(ip, port)
        self.start_time = time.time()


    def connect(self, ip, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print("IP:", ip, "PORT:", port)
        self.sock.bind((ip, port))
        self.sock.listen(1)
        self.conn, self.addr = self.sock.accept()
        Log("Created socket")
        print("finished running connect method")


    def init_backend(self, b):
        self.backend = b


    def begin(self):
        """ Starts the send and listen threads """
        self.send_thread = threading.Thread(target=self.send)
        self.send_thread.daemon = True
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.daemon = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat)
        self.heartbeat_thread.daemon = True
        self.send_thread.start()
        self.listen_thread.start()
        self.heartbeat_thread.start()


    def send(self):
        """ Constantly sends next packet from queue to ground station """
        while True:
            if self.queue_send and SEND_ALLOWED:
                encoded = heapq.heappop(self.queue_send)[1]
                self.conn.send(encoded)
            time.sleep(DELAY_SEND)


    def listen(self):
        """ Constantly listens for any from ground station """
        while True:
            data = self.conn.recv(BYTE_SIZE)
            if data:
                self.ingest_thread = threading.Thread(
                    target=self.ingest, args=(data,))
                self.ingest_thread.daemon = True
                self.ingest_thread.start()
                # time.sleep(DELAY_LISTEN)


    def enqueue(self, packet):
        """ Encrypts and enqueues the given Packet """
        packet_str = (packet.to_string() + "END").encode()
        heapq.heappush(self.queue_send, (packet.level, packet_str))


    def ingest(self, packet_str):
        """ Prints any packets received """
#        print("Ingesting:", packet_str)
        packet_str = packet_str.decode()
        packet_strs = packet_str.split("END")[:-1]
        if (packet_str.count("END") > 1):
            packets = [Packet.from_string(p_str) for p_str in packet_strs]
        else:
            packets = [Packet.from_string(packet_strs[0])]

        #packet = Packet.from_string(packet_str)
        for packet in packets:
            for log in packet.logs:
                log.timestamp = round(log.timestamp, 1)   ##########################################CHANGE THIS TO BE TIMESTAMP - START TIME IF PYTHON
#                print("Timestamp:", log.timestamp)
                if log.header in ["heartbeat", "stage", "response", "mode"]:
                    self.backend.update_general(log.__dict__)

                if log.header == "sensor_data":
                    self.backend.update_sensor_data(log.__dict__)

                if log.header == "valve_data":
                    self.backend.update_valve_data(log.__dict__)
                
                log.save()


    def heartbeat(self):
        """ Constantly sends heartbeat message """
        while True:
            log = Log(header="heartbeat", message="AT")
            self.enqueue(Packet(logs=[log], level=LogPriority.INFO))
            print("Sent heartbeat")
            time.sleep(DELAY_HEARTBEAT)