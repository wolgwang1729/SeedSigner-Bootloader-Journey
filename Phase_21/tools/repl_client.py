#!/usr/bin/env python3
"""Phase 21: interactive MicroPython REPL client over esp-emu --uart-tcp.

The firmware REPL executes a line only on carriage return (MicroPython
shared/readline expects '\\r'; a plain terminal Enter sends '\\n', which is
swallowed). This client runs the tty in raw mode and forwards every
keystroke to the emulator immediately (Enter and pasted newlines become
'\\r'), so the REPL echoes characters as you type and executes on Enter.

Keys:
  - Enter (and pasted \\n) execute as on a real board.
  - Ctrl-C is forwarded to the device (interrupts running code).
  - Ctrl-D quits the client (hangs up the TCP bridge; the emulator exits).
"""
import argparse, os, socket, sys, termios, threading

p = argparse.ArgumentParser()
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=5555)
a = p.parse_args()

s = socket.create_connection((a.host, a.port))

def rx():
    while True:
        try:
            d = s.recv(4096)
        except OSError:
            break
        if not d:
            break
        sys.stdout.write(d.decode(errors="replace"))
        sys.stdout.flush()

def send_keystrokes(fd):
    while True:
        try:
            b = os.read(fd, 1)
        except OSError:
            b = b""
        if not b:
            break
        if b == b"\x04":                 # Ctrl-D -> leave the client cleanly
            print("\n(repl_client: bye)")
            break
        if b in (b"\r", b"\n"):          # Enter / pasted newline -> CR
            s.sendall(b"\r")
            continue
        try:
            s.sendall(b)                 # everything else forwarded as-is
        except OSError:
            break
    s.shutdown(socket.SHUT_RDWR)

def send_lines():
    for line in sys.stdin:
        s.sendall(line.rstrip("\n").encode() + b"\r")
    s.shutdown(socket.SHUT_RDWR)

# receiver first so nothing the emulator prints before our first send is missed
threading.Thread(target=rx, daemon=True).start()

if sys.stdin.isatty():
    fd = sys.stdin.fileno()
    attr = termios.tcgetattr(fd)
    try:
        new = list(attr)
        new[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
        new[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK |
                    termios.ISTRIP | termios.INLCR | termios.IGNCR |
                    termios.ICRNL | termios.IXON)
        # oflags left untouched: OPOST|ONLCR stay on so the remote '\n'
        # output still renders with CR handled by the terminal
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new)
        send_keystrokes(fd)
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attr)
        s.close()
else:
    try:
        send_lines()
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        s.close()
