"""
tcp_sender.py - Non-blocking TCP JSON sender.

Import into CV model and call send() instead of print().
Messages are framed as newline-delimited JSON (one JSON object per line),
which is easy to read on the Unity side with StreamReader.ReadLine().

Usage:
    from tcp_sender import JsonTcpSender

    sender = JsonTcpSender("127.0.0.1", 5005)
    sender.start()
    sender.send({"id": 42, "x": 1.0, "y": 2.0})   # returns immediately
    ...
    sender.stop()

Or as a context manager:
    with JsonTcpSender("127.0.0.1", 5005) as sender:
        sender.send({"x": 1.0})
"""

import json
import queue
import socket
import threading
import time


class JsonTcpSender:
    def __init__(self, host="127.0.0.1", port=5005, max_queue=10000,
                 reconnect_delay=1.0, drop_oldest=True):
        """
        host / port      : address of the listener (Unity).
        max_queue        : max messages buffered while disconnected or slow.
        reconnect_delay  : seconds between connection attempts.
        drop_oldest      : if the buffer is full, discard the oldest message
                           (keeps data fresh). If False, discard the new one.
        """
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        self.drop_oldest = drop_oldest
        self.dropped = 0  # count of messages discarded due to a full buffer

        self._queue = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._thread = None
        self._sock = None

    # ---- public API -------------------------------------------------------

    def start(self):
        #check if thread alive
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()

        #create thread object
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="JsonTcpSender")
        
        #start thread
        self._thread.start()

    def send(self, data):
        """Queue a dict/list (or pre-serialized JSON string) for sending.
        Never blocks the caller."""
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        payload = data if isinstance(data, str) else json.dumps(
            data, separators=(",", ":"))
        line = (payload + "\n").encode("utf-8")

        try:
            self._queue.put_nowait(line)
        except queue.Full:
            self.dropped += 1
            if self.drop_oldest:
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(line)
                except (queue.Empty, queue.Full):
                    pass

    def stop(self, flush_timeout=2.0):
        """Try to flush pending messages, then shut down."""
        deadline = time.time() + flush_timeout
        while not self._queue.empty() and time.time() < deadline \
                and self._sock is not None:
            time.sleep(0.01)
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._close_socket()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # ---- internals --------------------------------------------------------

    def _connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # low latency
        sock.settimeout(3.0)
        sock.connect((self.host, self.port))
        sock.settimeout(None)
        

        return MonitoredSocket(sock)

    def get_stats(self) -> dict:
        """Return live socket performance metrics and queue stats"""
        stats = {
                "queue_size": self._queue.qsize(),
                "dropped_messages": self.dropped,
                "connected": self._sock is not None,
        }

        if self._sock is not None:
            stats.update(self._sock.get_stats())

        return stats

    def _close_socket(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _run(self):
        pending = None  # message we failed to send, retried after reconnect
        while not self._stop_event.is_set():
            # (Re)connect
            if self._sock is None:
                try:
                    self._sock = self._connect()
                    print(f"[sender] connected to {self.host}:{self.port}")
                except OSError:
                    self._stop_event.wait(self.reconnect_delay)
                    continue

            # Get next message
            if pending is None:
                try:
                    pending = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

            # Batch whatever else is waiting into one send() call
            batch = [pending]
            while len(batch) < 500:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            data = b"".join(batch)

            try:
                self._sock.sendall(data)
                pending = None
            except OSError:
                print("[sender] connection lost, reconnecting...")
                self._close_socket()
                pending = data  # resend the whole batch after reconnecting






class MonitoredSocket:
    """Wrapper around a standard socket to record performance metrics"""

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self.start_time = time.time()

        self.bytes_sent = 0
        self.bytes_received = 0
        self.send_calls = 0
        self.recv_calls = 0

        self.last_send_time = None
        self.last_recv_time = None

    def sendall(self, data: bytes, flags: int = 0) -> None:
        """Track bytes send through sendall()"""
        self._sock.sendall(data, flags)
        now = time.time()
        self.bytes_sent += len(data)
        self.send_calls += 1
        self.last_send_time = now

    def send(self, data: bytes, flags: int = 0) -> int:
        """function for tracking partial sends"""
        sent = self._sock.send(data, flags)
        now = time.time()
        self.bytes_sent += sent
        self.send_calls += 1
        self.last_send_time = now
        return sent

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        """track incoming data"""
        data = self._sock.recv(bufsize, flags)
        now = time.time()
        self.bytes_received += len(data)
        self.recv_calls += 1
        self.last_recv_time = now
        return data

    def get_stats(self) -> dict:
        """Calculates throughput rates and current runtime"""
        elapsed = time.time() - self.start_time
        safe_elapsed = max(elapsed, 0.001) # prevents div by zero error

        return{
                "elapsed_seconds": round(elapsed, 2),
                "bytes_sent": self.bytes_sent,
                "bytes_received": self.bytes_received,
                "sent_rate_kbps":round((self.bytes_sent / 1024) / safe_elapsed, 2),
                "recv_rate_kbps":round((self.bytes_received / 1024) / safe_elapsed, 2),
                "send_calls": self.send_calls,
                "avg_payload_bytes": round(self.bytes_sent / max(self.send_calls, 1), 1),
        }
        
    def __getattr__(self, name: str):
        """Pass any unhandled socket method to the raw socket"""
        return getattr(self._sock, name)
