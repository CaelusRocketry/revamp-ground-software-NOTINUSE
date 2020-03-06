import socket
import threading
import time
import heapq
import multiprocessing
from packet import Packet, Log
import ast
import base64

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
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((ip, port))
        self.sock.listen(1)
        self.conn, self.addr = self.sock.accept()
        Log("Created socket")
    
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
            self.ingest_thread = threading.Thread(target=self.ingest, args=(data,))
            self.ingest_thread.daemon = True
            self.ingest_thread.start()
            time.sleep(DELAY_LISTEN)

    def enqueue(self, packet):
        """ Encripts and enqueues the given Packet """
        packet_str = packet.to_string().encode()
        heapq.heappush(self.queue_send, (packet.level, packet_str))

    def ingest(self, packet_str):
        """ Prints any packets received """
        packet = Packet.from_string(packet_str)
        for log in packet.logs:
            print(log.to_string())
            log.save()

    def heartbeat(self):
        """ Constantly sends heartbeat message """
        while True:
            log = Log(header="HEARTBEAT", message="AT")
            self.enqueue(Packet(header="HEARTBEAT", logs=[log]))
            print("Sent heartbeat")
            time.sleep(DELAY_HEARTBEAT)
