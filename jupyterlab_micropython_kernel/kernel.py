# use of argparse for handling the %commands in the cells
import argparse
import logging
import os
import re
import shlex
import time
import nbconvert
import nbformat
import websocket  # only for WebSocketConnectionClosedException
from ipykernel.kernelbase import Kernel

from . import deviceconnector

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ap_serial_connect = argparse.ArgumentParser(prog="%serialconnect", add_help=False)
ap_serial_connect.add_argument('--raw', help='Just open connection', action='store_true')
ap_serial_connect.add_argument('--port', type=str, default=0)
ap_serial_connect.add_argument('--baud', type=int, default=115200)
ap_serial_connect.add_argument('--verbose', action='store_true')
ap_serial_connect.add_argument('--clear', '-c', help='soft reboot after connected', action='store_true')

ap_socket_connect = argparse.ArgumentParser(prog="%socketconnect", add_help=False)
ap_socket_connect.add_argument('--raw', help='Just open connection', action='store_true')
ap_socket_connect.add_argument('ipnumber', type=str)
ap_socket_connect.add_argument('portnumber', type=int)

ap_disconnect = argparse.ArgumentParser(prog="%disconnect", add_help=False)
ap_disconnect.add_argument('--raw', help='Close connection without exiting paste mode', action='store_true')

ap_websocket_connect = argparse.ArgumentParser(prog="%websocketconnect", add_help=False)
ap_websocket_connect.add_argument('--raw', help='Just open connection', action='store_true')
ap_websocket_connect.add_argument('websocketurl', type=str, default="ws://192.168.4.1:8266", nargs="?")
ap_websocket_connect.add_argument("--password", type=str)
ap_websocket_connect.add_argument('--verbose', action='store_true')

ap_write_bytes = argparse.ArgumentParser(prog="%writebytes", add_help=False)
ap_write_bytes.add_argument('--binary', '-b', action='store_true')
ap_write_bytes.add_argument('--verbose', '-v', action='store_true')
ap_write_bytes.add_argument('stringtosend', type=str)

ap_read_bytes = argparse.ArgumentParser(prog="%readbytes", add_help=False)
ap_read_bytes.add_argument('--binary', '-b', action='store_true')

ap_send_to_file = argparse.ArgumentParser(prog="%sendfile",
                                          description="send a file to the microcontroller's file system",
                                          add_help=False)
ap_send_to_file.add_argument('--append', '-a', action='store_true')
ap_send_to_file.add_argument('--mkdir', '-d', action='store_true')
ap_send_to_file.add_argument('--binary', '-b', action='store_true')
ap_send_to_file.add_argument('--execute', '-x', action='store_true')
ap_send_to_file.add_argument('--source', help="source file", type=str, default="<<cellcontents>>", nargs="?")
ap_send_to_file.add_argument('--quiet', '-q', action='store_true')
ap_send_to_file.add_argument('--QUIET', '-Q', action='store_true')
ap_send_to_file.add_argument('destinationfilename', type=str, nargs="?")

ap_upload_main = argparse.ArgumentParser(prog="%uploadmain",
                                         description="upload file(.py/.ipynb) as 'main.py' to the microcontroller's "
                                                     "file system",
                                         add_help=False)
ap_upload_main.add_argument('--source', help='source file(.py/.ipynb)', type=str)
ap_upload_main.add_argument('--reboot', '-r', help='hard reset after uploaded', action='store_true')

ap_upload_project = argparse.ArgumentParser(prog="%uploadproject",
                                            description="upload all files in the specified folder to the"
                                                        " microcontroller's file system"
                                                        " while convert all .ipynb files to .py files")
ap_upload_project.add_argument('--source', help='project source directory', type=str, default=".")
ap_upload_project.add_argument('--reboot', '-r', help='hard reset after uploaded', action='store_true')
ap_upload_project.add_argument('--emptydevice', '-e', help='empty device before uploaded', action='store_true')
ap_upload_project.add_argument('--onlypy', '-py', help='Only upload all .py and .ipynb files', action='store_true')

ap_ls = argparse.ArgumentParser(prog="%ls", description="list directory of the microcontroller's file system",
                                add_help=False)
ap_ls.add_argument('--recurse', '-r', action='store_true')
ap_ls.add_argument('dirname', type=str, nargs="?")

