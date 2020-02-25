import ast
import binascii
import re
import subprocess
import sys
import time

import select
import serial
import serial.tools.list_ports
import socket
import websocket  # the old non async one

serialTimeout = 0.5
serialTimeoutCount = 10

wifiMessageIgnore = re.compile(
    "(\x1b\[[\d;]*m)?[WI] \(\d+\) (wifi|system_api|modsocket|phy|event|cpu_start|heap_init|network|wpa): ")


# this should take account of the operating system
def guess_serial_port():
    lp = list(serial.tools.list_ports.grep(""))
    lp.sort(key=lambda item: (item.hwid == "n/a", item.device))
    # n/a could be good evidence that the port is non-existent
    return [x.device for x in lp]


# merge uncoming serial stream and break at OK, \x04, >, \r\n, and long delays
# (must make this a member function so does not have to switch on the type of s)
def yield_serial_chunk(s):
    res = []
    n = 0
    websocket_res_buffer = b""
    websocket_res_buffer_i = 0
    while True:
        try:
            if type(s) == serial.Serial:
                b = s.read()
            elif type(s) == socket.socket:
                r, w, e = select.select([s], [], [], serialTimeout)
                if r:
                    b = s._sock.recv(1)
                else:
                    b = b''

            else:  # websocket (break down to individual bytes)
                if websocket_res_buffer_i >= len(websocket_res_buffer):
                    r, w, e = select.select([s], [], [], serialTimeout)
                    if r:
                        websocket_res_buffer = s.recv()
                        # this comes as batches of strings, which beed to be broken to characters
                        if type(websocket_res_buffer) == str:
                            websocket_res_buffer = websocket_res_buffer.encode(
                                "utf8")  # handle fact that strings come back from this interface
                    else:
                        websocket_res_buffer = b''
                    websocket_res_buffer_i = 0

                if len(websocket_res_buffer) > 0:
                    b = websocket_res_buffer[websocket_res_buffer_i:websocket_res_buffer_i + 1]
                    websocket_res_buffer_i += 1
                else:
                    b = b''
        except serial.SerialException as e:
            yield b"\r\n**[ys] "
            yield str(type(e)).encode("utf8")
            yield b"\r\n**[ys] "
            yield str(e).encode("utf8")
            yield b"\r\n\r\n"
            break

        if not b:
            if res and (res[0] != 'O' or len(res) > 3):
                yield b''.join(res)
                res.clear()
            else:
                n += 1
                if (n % serialTimeoutCount) == 0:
                    yield b''
                    # yield a blank line every (serialtimeout*serialtimeoutcount) seconds

        elif b == b'K' and len(res) >= 1 and res[-1] == b'O':
            if len(res) > 1:
                yield b''.join(res[:-1])
            yield b'OK'
            res.clear()
        elif b == b'\x04' or b == b'>':
            if res:
                yield b''.join(res)
            yield b
            res.clear()
        else:
            res.append(b)
            if b == b'\n' and len(res) >= 2 and res[-2] == b'\r':
                yield b''.join(res)
                res.clear()


