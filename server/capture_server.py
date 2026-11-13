#!/usr/bin/env python3
"""
Servidor de captura para o online do Marvel vs. Capcom 2 (PS2 Japao).
- Escuta TCP nas portas indicadas e mostra, em hexadecimal, tudo que o jogo enviar.
- Escuta UDP na porta 9999 e mostra os logs que o PS2 manda (o que o jogo pediu, DNS, etc.).
- Tudo e salvo em capture.log para voce me enviar.

Uso:   python capture_server.py                 (porta TCP 1000)
       python capture_server.py --ports 1000,10000
       python capture_server.py --greet 0c6000000000000000000000   (envia bytes ao conectar)
"""
import argparse, socket, threading, time, sys

LOG = open("capture.log", "a", encoding="utf-8")
LOCK = threading.Lock()

def out(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    with LOCK:
        print(line); sys.stdout.flush()
        LOG.write(line + "\n"); LOG.flush()

def hexdump(b):
    rows = []
    for i in range(0, len(b), 16):
        chunk = b[i:i+16]
        rows.append("%04x  %-47s  %s" % (i, " ".join("%02x" % c for c in chunk),
                    "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
    return "\n".join(rows)

def handle(conn, addr, port, greet):
    out("[TCP %d] conexao de %s:%d" % (port, addr[0], addr[1]))
    try:
        if greet:
            conn.sendall(greet); out("[TCP %d] enviado (greet): %s" % (port, greet.hex()))
        while True:
            data = conn.recv(4096)
            if not data:
                break
            out("[TCP %d] recebido %d bytes:\n%s" % (port, len(data), hexdump(data)))
    except Exception as e:
        out("[TCP %d] erro: %s" % (port, e))
    finally:
        out("[TCP %d] conexao encerrada" % port); conn.close()

def tcp_listener(port, greet):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port)); s.listen(5)
    out("escutando TCP %d" % port)
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a, port, greet), daemon=True).start()

def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    return sorted(ips)

def udp_logger(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    out("escutando logs UDP %d (mensagens do PS2)" % port)
    last = ""
    while True:
        d, a = s.recvfrom(2048)
        if d.startswith(b"MVC2-DISCOVER"):
            s.sendto(b"MVC2-SERVER", a)
            continue
        t = d.decode("latin-1").rstrip()
        if "hb:" in t:
            if t == last:
                continue
            last = t
        out("[PS2 %s] %s" % (a[0], t))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="1000")
    ap.add_argument("--logport", type=int, default=9999)
    ap.add_argument("--greet", default="")
    a = ap.parse_args()
    greet = bytes.fromhex(a.greet) if a.greet else b""
    for p in a.ports.split(","):
        threading.Thread(target=tcp_listener, args=(int(p), greet), daemon=True).start()
    threading.Thread(target=udp_logger, args=(a.logport,), daemon=True).start()
    out("IPs deste PC: " + ", ".join(local_ips()))
    out("pronto. Aguardando o PS2... (Ctrl+C para sair)")
    while True: time.sleep(1)