ap_meminfo = argparse.ArgumentParser(prog="%meminfo", add_help=False)

ap_remove = argparse.ArgumentParser(prog="%remove",
                                    description="remove a file of the microcontroller's file system",
                                    add_help=False)
ap_remove.add_argument('filename', type=str)

ap_rmdir = argparse.ArgumentParser(prog="%rmdir",
                                   description="remove a directory of the microcontroller's file system",
                                   add_help=False)
ap_rmdir.add_argument('directory', type=str)

ap_fetch_file = argparse.ArgumentParser(prog="%fetchfile",
                                        description="fetch a file from the microcontroller's file system",
                                        add_help=False)
ap_fetch_file.add_argument('--binary', '-b', action='store_true')
ap_fetch_file.add_argument('--print', '-p', action="store_true")
ap_fetch_file.add_argument('--load', '-l', action="store_true")
ap_fetch_file.add_argument('--quiet', '-q', action='store_true')
ap_fetch_file.add_argument('--QUIET', '-Q', action='store_true')
ap_fetch_file.add_argument('sourcefilename', type=str)
ap_fetch_file.add_argument('destinationfilename', type=str, nargs="?")

ap_mpycross = argparse.ArgumentParser(prog="%mpy-cross", add_help=False)
ap_mpycross.add_argument('--set-exe', type=str)
ap_mpycross.add_argument('pyfile', type=str, nargs="?")

ap_esptool = argparse.ArgumentParser(prog="%esptool", add_help=False)
ap_esptool.add_argument('--port', type=str, default=0)
ap_esptool.add_argument('espcommand', choices=['erase', 'esp32', 'esp8266'])
ap_esptool.add_argument('binfile', type=str, nargs="?")

ap_capture = argparse.ArgumentParser(prog="%capture", description="capture output printed by device and save to a file",
                                     add_help=False)
ap_capture.add_argument('--quiet', '-q', action='store_true')
ap_capture.add_argument('--QUIET', '-Q', action='store_true')
ap_capture.add_argument('outputfilename', type=str)

ap_write_file_pc = argparse.ArgumentParser(prog="%%writefile", description="write contents of cell to file on PC",
                                           add_help=False)
ap_write_file_pc.add_argument('--append', '-a', action='store_true')
ap_write_file_pc.add_argument('--execute', '-x', action='store_true')
ap_write_file_pc.add_argument('destinationfilename', type=str)


def parse_ap(ap, args1):
    try:
        return ap.parse_known_args(args1)[0]
    except SystemExit:
        # argparse throws these because it assumes you only want to do the command line
        # should be a default one
        return None