class DeviceConnector:
    def __init__(self, sres, sres_sys):
        self.working_serial = None
        self.working_socket = None
        self.working_websocket = None
        self.working_serial_chunk = None
        self.sres = sres  # two output functions borrowed across
        self.sres_sys = sres_sys
        self._esptool_command = None

    def working_serial_readall(self):
        # usually used to clear the incoming buffer, results are printed out rather than used
        if self.working_serial:
            return self.working_serial.read_all()

        if self.working_websocket:
            res = []
            while True:
                r, w, e = select.select([self.working_websocket], [], [],
                                        0.2)  # add a timeout to the webrepl, which can be slow
                if not r:
                    break
                res.append(self.working_websocket.recv())
            return "".join(res)  # this is returning a text array, not bytes
            # though a binary frame can be stipulated according to websocket.ABNF.OPCODE_MAP
            # fix this when we see it

        # socket case, get it all down
        res = []
        while True:
            r, w, e = select.select([self.working_socket._sock], [], [], 0)
            if not r:
                break
            res.append(self.working_socket._sock.recv(1000))
            self.sres("Selected socket {}  {}\n".format(len(res), len(res[-1])))
        return b"".join(res)

    def disconnect(self, raw=False, verbose=False):
        if not raw:
            self.exit_paste_mode(verbose)  # this doesn't seem to do any good (paste mode is left on disconnect anyway)

        self.working_serial_chunk = None
        if self.working_serial is not None:
            if verbose:
                self.sres_sys("\nClosing serial {}\n".format(str(self.working_serial)))
            self.working_serial.close()
            self.working_serial = None
        if self.working_socket is not None:
            self.sres_sys("\nClosing socket {}\n".format(str(self.working_socket)))
            self.working_socket.close()
            self.working_socket = None
        if self.working_websocket is not None:
            self.sres_sys("\nClosing websocket {}\n".format(str(self.working_websocket)))
            self.working_websocket.close()
            self.working_websocket = None

    def serial_connect(self, portname, baudrate, verbose):
        assert not self.working_serial
        if type(portname) is int:
            port_index = portname
            possible_ports = guess_serial_port()
            if possible_ports:
                portname = possible_ports[port_index]
                if len(possible_ports) > 1:
                    self.sres("Found serial ports: {} \n".format(", ".join(possible_ports)))
            else:
                self.sres_sys("No possible ports found")
                portname = ("COM4" if sys.platform == "win32" else "/dev/ttyUSB0")

        self.sres_sys("Connecting to --port={} --baud={} ".format(portname, baudrate))
        try:
            self.working_serial = serial.Serial(portname, baudrate, timeout=serialTimeout)
        except serial.SerialException as e:
            self.sres(e.strerror)
            self.sres("\n")
            possible_ports = guess_serial_port()
            if possible_ports:
                self.sres_sys("\nTry one of these ports as --port= \n  {}".format("\n  ".join(possible_ports)))
            else:
                self.sres_sys("\nAre you sure your ESP-device is plugged in?")
            return

        i = 0
        for i in range(5001):
            if self.working_serial.isOpen():
                break
            time.sleep(0.01)
        if verbose:
            self.sres_sys(" [connected]")
        self.sres("\n")
        if verbose:
            self.sres(str(self.working_serial))
            self.sres("\n")

        if i != 0 and verbose:
            self.sres("Waited {} seconds for isOpen()\n".format(i * 0.01))

    def socket_connect(self, ipnumber, portnumber):
        self.disconnect(verbose=True)

        self.sres_sys("Connecting to socket ({} {})\n".format(ipnumber, portnumber))
        s = socket.socket()
        try:
            self.sres("preconnect\n")
            s.connect(socket.getaddrinfo(ipnumber, portnumber)[0][-1])
            self.sres("Doing makefile\n")
            self.working_socket = s.makefile('rwb', 0)
        except OSError as e:
            self.sres("Socket OSError {}".format(str(e)))
        except ConnectionRefusedError as e:
            self.sres("Socket ConnectionRefusedError {}".format(str(e)))

    def websocket_connect(self, websocket_url):
        self.disconnect(verbose=True)
        try:
            self.working_websocket = websocket.create_connection(websocket_url, 5)
            self.working_websocket.settimeout(serialTimeout)
        except socket.timeout:
            self.sres("Websocket Timeout after 5 seconds {}\n".format(websocket_url))
        except ValueError as e:
            self.sres("WebSocket ValueError {}\n".format(str(e)))
        except ConnectionResetError as e:
            self.sres("WebSocket ConnectionError {}\n".format(str(e)))
        except OSError as e:
            self.sres("WebSocket OSError {}\n".format(str(e)))
        except websocket.WebSocketException as e:
            self.sres("WebSocketException {}\n".format(str(e)))

    def esptool(self, esp_command, portname, binfile):
        self.disconnect(verbose=True)
        if type(portname) is int:
            possible_ports = guess_serial_port()
            if possible_ports:
                portname = possible_ports[portname]
                if len(possible_ports) > 1:
                    self.sres("Found serial ports {}: \n".format(", ".join(possible_ports)))
            else:
                self.sres("No possible ports found")
                portname = ("COM4" if sys.platform == "win32" else "/dev/ttyUSB0")

        if self._esptool_command is None:
            # this section for finding what the name of the command function is
            # may print junk into the jupyter Lab logs
            for command in ("esptool.py", "esptool"):
                try:
                    subprocess.check_call([command, "version"])
                    self._esptool_command = command
                    break
                except (subprocess.CalledProcessError, OSError):
                    pass
            if self._esptool_command is None:
                self.sres("esptool not found on path\n")
                return

        pargs = [self._esptool_command, "--port", portname]
        if esp_command == "erase":
            pargs.append("erase_flash")
        if esp_command == "esp32":
            pargs.extend(["--chip", "esp32", "write_flash", "-z", "0x1000"])
            pargs.append(binfile)
        if esp_command == "esp8266":
            pargs.extend(["--baud", "460800", "write_flash", "--flash_size=detect", "-fm", "dio", "0"])
            pargs.append(binfile)
        self.sres_sys("Executing:\n  {}\n\n".format(" ".join(pargs)))
        process = subprocess.Popen(pargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in process.stdout:
            x = line.decode()
            self.sres(x)
            if x[:12] == "Connecting..":
                self.sres_sys("[Press the PRG button now if required]\n")
        for line in process.stderr:
            self.sres(line.decode(), n04count=1)

    def mpycross(self, mpycrossexe, pyfile):
        pargs = [mpycrossexe, pyfile]
        self.sres_sys("Executing:  {}\n".format(" ".join(pargs)))
        process = subprocess.Popen(pargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in process.stdout:
            self.sres(line.decode())
        for line in process.stderr:
            self.sres(line.decode(), n04count=1)

    def receive_stream(self, seek_okay, warn_okay_priors=True, five_second_timeout=False, fetch_file_capture_chunks=0):
        n04count = 0
        reboot_detected = False
        res = []
        for j in range(2):
            # for restarting the chunk when interrupted
            if self.working_serial_chunk is None:
                self.working_serial_chunk = yield_serial_chunk(
                    self.working_serial or self.working_socket or self.working_websocket)

            index_prev_greater_than_sign = -1
            # index04line = -1
            for i, receive_line in enumerate(self.working_serial_chunk):
                assert receive_line is not None

                # warning message when we are waiting on an OK
                if seek_okay and warn_okay_priors and (receive_line != b'OK') and (
                        receive_line != b'>') and receive_line.strip():
                    self.sres("\n[missing-OK]")

                # the main interpreting loop
                if receive_line == b'OK' and seek_okay:
                    if i != 0 and warn_okay_priors:
                        self.sres("\n\n[Late OK]\n\n")
                    seek_okay = False

                # one of 2 Ctrl-Ds in the return from execute in paste mode
                elif receive_line == b'\x04':
                    n04count += 1
                    # index04line = i

                # leaving condition where OK...x04...x04...> has been found in paste mode
                elif receive_line == b'>' and n04count >= 2 and not seek_okay:
                    if n04count != 2:
                        self.sres("[too many x04s %d]" % n04count)
                    break

                elif receive_line == b'':
                    if five_second_timeout:
                        self.sres("[Timed out waiting for recognizable response]\n", 31)
                        return False
                    # str holding position to prove it's alive
                    self.sres("")
                    # self.sres("\n[Waiting for the program to finish]\n\n")

                elif receive_line == b'Type "help()" for more information.\r\n':
                    reboot_detected = True
                    self.sres(receive_line.decode(), n04count=n04count)

                elif receive_line == b'>':
                    index_prev_greater_than_sign = i
                    self.sres('>', n04count=n04count)

                # looks for ">>> "
                elif receive_line == b' ' and reboot_detected and index_prev_greater_than_sign == i - 1:
                    self.sres("[reboot detected %d]" % n04count)
                    self.enter_paste_mode()
                    # this is unintentionally recursive, but after a reboot has been seen we need to get into paste mode
                    self.sres(' ', n04count=n04count)
                    break

                # normal processing of the string of bytes that have come in
                else:
                    try:
                        ur = receive_line.decode()
                    except UnicodeDecodeError:
                        ur = str(receive_line)
                    if not wifiMessageIgnore.match(ur):
                        if fetch_file_capture_chunks:
                            if res and res[-1][-2:] != "\r\n":
                                # need to rejoin strings that have been split on the b"OK" string by the lexical parser
                                res[-1] = res[-1] + ur
                            else:
                                res.append(ur)
                            if (i % 10) == 0 and fetch_file_capture_chunks > 0:
                                self.sres("%d%% fetched\n" % int(len(res) / fetch_file_capture_chunks * 100 + 0.5),
                                          clear_output=True)
                        else:
                            self.sres(ur, n04count=n04count)

            # else on the for-loop, means the generator has ended at a stop iteration
            # this happens with Keyboard interrupt, and generator needs to be rebuilt
            else:  # of the for-command
                self.working_serial_chunk = None
                continue

            break  # out of the for loop
        return res if fetch_file_capture_chunks else True

    def send_to_file(self, destination_filename, mkdir, append, binary, quiet, file_contents):
        if not (self.working_serial or self.working_websocket):
            self.sres("File transfers not implemented for sockets\n", 31)
            return

        lines = []
        if not binary:
            lines = file_contents.splitlines(True)
            maxlinelen = max(map(len, lines), default=0)
            if maxlinelen > 250:
                self.sres("Line length {} exceeds maximum for line ascii files, try --binary\n".format(maxlinelen),
                          31)
                return

        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send

        if mkdir:
            dseq = [d for d in destination_filename.split("/")[:-1] if d]
            if dseq:
                working_device_write(b'import os\r\n')
                for i in range(len(dseq)):
                    working_device_write('try:  os.mkdir({})\r\n'.format(repr("/".join(dseq[:i + 1]))).encode())
                    working_device_write(b'except OSError:  pass\r\n')

        file_modifier = ("a" if append else "w") + ("b" if binary else "")
        if binary:
            working_device_write(b"import ubinascii; O6 = ubinascii.a2b_base64\r\n")
        working_device_write("O=open({}, '{}')\r\n".format(repr(destination_filename), file_modifier).encode())
        working_device_write(b'\r\x04')  # intermediate execution
        self.receive_stream(seek_okay=True)
        clear_output = True  # set this to False to help with debugging
        if binary:
            if type(file_contents) == str:
                file_contents = file_contents.encode()

            chunk_size = 30
            chunks_len = int(len(file_contents) / chunk_size)

            i = 0
            for i in range(chunks_len + 1):
                chunk_bytes = file_contents[i * chunk_size:(i + 1) * chunk_size]
                working_device_write(b'O.write(O6("')
                working_device_write(binascii.b2a_base64(chunk_bytes)[:-1])
                working_device_write(b'"))\r\n')
                if (i % 10) == 9:
                    working_device_write(b'\r\x04')  # intermediate executions
                    self.receive_stream(seek_okay=True)
                    if not quiet:
                        self.sres("{}%, chunk {}".format(int((i + 1) / (chunks_len + 1) * 100), i + 1),
                                  clear_output=clear_output)
            self.sres("Sent {} bytes in {} chunks to {}.\n".format(len(file_contents), i + 1, destination_filename),
                      clear_output=not quiet)

        else:
            i = -1
            line_chunk_size = 5

            if append:
                working_device_write("O.write('\\n')\r\n".encode())  # avoid line concattenation on appends
            for i, line in enumerate(lines):
                working_device_write("O.write({})\r\n".format(repr(line)).encode())
                if (i % line_chunk_size) == line_chunk_size - 1:
                    working_device_write(b'\r\x04')  # intermediate executions
                    self.receive_stream(seek_okay=True)
                    if not quiet:
                        self.sres("{}%, line {}\n".format(int((i + 1) / (len(lines) + 1) * 100), i + 1),
                                  clear_output=clear_output)
            self.sres("Sent {} lines ({} bytes) to {}.\n".format(i + 1, len(file_contents), destination_filename),
                      clear_output=(clear_output and not quiet))

        working_device_write("O.close()\r\n".encode())
        working_device_write("del O\r\n".encode())
        working_device_write(b'\r\x04')
        self.receive_stream(seek_okay=True)

    def fetch_file(self, source_filename, binary, quiet):
        if not (self.working_serial or self.working_websocket):
            self.sres("File transfers not implemented for sockets\n", 31)
            return None
        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send

        if not binary:
            self.sres("non-binary mode not implemented, switching to binary")
        if True:
            chunk_size = 30
            working_device_write(b"import sys,os;O7=sys.stdout.write\r\n")
            working_device_write(b"import ubinascii;O8=ubinascii.b2a_base64\r\n")
            working_device_write("O=open({},'rb')\r\n".format(repr(source_filename)).encode())
            working_device_write(b"O9=bytearray(%d)\r\n" % chunk_size)
            working_device_write("O4=os.stat({})[6]\r\n".format(repr(source_filename)).encode())
            working_device_write(b"print(O4)\r\n")
            working_device_write(b'\r\x04')  # intermediate execution to get chunk size
            chunk_res = self.receive_stream(seek_okay=True, fetch_file_capture_chunks=-1)
            try:
                bytes_num = int("".join(chunk_res))
            except ValueError:
                self.sres(str(chunk_res))
                return None

            working_device_write(b"O7(O8(O.read(O4%%%d)))\r\n" % chunk_size)  # get sub-block
            working_device_write(b"while O.readinto(O9): O7(O8(O9))\r\n")
            working_device_write(b"O.close(); del O,O7,O8,O9,O4\r\n")
            working_device_write(b'\r\x04')
            chunks = self.receive_stream(seek_okay=True, fetch_file_capture_chunks=bytes_num // chunk_size + 1)
            receive_res = []
            for ch in chunks:
                try:
                    receive_res.append(binascii.a2b_base64(ch))
                except binascii.Error as e:
                    self.sres(str(e))
                    self.sres(str([ch]))
            res = b"".join(receive_res)
            if not quiet:
                self.sres("Fetched {}={} bytes from {}.\n".format(len(res), bytes_num, source_filename),
                          clear_output=True)
            return res

    def working_device_list_dir(self, working_device_write, dirname):
        working_device_write(b"import os,sys\r\n")
        working_device_write(("for O in os.ilistdir(%s):\r\n" % repr(dirname)).encode())
        working_device_write(b"  sys.stdout.write(repr(O))\r\n")
        working_device_write(b"  sys.stdout.write('\\n')\r\n")
        working_device_write(b"del O\r\n")
        working_device_write(b'\r\x04')
        k = self.receive_stream(seek_okay=True, fetch_file_capture_chunks=-1)
        receive_list = []
        try:
            receive_list = list(map(ast.literal_eval, k))
        except SyntaxError:
            self.sres("Empty directory")
        receive_list.sort()
        for item in receive_list:
            if item[1] == 0x4000:
                self.sres("             %s/\n" % (dirname + '/' + item[0]).lstrip("/"))
            else:
                self.sres("%9d    %s\n" % (item[3], (dirname + '/' + item[0]).lstrip("/")))
        return [dirname + "/" + item[0] for item in receive_list if item[1] == 0x4000]

    def listdir(self, dirname, recurse):
        self.sres("Listing directory '%s'.\n" % (dirname or '/'))
        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send
        ld = self.working_device_list_dir(working_device_write, dirname)
        if recurse:
            while ld:
                d = ld.pop(0)
                self.sres("\n%s:\n" % d.lstrip("/"))
                ld.extend(self.working_device_list_dir(working_device_write, d))
        return None

    def mem_info(self):
        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send
        working_device_write(b"from micropython import mem_info\r\n")
        working_device_write(b"import sys\r\n")
        working_device_write(b"mem_info()\r\n")
        working_device_write(b'\r\x04')
        ram = self.receive_stream(seek_okay=True, fetch_file_capture_chunks=-1)
        assert type(ram) != bool
        # self.sres(str(ram))
        mem_info = ram[1]
        mem = {elem.strip().split(':')[0]: int(elem.strip().split(':')[1]) for elem in mem_info[4:].split(',')}
        total_mem = mem['total'] / 1024
        used_mem = mem['used'] / 1024
        free_mem = mem['free'] / 1024
        total_mem_s = "{:.3f} KB".format(total_mem)
        used_mem_s = "{:.3f} KB".format(used_mem)
        free_mem_s = "{:.3f} KB".format(free_mem)
        self.sres("{0:12}{1:^12}{2:^12}{3:^12}{4:^12}\n".format(*['Memmory','Size', 'Used','Avail','Use%']))
        self.sres('{0:12}{1:^12}{2:^12}{3:^12}{4:>8}\n'.format('RAM', total_mem_s,
                                                               used_mem_s, free_mem_s,
                                                               "{:.1f} %".format((used_mem / total_mem) * 100)))
        return None

    def remove_file(self, filename):
        self.sres("Delete file: '%s'.\n" % filename)
        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send
        working_device_write(b"try:\r\n")
        working_device_write(b"  import os\r\n")
        working_device_write(b"except ImportError:\r\n")
        working_device_write(b"  import uos as os\r\n")
        working_device_write(("os.remove(%s)\r\n" % repr(filename)).encode())
        working_device_write(b'\r\x04')
        self.receive_stream(True)
        return None

    def remove_dir(self, directory):
        self.sres("Delete directory: '%s'.\n" % directory)
        working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send
        working_device_write(b"try:\r\n")
        working_device_write(b"  import os\r\n")
        working_device_write(b"except ImportError:\r\n")
        working_device_write(b"  import uos as os\r\n")
        working_device_write(b"def rmdir(dir):\r\n")
        working_device_write(b"  os.chdir(dir)\r\n")
        working_device_write(b"  for f in os.listdir():\r\n")
        working_device_write(b"    try:\r\n")
        working_device_write(b"      os.remove(f)\r\n")
        working_device_write(b"    except OSError:\r\n")
        working_device_write(b"      pass\r\n")
        working_device_write(b"  for f in os.listdir():\r\n")
        working_device_write(b"    rmdir(f)\r\n")
        working_device_write(b"  for f in os.listdir():\r\n")
        working_device_write(b"    rmdir(f)\r\n")
        working_device_write(b"  try:\r\n")
        working_device_write(b"    os.chdir('..')\r\n")
        working_device_write(b"    os.rmdir(dir)\r\n")
        working_device_write(b"  except OSError:\r\n")
        working_device_write(b"    pass\r\n")
        working_device_write(("rmdir(%s)\r\n" % repr(directory)).encode())
        working_device_write(b'\r\x04')
        self.receive_stream(True)
        return None

    def enter_paste_mode(self, verbose=True):
        # now sort out connection situation
        if self.working_serial or self.working_websocket:
            working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send

            time.sleep(0.2)  # try to give a moment to connect before issuing the Ctrl-C
            working_device_write(b'\x03')  # ctrl-C: kill off running programs
            time.sleep(0.1)
            msg = self.working_serial_readall()
            if msg[-6:] == b'\r\n>>> ':
                if verbose:
                    self.sres('repl is in normal command mode\n')
                    self.sres('[\\r\\x03\\x03] ')
                    self.sres(str(msg))
            else:
                if verbose:
                    self.sres('normal repl mode not detected ')
                    self.sres(str(msg))
                    self.sres('\nnot command mode\n')

            # self.working_serial.write(b'\r\x02')
            # ctrl-B: leave paste mode if still in it <-- doesn't work as when not in paste mode it reboots the device

            working_device_write(b'\r\x01')
            # ctrl-A: enter raw REPL
            time.sleep(0.1)
            msg = self.working_serial_readall()
            if verbose and msg:
                self.sres('\n[\\r\\x01] ')
                self.sres(str(msg))
            working_device_write(b'1\x04')
            # single character program to run so receive stream works
        else:
            self.working_socket.write(b'1\x04')
            # single character program "1" to run so receive stream works

        return self.receive_stream(seek_okay=True, warn_okay_priors=False, five_second_timeout=True)

    def exit_paste_mode(self, verbose):  # try to make it clean
        if self.working_serial or self.working_websocket:
            working_device_write = self.working_serial.write if self.working_serial else self.working_websocket.send
            try:
                working_device_write(b'\r\x03\x02')  # ctrl-C; ctrl-B to exit paste mode
                time.sleep(0.1)
                msg = self.working_serial_readall()
            except serial.SerialException as e:
                self.sres("serial exception on close {}\n".format(str(e)))
                return

            if verbose:
                self.sres_sys('attempt to exit paste mode\n')
                self.sres_sys('[\\r\\x03\\x02] ')
                self.sres(str(msg))

    def write_bytes(self, bytes_to_send):
        if self.working_serial:
            working_serial_written = self.working_serial.write(bytes_to_send)
            return ("serial.write {} bytes to {} at baudrate {}\n"
                    .format(working_serial_written, self.working_serial.port, self.working_serial.baudrate))
        elif self.working_websocket:
            working_websocket_written = self.working_websocket.send(bytes_to_send)
            return "serial.write {} bytes to {}\n".format(working_websocket_written, "websocket")
        else:
            working_socket_written = self.working_socket.write(bytes_to_send)
            return "serial.write {} bytes to {}\n".format(working_socket_written, str(self.working_socket))

    # def terminate_running(self):
    #     self.write_bytes(b"\x03\x03")
    #     self.sres(str(self.working_serial_readall()))
    #     return None
    def send_reboot_message(self):
        if self.working_serial:
            self.working_serial.write(b"\x03\r")  # quit any running program
            self.working_serial.write(b"\x02\r")  # exit the paste mode with ctrl-B
            self.working_serial.write(b"\x04\r")  # soft reboot code
        elif self.working_websocket:
            self.working_websocket.send(b"\x03\r")  # quit any running program
            self.working_websocket.send(b"\x02\r")  # exit the paste mode with ctrl-B
            self.working_websocket.send(b"\x04\r")  # soft reboot code

    def write_line(self, line):
        if self.working_serial:
            self.working_serial.write(line.encode("utf8"))
            self.working_serial.write(b'\r\n')
        elif self.working_websocket:
            self.working_websocket.send(line.encode("utf8"))
            self.working_websocket.send(b'\r\n')
        else:
            self.working_socket.write(line.encode("utf8"))
            self.working_socket.write(b'\r\n')

    def serial_exists(self):
        return self.working_serial or self.working_socket or self.working_websocket