class MicroPythonKernel(Kernel):
    def do_apply(self, content, bufs, msg_id, reply_metadata):
        pass

    def do_clear(self):
        pass

    implementation = 'micropython_kernel'
    implementation_version = "v3"

    banner = "MicroPython Serializer"

    language_info = {'name': 'micropython',
                     'codemirror_mode': 'python',
                     'mimetype': 'text/python',
                     'file_extension': '.py'}

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self.silent = False
        self.dc = deviceconnector.DeviceConnector(self.sres, self.sres_system)
        self.mpycrossexe = None

        self.srescapturemode = 0
        # 0 none, 1 print lines, 2 print on-going line count (--quiet), 3 print only final line count (--QUIET)
        self.srescapturedoutputfile = None  # used by %capture command
        self.srescapturedlinecount = 0
        self.srescapturedlasttime = 0  # to control the frequency of capturing reported

    def interpret_percent_line(self, percent_line, cell_contents):
        try:
            percentstringargs = shlex.split(percent_line)
        except ValueError as e:
            self.sres("\n\n***Bad percentcommand [%s]\n" % str(e), 31)
            self.sres(percent_line)
            return None

        percentcommand = percentstringargs[0]

        if percentcommand == ap_serial_connect.prog:
            apargs = parse_ap(ap_serial_connect, percentstringargs[1:])

            self.dc.disconnect(apargs.verbose)
            self.dc.serial_connect(apargs.port, apargs.baud, apargs.verbose)
            if self.dc.working_serial:
                if not apargs.raw:
                    if self.dc.enter_paste_mode(verbose=apargs.verbose):
                        if apargs.clear:
                            self.dc.send_reboot_message()
                            self.dc.enter_paste_mode()
                        self.sres_system("\nReady.\n")
                    else:
                        self.sres("Disconnecting [paste mode not working]\n", 31)
                        self.dc.disconnect(verbose=apargs.verbose)
                        self.sres_system("  (You may need to reset the device)")
                        cell_contents = ""
            else:
                cell_contents = ""
            return cell_contents.strip() and cell_contents or None

        if percentcommand == ap_websocket_connect.prog:
            apargs = parse_ap(ap_websocket_connect, percentstringargs[1:])
            if apargs.password is None and not apargs.raw:
                self.sres(ap_websocket_connect.format_help())
                return None
            self.dc.websocket_connect(apargs.websocketurl)
            if self.dc.working_websocket:
                self.sres_system("** WebSocket connected **\n")
                if not apargs.raw:
                    pline = self.dc.working_websocket.recv()
                    self.sres(pline)
                    if pline == 'Password: ' and apargs.password is not None:
                        self.dc.working_websocket.send(apargs.password)
                        self.dc.working_websocket.send("\r\n")
                        res = self.dc.working_serial_readall()
                        self.sres(res)  # '\r\nWebREPL connected\r\n>>> '
                        if not apargs.raw:
                            if self.dc.enter_paste_mode(apargs.verbose):
                                self.sres_system("Ready.\n")
                            else:
                                self.sres("Disconnecting [paste mode not working]\n", 31)
                                self.dc.disconnect(verbose=apargs.verbose)
                                self.sres("  (You may need to reset the device)")
                                cell_contents = ""
            else:
                cell_contents = ""
            return cell_contents.strip() and cell_contents or None

        # this is the direct socket kind, not attached to a webrepl
        if percentcommand == ap_socket_connect.prog:
            apargs = parse_ap(ap_socket_connect, percentstringargs[1:])
            self.dc.socket_connect(apargs.ipnumber, apargs.portnumber)
            if self.dc.working_socket:
                self.sres("\n ** Socket connected **\n\n", 32)
                if apargs.verbose:
                    self.sres(str(self.dc.working_socket))
                self.sres("\n")
                # if not apargs.raw:
                #    self.dc.enterpastemode()
            return cell_contents.strip() and cell_contents or None

        if percentcommand == ap_esptool.prog:
            apargs = parse_ap(ap_esptool, percentstringargs[1:])
            if apargs and (apargs.espcommand == "erase" or apargs.binfile):
                self.dc.esptool(apargs.espcommand, apargs.port, apargs.binfile)
            else:
                self.sres(ap_esptool.format_help())
                self.sres("Please download the bin file from https://micropython.org/download/#{}".format(
                    apargs.espcommand if apargs else ""))
            return cell_contents.strip() and cell_contents or None

        if percentcommand == ap_write_file_pc.prog:
            apargs = parse_ap(ap_write_file_pc, percentstringargs[1:])
            if apargs:
                if apargs.append:
                    self.sres("Appending to {}\n\n".format(apargs.destinationfilename), asciigraphicscode=32)
                    file_out = open(apargs.destinationfilename, "a")
                    file_out.write("\n")
                else:
                    self.sres("Writing {}\n\n".format(apargs.destinationfilename), asciigraphicscode=32)
                    file_out = open(apargs.destinationfilename, "w")

                file_out.write(cell_contents)
                file_out.close()
            else:
                self.sres(ap_write_file_pc.format_help())
            if not apargs.execute:
                return None
            return cell_contents  # should add in some blank lines at top to get errors right

        if percentcommand == "%mpy-cross":
            apargs = parse_ap(ap_mpycross, percentstringargs[1:])
            if apargs and apargs.set_exe:
                self.mpycrossexe = apargs.set_exe
            elif apargs.pyfile:
                if self.mpycrossexe:
                    self.dc.mpycross(self.mpycrossexe, apargs.pyfile)
                else:
                    self.sres("Cross compiler executable not yet set\n", 31)
                    self.sres(
                        "try: %mpy-cross --set-exe ~/extrepositories/micropython/mpy-cross/mpy-cross\n")
                if self.mpycrossexe:
                    self.mpycrossexe = "~/extrepositories/micropython/mpy-cross/mpy-cross"
            else:
                self.sres(ap_mpycross.format_help())
            return cell_contents.strip() and cell_contents or None

        if percentcommand == "%comment":
            self.sres(" ".join(percentstringargs[1:]), asciigraphicscode=32)
            return cell_contents.strip() and cell_contents or None

        if percentcommand == "%lsmagic":
            self.sres(re.sub("usage: ", "", ap_serial_connect.format_usage()))
            self.sres("    connects to a device over USB wire\n\n")
            self.sres(re.sub("usage: ", "", ap_socket_connect.format_usage()))
            self.sres("    connects to a socket of a device over wifi\n\n")
            self.sres("%suppressendcode\n    doesn't send x04 or wait to read after sending the contents of the cell\n")
            self.sres("  (assists for debugging using %writebytes and %readbytes)\n\n")
            self.sres(re.sub("usage: ", "", ap_websocket_connect.format_usage()))
            self.sres("    connects to the webREPL websocket of an ESP8266 over wifi\n")
            self.sres("    websocketurl defaults to ws://192.168.4.1:8266 but be sure to be connected\n\n")
            self.sres(re.sub("usage: ", "", ap_disconnect.format_usage()))
            self.sres("    disconnects from web/serial connection\n\n")

            self.sres("%rebootdevice\n    reboots device\n\n")
            self.sres("%hardreset\n    A hard reset is the same as performing a power cycle to the board. \n\n")
            self.sres(re.sub("usage: ", "", ap_ls.format_usage()))
            self.sres("    list files on the device\n\n")
            self.sres(re.sub("usage: ", "", ap_meminfo.format_usage()))
            self.sres("    show RAM size/used/free/use% info\n\n")
            self.sres(re.sub("usage: ", "", ap_read_bytes.format_usage()))
            self.sres("    does serial.read_all()\n\n")
            self.sres(re.sub("usage: ", "", ap_write_bytes.format_usage()))
            self.sres("    does serial.write() of the python quoted string given\n\n")

            self.sres(re.sub("usage: ", "", ap_write_file_pc.format_usage()))
            self.sres("    write contents of cell to a file\n\n")
            self.sres(re.sub("usage: ", "", ap_remove.format_usage()))
            self.sres("    remove file on the device\n\n")
            self.sres(re.sub("usage: ", "", ap_rmdir.format_usage()))
            self.sres("    remove directory on the device\n\n")
            self.sres(re.sub("usage: ", "", ap_send_to_file.format_usage()))
            self.sres("    send cell contents or file/direcectory to the device\n\n")
            self.sres(re.sub("usage: ", "", ap_upload_main.format_usage()))
            self.sres("    convert a .py or .ipynb file to a main.py and upload it\n\n")
            self.sres((re.sub("usage:", "", ap_upload_project.format_usage())))
            self.sres("    upload all files in the specified folder to the microcontroller's file system"
                      " while convert all .ipynb files to .py files\n\n")
            self.sres(re.sub("usage: ", "", ap_fetch_file.format_usage()))
            self.sres("    fetch and save a file from the device\n\n")

            self.sres(re.sub("usage: ", "", ap_esptool.format_usage()))
            self.sres("    commands for flashing your esp-device\n\n")
            self.sres(re.sub("usage: ", "", ap_capture.format_usage()))
            self.sres("    records output to a file\n\n")
            self.sres("%comment\n    print this into output\n\n")
            self.sres(re.sub("usage: ", "", ap_mpycross.format_usage()))
            self.sres("    cross-compile a .py file to a .mpy file\n\n")
            self.sres("%lsmagic\n    list magic commands\n\n")

            return None

        if percentcommand == ap_disconnect.prog:
            apargs = parse_ap(ap_disconnect, percentstringargs[1:])
            self.dc.disconnect(raw=apargs.raw, verbose=True)
            return None

        # remaining commands require a connection
        if not self.dc.serial_exists():
            return cell_contents

        if percentcommand == ap_capture.prog:
            apargs = parse_ap(ap_capture, percentstringargs[1:])
            if apargs:
                self.sres("Writing output to file {}\n\n".format(apargs.outputfilename), asciigraphicscode=32)
                self.srescapturedoutputfile = open(apargs.outputfilename, "w")
                self.srescapturemode = (3 if apargs.QUIET else (2 if apargs.quiet else 1))
                self.srescapturedlinecount = 0
            else:
                self.sres(ap_capture.format_help())
            return cell_contents

        if percentcommand == ap_write_bytes.prog:
            # (not effectively using the --binary setting)
            apargs = parse_ap(ap_write_bytes, percentstringargs[1:])
            if apargs:
                byte_sto_send = apargs.stringtosend.encode().decode("unicode_escape").encode()
                res = self.dc.write_bytes(byte_sto_send)
                if apargs.verbose:
                    self.sres(res, asciigraphicscode=34)
            else:
                self.sres(ap_write_bytes.format_help())
            return cell_contents.strip() and cell_contents or None

        if percentcommand == ap_read_bytes.prog:
            # (not effectively using the --binary setting)
            apargs = parse_ap(ap_read_bytes, percentstringargs[1:])
            time.sleep(
                0.1)  # just give it a moment if running on from a series of values (could use an --expect keyword)
            msg = self.dc.working_serial_readall()
            if apargs.binary:
                self.sres(repr(msg))
            elif type(msg) == bytes:
                self.sres(msg.decode(errors="ignore"))
            else:
                self.sres(msg)  # strings come back from webrepl
            return cell_contents.strip() and cell_contents or None

        if percentcommand == "%rebootdevice":
            self.dc.send_reboot_message()
            self.dc.enter_paste_mode()
            return cell_contents.strip() and cell_contents or None

        if percentcommand == "%hardreset":
            self.dc.send_hard_reset_message()
            self.dc.enter_paste_mode()
            return cell_contents.strip() and cell_contents or None

        if percentcommand == "%reboot":
            self.sres("Did you mean %rebootdevice or %hardreset?\n", 31)
            return None

        if percentcommand == "%%writetofile" or percentcommand == "%writefile":
            self.sres("Did you mean %%writefile?\n", 31)
            return None

        if percentcommand == "%serialdisconnect":
            self.sres("Did you mean %disconnect?\n", 31)
            return None

        if percentcommand == "%sendbytes":
            self.sres("Did you mean %writebytes?\n", 31)
            return None

        if percentcommand == "%reboot":
            self.sres("Did you mean %rebootdevice?\n", 31)
            return None

        if percentcommand in ("%savetofile", "%savefile", "%send_file"):
            self.sres("Did you mean to write %sendfile?\n", 31)
            return None

        if percentcommand in ("%readfile", "%fetchfromfile"):
            self.sres("Did you mean to write %fetchfile?\n", 31)
            return None

        if percentcommand == ap_fetch_file.prog:
            apargs = parse_ap(ap_fetch_file, percentstringargs[1:])
            if apargs:
                fetchedcontents = self.dc.fetch_file(apargs.sourcefilename, apargs.binary, apargs.quiet)
                if apargs.print:
                    self.sres(fetchedcontents.decode() if type(fetchedcontents) == bytes else fetchedcontents,
                              clear_output=True)

                if (apargs.destinationfilename or (not apargs.print and not apargs.load)) and fetchedcontents:
                    dst_file = apargs.destinationfilename or os.path.basename(apargs.sourcefilename)
                    self.sres("Saving file to {}".format(repr(dst_file)))
                    file_out = open(dst_file, "wb" if apargs.binary else "w")
                    file_out.write(fetchedcontents)
                    file_out.close()

                if apargs.load:
                    file_contents = fetchedcontents.decode() if type(fetchedcontents) == bytes else fetchedcontents
                    if not apargs.quiet:
                        file_contents = "#%s\n\n%s" % (" ".join(percentstringargs), file_contents)
                    set_next_input_payload = {"source": "set_next_input", "text": file_contents, "replace": True}
                    return set_next_input_payload

            else:
                self.sres(ap_fetch_file.format_help())
            return None

        if percentcommand == ap_ls.prog:
            apargs = parse_ap(ap_ls, percentstringargs[1:])
            if apargs:
                self.dc.listdir(apargs.dirname or "", apargs.recurse)
            else:
                self.sres(ap_ls.format_help())
            return None

        if percentcommand == ap_meminfo.prog:
            apargs = parse_ap(ap_meminfo, percentstringargs[1:])
            if apargs:
                self.dc.mem_info()
            else:
                self.sres(ap_meminfo.format_help())
            return None

        if percentcommand == ap_remove.prog:
            apargs = parse_ap(ap_remove, percentstringargs[1:])
            if apargs:
                self.dc.remove_file(apargs.filename or "")
            else:
                self.sres(ap_remove.format_help())
            return None

        if percentcommand == ap_rmdir.prog:
            apargs = parse_ap(ap_rmdir, percentstringargs[1:])
            if apargs:
                self.dc.remove_dir(apargs.directory or "main.py")
            else:
                self.sres(ap_rmdir.format_help())
            return None

        if percentcommand == ap_send_to_file.prog:
            apargs = parse_ap(ap_send_to_file, percentstringargs[1:])
            if apargs and not (apargs.source == "<<cellcontents>>" and not apargs.destinationfilename) and (
                    apargs.source is not None):

                dest_file_name = apargs.destinationfilename

                def send_to_file(filename, contents):
                    self.dc.send_to_file(filename, apargs.mkdir, apargs.append, apargs.binary, apargs.quiet, contents)
                    self.dc.send_hard_reset_message()

                if apargs.source == "<<cellcontents>>":
                    file_contents = cell_contents
                    if not apargs.execute:
                        cell_contents = None
                    send_to_file(dest_file_name, file_contents)

                else:
                    mode = "rb" if apargs.binary else "r"
                    if not dest_file_name:
                        dest_file_name = os.path.basename(apargs.source)
                    elif dest_file_name[-1] == "/":
                        dest_file_name += os.path.basename(apargs.source)

                    if os.path.isfile(apargs.source):
                        file_contents = open(apargs.source, mode).read()
                        if apargs.execute:
                            self.sres("Cannot execute sourced file\n", 31)
                        send_to_file(dest_file_name, file_contents)

                    elif os.path.isdir(apargs.source):
                        if apargs.execute:
                            self.sres("Cannot execute folder\n", 31)
                        for root, dirs, files in os.walk(apargs.source):
                            for fn in files:
                                skip = False
                                fp = os.path.join(root, fn)
                                real_path = os.path.relpath(fp, apargs.source)
                                if real_path.endswith('.py'):
                                    # Check for compiled copy, skip py if exists
                                    if os.path.exists(fp[:-3] + '.mpy'):
                                        skip = True
                                if not skip:
                                    dest_path = os.path.join(dest_file_name, real_path).replace('\\', '/')
                                    file_contents = open(os.path.join(root, fn), mode).read()
                                    send_to_file(dest_path, file_contents)
            else:
                self.sres(ap_send_to_file.format_help())
            return cell_contents  # allows for repeat %send_to_file in same cell
        if percentcommand == ap_upload_main.prog:
            apargs = parse_ap(ap_upload_main, percentstringargs[1:])
            if apargs:
                source = apargs.source if apargs.source else "main.ipynb"
                if (not source.endswith(".py")) and (not source.endswith(".ipynb")):
                    self.sres("you must choose a .py or .ipynb file")
                    return None
                self.upload_file(source)
                if apargs.reboot:
                    self.dc.send_hard_reset_message()
                    self.dc.enter_paste_mode()
                    return cell_contents.strip() and cell_contents or None
            else:
                self.sres(ap_upload_main.format_help())
            return None
        if percentcommand == ap_upload_project.prog:
            apargs = parse_ap(ap_upload_project, percentstringargs[1:])
            if apargs:
                if not os.path.isdir(apargs.source):
                    self.sres("source: {0} is not a directory, you can upload main.py by '%upload main --source '"
                              .format(apargs.source))
                    self.sres(ap_upload_project.format_help())
                    return None
                if apargs.emptydevice:
                    self.dc.remove_dir(".")
                self.upload_dir(apargs.source, apargs.onlypy)
                if apargs.reboot:
                    self.dc.send_hard_reset_message()
                    self.dc.enter_paste_mode()
                    return cell_contents.strip() and cell_contents or None
            else:
                self.sres(ap_upload_project.format_help())
                self.sres(ap_upload_project.format_help())
            return None
        self.sres("Unrecognized percentline {}\n".format([percent_line]), 31)
        return cell_contents

    def upload_file(self, source, mkdir=False, append=False, binary=False, quiet=True, root=""):
        if os.path.exists(source) and os.path.isfile(source):
            destination = source
            root_len = len(root)
            if root != "" and root_len+1 < len(source) and source[:root_len] == root:
                destination = destination[root_len+1:]
            if destination.endswith(".ipynb"):
                notebook = nbformat.read(source, as_version=4)
                py_exporter = nbconvert.PythonExporter()

                output, resources = py_exporter.from_notebook_node(notebook)
                file_contents = output.replace("get_ipython().run_line_magic", "# %")
                destination = destination.replace(".ipynb", ".py")
            else:
                file_contents = open(source, "r").read()
            self.sres("\n\nuploading '{0}'\n".format(destination))
            self.dc.send_to_file(destination, mkdir=mkdir, append=append, binary=binary,
                                 quiet=quiet, file_contents=file_contents)
        else:
            self.sres("'{0}' is not a file\n\n".format(source))

    def upload_dir(self, source, onlypy):
        if os.path.exists(source) and os.path.isdir(source):
            for root, dirs, files in os.walk(source, topdown=False):
                if onlypy:
                    files = [f for f in files if (not f[0] == '.' ) and ("/." not in root) and (f.endswith('.py') or f.endswith('.ipynb'))]
                else:
                    files = [f for f in files if (not f[0] == '.') and ("/." not in root)]
                for f in files:
                    self.upload_file(os.path.join(root, f), mkdir=True, binary=f.endswith(".mpy"), root=source)
        else:
            self.sres("'{0}' is not a directory\n\n".format(source))

    def run_normal_cell(self, cell_contents, bsuppressendcode):
        cmd_lines = cell_contents.splitlines(True)
        r = self.dc.working_serial_readall()
        if r:
            self.sres('[priorstuff] ')
            self.sres(str(r))

        for line in cmd_lines:
            if line:
                if line[-2:] == '\r\n':
                    line = line[:-2]
                elif line[-1] == '\n':
                    line = line[:-1]
                self.dc.write_line(line)
                r = self.dc.working_serial_readall()
                if r:
                    self.sres('[duringwriting] ')
                    self.sres(str(r))

        if not bsuppressendcode:
            self.dc.write_bytes(b'\r\x04')
            self.dc.receive_stream(seek_okay=True)

    def send_command(self, cell_contents):
        bsuppressendcode = False  # can't yet see how to get this signal through

        if self.srescapturedoutputfile:
            self.srescapturedoutputfile.close()  # shouldn't normally get here
            self.sres("closing stuck open srescapturedoutputfile\n")
            self.srescapturedoutputfile = None

        # extract any %-commands we have here at the start (or ending?),
        # tolerating pure comment lines and white space before the first %
        # (if there's no %-command in there, then no lines at the front get dropped due to being comments)

        while True:
            match_per_cent_line = re.match("(?:(?:\s*|(?:\s*#.*\n))*)(%.*)\n?(?:[ \r]*\n)?", cell_contents)
            if not match_per_cent_line:
                break
            cell_contents = self.interpret_percent_line(match_per_cent_line.group(1),
                                                        cell_contents[match_per_cent_line.end():])
            # discards the %command and a single blank line (if there is one) from the cell contents
            if isinstance(cell_contents, dict) and cell_contents.get("source") == "set_next_input":
                return cell_contents  # set_next_input_payload:
            if cell_contents is None:
                return None

        if not self.dc.serial_exists():
            self.sres("No serial connected\n", 31)
            self.sres("  %serialconnect to connect\n")
            self.sres("  %esptool to flash the device\n")
            self.sres("  %lsmagic to list commands")
            return None

        # run the cell contents as normal
        if cell_contents:
            self.run_normal_cell(cell_contents, bsuppressendcode)
        return None

    def sres_system(self, output, clear_output=False):  # system call
        self.sres(output, asciigraphicscode=34, clear_output=clear_output)

    # 1=bold, 31=red, 32=green, 34=blue; from http://ascii-table.com/ansi-escape-sequences.php
    def sres(self, output, asciigraphicscode=None, n04count=0, clear_output=False):
        if self.silent:
            return

        if self.srescapturedoutputfile and (n04count == 0) and not asciigraphicscode:
            self.srescapturedoutputfile.write(output)
            self.srescapturedlinecount += len(output.split("\n")) - 1
            if self.srescapturemode == 3:
                # 0 none, 1 print lines, 2 print on-going line count (--quiet), 3 print only final line count (--QUIET)
                return

            # changes the printing out to a lines captured statement every 1second.  
            if self.srescapturemode == 2:  # (allow stderrors to drop through to normal printing
                srescapturedtime = time.time()
                if srescapturedtime < self.srescapturedlasttime + 1:  # update no more frequently than once a second
                    return
                self.srescapturedlasttime = srescapturedtime
                clear_output = True
                output = "{} lines captured".format(self.srescapturedlinecount)

        if clear_output:  # used when updating lines printed
            self.send_response(self.iopub_socket, 'clear_output', {"wait": True})
        if asciigraphicscode:
            output = "\x1b[{}m{}\x1b[0m".format(asciigraphicscode, output)
        stream_content = {'name': ("stdout" if n04count == 0 else "stderr"), 'text': output}
        self.send_response(self.iopub_socket, 'stream', stream_content)

    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        self.silent = silent
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count, 'payload': [], 'user_expressions': {}}

        interrupted = False

        # clear buffer out before executing any commands (except the readbytes one)
        if self.dc.serial_exists() and not re.match(
                "\s*%readbytes|\s*%disconnect|\s*%serialconnect|\s*websocketconnect",
                code):
            prior_buffer = None
            try:
                prior_buffer = self.dc.working_serial_readall()
            except KeyboardInterrupt:
                interrupted = True
            except OSError as e:
                prior_buffer = []
                self.sres("\n\n***Connection broken [%s]\n" % str(e.strerror), 31)
                self.sres("You may need to reconnect")
                self.dc.disconnect(raw=True, verbose=True)

            except websocket.WebSocketConnectionClosedException as e:
                prior_buffer = []
                self.sres("\n\n***Websocket connection broken [%s]\n" % str(e), 31)
                self.sres("You may need to reconnect")
                self.dc.disconnect(raw=True, verbose=True)

            if prior_buffer:
                if type(prior_buffer) == bytes:
                    try:
                        prior_buffer = prior_buffer.decode()
                    except UnicodeDecodeError:
                        prior_buffer = str(prior_buffer)

                for pbline in prior_buffer.splitlines():
                    if deviceconnector.wifiMessageIgnore.match(pbline):
                        continue  # filter out boring wifi status messages
                    if pbline:
                        self.sres('[leftinbuffer] ')
                        self.sres(str([pbline]))
                        self.sres('\n')

        set_next_input_payload = None
        try:
            if not interrupted:
                set_next_input_payload = self.send_command(code)
        except KeyboardInterrupt:
            interrupted = True
        except OSError as e:
            self.sres("\n\n***OSError [%s]\n\n" % str(e.strerror))
        # except pexpect.EOF:
        #    self.sres(self.asyncmodule.before + 'Restarting Bash')
        #    self.startasyncmodule()

        if self.srescapturedoutputfile:
            if self.srescapturemode == 2:
                self.send_response(self.iopub_socket, 'clear_output', {"wait": True})
            if self.srescapturemode == 2 or self.srescapturemode == 3:
                output = "{} lines captured.".format(
                    self.srescapturedlinecount)  # finish off by updating with the correct number captured
                stream_content = {'name': "stdout", 'text': output}
                self.send_response(self.iopub_socket, 'stream', stream_content)

            self.srescapturedoutputfile.close()
            self.srescapturedoutputfile = None
            self.srescapturemode = 0

        if interrupted:
            self.sres_system("\n\n*** Sending Ctrl-C\n\n")
            if self.dc.serial_exists():
                self.dc.write_bytes(b'\r\x03')
                # interrupted = True
                try:
                    self.dc.receive_stream(seek_okay=False, warn_okay_priors=True)
                except KeyboardInterrupt:
                    self.sres("\n\nKeyboard interrupt while waiting response on Ctrl-C\n\n")
                except OSError as e:
                    self.sres("\n\n***OSError while issuing a Ctrl-C [%s]\n\n" % str(e.strerror))
            return {'status': 'abort', 'execution_count': self.execution_count}

        # everything already gone out with send_response(), but could detect errors (text between the two \x04s

        payload = [set_next_input_payload] if set_next_input_payload else []
        # {"source": "set_next_input", "text": "some cell content", "replace": False}
        return {'status': 'ok', 'execution_count': self.execution_count, 'payload': payload, 'user_expressions': {}}
